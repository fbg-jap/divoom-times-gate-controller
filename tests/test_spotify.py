import base64
import hashlib
import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
import unittest.mock
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from PIL import Image

from keeper import spotify
from keeper.config import defaults, validate
from keeper.portal import create_app
from keeper.widgets import Providers, Renderer
from keeper.config import slot

TOKEN = "unit-test-token-at-least-24-characters"


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None, chunks=None):
        self.status_code, self.body, self.headers, self.chunks = status, body, headers or {}, chunks

    def json(self):
        if self.body is None:
            raise ValueError("no body")
        return self.body

    def iter_content(self, size):
        yield from (self.chunks if self.chunks is not None else [b"x"])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeSession:
    """Answers by URL prefix from queues; records every call. No network."""
    def __init__(self, token=(), playing=(), art=()):
        self.queues = {spotify.TOKEN_URL: list(token), spotify.NOW_PLAYING_URL: list(playing)}
        self.art, self.calls = list(art), []

    def post(self, url, data=None, **kw):
        self.calls.append(("post", url, dict(data or {}), kw))
        return self.queues[url].pop(0)

    def get(self, url, **kw):
        self.calls.append(("get", url, None, kw))
        if url in self.queues:
            return self.queues[url].pop(0)
        return self.art.pop(0)

    def of(self, method, url):
        return [c for c in self.calls if c[0] == method and c[1] == url]


def token(access="ACCESS-1", refresh=None, expires=3600):
    body = {"access_token": access, "token_type": "Bearer", "expires_in": expires}
    if refresh:
        body["refresh_token"] = refresh
    return FakeResponse(200, body)


def track(**over):
    item = {"name": "Song", "duration_ms": 200000, "artists": [{"name": "A"}, {"name": "B"}],
            "album": {"images": [{"url": "https://i.scdn.co/image/big", "width": 640},
                                 {"url": "https://i.scdn.co/image/mid", "width": 300},
                                 {"url": "https://i.scdn.co/image/small", "width": 64}]}}
    return FakeResponse(200, {"is_playing": True, "progress_ms": 1000, "currently_playing_type": "track", "item": item, **over})


