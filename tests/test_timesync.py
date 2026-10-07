import copy
import email.utils
import json
import os
import socket
import struct
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from keeper import timesync
from keeper.config import ConfigStore, defaults, slot, validate
from keeper.engine import Engine
from keeper.timesync import TimeSource, TimeSyncError, combine, https_sample, sntp_query, sntp_sample, NTP_EPOCH
from keeper.widgets import Renderer
from test_core import FakeClient, FixtureCase


def ntp_bytes(value):
    seconds = int(value)
    return struct.pack(">II", seconds + NTP_EPOCH, int((value - seconds) * (1 << 32)))


class FakeNtpServer:
    """A UDP server on 127.0.0.1 answering with a crafted reply built by `build(request, receive_time)`."""

    def __init__(self, build=None, skew=0.0):
        self.skew, self.build, self.requests, self.via = skew, build, [], None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.2)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    @property
    def address(self):
        return (socket.AF_INET, socket.SOCK_DGRAM, 0, "", self.sock.getsockname())

    def reply(self, request, flags=(0 << 6) | (4 << 3) | 4, stratum=2, originate=None, transmit_shift=0.0, refid=b"GPS\0", transmit=True):
        now = time.time() + self.skew
        return (bytes([flags, stratum, 6, 0xEC]) + bytes(4) + bytes(4) + refid + bytes(8)
                + (request[40:48] if originate is None else originate)
                + ntp_bytes(now) + (ntp_bytes(now + transmit_shift) if transmit else bytes(8)))

    def run(self):
        while not self.stop.is_set():
            try:
                data, peer = self.sock.recvfrom(1024)
            except socket.timeout:
                continue
            self.requests.append(data)
            out = self.build(self, data) if self.build else self.reply(data)
            if out is None and self.via is not None:
                out = self.reply(data)          # a valid reply, but from a source address the client never asked
            if out is not None:
                (self.via or self.sock).sendto(out, peer)

    def close(self):
        self.stop.set()
        self.thread.join(1)
        self.sock.close()


