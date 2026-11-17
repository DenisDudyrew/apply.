"""Build a signed standalone APK. Signing keys remain local and are never staged."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from prepare_android import main as stage

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--gradle', default=str(ROOT / 'android/gradlew'))
    parser.add_argument('--generate-key', action='store_true')
    args = parser.parse_args()
    env = dict(os.environ)
    key_dir = ROOT / '.build/android-signing'
    credentials = key_dir / 'credentials.json'
    if args.generate_key and not credentials.exists():
        key_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        key_dir.chmod(0o700)
        key_file = key_dir / 'apply.jks'
        if key_file.exists():
            raise SystemExit('Signing key already exists; recover its password before continuing.')
        password = secrets.token_urlsafe(40)
        key_env = dict(env, APPLY_GENERATED_KEY_PASSWORD=password)
        subprocess.run(['keytool', '-genkeypair', '-keystore', str(key_file), '-alias', 'apply',
            '-keyalg', 'RSA', '-keysize', '3072', '-validity', '10000', '-dname', 'CN=Apply',
            '-storetype', 'PKCS12', '-storepass:env', 'APPLY_GENERATED_KEY_PASSWORD',
            '-keypass:env', 'APPLY_GENERATED_KEY_PASSWORD'], env=key_env, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        key_file.chmod(0o600)
        fd = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'password': password, 'alias': 'apply'}, stream)
        print('Created local signing key. Back up .build/android-signing securely; future updates require it.')
    if credentials.exists() and not env.get('APPLY_ANDROID_KEYSTORE'):
        data = json.loads(credentials.read_text())
        env.update(APPLY_ANDROID_KEYSTORE=str(key_dir / 'apply.jks'), APPLY_ANDROID_STORE_PASSWORD=data['password'],
                   APPLY_ANDROID_KEY_PASSWORD=data['password'], APPLY_ANDROID_KEY_ALIAS=data['alias'])
    if not env.get('APPLY_ANDROID_KEYSTORE'):
        raise SystemExit('Provide Android signing environment variables, or use --generate-key for the first local build.')
    subprocess.run(['npm', 'run', 'build', '--prefix', str(ROOT / 'frontend')], check=True)
    stage()
    subprocess.run([args.gradle, '-p', str(ROOT / 'android'), ':app:assembleRelease', '--console=plain'], env=env, check=True)
    version = json.loads((ROOT / 'frontend/package.json').read_text())['version']
    output = ROOT / 'release' / f'Apply-{version}-Android.apk'
    output.parent.mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'android/app/build/outputs/apk/release/app-release.apk', output)
    print('Signed Android APK:', output)


if __name__ == '__main__':
    main()
