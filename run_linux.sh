#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv-linux/bin/python ]]; then
  python3 -m venv .venv-linux
  .venv-linux/bin/python -m pip install -r requirements.txt
fi
exec .venv-linux/bin/python app.py "$@"