class SntpTests(unittest.TestCase):
    def serve(self, build=None, skew=0.0):
        server = FakeNtpServer(build, skew)
        self.addCleanup(server.close)
        return server

    def test_offset_of_a_skewed_server_clock(self):
        server = self.serve(skew=2.5)
        sample = sntp_query(server.address, 1.0)
        self.assertAlmostEqual(sample["offset"], 2.5, delta=0.05)
        self.assertGreaterEqual(sample["delay"], 0)
        self.assertLess(sample["delay"], 0.5)
        request = server.requests[0]
        self.assertEqual((len(request), request[0]), (48, (0 << 6) | (4 << 3) | 3))   # LI=0 VN=4 mode=3

    def test_negative_skew_and_nonce_is_random_transmit_timestamp(self):
        server = self.serve(skew=-40.0)
        self.assertAlmostEqual(sntp_query(server.address, 1.0)["offset"], -40.0, delta=0.05)
        sntp_query(server.address, 1.0)
        self.assertNotEqual(server.requests[0][40:48], server.requests[1][40:48])

    def test_math_with_exact_timestamps(self):
        # T1=100, T2=110.2, T3=110.3, T4=100.5 -> offset ((10.2)+(9.8))/2=10.0, delay=0.5-0.1=0.4
        clock = iter([100.0, 100.5])
        server = self.serve(lambda s, req: s.reply(req)[:32] + ntp_bytes(110.2) + ntp_bytes(110.3))
        sample = sntp_query(server.address, 1.0, clock=lambda: next(clock))
        self.assertAlmostEqual(sample["offset"], 10.0, places=4)
        self.assertAlmostEqual(sample["delay"], 0.4, places=4)

    def assertRejected(self, build, text):
        server = self.serve(build)
        with self.assertRaises(TimeSyncError) as caught:
            sntp_query(server.address, 1.0)
        self.assertIn(text, str(caught.exception))

    def test_nonce_mismatch_rejected(self):
        self.assertRejected(lambda s, req: s.reply(req, originate=bytes(range(1, 9))), "does not match")

    def test_kiss_of_death_rejected_with_code(self):
        self.assertRejected(lambda s, req: s.reply(req, flags=(3 << 6) | (4 << 3) | 4, stratum=0, refid=b"RATE"), "RATE")

    def test_leap_indicator_3_rejected(self):
        self.assertRejected(lambda s, req: s.reply(req, flags=(3 << 6) | (4 << 3) | 4), "unsynchronised")

    def test_bad_mode_and_version_rejected(self):
        self.assertRejected(lambda s, req: s.reply(req, flags=(0 << 6) | (4 << 3) | 3), "not a server reply")
        self.assertRejected(lambda s, req: s.reply(req, flags=(0 << 6) | (2 << 3) | 4), "version")
        self.assertRejected(lambda s, req: s.reply(req, flags=(0 << 6) | (5 << 3) | 4), "version")

    def test_stratum_out_of_range_and_zero_transmit_rejected(self):
        self.assertRejected(lambda s, req: s.reply(req, stratum=16), "stratum")
        self.assertRejected(lambda s, req: s.reply(req, transmit=False), "transmit")

    def test_delay_out_of_range_rejected(self):
        self.assertRejected(lambda s, req: s.reply(req, transmit_shift=-3.0), "delay")   # server claims to have gone back in time -> huge
        self.assertRejected(lambda s, req: s.reply(req, transmit_shift=5.0), "delay")    # negative delay

    def test_truncated_packet_rejected(self):
        self.assertRejected(lambda s, req: s.reply(req)[:47], "truncated")

    def test_timeout_is_handled(self):
        server = self.serve(lambda s, req: None)
        started = time.monotonic()
        with self.assertRaises(TimeSyncError) as caught:
            sntp_query(server.address, 0.3)
        self.assertLess(time.monotonic() - started, 2)
        self.assertIn("no reply", str(caught.exception))

    def test_datagram_from_another_source_is_ignored(self):
        spoof = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(spoof.close)
        spoof.bind(("127.0.0.2", 0))
        server = self.serve(lambda s, req: None)
        server.via = spoof
        with self.assertRaises(TimeSyncError) as caught:
            sntp_query(server.address, 0.3)
        self.assertIn("no reply", str(caught.exception))

    def test_best_of_selection_by_delay_and_median(self):
        a = {"offset": 1.0, "delay": 0.30, "server": "a"}
        b = {"offset": 2.0, "delay": 0.05, "server": "b"}
        c = {"offset": 9.0, "delay": 0.10, "server": "c"}
        self.assertEqual(combine([a, b])["server"], "b")
        self.assertEqual(combine([a, b, c])["server"], "b")          # median offset of three, not the lowest delay
        self.assertEqual(combine([a])["server"], "a")

    def test_sample_queries_up_to_three_addresses_across_servers(self):
        infos = {"one": [(2, 2, 0, "", (f"10.0.0.{i}", 123)) for i in range(1, 4)], "two": [(2, 2, 0, "", ("10.0.1.1", 123))]}
        seen = []
        def query(info, timeout, clock):
            seen.append(info[4][0])
            return {"offset": float(len(seen)), "delay": 0.1 * len(seen)}
        sample = sntp_sample(["one", "two"], resolve=lambda host, port, type=0: infos[host], query=query)
        self.assertEqual(len(seen), 3)
        self.assertEqual(sample["offset"], 2.0)

    def test_sample_survives_dns_and_query_failures_and_reports_them(self):
        def resolve(host, port, type=0):
            if host == "bad":
                raise socket.gaierror("nope")
            return [(2, 2, 0, "", ("10.0.0.1", 123))]
        def query(info, timeout, clock):
            raise TimeSyncError("no reply")
        with self.assertRaises(TimeSyncError) as caught:
            sntp_sample(["bad", "worse"], resolve=resolve, query=query)
        self.assertIn("bad: name not found", str(caught.exception))
        self.assertIn("worse: no reply", str(caught.exception))

    def test_sample_respects_the_overall_budget(self):
        def query(info, timeout, clock):
            raise TimeSyncError("slow")
        infos = [(2, 2, 0, "", (f"10.0.0.{i}", 123)) for i in range(1, 20)]
        with self.assertRaises(TimeSyncError):
            sntp_sample(["x"], budget=0, resolve=lambda *a, **k: infos, query=query)


