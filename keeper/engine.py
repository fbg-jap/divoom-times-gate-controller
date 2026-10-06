from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import json
import logging
import os
import queue
import threading
import time

from .config import slot
from .content import PlaylistCursor, composition, empty_playlists
from .protocol import Client, discover, media_frames
from .timesync import timesource
from .widgets import Renderer, png_bytes


class Engine(threading.Thread):
    """Single owner of all device I/O; UI communicates through queues only."""
    def __init__(self, store, demo=False, client_factory=Client):
        super().__init__(daemon=True, name="divoom-io")
        self.store = store
        self.demo = demo
        self.client_factory = client_factory
        self.jobs = queue.Queue(maxsize=100)
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.renderer = Renderer(demo)
        self.session_probe = None
        if os.name != "nt" and not demo and os.getenv("XDG_SESSION_ID"):
            from .windows_sources import AsyncProbe
            from .platform_support import linux_locked
            self.session_probe = AsyncProbe(linux_locked, 5)
        from .automation import Automations
        from .integrations import Bridge
        self.automations = Automations(self)
        self.bridge = Bridge(self)
        self.clock_sent = None
        self.hashes = {}
        self.last_sent = {}
        self.last_attempt = {}
        self.clients = {}
        self.last_health = {}
        self.online = {}
        self.lighting_restored = set()
        self.paused = {d["id"] for d in store.snapshot()["devices"] if d.get("suspended")}
        self.power_off = {d["id"] for d in store.snapshot()["devices"] if d.get("screens_off")}
        self.overrides = {}
        self.rotation_at = {}
        self.rotation_index = {}
        self.playlist_cursors = {}
        self.rules_attempted = set()
        self.pending = set()
        self.pending_lock = threading.Lock()
        self.suppress_initial = not store.snapshot().get("resend_on_startup", True)
        if self.suppress_initial:
            for d in store.snapshot()["devices"]:
                for i in range(5):
                    self.last_sent[(d["id"], i)] = time.monotonic()

    def emit(self, event, **kwargs):
        self.events.put({"event": event, **kwargs})

    def log(self, message, level="info"):
        getattr(logging, level)(message)
        self.emit("log", message=message, level=level)

    def submit(self, action, device_id=None, **kwargs):
        key = (action, device_id, kwargs.get("panel"))
        with self.pending_lock:
            if key in self.pending and action in {"send", "preview", "health", "discover"}:
                return
            try:
                self.jobs.put_nowait((key, action, device_id, kwargs))
                self.pending.add(key)
                return True
            except queue.Full:
                self.emit("log", message="Task queue full. Wait for the send to finish.", level="warning")
                return False

    def client(self, device):
        options = {k: device[k] for k in ("port", "local_token") if device.get(k)}
        key = (device["id"], device["ip"], tuple(sorted(options.items())))
        if key not in self.clients:
            if "local_token" in options:
                options["token"] = options.pop("local_token")
            self.clients[key] = self.client_factory(device["ip"], **options)
        return self.clients[key]

    def command(self, d, payload):
        if self.demo:
            return {"error_code": 0, "Brightness": 65, "LightSwitch": 1, "demo": True}
        return self.client(d).command(payload)

    def invalidate(self, device_id, panel=None):
        for mapping in [self.hashes, self.last_sent, self.last_attempt, self.playlist_cursors]:
            for key in list(mapping):
                if key[0] == device_id and (panel is None or key[1] == panel):
                    mapping.pop(key, None)

    def forget_device(self, device_id):
        """Drop every runtime entry of a removed device. Runs on the engine thread."""
        self.invalidate(device_id)
        for mapping in [self.overrides, self.rotation_at, self.rotation_index, self.clients, self.last_health, self.online,
                        self.automations.profile_ids]:
            for key in list(mapping):
                if key == device_id or (isinstance(key, tuple) and key[0] == device_id):
                    mapping.pop(key, None)
        for group in (self.paused, self.power_off):
            group.discard(device_id)
        for key in list(self.lighting_restored):
            if key[0] == device_id:
                self.lighting_restored.discard(key)
        self.automations.notice_queue[:] = [item for item in self.automations.notice_queue if item[1] != device_id]

    def playlist_content(self, d, panel, advance=False):
        playlist = d.get("playlists", empty_playlists())[panel]
        items = playlist.get("items", [])
        if not playlist.get("enabled") or not items:
            self.playlist_cursors.pop((d["id"], panel), None)
            return d["screens"][panel], None, 0, False
        key = (d["id"], panel)
        fresh = PlaylistCursor.for_list(playlist)
        cursor = self.playlist_cursors.get(key)
        if cursor is None or cursor.fingerprint != fresh.fingerprint:
            cursor = fresh
            self.playlist_cursors[key] = cursor
        index, switched = cursor.candidate(items, time.monotonic(), advance)
        return items[index]["screen"], cursor, index, switched

    def preview(self, d, panel):
        s, _, _, _ = self.playlist_content(d, panel)
        if s["kind"] == "media" and s.get("path"):
            # Only decode one frame for the preview, irrespective of animation size.
            from PIL import Image
            from .protocol import resize
            with Image.open(s["path"]) as source:
                image = resize(source.copy(), s.get("fit", "contain"))
        else:
            image = self.renderer.render(s)
        self.emit("preview", device_id=d["id"], panel=panel, png=png_bytes(image))

    def send_panel(self, d, panel, force=False, replacement=None):
        key = (d["id"], panel)
        s, cursor, playlist_index, switched = self.playlist_content(d, panel, advance=replacement is None)
        if replacement is not None:
            s, cursor, switched = replacement, None, False
        kind = s["kind"]
        if kind in {"empty", "native"}:
            return
        now = time.monotonic()
        interval = max(1, int(d.get("interval_minutes", 60))) * 60
        if not force:
            refresh = 5 if switched else interval if kind == "media" else max(5, int(s.get("refresh", 30)))
            if now - self.last_attempt.get(key, -1e12) < refresh:
                return
            if self.suppress_initial and key not in self.hashes and now - self.last_sent.get(key, -1e12) < interval:
                return
        self.last_attempt[key] = now
        try:
            if kind == "pc_native":
                # Streaming to an already selected native clock needs no cloud
                # IDs. Activation, however, requires the actual native group.
                activate = s.get("native_pc_mode", "activate") == "activate"
                if activate and (force or key not in self.hashes):
                    if int(s.get("independence", 0)) <= 0:
                        raise ValueError("Select PC Monitor in the Divoom app and use 'Send data to the already chosen monitor'. "
                                         "Direct activation needs a valid native group; 0 alters other screens.")
                    payload = {"Command": "Channel/SetClockSelectId", "ClockId": 625,
                               "LcdIndependence": int(s.get("independence", 0)), "LcdIndex": panel}
                    if int(d.get("device_id", 0)):
                        payload["DeviceId"] = int(d["device_id"])
                    self.command(d, payload)
                    if self.stop_event.wait(.3):
                        raise InterruptedError("Send cancelled")
                values = self.renderer.providers.pc()
                def fmt(name, suffix):
                    value = values.get(name)
                    return "N/A" if value is None else f"{value:.0f}{suffix}"
                self.command(d, {"Command": "Device/UpdatePCParaInfo", "ScreenList": [{
                    "LcdId": panel, "DispData": [fmt("cpu", "%"), fmt("gpu", "%"), fmt("cpu_temp", " C"),
                                                  fmt("gpu_temp", " C"), fmt("ram", "%"), fmt("disk", "%")]}]})
                self.hashes[key] = "native-pc"
                self.last_sent[key] = time.monotonic()
                self.emit("status", device_id=d["id"], text="PC data sent · clock 625 required")
                self.log(f"{d['name']} · screen {panel + 1} · native PC: CPU {fmt('cpu', '%')}, "
                         f"RAM {fmt('ram', '%')}, GPU {fmt('gpu', '%')} · datos aceptados")
                return
            if kind == "media":
                if s.get("panorama_speed"):
                    from .panorama_media import animation_frames
                    frames = animation_frames(s["path"], s["panorama_speed"])
                else:
                    frames = media_frames(s["path"], s.get("fit", "contain"), s.get("frame_step", 1))
            else:
                frames = [self.renderer.render(s)]
            signature = hashlib.sha256()
            signature.update(json.dumps(s, sort_keys=True).encode())
            signature.update(str((d.get("quality"), d.get("speed"))).encode())
            for frame in frames:
                signature.update(frame.tobytes())
            digest = signature.hexdigest()
            if not force and not switched and self.hashes.get(key) == digest and now - self.last_sent.get(key, 0) < interval:
                return
            self.emit("status", device_id=d["id"], text=f"Sending screen {panel + 1}…")
            if not self.demo:
                self.client(d).send_frames(frames, panel, d.get("quality", 85), s.get("panorama_speed") or d.get("speed", 100), self.stop_event)
            self.hashes[key] = digest
            self.last_sent[key] = time.monotonic()
            if cursor is not None:
                cursor.index = playlist_index
                if switched:
                    cursor.started = self.last_sent[key]
                self.emit("playing", device_id=d["id"], panel=panel, index=playlist_index,
                          count=len(d["playlists"][panel]["items"]))
            self.emit("preview", device_id=d["id"], panel=panel, png=png_bytes(frames[0]))
            self.emit("status", device_id=d["id"], text="Send accepted · " + datetime.now().strftime("%H:%M:%S"))
            self.log(f"{d['name']} · screen {panel + 1} · {kind} sent")
        except Exception as error:
            self.log(f"{d['name']} · screen {panel + 1}: {type(error).__name__}: {error}", "error")
            self.emit("status", device_id=d["id"], text="Send error · see Activity")
            if force:
                raise

    def send(self, d, panel=None, force=True):
        failures = []
        for i in range(5) if panel is None else [panel]:
            if self.stop_event.is_set():
                break
            if (d["id"], i) not in self.overrides:
                try:
                    self.send_panel(d, i, force)
                except Exception as error:
                    failures.append(f"{i+1}: {error}")
        if failures:
            raise RuntimeError("Screens with errors: " + "; ".join(failures))

    def set_state(self, device_id, **values):
        self.store.change(lambda data: next(d for d in data["devices"] if d["id"] == device_id).update(values))

    def apply_scene(self, d, scene_id):
        scene = next(s for s in self.store.snapshot()["scenes"] if s["id"] == scene_id)
        d.update(composition(scene))
        self.store.update_fields(d["id"], **composition(scene))
        self.paused.discard(d["id"])
        self.set_state(d["id"], suspended=False)
        self.invalidate(d["id"])
        self.emit("config")
        if d["id"] not in self.power_off:
            self.send(d)

    def process(self, action, device_id, args):
        if action == "reset_runtime":
            self.lighting_restored.clear()
            self.hashes.clear()
            self.last_sent.clear()
            self.last_attempt.clear()
            self.overrides.clear()
            self.rotation_at.clear()
            self.rotation_index.clear()
            self.playlist_cursors.clear()
            self.automations.states.clear()
            self.automations.profile_ids.clear()
            self.automations.notice_queue.clear()
            self.automations.pomodoro.command("reset")
            data = self.store.snapshot()
            self.paused = {d["id"] for d in data["devices"] if d.get("suspended")}
            self.power_off = {d["id"] for d in data["devices"] if d.get("screens_off")}
            return
        if action == "forget_device":
            self.forget_device(device_id)
            return
        if action == "session_lock":
            self.automations.locked = bool(args["locked"])
            return
        if action == "pomodoro":
            self.automations.pomodoro.command(args.pop("operation"), device_id=device_id, **args)
            self.renderer.providers.extra.pomodoro = self.automations.pomodoro.snapshot()
            return
        if action == "discover":
            found = [{"name": "Times Gate · Demo", "ip": "192.168.1.116"}] if self.demo else discover(**args)
            self.emit("discovery", devices=found)
            return
        d = self.store.get_device(device_id)
        if action in {"send", "preview", "notification"}:
            d = self.automations.effective(d, self.store.snapshot(), time.monotonic())
        if action == "preview":
            self.preview(d, args["panel"])
        elif action == "send":
            self.paused.discard(d["id"])
            self.set_state(d["id"], suspended=False)
            if d["id"] in self.power_off:
                self.log("Screens are off. Turn them on before sending.", "warning")
                return
            self.send(d, args.get("panel"))
        elif action == "command":
            payload = args["payload"]
            if payload.get('Command') == 'Channel/SetRGBInfo':
                from .lighting import from_payload, payload as lighting_payload
                lighting = from_payload(payload)
                payload = lighting_payload(lighting)
            result = self.command(d, payload)
            if payload.get('Command') == 'Channel/SetRGBInfo':
                self.set_state(d['id'], lighting=lighting, lighting_restore=True)
                self.lighting_restored.add((d['id'], d['ip']))
            if args.get("pause"):
                self.overrides = {key: value for key, value in self.overrides.items() if key[0] != d["id"]}
                self.paused.add(d["id"])
                self.set_state(d["id"], suspended=True)
                self.emit("status", device_id=d["id"], text="Native tool · resending paused")
            if payload["Command"] == "Channel/OnOffScreen":
                self.set_state(d["id"], screens_off=payload["OnOff"] == 0)
                if payload["OnOff"] == 0:
                    self.power_off.add(d["id"])
                else:
                    self.power_off.discard(d["id"])
                    self.invalidate(d["id"])
            if payload["Command"] == "Device/SysReboot":
                self.invalidate(d["id"])
                self.last_health[d["id"]] = time.monotonic()
                self.online[d["id"]] = False
            self.emit("response", command=payload["Command"], body=result)
            self.log(f"{d['name']} · {payload['Command']} · aceptado")
        elif action == "resume":
            self.paused.discard(d["id"])
            self.set_state(d["id"], suspended=False)
            self.invalidate(d["id"])
            if d["id"] not in self.power_off:
                self.send(d)
        elif action == "health":
            self.health(d)
        elif action == "scene":
            self.apply_scene(d, args["scene_id"])
        elif action == "notification":
            if d["id"] in self.power_off:
                raise ValueError("Turn the screens on before sending a notice")
            panel = args["panel"]
            current, _, _, _ = self.playlist_content(d, panel)
            if current["kind"] in {"empty", "native", "pc_native"}:
                raise ValueError("The notice needs a screen with restorable content (image or widget)")
            self.send_panel(d, panel, True, slot("text", title=args.get("title", "NOTICE"), text=args["text"],
                                                **({"color": args["color"]} if args.get("color") else {})))
            self.overrides[(d["id"], panel)] = time.monotonic() + args.get("seconds", 15)
            if args.get("buzzer"):
                self.command(d, {"Command": "Device/PlayBuzzer", "ActiveTimeInCycle": 150,
                                 "OffTimeInCycle": 150, "PlayTotalTime": 600})
        elif action == "catalog":
            import requests
            if self.demo:
                body = {"demo": True, "LcdIndependence": 1234}
            else:
                response = requests.get("https://app.divoom-gz.com/Channel/Get5LcdInfoV2",
                                        params={"DeviceType": "LCD", "DeviceId": int(d.get("device_id", 0))}, timeout=10)
                response.raise_for_status()
                body = response.json()
            self.emit("response", command="Get5LcdInfoV2", body=body)
        elif action == "invalidate":
            self.invalidate(d["id"], args.get("panel"))

    def health(self, d):
        self.last_health[d["id"]] = time.monotonic()
        try:
            body = self.command(d, {"Command": "Channel/GetAllConf"})
            if self.online.get(d["id"]) is False:
                self.lighting_restored.discard((d['id'], d['ip']))
                self.invalidate(d["id"])
                self.log(f"{d['name']} · connection recovered; its content will be restored")
            self.online[d["id"]] = True
            self.emit("health", device_id=d["id"], online=True, body=body)
        except Exception as error:
            self.online[d["id"]] = False
            self.lighting_restored.discard((d['id'], d['ip']))
            self.emit("health", device_id=d["id"], online=False, body={"error": str(error)})
            return
        key = (d['id'], d['ip'])
        if d.get('lighting') and d.get('lighting_restore', True) and key not in self.lighting_restored:
            from .lighting import payload
            try:
                self.command(d, payload(d['lighting']))
                self.lighting_restored.add(key)
                self.log(f"{d['name']} · lighting recovered")
            except Exception as error:
                # An RGB failure must not suspend image/GIF uploads.
                self.log(f"{d['name']} · could not recover lighting: {error}", 'warning')

    def sync_device_clock(self, data, now):
        """integrations.timesync.sync_device: push the corrected UTC to each enabled device after a good sync, then at most every 6 h."""
        if not (timesource.sync_device and timesource.synced()):
            self.clock_sent = None
            return
        if self.clock_sent is not None and now - self.clock_sent < 6 * 3600:
            return
        self.clock_sent = now
        for d in data["devices"]:
            if d.get("enabled") and d["id"] not in self.paused:
                try:
                    self.submit("command", d["id"], payload={"Command": "Device/SetUTC", "Utc": int(timesource.time())})
                except Exception as error:
                    self.log(f"{d['name']} · device clock sync failed: {error}", "warning")

    def tick(self):
        data = self.store.snapshot()
        now = time.monotonic()
        wall = timesource.now()
        self.bridge.tick(data, now)
        self.sync_device_clock(data, now)
        if self.session_probe and any(r.get("trigger") == "locked" for r in data.get("profiles", [])):
            locked, _ = self.session_probe.read()
            if locked is not None:
                self.automations.locked = bool(locked)
        self.automations.update(data, now)
        for d in data["devices"]:
            device_id = d["id"]
            if d.get("enabled") and device_id not in self.paused and device_id not in self.power_off:
                d = self.automations.effective(d, data, now)
            # Temporary notices restore even when regular automatic sending is off.
            for key, expiry in list(self.overrides.items()):
                if key[0] == device_id and now >= expiry:
                    self.overrides.pop(key)
                    cursor = self.playlist_cursors.get(key)
                    if cursor is not None:
                        cursor.started = now
                    if device_id not in self.power_off:
                        try:
                            self.send_panel(d, key[1], True)
                        except Exception:
                            self.overrides[key] = time.monotonic() + 5
            if not d.get("ip"):
                continue
            if (d.get('enabled') or (d.get('lighting') and d.get('lighting_restore', True))) and now - self.last_health.get(device_id, -1e12) > 30:
                self.health(d)
            if not d.get('enabled'):
                continue
            if self.online.get(device_id) is False:
                continue
            for rule in data["schedules"]:
                stamp = wall.strftime("%Y-%m-%d") + " " + rule["time"]
                attempt = (rule["id"], stamp)
                if (rule.get("enabled", True) and rule["device_id"] == device_id
                        and wall.weekday() in rule["days"] and wall.strftime("%H:%M") == rule["time"]
                        and rule.get("last_run") != stamp and attempt not in self.rules_attempted):
                    self.rules_attempted.add(attempt)
                    action = rule["action"]
                    if action == "scene":
                        self.apply_scene(d, rule["value"])
                    else:
                        payload = {"Command": "Channel/SetBrightness", "Brightness": int(rule["value"])} if action == "brightness" else {
                            "Command": "Channel/OnOffScreen", "OnOff": int(action == "on")}
                        self.process("command", device_id, {"payload": payload})
                    self.store.change(lambda config, rid=rule["id"], mark=stamp: next(
                        r for r in config["schedules"] if r["id"] == rid).update(last_run=mark))
                    self.log(f"Horario ejecutado · {rule.get('name', rule['time'])}")
            if device_id in self.paused or device_id in self.power_off:
                continue
            self.automations.deliver(d, now)
            rotation = [x for x in d.get("rotation", []) if any(s["id"] == x for s in data["scenes"])]
            self.rotation_at.setdefault(device_id, now)
            if rotation and not self.automations.profile_ids.get(device_id) and now - self.rotation_at[device_id] >= max(30, d.get("rotation_seconds", 300)):
                index = self.rotation_index.get(device_id, 0) % len(rotation)
                self.rotation_at[device_id] = now
                self.rotation_index[device_id] = index + 1
                self.apply_scene(d, rotation[index])
            self.send(d, force=False)

    def run(self):
        self.log("Engine ready" + (" · DEMO: no device connection" if self.demo else ""))
        tick_at = 0.
        while not self.stop_event.is_set():
            if time.monotonic() >= tick_at:
                try:
                    self.tick()
                except Exception as error:
                    self.log(f"Programador: {error}", "error")
                tick_at = time.monotonic() + 1
            try:
                key, action, device_id, args = self.jobs.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self.process(action, device_id, args)
            except Exception as error:
                self.log(f"{action}: {error}", "error")
                self.emit("failure", action=action, message=str(error))
            finally:
                with self.pending_lock:
                    self.pending.discard(key)
                self.jobs.task_done()

        self.bridge.close()
        timesource.stop()

    def stop(self):
        self.stop_event.set()
