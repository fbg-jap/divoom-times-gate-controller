import base64
import copy
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from PIL import Image
import requests

from keeper.config import ConfigStore, device, slot, uid, validate
from keeper.engine import Engine
from keeper.protocol import Client, DeviceError, media_frames, resize
from keeper.widgets import Providers, Renderer


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ConfigStore(self.root / "studio", migrate=False)
        self.d = self.store.get_device()
        self.d["ip"] = "192.168.1.10"
        self.store.update_device(self.d)

    def tearDown(self):
        self.temp.cleanup()

    def image(self, name="test.png"):
        path = self.root / name
        Image.new("RGB", (240, 120), "red").save(path)
        return path


class StoreCase(FixtureCase):
    def test_migration_preserves_legacy_and_copies_media(self):
        old_root = self.root / "old-appdata"
        old = old_root / "DivoomKeeper" / "config.json"
        old.parent.mkdir(parents=True)
        source = self.image()
        raw = {"device_ip": "192.168.1.10", "screens": [{"path": str(source)}],
               "device_profiles": {"192.168.1.11": {"screens": [{"path": str(source)}]}},
               "speed": 130, "quality": 90, "start_with_windows": True}
        old.write_text(json.dumps(raw))
        original = old.read_bytes()
        with patch.dict("os.environ", {"APPDATA": str(old_root)}):
            migrated = ConfigStore(self.root / "migrated")
        self.assertEqual(old.read_bytes(), original)
        self.assertEqual(len(migrated.data["devices"]), 2)
        d = migrated.get_device()
        self.assertEqual(d["screens"][0]["fit"], "stretch")
        self.assertEqual(d["speed"], 130)
        self.assertFalse(d["enabled"])
        self.assertFalse(migrated.data["startup"])
        source.unlink()
        self.assertTrue(Path(d["screens"][0]["path"]).is_file())

    def test_corrupt_config_not_overwritten(self):
        self.store.path.write_text("{broken")
        with self.assertRaises(json.JSONDecodeError):
            ConfigStore(self.store.root)
        self.assertEqual(self.store.path.read_text(), "{broken")

    def test_failed_change_rolls_back(self):
        before = self.store.snapshot()
        with self.assertRaises(ValueError):
            self.store.change(lambda data: data.update(devices=[]))
        self.assertEqual(before, self.store.snapshot())
        self.assertEqual(json.loads(self.store.path.read_text()), before)

    def test_portable_export_import_with_scenes(self):
        self.d["screens"][0] = slot("media", path=self.store.import_media(self.image()))
        self.d["enabled"] = True
        self.store.update_device(self.d)
        self.store.change(lambda data: data["scenes"].append({"id": uid(), "name": "Test", "screens": self.d["screens"]}))
        bundle = self.root / "backup.zip"
        self.store.export(bundle)
        target = ConfigStore(self.root / "target", migrate=False)
        target.import_bundle(bundle)
        imported = target.get_device()
        self.assertFalse(imported["enabled"])
        self.assertTrue(Path(imported["screens"][0]["path"]).is_file())
        self.assertTrue(Path(target.data["scenes"][0]["screens"][0]["path"]).is_file())

    def test_zip_traversal_rejected(self):
        data = self.store.snapshot()
        data["devices"][0]["screens"][0] = slot("media", path="media/../../outside.png")
        bundle = self.root / "bad.zip"
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("config.json", json.dumps(data))
            archive.writestr("media/../../outside.png", b"bad")
        before = self.store.snapshot()
        with self.assertRaises(ValueError):
            self.store.import_bundle(bundle)
        self.assertEqual(before, self.store.snapshot())
        self.assertFalse((self.root / "outside.png").exists())

    def test_invalid_schedule_rejected(self):
        with self.assertRaises(ValueError):
            self.store.change(lambda data: data["schedules"].append({"time": "25:00", "action": "on"}))


