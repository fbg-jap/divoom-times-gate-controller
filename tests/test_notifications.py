import os
import json
import queue
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from keeper import notifications as nt
from keeper.notifications import (NotificationService, RateLimiter, Unavailable, app_allowed,
                                  classify_teams, clean, format_notification, new_toasts)


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

    def test_clean_caps_input_and_ignores_non_strings(self):
        started = time.monotonic()
        self.assertEqual(len(nt.clean("a" * 50_000_000, 80)), 80)
        self.assertLess(time.monotonic() - started, 1)
        for value in (None, 123, b"abc", ["a"], {"a": 1}):
            self.assertEqual(nt.clean(value, 80), "")

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
        self.assertEqual(engine.automations.calls, [("dev1", 2, "Hello", "Mail", 12, False, "#ff7a3d", True, True)])

    @unittest.skipIf(os.name == "nt", "installed apps come from XDG .desktop entries (Linux only)")
    def test_known_apps_lists_seen_senders_and_installed_entries(self):
        import tempfile
        from pathlib import Path
        from keeper import notifications
        engine, service, _ = self.service()
        service.device_id = "dev1"
        service.config = data()["integrations"]["notifications"]
        service.handle("Slack", "hi", "")
        service.handle("Brave", "hi", "")
        service.handle("slack", "again", "")   # same app: moved to the end, no duplicate by case
        with tempfile.TemporaryDirectory() as temp:
            apps = Path(temp) / "applications"
            apps.mkdir()
            (apps / "a.desktop").write_text("[Desktop Entry]\nName=Zeta Editor\nType=Application\n", encoding="utf-8")
            (apps / "b.desktop").write_text("[Desktop Entry]\nName=Hidden Thing\nNoDisplay=true\n", encoding="utf-8")
            (apps / "c.desktop").write_text("[Desktop Entry]\nName=Alpha Mail\n[Desktop Action x]\nName=Compose\n", encoding="utf-8")
            found = notifications.installed_apps(now=1e9, environ={"XDG_DATA_HOME": temp, "XDG_DATA_DIRS": "/nonexistent"})
        self.assertEqual(found, ["Alpha Mail", "Zeta Editor"])
        self.assertEqual(service.known_apps()["seen"], ["Brave", "slack"])
        notifications._installed.update(at=-1e9, names=[])

    def test_custom_color_border_and_blink_switches(self):
        engine, service, _ = self.service()
        service.device_id = "dev1"
        service.config = data(color="#00ff88", border=False, blink=False)["integrations"]["notifications"]
        self.assertTrue(service.handle("Mail", "Hello", ""))
        self.assertEqual(engine.automations.calls[-1][6:], ("#00ff88", False, False))
        service.config = data(color="red")["integrations"]["notifications"]   # an invalid color falls back to the default
        self.assertTrue(service.handle("Mail", "Again", ""))
        self.assertEqual(engine.automations.calls[-1][6], "#ff7a3d")

    def test_handle_filters_and_rate_limits(self):
        engine, service, _ = self.service()
        service.device_id = "dev1"
        service.config = data(deny_apps=["Spam"], per_minute=2)["integrations"]["notifications"]
        self.assertFalse(service.handle("spam", "x", ""))
        self.assertTrue(service.handle("A", "1", ""))
        self.assertTrue(service.handle("A", "2", ""))
        self.assertFalse(service.handle("A", "3", ""))
        self.assertEqual(len(engine.automations.calls), 2)

    def test_limiter_is_consulted_before_formatting(self):
        engine, service, _ = self.service()
        service.device_id = "dev1"
        service.config = data(per_minute=1)["integrations"]["notifications"]
        self.assertTrue(service.handle("A", "1", ""))
        with patch.object(nt, "format_notification") as fmt:
            self.assertFalse(service.handle("A", "2", ""))
            fmt.assert_not_called()

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


PATTERNS = nt.TEAMS_DEFAULTS["patterns"]