class FakeResponse:
    def __init__(self, headers):
        self.headers, self.closed = headers, False

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, headers=None, error=None):
        self.headers, self.error, self.calls = headers or {}, error, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        self.response = FakeResponse(self.headers)
        return self.response


class HttpsTests(unittest.TestCase):
    def sample(self, session, times=(1000.0, 1000.2), url="https://time.example/"):
        clock = iter(times)
        return https_sample(url, session, clock=lambda: next(clock))

    def test_date_header_offset(self):
        date = email.utils.formatdate(1003, usegmt=True)
        session = FakeSession({"Date": date})
        sample = self.sample(session)
        self.assertAlmostEqual(sample["offset"], 1003 + 0.5 - 1000.1, places=6)
        url, kwargs = session.calls[0]
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(kwargs["verify"])
        self.assertEqual(kwargs["timeout"], 5.0)
        self.assertTrue(session.response.closed)

    def test_missing_or_garbage_date_rejected(self):
        for headers, text in (({}, "no Date"), ({"Date": "yesterday-ish"}, "invalid Date"), ({"Date": ""}, "no Date")):
            with self.assertRaises(TimeSyncError, msg=str(headers)) as caught:
                self.sample(FakeSession(headers))
            self.assertIn(text, str(caught.exception))

    def test_redirect_is_not_followed_and_its_date_is_still_usable(self):
        session = FakeSession({"Date": email.utils.formatdate(1000, usegmt=True), "Location": "http://evil.example/"})
        self.sample(session)
        self.assertEqual(len(session.calls), 1)
        self.assertFalse(session.calls[0][1]["allow_redirects"])

    def test_network_error_and_non_https_rejected(self):
        with self.assertRaises(TimeSyncError):
            self.sample(FakeSession(error=ConnectionError("tls")))
        with self.assertRaises(TimeSyncError):
            self.sample(FakeSession({}), url="http://time.example/")

    def test_slow_response_rejected(self):
        with self.assertRaises(TimeSyncError):
            self.sample(FakeSession({"Date": email.utils.formatdate(1000, usegmt=True)}), times=(1000.0, 1007.0))


def source(**conf):
    """A TimeSource with an injected clock/monotonic pair and no thread."""
    state = {"wall": 1_800_000_000.0, "mono": 1000.0}
    ts = TimeSource(clock=lambda: state["wall"], mono=lambda: state["mono"])
    ts._conf = {**TimeSource.DEFAULTS, "enabled": True, **conf}
    ts.state = state
    return ts


