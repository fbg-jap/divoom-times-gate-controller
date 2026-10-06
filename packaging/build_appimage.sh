#!/usr/bin/env bash
# Wrap the PyInstaller onedir (dist/linux/DivoomKeeperStudio, from build_linux.sh) into an AppImage.
# Optional env: APP_NAME (default DivoomKeeperStudio; DivoomKeeperStudioWeb for the Qt-free web shell),
# ONEDIR (default dist/linux/$APP_NAME), OUT_NAME (default $APP_NAME).
# appimagetool is taken from $APPIMAGETOOL or PATH; it is never downloaded here.
# Optional: APPIMAGE_RUNTIME=/path/to/runtime-x86_64 (https://github.com/AppImage/type2-runtime/releases, tag 20251108).
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

TOOL="${APPIMAGETOOL:-}"
if [[ -z "$TOOL" ]]; then TOOL="$(command -v appimagetool || true)"; fi
if [[ -z "$TOOL" || ! -x "$TOOL" ]]; then
  echo "error: appimagetool not found. Put it on PATH or set APPIMAGETOOL=/path/to/appimagetool-x86_64.AppImage (https://github.com/AppImage/appimagetool/releases)." >&2
  exit 1
fi

APP_NAME="${APP_NAME:-DivoomKeeperStudio}"
ONEDIR="${ONEDIR:-dist/linux/$APP_NAME}"
OUT_NAME="${OUT_NAME:-$APP_NAME}"
DESKTOP_ID="divoom-keeper-studio"
if [[ "$APP_NAME" == *Web ]]; then DESKTOP_ID="divoom-keeper-studio-web"; fi
if [[ ! -x "$ONEDIR/$APP_NAME" ]]; then
  echo "error: $ONEDIR/$APP_NAME not found. Run build_linux.sh first (add --ui web for DivoomKeeperStudioWeb)." >&2
  exit 1
fi

VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' keeper/__init__.py)"
if [[ -z "$VERSION" ]]; then echo "error: cannot read version from keeper/__init__.py" >&2; exit 1; fi
ARCH="${ARCH:-$(uname -m)}"
OUT="dist/${OUT_NAME}-${VERSION}-${ARCH}.AppImage"
APPDIR="dist/appimage/${APP_NAME}.AppDir"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib/divoom"
cp -a "$ONEDIR/." "$APPDIR/usr/lib/divoom/"
cp packaging/divoom-keeper-studio.png "$APPDIR/divoom-keeper-studio.png"
cp packaging/divoom-keeper-studio.png "$APPDIR/.DirIcon"

cat > "$APPDIR/$DESKTOP_ID.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Divoom Keeper Studio
Comment=Control the Divoom Times Gate
Exec=$APP_NAME
Icon=divoom-keeper-studio
Categories=Utility;
Terminal=false
DESKTOP

cat > "$APPDIR/AppRun" <<APPRUN
#!/bin/sh
HERE="\$(dirname "\$(readlink -f "\$0")")"
exec "\$HERE/usr/lib/divoom/$APP_NAME" "\$@"
APPRUN
chmod +x "$APPDIR/AppRun"

mkdir -p dist
rm -f "$OUT"
# Without a runtime file appimagetool downloads the rolling "continuous" runtime at build time; pass
# $APPIMAGE_RUNTIME (a pinned, checksum-verified runtime-x86_64) for reproducible, offline builds.
ARGS=()
if [[ -n "${APPIMAGE_RUNTIME:-}" ]]; then ARGS+=(--runtime-file "$APPIMAGE_RUNTIME"); fi
ARCH="$ARCH" "$TOOL" ${ARGS[@]+"${ARGS[@]}"} "$APPDIR" "$OUT"
echo "Built $OUT"