class TeamsClassifyTests(unittest.TestCase):
    def kind(self, app, summary, body=""):
        found = classify_teams(app, summary, body, PATTERNS)
        return found and found["kind"]

    def test_kinds_and_languages(self):
        self.assertEqual(self.kind("Microsoft Teams", "Ana Ruiz", "see you at 5"), "chat")
        for text in ("Ana is calling you", "Incoming call", "Ana ringer til dig", "Ana te está llamando", "Ana ruft an"):
            self.assertEqual(self.kind("Microsoft Teams", text), "call", text)
        for text in ("Ana mentioned you", "Ana nævnte dig", "Ana te mencionó", "Ana hat Sie erwähnt", "Ana", "@Jakob hi"):
            body = "@Jakob hi" if text == "Ana" else ""
            self.assertEqual(self.kind("Microsoft Teams", text, body), "mention", text)

    def test_apps(self):
        self.assertEqual(self.kind("teams-for-linux", "Ana", "hi"), "chat")
        self.assertEqual(self.kind("Brave", "Ana in General", "hi teams.microsoft.com"), "chat")
        self.assertEqual(self.kind("Google Chrome", "Ana", "https://teams.cloud.microsoft"), "chat")
        self.assertIsNone(self.kind("Firefox", "Ana", "hello"))
        self.assertIsNone(classify_teams("Mail", "Teams meeting notes", "", PATTERNS))

    def test_sender_trimming(self):
        self.assertEqual(classify_teams("Microsoft Teams", "Ana in General", "", PATTERNS)["sender"], "Ana")
        self.assertEqual(classify_teams("Microsoft Teams", "Ana (via Teams)", "", PATTERNS)["sender"], "Ana")
        self.assertEqual(classify_teams("Microsoft Teams", "Ana is calling you", "", PATTERNS)["sender"], "Ana")
        self.assertEqual(classify_teams("Microsoft Teams", "Ana mentioned you in General", "", PATTERNS)["sender"], "Ana")
        self.assertLessEqual(len(classify_teams("Microsoft Teams", "x" * 999, "", PATTERNS)["sender"]), 72)

    def test_odd_input(self):
        for args in ((None, "a", "b", PATTERNS), ("Microsoft Teams", 5, "", PATTERNS), ("Microsoft Teams", "a", b"x", PATTERNS),
                     ("Microsoft Teams", "a", "", None), ("a", "b", "c", [None, 5, ""])):
            self.assertIsNone(classify_teams(*args))
        start = time.monotonic()
        self.assertEqual(classify_teams("Microsoft Teams", "x" * 10 ** 6, "y" * 10 ** 6, PATTERNS)["kind"], "chat")
        self.assertLess(time.monotonic() - start, 1)


class TeamsServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = FakeEngine()
        self.service = NotificationService(self.engine, lambda stop: iter(()))
        self.service.device_id = "dev1"

    def configure(self, teams=None, **general):
        self.service.config = data(teams={"enabled": True, **(teams or {})}, **general)["integrations"]["notifications"]

    def test_privacy_default_hides_preview(self):
        self.configure()
        self.assertTrue(self.service.handle("Microsoft Teams", "Ana in General", "secret text"))
        self.assertEqual(self.engine.automations.calls,
                         [("dev1", 2, "New message", "Teams · Ana", 8, False, "#6264a7", True, True)])

    def test_show_preview_is_capped(self):
        self.configure({"show_preview": True})
        self.service.handle("Microsoft Teams", "Ana", "z" * 900)
        self.assertEqual(len(self.engine.automations.calls[0][2]), 500)
        self.service.handle("Microsoft Teams", "Ana mentioned you", "hello")
        self.assertIn("Mentioned you", self.engine.automations.calls[1][2])
        self.assertIn("hello", self.engine.automations.calls[1][2])

    def test_allow_list_does_not_block_teams_but_deny_does(self):
        self.configure(allow_apps=["Firefox"], deny_apps=["Brave"])
        self.assertTrue(self.service.handle("teams-for-linux", "Ana", "hi"))
        self.assertFalse(self.service.handle("Chromium", "Ana", "hello"))   # not Teams, not allowed
        self.assertTrue(self.service.handle("Firefox", "Ana", "hello"))
        self.assertFalse(self.service.handle("Brave", "teams.microsoft.com", "Ana: hi"))   # deny wins
        self.assertEqual(len(self.engine.automations.calls), 2)

    def test_mention_without_preview(self):
        self.configure()
        self.service.handle("Microsoft Teams", "Ana mentioned you", "secret")
        self.assertEqual(self.engine.automations.calls[0][2], "Mentioned you")

    def test_kind_filters_drop(self):
        self.configure({"chats": False, "mentions": False, "calls": False})
        for summary in ("Ana", "Ana mentioned you", "Ana is calling you"):
            self.assertFalse(self.service.handle("Microsoft Teams", summary, ""))
        self.assertEqual(self.engine.automations.calls, [])

    def test_call_seconds_and_buzzer(self):
        self.configure({"call_seconds": 30, "buzzer_on_call": True, "seconds": 10})
        self.service.handle("Microsoft Teams", "Ana is calling you", "")
        self.assertEqual(self.engine.automations.calls[0], ("dev1", 2, "Incoming call", "Teams · Ana", 30, True, "#6264a7", True, True))
        self.service.handle("Microsoft Teams", "Ana", "")
        self.assertEqual(self.engine.automations.calls[1][4:6], (10, False))

    def test_panel_override_and_fallback(self):
        self.configure({"panel": 5})
        self.service.handle("Microsoft Teams", "Ana", "")
        self.assertEqual(self.engine.automations.calls[0][1], 4)
        self.configure({"panel": 0})
        self.service.handle("Microsoft Teams", "Ana", "")
        self.assertEqual(self.engine.automations.calls[1][1], 2)

    def test_deny_list_applies_to_teams_but_the_allow_list_does_not(self):
        self.configure(deny_apps=["microsoft teams"])
        self.assertFalse(self.service.handle("Microsoft Teams", "Ana", ""))
        self.configure(allow_apps=["Mail"])
        self.assertTrue(self.service.handle("Microsoft Teams", "Ana", ""))

    def test_rate_limiter_still_first(self):
        self.configure(per_minute=1)
        self.assertTrue(self.service.handle("Microsoft Teams", "Ana", ""))
        self.assertFalse(self.service.handle("Microsoft Teams", "Ana", ""))
        self.assertEqual(len(self.engine.automations.calls), 1)

    def test_non_teams_path_is_unchanged_with_teams_enabled(self):
        self.configure()
        self.assertTrue(self.service.handle("Mail", "Hello", "body"))
        self.assertEqual(self.engine.automations.calls, [("dev1", 2, "Hello", "Mail", 8, False, "#ff7a3d", True, True)])

    def test_teams_disabled_or_missing_uses_old_path(self):
        self.service.config = data(teams={"enabled": False})["integrations"]["notifications"]
        self.service.handle("Microsoft Teams", "Ana", "")
        self.service.config = data()["integrations"]["notifications"]   # old config without teams
        self.service.handle("Microsoft Teams", "Ana", "")
        self.assertEqual(self.engine.automations.calls, [("dev1", 2, "Ana", "Microsoft Teams", 8, False, "#ff7a3d", True, True)] * 2)

    def test_partial_teams_config_gets_defaults(self):
        self.configure({"enabled": True})
        self.assertTrue(self.service.handle("teams-for-linux", "Ana", ""))