class TimeSourceTests(unittest.TestCase):
    def test_disabled_means_zero_offset(self):
        ts = source(enabled=False)
        ts._ntp = Mock(return_value={"offset": 5.0, "delay": 0.01, "server": "x"})
        ts.sync_now()
        self.assertEqual(ts.time(), ts.state["wall"])
        self.assertFalse(ts.status()["enabled"])
        self.assertFalse(ts.synced())

    def test_success_sets_status_and_corrects_time_and_now(self):
        ts = source()
        ts._ntp = Mock(return_value={"offset": 2.5, "delay": 0.0123, "server": "pool.ntp.org"})
        self.assertTrue(ts.sync_now())
        self.assertAlmostEqual(ts.time(), ts.state["wall"] + 2.5)
        status = ts.status()
        self.assertEqual((status["enabled"], status["source"], status["server"], status["offset_ms"], status["delay_ms"], status["error"], status["stale"]),
                         (True, "ntp", "pool.ntp.org", 2500.0, 12.3, None, False))
        self.assertAlmostEqual(status["synced_at"], ts.state["wall"] + 2.5)
        self.assertEqual(ts.now(timezone.utc).timestamp(), ts.time())
        self.assertIsNotNone(ts.now().tzinfo)
        self.assertTrue(ts.monotonic_unchanged)

    def test_failure_keeps_last_good_until_six_hours_then_stale(self):
        ts = source()
        ts._ntp = Mock(return_value={"offset": 3.0, "delay": 0.01, "server": "s"})
        ts.sync_now()
        ts._ntp = Mock(side_effect=TimeSyncError("no reply"))
        ts._https = Mock(side_effect=TimeSyncError("no Date header"))
        ts.state["mono"] += 5 * 3600
        self.assertFalse(ts.sync_now())
        self.assertAlmostEqual(ts.time(), ts.state["wall"] + 3.0)
        self.assertFalse(ts.status()["stale"])
        self.assertIn("no reply", ts.status()["error"])
        self.assertIn("no Date header", ts.status()["error"])
        ts.state["mono"] += 3600 + 1
        self.assertEqual(ts.time(), ts.state["wall"])
        self.assertTrue(ts.status()["stale"])
        self.assertFalse(ts.synced())

    def test_absurd_offset_rejected_but_reported(self):
        ts = source()
        ts._ntp = Mock(return_value={"offset": 2 * 86400.0, "delay": 0.01, "server": "s"})
        self.assertFalse(ts.sync_now())
        self.assertEqual(ts.time(), ts.state["wall"])
        self.assertIn("172800", ts.status()["error"])
        self.assertIsNone(ts.status()["offset_ms"])

    def test_ntp_failure_falls_back_to_https_only_when_allowed(self):
        ts = source()
        ts._ntp = Mock(side_effect=TimeSyncError("no reply"))
        ts._https = Mock(return_value={"offset": 1.0, "delay": 0.2, "server": "https://x/"})
        self.assertTrue(ts.sync_now())
        self.assertEqual(ts.status()["source"], "https")
        off = source(fallback_https=False)
        off._ntp = Mock(side_effect=TimeSyncError("no reply"))
        off._https = Mock()
        self.assertFalse(off.sync_now())
        off._https.assert_not_called()
        only = source(source="https")
        only._ntp, only._https = Mock(), Mock(return_value={"offset": 1.0, "delay": 0.2, "server": "u"})
        self.assertTrue(only.sync_now())
        only._ntp.assert_not_called()

    def test_unexpected_exception_never_escapes(self):
        ts = source()
        ts._ntp = Mock(side_effect=RuntimeError("boom"))
        ts._https = Mock(side_effect=ValueError("bang"))
        self.assertFalse(ts.sync_now())
        self.assertIn("RuntimeError", ts.status()["error"])
        ts._clock = Mock(side_effect=OSError("clock"))
        self.assertIsInstance(ts.time(), float)

    def test_retry_backoff_schedule(self):
        self.assertEqual([TimeSource.retry_delay(n) for n in range(1, 8)], [60, 120, 240, 480, 900, 900, 900])

    def test_configure_starts_one_thread_restarts_on_change_and_stops(self):
        ts = TimeSource()
        ts._ntp = Mock(return_value={"offset": 1.0, "delay": 0.01, "server": "s"})
        conf = {"enabled": True, "servers": ["a.example"], "interval_minutes": 60}
        ts.configure(conf)
        thread = ts._thread
        self.addCleanup(ts.stop)
        self.wait(lambda: ts.sync_count >= 1)
        ts.configure(dict(conf))                                   # unchanged: same thread, no resync
        self.assertIs(ts._thread, thread)
        ts.configure({**conf, "servers": ["b.example"]})           # changed: immediate resync
        self.wait(lambda: ts.sync_count >= 2)
        self.assertIs(ts._thread, thread)
        self.assertEqual(ts._ntp.call_args[0][0], ["b.example"])
        ts.configure({"enabled": False})
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertIsNone(ts.status()["offset_ms"])
        self.assertLess(abs(ts.time() - time.time()), 1)

    def test_configure_with_garbage_does_not_raise(self):
        ts = TimeSource()
        ts._ntp = ts._https = Mock(side_effect=TimeSyncError("offline"))
        self.addCleanup(ts.stop)
        for bad in (None, "x", {"servers": 5, "interval_minutes": "no"}, {"enabled": True, "servers": [1, None]}):
            ts.configure(bad)

    def test_refresher_retries_after_failure(self):
        ts = TimeSource()
        results = [TimeSyncError("down"), {"offset": 0.5, "delay": 0.01, "server": "s"}]
        def ntp(servers, clock=None):
            value = results.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        ts._ntp = ntp
        ts._https = Mock(side_effect=TimeSyncError("no"))
        ts.configure({"enabled": True})
        self.addCleanup(ts.stop)
        self.wait(lambda: ts.status()["error"] is not None)
        self.assertIn("down", ts.status()["error"])
        ts._wake.set()                                              # skip the 60 s retry wait
        self.wait(lambda: ts.sync_count >= 1)
        self.assertIsNone(ts.status()["error"])

    def wait(self, predicate, seconds=3.0):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("condition not reached")


