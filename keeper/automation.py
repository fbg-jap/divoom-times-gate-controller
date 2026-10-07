"""Automation state is ephemeral; automatic profiles never overwrite saved screens."""
from __future__ import annotations

import copy
import json
import time

import psutil

from .content import composition
from .extensions import finite



class Pomodoro:
    def __init__(self):
        self.phase, self.remaining, self.total = "Ready", 1500., 1500.
        self.running, self.cycle, self.stamp = False, 0, time.monotonic()
        self.settings = {"work": 25, "rest": 5, "long_rest": 15, "cycles": 4}
        self.device_id, self.panel, self.buzzer = None, 0, False

    def snapshot(self):
        return {k: getattr(self, k) for k in ("phase", "remaining", "total", "running", "cycle")}

    def command(self, operation, **args):
        if operation == "start":
            settings = {key: int(args.get(key, value)) for key, value in self.settings.items()}
            if any(not 1 <= value <= (12 if key == "cycles" else 180) for key, value in settings.items()):
                raise ValueError("Invalid Pomodoro duration")
            self.settings = settings
            self.device_id, self.panel = args["device_id"], int(args.get("panel", 0))
            self.buzzer = bool(args.get("buzzer"))
            self.phase, self.cycle, self.running = "Work", 1, True
            self.total = self.remaining = settings["work"] * 60
        elif operation == "pause":
            self.advance(time.monotonic())
            self.running = False
        elif operation == "resume":
            self.running = self.phase != "Ready"
        elif operation == "reset":
            self.running, self.phase, self.cycle = False, "Ready", 0
            self.total = self.remaining = self.settings["work"] * 60
        elif operation == "skip":
            self._next()
        else:
            raise ValueError("Unknown Pomodoro control")
        self.stamp = time.monotonic()

    def _next(self):
        if self.phase == "Work":
            long = self.cycle % self.settings["cycles"] == 0
            self.phase = "Long break" if long else "Break"
            minutes = self.settings["long_rest" if long else "rest"]
        else:
            self.phase, self.cycle = "Work", self.cycle + 1
            minutes = self.settings["work"]
        self.total = self.remaining = minutes * 60

    def advance(self, now):
        if self.running:
            self.remaining = max(0, self.remaining - max(0, now - self.stamp))
        self.stamp = now
        if self.running and self.remaining <= 0:
            self._next()
            return self.phase
        return None