class BridgeIntegrationTests(unittest.TestCase):
    def test_status_exposes_notifications(self):
        from keeper.integrations import Bridge
        engine = FakeEngine()
        engine.store = type("S", (), {"snapshot": lambda self: {"devices": [], "scenes": []}})()
        bridge = Bridge(engine)
        self.assertEqual(bridge.status()["notifications"], "Disabled")

    def bridge(self):
        from keeper.integrations import Bridge
        engine = FakeEngine(); engine.demo = False
        engine.renderer = SimpleNamespace(providers=SimpleNamespace(extra=SimpleNamespace()))
        bridge = Bridge(engine)
        self.addCleanup(bridge.notifications.close)
        return bridge

    def test_only_api_and_mqtt_edits_restart_the_bridge(self):
        bridge = self.bridge()
        base = {"integrations": {"api": {"enabled": False}, "mqtt": {"enabled": False}, "prtg": {"enabled": False},
                                 "mail": {}, "spotify": {}, "notifications": {"enabled": False}}}
        def edited(section, **values):
            copy_ = json.loads(json.dumps(base)); copy_["integrations"][section].update(values); return copy_
        with patch.object(bridge, "close", wraps=bridge.close) as close:
            bridge.configure(base); self.assertEqual(close.call_count, 1)
            for change in (edited("prtg", token="t"), edited("mail", host="h"), edited("spotify", refresh_token="r"),
                           edited("notifications", enabled=True, seconds=9)):
                bridge.configure(change)
            self.assertEqual(close.call_count, 1)
            bridge.configure(edited("api", port=9999)); self.assertEqual(close.call_count, 2)
            bridge.configure(edited("api", port=9999)); self.assertEqual(close.call_count, 2)
            bridge.configure(edited("mqtt", host="broker")); self.assertEqual(close.call_count, 3)

    def test_notification_service_still_sees_its_own_config_changes(self):
        bridge = self.bridge()
        with patch.object(bridge.notifications, "start") as start:
            bridge.tick(data(enabled=False), 1.)
            start.assert_not_called()
            bridge.tick(data(panel=4), 2.)  # same api/mqtt signature, new notification settings
            start.assert_called_once()
            self.assertEqual(bridge.notifications.config["panel"], 4)

    def test_rotated_token_is_saved_only_if_it_replaces_the_stored_one(self):
        bridge = self.bridge()
        stored = {"integrations": {"spotify": {"refresh_token": "T0"}}}
        bridge.engine.store = SimpleNamespace(change=lambda callback: callback(stored))
        bridge.save_spotify_token("T1", "T0")
        self.assertEqual(stored["integrations"]["spotify"]["refresh_token"], "T1")
        stored["integrations"]["spotify"]["refresh_token"] = ""  # Disconnect while a refresh was in flight
        bridge.save_spotify_token("T2", "T1")
        self.assertEqual(stored["integrations"]["spotify"]["refresh_token"], "")


