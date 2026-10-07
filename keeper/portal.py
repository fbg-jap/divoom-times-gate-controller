"""Authenticated, single-engine web controller. No Qt dependency."""
from __future__ import annotations

import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import copy
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from filelock import FileLock
from PIL import Image, ImageOps

from . import __version__
from .config import ConfigStore, slot, validate, uid
from .content import all_screens, assets, panorama_canvas
from .engine import Engine
from .extensions import spotify_redirect_kind
from .mail import migrate_conf
from .panorama_media import decode_clip, VIDEO_EXTENSIONS, rgb
from .protocol import valid_ip
from .timesync import timesource
from . import oauth, spotify
from .widgets import png_bytes
from . import platform_support

MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".ics"}
LIMIT = 100 * 1024**2


def revision(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class PortalEngine(Engine):
    def __init__(self, *args, **kwargs):
        self.activity = deque(maxlen=300)
        self.previews = {}
        self.tasks = {}
        self.portal_lock = threading.RLock()
        self.sequence = 0
        super().__init__(*args, **kwargs)

    def emit(self, event, **kwargs):
        with self.portal_lock:
            if event == "preview":
                self.previews[(kwargs["device_id"], kwargs["panel"])] = kwargs["png"]
                return
            self.sequence += 1
            self.activity.append({"id": self.sequence, "event": event, "time": time.time(), **kwargs})

    def invalidate(self, device_id, panel=None):
        super().invalidate(device_id, panel)
        with self.portal_lock:
            for key in list(self.previews):
                if key[0] == device_id and (panel is None or key[1] == panel):
                    self.previews.pop(key, None)

    def new_task(self, operation):
        with self.portal_lock:
            for key in list(self.tasks):
                if len(self.tasks) < 100:
                    break
                if self.tasks[key]["status"] in {"done", "error", "cancelled"}:
                    del self.tasks[key]
            if len(self.tasks) >= 100:
                raise ValueError("Too many pending tasks")
            key = uid()
            self.tasks[key] = {"id": key, "operation": operation, "status": "queued"}
            return key

    def task_update(self, key, **values):
        with self.portal_lock:
            self.tasks[key].update(values)

    def enqueue(self, operation, callback):
        key = self.new_task(operation)
        if not self.submit("portal", task_id=key, callback=callback):
            self.task_update(key, status="error", error="Queue full")
            raise ValueError("Queue full")
        return {"job": key}

    def process(self, action, device_id, args):
        if action != "portal":
            return super().process(action, device_id, args)
        key = args["task_id"]
        self.task_update(key, status="running")
        try:
            result = args["callback"]()
            self.task_update(key, status="done", result=result)
        except Exception as error:
            self.task_update(key, status="error", error=str(error))
            self.log(str(error), "error")


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


HOST_PATTERN = re.compile(r"(\[[0-9a-f:]+\]|[a-z0-9.-]+)(?::(\d{1,5}))?", re.I)


def host_name(header):
    """Lower-cased hostname of a strictly valid Host header (name or [ipv6], optional port <= 65535); '' otherwise."""
    match = HOST_PATTERN.fullmatch(header or "")
    if not match or (match.group(2) and int(match.group(2)) > 65535):
        return ""
    return match.group(1).lower()


class LaunchCodes:
    """Short-lived single-use codes that let the local shell hand the admin token to a browser it opens.

    Codes are only ever created in-process (`issue()`); there is deliberately no HTTP route that creates them.
    """

    def __init__(self, clock=time.monotonic, ttl=60, limit=8, max_failures=10, window=60):
        self.clock, self.ttl, self.limit, self.max_failures, self.window = clock, ttl, limit, max_failures, window
        self.codes, self.failures = {}, deque()
        self.on_redeem = None  # called (outside the lock) after a successful redeem
        self.lock = threading.Lock()

    def issue(self):
        code = secrets.token_urlsafe(24)
        with self.lock:
            now = self.clock()
            for old in [c for c, expires in self.codes.items() if expires <= now]:
                del self.codes[old]
            while len(self.codes) >= self.limit:
                del self.codes[next(iter(self.codes))]
            self.codes[code] = now + self.ttl
        return code

    def limited(self):
        with self.lock:
            now = self.clock()
            while self.failures and now - self.failures[0] > self.window:
                self.failures.popleft()
            return len(self.failures) >= self.max_failures

    def redeem(self, code):
        with self.lock:
            now = self.clock()
            match = None
            for stored in self.codes:
                if hmac.compare_digest(stored.encode(), code.encode()):
                    match = stored
            expires = self.codes.pop(match, None) if match is not None else None
            if expires is None or expires <= now:
                self.failures.append(now)
                return False
        if self.on_redeem:
            self.on_redeem()
        return True


def validate_portal(data, media_dir):
    validate(data)
    if len(data["devices"]) > 30 or len(data["scenes"]) > 200 or len(data["schedules"]) > 200:
        raise ValueError("Device, scene or schedule limit exceeded")
    for d in data["devices"]:
        if d.get("ip"):
            valid_ip(d["ip"])
        if not 30 <= int(d.get("quality", 85)) <= 100 or not 1 <= int(d.get("speed", 100)) <= 60000:
            raise ValueError("Invalid quality or speed")
    root = media_dir.resolve()
    for screen in all_screens(data):
        if not 1 <= int(screen.get("frame_step", 1)) <= 100 or not 5 <= int(screen.get("refresh", 30)) <= 86400:
            raise ValueError("Invalid step or refresh")
        for asset in assets(screen):
            if asset.get("path"):
                path = Path(asset["path"]).resolve()
                if path.parent != root or not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
                    raise ValueError("Use a file uploaded to this server's library")


def create_app(root, token=None, demo=False, engine_factory=PortalEngine, web_root=None, shell_mode=False, clock=time.monotonic):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = FileLock(root / "server.lock", timeout=0)
    token_path = root / "admin.token"
    token = token or os.getenv("KEEPER_TOKEN")
    if not token:
        if not token_path.exists():
            with os.fdopen(os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
                stream.write(secrets.token_urlsafe(32))
        token = token_path.read_text(encoding="utf-8").strip()
    if len(token) < 24:
        raise ValueError("KEEPER_TOKEN must be at least 24 characters")
    with lock:
        store = ConfigStore(root, migrate=False)
    engine = engine_factory(store, demo=demo)
    converter = ThreadPoolExecutor(max_workers=1, thread_name_prefix="portal-converter")
    conversion_slots = threading.BoundedSemaphore(2)
    cancelled = {}

    @asynccontextmanager
    async def lifespan(app):
        lock.acquire()
        engine.start()
        try:
            yield
        finally:
            for event in list(cancelled.values()):
                event.set()
            converter.shutdown(wait=False, cancel_futures=True)
            engine.stop()
            await asyncio.to_thread(engine.join, 15)
            lock.release()

    app = FastAPI(title="Divoom Keeper Portal", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store, app.state.engine = store, engine
    pending_spotify = spotify.PendingAuth()
    app.state.spotify_pending = pending_spotify
    app.state.spotify_session = spotify.requests.Session
    app.state.oauth_pending = pending_oauth = oauth.PendingOAuth(clock)
    app.state.oauth_session = spotify.requests.Session
    # Separate budgets (monotonic times of failures): the public callback only counts failures after a VALID state (a forged
    # state costs an attacker nothing to produce and must not lock out the real sign-in or the authenticated paste-back).
    callback_failures, complete_failures = deque(), deque()
    app.state.launch_codes = LaunchCodes(clock)
    app.state.quit_event = threading.Event()
    app.state.open_external = platform_support.open_external
    extra_hosts = {h.strip().lower() for h in os.getenv("KEEPER_HOSTS", "").split(",") if h.strip()}

    @app.middleware("http")
    async def security(request, call_next):
        # The browser returns from accounts.spotify.com / Google / Microsoft without the Bearer header. Only these two exact
        # GETs are exempt, and the handlers themselves require a single-use `state` that an authenticated start call issued.
        hosts = request.headers.getlist("host")
        if shell_mode and (len(hosts) != 1 or host_name(hosts[0]) not in LOOPBACK_HOSTS | extra_hosts):
            # DNS rebinding: a page on another origin must not reach the local server under its own hostname.
            return JSONResponse({"error": "Host not allowed"}, status_code=421)
        public = request.method == "GET" and request.url.path in {"/api/spotify/callback", "/api/oauth/callback"}
        # The shell exchanges its single-use launch code for the token here; exact POST match only.
        public = public or (shell_mode and request.method == "POST" and request.url.path == "/api/launch")
        if request.url.path.startswith("/api/") and not public:
            supplied = request.headers.get("authorization", "")
            if not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
                return JSONResponse({"error": "Enter the access token"}, status_code=401)
            origin = request.headers.get("origin")
            if origin and origin not in {str(request.base_url).rstrip("/"), *os.getenv("KEEPER_ORIGINS", "").split(",")}:
                return JSONResponse({"error": "Origin not allowed"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
        return response

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(KeyError)
    @app.exception_handler(TypeError)
    async def malformed(request, exc):
        return JSONResponse({"error": "Incomplete request or invalid types"}, status_code=400)

    async def body(request, limit=1024**2):
        chunks, count = [], 0
        async for chunk in request.stream():
            count += len(chunk)
            if count > limit:
                raise HTTPException(413, "File or request too large")
            chunks.append(chunk)
        return b"".join(chunks)

    async def json_body(request):
        value = json.loads(await body(request))
        if not isinstance(value, dict):
            raise ValueError("A JSON object is required")
        return value

    def owned(name):
        if not name or Path(name).name != name:
            raise ValueError("Invalid file")
        path = (store.media_dir / name).resolve()
        if path.parent != store.media_dir.resolve() or not path.is_file():
            raise HTTPException(404, "File not found")
        return path

    def save_blob(blob, suffix):
        path = store.media_dir / (hashlib.sha256(blob).hexdigest()[:20] + suffix)
        path.write_bytes(blob)
        return str(path)

    @app.get("/healthz")
    def health():
        return {"ok": engine.is_alive(), "version": __version__}

    def loopback_or_https(url):
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1"})

    @app.post("/api/spotify/connect")
    async def spotify_connect(request: Request):
        values = await json_body(request)
        client_id = str(values.get("client_id") or store.snapshot().get("integrations", {}).get("spotify", {}).get("client_id", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9]{8,128}", client_id):
            raise ValueError("Enter the Spotify Client ID first")
        redirect_uri = str(request.base_url).rstrip("/") + "/api/spotify/callback"
        if not loopback_or_https(redirect_uri):
            raise ValueError("Spotify only accepts https or http://127.0.0.1 redirect URIs. Open the portal through "
                             "http://127.0.0.1:<port> (for example an SSH tunnel) or behind https, then try again.")
        _, url = pending_spotify.issue(client_id, redirect_uri)
        return {"url": url, "redirect_uri": redirect_uri}

    @app.get("/api/spotify/callback")
    async def spotify_callback(request: Request):
        def page(status, message):
            blob = ("<!doctype html><meta charset=utf-8><title>Keeper</title><p>" + message + "</p>").encode()
            return Response(blob, status_code=status, media_type="text/html")
        query = request.query_params
        pending = pending_spotify.take(query.get("state", ""))
        if pending is None:
            return page(400, "This Spotify link is invalid or has expired. Start again from Keeper.")
        verifier, client_id, redirect_uri = pending
        if not query.get("code"):
            return page(400, "Spotify did not authorize Keeper.")
        try:
            data = await asyncio.to_thread(lambda: spotify.exchange_code(app.state.spotify_session(), client_id, query["code"], verifier, redirect_uri))
            if not data["refresh_token"]:
                raise spotify.SpotifyError("no refresh token")
            await asyncio.to_thread(store.change, lambda d: d.setdefault("integrations", {}).setdefault("spotify", {}).update(
                refresh_token=data["refresh_token"], client_id=client_id))
        except spotify.SpotifyError as error:
            return page(502, "Could not connect to Spotify: " + spotify.redact(str(error), query["code"], verifier))
        return page(200, "Spotify connected. You can close this tab and reload Keeper.")

    OAUTH_INVALID = "This sign-in link is invalid or has expired. Start again from Keeper."
    OAUTH_FAILED = "Could not complete the connection. Check the client settings and try again."
    OAUTH_SAFE_ERRORS = {  # fixed texts of the paste-back parsers (they never include the pasted input)
        "the pasted address is empty or too long", "the pasted address has no authorization code",
        "Spotify did not authorize Keeper", "the pasted address does not belong to this connection attempt; start again",
        "sign-in was not authorized", "the pasted address does not belong to this sign-in attempt; start again"}

    def oauth_limited(failures):
        now = clock()
        while failures and now - failures[0] > 60:
            failures.popleft()
        return len(failures) >= 10

    def oauth_error(error):
        text = str(error)
        return text if text in OAUTH_SAFE_ERRORS else OAUTH_FAILED

    def exchange_token(entry, code):
        session = app.state.oauth_session()
        if entry["service"] == "spotify":
            data = spotify.exchange_code(session, entry["account"]["client_id"], code, entry["verifier"], entry["redirect_uri"])
            if not data["refresh_token"]:
                raise spotify.SpotifyError("no refresh token")
            return data["refresh_token"]
        return oauth._need_refresh(oauth.exchange_code(session, entry["account"]["provider"], entry["account"], code,
                                                       entry["verifier"], entry["redirect_uri"]))

    def paste_token(entry, state, pasted):
        session = app.state.oauth_session()
        if entry["service"] == "spotify":
            return spotify.finish_manual(session, entry["account"]["client_id"], entry["redirect_uri"], entry["verifier"], state, pasted)
        return oauth.finish_manual(session, entry["account"]["provider"], entry["account"], entry["redirect_uri"], entry["verifier"], state, pasted)

    def store_connected(entry, token):
        """Set the refresh token (a new sign-in replaces whatever is stored) together with the client id it belongs to."""
        found = []
        def apply(data):
            integrations = data.setdefault("integrations", {})
            if entry["service"] == "spotify":
                integrations.setdefault("spotify", {}).update(refresh_token=token, client_id=entry["account"]["client_id"])
                found.append(True)
                return
            mail = migrate_conf(integrations.get("mail", {}))
            for account in mail.get("accounts", []) if isinstance(mail, dict) else []:
                if isinstance(account, dict) and account.get("id") == entry["account"].get("id"):
                    started = entry["account"]
                    if (account.get("provider"), account.get("tenant"), account.get("client_id")) != (
                            started.get("provider"), started.get("tenant"), started.get("stored_client_id")):
                        raise ValueError("The account changed during sign-in; start again")
                    account.update(refresh_token=token, client_id=entry["account"]["client_id"])
                    integrations["mail"] = mail
                    found.append(True)
                    return
        store.change(apply)
        if not found:
            raise ValueError("Account not found. Save the configuration and try again.")

    @app.post("/api/oauth/start")
    async def oauth_start(request: Request):
        values = await json_body(request)
        service = values.get("service")
        if service not in {"spotify", "mail"}:
            raise ValueError("Unknown service")
        integrations = store.snapshot().get("integrations", {})
        for key in ("client_id", "redirect_uri", "account_id"):
            if values.get(key) is not None and not isinstance(values[key], str):
                raise ValueError("Invalid " + key)
        if service == "spotify":
            stored = integrations.get("spotify", {})
            account = {"client_id": (values.get("client_id") or stored.get("client_id", "")).strip()}
            if not re.fullmatch(r"[A-Za-z0-9]{8,128}", account["client_id"]):
                raise ValueError("Enter the Spotify Client ID first")
        else:
            accounts = migrate_conf(integrations.get("mail", {})).get("accounts", [])
            stored = next((a for a in accounts if isinstance(a, dict) and a.get("id") == values.get("account_id")), None)
            if stored is None:
                raise ValueError("Unknown mail account. Save the configuration first.")
            if stored.get("provider") not in oauth.PROVIDERS:
                raise ValueError("This account does not use OAuth")
            account = {**stored, "client_id": (values.get("client_id") or stored.get("client_id", "")).strip(),
                       "stored_client_id": stored.get("client_id")}  # what the sign-in started from: it must not change meanwhile
            if not account["client_id"] or len(account["client_id"]) > 256 or not account["client_id"].isprintable() or " " in account["client_id"]:
                raise ValueError("Enter the Client ID first")
            if stored["provider"] == "google" and not account.get("client_secret"):
                raise ValueError("Enter the Client secret first")
        configured = (values.get("redirect_uri") or stored.get("redirect_uri", "")).strip()
        kind = spotify_redirect_kind(configured)
        if kind is None:
            raise ValueError("Invalid redirect URI: use an https address or leave it empty")
        if kind == "https":
            mode, redirect_uri = "manual", configured
        else:
            mode, redirect_uri = "loopback", str(request.base_url).rstrip("/") + "/api/oauth/callback"
            if not loopback_or_https(redirect_uri):
                raise ValueError("Open the portal through http://127.0.0.1:<port> (for example an SSH tunnel) or behind https, "
                                 "or set an https redirect URI and paste the address back.")
        state, url = pending_oauth.issue(service, mode, redirect_uri, account)
        return {"authorize_url": url, "state": state, "mode": mode, "redirect_uri": redirect_uri}

    @app.get("/api/oauth/callback")
    async def oauth_callback(request: Request):
        def page(status, message):  # static texts only: nothing from the request is ever reflected
            blob = ("<!doctype html><meta charset=utf-8><title>Keeper</title><p>" + message + "</p>").encode()
            return Response(blob, status_code=status, media_type="text/html", headers={"Content-Security-Policy": "default-src 'none'"})
        # A provider redirect is a top-level navigation. Subresource probes (img/fetch/iframe from any website) are refused
        # before any accounting and without consuming the state. Clients that send no Sec-Fetch headers are allowed.
        dest, mode = request.headers.get("sec-fetch-dest"), request.headers.get("sec-fetch-mode")
        if (dest is not None and dest != "document") or (mode is not None and mode != "navigate"):
            return page(400, OAUTH_INVALID)
        if oauth_limited(callback_failures):
            return page(429, "Too many attempts. Wait a minute and start again from Keeper.")
        query = request.query_params
        entry = pending_oauth.take(query.get("state", ""))
        if entry is None or entry["mode"] != "loopback":
            return page(400, OAUTH_INVALID)  # not counted: the 192-bit single-use state needs no limiter here
        code = query.get("code")
        if not code:
            return page(400, "The sign-in was not authorized.")
        try:
            token = await asyncio.to_thread(exchange_token, entry, code)
            await asyncio.to_thread(store_connected, entry, token)
        except Exception:
            callback_failures.append(clock())
            return page(502, OAUTH_FAILED)
        return page(200, "Connected. You can close this tab and return to Keeper.")

    @app.post("/api/oauth/complete")
    async def oauth_complete(request: Request):
        if oauth_limited(complete_failures):
            return JSONResponse({"error": "Too many attempts"}, status_code=429)
        values = await json_body(request)
        state, pasted = values.get("state"), values.get("pasted")
        if not isinstance(state, str) or not isinstance(pasted, str):
            raise ValueError("state and pasted are required")
        entry = pending_oauth.take(state)
        if entry is None or entry["mode"] != "manual":
            complete_failures.append(clock())
            return JSONResponse({"error": OAUTH_INVALID}, status_code=400)
        try:
            token = await asyncio.to_thread(paste_token, entry, state, pasted)
            await asyncio.to_thread(store_connected, entry, token)
        except ValueError as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        except (spotify.SpotifyError, oauth.OAuthError) as error:
            complete_failures.append(clock())
            return JSONResponse({"error": oauth_error(error)}, status_code=400)
        except Exception:
            complete_failures.append(clock())
            return JSONResponse({"error": OAUTH_FAILED}, status_code=400)
        return {"connected": True}

    if shell_mode:
        @app.post("/api/launch")
        async def launch(request: Request):
            denied = JSONResponse({"error": "Invalid or expired launch code"}, status_code=401)
            if host_name(request.headers.get("host")) not in LOOPBACK_HOSTS:
                return denied
            # Cross-site callers are rejected before the failure limiter so a website cannot burn the login attempts.
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"error": "Origin not allowed"}, status_code=403)
            if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                return JSONResponse({"error": "Content-Type must be application/json"}, status_code=415)
            if app.state.launch_codes.limited():
                return JSONResponse({"error": "Too many attempts"}, status_code=429)
            try:
                code = (await json_body(request)).get("code")
            except (ValueError, HTTPException):
                code = None
            if not isinstance(code, str) or not app.state.launch_codes.redeem(code):
                return denied
            return {"token": token}

        @app.get("/api/startup")
        def get_startup():
            return {"enabled": bool(store.snapshot().get("startup"))}

        @app.post("/api/startup")
        async def set_startup_route(request: Request):
            enabled = (await json_body(request)).get("enabled")
            if not isinstance(enabled, bool):
                raise ValueError("enabled must be true or false")
            from .startup import set_startup
            try:
                await asyncio.to_thread(set_startup, enabled, store.root)
            except OSError as error:
                raise ValueError("Could not change autostart: " + str(error))
            await asyncio.to_thread(store.change, lambda d: d.update(startup=enabled))
            return {"enabled": enabled}

        @app.post("/api/open")
        async def open_folder(request: Request):
            what = (await json_body(request)).get("what")
            targets = {"data": store.root, "library": store.media_dir}
            if what not in targets:
                raise ValueError("Unknown folder")
            return {"opened": bool(await asyncio.to_thread(app.state.open_external, targets[what]))}

        @app.post("/api/quit")
        def quit_keeper():
            return JSONResponse({"quitting": True}, background=BackgroundTask(app.state.quit_event.set))

    @app.get("/api/state")
    def state():
        data = store.snapshot()
        with engine.portal_lock:
            events = list(engine.activity)
        return {"config": data, "revision": revision(data), "events": events, "version": __version__, "desktop": shell_mode,
                "runtime": {"online": dict(engine.online), "pomodoro": engine.automations.pomodoro.snapshot(), "timesync": timesource.status()},
                "capabilities": {"mode": "server", "demo": demo, "pc": True, "music": True,
                    "profiles": True, "mqtt": True, "hardware": True, "continuous": True,
                    "metrics_label": "Metrics of the machine running the server; in Docker, of the container"}}

    @app.put("/api/config")
    async def put_config(request: Request):
        values = await json_body(request)
        data = values["config"]
        validate_portal(data, store.media_dir)
        def update():
            with store.lock:
                if values.get("revision") != revision(store.data):
                    raise ValueError("The configuration changed. Reload before saving to avoid overwriting changes.")
                previous = {d["id"] for d in store.data["devices"]}
                store.change(lambda current: (current.clear(), current.update(copy.deepcopy(data))))
            for gone in previous - {d["id"] for d in data["devices"]}:
                engine.forget_device(gone)  # runs on the engine thread (engine.enqueue below)
            # Preserve live Pomodoro and temporary notices; synchronize the runtime flags.
            engine.paused = {d["id"] for d in data["devices"] if d.get("suspended")}
            engine.power_off = {d["id"] for d in data["devices"] if d.get("screens_off")}
            for d in data["devices"]:
                engine.invalidate(d["id"])
            return {"revision": revision(store.snapshot())}
        return engine.enqueue("Save configuration", update)

    @app.post("/api/upload")
    async def upload(request: Request, name: str):
        suffix = Path(name).suffix.lower()
        if suffix not in MEDIA_EXTENSIONS:
            raise ValueError("Unsupported format")
        blob = await body(request, LIMIT)
        if not blob:
            raise ValueError("Empty file")
        if suffix not in VIDEO_EXTENSIONS | {".ics"}:
            with Image.open(io.BytesIO(blob)) as image:
                if image.width * image.height > 20_000_000:
                    raise ValueError("Maximum 20 megapixels")
                image.verify()
        path = save_blob(blob, suffix)
        return {"path": path, "name": Path(path).name, "original": Path(name).name}

    @app.get("/api/media/{name}")
    def media(name: str):
        return FileResponse(owned(name))

    @app.get("/api/library")
    def library():
        return [{"path": str(p), "name": p.name, "size": p.stat().st_size}
                for p in sorted(store.media_dir.iterdir()) if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS]

    @app.get("/api/jobs/{key}")
    def job(key: str):
        with engine.portal_lock:
            if key not in engine.tasks:
                raise HTTPException(404, "Task expired")
            return copy.deepcopy(engine.tasks[key])

    @app.post("/api/jobs/{key}/cancel")
    def cancel(key: str):
        event = cancelled.get(key)
        if event:
            event.set()
        return {"cancelled": bool(event)}

    @app.post("/api/panorama")
    async def panorama(request: Request):
        values = await json_body(request)
        path = owned(Path(values["path"]).name)
        if not conversion_slots.acquire(blocking=False):
            raise ValueError("Wait for the previous conversion")
        key = engine.new_task("Convert panorama")
        stop = cancelled[key] = threading.Event()
        def convert():
            engine.task_update(key, status="running")
            try:
                options = {k: values[k] for k in ("fit", "position", "zoom", "start", "duration", "fps", "rotation") if k in values}
                animated = path.suffix in VIDEO_EXTENSIONS
                if not animated:
                    with Image.open(path) as image:
                        animated = getattr(image, "is_animated", False)
                if animated:
                    clip = decode_clip(path, **options, stop=stop)
                    screens = [slot("media", path=save_blob(blob, ".gif"), fit="stretch", panorama_speed=clip["speed"])
                               for blob in clip["blobs"]]
                    preview = io.BytesIO()
                    clip["frames"][0].save(preview, "GIF", save_all=True, append_images=clip["frames"][1:],
                                          duration=clip["speed"], loop=0)
                    preview_path = save_blob(preview.getvalue(), ".gif")
                    count, duration = clip["count"], clip["duration"]
                else:
                    with Image.open(path) as image:
                        image = rgb(ImageOps.exif_transpose(image)).rotate(-int(options.get("rotation", 0)), expand=True)
                        canvas = panorama_canvas(image, options.get("fit", "cover"), options.get("position", (.5, .5)), options.get("zoom", 1))
                    screens = [slot("media", fit="stretch", path=save_blob(png_bytes(canvas.crop((i*128, 0, (i+1)*128, 128))), ".png")) for i in range(5)]
                    preview_path = save_blob(png_bytes(canvas), ".png")
                    count, duration = 1, 0
                if stop.is_set():
                    raise InterruptedError("Conversion cancelled")
                engine.task_update(key, status="done", result={"screens": screens, "preview": preview_path,
                    "count": count, "duration": duration, "animated": animated})
            except InterruptedError:
                engine.task_update(key, status="cancelled")
            except Exception as error:
                engine.task_update(key, status="error", error=str(error))
            finally:
                cancelled.pop(key, None)
                conversion_slots.release()
        converter.submit(convert)
        return {"job": key}

    @app.get("/api/preview/{device_id}/{panel}")
    def preview(device_id: str, panel: int):
        if panel not in range(5):
            raise ValueError("Invalid screen")
        if device_id not in {d['id'] for d in store.snapshot()['devices']}:
            raise HTTPException(404, "Unknown device")
        engine.submit("preview", device_id, panel=panel)
        with engine.portal_lock:
            blob = engine.previews.get((device_id, panel))
        return Response(blob or b"", media_type="image/png", status_code=200 if blob else 204)

    @app.post("/api/action")
    async def action(request: Request):
        values = await json_body(request)
        operation = values["action"]
        device_id = values.get("device_id") or store.snapshot()["active_device"]
        if device_id not in {d["id"] for d in store.snapshot()["devices"]}:
            raise ValueError("Unknown device")
        args = values.get("args", {})
        if operation not in {"send", "resume", "health", "scene", "notification", "pomodoro", "command", "discover", "catalog"}:
            raise ValueError("Unknown action")
        if "panel" in args and int(args["panel"]) not in range(5):
            raise ValueError("Invalid screen")
        if operation == "command":
            validate_command(args.get("payload", {}))
        if operation == "notification" and (not 5 <= int(args.get("seconds", 15)) <= 300 or len(str(args.get("text", ""))) > 500):
            raise ValueError("Invalid notice")
        if operation == "discover" and args.get("seed"):
            valid_ip(args["seed"])
        return engine.enqueue(operation, lambda: engine.process(operation, device_id, copy.deepcopy(args)))

    @app.get("/api/export")
    def export():
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "backup.zip"
            store.export(path)
            return Response(path.read_bytes(), media_type="application/zip",
                            headers={"Content-Disposition": 'attachment; filename="Keeper-backup.zip"'})

    @app.post("/api/import")
    async def import_bundle(request: Request):
        blob = await body(request, LIMIT)
        def load():
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "backup.zip"
                path.write_bytes(blob)
                trial = ConfigStore(Path(temp) / "trial", migrate=False)
                trial.import_bundle(path)
                validate_portal(trial.snapshot(), trial.media_dir)
                store.import_bundle(path)
                engine.process("reset_runtime", None, {})
            return {"imported": True}
        return engine.enqueue("Import backup", load)

    directory = Path(web_root or Path(__file__).resolve().parents[1] / "web/dist")
    if directory.exists():
        app.mount("/", StaticFiles(directory=directory, html=True), name="portal")
    return app


def validate_command(payload):
    if payload.get('Command') == 'Channel/SetRGBInfo':
        from .lighting import from_payload
        from_payload(payload)
        return
    commands = {
        "Channel/GetAllConf": {}, "Device/SysReboot": {}, "Channel/SetBrightness": {"Brightness": (0, 100)},
        "Channel/OnOffScreen": {"OnOff": (0, 1)}, "Channel/Set5LcdBrightness": {"Brightness": (0, 100)},
        "Tools/SetTimer": {"Minute": (0, 999), "Second": (0, 59), "Status": (0, 1)},
        "Tools/SetStopWatch": {"Status": (0, 2)}, "Tools/SetScoreBoard": {"RedScore": (0, 999), "BlueScore": (0, 999)},
        "Tools/SetNoiseStatus": {"NoiseStatus": (0, 1)},
        "Device/PlayBuzzer": {"ActiveTimeInCycle": (0, 10000), "OffTimeInCycle": (0, 10000), "PlayTotalTime": (0, 10000)},
        "Channel/SetClockSelectId": {"ClockId": (1, 10000000), "LcdIndependence": (1, 100000000), "LcdIndex": (0, 4)},
    }
    name = payload.get("Command")
    if name not in commands:
        raise ValueError("Unsupported command")
    for key, (low, high) in commands[name].items():
        if key not in payload or not low <= int(payload[key]) <= high:
            raise ValueError("Invalid parameter: " + key)
    if set(payload) - {"Command", "DeviceId", *commands[name]}:
        raise ValueError("Unknown parameter")