class ValidationTests(unittest.TestCase):
    def check(self, **values):
        data = defaults()
        data["integrations"]["timesync"].update(values)
        validate(data)

    def test_defaults_are_off_and_valid(self):
        data = defaults()
        conf = data["integrations"]["timesync"]
        self.assertEqual((conf["enabled"], conf["source"], conf["servers"], conf["interval_minutes"], conf["fallback_https"], conf["sync_device"]),
                         (False, "ntp", ["pool.ntp.org"], 60, True, False))
        validate(data)

    def test_valid_values(self):
        self.check(enabled=True, source="https", servers=["time.cloudflare.com", "192.168.1.1", "::1", "a-b.example.org."], interval_minutes=5, https_url="https://example.org/t")
        self.check(servers=["x"] * 5, interval_minutes=1440)

    def test_invalid_values(self):
        cases = [("enabled", 1), ("fallback_https", "y"), ("sync_device", None), ("source", "gps"), ("servers", []), ("servers", ["a"] * 6), ("servers", "pool.ntp.org"),
                 ("servers", ["ntp://pool.ntp.org"]), ("servers", ["pool.ntp.org/x"]), ("servers", ["pool ntp.org"]), ("servers", ["-bad.example"]),
                 ("servers", [" pool.ntp.org"]), ("servers", ["a" * 64 + ".org"]), ("servers", ["a." * 130 + "org"]), ("servers", [""]), ("servers", [5]),
                 ("https_url", "http://time.example/"), ("https_url", "ftp://x"), ("https_url", ""), ("https_url", "https://a b/"),
                 ("interval_minutes", 4), ("interval_minutes", 1441), ("interval_minutes", True), ("interval_minutes", "60")]
        for key, value in cases:
            with self.assertRaises(ValueError, msg=f"{key}={value!r}"):
                self.check(**{key: value})
        data = defaults()
        data["integrations"]["timesync"] = []
        with self.assertRaises(ValueError):
            validate(data)

    def test_old_config_without_timesync_loads_with_defaults(self):
        with tempfile.TemporaryDirectory() as root:
            store = ConfigStore(Path(root), migrate=False)
            raw = copy.deepcopy(store.data)
            raw["integrations"].pop("timesync")
            store.path.write_text(json.dumps(raw))
            loaded = ConfigStore(Path(root), migrate=False).data["integrations"]["timesync"]
            self.assertEqual(loaded, defaults()["integrations"]["timesync"])
            raw["integrations"]["timesync"] = {"enabled": True}
            store.path.write_text(json.dumps(raw))
            loaded = ConfigStore(Path(root), migrate=False).data["integrations"]["timesync"]
            self.assertTrue(loaded["enabled"])
            self.assertEqual(loaded["servers"], ["pool.ntp.org"])

    def test_signature_ignores_timesync(self):
        engine = Mock(demo=True)
        from keeper.integrations import Bridge
        bridge = Bridge(engine)
        with patch("keeper.integrations.timesource") as ts:
            data = defaults()
            bridge.configure(data)
            data["integrations"]["timesync"]["enabled"] = True
            signature = bridge.signature
            bridge.configure(data)
            self.assertEqual(bridge.signature, signature)
            ts.configure.assert_called_with({})                      # demo mode never contacts servers
            engine.demo = False
            bridge.configure(data)
            self.assertTrue(ts.configure.call_args[0][0]["enabled"])
        bridge.close()


def skewed(offset, wall=1_800_000_000.0):
    ts = TimeSource(clock=lambda: wall, mono=lambda: 5.0)
    ts._conf = {**TimeSource.DEFAULTS, "enabled": True}
    ts._offset, ts._good_mono = float(offset), 5.0
    return ts


