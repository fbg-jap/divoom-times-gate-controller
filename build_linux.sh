#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  for candidate in python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
  done
fi
"${PYTHON:-python3}" -m venv .venv-linux
.venv-linux/bin/python -m pip install -r requirements.txt 'pyinstaller>=6,<7'
VERSION="$(.venv-linux/bin/python -c 'import keeper; print(keeper.__version__)')"
if [[ ! -f web/dist/index.html ]]; then
  if ! command -v npm >/dev/null 2>&1; then echo "error: web/dist is missing and npm is not installed; build it with 'cd web && npm ci && npm run build'." >&2; exit 1; fi
  (cd web && npm ci && npm run build)
fi
.venv-linux/bin/python -m PyInstaller --noconfirm --clean --distpath dist/linux packaging/DivoomKeeperStudio.spec
tar -C dist/linux -czf "dist/DivoomKeeperStudio-${VERSION}-linux-$(uname -m).tar.gz" DivoomKeeperStudio
