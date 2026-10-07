import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import zipfile

from PIL import Image
from fastapi.testclient import TestClient
from unittest import mock

from keeper.config import slot
from keeper.mail import new_account
from keeper.portal import create_app, validate_command


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = create_app(self.root, token="unit-test-token-at-least-24-characters", demo=True)
        self.client = TestClient(self.app).__enter__()
        self.client.headers["Authorization"] = "Bearer unit-test-token-at-least-24-characters"

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def job(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        key = response.json()["job"]
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            value = self.client.get("/api/jobs/" + key).json()
            if value["status"] in {"done", "error", "cancelled"}:
                return value
            time.sleep(.02)
        self.fail("Job timed out")

    def upload(self, gif=False):
        b = io.BytesIO()
        image = Image.new("RGB", (640, 128), "red")
        image.save(b, "GIF" if gif else "PNG", **({"save_all": True, "append_images": [Image.new("RGB", (640, 128), "blue")], "duration": 400} if gif else {}))
        r = self.client.post("/api/upload?name=test." + ("gif" if gif else "png"), content=b.getvalue())
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_auth_origin_and_no_public_media(self):
        self.assertEqual(self.client.get("/api/state", headers={"Authorization": "wrong"}).status_code, 401)
        self.assertEqual(self.client.get("/api/state", headers={"Origin": "https://other.invalid"}).status_code, 403)
        self.assertEqual(self.client.get("/api/state", headers={"Origin": "http://testserver"}).status_code, 200)
        self.assertEqual(self.client.get("/api/media/config.json", headers={"Authorization": ""}).status_code, 401)

    def test_changing_a_screen_drops_its_stale_preview(self):
        engine = self.app.state.engine
        device_id = self.app.state.store.snapshot()['active_device']
        engine.emit('preview', device_id=device_id, panel=0, png=b'old-a')
        engine.emit('preview', device_id=device_id, panel=1, png=b'old-b')
        engine.invalidate(device_id, 0)
        self.assertNotIn((device_id, 0), engine.previews)
        self.assertEqual(engine.previews[(device_id, 1)], b'old-b')
        engine.invalidate(device_id)
        self.assertFalse(engine.previews)

    def test_upload_configuration_and_stale_editor_rejected(self):
        file = self.upload()
        state = self.client.get("/api/state").json()
        state["config"]["devices"][0]["screens"][0] = slot("media", path=file["path"])
        first = self.job(self.client.put("/api/config", json=state))
        self.assertEqual(first["status"], "done")
        second = self.job(self.client.put("/api/config", json=state))
        self.assertEqual(second["status"], "error")
        self.assertIn("changed", second["error"])
        media = self.client.get("/api/media/" + file["name"])
        self.assertEqual(media.headers["content-type"], "image/png")

    def test_removing_a_device_through_the_portal_clears_its_runtime_state(self):
        engine = self.app.state.engine
        state = self.client.get("/api/state").json()
        keep = state["config"]["devices"][0]
        extra = {**keep, "id": "extra-device-id", "name": "Extra"}
        state["config"]["devices"].append(extra)
        self.assertEqual(self.job(self.client.put("/api/config", json=state))["status"], "done")
        engine.online["extra-device-id"] = True
        engine.last_health["extra-device-id"] = 1.0
        engine.paused.add("extra-device-id")
        state = self.client.get("/api/state").json()
        state["config"]["devices"] = [d for d in state["config"]["devices"] if d["id"] != "extra-device-id"]
        self.assertEqual(self.job(self.client.put("/api/config", json=state))["status"], "done")
        self.assertNotIn("extra-device-id", engine.online)
        self.assertNotIn("extra-device-id", engine.last_health)
        self.assertNotIn("extra-device-id", engine.paused)
        self.assertIn(keep["id"], {d["id"] for d in self.client.get("/api/state").json()["config"]["devices"]})

    def test_config_cannot_read_unowned_paths(self):
        state = self.client.get("/api/state").json()
        state["config"]["devices"][0]["screens"][0] = slot("media", path=str(self.root / "config.json"))
        self.assertEqual(self.client.put("/api/config", json=state).status_code, 400)
        self.assertEqual(self.client.post("/api/upload?name=test.html", content=b"html").status_code, 400)

    def test_animation_conversion_and_apply_retains_five_parts(self):
        file = self.upload(True)
        result = self.job(self.client.post("/api/panorama", json={"path": file["path"], "duration": .8, "fps": 5}))
        self.assertEqual(result["status"], "done", result)
        self.assertEqual(result["result"]["count"], 4)
        self.assertEqual(len(result["result"]["screens"]), 5)
        state = self.client.get("/api/state").json()
        state["config"]["devices"][0]["screens"] = result["result"]["screens"]
        self.assertEqual(self.job(self.client.put("/api/config", json=state))["status"], "done")
        self.assertEqual(self.job(self.client.post("/api/action", json={"action": "send"}))["status"], "done")
        self.assertEqual(len(self.app.state.engine.hashes), 5)

    def test_portable_backup_and_restoration(self):
        file = self.upload()
        state = self.client.get("/api/state").json()
        state["config"]["devices"][0]["screens"][0] = slot("media", path=file["path"])
        self.job(self.client.put("/api/config", json=state))
        bundle = self.client.get("/api/export")
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as z:
            data = json.loads(z.read("config.json"))
            self.assertTrue(data["devices"][0]["screens"][0]["path"].startswith("media/"))
        result = self.job(self.client.post("/api/import", content=bundle.content))
        self.assertEqual(result["status"], "done", result)
        self.assertFalse(self.app.state.store.get_device()["enabled"])

    def test_failed_device_work_reports_job_error(self):
        result = self.job(self.client.post("/api/action", json={"action": "notification", "args": {"panel": 0, "text": "test", "seconds": 10}}))
        self.assertEqual(result["status"], "error")
        self.assertIn("restorable", result["error"])
        self.assertEqual(self.client.post("/api/action", json={"action": "command", "args": {"payload": {"Command": "Unknown"}}}).status_code, 400)

    def test_native_group_zero_and_invalid_parameters_blocked(self):
        with self.assertRaises(ValueError):
            validate_command({"Command": "Channel/SetClockSelectId", "ClockId": 625, "LcdIndex": 0, "LcdIndependence": 0})
        with self.assertRaises(ValueError):
            validate_command({"Command": "Channel/SetBrightness", "Brightness": 900})

    def test_visual_rgb_roundtrip_and_invalid_mode_rejected(self):
        from keeper.lighting import payload, defaults, from_payload
        before = self.app.state.store.get_device()['screens']
        command = payload({**defaults(), 'effect': 11, 'zone': 2, 'color': '#a799ff'})
        response = self.client.post('/api/action', json={'action': 'command', 'args': {'payload': command}})
        self.assertEqual(self.job(response)['status'], 'done')
        d = self.client.get('/api/state').json()['config']['devices'][0]
        self.assertEqual(d['lighting'], from_payload(command))
        self.assertEqual(d['screens'], before)
        command['LightList'] = [{'SelectEffect': 99}]
        self.assertEqual(self.client.post('/api/action', json={'action': 'command', 'args': {'payload': command}}).status_code, 400)

    def test_conversion_failure_does_not_touch_current_composition(self):
        before = self.app.state.store.snapshot()
        file = self.upload(True)
        result = self.job(self.client.post("/api/panorama", json={"path": file["path"], "start": 999, "duration": 1, "fps": 5}))
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.app.state.store.snapshot(), before)

    # --- refresh tokens belong to the server -------------------------------------------------------------------------
    def put(self, state):
        return self.job(self.client.put("/api/config", json=state))

    def with_tokens(self, spotify="S0", mail="M0"):
        def apply(data):
            data["integrations"]["spotify"].update(refresh_token=spotify, client_id="abcdef1234567890")
            data["integrations"]["mail"]["accounts"] = [new_account(id="ms1", provider="microsoft", client_id="cid", refresh_token=mail)]
        self.app.state.store.change(apply)

    def stored_tokens(self):
        data = self.app.state.store.snapshot()["integrations"]
        return data["spotify"]["refresh_token"], data["mail"]["accounts"][0]["refresh_token"]

    def test_rotation_between_load_and_save_does_not_conflict_or_clobber(self):
        self.with_tokens()
        state = self.client.get("/api/state").json()
        self.app.state.store.change(lambda d: (d["integrations"]["spotify"].update(refresh_token="S1"),
                                               d["integrations"]["mail"]["accounts"][0].update(refresh_token="M1")))
        self.assertEqual(self.client.get("/api/state").json()["revision"], state["revision"])
        state["config"]["integrations"]["prtg"]["enabled"] = False
        state["config"]["theme"] = "light"
        self.assertEqual(self.put(state)["status"], "done")
        self.assertEqual(self.stored_tokens(), ("S1", "M1"))
        self.assertEqual(self.app.state.store.snapshot()["theme"], "light")

    def test_disconnect_with_an_empty_token_clears_it(self):
        self.with_tokens()
        state = self.client.get("/api/state").json()
        state["config"]["integrations"]["spotify"]["refresh_token"] = ""
        state["config"]["integrations"]["mail"]["accounts"][0]["refresh_token"] = ""
        self.assertEqual(self.put(state)["status"], "done")
        self.assertEqual(self.stored_tokens(), ("", ""))

    def test_a_forged_token_is_ignored_for_known_and_new_accounts(self):
        self.with_tokens()
        state = self.client.get("/api/state").json()
        accounts = state["config"]["integrations"]["mail"]["accounts"]
        state["config"]["integrations"]["spotify"]["refresh_token"] = "FORGED"
        accounts[0]["refresh_token"] = "FORGED"
        accounts.append(new_account(id="new1", provider="microsoft", client_id="cid2", refresh_token="FORGED"))
        self.assertEqual(self.put(state)["status"], "done")
        saved = self.app.state.store.snapshot()["integrations"]
        self.assertEqual(self.stored_tokens(), ("S0", "M0"))
        self.assertEqual([a["refresh_token"] for a in saved["mail"]["accounts"]], ["M0", ""])

    def test_other_edits_still_conflict_check(self):
        self.with_tokens()
        state = self.client.get("/api/state").json()
        self.app.state.store.change(lambda d: d.update(theme="light"))
        state["config"]["integrations"]["prtg"]["enabled"] = False
        result = self.put(state)
        self.assertEqual(result["status"], "error")
        self.assertIn("Reload before saving", result["error"])
        self.assertEqual(self.stored_tokens(), ("S0", "M0"))

    def test_revision_ignores_only_refresh_tokens(self):
        from keeper.portal import revision
        self.with_tokens()
        before = revision(self.app.state.store.snapshot())
        self.app.state.store.change(lambda d: d["integrations"]["spotify"].update(refresh_token="OTHER"))
        self.assertEqual(revision(self.app.state.store.snapshot()), before)
        self.app.state.store.change(lambda d: d["integrations"]["spotify"].update(client_id="zzzzzzzzzzzz"))
        self.assertNotEqual(revision(self.app.state.store.snapshot()), before)

    def test_legacy_spotify_routes_are_gone(self):
        # 405 when the built web UI is mounted at "/", 404 when web/dist does not exist (CI runs tests before building it)
        self.assertIn(self.client.post("/api/spotify/connect", json={}).status_code, (404, 405))
        self.assertEqual(self.client.get("/api/spotify/callback?code=c&state=x", headers={"Authorization": ""}).status_code, 401)

    # --- migration of the original app's profiles --------------------------------------------------------------------
    def test_state_reports_the_migration_note_once(self):
        self.assertEqual(self.client.get("/api/state").json()["notice"], "")
        self.app.state.store.migration_note = "Profiles imported."
        self.assertEqual(self.client.get("/api/state").json()["notice"], "Profiles imported.")
        self.assertEqual(self.client.get("/api/state").json()["notice"], "")

    def test_create_app_imports_a_legacy_profile_only_when_asked(self):
        with tempfile.TemporaryDirectory() as appdata:
            legacy = Path(appdata) / "DivoomKeeper"
            legacy.mkdir()
            (legacy / "config.json").write_text(json.dumps({"device_ip": "192.168.1.50", "ui_lang": "es", "screens": []}))
            for migrate, expected in ((False, ""), (True, "192.168.1.50")):
                with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {"APPDATA": appdata}):
                    app = create_app(Path(temp), token="unit-test-token-at-least-24-characters", demo=True, migrate=migrate)
                    with TestClient(app) as client:
                        state = client.get("/api/state", headers={"Authorization": "Bearer unit-test-token-at-least-24-characters"}).json()
                    self.assertEqual(state["config"]["devices"][0]["ip"], expected)
                    self.assertEqual(bool(state["notice"]), migrate)
                    self.assertEqual(state["config"]["language"], "es" if migrate else "en")