class Automations:
    def __init__(self, engine):
        self.engine = engine
        self.states, self.profile_ids, self.notice_queue = {}, {}, []
        self.last_check, self.process_stamp = -1e12, -1e12
        self.processes, self.locked = set(), False
        self.pomodoro = Pomodoro()

    def effective(self, d, config, now):
        rules = [r for r in config.get("profiles", []) if d.get("enabled") and r.get("enabled", True) and r["device_id"] == d["id"]]
        if any(r["trigger"] == "process" for r in rules) and now - self.process_stamp >= 5:
            self.process_stamp = now
            self.processes = set()
            for process in psutil.process_iter(["name"]):
                try:
                    self.processes.add((process.info["name"] or "").casefold())
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        def matches(r):
            return (r["trigger"] == "locked" and self.locked or
                    r["trigger"] == "process" and not self.locked and r.get("process", "").casefold() in self.processes or
                    r["trigger"] == "desktop" and not self.locked)
        priority = {"locked": 0, "process": 1, "desktop": 2}
        match = next((r for r in sorted(rules, key=lambda r: priority[r["trigger"]]) if matches(r)), None)
        scene = next((s for s in config["scenes"] if match and s["id"] == match["scene_id"]), None)
        signature = json.dumps(composition(scene), sort_keys=True) if scene else None
        if self.profile_ids.get(d["id"]) != signature:
            self.profile_ids[d["id"]] = signature
            self.engine.invalidate(d["id"])
            self.engine.log("Automatic profile · " + (scene["name"] if scene else "usual layout"))
        if scene:
            return {**d, **composition(scene)}
        return d

    def enqueue(self, device_id, panel, text, title, seconds=15, buzzer=False, color=None, border=False, blink=False):
        if len(self.notice_queue) < 20:
            args = {"panel": panel, "text": text, "title": title, "seconds": seconds, "buzzer": buzzer}
            if color:
                args["color"] = color
                if border:
                    args["border"] = True
                if blink:
                    args["blink"] = True
            self.notice_queue.append((time.monotonic() + 120, device_id, args))

    def update(self, config, now):
        phase = self.pomodoro.advance(now)
        self.engine.renderer.providers.extra.pomodoro = self.pomodoro.snapshot()
        self.engine.emit("pomodoro", **self.pomodoro.snapshot())
        if phase and self.pomodoro.device_id:
            self.enqueue(self.pomodoro.device_id, self.pomodoro.panel, phase, "POMODORO", buzzer=self.pomodoro.buzzer)
        if now - self.last_check < 5:
            return
        self.last_check = now
        active = {d["id"] for d in config["devices"] if d.get("enabled") and d["id"] not in self.engine.paused
                  and d["id"] not in self.engine.power_off and self.engine.online.get(d["id"]) is not False}
        enabled_keys = set()
        for group in ("alerts", "reminders"):
            for r in config.get(group, []):
                if not r.get("enabled", True) or r["device_id"] not in active:
                    continue
                key = (group, r["id"], json.dumps(r, sort_keys=True))
                enabled_keys.add(key)
                state = self.states.setdefault(key, {"since": None, "fired": False, "last": -1e12, "next": now + r.get("minutes", 30) * 60})
                if group == "reminders":
                    fire = now >= state["next"]
                    if fire:
                        state["next"] = now + r["minutes"] * 60
                else:
                    try:
                        value = self.value(r)
                    except Exception:
                        value = None
                    threshold = float(r.get("threshold", 80))
                    condition = value is not None and (value > threshold if r.get("operator", "above") == "above" else value < threshold)
                    if not condition:
                        state["since"], state["fired"] = None, False
                        continue
                    if state["since"] is None:
                        state["since"] = now
                    fire = not state["fired"] and now - state["since"] >= r.get("hold", 10) and now - state["last"] >= r.get("cooldown", 300)
                    if fire:
                        state["fired"], state["last"] = True, now
                if fire:
                    self.enqueue(r["device_id"], r["panel"], r["text"], r.get("name") or "NOTICE", r.get("seconds", 15), r.get("buzzer", False))
        self.states = {k: v for k, v in self.states.items() if k in enabled_keys}

    def value(self, r):
        provider = self.engine.renderer.providers
        if r["metric"] == "service":
            return 0 if provider.service(r["source"])[0] else 1
        if r["metric"] == "disk_free":
            value = provider.disk(r.get("source", ""))["free"]
            return None if value is None else value / 1024**3
        if r["metric"] == "sensor":
            return finite(provider.extra.sensor(r.get("sensor_source", "mqtt"), r.get("source", ""), r.get("sensor_field", "")))
        if r["metric"] in {"prtg_down", "prtg_warning"}:
            data = provider.extra.prtg()
            return None if data is None else data[r["metric"][5:]]
        if r["metric"] == "mail_unread":
            data, _ = provider.extra.mail_state(r.get("source") or "all")  # the rule's source is the mail account id
            return None if data is None else data["unread"]
        return finite(provider.pc().get(r["metric"]))

    def deliver(self, d, now):
        for item in list(self.notice_queue):
            expiry, device_id, args = item
            if now > expiry:
                self.notice_queue.remove(item)
                continue
            if device_id != d["id"] or (device_id, args["panel"]) in self.engine.overrides:
                continue
            self.notice_queue.remove(item)
            try:
                self.engine.process("notification", device_id, args)
            except Exception as error:
                self.engine.log(f"Notice: {error}", "warning")
            break
