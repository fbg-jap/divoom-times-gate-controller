import queue
import threading
import time
import unittest
from unittest.mock import patch

from keeper import notifications as nt
from keeper.notifications import (NotificationService, RateLimiter, Unavailable, app_allowed,
                                  clean, format_notification, new_toasts)


class FakeAutomations:
    def __init__(self):
        self.calls = []

    def enqueue(self, *args):
        self.calls.append(args)


class FakeEngine:
    def __init__(self):
        self.stop_event = threading.Event()
        self.automations = FakeAutomations()
        self.logs = []

    def log(self, message, level="info"):
        self.logs.append((level, message))


def data(**overrides):
    cfg = {"enabled": True, "panel": 3, "seconds": 8, "allow_apps": [], "deny_apps": [],
           "show_body": False, "per_minute": 6, **overrides}
    return {"active_device": "dev1", "integrations": {"notifications": cfg}}


def wait_for(predicate, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(.01)
    return False


class PureFunctionTests(unittest.TestCase):
    def test_clean_strips_control_chars_and_truncates(self):
        self.assertEqual(clean("a\nb\r\tc\x00\x1b[d", 50), "a b c[d")
        self.assertEqual(len(clean("x" * 900, 500)), 500)

    def test_format_summary_only_by_default(self):
        self.assertEqual(format_notification("Mail", "New message", "secret body"), ("Mail", "New message"))

    def test_format_with_body_and_limits(self):
        title, text = format_notification("A" * 200, "S", "B" * 900, show_body=True)
        self.assertEqual(len(title), 80)
        self.assertEqual(len(text), 500)
        self.assertTrue(text.startswith("S - B"))

    def test_format_empty(self):
        self.assertIsNone(format_notification("App", "", "body"))
        self.assertEqual(format_notification("", "hi", ""), ("NOTIFICATION", "hi"))
        self.assertEqual(format_notification("App", "", "body", True), ("App", "body"))

    def test_allow_deny(self):
        self.assertTrue(app_allowed("Slack", [], []))
        self.assertFalse(app_allowed("Slack", [], ["slack"]))
        self.assertTrue(app_allowed("SLACK", ["slack"], []))
        self.assertFalse(app_allowed("Mail", ["slack"], []))
        self.assertFalse(app_allowed("Slack", ["slack"], ["SLACK"]))

    def test_rate_limit_sliding_window(self):
        now = [0.]
        limiter = RateLimiter(lambda: now[0])
        self.assertEqual([limiter.allow(2) for _ in range(3)], [True, True, False])
        now[0] = 59
        self.assertFalse(limiter.allow(2))
        now[0] = 61
        self.assertTrue(limiter.allow(2))

    def test_new_toasts_dedup(self):
        seen = set()
        first = [(1, "A", "s1", "b1"), (2, "B", "s2", "b2")]
        self.assertEqual(new_toasts(first, seen), [("A", "s1", "b1"), ("B", "s2", "b2")])
        self.assertEqual(new_toasts(first, seen), [])
        self.assertEqual(new_toasts([(2, "B", "s2", "b2"), (3, "C", "s3", "")], seen), [("C", "s3", "")])
        self.assertEqual(seen, {2, 3})


class ServiceTests(unittest.TestCase):
    def service(self, items=(), error=None):
        engine = FakeEngine()
        gate = threading.Event()

        def backend(stop):
            if error:
                raise error
            gate.wait(3)
            yield from items
            stop.wait(3)
        return engine, NotificationService(engine, backend), gate

    def tearDown(self):
        pass

    def test_handle_enqueues_zero_based_panel(self):
        engine, service, _ = self.service()
        service.device_id = "dev1"
        service.config = data(panel=3, seconds=12)["integrations"]["notifications"]
        self.assertTrue(service.handle("Mail", "Hello", "body"))
        self.assertEqual(engine.automations.calls, [("dev1", 2, "Hello", "Mail", 12, False)])

    def test_handle_filters_and_rate_limits(self):
        engine, service, _ = self.service()
        service.device_id = "dev1"
        service.config = data(deny_apps=["Spam"], per_minute=2)["integrations"]["notifications"]
        self.assertFalse(service.handle("spam", "x", ""))
        self.assertTrue(service.handle("A", "1", ""))
        self.assertTrue(service.handle("A", "2", ""))
        self.assertFalse(service.handle("A", "3", ""))
        self.assertEqual(len(engine.automations.calls), 2)

    def test_handle_never_raises(self):
        engine, service, _ = self.service()
        service.device_id = "dev1"
        service.config = data()["integrations"]["notifications"]
        with patch.object(engine.automations, "enqueue", side_effect=RuntimeError("boom")):
            self.assertFalse(service.handle("A", "x", ""))
        self.assertTrue(engine.logs)
        service.config = {"enabled": True, "panel": "bad"}
        self.assertFalse(service.handle("A", "x", ""))

    def test_lifecycle_enable_disable(self):
        engine, service, gate = self.service([("App", "One", "b")])
        service.tick(data(enabled=False))
        self.assertIsNone(service.thread)
        self.assertEqual(service.status, "Disabled")
        service.tick(data())
        self.assertIsNotNone(service.thread)
        gate.set()
        self.assertTrue(wait_for(lambda: engine.automations.calls))
        self.assertEqual(engine.automations.calls[0][2:4], ("One", "App"))
        self.assertEqual(service.status, "Running")
        thread, stop = service.thread, service.stop
        service.tick(data(enabled=False))
        self.assertTrue(stop.is_set())
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(service.status, "Disabled")

    def test_unavailable_backend_reports_status_and_retries_later(self):
        engine, service, _ = self.service(error=Unavailable("jeepney not installed"))
        service.tick(data(), now=100.)
        self.assertTrue(wait_for(lambda: service.status.startswith("Unavailable")))
        self.assertEqual(service.status, "Unavailable (jeepney not installed)")
        thread = service.thread
        thread.join(2)
        service.tick(data(), now=101.)
        self.assertIs(service.thread, thread)
        service.tick(data(), now=100. + nt.RETRY_SECONDS + 1)
        self.assertIsNot(service.thread, thread)
        service.close()

    def test_backend_crash_is_contained(self):
        engine, service, _ = self.service(error=ValueError("x"))
        service.tick(data())
        self.assertTrue(wait_for(lambda: service.status == "Unavailable (ValueError)"))
        service.close()

    def test_no_thread_after_engine_stop(self):
        engine, service, _ = self.service()
        engine.stop_event.set()
        service.tick(data())
        self.assertIsNone(service.thread)

    def test_linux_backend_without_jeepney_is_unavailable(self):
        with patch.dict("sys.modules", {"jeepney": None}):
            with self.assertRaises(Unavailable) as ctx:
                next(nt.linux_backend(threading.Event()))
        self.assertIn("jeepney not installed", str(ctx.exception))


class BridgeIntegrationTests(unittest.TestCase):
    def test_status_exposes_notifications(self):
        from keeper.integrations import Bridge
        engine = FakeEngine()
        engine.store = type("S", (), {"snapshot": lambda self: {"devices": [], "scenes": []}})()
        bridge = Bridge(engine)
        self.assertEqual(bridge.status()["notifications"], "Disabled")


if __name__ == "__main__":
    unittest.main()