class ProtocolTests(unittest.TestCase):
    def test_pkce_pair(self):
        verifier, challenge = spotify.make_pkce_pair()
        self.assertTrue(43 <= len(verifier) <= 128)
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        self.assertEqual(challenge, expected)
        self.assertNotIn("=", challenge)
        self.assertNotEqual(verifier, spotify.make_pkce_pair()[0])

    def test_authorize_url(self):
        url = urlparse(spotify.build_authorize_url("cid", "http://127.0.0.1:5/callback", "st", "chal"))
        self.assertEqual((url.scheme, url.netloc, url.path), ("https", "accounts.spotify.com", "/authorize"))
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.assertEqual(q, {"client_id": "cid", "response_type": "code", "redirect_uri": "http://127.0.0.1:5/callback",
                             "scope": "user-read-currently-playing user-read-playback-state", "state": "st",
                             "code_challenge_method": "S256", "code_challenge": "chal"})

    def test_exchange_and_refresh_payloads_have_no_secret(self):
        session = FakeSession(token=[token(refresh="R1"), token("ACCESS-2")])
        data = spotify.exchange_code(session, "cid", "CODE", "VERIFIER", "http://127.0.0.1:5/callback")
        self.assertEqual(data["refresh_token"], "R1")
        spotify.refresh_access_token(session, "cid", "R1")
        exchange, refresh = [c[2] for c in session.of("post", spotify.TOKEN_URL)]
        self.assertEqual(exchange, {"grant_type": "authorization_code", "code": "CODE", "redirect_uri": "http://127.0.0.1:5/callback",
                                    "client_id": "cid", "code_verifier": "VERIFIER"})
        self.assertEqual(refresh, {"grant_type": "refresh_token", "refresh_token": "R1", "client_id": "cid"})
        for payload in (exchange, refresh):
            self.assertFalse(any("secret" in k for k in payload))

    def test_errors_never_contain_tokens(self):
        session = FakeSession(token=[FakeResponse(400, {"error": "invalid_grant", "error_description": "Bad CODE-SECRET"})])
        with self.assertRaises(spotify.SpotifyAuthError) as caught:
            spotify.exchange_code(session, "cid", "CODE-SECRET", "VERIFIER-SECRET", "u")
        self.assertIn("invalid_grant", str(caught.exception))
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertEqual(spotify.redact("a CODE-SECRET b", "CODE-SECRET", ""), "a [redacted] b")

    def test_now_playing_shapes(self):
        playing = spotify.fetch_now_playing(FakeSession(playing=[track()]), "T")
        self.assertEqual((playing["title"], playing["artist"], playing["playing"], playing["progress_ms"], playing["duration_ms"]),
                         ("Song", "A, B", True, 1000, 200000))
        self.assertEqual(playing["image_url"], "https://i.scdn.co/image/small")  # smallest >= 64 px
        self.assertIsNone(spotify.fetch_now_playing(FakeSession(playing=[FakeResponse(204)]), "T"))
        episode = FakeResponse(200, {"is_playing": False, "currently_playing_type": "episode", "item": {
            "type": "episode", "name": "Ep", "show": {"publisher": "Pub"}, "images": [{"url": "https://i.scdn.co/e", "width": 300}]}})
        item = spotify.fetch_now_playing(FakeSession(playing=[episode]), "T")
        self.assertEqual((item["title"], item["artist"], item["playing"]), ("Ep", "Pub", False))
        ad = FakeResponse(200, {"is_playing": True, "currently_playing_type": "ad", "item": None})
        self.assertEqual(spotify.fetch_now_playing(FakeSession(playing=[ad]), "T")["title"], "Advertisement")
        session = FakeSession(playing=[track()])
        spotify.fetch_now_playing(session, "T")
        self.assertEqual(session.calls[0][3]["headers"], {"Authorization": "Bearer T"})
        self.assertEqual(spotify.pick_image([{"url": "u", "width": 32}, {"url": "v", "width": 48}]), "v")
        self.assertEqual(spotify.pick_image([]), "")

    def test_statuses(self):
        for status, error in ((401, "expired"), (403, "forbidden")):
            with self.assertRaises(spotify.SpotifyAuthError) as caught:
                spotify.fetch_now_playing(FakeSession(playing=[FakeResponse(status)]), "T")
            self.assertEqual(str(caught.exception), error)
        with self.assertRaises(spotify.SpotifyRateLimited) as caught:
            spotify.fetch_now_playing(FakeSession(playing=[FakeResponse(429, headers={"Retry-After": "7"})]), "T")
        self.assertEqual(caught.exception.retry_after, 7)
        with self.assertRaises(spotify.SpotifyError):
            spotify.fetch_now_playing(FakeSession(playing=[FakeResponse(500)]), "T")


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.now = [100.]
        self.saved = []

    def source(self, session):
        return spotify.SpotifySource("cid", "R0", self.saved.append, session, lambda: self.now[0])

    def test_refreshes_once_on_401_then_succeeds(self):
        session = FakeSession(token=[token("A1"), token("A2", refresh="R1")], playing=[FakeResponse(401), track()],
                              art=[FakeResponse(200, chunks=[b"img"])])
        source = self.source(session)
        result = source.poll()
        self.assertEqual(result["title"], "Song")
        self.assertEqual(len(session.of("post", spotify.TOKEN_URL)), 2)
        self.assertEqual(self.saved, ["R1"])  # rotated refresh token is persisted
        self.assertEqual(session.of("get", spotify.NOW_PLAYING_URL)[1][3]["headers"]["Authorization"], "Bearer A2")

    def test_second_401_means_reconnect_and_does_not_loop(self):
        session = FakeSession(token=[token("A1"), token("A2")], playing=[FakeResponse(401), FakeResponse(401)])
        with self.assertRaises(spotify.SpotifyAuthError) as caught:
            self.source(session).poll()
        self.assertEqual(str(caught.exception), "reconnect")
        self.assertEqual(len(session.of("post", spotify.TOKEN_URL)), 2)

    def test_invalid_grant_on_refresh_means_reconnect(self):
        session = FakeSession(token=[FakeResponse(400, {"error": "invalid_grant"})])
        with self.assertRaises(spotify.SpotifyAuthError) as caught:
            self.source(session).poll()
        self.assertEqual(str(caught.exception), "reconnect")
        self.assertNotIn("R0", str(caught.exception))

    def test_token_reused_until_expiry_and_204_is_idle(self):
        session = FakeSession(token=[token("A1", expires=3600), token("A2")], playing=[FakeResponse(204), FakeResponse(204), FakeResponse(204)])
        source = self.source(session)
        self.assertEqual(source.poll(), {"idle": True})
        source.poll()
        self.assertEqual(len(session.of("post", spotify.TOKEN_URL)), 1)
        self.now[0] += 3600
        source.poll()
        self.assertEqual(len(session.of("post", spotify.TOKEN_URL)), 2)

    def test_429_honours_retry_after_without_calling(self):
        session = FakeSession(token=[token()], playing=[track(), FakeResponse(429, headers={"Retry-After": "30"}), FakeResponse(204)],
                              art=[FakeResponse(200, chunks=[b"i"])])
        source = self.source(session)
        first = source.poll()
        self.now[0] += 5
        self.assertEqual(source.poll(), first)  # limited: the last value is kept
        calls = len(session.of("get", spotify.NOW_PLAYING_URL))
        self.now[0] += 10
        self.assertEqual(source.poll(), first)
        self.assertEqual(len(session.of("get", spotify.NOW_PLAYING_URL)), calls)  # still blocked
        self.now[0] += 25
        self.assertEqual(source.poll(), {"idle": True})

    def test_429_without_previous_value_raises(self):
        source = self.source(FakeSession(token=[token()], playing=[FakeResponse(429, headers={"Retry-After": "9"})]))
        with self.assertRaises(spotify.SpotifyRateLimited):
            source.poll()
        with self.assertRaises(spotify.SpotifyRateLimited):
            source.poll()

    def test_art_fetched_once_per_track(self):
        session = FakeSession(token=[token()], playing=[track(), track(), track()],
                              art=[FakeResponse(200, chunks=[b"PNGDATA"])])
        source = self.source(session)
        for _ in range(3):
            result = source.poll()
        self.assertEqual(base64.b64decode(result["art"]), b"PNGDATA")
        self.assertEqual(len(session.art), 0)  # exactly one image request was consumed (a second would raise)
        self.assertEqual(len([c for c in session.calls if c[1].startswith("https://i.scdn.co")]), 1)

    def test_art_host_validation_and_size_cap(self):
        for url in ("http://i.scdn.co/a", "https://evil.example/a", "https://i.scdn.co.evil.example/a", "https://user@i.scdn.co/a",
                    "https://scdn.co.evil/x", "", "https://i.scdn.co:8443/a", "file:///etc/passwd"):
            session = FakeSession()
            self.assertIsNone(spotify.fetch_art(session, url), url)
            self.assertEqual(session.calls, [], url)
        for url in ("https://i.scdn.co/a", "https://mosaic.scdn.co/a", "https://image-cdn-ak.spotifycdn.com/a"):
            self.assertEqual(spotify.fetch_art(FakeSession(art=[FakeResponse(200, chunks=[b"ok"])]), url), b"ok", url)
        big = FakeResponse(200, chunks=[b"x" * 600000, b"x" * 600000])
        self.assertIsNone(spotify.fetch_art(FakeSession(art=[big]), "https://i.scdn.co/a"))
        session = FakeSession(art=[FakeResponse(200, chunks=[b"x"])])
        spotify.fetch_art(session, "https://i.scdn.co/a")
        self.assertFalse(session.calls[0][3]["allow_redirects"])


