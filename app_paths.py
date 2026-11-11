"""Keep distributable resources separate from each user's private local data."""
import os
from pathlib import Path
import shutil
import sys

FROZEN = bool(getattr(sys, 'frozen', False))
RESOURCE_DIR = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
if os.environ.get('APPLY_DATA_DIR'):
    DATA_DIR = Path(os.environ['APPLY_DATA_DIR']).expanduser().resolve()
elif FROZEN or os.environ.get('APPLY_DESKTOP') == '1':
    from platformdirs import user_data_path
    DATA_DIR = user_data_path('Apply', 'ApplyLocal', roaming=False)
else:
    DATA_DIR = Path(__file__).resolve().parent


def initialize():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in ('config.json', 'letter.txt'):
        destination = DATA_DIR / name
        if not destination.exists():
            shutil.copyfile(RESOURCE_DIR / 'defaults' / name, destination)
    return DATA_DIR