class UsageTests(FixtureCase):
    def test_clock_widget_renders_the_corrected_time(self):
        wall = datetime(2030, 3, 4, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        s = slot("clock", timezone="UTC")
        def render(offset, at):
            with patch("keeper.widgets.timesource", skewed(offset, at)):
                return Renderer(demo=True).render(s).tobytes()
        self.assertEqual(render(3600, wall), render(0, wall + 3600))
        self.assertNotEqual(render(3600, wall), render(0, wall))

    def test_countdown_uses_the_corrected_time(self):
        wall = datetime(2030, 3, 4, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        s = slot("countdown", target="2030-03-04T12:10:00+00:00")
        def render(offset, at):
            with patch("keeper.widgets.timesource", skewed(offset, at)):
                return Renderer(demo=True).render(s).tobytes()
        self.assertEqual(render(300, wall), render(0, wall + 300))
        self.assertNotEqual(render(300, wall), render(0, wall))

    def test_engine_tick_wall_clock_comes_from_the_time_source(self):
        engine = Engine(self.store, demo=True)
        fake = Mock()
        fake.now.return_value = datetime(2030, 1, 1, 8, 30)
        fake.sync_device = False
        with patch("keeper.engine.timesource", fake):
            engine.tick()
        fake.now.assert_called()

    def test_custom_placeholder_time_uses_the_source(self):
        from keeper import extensions
        fake = Mock()
        fake.now.return_value = datetime(2030, 1, 1, 8, 30)
        s = slot("custom")
        s["elements"] = [{"type": "text", "text": "{time} {date}", "x": 0, "y": 0, "w": 100, "h": 30, "size": 12}]
        with patch("keeper.extensions.timesource", fake):
            extensions.custom_image(s, {})
        fake.now.assert_called()

    def test_device_clock_is_sent_after_a_sync_and_at_most_every_six_hours(self):
        self.d["enabled"] = True
        self.store.update_device(self.d)
        engine = Engine(self.store, client_factory=FakeClient)
        fake = Mock()
        fake.sync_device, fake.synced.return_value = True, True
        fake.time.return_value = 1_800_000_002.4
        data = self.store.snapshot()
        def queued():
            out = []
            while not engine.jobs.empty():
                out.append(engine.jobs.get_nowait())
            return out
        with patch("keeper.engine.timesource", fake):
            engine.sync_device_clock(data, 100.0)
            first = queued()
            self.assertEqual(len(first), 1)
            self.assertEqual((first[0][1], first[0][3]["payload"]), ("command", {"Command": "Device/SetUTC", "Utc": 1_800_000_002}))
            engine.sync_device_clock(data, 100.0 + 6 * 3600 - 1)
            self.assertEqual(queued(), [])
            engine.sync_device_clock(data, 100.0 + 6 * 3600)
            self.assertEqual(len(queued()), 1)
            fake.sync_device = False                                   # disabled: nothing, and a later enable resends
            engine.sync_device_clock(data, 100.0 + 12 * 3600)
            self.assertEqual(queued(), [])
            fake.sync_device, fake.synced.return_value = True, False   # not synced yet: nothing
            engine.sync_device_clock(data, 100.0 + 12 * 3600)
            self.assertEqual(queued(), [])
            fake.synced.return_value = True
            engine.sync_device_clock(data, 100.0 + 12 * 3600 + 1)
            self.assertEqual(len(queued()), 1)

    def test_device_clock_skips_paused_and_disabled_devices(self):
        engine = Engine(self.store, client_factory=FakeClient)
        fake = Mock()
        fake.sync_device, fake.synced.return_value = True, True
        fake.time.return_value = 1_800_000_000.0
        data = self.store.snapshot()
        with patch("keeper.engine.timesource", fake):
            engine.sync_device_clock(data, 1.0)                        # device not enabled
            self.assertTrue(engine.jobs.empty())
            data["devices"][0]["enabled"] = True
            engine.paused.add(data["devices"][0]["id"])
            engine.clock_sent = None
            engine.sync_device_clock(data, 2.0)
            self.assertTrue(engine.jobs.empty())


if __name__ == "__main__":
    unittest.main()
