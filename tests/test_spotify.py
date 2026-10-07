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
from PIL import Image, ImageColor

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


class ManualFlowTests(unittest.TestCase):
    REDIRECT = "https://example.org/callback"

    def start(self):
        verifier, challenge = spotify.make_pkce_pair()
        state = "state-" + verifier[:10]
        return spotify.build_authorize_url("cid", self.REDIRECT, state, challenge), verifier, state

    def finish(self, session, verifier, state, pasted):
        return spotify.finish_manual(session, "cid", self.REDIRECT, verifier, state, pasted)

    def test_authorize_url(self):
        url, verifier, state = self.start()
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        self.assertEqual(q["redirect_uri"], self.REDIRECT)
        self.assertEqual(q["state"], state)
        self.assertEqual(q["code_challenge_method"], "S256")
        self.assertEqual(q["code_challenge"], base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("="))
        self.assertEqual(q["scope"], spotify.SCOPES)

    def test_full_url_and_query_forms(self):
        for template in ("https://example.org/callback?code=CODE-1&state={s}", "http://other.test/x?state={s}&code=CODE-1#frag",
                         "code=CODE-1&state={s}", "?code=CODE-1&state={s}"):
            url, verifier, state = self.start()
            session = FakeSession(token=[token(refresh="R9")])
            self.assertEqual(self.finish(session, verifier, state, "  " + template.format(s=state) + " "), "R9")
            payload = session.of("post", spotify.TOKEN_URL)[0][2]
            self.assertEqual((payload["code"], payload["redirect_uri"], payload["code_verifier"]), ("CODE-1", self.REDIRECT, verifier))

    def test_rejections_make_no_request_and_leak_nothing(self):
        url, verifier, state = self.start()
        cases = ["https://x.test/cb?code=SECRETCODE&state=WRONG", "https://x.test/cb?code=SECRETCODE",
                 f"https://x.test/cb?error=access_denied&state={state}", f"https://x.test/cb?state={state}",
                 "", "no query at all", "code=SECRETCODE&state=" + state + "&x=" + "a" * 3000]
        for pasted in cases:
            session = FakeSession()
            with self.assertRaises(spotify.SpotifyError) as caught:
                self.finish(session, verifier, state, pasted)
            for secret in ("SECRETCODE", state, verifier):
                self.assertNotIn(secret, str(caught.exception))
            self.assertEqual(session.calls, [])

    def test_exchange_failure_text_has_no_secrets(self):
        url, verifier, state = self.start()
        session = FakeSession(token=[FakeResponse(400, {"error": "invalid_grant"})])
        with self.assertRaises(spotify.SpotifyAuthError) as caught:
            self.finish(session, verifier, state, f"code=SECRETCODE&state={state}")
        for secret in ("SECRETCODE", state, verifier):
            self.assertNotIn(secret, str(caught.exception))


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
        return spotify.SpotifySource("cid", "R0", lambda new, old: self.saved.append(new), session, lambda: self.now[0])

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

    def test_dead_token_makes_one_token_request_then_no_network(self):
        session = FakeSession(token=[FakeResponse(400, {"error": "invalid_grant"})])
        source = self.source(session)
        for _ in range(5):
            with self.assertRaises(spotify.SpotifyAuthError) as caught:
                source.poll()
            self.assertEqual(str(caught.exception), "reconnect")
            self.now[0] += 5
        self.assertEqual(len(session.calls), 1)

    def test_token_server_outage_is_not_a_dead_token(self):
        session = FakeSession(token=[FakeResponse(503), token()], playing=[FakeResponse(204)])
        source = self.source(session)
        with self.assertRaises(spotify.SpotifyError) as caught:
            source.poll()
        self.assertNotIsInstance(caught.exception, spotify.SpotifyAuthError)
        self.assertEqual(source.poll(), {"idle": True})

    def test_forbidden_backs_off_for_five_minutes(self):
        session = FakeSession(token=[token()], playing=[FakeResponse(403), FakeResponse(204)])
        source = self.source(session)
        for _ in range(3):
            with self.assertRaises(spotify.SpotifyAuthError) as caught:
                source.poll()
            self.assertIn("User Management", str(caught.exception))
            self.now[0] += 5
        self.assertEqual(len(session.calls), 2)  # one token request, one now-playing request
        self.now[0] += 300
        self.assertEqual(source.poll(), {"idle": True})

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