class ProtocolTests(unittest.TestCase):
    def test_real_http_exchange_with_device_simulator(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        captured = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                captured.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error_code":0}')
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        class LocalSession:
            def post(self, url, **kwargs):
                return requests.post(f"http://127.0.0.1:{server.server_port}/post", **kwargs)
        try:
            client = Client("127.0.0.1", LocalSession())
            client.command({"Command": "Channel/GetAllConf"})
            client.send_frames([Image.new("RGB", (128, 128), "red")], 4)
            self.assertEqual(captured[0]["Command"], "Channel/GetAllConf")
            self.assertEqual(captured[1]["LcdArray"], [0, 0, 0, 0, 1])
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_original_jpeg_payload_and_offsets(self):
        session = MagicMock()
        session.post.return_value.json.return_value = {"error_code": 0}
        client = Client("192.168.1.10", session)
        frames = [Image.new("RGB", (128, 128), c) for c in ["red", "blue"]]
        with patch("keeper.protocol.time.sleep"):
            client.send_frames(frames, 3, 85, 120)
        self.assertEqual(session.post.call_count, 2)
        for i, call in enumerate(session.post.call_args_list):
            self.assertEqual(call.args[0], "http://192.168.1.10/post")
            payload = call.kwargs["json"]
            self.assertEqual(payload["LcdArray"], [0, 0, 0, 1, 0])
            self.assertEqual(payload["PicOffset"], i)
            self.assertEqual(payload["PicNum"], 2)
            self.assertEqual(payload["PicSpeed"], 120)
            with Image.open(io.BytesIO(base64.b64decode(payload["PicData"]))) as img:
                self.assertEqual(img.format, "JPEG")
                self.assertEqual(img.size, (128, 128))

    def test_rejected_json_is_not_success(self):
        for body in [{"error_code": "DeviceToken is err"}, {}, [], {"error_code": 3}]:
            session = MagicMock()
            session.post.return_value.json.return_value = body
            with self.assertRaises(DeviceError):
                Client("192.168.1.10", session).command({"Command": "Channel/GetAllConf"})

    def test_cancel_between_frames(self):
        session = MagicMock()
        event = threading.Event()
        event.set()
        with self.assertRaises(InterruptedError):
            Client("127.0.0.1", session).send_frames([Image.new("RGB", (128, 128))], 0, stop=event)
        session.post.assert_not_called()

    def test_aspect_and_alpha(self):
        image = Image.new("RGBA", (256, 128), (255, 0, 0, 0))
        for fit in ["contain", "cover", "stretch"]:
            output = resize(image, fit)
            self.assertEqual(output.size, (128, 128))
            self.assertEqual(output.getpixel((64, 64)), (255, 0, 0) if fit == "stretch" else (0, 0, 0))
        image = Image.new("RGB", (256, 128), "red")
        self.assertEqual(resize(image).getpixel((64, 0)), (0, 0, 0))
        self.assertEqual(resize(image, "cover").getpixel((64, 0)), (255, 0, 0))

    def test_gif_frame_skip(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "test.gif"
            images = [Image.new("RGB", (20, 20), c) for c in ["red", "green", "blue", "yellow"]]
            images[0].save(path, save_all=True, append_images=images[1:], duration=100)
            self.assertEqual(len(media_frames(path, frame_step=2)), 2)


class FakeClient:
    def __init__(self, ip):
        self.ip = ip
        self.commands = []
        self.uploads = []
        self.fail = False
        self.fail_panel = None

    def command(self, payload):
        self.commands.append(payload)
        if self.fail:
            raise requests.ConnectionError("offline")
        return {"error_code": 0, "Brightness": 70}

    def send_frames(self, frames, panel, quality, speed, stop):
        if self.fail or self.fail_panel == panel:
            raise requests.ConnectionError("offline")
        self.uploads.append((panel, frames[0].tobytes()))


class EngineTests(FixtureCase):
    def setUp(self):
        super().setUp()
        self.d["screens"][0] = slot("text", text="hello")
        self.d["enabled"] = True
        self.store.update_device(self.d)
        self.engine = Engine(self.store, client_factory=FakeClient)
        self.client = self.engine.client(self.d)

    def test_unchanged_widget_not_uploaded_until_recovery_interval(self):
        self.engine.send_panel(self.d, 0)
        self.engine.last_attempt.clear()
        self.engine.send_panel(self.d, 0)
        self.assertEqual(len(self.client.uploads), 1)
        self.engine.last_sent[(self.d["id"], 0)] -= 3601
        self.engine.last_attempt.clear()
        self.engine.send_panel(self.d, 0)
        self.assertEqual(len(self.client.uploads), 2)

    def test_failed_transfer_does_not_update_hash(self):
        self.client.fail = True
        self.engine.send_panel(self.d, 0)
        self.assertNotIn((self.d["id"], 0), self.engine.hashes)

    def test_manual_tools_pause_and_resume_persisted(self):
        self.engine.process("command", self.d["id"], {"payload": {"Command": "Tools/SetTimer", "Minute": 25, "Second": 0, "Status": 1}, "pause": True})
        self.engine.tick()
        self.assertEqual(self.client.uploads, [])
        restarted = Engine(self.store, client_factory=FakeClient)
        self.assertIn(self.d["id"], restarted.paused)
        self.engine.process("resume", self.d["id"], {})
        self.assertEqual(len(self.client.uploads), 1)
        self.assertFalse(self.store.get_device()["suspended"])

    def test_rejected_tool_does_not_pause(self):
        self.client.fail = True
        with self.assertRaises(requests.ConnectionError):
            self.engine.process("command", self.d["id"], {"payload": {"Command": "Tools/SetTimer"}, "pause": True})
        self.assertNotIn(self.d["id"], self.engine.paused)

    def test_power_off_blocks_upload_and_survives_restart(self):
        self.engine.process("command", self.d["id"], {"payload": {"Command": "Channel/OnOffScreen", "OnOff": 0}})
        self.engine.tick()
        self.engine.process("resume", self.d["id"], {})
        self.assertFalse(self.client.uploads)
        self.assertIn(self.d["id"], Engine(self.store).power_off)
        self.engine.process("command", self.d["id"], {"payload": {"Command": "Channel/OnOffScreen", "OnOff": 1}})
        self.engine.tick()
        self.assertEqual(len(self.client.uploads), 1)

    def test_notification_restores_without_auto(self):
        self.d["enabled"] = False
        self.store.update_device(self.d)
        self.engine.process("notification", self.d["id"], {"panel": 0, "text": "temporary", "seconds": 10})
        notice = self.client.uploads[0][1]
        self.engine.overrides[(self.d["id"], 0)] = 0
        self.engine.tick()
        self.assertEqual(len(self.client.uploads), 2)
        self.assertNotEqual(notice, self.client.uploads[1][1])

    def test_notification_refuses_unmanaged_screen(self):
        with self.assertRaises(ValueError):
            self.engine.process("notification", self.d["id"], {"panel": 1, "text": "temporary"})

    def test_reconnection_restores_only_same_device(self):
        self.engine.tick()
        self.engine.online[self.d["id"]] = False
        self.engine.health(self.d)
        self.engine.tick()
        self.assertEqual(len(self.client.uploads), 2)
        self.assertEqual(self.store.get_device()["ip"], self.d["ip"])
        self.assertEqual(len(self.engine.clients), 1)

    def test_schedules_run_once_and_persist(self):
        now = datetime.now()
        rule = {"id": uid(), "device_id": self.d["id"], "time": now.strftime("%H:%M"), "days": [now.weekday()], "action": "brightness", "value": 15, "enabled": True}
        self.store.change(lambda data: data["schedules"].append(rule))
        self.engine.tick()
        self.engine.tick()
        matches = [p for p in self.client.commands if p["Command"] == "Channel/SetBrightness"]
        self.assertEqual(len(matches), 1)
        restarted = Engine(self.store, client_factory=FakeClient)
        restarted.tick()
        self.assertFalse(any(p["Command"] == "Channel/SetBrightness" for p in restarted.client(self.d).commands))

    def test_scene_rotation_updates_profile(self):
        screens = [slot("text", text="rotated")] + [slot() for _ in range(4)]
        scene = {"id": uid(), "name": "rotate", "screens": screens}
        self.store.change(lambda data: data["scenes"].append(scene))
        self.d["rotation"] = [scene["id"]]
        self.d["rotation_seconds"] = 30
        self.store.update_device(self.d)
        self.engine.rotation_at[self.d["id"]] = time.monotonic() - 31
        self.engine.tick()
        self.assertEqual(self.store.get_device()["screens"][0]["text"], "rotated")
        self.assertEqual(len(self.client.uploads), 1)

    def test_disabled_device_never_auto_connects(self):
        self.d["enabled"] = False
        self.store.update_device(self.d)
        self.engine.tick()
        self.assertFalse(self.client.commands)
        self.assertFalse(self.client.uploads)

    def test_bad_screen_does_not_prevent_other_screens(self):
        self.d["screens"][1] = slot("text", text="second")
        self.client.fail_panel = 0
        with self.assertRaises(RuntimeError):
            self.engine.send(self.d)
        self.assertEqual([u[0] for u in self.client.uploads], [1])

    def test_invalidate_only_changed_panel(self):
        self.engine.hashes = {(self.d["id"], 0): "a", (self.d["id"], 1): "b"}
        self.engine.invalidate(self.d["id"], 0)
        self.assertEqual(self.engine.hashes, {(self.d["id"], 1): "b"})

    def test_native_pc_activation_before_metrics(self):
        self.d["screens"][0] = slot("pc_native", independence=123, native_pc_mode="activate")
        self.engine.renderer.providers.demo = True
        self.engine.send_panel(self.d, 0, True)
        self.assertEqual([p["Command"] for p in self.client.commands], ["Channel/SetClockSelectId", "Device/UpdatePCParaInfo"])
        self.assertEqual(self.client.commands[1]["ScreenList"][0]["LcdId"], 0)

    def test_native_pc_existing_clock_streams_without_cloud_ids(self):
        self.d["screens"][2] = slot("pc_native")
        self.engine.renderer.providers.demo = True
        self.engine.send_panel(self.d, 2, True)
        self.assertEqual([p["Command"] for p in self.client.commands], ["Device/UpdatePCParaInfo"])
        screen = self.client.commands[0]["ScreenList"][0]
        self.assertEqual(screen["LcdId"], 2)
        self.assertEqual(screen["DispData"], ["24%", "37%", "52 C", "46 C", "62%", "48%"])

    def test_native_pc_refresh_without_reactivation(self):
        self.d["screens"][0] = slot("pc_native", native_pc_mode="activate", independence=123, refresh=5)
        self.engine.renderer.providers.demo = True
        self.engine.send_panel(self.d, 0, True)
        activation = self.client.commands[0]
        self.assertEqual(activation["LcdIndependence"], 123)
        self.assertNotIn("DeviceId", activation)
        self.engine.last_attempt[(self.d["id"], 0)] -= 6
        self.engine.send_panel(self.d, 0)
        self.assertEqual([p["Command"] for p in self.client.commands], [
            "Channel/SetClockSelectId", "Device/UpdatePCParaInfo", "Device/UpdatePCParaInfo"])

    def test_native_pc_zero_group_does_not_touch_device(self):
        self.d["screens"][0] = slot("pc_native", native_pc_mode="activate")
        with self.assertRaises(ValueError):
            self.engine.send_panel(self.d, 0, True)
        self.assertEqual(self.client.commands, [])


class WidgetTests(unittest.TestCase):
    def test_font_covers_nordic_letters_and_wrapping_keeps_words(self):
        from PIL import Image, ImageDraw
        from keeper.widgets import font, wrap_text
        for bold in (False, True):
            f = font(14, bold)
            for ch in "æøåÆØÅ♪":   # Pillow's built-in fallback font draws these as empty boxes
                self.assertNotEqual(f.getmask(ch).getbbox(), f.getmask("\uffff").getbbox(), ch)
        draw = ImageDraw.Draw(Image.new("RGB", (128, 128)))
        lines = wrap_text(draw, "Kosovos parlament vælger præsident", font(14, True), 112)
        self.assertTrue(all(" " not in line or draw.textlength(line, font=font(14, True)) <= 112 for line in lines))
        self.assertEqual(" ".join(lines), "Kosovos parlament vælger præsident")
        self.assertEqual(wrap_text(draw, "x" * 80, font(14), 112)[0][:3], "xxx")   # a very long word is still split

    def test_all_renderers_with_demo_data(self):
        renderer = Renderer(demo=True)
        for kind in ["text", "clock", "pc", "weather", "calendar", "service", "countdown"]:
            with self.subTest(kind=kind):
                s = slot(kind, text="Hello!\n世界", target=(datetime.now()+timedelta(hours=1)).isoformat())
                image = renderer.render(s)
                self.assertEqual(image.size, (128, 128))
                self.assertEqual(image.mode, "RGB")

    def test_recurring_calendar_selects_next_instance(self):
        from icalendar import Calendar, Event
        now = datetime.now().astimezone()
        cal, event = Calendar(), Event()
        event.add("uid", "test-recurring")
        event.add("dtstart", now-timedelta(days=1)+timedelta(hours=1))
        event.add("duration", timedelta(minutes=30))
        event.add("rrule", {"freq": "daily", "count": 5})
        event.add("summary", "Daily meeting")
        cal.add_component(event)
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "calendar.ics"
            p.write_bytes(cal.to_ical())
            title, when = Providers().calendar(str(p))
            self.assertEqual(title, "Daily meeting")
            self.assertEqual(when, (now+timedelta(hours=1)).strftime("%H:%M"))

    def test_weather_cached_and_validated(self):
        providers = Providers()
        providers.session = MagicMock()
        providers.session.get.return_value.json.return_value = {"current": {"temperature_2m": 20}}
        providers.weather(40, -3)
        providers.weather(40, -3)
        self.assertEqual(providers.session.get.call_count, 1)
        with self.assertRaises(ValueError):
            providers.weather(100, 0)

    def test_service_failure_becomes_offline(self):
        providers = Providers()
        providers.session = MagicMock()
        providers.session.get.side_effect = requests.Timeout()
        self.assertEqual(providers.service("https://example.com"), (False, 0))


if __name__ == "__main__":
    unittest.main()
