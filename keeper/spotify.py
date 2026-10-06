"""Spotify Web API client (read-only "now playing"). OAuth Authorization Code with PKCE, no client secret.

Checked against the official docs on 2026-10-06 (developer.spotify.com):
  VERIFIED  authorize: GET https://accounts.spotify.com/authorize with client_id, response_type=code, redirect_uri,
            code_challenge, code_challenge_method=S256, scope (space separated), state.
  VERIFIED  token: POST https://accounts.spotify.com/api/token, application/x-www-form-urlencoded.
            Exchange: grant_type=authorization_code, code, redirect_uri, client_id, code_verifier.
            Refresh (PKCE): grant_type=refresh_token, refresh_token, client_id. No client secret anywhere.
            Responses carry access_token, expires_in (3600) and sometimes a NEW refresh_token (keep the old one
            otherwise); refresh does not extend the 6 month refresh token life; invalid_grant = discard and reconnect.
  VERIFIED  redirect URIs: https, or http only on loopback IP literals (http://127.0.0.1:PORT/path, http://[::1]:PORT/path);
            "localhost" is not accepted; for loopback the port may be left out of the registered URI and supplied
            at authorize time.
  VERIFIED  GET https://api.spotify.com/v1/me/player/currently-playing (scope user-read-currently-playing; optional
            additional_types=track,episode); statuses 200/401/403/429; 429 Retry-After is in seconds; fields is_playing,
            progress_ms, currently_playing_type (track|episode|ad|unknown), item.
  RECALLED  (not stated on the pages read) 204 = nothing playing; item.name, item.artists[].name, item.duration_ms,
            item.album.images[{url,width,height}]; episodes use item.show.publisher/name and item.images; ads may
            have item = null. user-read-playback-state is requested as in the plan but is not needed for this endpoint.
  RECALLED  album art is served from i.scdn.co (also *.scdn.co and *.spotifycdn.com are accepted here).
No real Spotify account has been used; the code is exercised with a fake session only.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import re
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode, urlparse

import requests

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
NOW_PLAYING_URL = "https://api.spotify.com/v1/me/player/currently-playing"
SCOPES = "user-read-currently-playing user-read-playback-state"
FORBIDDEN = "forbidden — add this account in the Spotify app's User Management (development mode)"
FORBIDDEN_BACKOFF = 300
ART_LIMIT = 1024 * 1024
TIMEOUT = 8


class SpotifyError(Exception):
    """Messages are short fixed text; they never include tokens, codes or response bodies."""


class SpotifyAuthError(SpotifyError):
    pass


class SpotifyRateLimited(SpotifyError):
    def __init__(self, retry_after):
        super().__init__("rate limited")
        self.retry_after = retry_after


def redact(text, *secrets_):
    text = str(text)
    for value in secrets_:
        if value:
            text = text.replace(value, "[redacted]")
    return text


def make_pkce_pair():
    verifier = secrets.token_urlsafe(64)[:96]  # 43-128 characters from the unreserved set
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(client_id, redirect_uri, state, challenge):
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri, "scope": SCOPES,
        "state": state, "code_challenge_method": "S256", "code_challenge": challenge})


def _token_request(session, payload, secrets_):
    try:
        response = session.post(TOKEN_URL, data=payload, timeout=TIMEOUT,
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
    except requests.RequestException:
        raise SpotifyError("cannot reach Spotify") from None
    if response.status_code == 429:
        raise SpotifyRateLimited(_retry_after(response))
    if response.status_code != 200:
        code = ""
        try:
            value = response.json().get("error", "")
            code = value if isinstance(value, str) and re.fullmatch(r"[a-z_]{1,40}", value) else ""
        except ValueError:
            pass
        raise SpotifyAuthError(redact(f"token request failed (HTTP {response.status_code}{': ' + code if code else ''})", *secrets_))
    try:
        data = response.json()
        token, expires = data["access_token"], int(data.get("expires_in", 3600))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise SpotifyError("unexpected token response") from None
    refresh = data.get("refresh_token")
    return {"access_token": token, "expires_in": expires, "refresh_token": refresh if isinstance(refresh, str) and refresh else None}


def exchange_code(session, client_id, code, verifier, redirect_uri):
    return _token_request(session, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                                    "client_id": client_id, "code_verifier": verifier}, (code, verifier))


def refresh_access_token(session, client_id, refresh_token):
    return _token_request(session, {"grant_type": "refresh_token", "refresh_token": refresh_token,
                                    "client_id": client_id}, (refresh_token,))


def _retry_after(response):
    try:
        return max(1, min(3600, int(float(response.headers.get("Retry-After", 5)))))
    except (ValueError, TypeError):
        return 5


def _clean(text, limit=120):
    return "".join(c if c.isprintable() else " " for c in str(text or "")).strip()[:limit]


def pick_image(images):
    """Smallest image that is at least 64 px wide; otherwise the largest one available."""
    usable = [i for i in images or [] if isinstance(i, dict) and isinstance(i.get("url"), str)]
    sized = sorted((i for i in usable if isinstance(i.get("width"), int)), key=lambda i: i["width"])
    big = [i for i in sized if i["width"] >= 64]
    if big:
        return big[0]["url"]
    if sized:
        return sized[-1]["url"]
    return usable[0]["url"] if usable else ""


def fetch_now_playing(session, access_token):
    """Normalised dict, None when nothing is playing (204), or raises SpotifyAuthError / SpotifyRateLimited / SpotifyError."""
    try:
        response = session.get(NOW_PLAYING_URL, params={"additional_types": "track,episode"}, timeout=TIMEOUT,
                               headers={"Authorization": "Bearer " + access_token})
    except requests.RequestException:
        raise SpotifyError("cannot reach Spotify") from None
    status = response.status_code
    if status == 204:
        return None
    if status == 401:
        raise SpotifyAuthError("expired")
    if status == 403:
        raise SpotifyAuthError("forbidden")
    if status == 429:
        raise SpotifyRateLimited(_retry_after(response))
    if status != 200:
        raise SpotifyError(f"HTTP {status}")
    try:
        data = response.json()
    except ValueError:
        return None  # an empty 200 body also means nothing is playing
    if not isinstance(data, dict):
        return None
    kind = data.get("currently_playing_type")
    item = data.get("item") if isinstance(data.get("item"), dict) else None
    result = {"title": "", "artist": "", "playing": bool(data.get("is_playing")), "type": kind or "unknown",
              "progress_ms": int(data.get("progress_ms") or 0), "duration_ms": 0, "image_url": ""}
    if item is None:
        if kind == "ad":
            result["title"] = "Advertisement"
            return result
        return None
    result["title"] = _clean(item.get("name"))
    result["duration_ms"] = int(item.get("duration_ms") or 0)
    if kind == "episode" or item.get("type") == "episode":
        show = item.get("show") if isinstance(item.get("show"), dict) else {}
        result["artist"] = _clean(show.get("publisher") or show.get("name"))
        result["image_url"] = pick_image(item.get("images") or show.get("images"))
    else:
        artists = item.get("artists") if isinstance(item.get("artists"), list) else []
        result["artist"] = _clean(", ".join(a.get("name", "") for a in artists if isinstance(a, dict)))
        album = item.get("album") if isinstance(item.get("album"), dict) else {}
        result["image_url"] = pick_image(album.get("images"))
    return result


def allowed_art_url(url):
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    ok = host in {"scdn.co", "spotifycdn.com"} or host.endswith((".scdn.co", ".spotifycdn.com"))
    return parsed.scheme == "https" and ok and not parsed.username and parsed.port in (None, 443)


def fetch_art(session, url):
    """Image bytes (at most 1 MB) from a Spotify CDN host, or None."""
    if not allowed_art_url(url):
        return None
    try:
        with session.get(url, timeout=TIMEOUT, stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                return None
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > ART_LIMIT:
                    return None
                chunks.append(chunk)
            return b"".join(chunks) or None
    except requests.RequestException:
        return None


class SpotifySource:
    """Holds the access token in memory only. The refresh token is handed to `on_refresh_token` when Spotify rotates it."""

    def __init__(self, client_id, refresh_token, on_refresh_token=None, session=None, clock=time.monotonic):
        self.client_id, self.refresh_token, self.initial_token = client_id, refresh_token, refresh_token
        self.on_refresh_token = on_refresh_token
        self.session = session or requests.Session()
        self.clock = clock
        self.access_token, self.expires = "", 0.0
        self.blocked_until, self.last = 0.0, None
        self.dead, self.forbidden = False, False  # `dead`: refresh token rejected; only a rebuilt source (new token) clears it
        self.art_url, self.art = "", ""

    def _refresh(self):
        data = refresh_access_token(self.session, self.client_id, self.refresh_token)
        self.access_token, self.expires = data["access_token"], self.clock() + data["expires_in"] - 60
        if data["refresh_token"] and data["refresh_token"] != self.refresh_token:
            old = self.refresh_token
            self.refresh_token = data["refresh_token"]
            if self.on_refresh_token:
                self.on_refresh_token(self.refresh_token, old)

    def _art(self, url):
        if url != self.art_url:  # one image per track, fetched once; only the current one is kept
            blob = fetch_art(self.session, url) if url else None
            self.art_url, self.art = url, base64.b64encode(blob).decode("ascii") if blob else ""
        return self.art

    def poll(self):
        """{"idle": True} when nothing plays, else the track dict plus "art" (base64) and "sampled"."""
        if self.dead:
            raise SpotifyAuthError("reconnect")  # no network call until the user reconnects
        now = self.clock()
        if now < self.blocked_until:
            if self.forbidden:
                raise SpotifyAuthError(FORBIDDEN)
            if self.last is None:
                raise SpotifyRateLimited(int(self.blocked_until - now) + 1)
            return self.last
        try:
            if not self.access_token or now >= self.expires:
                self._refresh()
            try:
                track = fetch_now_playing(self.session, self.access_token)
            except SpotifyAuthError as error:
                if str(error) != "expired":
                    raise
                self._refresh()  # once; a second 401 propagates as "expired" and means reconnect
                track = fetch_now_playing(self.session, self.access_token)
        except SpotifyRateLimited as error:
            self.blocked_until, self.forbidden = self.clock() + error.retry_after, False
            if self.last is None:
                raise
            return self.last
        except SpotifyAuthError as error:
            if str(error) == "forbidden":  # the token itself is fine; the account is not allowed
                self.forbidden, self.blocked_until = True, self.clock() + FORBIDDEN_BACKOFF
                raise SpotifyAuthError(FORBIDDEN) from None
            self.access_token = ""
            if str(error) == "expired" or re.search(r"HTTP 4\d\d", str(error)):
                self.dead = True
                raise SpotifyAuthError("reconnect") from None
            raise SpotifyError("cannot refresh the Spotify token") from None  # 5xx: transient, retried at the normal pace
        if track is None:
            self.last = {"idle": True}
        else:
            self.last = {**track, "art": self._art(track["image_url"]), "sampled": self.clock()}
        return self.last


class _Callback(BaseHTTPRequestHandler):
    timeout = 5  # a local client that connects and stalls must not block the flow's deadline

    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urlparse(self.path)
        if url.path != "/callback":
            return self._reply(404, "Not found")
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if not hmac.compare_digest(query.get("state", "").encode(), self.server.state.encode()):
            return self._reply(400, "Invalid state. Return to Keeper and try again.")
        self.server.outcome = (query.get("code", ""), query.get("error", ""))
        self._reply(200, "Spotify connected. You can close this tab and return to Keeper." if query.get("code")
                    else "Spotify did not authorize Keeper. You can close this tab.")

    def _reply(self, status, message):
        blob = ("<!doctype html><meta charset=utf-8><title>Keeper</title><p>" + message + "</p>").encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(blob)


def connect_loopback(client_id, opener, session=None, timeout=180, on_ready=None):
    """Desktop flow: one-shot server on 127.0.0.1 (random port), browser opened through `opener(url)`.

    Returns the refresh token. Always closes the server. `on_ready(redirect_uri)` is called once the port is known.
    """
    session = session or requests.Session()
    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(24)
    server = HTTPServer(("127.0.0.1", 0), _Callback)
    server.state, server.outcome, server.timeout = state, None, 0.5
    try:
        redirect_uri = f"http://127.0.0.1:{server.server_address[1]}/callback"
        if on_ready:
            on_ready(redirect_uri)
        if not opener(build_authorize_url(client_id, redirect_uri, state, challenge)):
            raise SpotifyError("could not open the browser")
        deadline = time.monotonic() + timeout
        while server.outcome is None and time.monotonic() < deadline:
            server.handle_request()
        if server.outcome is None:
            raise SpotifyError("timed out waiting for Spotify")
        code, error = server.outcome
        if not code:
            raise SpotifyError("Spotify did not authorize Keeper" + (": " + error[:40] if re.fullmatch(r"[a-z_]{1,40}", error) else ""))
        data = exchange_code(session, client_id, code, verifier, redirect_uri)
        if not data["refresh_token"]:
            raise SpotifyError("Spotify returned no refresh token")
        return data["refresh_token"]
    finally:
        server.server_close()


PASTE_LIMIT = 2048


def begin_manual(client_id, redirect_uri):
    """Paste-back flow, step 1: (authorize_url, verifier, state). The caller keeps verifier and state in memory."""
    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(24)
    return build_authorize_url(client_id, redirect_uri, state, challenge), verifier, state


def finish_manual(session, client_id, redirect_uri, verifier, state, pasted):
    """Paste-back flow, step 2: the full redirected address (or its `code=...&state=...` query) -> refresh token."""
    text = str(pasted or "").strip()
    if not text or len(text) > PASTE_LIMIT:
        raise SpotifyError("the pasted address is empty or too long")
    query = urlparse(text).query if "://" in text else text.split("#", 1)[0].split("?", 1)[-1]
    params = {k: v[0] for k, v in parse_qs(query).items()}
    if params.get("error"):
        raise SpotifyError("Spotify did not authorize Keeper")
    got = params.get("state", "")
    if not got or not hmac.compare_digest(got.encode(), state.encode()):
        raise SpotifyError("the pasted address does not belong to this connection attempt; start again")
    code = params.get("code", "")
    if not code:
        raise SpotifyError("the pasted address has no authorization code")
    data = exchange_code(session, client_id, code, verifier, redirect_uri)
    if not data["refresh_token"]:
        raise SpotifyError("Spotify returned no refresh token")
    return data["refresh_token"]


class PendingAuth:
    """Server mode: PKCE verifiers keyed by single-use `state`, valid for 5 minutes, bounded."""
    TTL, LIMIT = 300, 20

    def __init__(self, clock=time.monotonic):
        self.clock, self.items, self.lock = clock, {}, threading.Lock()

    def issue(self, client_id, redirect_uri):
        verifier, challenge = make_pkce_pair()
        state = secrets.token_urlsafe(24)
        now = self.clock()
        with self.lock:
            self.items = {k: v for k, v in self.items.items() if v[3] > now}
            while len(self.items) >= self.LIMIT:
                self.items.pop(next(iter(self.items)))
            self.items[state] = (verifier, client_id, redirect_uri, now + self.TTL)
        return state, build_authorize_url(client_id, redirect_uri, state, challenge)

    def take(self, state):
        """(verifier, client_id, redirect_uri) or None; always consumes the state."""
        with self.lock:
            item = self.items.pop(state, None)
        if item is None or item[3] <= self.clock():
            return None
        return item[:3]
