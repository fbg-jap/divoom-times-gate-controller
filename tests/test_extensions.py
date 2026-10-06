import copy
import json
import queue
import time
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw
import requests

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
        for kind in ("music", "rss", "custom", "pomodoro", "sensor", "prtg"):
            image = r.render(slot(kind, url="https://example.test"))
            self.assertEqual(image.size, (128, 128))
        with self.assertRaises(ValueError):
            validate_content(slot("custom", elements=[{"type": "bar", "maximum": 0}]))


class PrtgTests(unittest.TestCase):
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
        data = p.prtg("https://prtg.test/", "TOKEN", False)
        self.assertEqual({k: data[k] for k in ("up", "warning", "down", "paused", "unusual")}, dict(up=1, warning=1, down=1, paused=1, unusual=1))
        self.assertEqual(data["worst"], "d · http")
        args, kwargs = p.session.get.call_args
        self.assertEqual(args[0], "https://prtg.test/api/table.json")
        self.assertIs(kwargs["verify"], False); self.assertEqual(kwargs["timeout"], 8)
        self.assertEqual(kwargs["params"]["apitoken"], "TOKEN")

    def test_worst_ordering_warning_over_unusual(self):
        p = Providers(); sensors = [{"device": "u", "sensor": "1", "status_raw": 10}, {"device": "w", "sensor": "2", "status_raw": 4}]
        p.session.get = Mock(return_value=self.reply({"sensors": sensors}))
        self.assertEqual(p.prtg("http://x.test", "t")["worst"], "w · 2")

    def test_failure_is_negative_cached_and_default_verifies_tls(self):
        p = Providers(); p.session.get = Mock(return_value=self.reply({}, 500))
        self.assertIsNone(p.prtg("http://x.test", "t")); self.assertIsNone(p.prtg("http://x.test", "t"))
        self.assertEqual(p.session.get.call_count, 1); self.assertIs(p.session.get.call_args.kwargs["verify"], True)
        p.session.get = Mock(return_value=self.reply({"unexpected": 1}))
        self.assertIsNone(p.prtg("http://y.test", "t"))

    def test_oversized_and_unconfigured(self):
        p = Providers(); response = self.reply({}); response.iter_content = lambda size: iter([b"x" * (2 * 1024**2 + 1)])
        p.session.get = Mock(return_value=response)
        self.assertIsNone(p.prtg("http://x.test", "t"))
        p.session.get.reset_mock(); self.assertIsNone(p.prtg("", "t")); self.assertIsNone(p.prtg("http://x.test", ""))
        p.session.get.assert_not_called()

    def test_render_states_and_validation(self):
        p = Providers(); p.session.get = Mock(return_value=self.reply(self.SENSORS))
        from keeper.extensions import render_extra
        self.assertIsNone(p.extra.prtg())  # disabled
        p.extra.prtg_conf = {"enabled": True, "base_url": "http://x.test", "token": "t", "verify_tls": True}
        self.assertEqual(p.extra.prtg()["down"], 1)
        self.assertEqual(render_extra(slot("prtg"), p).size, (128, 128))
        p.extra.prtg_conf = {}
        self.assertEqual(render_extra(slot("prtg"), p).size, (128, 128))
        validate_content(slot("prtg"))


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
