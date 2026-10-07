"""Browser-based desktop shell: engine + portal on 127.0.0.1, UI in the browser, optional tray. No Qt."""
from __future__ import annotations

import argparse
from contextlib import suppress
import html
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
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
PRIVATE_DIR, PRIVATE_FILE = 0o700, 0o600


class PrivateRotatingFileHandler(RotatingFileHandler):
    """Log file readable by the owner only, including after a rollover."""

    def _open(self):
        stream = super()._open()
        if os.name != "nt":
            with suppress(OSError):
                os.chmod(self.baseFilename, PRIVATE_FILE)
        return stream


def write_private(path, text):
    """Write `text` to `path` as an owner-only (0600) file; an existing file is truncated and its mode tightened."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_FILE)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        if os.name != "nt":
            os.chmod(path, PRIVATE_FILE)
        handle.write(text)


def launch_page(root, url):
    """Create a 0600 `open-<random>.html` in `root` that redirects to `url`; returns its Path.

    The one-time launch code travels inside this file, never on a command line (argv is world-readable through
    /proc), so only the data-directory owner can read it. O_EXCL means an existing file or symlink is never reused.
    """
    path = Path(root) / f"open-{secrets.token_hex(8)}.html"
    page = ('<!doctype html><meta charset="utf-8"><title>Keeper</title>'
            f'<meta http-equiv="refresh" content="0;url={html.escape(url, quote=True)}">'
            f'<script>location.replace({json.dumps(url).replace("<", chr(92) + "u003c")})</script>')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(page)
    return path


def remove_stale_launch_pages(root):
    for stale in Path(root).glob("open-*.html"):
        with suppress(OSError):
            stale.unlink()


class LaunchPages:
    """Issues launch codes wrapped in short-lived launch pages and deletes each page once its code is spent or expired."""

    def __init__(self, root, codes, clock=time.monotonic):
        self.root, self.codes, self.clock = root, codes, clock
        self.pages, self.lock = {}, threading.Lock()
        codes.on_redeem = self.sweep

    def create(self, base):
        """file:// URI of a fresh launch page for `base`, or None when it cannot be written (never a URL with the code)."""
        code = self.codes.issue()
        try:
            path = launch_page(self.root, base + "#launch=" + code)
        except OSError as error:
            log.warning("Could not write the launch page (%s); opening the login page instead", error)
            return None
        with self.lock:
            self.pages[path] = (code, self.clock() + self.codes.ttl)
        return path.as_uri()

    def sweep(self):
        with self.codes.lock:
            live = set(self.codes.codes)
        now = self.clock()
        with self.lock:
            for path, (code, expires) in list(self.pages.items()):
                if code not in live or now >= expires:
                    with suppress(OSError):
                        path.unlink()
                    del self.pages[path]

    def close(self):
        with self.lock:
            for path in self.pages:
                with suppress(OSError):
                    path.unlink()
            self.pages.clear()


QT_REMOVED = ("The Qt interface was removed; the web UI is the interface. "
              "Use tag qt-ui-last to get the old app.")


