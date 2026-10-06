"""Desktop data paths and optional Linux session readers."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import base64
from urllib.parse import urlparse, unquote


def external_environment(env=None):
    """Environment for programs started from a frozen Linux build (PyInstaller/AppImage).

    The bundle exports LD_LIBRARY_PATH (and some QT_*/PYTHON* paths) pointing at its own libraries; a child such
    as xdg-open/kde-open or the browser then loads the bundled Qt against the system's and fails to start.
    """
    env = dict(os.environ if env is None else env)
    if not (sys.platform.startswith("linux") and getattr(sys, "frozen", False)):
        return env
    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is None:
        env.pop("LD_LIBRARY_PATH", None)
    else:
        env["LD_LIBRARY_PATH"] = original
    bundle = getattr(sys, "_MEIPASS", "") or env.get("APPDIR", "")
    if bundle:
        for key in [k for k, v in env.items() if (k.startswith("QT_") or k in ("PYTHONHOME", "PYTHONPATH")) and bundle in v]:
            env.pop(key)
    return env


def open_external(target, wait=3.0):
    """Open a URL or file path with the desktop's default handler.

    Returns False when no handler could be started or the Linux launcher exits with an error within `wait`
    seconds; a launcher still running after that is assumed to be starting the application.
    """
    target = str(target)
    is_url = target.startswith(("http://", "https://"))
    if sys.platform.startswith("linux"):
        opener = shutil.which("xdg-open")
        if not opener:
            return False
        try:
            process = subprocess.Popen([opener, target], env=external_environment(), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            return False
        try:
            return process.wait(timeout=wait) == 0
        except subprocess.TimeoutExpired:
            return True
    if is_url:
        import webbrowser
        return bool(webbrowser.open(target))
    try:
        if os.name == "nt":
            os.startfile(target)
        else:
            subprocess.Popen(["open", target])
        return True
    except OSError:
        return False


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
    # APPIMAGE is inherited by child processes, so trust it only when this very process is the frozen binary inside that AppDir.
    appdir = os.environ.get("APPDIR", "")
    appimage = os.getenv("APPIMAGE") if (getattr(sys, "frozen", False) and appdir
                                         and Path(sys.executable).resolve().is_relative_to(Path(appdir).resolve())) else None
    args = [appimage] if appimage else [sys.executable]
    if not appimage and not getattr(sys, "frozen", False):
        args.append(str(Path(__file__).resolve().parents[1] / "app.py"))
    args += ["--minimized", "--config-dir", str(config_root)]
    root.mkdir(parents=True, exist_ok=True)
    path.write_text("[Desktop Entry]\nType=Application\nName=Divoom Keeper Studio\nExec=" +
                    " ".join(quote(x) for x in args) + "\nTerminal=false\n", encoding="utf-8")
