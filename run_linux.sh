#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
# Prefer a Python with PySide6/PyAV wheels; the newest interpreter often has none yet.
PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  for candidate in python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
  done
fi
PYTHON="${PYTHON:-python3}"
if [[ ! -x .venv-linux/bin/python ]]; then
  "$PYTHON" -m venv .venv-linux
  .venv-linux/bin/python -m pip install -r requirements.txt
fi
exec .venv-linux/bin/python app.py "$@"
