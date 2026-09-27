#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
python3 -m venv .venv-linux
.venv-linux/bin/python -m pip install -r requirements.txt 'pyinstaller>=6,<7'
.venv-linux/bin/python -m PyInstaller --noconfirm --clean --distpath dist/linux packaging/DivoomKeeperStudio.spec
tar -C dist/linux -czf dist/DivoomKeeperStudio-3.1.0-linux-$(uname -m).tar.gz DivoomKeeperStudio
