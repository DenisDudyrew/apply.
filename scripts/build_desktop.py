"""Build on the target OS. Only explicit public resources enter the frozen backend."""
import argparse
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def target_triple():
    if sys.platform == 'win32':
        return 'x86_64-pc-windows-msvc'
    if sys.platform == 'darwin':
        return ('aarch64' if platform.machine() == 'arm64' else 'x86_64') + '-apple-darwin'
    raise SystemExit('Desktop installers are built on macOS or Windows.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend-only', action='store_true')
    args = parser.parse_args()
    target = target_triple()
    destination = ROOT / '.build' / 'backend' / target
    separator = ';' if sys.platform == 'win32' else ':'
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
        '--name', 'apply-backend', '--distpath', str(destination),
        '--workpath', str(ROOT / '.build' / 'pyinstaller' / target),
        '--specpath', str(ROOT / '.build'), '--paths', str(ROOT), '--log-level', 'WARN',
        '--collect-all', 'hh_applicant_tool', '--collect-all', 'playwright', '--collect-all', 'keyring',
        '--collect-submodules', 'uvicorn', '--collect-submodules', 'fastapi',
        '--copy-metadata', 'hh-applicant-tool', '--copy-metadata', 'keyring',
        '--hidden-import', 'tzdata']
    command += ['--hidden-import', 'keyring.backends.Windows' if sys.platform == 'win32' else 'keyring.backends.macOS']
    for source, name in ((ROOT / 'frontend' / 'dist', 'frontend/dist'),
                         (ROOT / 'defaults', 'defaults'),
                         (ROOT / 'THIRD_PARTY_NOTICES.md', '.')):
        command += ['--add-data', str(source) + separator + name]
    command.append(str(ROOT / 'desktop' / 'backend_entry.py'))
    subprocess.run(command, cwd=ROOT, check=True)
    suffix = '.exe' if sys.platform == 'win32' else ''
    artifact = ROOT / 'src-tauri' / 'binaries' / ('apply-backend-' + target + suffix)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(destination / ('apply-backend' + suffix), artifact)
    print('Backend ready:', artifact, flush=True)
    if not args.backend_only:
        cli = ROOT / 'frontend' / 'node_modules' / '.bin' / ('tauri.cmd' if sys.platform == 'win32' else 'tauri')
        subprocess.run([str(cli), 'build'], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
