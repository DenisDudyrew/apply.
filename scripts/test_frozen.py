"""Verify that shipped resources contain no developer resume, auth, or history."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_desktop import target_triple, ROOT

binary = ROOT / 'src-tauri' / 'binaries' / ('apply-backend-' + target_triple() + ('.exe' if sys.platform == 'win32' else ''))
with tempfile.TemporaryDirectory() as directory:
    result = subprocess.run([str(binary), '--self-test'], env=dict(os.environ, APPLY_DATA_DIR=directory),
                            capture_output=True, text=True, timeout=120, check=True)
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data['ok'] and data['resources'] and data['clean_config'], data
    root = Path(directory)
    assert not (root / 'auth-profile' / 'token.json').exists()
    assert not (root / 'state.sqlite3').exists()
print('PASS: standalone engine, clean default profile, bundled UI, no developer credentials/history')