class StateRuntimeTests(unittest.TestCase):
    TOKEN = "unit-test-token-at-least-24-characters"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name), token=self.TOKEN, demo=True)
        self.client = TestClient(self.app).__enter__()
        self.client.headers["Authorization"] = "Bearer " + self.TOKEN

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def set_hardware(self, enabled):
        self.app.state.store.change(lambda d: d["integrations"].update(hardware=enabled))

    def probe(self, readings):
        return mock.patch.object(self.app.state.engine.renderer.providers.extra, "hardware", return_value=readings)

    def test_runtime_has_the_notification_status_and_revision_ignores_it(self):
        first = self.client.get("/api/state").json()
        self.assertEqual(first["runtime"]["notifications"], "Disabled")
        self.assertIn("online", first["runtime"])
        self.app.state.engine.bridge.notifications.status = "Running"
        second = self.client.get("/api/state").json()
        self.assertEqual(second["runtime"]["notifications"], "Running")
        self.assertEqual(first["revision"], second["revision"])
        self.assertNotIn("hardware_sensors", second["config"])

    def test_hardware_sensors_are_listed_only_when_enabled(self):
        readings = [{"Identifier": "/coretemp/temperature/0", "Name": "Package id 0", "SensorType": "Temperature", "Value": 54.26}]
        with self.probe(readings):
            self.set_hardware(False)
            self.assertEqual(self.client.get("/api/state").json()["hardware_sensors"], [])
            self.set_hardware(True)
            state = self.client.get("/api/state").json()
        self.assertEqual(state["hardware_sensors"], [{"id": "/coretemp/temperature/0", "name": "Package id 0",
                                                     "type": "Temperature", "value": 54.3}])

    def test_hardware_sensors_are_capped_cut_and_sanitised(self):
        readings = [{"Identifier": f"/s/{i}", "Name": "n" * 200, "SensorType": "Fan", "Value": float(i)} for i in range(400)]
        readings += [None, {"Name": "no id"}, {"Identifier": "/nan", "Name": "x", "SensorType": "Load", "Value": float("nan")}]
        with self.probe(readings):
            self.set_hardware(True)
            sensors = self.client.get("/api/state").json()["hardware_sensors"]
        self.assertEqual(len(sensors), 300)
        self.assertEqual(len(sensors[0]["name"]), 80)
        with self.probe([readings[-1]]):
            self.assertIsNone(self.client.get("/api/state").json()["hardware_sensors"][0]["value"])

    def test_a_failing_or_empty_probe_gives_an_empty_list(self):
        self.set_hardware(True)
        with mock.patch.object(self.app.state.engine.renderer.providers.extra, "hardware", side_effect=RuntimeError("x")):
            self.assertEqual(self.client.get("/api/state").json()["hardware_sensors"], [])
        with self.probe([]):
            self.assertEqual(self.client.get("/api/state").json()["hardware_sensors"], [])
