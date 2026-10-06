"""Browser-based desktop shell: engine + portal on 127.0.0.1, UI in the browser, optional tray. No Qt."""
from __future__ import annotations

from contextlib import suppress
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from filelock import FileLock, Timeout

from . import platform_support

DEFAULT_PORT = 8765
BROWSERS = ["brave-browser", "brave", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
            "microsoft-edge", "msedge"]
WINDOWS_BROWSERS = [
    r"BraveSoftware\Brave-Browser\Application\brave.exe",
    r"Google\Chrome\Application\chrome.exe",
    r"Microsoft\Edge\Application\msedge.exe",
]
log = logging.getLogger("keeper.shell")


def find_app_browser(which=shutil.which, exists=os.path.exists, environ=None, platform=None):
    """Path of the first Chromium-family browser that supports --app=URL, or None."""
    for name in BROWSERS:
        found = which(name)
        if found:
            return found
    if (platform or sys.platform) == "win32":
        environ = os.environ if environ is None else environ
        for base in (environ.get("PROGRAMFILES"), environ.get("PROGRAMFILES(X86)"), environ.get("LOCALAPPDATA")):
            for suffix in WINDOWS_BROWSERS if base else ():
                candidate = os.path.join(base, suffix)
                if exists(candidate):
                    return candidate
    return None


def open_ui(url, find=find_app_browser, popen=subprocess.Popen, fallback=platform_support.open_external):
    """Open `url` in an app-mode browser window, else the default handler. Returns True when something started."""
    browser = find()
    if browser:
        try:
            popen([browser, "--app=" + url], env=platform_support.external_environment(), stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=os.name != "nt")
            return True
        except OSError as error:
            log.warning("Could not start %s: %s", browser, error)
    return bool(fallback(url))


def load_tray():
    """Optional Qt-free tray helper (keeper/tray.py): start_tray(menu_callbacks) -> object with .stop()/.notify(title, text), or None."""
    try:
        from .tray import start_tray
    except ImportError:
        return None
    return start_tray


def pick_socket(port):
    """Bound, listening 127.0.0.1 socket on `port`, or on any free port when that one is busy."""
    for candidate in (port, 0):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", candidate))
        except OSError:
            sock.close()
            continue
        sock.listen(128)
        return sock
    raise OSError("No free local port")


def wait_healthy(port, timeout=30, clock=time.monotonic, fetch=None):
    fetch = fetch or (lambda url: urllib.request.urlopen(url, timeout=2).status)
    deadline = clock() + timeout
    while clock() < deadline:
        with suppress(OSError, ValueError):
            if fetch(f"http://127.0.0.1:{port}/healthz") == 200:
                return True
        time.sleep(.1)
    return False


def start_server(app, sock):
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", proxy_headers=False, lifespan="on"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), name="portal-server", daemon=True)
    thread.start()
    return server, thread


def read_running(root):
    try:
        info = json.loads((root / "shell.json").read_text(encoding="utf-8"))
        return int(info["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def resolve_root(args):
    if args.config_dir:
        return Path(args.config_dir), None
    if args.demo:
        temp = tempfile.TemporaryDirectory(prefix="divoom-studio-demo-")
        return Path(temp.name), temp
    return platform_support.data_directory(), None


def run(args, *, serve=start_server, healthy=wait_healthy, opener=open_ui, tray_loader=load_tray, quit_event=None):
    """Run the shell until quit. Returns the process exit code.

    A second instance only opens the browser on the running one; the page then asks for the access token as the
    plain web portal does (the launch code is in-process only, so a second process cannot obtain one).
    """
    root, temp = resolve_root(args)
    root.mkdir(parents=True, exist_ok=True)
    lock = FileLock(root / "studio.lock", timeout=0)
    try:
        lock.acquire()
    except Timeout:
        port = read_running(root)
        if port and not args.minimized:
            opener(f"http://127.0.0.1:{port}/")
        print("Keeper is already running" + (f": http://127.0.0.1:{port}/" if port else "."), file=sys.stderr)
        return 0
    handler = RotatingFileHandler(root / "studio.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s [%(levelname)s] %(message)s")
    quit_event = quit_event or threading.Event()
    sock = server = thread = tray = None
    code = 0
    try:
        from .portal import create_app
        app = create_app(root, demo=args.demo, shell_mode=True)
        app.state.quit_event = quit_event
        sock = pick_socket(args.port or int(os.getenv("KEEPER_SHELL_PORT", DEFAULT_PORT)))
        port = sock.getsockname()[1]
        server, thread = serve(app, sock)
        if not healthy(port):
            log.error("The portal did not start")
            return 1
        (root / "shell.json").write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
        base = f"http://127.0.0.1:{port}/"

        def open_browser():
            opener(base + "#launch=" + app.state.launch_codes.issue())

        if args.print_launch_url:
            print(base + "#launch=" + app.state.launch_codes.issue(), flush=True)
        log.info("Keeper portal on %s", base)
        factory = tray_loader()
        if factory:
            try:
                from .startup import set_startup
                tray = factory({"open": open_browser, "quit": quit_event.set,
                                "startup_enabled": lambda: bool(app.state.store.snapshot().get("startup")),
                                "set_startup": lambda on: (set_startup(on, root), app.state.store.change(lambda d: d.update(startup=on)))})
            except Exception as error:
                log.warning("Tray unavailable: %s", error)
        if not args.minimized:
            open_browser()
        elif not tray:
            log.info("Started minimized without a tray; open %s", base)
        if threading.current_thread() is threading.main_thread():
            with suppress(ValueError):
                signal.signal(signal.SIGTERM, lambda *_: quit_event.set())
        try:
            while not quit_event.wait(.5):
                if thread is not None and not thread.is_alive():
                    log.error("The portal server stopped unexpectedly")
                    code = 1
                    break
        except KeyboardInterrupt:
            pass
    finally:
        if tray:
            with suppress(Exception):
                tray.stop()
        if server:
            server.should_exit = True
        if thread:
            thread.join(30)
        if sock:
            sock.close()
        (root / "shell.json").unlink(missing_ok=True)
        lock.release()
        handler.close()
        if temp:
            temp.cleanup()
    return code