if __name__ == "__main__":
    unittest.main()


class TeamsMentionRuleTests(unittest.TestCase):
    PATTERNS = ["microsoft teams"]

    def kind(self, body):
        from keeper.notifications import classify_teams
        return classify_teams("Microsoft Teams", "Ana Lopez", body, self.PATTERNS)["kind"]

    def test_at_mention_needs_a_word_start_and_an_email_address_is_a_chat(self):
        self.assertEqual(self.kind("@Jakob can you look at this?"), "mention")
        self.assertEqual(self.kind("thanks @Jakob"), "mention")
        self.assertEqual(self.kind("mail me at ana@example.com"), "chat")
        self.assertEqual(self.kind("price is 5 @ 10 each"), "chat")
        self.assertEqual(self.kind("lone @"), "chat")


class TeamsOnlyAndStatusLogTests(unittest.TestCase):
    def make(self, backend=None):
        engine = FakeEngine()
        service = NotificationService(engine, backend or (lambda stop: iter(())))
        service.device_id = "dev1"
        return engine, service

    def only_teams(self, service, **teams):
        service.config = data(enabled=False, teams={"enabled": True, **teams})["integrations"]["notifications"]

    def test_teams_only_passes_teams_and_drops_the_rest(self):
        engine, service = self.make()
        self.only_teams(service)
        self.assertTrue(service.handle("Microsoft Teams", "Ana in General", "hi"))
        self.assertFalse(service.handle("Mail", "New message", "secret"))
        self.assertEqual(len(engine.automations.calls), 1)
        self.assertEqual(engine.automations.calls[0][3], "Teams · Ana")

    def test_teams_only_does_not_spend_the_rate_limit_on_other_apps(self):
        engine, service = self.make()
        self.only_teams(service, per_minute=1)
        service.config["per_minute"] = 1
        for _ in range(5):
            service.handle("Mail", "x", "")
        self.assertTrue(service.handle("Microsoft Teams", "Ana", "hi"))

    def test_general_on_still_shows_non_teams(self):
        engine, service = self.make()
        service.config = data(teams={"enabled": True})["integrations"]["notifications"]
        self.assertTrue(service.handle("Mail", "Hello", ""))
        self.assertTrue(service.handle("Microsoft Teams", "Ana", "hi"))
        self.assertEqual(len(engine.automations.calls), 2)

    def test_both_off_drops_everything(self):
        engine, service = self.make()
        service.config = data(enabled=False, teams={"enabled": False})["integrations"]["notifications"]
        self.assertFalse(service.handle("Microsoft Teams", "Ana", "hi"))
        self.assertFalse(service.handle("Mail", "x", ""))

    def test_tick_starts_for_teams_only_and_not_when_both_off(self):
        gate = threading.Event()
        engine, service = self.make(lambda stop: (gate.wait(3), iter(()))[1])
        service.tick(data(enabled=False, teams={"enabled": False}))
        self.assertIsNone(service.thread)
        service.tick(data(enabled=False, teams={"enabled": True}))
        self.assertIsNotNone(service.thread)
        service.tick(data(enabled=False, teams={"enabled": False}))
        self.assertIsNone(service.thread)
        gate.set()

    def test_status_changes_are_logged_once_without_content(self):
        def backend(stop):
            yield ("Mail", "TOPSECRET summary", "TOPSECRET body")
            stop.wait(3)
        engine, service = self.make(backend)
        service.tick(data(show_body=True), now=1.)
        self.assertTrue(wait_for(lambda: engine.automations.calls))
        service.tick(data(), now=2.)
        service.tick(data(), now=2.5)
        service.tick(data(enabled=False), now=3.)
        service.tick(data(enabled=False), now=4.)
        self.assertEqual([m for _, m in engine.logs],
                         ["Notification listener: Running", "Notification listener: Disabled"])
        self.assertNotIn("TOPSECRET", " ".join(m for _, m in engine.logs))

    def test_unavailable_is_a_warning_logged_once_across_retries(self):
        engine, service = self.make(lambda stop: (_ for _ in ()).throw(Unavailable("no session D-Bus: OSError")))
        service.tick(data(), now=100.)
        self.assertTrue(wait_for(lambda: service.status.startswith("Unavailable")))
        service.thread.join(2)
        service.tick(data(), now=101.)
        service.tick(data(), now=100. + nt.RETRY_SECONDS + 1)
        self.assertTrue(wait_for(lambda: not service.thread.is_alive()))
        service.tick(data(), now=100. + nt.RETRY_SECONDS + 2)
        self.assertEqual(engine.logs, [("warning", "Notification listener: Unavailable (no session D-Bus: OSError)")])
