import copy
import json
import imaplib
import queue
import socket
import ssl
import threading
import time
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw
import requests

from keeper import mail
from keeper.config import slot, uid
from keeper.content import composition, split_panorama
from keeper.engine import Engine
from keeper.widgets import Providers, Renderer
from keeper.automation import Pomodoro
from keeper.extensions import custom_image, normalize_phase, validate_content
from test_core import FixtureCase, FakeClient


class CropTests(FixtureCase):
    def test_choose_top_bottom_and_zoom_region(self):
        image = Image.new("RGB", (640, 640), "green")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 639, 127), fill="red")
        draw.rectangle((0, 512, 639, 639), fill="blue")
        path = self.root / "tall.png"; image.save(path)
        for y, expected in [(0, (255, 0, 0)), (1, (0, 0, 255))]:
            tiles = split_panorama(path, position=(.5, y))
            self.assertTrue(all(t.getpixel((64, 64)) == expected for t in tiles))
        tiles = split_panorama(path, position=(1, 1), zoom=4)
        self.assertTrue(all(t.getpixel((64, 64)) == (0, 0, 255) for t in tiles))

    def test_choose_horizontal_crop(self):
        image = Image.new("RGB", (1280, 128), "red")
        ImageDraw.Draw(image).rectangle((640, 0, 1279, 127), fill="blue")
        path = self.root / "wide.png"; image.save(path)
        self.assertEqual(split_panorama(path, position=(0, .5))[2].getpixel((64, 64)), (255, 0, 0))
        self.assertEqual(split_panorama(path, position=(1, .5))[2].getpixel((64, 64)), (0, 0, 255))


