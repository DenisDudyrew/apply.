#!/bin/bash
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null; then
  echo "Установите Python 3 с python.org и запустите этот файл снова."
  read -r -p "Нажмите Enter для выхода…"
  exit 1
fi
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
if [ ! -f frontend/dist/index.html ]; then
  if ! command -v npm >/dev/null; then
    echo "Для первой сборки интерфейса установите Node.js с nodejs.org."
    exit 1
  fi
  npm ci --prefix frontend
  npm run build --prefix frontend
fi
.venv/bin/python ui.py
read -r -p "Готово. Нажмите Enter для выхода…"
