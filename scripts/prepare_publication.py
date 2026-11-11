"""Copy an allowlisted source tree, refusing account data or known credentials."""
from pathlib import Path
import json
import shutil
import sys
ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / '.build' / 'publish'


def files():
    values = list(ROOT.glob('*.py'))
    values += [ROOT / p for p in ('README.md', 'THIRD_PARTY_NOTICES.md', '.gitignore', 'requirements.txt', 'requirements-build.txt', 'start.command')]
    for directory in ('defaults', 'desktop', 'scripts', 'tests', '.github', 'frontend/src', 'frontend/public', 'src-tauri/src', 'src-tauri/icons'):
        values += [p for p in (ROOT / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    values += [ROOT / p for p in ('frontend/package.json', 'frontend/package-lock.json', 'frontend/index.html', 'frontend/tsconfig.json', 'frontend/vite.config.ts',
               'src-tauri/Cargo.toml', 'src-tauri/Cargo.lock', 'src-tauri/build.rs', 'src-tauri/tauri.conf.json', 'src-tauri/binaries/.gitkeep')]
    return sorted(set(values))


def main():
    sensitive = []
    config_path = ROOT / 'config.json'
    if config_path.exists():
        config = json.loads(config_path.read_text())
        sensitive += [str(config.get('resume_id', '')), str(config.get('resume_title', ''))]
    token_path = ROOT / 'auth-profile' / 'token.json'
    if token_path.exists():
        token = json.loads(token_path.read_text()).get('token', {})
        sensitive += [str(token.get('access_token', '')), str(token.get('refresh_token', ''))]
    sensitive = [v for v in sensitive if len(v) > 15]
    manifest = []
    for source in files():
        relative = source.relative_to(ROOT)
        if any(part in ('auth-profile', 'browser-profile', 'screenshots', 'node_modules') for part in relative.parts):
            raise SystemExit('Private path in publication manifest')
        content = source.read_bytes()
        if any(secret.encode() in content for secret in sensitive):
            raise SystemExit('Known private value found in: ' + str(relative))
        destination = DEST / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        manifest.append(str(relative))
    (ROOT / '.build' / 'publication-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f'Publication audit passed: {len(manifest)} allowlisted source files; no known account data.')


if __name__ == '__main__':
    main()
