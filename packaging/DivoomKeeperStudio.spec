# PyInstaller spec for Divoom Keeper Studio: the browser shell (shell_main.py) with the bundled web UI. Build web/dist first (cd web && npm ci && npm run build).
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent
if not (root / "web" / "dist" / "index.html").exists():
    raise SystemExit("web/dist is missing: run `npm ci && npm run build` in web/ first.")
datas = [(str(root / "web" / "dist"), "web/dist"),
         (str(root / "packaging" / "divoom-keeper-studio.png"), "packaging")]
for package in ("tzdata", "icalendar", "recurring_ical_events"):
    datas += collect_data_files(package)

hiddenimports = [
    # uvicorn picks its loop/protocol implementations by name at runtime.
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.loops.asyncio", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]
# pystray (optional tray) selects its platform backend by name at import time; absent when not installed.
hiddenimports += collect_submodules("pystray")
# jeepney is imported lazily by keeper.notifications, so PyInstaller cannot see it.
if sys.platform == "linux":
    hiddenimports += ["jeepney", "jeepney.io.blocking"]

a = Analysis(
    [str(root / "shell_main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PySide6", "shiboken6", "PyQt5", "PyQt6", "icalendar.tests", "recurring_ical_events.test"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="DivoomKeeperStudio", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=sys.platform != "win32",
)
coll = COLLECT(
    exe, a.binaries, a.datas, strip=False, upx=False, name="DivoomKeeperStudio",
)
