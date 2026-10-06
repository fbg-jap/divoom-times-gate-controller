#!/usr/bin/env bash
# Wrap the PyInstaller onedir (dist/linux/DivoomKeeperStudio, from build_linux.sh) into an AppImage.
# appimagetool is taken from $APPIMAGETOOL or PATH; it is never downloaded here.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

TOOL="${APPIMAGETOOL:-}"
if [[ -z "$TOOL" ]]; then TOOL="$(command -v appimagetool || true)"; fi
if [[ -z "$TOOL" || ! -x "$TOOL" ]]; then
  echo "error: appimagetool not found. Put it on PATH or set APPIMAGETOOL=/path/to/appimagetool-x86_64.AppImage (https://github.com/AppImage/appimagetool/releases)." >&2
  exit 1
fi

ONEDIR="dist/linux/DivoomKeeperStudio"
if [[ ! -x "$ONEDIR/DivoomKeeperStudio" ]]; then
  echo "error: $ONEDIR/DivoomKeeperStudio not found. Run build_linux.sh first." >&2
  exit 1
fi

VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' keeper/__init__.py)"
if [[ -z "$VERSION" ]]; then echo "error: cannot read version from keeper/__init__.py" >&2; exit 1; fi
ARCH="${ARCH:-$(uname -m)}"
OUT="dist/DivoomKeeperStudio-${VERSION}-${ARCH}.AppImage"
APPDIR="dist/appimage/DivoomKeeperStudio.AppDir"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib/divoom"
cp -a "$ONEDIR/." "$APPDIR/usr/lib/divoom/"
cp packaging/divoom-keeper-studio.png "$APPDIR/divoom-keeper-studio.png"
cp packaging/divoom-keeper-studio.png "$APPDIR/.DirIcon"

cat > "$APPDIR/divoom-keeper-studio.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Divoom Keeper Studio
Comment=Control the Divoom Times Gate
Exec=DivoomKeeperStudio
Icon=divoom-keeper-studio
Categories=Utility;
Terminal=false
DESKTOP

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/divoom/DivoomKeeperStudio" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

mkdir -p dist
rm -f "$OUT"
ARCH="$ARCH" "$TOOL" "$APPDIR" "$OUT"
echo "Built $OUT"
