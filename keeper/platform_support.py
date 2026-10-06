"""Desktop data paths and optional Linux session readers."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import base64
from urllib.parse import urlparse, unquote


def data_directory():
    if os.name == "nt":
        return Path(os.getenv("APPDATA", str(Path.home()))) / "DivoomKeeperStudio"
    return Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "divoom-keeper-studio"


def linux_music():
    playerctl = shutil.which("playerctl")
    if not playerctl:
        return {"title": "", "artist": "", "status": "Install playerctl to read MPRIS music", "art": ""}
    def run(*args):
        return subprocess.run([playerctl, *args], capture_output=True, text=True, timeout=3).stdout.strip()
    art = ""
    artwork = run("metadata", "mpris:artUrl")
    try:
        parsed = urlparse(artwork)
        blob = b""
        if parsed.scheme == "file":
            path = Path(unquote(parsed.path))
            if path.is_file() and path.stat().st_size <= 2 * 1024**2:
                blob = path.read_bytes()
        elif parsed.scheme in {"http", "https"}:
            import requests
            with requests.get(artwork, stream=True, timeout=3) as response:
                response.raise_for_status()
                for part in response.iter_content(65536):
                    blob += part
                    if len(blob) > 2 * 1024**2:
                        blob = b""
                        break
        art = base64.b64encode(blob).decode("ascii") if blob else ""
    except (OSError, ValueError):
        pass
    return {"title": run("metadata", "xesam:title"), "artist": run("metadata", "xesam:artist"),
            "status": run("status") or "Nothing playing", "art": art}


def linux_locked():
    session = os.getenv("XDG_SESSION_ID")
    executable = shutil.which("loginctl")
    if not session or not executable:
        return None
    result = subprocess.run([executable, "show-session", session, "-p", "LockedHint", "--value"],
                            capture_output=True, text=True, timeout=2)
    return result.stdout.strip() == "yes" if result.returncode == 0 else None


def linux_hardware():
    import psutil
    result = []
    for group, sensors in getattr(psutil, "sensors_temperatures", lambda: {})().items():
        for index, sensor in enumerate(sensors):
            result.append({"Identifier": f"/{group}/temperature/{index}", "Name": sensor.label or group,
                           "SensorType": "Temperature", "Value": sensor.current})
    return result


def linux_startup(enabled, config_root):
    root = Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "autostart"
    path = root / "divoom-keeper-studio.desktop"
    if not enabled:
        path.unlink(missing_ok=True)
        return
    # Desktop Entry Exec quoting, not shell evaluation.
    def quote(value):
        value = str(value)
        if "\n" in value or "\r" in value:
            raise ValueError("Invalid autostart path")
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
    # Inside an AppImage sys.executable is a temporary mount; relaunch the AppImage file itself.
    appimage = os.getenv("APPIMAGE")
    args = [appimage] if appimage else [sys.executable]
    if not appimage and not getattr(sys, "frozen", False):
        args.append(str(Path(__file__).resolve().parents[1] / "app.py"))
    args += ["--minimized", "--config-dir", str(config_root)]
    root.mkdir(parents=True, exist_ok=True)
    path.write_text("[Desktop Entry]\nType=Application\nName=Divoom Keeper Studio\nExec=" +
                    " ".join(quote(x) for x in args) + "\nTerminal=false\n", encoding="utf-8")
