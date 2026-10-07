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
LAUNCH_WAIT = 65  # launch-code TTL (60 s) plus margin: how long a second instance keeps its launch page


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


def ensure_std_streams():
    """A windowed (console-less) Windows build has sys.stdout/sys.stderr = None: give them a null sink so nothing crashes."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def parse_args(argv=None):
    """The single argument parser (app.py and shell_main.py both use it)."""
    parser = argparse.ArgumentParser(description="Divoom Keeper Studio")
    parser.add_argument("--demo", action="store_true", help="Synthetic data; no device/network writes")
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--no-tray", action="store_true", help="Do not show the tray icon")
    parser.add_argument("--ui", choices=("web", "qt"), default="web", help=argparse.SUPPRESS)  # web: kept for old autostart entries
    parser.add_argument("--port", type=int, help="Local port (default 8765, KEEPER_SHELL_PORT)")
    parser.add_argument("--self-test", action="store_true", help="Check the bundled libraries (calendar, video, GIF, ...) and exit")
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


BROWSER_PROFILE = None   # set by run(): the app window gets its own browser profile folder (and so its own process)


def browser_flags():
    """Flags that need a browser process of their own: with Keeper's profile folder Brave/Chrome start a separate process
    instead of handing --app to the normal, already running one (which ignores --class and --window-size)."""
    flags = ["--window-size=1280,800"]
    if sys.platform.startswith("linux"):
        flags.append("--class=" + platform_support.WM_CLASS)
    if BROWSER_PROFILE:
        flags += ["--user-data-dir=" + str(BROWSER_PROFILE), "--no-first-run", "--no-default-browser-check"]
    return flags


def open_ui(url, find=find_app_browser, popen=subprocess.Popen, fallback=platform_support.open_external):
    """Open `url` in an app-mode browser window, else the default handler. Returns True when something started."""
    browser = find()
    if browser:
        try:
            log.info("Opening the UI in %s (app mode)", Path(browser).name)
            popen([browser, "--app=" + url, *browser_flags()], env=platform_support.external_environment(), stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=os.name != "nt")
            return True
        except OSError as error:
            log.warning("Could not start %s: %s", browser, error)
    log.info("Opening the UI with the system opener")
    opened = bool(fallback(url))
    if not opened:
        log.warning("Could not open a browser: no browser found and the system opener failed")
    return opened


def reopen_running(root, port, opener, *, session_factory=None, sleep=time.sleep, wait=LAUNCH_WAIT):
    """Second instance: open the running one already logged in; falls back to its login page. Never raises.

    Reads the owner-only admin.token, asks the running instance for a fresh single-use launch code (Bearer, loopback,
    no proxy) and opens a 0600 launch page exactly like the first instance, so only a file:// URI reaches argv. The
    process then stays alive for `wait` seconds (code TTL plus margin) and deletes the page: the code is dead by then.
    """
    base = f"http://127.0.0.1:{port}/"
    page = None
    try:
        token = (Path(root) / "admin.token").read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError("empty token file")
        if session_factory is None:
            import requests
            session_factory = requests.Session
        session = session_factory()
        session.trust_env = False  # no proxy may ever see the token
        response = session.post(base + "api/launch/issue", headers={"Authorization": "Bearer " + token, "Host": f"127.0.0.1:{port}"},
                                timeout=5, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError(f"the running instance answered HTTP {response.status_code}")
        code = response.json().get("code")
        if not isinstance(code, str) or not code:
            raise ValueError("no launch code in the reply")
        page = launch_page(root, base + "#launch=" + code)
    except Exception as error:  # nothing here may stop the plain fallback; the message never contains the token or code
        log.warning("Second instance: could not log in automatically (%s); opening the login page", error)
        opener(base)
        return
    try:
        if opener(page.as_uri()):
            log.info("Second instance: opened the running UI with a launch page (removed in %s s)", wait)
            sleep(wait)
        else:
            log.warning("Second instance: the browser did not start")
    finally:
        with suppress(OSError):
            page.unlink()


def load_tray():
    """Optional Qt-free tray helper (keeper/tray.py): start_tray(menu_callbacks) -> object with .stop()/.notify(title, text), or None."""
    try:
        from .tray import start_tray
    except ImportError:
        return None
    return start_tray


LOCK_TAKEOVER_WAIT = 10


def pick_socket(port):
    """Bound, listening 127.0.0.1 socket on `port`, or on any free port when that one is busy."""
    for candidate in (port, 0):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt":  # never SO_REUSEADDR on Windows: it would let another process share the port
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:  # POSIX: a restart right after quitting must not find the port held by TIME_WAIT sockets (it never shares a live listener)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
    # log_config=None: uvicorn's default logging config needs a real stdout/stderr; the shell logs to studio.log through
    # the root logger, which uvicorn's (handler-less, propagating) loggers reach at WARNING.
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", log_config=None, proxy_headers=False, lifespan="on"))
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


def show_error(text):
    """Tell the user about a startup failure when there is no console (best effort, never raises)."""
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, "Divoom Keeper Studio", 0x10)
        else:
            notifier = shutil.which("notify-send")
            if notifier:
                subprocess.Popen([notifier, "Divoom Keeper Studio", text], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as error:
        log.warning("Could not show the error message: %s", error)


def config_failure(root, error):
    """Log, print and show a startup failure caused by the settings; returns the exit code."""
    log.error("The settings file could not be loaded", exc_info=error)
    if isinstance(error, (json.JSONDecodeError, UnicodeDecodeError)):
        reason = "the file is not valid JSON"
    elif isinstance(error, (ValueError, KeyError, TypeError)):
        reason = "a setting is invalid"
    elif isinstance(error, OSError):
        reason = "the file could not be read"
    else:
        reason = "unexpected error"
    text = f"The settings file could not be loaded: {reason}. Nothing was modified. Data folder: {root}"
    print(text, file=sys.stderr)
    show_error(text)
    return 1


def run(args, *, serve=start_server, healthy=wait_healthy, opener=open_ui, tray_loader=load_tray, quit_event=None):
    """Run the shell until quit. Returns the process exit code.

    A second instance opens the browser on the running one, logged in through a launch code that the running one
    issues to it on request (reopen_running); when that fails it opens the login page.
    """
    ensure_std_streams()
    if getattr(args, "self_test", False):
        from .selftest import run_self_test
        return run_self_test()
    from .startup import set_ui_args
    set_ui_args(["--ui", "web"])  # autostart relaunches this same mode
    root, temp = resolve_root(args)
    owned = not args.config_dir or not root.exists()
    root.mkdir(mode=PRIVATE_DIR, parents=True, exist_ok=True)
    global BROWSER_PROFILE
    BROWSER_PROFILE = root / "browser"   # not in demo/test roots that vanish: it is only a path until a browser starts
    if owned and os.name != "nt":
        try:
            os.chmod(root, PRIVATE_DIR)
        except OSError as error:
            log.warning("Could not restrict %s to its owner: %s", root, error)
    lock = FileLock(root / "studio.lock", timeout=0, mode=PRIVATE_FILE)
    try:
        lock.acquire()
        running = False
    except Timeout:
        running = True
    if running:
        port = read_running(root)
        if not (port and wait_healthy(port, timeout=1)):
            # The other instance is still shutting down (or hung): take over as soon as it releases the lock.
            with suppress(Timeout):
                lock.acquire(timeout=LOCK_TAKEOVER_WAIT)
                running = False
    if running:
        second_log = logging.FileHandler(root / "studio.log", encoding="utf-8")  # append; the first instance owns rotation
        second_log.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(second_log)
        previous_level = root_logger.level
        root_logger.setLevel(logging.INFO)
        try:
            if os.name != "nt":
                with suppress(OSError):
                    os.chmod(second_log.baseFilename, PRIVATE_FILE)
            if port and not args.minimized:
                log.info("Another instance is running on port %s; opening it", port)
                reopen_running(root, port, opener)
            else:
                log.info("Another instance is running (port %s); nothing to open", port)
        finally:
            root_logger.removeHandler(second_log)
            root_logger.setLevel(previous_level)
            second_log.close()
        print("Keeper is already running" + (f": http://127.0.0.1:{port}/" if port else "."), file=sys.stderr)
        return 0
    remove_stale_launch_pages(root)
    handler = PrivateRotatingFileHandler(root / "studio.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)  # not basicConfig: a handler left by an earlier run() in this process must not win
    root_logger.setLevel(logging.INFO)
    quit_event = quit_event or threading.Event()
    sock = server = thread = tray = pages = None
    code = 0
    try:
        from .portal import create_app
        try:
            app = create_app(root, demo=args.demo, shell_mode=True, migrate=not args.demo)
        except Exception as error:
            return config_failure(root, error)
        if not args.demo and app.state.store.snapshot().get("startup"):
            # Keep an enabled autostart entry pointing at this release (AppImage / unpacked exe paths change per version).
            from .startup import set_startup
            try:
                set_startup(True, root)
            except OSError as error:
                log.warning("Could not update autostart: %s", error)
        if not args.demo and sys.platform.startswith("linux"):
            try:   # taskbar icon: the app window's --class matches this entry's StartupWMClass
                platform_support.linux_launcher_entry(root)
            except Exception as error:
                log.warning("Could not install the launcher entry: %s", error)
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
            if getattr(sys.stdout, "isatty", lambda: False)() or os.getenv("KEEPER_ALLOW_PIPED_LAUNCH_URL") == "1":
                launch_url = base + "#launch=" + app.state.launch_codes.issue()
                print(launch_url, flush=True)
                # TEST-ONLY: a windowed (console-less) Windows build has no stdout, so the smoke test can read the URL
                # from a file instead. Only honoured together with the opt-in above; written owner-only.
                url_file = os.getenv("KEEPER_LAUNCH_URL_FILE")
                if url_file and os.getenv("KEEPER_ALLOW_PIPED_LAUNCH_URL") == "1":
                    try:
                        write_private(url_file, launch_url + "\n")
                    except OSError:
                        log.warning("Could not write the launch URL file")
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
            log.info("Started minimized without a tray; opening %s so the app is not invisible", base)
            open_browser()
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
        root_logger.removeHandler(handler)
        handler.close()
        if temp:
            temp.cleanup()
    return code