class LoopbackTests(unittest.TestCase):
    def opener(self, behaviour):
        """Returns an opener that performs the browser's callback request from a thread."""
        self.seen = {}
        def open_url(url):
            q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
            self.seen = {"url": url, **q}
            def browser():
                base = q["redirect_uri"]
                for suffix in behaviour(q):
                    try:
                        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                        with opener.open(base + suffix, timeout=3) as r:
                            self.seen.setdefault("statuses", []).append(r.status)
                    except urllib.error.HTTPError as error:
                        self.seen.setdefault("statuses", []).append(error.code)
                    except OSError:
                        self.seen.setdefault("statuses", []).append("closed")
            self.thread = threading.Thread(target=browser, daemon=True)
            self.thread.start()
            return True
        return open_url

    def test_successful_flow_validates_state_and_exchanges(self):
        session = FakeSession(token=[token("A", refresh="REFRESH-NEW")])
        result = spotify.connect_loopback("cid", self.opener(lambda q: ["?code=C1&state=wrong", "?code=C2&state=" + q["state"]]), session, timeout=10)
        self.assertEqual(result, "REFRESH-NEW")
        self.thread.join(5)
        self.assertEqual(self.seen["statuses"], [400, 200])  # forged state rejected, real one accepted
        payload = session.of("post", spotify.TOKEN_URL)[0][2]
        self.assertEqual(payload["code"], "C2")
        self.assertEqual(payload["redirect_uri"], self.seen["redirect_uri"])
        self.assertRegex(self.seen["redirect_uri"], r"^http://127\.0\.0\.1:\d+/callback$")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(payload["code_verifier"].encode()).digest()).decode().rstrip("=")
        self.assertEqual(challenge, self.seen["code_challenge"])

    def test_denied_by_user(self):
        with self.assertRaises(spotify.SpotifyError) as caught:
            spotify.connect_loopback("cid", self.opener(lambda q: ["?error=access_denied&state=" + q["state"]]), FakeSession(), timeout=10)
        self.assertIn("access_denied", str(caught.exception))

    def test_timeout_and_server_is_closed(self):
        ports = []
        started = time.monotonic()
        with self.assertRaises(spotify.SpotifyError) as caught:
            spotify.connect_loopback("cid", lambda url: True, FakeSession(), timeout=1,
                                     on_ready=lambda uri: ports.append(int(urlparse(uri).port)))
        self.assertIn("timed out", str(caught.exception))
        self.assertLess(time.monotonic() - started, 6)
        import socket
        with socket.socket() as probe:
            self.assertNotEqual(probe.connect_ex(("127.0.0.1", ports[0])), 0)  # nothing listens any more

    def test_browser_failure_closes_server(self):
        with self.assertRaises(spotify.SpotifyError):
            spotify.connect_loopback("cid", lambda url: False, FakeSession(), timeout=1)

    def test_binds_loopback_only(self):
        hosts = []
        real = spotify.HTTPServer
        class Spy(real):
            def __init__(self, address, handler):
                hosts.append(address[0]); super().__init__(address, handler)
        spotify.HTTPServer = Spy
        try:
            with self.assertRaises(spotify.SpotifyError):
                spotify.connect_loopback("cid", lambda url: False, FakeSession(), timeout=1)
        finally:
            spotify.HTTPServer = real
        self.assertEqual(hosts, ["127.0.0.1"])