class WidgetTests(unittest.TestCase):
    def setUp(self):
        # These tests cover the non-blocking placeholder path; the first-read wait has its own test below.
        patcher = unittest.mock.patch("keeper.extensions.FIRST_READ_WAIT", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

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

    def test_decompression_bomb_art_falls_back_to_no_art(self):
        providers = Providers()
        providers.extra.spotify_conf = {"enabled": True, "client_id": "c", "refresh_token": "r"}
        data = {"title": "T", "artist": "A", "playing": True, "art": base64.b64encode(b"x").decode(),
                "progress_ms": 1, "duration_ms": 10, "sampled": time.monotonic()}
        for payload in (data, {**data, "art": base64.b64encode(b"y").decode()}):
            with unittest.mock.patch.object(providers.extra, "spotify_state", return_value=(payload, "")), \
                    unittest.mock.patch("keeper.extensions.Image.open", side_effect=Image.DecompressionBombError("bomb")):
                self.assertEqual(self.image(providers).size, (128, 128))

    def display_image(self, mode=None, art=True, color=(200, 30, 30)):
        from keeper.extensions import render_extra
        providers = Providers()
        buffer = io.BytesIO()
        Image.new("RGB", (40, 40), color).save(buffer, "PNG")
        data = {"title": "A Long Song Title For Testing", "artist": "Some Artist", "playing": True,
                "art": base64.b64encode(buffer.getvalue()).decode() if art else "",
                "progress_ms": 60000, "duration_ms": 200000, "sampled": 100.0}
        screen = slot("spotify")
        if mode is not None:
            screen["spotify_display"] = mode
        with unittest.mock.patch.object(providers.extra, "spotify_state", return_value=(data, "")), \
                unittest.mock.patch("keeper.extensions.time.monotonic", return_value=100.0):
            return render_extra(screen, providers)

    def test_display_modes_differ_and_unknown_means_both(self):
        images = {m: self.display_image(m) for m in ("both", "art", "text")}
        for image in images.values():
            self.assertEqual(image.size, (128, 128))
        self.assertEqual(len({i.tobytes() for i in images.values()}), 3)
        self.assertEqual(self.display_image().tobytes(), images["both"].tobytes())
        self.assertEqual(self.display_image("nonsense").tobytes(), images["both"].tobytes())

    def test_art_mode_fills_the_canvas_and_keeps_the_progress_bar(self):
        art_color, image = (200, 30, 30), self.display_image("art")
        self.assertEqual(image.getpixel((64, 64)), art_color)
        self.assertEqual(image.getpixel((100, 100)), art_color)
        self.assertEqual(image.getpixel((64, 40)), art_color)  # where TEXT draws the title: plain art, no text
        self.assertEqual(image.getpixel((119, 124)), ImageColor.getrgb("#26334b"))  # empty part of the thin bar
        self.assertEqual(image.getpixel((20, 124)), ImageColor.getrgb("#64e6ca"))  # elapsed part
        self.assertEqual({image.getpixel((x, 80)) for x in range(0, 128)}, {art_color})

    def test_text_mode_has_no_art(self):
        image = self.display_image("text")
        self.assertEqual(self.display_image("text").tobytes(), self.display_image("text", art=False).tobytes())
        self.assertNotIn((200, 30, 30), {image.getpixel((x, y)) for x in range(8, 60) for y in range(22, 74)})

    def test_art_mode_without_art_draws_the_placeholder(self):
        image = self.display_image("art", art=False)
        centre = [image.getpixel((x, 64)) for x in range(0, 128)]
        self.assertIn(ImageColor.getrgb("#64e6ca"), centre)
        self.assertNotEqual(image.tobytes(), Image.new("RGB", (128, 128), "#101b2b").tobytes())
        self.assertEqual(image.getpixel((8, 64)), ImageColor.getrgb("#101b2b"))

    def test_display_setting_is_validated_only_for_spotify(self):
        from keeper.extensions import validate_content
        for value in ("both", "art", "text"):
            validate_content(slot("spotify", spotify_display=value))
        validate_content(slot("spotify"))
        with self.assertRaises(ValueError):
            validate_content(slot("spotify", spotify_display="cover"))
        validate_content(slot("clock", spotify_display="cover"))

    def test_first_draw_waits_briefly_so_the_widget_is_not_stuck_on_connecting(self):
        providers = Providers()
        providers.extra.spotify_conf = {"enabled": True, "client_id": "c", "refresh_token": "r"}
        session = FakeSession(token=[token()], playing=[FakeResponse(204)] * 5)
        with unittest.mock.patch("keeper.spotify.requests.Session", lambda: session), \
                unittest.mock.patch("keeper.extensions.FIRST_READ_WAIT", 2):
            data, error = providers.extra.spotify_state()
        self.assertEqual((data, error), ({"idle": True}, ""))  # real answer on the very first call

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

    def test_new_token_rebuilds_a_dead_source_and_works(self):
        sessions = [FakeSession(token=[FakeResponse(400, {"error": "invalid_grant"})]), FakeSession(token=[token()], playing=[FakeResponse(204)])]
        extra = Providers().extra
        extra.spotify_conf = {"enabled": True, "client_id": "c", "refresh_token": "old"}
        with unittest.mock.patch("keeper.spotify.requests.Session", lambda: sessions.pop(0)):
            for _ in range(300):
                if extra.spotify_state()[1] == "reconnect":
                    break
                time.sleep(.01)
            self.assertTrue(extra.spotify_source.dead)
            dead = extra.spotify_source
            extra.spotify_state()
            self.assertIs(extra.spotify_source, dead)  # same token: stays dead
            extra.spotify_conf = {"enabled": True, "client_id": "c", "refresh_token": "new"}
            for _ in range(300):
                data, _ = extra.spotify_state()
                if data is not None:
                    break
                time.sleep(.01)
        self.assertIsNot(extra.spotify_source, dead)
        self.assertEqual(data, {"idle": True})

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
