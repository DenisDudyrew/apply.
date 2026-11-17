"""Stage only public engine sources and UI assets for the standalone Android app."""
from pathlib import Path
import shutil
ROOT = Path(__file__).resolve().parents[1]
PUBLIC_MODULES = ('app_paths.py', 'hh_auth.py', 'hh_apply.py', 'api_apply.py', 'captcha_gate.py',
                  'ui.py', 'queue_store.py', 'profiles.py', 'file_lock.py', 'secret_store.py', 'repository.py')


def main():
    target = ROOT / '.build' / 'android-python'
    assets = ROOT / '.build' / 'android-assets'
    if not (ROOT / 'frontend/dist/index.html').is_file():
        raise SystemExit('Build the frontend before staging Android assets.')
    for directory in (target, assets):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
    for name in PUBLIC_MODULES:
        shutil.copy2(ROOT / name, target / name)
    shutil.copytree(ROOT / 'defaults', target / 'defaults')
    shutil.copytree(ROOT / 'frontend/dist', assets / 'ui')
    shutil.copy2(ROOT / 'THIRD_PARTY_NOTICES.md', assets / 'THIRD_PARTY_NOTICES.md')
    print('Android: staged public engine, clean defaults and bundled UI; no account data.')


if __name__ == '__main__':
    main()