class PendingAuthTests(unittest.TestCase):
    def test_single_use_and_expiry(self):
        now = [0.]
        pending = spotify.PendingAuth(lambda: now[0])
        state, url = pending.issue("cid", "http://127.0.0.1/api/spotify/callback")
        self.assertIn("state=" + state, url)
        self.assertIsNotNone(pending.take(state))
        self.assertIsNone(pending.take(state))
        state, _ = pending.issue("cid", "r")
        now[0] = 301
        self.assertIsNone(pending.take(state))
        self.assertIsNone(pending.take("unknown"))

    def test_bounded(self):
        pending = spotify.PendingAuth()
        for _ in range(50):
            pending.issue("cid", "r")
        self.assertLessEqual(len(pending.items), spotify.PendingAuth.LIMIT)


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Path(self.temp.name), token=TOKEN, demo=True)
        self.client = TestClient(self.app, base_url="http://127.0.0.1:8000").__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.auth = {"Authorization": "Bearer " + TOKEN}
        self.app.state.spotify_session = lambda: FakeSession(token=[token("A", refresh="PORTAL-REFRESH")])

    def connect(self, **body):
        return self.client.post("/api/spotify/connect", json={"client_id": "abcdef1234567890", **body}, headers=self.auth)

    def test_connect_requires_token(self):
        self.assertEqual(self.client.post("/api/spotify/connect", json={}).status_code, 401)
        self.assertEqual(self.client.post("/api/spotify/connect", json={}, headers={"Authorization": "Bearer nope"}).status_code, 401)

    def test_callback_is_the_only_public_api_route(self):
        for method, path in (("get", "/api/state"), ("get", "/api/spotify/callback/x"), ("post", "/api/spotify/callback"),
                             ("get", "/api/spotify/connect"), ("get", "/api/jobs/x")):
            self.assertEqual(getattr(self.client, method)(path).status_code, 401, path)
        self.assertEqual(self.client.get("/api/spotify/callback?code=c&state=nope").status_code, 400)

    def test_full_flow_stores_refresh_token_and_state_is_single_use(self):
        r = self.connect()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["redirect_uri"], "http://127.0.0.1:8000/api/spotify/callback")
        state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
        ok = self.client.get(f"/api/spotify/callback?code=CODE&state={state}")  # no Authorization header
        self.assertEqual(ok.status_code, 200, ok.text)
        saved = self.app.state.store.snapshot()["integrations"]["spotify"]
        self.assertEqual((saved["refresh_token"], saved["client_id"]), ("PORTAL-REFRESH", "abcdef1234567890"))
        self.assertEqual(self.client.get(f"/api/spotify/callback?code=CODE&state={state}").status_code, 400)  # reused
        self.assertNotIn("PORTAL-REFRESH", ok.text)

    def test_unknown_and_expired_state_rejected(self):
        self.assertEqual(self.client.get("/api/spotify/callback?code=c&state=never-issued").status_code, 400)
        self.assertEqual(self.client.get("/api/spotify/callback?code=c").status_code, 400)
        state = parse_qs(urlparse(self.connect().json()["url"]).query)["state"][0]
        verifier, client_id, uri, _ = self.app.state.spotify_pending.items[state]
        self.app.state.spotify_pending.items[state] = (verifier, client_id, uri, time.monotonic() - 1)
        self.assertEqual(self.client.get(f"/api/spotify/callback?code=c&state={state}").status_code, 400)
        self.assertEqual(self.app.state.store.snapshot()["integrations"]["spotify"]["refresh_token"], "")

    def test_denied_callback_stores_nothing(self):
        state = parse_qs(urlparse(self.connect().json()["url"]).query)["state"][0]
        self.assertEqual(self.client.get(f"/api/spotify/callback?error=access_denied&state={state}").status_code, 400)
        self.assertEqual(self.app.state.store.snapshot()["integrations"]["spotify"]["refresh_token"], "")

    def test_non_loopback_http_origin_is_refused_with_explanation(self):
        body = {"client_id": "abcdef1234567890"}
        r = self.client.post("http://portal.example.test/api/spotify/connect", json=body, headers=self.auth)
        self.assertEqual(r.status_code, 400)
        self.assertIn("127.0.0.1", r.json()["error"])
        self.assertEqual(self.client.post("https://portal.example.test/api/spotify/connect", json=body, headers=self.auth).status_code, 200)

    def test_client_id_required_and_validated(self):
        self.assertEqual(self.client.post("/api/spotify/connect", json={}, headers=self.auth).status_code, 400)
        self.assertEqual(self.connect(client_id="bad id&x=1").status_code, 400)


