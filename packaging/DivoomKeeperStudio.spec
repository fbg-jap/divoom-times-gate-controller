# PyInstaller spec: keep Windows' own ICU for Qt's unversioned ICU imports.
# Some development tools add a different ICU build to PATH. Bundling it causes
# QtCore to fail before the GUI starts (e.g. ucnv_open vs ucnv_open_78).
from pathlib import Path
import re
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
datas = []
for package in ("tzdata", "icalendar", "recurring_ical_events"):
    datas += collect_data_files(package)

a = Analysis(
    [str(root / "app.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["icalendar.tests", "recurring_ical_events.test"],
    noarchive=False,
)
# This Qt wheel targets the ICU API provided by Windows 10 (1809+) / Windows 11.
# Let the Windows loader resolve those OS libraries, rather than shipping DLLs
# discovered through an unrelated development tool's PATH.
a.binaries = [entry for entry in a.binaries if not re.fullmatch(
    r"icu(?:uc|in|dt\d*)\.dll", Path(entry[0]).name, flags=re.IGNORECASE)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="DivoomKeeperStudio", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas, strip=False, upx=False, name="DivoomKeeperStudio",
)