class NewContentTests(FixtureCase):
    def test_design_clips_and_resolves_metrics(self):
        s = slot("custom", elements=[{"type": "bar", "x": 10, "y": 20, "width": 100, "height": 10,
                    "metric": "cpu", "maximum": 100, "color": "red"}])
        image = custom_image(s, {"cpu": 50})
        self.assertEqual(image.getpixel((59, 25)), (255, 0, 0))
        self.assertNotEqual(image.getpixel((60, 25)), (255, 0, 0))
        s["elements"].append({"type": "text", "x": 0, "y": 0, "text": "{cpu}", "size": 12})
        self.assertNotEqual(custom_image(s, {"cpu": 25}).tobytes(), custom_image(s, {"cpu": None}).tobytes())

    def test_design_assets_survive_portable_export(self):
        path = self.image()
        self.d["screens"][0] = slot("custom", elements=[{"type": "image", "path": str(path), "x": 0, "y": 0, "width": 128, "height": 128}])
        self.store.update_device(self.d)
        target = self.root / "backup.zip"; self.store.export(target)
        path.unlink(); self.store.import_bundle(target)
        new = self.store.get_device()["screens"][0]
        self.assertEqual(custom_image(new, {}).getpixel((64, 64)), (255, 0, 0))

    def test_export_removes_credentials_and_import_disables_integrations(self):
        config = self.store.snapshot()["integrations"]
        config["api"].update(enabled=True, token="secret" * 8)
        config["mqtt"].update(enabled=True, host="localhost", password="top-secret")
        self.store.change(lambda data: data.update(integrations=config))
        path = self.root / "backup.zip"; self.store.export(path)
        with zipfile.ZipFile(path) as archive:
            blob = archive.read("config.json")
            self.assertNotIn(b"top-secret", blob); self.assertNotIn(b"secretsecret", blob)
        self.store.import_bundle(path)
        self.assertFalse(self.store.snapshot()["integrations"]["api"]["enabled"])

    def test_sensor_json_path_stale_missing_and_nonnumeric(self):
        extra = Providers().extra
        with patch("time.monotonic", return_value=100):
            extra.receive("house/temp", '{"data":{"temperature":24.5}}')
            self.assertEqual(extra.sensor("mqtt", "house/temp", "data.temperature"), 24.5)
            self.assertIsNone(extra.sensor("mqtt", "house/temp", "missing"))
        with patch("time.monotonic", return_value=500):
            self.assertIsNone(extra.sensor("mqtt", "house/temp", "data.temperature"))
        self.assertIsNone(extra.sensor("hardware", "absent"))

    def test_sensor_hardware_missing_then_available(self):
        extra = Providers().extra; extra.hardware_enabled = True
        with patch.object(extra.hardware_probe, "read", return_value=([{"Identifier": "cpu/temp", "Value": 57}], "")):
            self.assertEqual(extra.sensor("hardware", "cpu/temp"), 57)

    def response(self, data):
        response = Mock()
        response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = [data]
        return response

    def test_rss_and_atom_rotate_cache_and_strip_markup(self):
        for blob in [b'<rss><channel><item><title>First &amp; title</title></item><item><title>Second</title></item></channel></rss>',
                     b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>First &amp; title</title></entry><entry><title>Second</title></entry></feed>']:
            provider = Providers(); provider.session.get = Mock(return_value=self.response(blob))
            with patch("time.monotonic", return_value=100):
                self.assertEqual(provider.extra.news("https://example.test/feed")[0], "First & title")
            with patch("time.monotonic", return_value=116):
                self.assertEqual(provider.extra.news("https://example.test/feed")[0], "Second")
            self.assertEqual(provider.session.get.call_count, 1)

    def test_rss_entity_and_size_limits(self):
        for blob in [b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///local">]><rss>&e;</rss>', b"x"*(2*1024**2+1)]:
            provider = Providers(); provider.session.get = Mock(return_value=self.response(blob))
            self.assertEqual(provider.extra.news("https://example.test")[1], "RSS · ERROR")
            provider.extra.news("https://example.test")
            self.assertEqual(provider.session.get.call_count, 1)

    def test_all_extra_widgets_render_without_external_sources(self):
        r = Renderer(demo=True)
        for kind in ("music", "rss", "custom", "pomodoro", "sensor", "prtg", "mail", "spotify"):
            image = r.render(slot(kind, url="https://example.test"))
            self.assertEqual(image.size, (128, 128))
        with self.assertRaises(ValueError):
            validate_content(slot("custom", elements=[{"type": "bar", "maximum": 0}]))


class PrtgTests(unittest.TestCase):
    def setUp(self):
        # These tests cover the non-blocking placeholder path; the first-read wait has its own tests.
        patcher = patch("keeper.extensions.FIRST_READ_WAIT", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def reply(self, payload, status=200):
        raw = json.dumps(payload).encode()
        response = Mock(); response.status_code = status
        response.iter_content = lambda size: iter([raw])
        response.raise_for_status = Mock(side_effect=None if status < 400 else requests.HTTPError("boom"))
        response.__enter__ = lambda self: self; response.__exit__ = lambda *a: False
        return response

    SENSORS = {"sensors": [{"device": "a", "sensor": "ping", "status_raw": 3}, {"device": "b", "sensor": "cpu", "status_raw": 4},
                           {"device": "c", "sensor": "disk", "status_raw": 10}, {"device": "d", "sensor": "http", "status_raw": 13},
                           {"device": "e", "sensor": "x", "status_raw": 7}, {"device": "f", "sensor": "y", "status_raw": 2}]}

    def test_counts_worst_sensor_and_request_shape(self):
        p = Providers(); p.session.get = Mock(return_value=self.reply(self.SENSORS))
        data = p.prtg_fetch("https://prtg.test/", "TOKEN", False)
        self.assertEqual({k: data[k] for k in ("up", "warning", "down", "paused", "unusual")}, dict(up=1, warning=1, down=1, paused=1, unusual=1))
        self.assertEqual(data["worst"], "d · http")
        args, kwargs = p.session.get.call_args
        self.assertEqual(args[0], "https://prtg.test/api/table.json")
        self.assertIs(kwargs["verify"], False); self.assertEqual(kwargs["timeout"], 8)
        self.assertEqual(kwargs["params"]["apitoken"], "TOKEN")
        self.assertIs(kwargs["allow_redirects"], False)

    def test_worst_ordering_warning_over_unusual(self):
        p = Providers(); sensors = [{"device": "u", "sensor": "1", "status_raw": 10}, {"device": "w", "sensor": "2", "status_raw": 4}]
        p.session.get = Mock(return_value=self.reply({"sensors": sensors}))
        self.assertEqual(p.prtg_fetch("http://x.test", "t")["worst"], "w · 2")

    def test_failures_raise_and_the_sampler_does_not_retry_every_frame(self):
        p = Providers(); p.session.get = Mock(return_value=self.reply({}, 500))
        with self.assertRaises(requests.HTTPError):
            p.prtg_fetch("http://x.test", "t")
        self.assertIs(p.session.get.call_args.kwargs["verify"], True)  # TLS verification is the default
        p.session.get = Mock(return_value=self.reply({"unexpected": 1}))
        with self.assertRaises(KeyError):
            p.prtg_fetch("http://y.test", "t")
        p = Providers(); p.session.get = Mock(return_value=self.reply({}, 500))
        p.extra.prtg_conf = {"enabled": True, "base_url": "http://x.test", "token": "SECRET-TOKEN", "verify_tls": True}
        self.wait_for(p.extra, lambda: p.extra.prtg_state()[1] not in ("", "Waiting for first reading"))
        for _ in range(5):
            data, error = p.extra.prtg_state()
        self.assertEqual((data, error), (None, "unexpected response"))  # a fixed reason: the token-bearing URL never reaches the error text
        self.assertEqual(p.session.get.call_count, 2)  # one v2 probe + one v1 request, not retried every frame

    def test_oversized_and_unconfigured(self):
        p = Providers(); response = self.reply({}); response.iter_content = lambda size: iter([b"x" * (2 * 1024**2 + 1)])
        p.session.get = Mock(return_value=response)
        with self.assertRaises(ValueError):
            p.prtg_fetch("http://x.test", "t")
        p.session.get.reset_mock()
        for conf in ({"enabled": True, "base_url": "", "token": "t"}, {"enabled": True, "base_url": "http://x.test", "token": ""},
                     {"enabled": False, "base_url": "http://x.test", "token": "t"}):
            p.extra.prtg_conf = conf
            self.assertEqual(p.extra.prtg_state(), (None, "not configured"))
        p.session.get.assert_not_called()

    @staticmethod
    def wait_for(extra, ready):
        for _ in range(300):
            if ready():
                return
            time.sleep(.01)
        raise AssertionError("sampler did not finish")

    def test_render_states_and_validation(self):
        p = Providers(); p.session.get = Mock(return_value=self.reply(self.SENSORS))
        from keeper.extensions import render_extra
        self.assertIsNone(p.extra.prtg())  # disabled
        p.extra.prtg_conf = {"enabled": True, "base_url": "http://x.test", "token": "t", "verify_tls": True}
        self.assertIsNone(p.extra.prtg())  # first sample still pending
        self.assertEqual(render_extra(slot("prtg"), p).size, (128, 128))
        self.wait_for(p.extra, lambda: p.extra.prtg() is not None)
        self.assertEqual(p.extra.prtg()["down"], 1)
        self.assertEqual(render_extra(slot("prtg"), p).size, (128, 128))
        p.extra.prtg_conf = {}
        self.assertEqual(render_extra(slot("prtg"), p).size, (128, 128))
        validate_content(slot("prtg"))

    def test_render_never_calls_the_network_on_the_calling_thread(self):
        from keeper.extensions import render_extra
        p = Providers(); gate = threading.Event(); threads = []
        def fetch(base, token, verify):
            threads.append(threading.current_thread()); gate.wait(30)
            return {"up": 1, "warning": 0, "down": 0, "paused": 0, "unusual": 0, "worst": ""}
        p.prtg_fetch = fetch
        p.extra.prtg_conf = {"enabled": True, "base_url": "http://x.test", "token": "t", "verify_tls": True}
        started = time.monotonic()
        render_extra(slot("prtg"), p); render_extra(slot("prtg"), p)  # fetch is blocked: render must still return at once
        self.assertLess(time.monotonic() - started, 10, "render waited for the blocked fetch")
        self.wait_for(p.extra, lambda: threads)
        self.assertNotIn(threading.current_thread(), threads)
        self.assertEqual(len(threads), 1)  # single flight
        gate.set()
        self.wait_for(p.extra, lambda: p.extra.prtg() is not None)

    def test_first_draw_waits_briefly_for_the_first_sample_but_never_hangs(self):
        conf = {"enabled": True, "base_url": "http://x.test", "token": "t", "verify_tls": True}
        p = Providers(); p.session.get = Mock(return_value=self.reply(self.SENSORS)); p.extra.prtg_conf = dict(conf)
        with patch("keeper.extensions.FIRST_READ_WAIT", 2):
            data, error = p.extra.prtg_state()
        self.assertEqual((data["down"], error), (1, ""))             # first call already has real data
        gate = threading.Event(); q = Providers(); q.extra.prtg_conf = dict(conf)
        q.prtg_fetch = lambda base, token, verify: (gate.wait(60), {"up": 1, "warning": 0, "down": 0, "paused": 0, "unusual": 0, "worst": ""})[1]
        started = time.monotonic()
        with patch("keeper.extensions.FIRST_READ_WAIT", 0.2):
            data, error = q.extra.prtg_state()
        self.assertIsNone(data)                                       # a slow source gives the placeholder after the cap
        self.assertLess(time.monotonic() - started, 30, "the first draw waited for the blocked fetch")
        gate.set()

    def test_sampler_rebuilt_only_when_the_connection_changes(self):
        p = Providers(); p.session.get = Mock(return_value=self.reply(self.SENSORS))
        conf = {"enabled": True, "base_url": "http://x.test", "token": "t", "verify_tls": True}
        p.extra.prtg_conf = dict(conf); p.extra.prtg_state(); first = p.extra.prtg_probe
        p.extra.prtg_conf = {**conf, "enabled": True}; p.extra.prtg_state()
        self.assertIs(p.extra.prtg_probe, first)
        p.extra.prtg_conf = {**conf, "verify_tls": False}; p.extra.prtg_state()
        self.assertIsNot(p.extra.prtg_probe, first)
        self.assertEqual((p.extra.prtg_probe.interval, p.extra.prtg_probe.stale), (30, 120))


class FakeReply:
    def __init__(self, status=200, body=b"", ctype="application/json", total=None):
        self.status_code, self.body = status, body
        self.headers = {"Content-Type": ctype, **({"X-Total-Count": str(total)} if total is not None else {})}
        self.raise_for_status = Mock(side_effect=None if status < 400 else requests.HTTPError("boom", response=self))
    def iter_content(self, size): return iter([self.body])
    def __enter__(self): return self
    def __exit__(self, *a): return False


class FakePrtgV2:
    """A PRTG v2 server: Bearer key required, X-Total-Count per status filter, one sample sensor per query."""
    KEY = "FAKE-KEY"
    COUNTS = {None: 919, "UP": 878, "DOWN": 2, "ACKNOWLEDGED": 1, "WARNING": 5, "UNUSUAL": 0, "UNKNOWN": 1, "COLLECTING": 3}
    PATH = [{"id": 0, "name": "Root", "type": "REFERENCED_ROOT"}, {"id": 1, "name": "Probe", "type": "PROBE"},
            {"id": 2, "name": "edge-01", "type": "REFERENCED_DEVICE"}]

    def __init__(self, v1=None, html_v2=False, status=None):
        self.calls, self.v1, self.html_v2, self.status = [], v1, html_v2, status

    def get(self, url, **kw):
        self.calls.append((url, kw))
        if "/api/v2/sensors" in url:
            if self.html_v2 or self.v1 is not None and not self.status:
                return FakeReply(200, b"<html>PRTG UI is loading</html>", "text/html")
            if self.status:
                return FakeReply(self.status, b"{}", "application/json")
            if kw.get("headers", {}).get("Authorization") != f"Bearer {self.KEY}":
                return FakeReply(400, b'{"code": "INVALID_TOKEN"}')
            state = kw["params"].get("filter", "").replace("status=", "") or None
            item = {"name": f"sensor-{state}", "status": state, "message": "m", "path": self.PATH}
            count = self.COUNTS[state]
            return FakeReply(200, json.dumps([item] if count else []).encode(), total=count)
        if self.v1 is not None:
            return FakeReply(200, json.dumps(self.v1).encode())
        return FakeReply(200, b"<html>PRTG UI is loading</html>", "text/html")


class PrtgV2Tests(unittest.TestCase):
    URL = "https://prtg.example.com:1616"

    def setUp(self):
        patcher = patch("keeper.extensions.FIRST_READ_WAIT", 0)
        patcher.start(); self.addCleanup(patcher.stop)

    def provider(self, fake):
        p = Providers(); p.session.get = fake.get
        return p

    def test_base_url_normalisation(self):
        from keeper.widgets import prtg_base
        for given, want in [("https://h.example.com:1616", "https://h.example.com:1616"), ("https://h.example.com:1616/", "https://h.example.com:1616"),
                            ("https://h.example.com:1616/api/table.json", "https://h.example.com:1616"),
                            ("https://h.example.com/api/v2/sensors", "https://h.example.com"),
                            ("http://h.example.com/prtg/api/table.json?apitoken=x#f", "http://h.example.com/prtg"),
                            ("http://h.example.com/prtg/?a=1", "http://h.example.com/prtg")]:
            self.assertEqual(prtg_base(given), want)
        with self.assertRaises(ValueError):
            prtg_base("ftp://h.example.com")

    def test_v2_counts_paused_worst_and_request_shape(self):
        fake = FakePrtgV2(); p = self.provider(fake)
        data = p.prtg_fetch(self.URL + "/api/table.json", fake.KEY, False)
        self.assertEqual(data, {"up": 878, "warning": 5, "down": 3, "paused": 919 - (878 + 2 + 1 + 5 + 0 + 1 + 3), "unusual": 0,
                                "worst": "edge-01 · sensor-DOWN"})
        self.assertEqual(data["paused"], 29)
        self.assertEqual(len(fake.calls), 8)
        for url, kw in fake.calls:
            self.assertEqual(url, self.URL + "/api/v2/sensors")
            self.assertEqual(kw["params"]["limit"], 1)
            self.assertEqual(set(kw["params"]) - {"limit", "filter"}, set())
            self.assertEqual(kw["headers"]["Authorization"], "Bearer FAKE-KEY")
            self.assertNotIn(fake.KEY, json.dumps(kw["params"]))
            self.assertIs(kw["verify"], False); self.assertIs(kw["allow_redirects"], False); self.assertLessEqual(kw["timeout"], 8)
        self.assertEqual({kw["params"].get("filter") for _, kw in fake.calls},
                         {None} | {f"status={s}" for s in ("UP", "DOWN", "ACKNOWLEDGED", "WARNING", "UNUSUAL", "UNKNOWN", "COLLECTING")})

    def test_worst_falls_back_through_acknowledged_warning_unusual_and_clamps(self):
        for counts, want in [({"DOWN": 0}, "edge-01 · sensor-ACKNOWLEDGED"), ({"DOWN": 0, "ACKNOWLEDGED": 0}, "edge-01 · sensor-WARNING"),
                             ({"DOWN": 0, "ACKNOWLEDGED": 0, "WARNING": 0, "UNUSUAL": 2}, "edge-01 · sensor-UNUSUAL"),
                             ({"DOWN": 0, "ACKNOWLEDGED": 0, "WARNING": 0}, "")]:
            fake = FakePrtgV2(); fake.COUNTS = {**FakePrtgV2.COUNTS, **counts}
            self.assertEqual(self.provider(fake).prtg_fetch(self.URL, fake.KEY)["worst"], want)
        fake = FakePrtgV2(); fake.COUNTS = {**FakePrtgV2.COUNTS, None: 10}  # states add up to more than the total
        self.assertEqual(self.provider(fake).prtg_fetch(self.URL, fake.KEY)["paused"], 0)

    def test_long_worst_label_is_cut(self):
        fake = FakePrtgV2(); fake.PATH = [{"name": "d" * 200, "type": "DEVICE"}]
        self.assertEqual(len(self.provider(fake).prtg_fetch(self.URL, fake.KEY)["worst"]), 80)

    def test_v1_only_server_falls_back_and_is_cached(self):
        v1 = {"sensors": [{"device": "a", "sensor": "ping", "status_raw": 3}, {"device": "b", "sensor": "x", "status_raw": 5}]}
        fake = FakePrtgV2(v1=v1); p = self.provider(fake)
        self.assertEqual(p.prtg_fetch(self.URL, "t")["down"], 1)
        self.assertEqual([("/api/v2/sensors" in u) for u, _ in fake.calls], [True, False])
        p.prtg_fetch(self.URL, "t")
        self.assertEqual(len(fake.calls), 3)  # steady state: v1 only, no v2 probe
        fake = FakePrtgV2(v1=v1, status=404); p = self.provider(fake)
        self.assertEqual(p.prtg_fetch(self.URL, "t")["up"], 1)

    def test_v2_detection_cached_and_reset_after_error(self):
        fake = FakePrtgV2(); p = self.provider(fake)
        p.prtg_fetch(self.URL, fake.KEY); self.assertEqual(p.prtg_api, "v2")
        p.prtg_fetch(self.URL, fake.KEY); self.assertEqual(len(fake.calls), 16)  # no separate detection request
        fake.status = 500
        with self.assertRaises(Exception):
            p.prtg_fetch(self.URL, fake.KEY)
        self.assertIsNone(p.prtg_api)

    def test_errors_map_to_fixed_reasons_without_secrets(self):
        from keeper.widgets import prtg_reason, PrtgError
        secret = "SECRET-KEY-123"
        def reason(fake):
            p = self.provider(fake)
            try:
                p.prtg_fetch(self.URL + "/api/table.json", secret)
            except Exception as error:
                return prtg_reason(error)
        self.assertEqual(reason(FakePrtgV2()), "invalid API key")  # wrong Bearer key -> 400 JSON
        self.assertEqual(reason(FakePrtgV2(status=401)), "access denied")
        self.assertEqual(reason(FakePrtgV2(status=403)), "access denied")
        self.assertEqual(reason(FakePrtgV2(html_v2=True)), "not an API endpoint (check the address)")  # HTML on v2 and on v1
        self.assertEqual(reason(FakePrtgV2()) , "invalid API key")
        self.assertEqual(prtg_reason(requests.ConnectionError(f"{self.URL}?apitoken={secret}")), "cannot connect")
        self.assertEqual(prtg_reason(requests.exceptions.SSLError(secret)), "cannot connect")
        self.assertEqual(prtg_reason(requests.ReadTimeout(secret)), "timeout")
        self.assertEqual(prtg_reason(requests.ConnectTimeout(secret)), "timeout")
        self.assertEqual(prtg_reason(requests.HTTPError("x", response=FakeReply(403))), "access denied")
        self.assertEqual(prtg_reason(requests.HTTPError(secret, response=FakeReply(500))), "unexpected response")
        self.assertEqual(prtg_reason(ValueError(secret)), "unexpected response")
        self.assertEqual(prtg_reason(PrtgError("timeout")), "timeout")
        for text in ("cannot connect", "timeout", "invalid API key", "access denied", "unexpected response"):
            self.assertNotIn(secret, text)

    def test_state_and_render_show_the_reason(self):
        from keeper.extensions import render_extra
        fake = FakePrtgV2(html_v2=True); p = self.provider(fake)
        p.extra.prtg_conf = {"enabled": True, "base_url": self.URL, "token": "SECRET-KEY-123", "verify_tls": True}
        deadline = time.monotonic() + 3
        while p.extra.prtg_state()[1] in ("", "Waiting for first reading") and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(p.extra.prtg_state(), (None, "not an API endpoint (check the address)"))
        blank = Providers(); blank.extra.prtg_conf = {}
        with_reason = render_extra(slot("prtg"), p)
        self.assertEqual(with_reason.size, (128, 128))
        self.assertNotEqual(with_reason.tobytes(), render_extra(slot("prtg"), blank).tobytes())

    def test_sampler_shows_v2_data(self):
        fake = FakePrtgV2(); p = self.provider(fake)
        p.extra.prtg_conf = {"enabled": True, "base_url": self.URL, "token": fake.KEY, "verify_tls": True}
        deadline = time.monotonic() + 3
        while p.extra.prtg() is None and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(p.extra.prtg()["down"], 3)


class FakeImap:
    """Stands in for imaplib: records every command and never touches the network."""
    def __init__(self, unseen=3, header=b"Subject: =?utf-8?q?Caf=C3=A9_report?=\r\n\r\n", starttls_fails=False, login_error=None, status_error=None):
        self.log, self.unseen, self.header = [], unseen, header
        self.starttls_fails, self.login_error, self.status_error = starttls_fails, login_error, status_error

    def starttls(self, ssl_context=None):
        self.log.append("starttls")
        if self.starttls_fails:
            raise imaplib.IMAP4.error("STARTTLS refused by secret-banner")

    def login(self, user, password):
        self.log.append("login")
        if self.login_error:
            raise self.login_error

    def select(self, mailbox, readonly=False):
        self.log.append(("select", mailbox, readonly)); return "OK", [b"1"]

    def status(self, mailbox, what):
        self.log.append(("status", mailbox, what))
        if self.status_error:
            raise self.status_error
        return "OK", [b'"INBOX" (UNSEEN %d)' % self.unseen]

    def search(self, charset, criterion):
        self.log.append(("search", criterion)); return "OK", [b"4 7 9"]

    def fetch(self, message_id, parts):
        self.log.append(("fetch", message_id, parts))
        return "OK", [(b"9 (BODY[HEADER.FIELDS (SUBJECT)] {10}", self.header), b")"]

    def logout(self):
        self.log.append("logout")


class MailTests(unittest.TestCase):
    def setUp(self):
        # These tests cover the non-blocking placeholder path; the first-read wait has its own tests.
        patcher = patch("keeper.extensions.FIRST_READ_WAIT", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    CONF = {"id": "main", "name": "Main", "provider": "imap", "enabled": True, "host": "imap.test", "port": 993, "user": "user-secret",
            "password": "pw-secret", "mailbox": "INBOX", "show_subject": False}
    MAIL = {"enabled": True, "accounts": [CONF]}

    def run_fetch(self, fake, **conf):
        calls = []
        def connector(host, port, timeout, context):
            calls.append((host, port, timeout, context)); return fake
        return mail.fetch_unread({**self.CONF, **conf}, connector=connector), calls

    def test_count_uses_examine_and_never_fetches_without_show_subject(self):
        fake = FakeImap(unseen=5)
        result, calls = self.run_fetch(fake)
        self.assertEqual(result, {"unread": 5, "subject": None})
        self.assertEqual(calls[0][:3], ("imap.test", 993, 10)); self.assertIsInstance(calls[0][3], ssl.SSLContext)
        self.assertIn(("select", '"INBOX"', True), fake.log)
        self.assertFalse([x for x in fake.log if isinstance(x, tuple) and x[0] in {"search", "fetch"}])
        self.assertNotIn("starttls", fake.log); self.assertEqual(fake.log[-1], "logout")

    def test_subject_peek_only_for_newest_unseen_and_decoded(self):
        fake = FakeImap(header=b"Subject: =?utf-8?q?Caf=C3=A9_report?=\r\n\x07x\r\n\r\n")
        result, _ = self.run_fetch(fake, show_subject=True)
        self.assertEqual(result["subject"], "Café report")
        fetch = [x for x in fake.log if isinstance(x, tuple) and x[0] == "fetch"]
        self.assertEqual(fetch, [("fetch", b"9", "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])")])
        long = FakeImap(header=b"Subject: " + b"a" * 300 + b"\r\n\r\n")
        self.assertEqual(len(self.run_fetch(long, show_subject=True)[0]["subject"]), 80)
        self.assertIsNone(self.run_fetch(FakeImap(unseen=0), show_subject=True)[0]["subject"])

    def test_huge_subject_header_is_capped_before_parsing(self):
        fake = FakeImap(header=b"Subject: " + b"a" * (4 * 1024 * 1024) + b"\r\n\r\n")
        started = time.monotonic()
        subject = self.run_fetch(fake, show_subject=True)[0]["subject"]
        self.assertLess(time.monotonic() - started, 10)
        self.assertLessEqual(len(subject), 80)

    def test_starttls_on_143_and_password_withheld_when_it_fails(self):
        fake = FakeImap()
        self.run_fetch(fake, port=143)
        self.assertEqual(fake.log[:2], ["starttls", "login"])
        fake = FakeImap(starttls_fails=True)
        with self.assertRaises(mail.MailError) as caught:
            self.run_fetch(fake, port=143)
        self.assertNotIn("login", fake.log); self.assertEqual(fake.log[-1], "logout")
        self.assertEqual(str(caught.exception), "protocol error")

    def test_errors_map_to_fixed_reasons_without_secrets(self):
        cases = [(FakeImap(login_error=imaplib.IMAP4.error("LOGIN failed pw-secret user-secret imap.test")), "authentication failed"),
                 (FakeImap(status_error=socket.timeout("pw-secret")), "timeout"),
                 (FakeImap(status_error=imaplib.IMAP4.error("pw-secret")), "protocol error"),
                 (FakeImap(status_error=RuntimeError("user-secret")), "protocol error")]
        for fake, reason in cases:
            with self.assertRaises(mail.MailError) as caught:
                self.run_fetch(fake)
            self.assertEqual(str(caught.exception), reason)
        def refuse(*args):
            raise ConnectionRefusedError("pw-secret imap.test")
        with self.assertRaises(mail.MailError) as caught:
            mail.fetch_unread(self.CONF, connector=refuse)
        self.assertEqual(str(caught.exception), "cannot connect")
        for text in ("pw-secret", "user-secret", "imap.test"):
            self.assertNotIn(text, str(caught.exception))
        self.assertEqual(str(mail.MailError("server said hello")), "protocol error")

    def test_mailbox_is_quoted_and_control_characters_rejected(self):
        fake = FakeImap(); self.run_fetch(fake, mailbox='My "Box"')
        self.assertIn(("select", '"My \\"Box\\""', True), fake.log)
        with self.assertRaises(mail.MailError):
            self.run_fetch(FakeImap(), mailbox="INBOX\r\nA1 DELETE x")

    def test_async_probe_first_read_can_wait_for_the_first_sample(self):
        import threading
        from keeper.windows_sources import AsyncProbe
        fast = AsyncProbe(lambda: "ready", 5, 30)
        self.assertEqual(fast.read(wait=2), ("ready", ""))          # first call already returns the sample
        release = threading.Event()
        slow = AsyncProbe(lambda: (release.wait(5), "late")[1], 5, 30)
        value, error = slow.read(wait=0.05)                          # sampler still running: placeholder, not a hang
        self.assertIsNone(value)
        self.assertEqual(error, "Waiting for first reading")
        release.set()
        slow.first.wait(2)
        self.assertEqual(slow.read(wait=0.05), ("late", ""))
        failing = AsyncProbe(lambda: 1 / 0, 5, 30)
        self.assertEqual(failing.read(wait=2)[1], "division by zero")  # an error also ends the wait
        plain = AsyncProbe(lambda: "x", 5, 30)
        self.assertEqual(plain.read(), (None, "Waiting for first reading"))  # default read() never waits

    def test_async_probe_defaults_unchanged_and_custom_stale(self):
        from keeper.windows_sources import AsyncProbe
        default = AsyncProbe(lambda: 1)
        self.assertEqual((default.interval, default.stale), (5, 30))
        clock = [1000.]
        with patch("time.monotonic", lambda: clock[0]):
            for probe, expect_at in ((AsyncProbe(lambda: 1, 10**9), 31), (AsyncProbe(lambda: 1, 10**9, 600), 601)):
                probe.read()
                for _ in range(200):
                    if probe.updated > 0:
                        break
                    time.sleep(.005)
                clock[0] = 1000.; probe.updated = 1000.
                clock[0] = 1000. + expect_at - 2; self.assertEqual(probe.read()[0], 1)
                clock[0] = 1000. + expect_at; self.assertIsNone(probe.read()[0])
                clock[0] = 1000.

    def test_sampler_lifecycle_is_lazy_single_flight_and_config_scoped(self):
        p = Providers(); extra = p.extra
        with patch("keeper.mail.fetch_unread") as fetch:
            self.assertEqual(extra.mail_state(), (None, "not configured"))
            extra.mail_conf = {**self.MAIL, "enabled": False}
            self.assertEqual(extra.mail_state(), (None, "not configured")); fetch.assert_not_called()
            gate = threading.Event(); fetch.side_effect = lambda conf, **kw: (gate.wait(30), {"unread": 2, "subject": None})[1]
            extra.mail_conf = copy.deepcopy(self.MAIL)
            extra.mail_state(); extra.mail_state(); extra.mail_state()
            deadline = time.monotonic() + 10
            while fetch.call_count < 1 and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(fetch.call_count, 1, "the sampler did not start exactly one fetch")
            gate.set()
            for _ in range(200):
                if extra.mail() is not None:
                    break
                time.sleep(.01)
            self.assertEqual(extra.mail()["unread"], 2)
            self.assertEqual(fetch.call_args.args[0]["password"], "pw-secret")
            gate.clear()  # the rebuilt sampler must not answer instantly, or the assertion below would race it
            extra.mail_conf = {**self.MAIL, "accounts": [{**self.CONF, "host": "other.test"}]}
            self.assertIsNone(extra.mail())  # new connection settings discard the old reading
            gate.set()

    def test_demo_data_respects_show_subject(self):
        p = Providers(demo=True)
        data, error = p.extra.mail_state()
        self.assertEqual((data["unread"], data["subject"], error), (3, None, ""))
        p.extra.mail_conf = {"enabled": True, "accounts": [{**self.CONF, "show_subject": True}]}
        self.assertEqual(p.extra.mail()["subject"], "Weekly report")

    def test_render_states_and_validation(self):
        from keeper.extensions import render_extra
        p = Providers()
        row = [{"id": "main", "name": "Main", "unread": 0, "error": ""}]
        for state in ((None, "not configured"), (None, "Waiting for first reading"), (None, "authentication failed"), (None, "account missing"),
                      ({"unread": 0, "subject": None, "accounts": row, "failed": 0}, ""),
                      ({"unread": 12, "subject": "Weekly report", "accounts": row, "failed": 0}, "")):
            with patch.object(p.extra, "mail_state", return_value=state):
                self.assertEqual(render_extra(slot("mail"), p).size, (128, 128))
        with patch.object(p.extra, "mail_state", return_value=({"unread": 0, "subject": None, "accounts": row, "failed": 0}, "")):
            green = render_extra(slot("mail"), p)
        with patch.object(p.extra, "mail_state", return_value=({"unread": 4, "subject": None, "accounts": row, "failed": 0}, "")):
            amber = render_extra(slot("mail"), p)
        self.assertIn((74, 222, 128), green.getdata()); self.assertIn((251, 191, 36), amber.getdata())
        validate_content(slot("mail"))


class AutomationTests(FixtureCase):
    def setUp(self):
        super().setUp()
        self.now = 100.
        self.clock = patch("time.monotonic", lambda: self.now); self.clock.start(); self.addCleanup(self.clock.stop)
        self.d["enabled"] = True; self.d["screens"][0] = slot("text", text="BASE")
        self.store.update_device(self.d)
        self.engine = Engine(self.store, demo=True)
        self.auto = self.engine.automations

    def rule(self, **kwargs):
        return {"id": uid(), "device_id": self.d["id"], "enabled": True, "panel": 0, "text": "Notice",
                "metric": "cpu", "threshold": 80, "operator": "above", "hold": 10, "cooldown": 30, **kwargs}

    def update(self, now):
        self.now = now; self.auto.update(self.store.snapshot(), now)

    def test_alert_requires_hold_rearms_and_ignores_missing(self):
        rule = self.rule(); self.store.change(lambda data: data.update(alerts=[rule]))
        with patch.object(self.auto, "value", return_value=95):
            self.update(100); self.assertEqual(len(self.auto.notice_queue), 0)
            self.update(111); self.assertEqual(len(self.auto.notice_queue), 1)
            self.update(150); self.assertEqual(len(self.auto.notice_queue), 1)
        with patch.object(self.auto, "value", return_value=None):
            self.update(156)
        with patch.object(self.auto, "value", return_value=95):
            self.update(162); self.update(173)
        self.assertEqual(len(self.auto.notice_queue), 2)

    def test_prtg_alert_metrics(self):
        for metric, expected in (("prtg_down", 2), ("prtg_warning", 5)):
            with patch.object(self.engine.renderer.providers.extra, "prtg", return_value={"down": 2, "warning": 5}):
                self.assertEqual(self.auto.value(self.rule(metric=metric)), expected)
        with patch.object(self.engine.renderer.providers.extra, "prtg", return_value=None):
            self.assertIsNone(self.auto.value(self.rule(metric="prtg_down")))
        self.store.change(lambda data: data.update(alerts=[self.rule(metric="prtg_down")]))

    def test_mail_unread_alert_metric(self):
        extra = self.engine.renderer.providers.extra
        with patch.object(extra, "mail_state", return_value=({"unread": 7, "subject": None}, "")) as state:
            self.assertEqual(self.auto.value(self.rule(metric="mail_unread")), 7)
            state.assert_called_with("all")  # old rules (empty source) mean the combined count
            self.auto.value(self.rule(metric="mail_unread", source="abc123")); state.assert_called_with("abc123")
        with patch.object(extra, "mail_state", return_value=(None, "account missing")):
            self.assertIsNone(self.auto.value(self.rule(metric="mail_unread")))
        self.store.change(lambda data: data.update(alerts=[self.rule(metric="mail_unread")]))

    def test_reminders_do_not_catch_up_after_pause(self):
        rule = self.rule(minutes=1); self.store.change(lambda data: data.update(reminders=[rule]))
        self.update(100); self.update(161)
        self.assertEqual(len(self.auto.notice_queue), 1)
        self.engine.paused.add(self.d["id"]); self.update(200); self.update(500)
        self.engine.paused.clear(); self.update(506)
        self.assertEqual(len(self.auto.notice_queue), 1)
        self.update(567); self.assertEqual(len(self.auto.notice_queue), 2)

    def test_notice_queue_waits_and_restores(self):
        self.auto.enqueue(self.d["id"], 0, "First", "Notice")
        self.auto.enqueue(self.d["id"], 0, "Second", "Notice")
        self.auto.deliver(self.d, 100); self.auto.deliver(self.d, 101)
        self.assertEqual(len(self.auto.notice_queue), 1)
        self.now = 116; self.engine.tick()
        self.assertEqual(len(self.auto.notice_queue), 0)
        self.assertEqual(self.store.get_device()["screens"][0]["text"], "BASE")

    def test_profiles_are_ephemeral_and_prioritized(self):
        scene = {"id": uid(), "name": "Game", "screens": [slot("text", text="GAME") for _ in range(5)]}
        lock_scene = {"id": uid(), "name": "Locked", "screens": [slot("text", text="LOCKED") for _ in range(5)]}
        profile = self.rule(trigger="process", process="game.exe", scene_id=scene["id"])
        locked = self.rule(trigger="locked", scene_id=lock_scene["id"])
        self.store.change(lambda data: data.update(scenes=[scene, lock_scene], profiles=[profile, locked]))
        data = self.store.snapshot(); before = self.store.path.read_bytes()
        with patch("psutil.process_iter", return_value=[SimpleNamespace(info={"name": "GAME.EXE"})]):
            self.assertEqual(self.auto.effective(self.d, data, 100)["screens"][0]["text"], "GAME")
            self.auto.locked = True
            self.assertEqual(self.auto.effective(self.d, data, 101)["screens"][0]["text"], "LOCKED")
        self.auto.locked = False
        with patch("psutil.process_iter", return_value=[]):
            self.assertEqual(self.auto.effective(self.d, data, 106)["screens"][0]["text"], "BASE")
        self.assertEqual(before, self.store.path.read_bytes())

    def test_pomodoro_pause_resume_long_break_and_reset(self):
        timer = Pomodoro(); timer.command("start", device_id=self.d["id"], work=1, rest=1, long_rest=2, cycles=2)
        self.now = 120; timer.command("pause"); self.assertEqual(timer.remaining, 40)
        self.now = 300; timer.command("resume")
        self.assertEqual(timer.advance(341), "Break")
        self.assertEqual(timer.advance(402), "Work")
        self.assertEqual(timer.advance(463), "Long break")
        self.assertEqual(timer.remaining, 120)
        timer.command("reset"); self.assertFalse(timer.running); self.assertEqual(timer.phase, "Ready")

    def test_normalize_phase_maps_legacy_spanish_values(self):
        for legacy, english in (("Preparado", "Ready"), ("Trabajo", "Work"), ("Descanso", "Break"), ("Descanso largo", "Long break")):
            self.assertEqual(normalize_phase(legacy), english)
            self.assertEqual(normalize_phase(english), english)

    def test_invalid_rules_rollback(self):
        before = self.store.snapshot()
        for group, rule in [("alerts", self.rule(metric="wrong")), ("reminders", self.rule(minutes=0)), ("profiles", self.rule(trigger="process", process="game.exe", scene_id="missing"))]:
            with self.assertRaises(ValueError):
                self.store.change(lambda data: data.update({group: [rule]}))
            self.assertEqual(before, self.store.snapshot())


class ApiTests(FixtureCase):
    def setUp(self):
        super().setUp()
        self.engine = Engine(self.store)
        self.bridge = self.engine.bridge
        self.bridge.start_api({"host": "127.0.0.1", "port": 0, "token": "test-token-for-local-tests"})
        self.base = self.bridge.api_status
        self.headers = {"Authorization": "Bearer test-token-for-local-tests"}

    def tearDown(self):
        self.bridge.close(); super().tearDown()

    def test_http_auth_status_no_credentials_and_route_limits(self):
        self.assertEqual(requests.get(self.base+"/v1/status", timeout=2).status_code, 401)
        response = requests.get(self.base+"/v1/status", headers=self.headers, timeout=2)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("test-token", response.text)
        self.assertEqual(requests.get(self.base+"/config", headers=self.headers, timeout=2).status_code, 404)
        self.assertEqual(requests.get(self.base+"/v1/status", headers={**self.headers, "Origin": "https://example.test"}, timeout=2).status_code, 401)

    def test_commands_queued_not_written_in_http_thread(self):
        response = requests.post(self.base+"/v1/action", headers=self.headers, json={"action": "notice", "panel": 3, "text": "Hello"}, timeout=2)
        self.assertEqual(response.status_code, 202)
        _, action, device_id, args = self.engine.jobs.get_nowait()
        self.assertEqual((action, args["panel"]), ("notification", 2))
        self.assertEqual(self.engine.clients, {})
        for body in [{"action": "notice", "panel": 6, "text": "Hi"}, {"action": "command", "payload": {}}, {"action": "scene", "scene_id": "missing"}, {"action": "power", "on": "false"}]:
            self.assertEqual(requests.post(self.base+"/v1/action", headers=self.headers, json=body, timeout=2).status_code, 400)

    def test_http_payload_limit_and_full_queue(self):
        self.assertEqual(requests.post(self.base+"/v1/action", headers=self.headers, data="x"*17000, timeout=2).status_code, 413)
        for _ in range(100):
            self.engine.submit("command", payload={})
        self.assertEqual(requests.post(self.base+"/v1/action", headers=self.headers, json={"action": "brightness", "value": 50}, timeout=2).status_code, 503)


class MqttTests(FixtureCase):
    def test_discovery_commands_and_sensor_subscription(self):
        engine = Engine(self.store); bridge = engine.bridge
        self.d["screens"][0] = slot("sensor", sensor_key="house/room", sensor_source="mqtt")
        self.store.update_device(self.d)
        conf = {"host": "localhost", "prefix": "keeper_test"}; bridge.config = {"mqtt": conf}
        with patch("paho.mqtt.client.Client") as cls:
            client = cls.return_value
            bridge.start_mqtt(conf)
            client.on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
            client.subscribe.assert_any_call("house/room")
            self.assertTrue(any(call.args[0].startswith("homeassistant/button/") for call in client.publish.call_args_list))
            client.on_message(client, None, SimpleNamespace(topic="house/room", payload=b'{"temp":25}', retain=True))
            self.assertEqual(engine.renderer.providers.extra.sensor("mqtt", "house/room", "temp"), 25)
            command = SimpleNamespace(topic="keeper_test/command", payload=b'{"action":"brightness","value":20}', retain=True)
            client.on_message(client, None, command); self.assertTrue(engine.jobs.empty())
            command.retain = False; client.on_message(client, None, command)
            self.assertEqual(engine.jobs.get_nowait()[3]["payload"]["Brightness"], 20)
            bridge.close()


if __name__ == "__main__":
    unittest.main()


class HardwareSensorPlaceholderTests(unittest.TestCase):
    def drawn(self, screen):
        from PIL import ImageDraw
        from keeper.extensions import render_extra
        texts, original = [], ImageDraw.ImageDraw.text
        def spy(self_, xy, text, *args, **kwargs):
            texts.append(text)
            return original(self_, xy, text, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, "text", spy):
            render_extra(screen, Providers())
        return " ".join(texts)

    def test_hardware_sensor_without_a_key_says_to_choose_one(self):
        for key in ("", "   "):
            screen = {**slot("sensor"), "sensor_source": "hardware", "sensor_key": key}
            texts = self.drawn(screen)
            self.assertIn("Choose a sensor", texts)
            self.assertNotIn("N/A", texts)

    def test_a_missing_key_or_other_source_keeps_the_old_text(self):
        for screen in ({**slot("sensor"), "sensor_source": "hardware", "sensor_key": "/x/temperature/0"},
                       {**slot("sensor"), "sensor_source": "mqtt", "sensor_key": ""}):
            texts = self.drawn(screen)
            self.assertNotIn("Choose a sensor", texts)
            self.assertIn("N/A", texts)