def parse_args(argv=None):
    """The single argument parser (app.py and shell_main.py both use it)."""
    parser = argparse.ArgumentParser(description="Divoom Keeper Studio")
    parser.add_argument("--demo", action="store_true", help="Synthetic data; no device/network writes")
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--no-tray", action="store_true", help="Do not show the tray icon")
    parser.add_argument("--ui", choices=("web", "qt"), default="web", help=argparse.SUPPRESS)  # web: kept for old autostart entries
    parser.add_argument("--port", type=int, help="Local port (default 8765, KEEPER_SHELL_PORT)")
    parser.add_argument("--print-launch-url", action="store_true", help="DEBUG ONLY: print the one-time login URL")
    parser.add_argument("--screenshot-dir", type=Path, help=argparse.SUPPRESS)  # removed with the Qt interface
    args = parser.parse_args(argv)
    if args.ui == "qt" or args.screenshot_dir:
        print(QT_REMOVED, file=sys.stderr)
        raise SystemExit(2)
    return args


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
        if os.name == "nt":  # never SO_REUSEADDR on Windows: it would let another process share the port
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
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
    from .startup import set_ui_args
    set_ui_args(["--ui", "web"])  # autostart relaunches this same mode
    root, temp = resolve_root(args)
    owned = not args.config_dir or not root.exists()
    root.mkdir(mode=PRIVATE_DIR, parents=True, exist_ok=True)
    if owned and os.name != "nt":
        try:
            os.chmod(root, PRIVATE_DIR)
        except OSError as error:
            log.warning("Could not restrict %s to its owner: %s", root, error)
    lock = FileLock(root / "studio.lock", timeout=0, mode=PRIVATE_FILE)
    try:
        lock.acquire()
    except Timeout:
        port = read_running(root)
        if port and not args.minimized:
            opener(f"http://127.0.0.1:{port}/")
        print("Keeper is already running" + (f": http://127.0.0.1:{port}/" if port else "."), file=sys.stderr)
        return 0
    remove_stale_launch_pages(root)
    handler = PrivateRotatingFileHandler(root / "studio.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s [%(levelname)s] %(message)s")
    quit_event = quit_event or threading.Event()
    sock = server = thread = tray = pages = None
    code = 0
    try:
        from .portal import create_app
        app = create_app(root, demo=args.demo, shell_mode=True)
        app.state.quit_event = quit_event
        wanted = args.port or int(os.getenv("KEEPER_SHELL_PORT", DEFAULT_PORT))
        sock = pick_socket(wanted)
        port = sock.getsockname()[1]
        fallback = bool(wanted) and port != wanted
        if fallback:
            log.warning("Port %s is in use; using %s", wanted, port)
        pages = LaunchPages(root, app.state.launch_codes)
        server, thread = serve(app, sock)
        if not healthy(port):
            log.error("The portal did not start")
            return 1
        write_private(root / "shell.json", json.dumps({"port": port, "pid": os.getpid(), "fallback": fallback}))
        base = f"http://127.0.0.1:{port}/"

        def open_browser():
            # Only a file:// URI (the 0600 launch page) reaches the browser's argv; never the code itself.
            # Chromium `--app=file:///...` then redirects to http://127.0.0.1 via location.replace: the app window
            # keeping its chrome-less mode across that redirect is UNVERIFIED; adjust launch_page/open_ui if it does not.
            opener(pages.create(base) or base)

        if args.print_launch_url:
            # A live code on a captured stdout is readable by whoever reads the pipe/log. Print it only to a terminal.
            # KEEPER_ALLOW_PIPED_LAUNCH_URL=1 is a TEST-ONLY opt-in (tools/smoke_shell.py must set it to read the URL).
            if sys.stdout.isatty() or os.getenv("KEEPER_ALLOW_PIPED_LAUNCH_URL") == "1":
                print(base + "#launch=" + app.state.launch_codes.issue(), flush=True)
            else:
                print(base, flush=True)
                print("launch URL suppressed (stdout is not a terminal); use the data-dir login", file=sys.stderr)
        log.info("Keeper portal on %s", base)
        factory = None if getattr(args, "no_tray", False) else tray_loader()
        if factory:
            try:
                from .startup import set_startup
                tray = factory({"open": open_browser, "quit": quit_event.set,
                                "startup_enabled": lambda: bool(app.state.store.snapshot().get("startup")),
                                "set_startup": lambda on: (set_startup(on, root), app.state.store.change(lambda d: d.update(startup=on)))})
            except Exception as error:
                log.warning("Tray unavailable: %s", error)
        if fallback and tray:
            try:
                tray.notify("Keeper", f"Port {wanted} is in use; using {port}")
            except Exception as error:
                log.warning("Tray notification failed: %s", error)
        if not args.minimized:
            open_browser()
        elif not tray:
            log.info("Started minimized without a tray; open %s", base)
        if threading.current_thread() is threading.main_thread():
            with suppress(ValueError):
                signal.signal(signal.SIGTERM, lambda *_: quit_event.set())
        try:
            while not quit_event.wait(.5):
                pages.sweep()
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
        if pages:
            pages.close()
        (root / "shell.json").unlink(missing_ok=True)
        lock.release()
        handler.close()
        if temp:
            temp.cleanup()
    return code