class WidgetTests(unittest.TestCase):
    def render(self, providers, **conf):
        providers.extra.spotify_conf = conf
        return Renderer.__new__(Renderer), providers

    def image(self, providers):
        from keeper.extensions import render_extra
        return render_extra(slot("spotify"), providers)

    def test_not_connected_states_do_not_start_a_poller(self):
        providers = Providers()
        for conf in ({}, {"enabled": True, "client_id": "c", "refresh_token": ""}, {"enabled": False, "client_id": "c", "refresh_token": "r"}):
            providers.extra.spotify_conf = conf
            self.assertEqual(providers.extra.spotify_state(), (None, "not connected"))
            self.assertEqual(self.image(providers).size, (128, 128))
        self.assertIsNone(providers.extra.spotify_probe)

    def test_lazy_start_and_states(self):
        providers = Providers()
        extra = providers.extra
        extra.spotify_conf = {"enabled": True, "client_id": "c", "refresh_token": "r"}
        session = FakeSession(token=[token()], playing=[FakeResponse(204)] * 5)
        from unittest.mock import patch
        with patch("keeper.spotify.requests.Session", lambda: session):
            self.assertIsNone(extra.spotify_probe)
            data, error = extra.spotify_state()
            self.assertIsNone(data)  # first reading still pending
            self.assertIsNotNone(extra.spotify_probe)
            for _ in range(300):
                data, error = extra.spotify_state()
                if data is not None:
                    break
                time.sleep(.01)
        self.assertEqual(data, {"idle": True})
        self.assertEqual(self.image(providers).size, (128, 128))
        # unavailable / reconnect text paths
        extra.spotify_probe.value, extra.spotify_probe.error, extra.spotify_probe.updated = None, "cannot reach Spotify", time.monotonic()
        extra.spotify_probe.started = time.monotonic()
        self.assertEqual(extra.spotify_state(), (None, "cannot reach Spotify"))
        self.image(providers)
        extra.spotify_probe.error = "reconnect"
        self.image(providers)

    @unittest.mock.patch("keeper.spotify.requests.Session", lambda: FakeSession(token=[token()], playing=[FakeResponse(204)] * 5))
    def test_source_rebuilt_for_new_token_but_not_for_rotated_one(self):
        extra = Providers().extra
        extra.spotify_conf = {"enabled": True, "client_id": "c", "refresh_token": "r1"}
        extra.spotify_state()
        first = extra.spotify_source
        first.refresh_token = "r2"  # rotated by Spotify
        extra.spotify_conf = {"enabled": True, "client_id": "c", "refresh_token": "r2"}
        extra.spotify_state()
        self.assertIs(extra.spotify_source, first)
        extra.spotify_conf = {"enabled": True, "client_id": "c", "refresh_token": "reconnected"}
        extra.spotify_state()
        self.assertIsNot(extra.spotify_source, first)

    def test_playing_render_with_art_and_demo(self):
        providers = Providers(demo=True)
        self.assertEqual(self.image(providers).getpixel((1, 1)), (16, 27, 43))
        art = io.BytesIO(); Image.new("RGB", (64, 64), (200, 30, 30)).save(art, "PNG")
        providers = Providers()
        providers.extra.spotify_state = lambda: ({"title": "T", "artist": "A", "playing": True, "art": base64.b64encode(art.getvalue()).decode(),
                                                  "progress_ms": 1000, "duration_ms": 2000, "sampled": time.monotonic()}, "")
        image = self.image(providers)
        self.assertEqual(image.getpixel((30, 40)), (200, 30, 30))
        providers.extra.spotify_state = lambda: ({"title": "T", "artist": "A", "playing": False, "art": "not-base64!!", "progress_ms": 0, "duration_ms": 0}, "")
        self.image(providers)

    def test_kind_and_validation(self):
        from keeper.content import EXTRA_KINDS, PLAYABLE
        self.assertIn(("spotify", "Spotify", "Spotify"), EXTRA_KINDS)
        self.assertIn("spotify", PLAYABLE)
        data = defaults()
        data["integrations"]["spotify"].update(enabled=True, client_id="abc", refresh_token="r")
        validate(data)
        data["integrations"]["spotify"]["refresh_token"] = "x" * 2000
        with self.assertRaises(ValueError):
            validate(data)


if __name__ == "__main__":
    unittest.main()
