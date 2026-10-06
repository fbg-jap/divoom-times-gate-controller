"""Opt-in local API and MQTT bridge. All device writes go through Engine's queue."""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from . import __version__


class Bridge:
    def __init__(self, engine):
        self.engine = engine
        self.server = self.mqtt = None
        self.signature = None
        self.api_status, self.mqtt_status = "Disabled", "Disabled"
        self.connected, self.published = False, set()
        self.last_publish = -1e12
        self.last_topics = set()
        self.config = {}
        from .notifications import NotificationService
        self.notifications = NotificationService(engine)

    def status(self):
        data = self.engine.store.snapshot()
        return {"version": __version__, "api": self.api_status, "mqtt": self.mqtt_status,
                "notifications": self.notifications.status,
                "devices": [{"id": d["id"], "name": d["name"], "enabled": d.get("enabled", False)} for d in data["devices"]],
                "scenes": [{"id": s["id"], "name": s["name"]} for s in data["scenes"]]}

    def dispatch(self, body):
        if not isinstance(body, dict):
            raise ValueError("A JSON object is required")
        data = self.engine.store.snapshot()
        device_id = body.get("device_id", data["active_device"])
        if device_id not in {d["id"] for d in data["devices"]}:
            raise ValueError("Unknown device")
        action = body.get("action")
        if action == "notice":
            panel = int(body.get("panel", 1)) - 1
            seconds = int(body.get("seconds", 15))
            text = body.get("text", "")
            if not 0 <= panel <= 4 or not 5 <= seconds <= 300 or not isinstance(text, str) or not text.strip() or len(text) > 500:
                raise ValueError("Invalid notice: panel 1–5, 5–300 seconds, text up to 500 characters")
            args = {"panel": panel, "seconds": seconds, "text": text, "title": str(body.get("title", "NOTICE"))[:80], "buzzer": bool(body.get("buzzer", False))}
            action = "notification"
        elif action == "scene":
            scene = body.get("scene_id")
            if scene not in {s["id"] for s in data["scenes"]}:
                raise ValueError("Unknown scene")
            args = {"scene_id": scene}
        elif action == "brightness":
            value = int(body.get("value", -1))
            if not 0 <= value <= 100:
                raise ValueError("Brightness between 0 and 100")
            action, args = "command", {"payload": {"Command": "Channel/SetBrightness", "Brightness": value}}
        elif action == "power":
            if not isinstance(body.get("on"), bool):
                raise ValueError("on must be true or false")
            action, args = "command", {"payload": {"Command": "Channel/OnOffScreen", "OnOff": int(body["on"])}}
        elif action == "send":
            args = {}
        else:
            raise ValueError("Supported action: notice, scene, brightness, power, send")
        if self.engine.submit(action, device_id, **args) is False:
            raise RuntimeError("Queue full")
        return {"accepted": True, "device_id": device_id}

    def configure(self, data):
        config = data.get("integrations", {})
        self.engine.renderer.providers.extra.hardware_enabled = bool(config.get("hardware", False))
        self.engine.renderer.providers.extra.prtg_conf = config.get("prtg", {})
        self.engine.renderer.providers.extra.mail_conf = config.get("mail", {})
        self.engine.renderer.providers.extra.spotify_conf = config.get("spotify", {})
        self.engine.renderer.providers.extra.spotify_save = self.save_spotify_token
        signature = json.dumps({k: v for k, v in config.items() if k != "spotify"}, sort_keys=True)  # a rotated Spotify token must not restart the API/MQTT
        if signature == self.signature:
            self.sync_topics(data)
            return
        self.close()
        self.signature, self.config = signature, config
        if self.engine.demo:
            self.api_status = self.mqtt_status = "DEMO · connections disabled"
            return
        api = config.get("api", {})
        if api.get("enabled"):
            try:
                self.start_api(api)
            except OSError as error:
                self.api_status = f"Could not open the port: {error}"
                self.engine.log("API: " + self.api_status, "error")
        mqtt = config.get("mqtt", {})
        if mqtt.get("enabled"):
            try:
                self.start_mqtt(mqtt)
            except Exception as error:
                self.mqtt_status = type(error).__name__ + ": check the configuration"
                self.engine.log("MQTT: " + self.mqtt_status, "error")

    def save_spotify_token(self, token):
        """Persist a rotated refresh token (the only Spotify secret that is stored)."""
        self.engine.store.change(lambda data: data.setdefault("integrations", {}).setdefault("spotify", {}).update(refresh_token=token))

    def start_api(self, config):
        bridge = self
        token = config["token"]
        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(3)

            def log_message(self, *args):
                pass

            def reply(self, status, value):
                blob = json.dumps(value, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(blob)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(blob)

            def authorized(self):
                supplied = self.headers.get("Authorization", "")
                if self.headers.get("Origin") or not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
                    self.reply(401, {"error": "Bearer token required"})
                    return False
                return True

            def do_GET(self):
                if not self.authorized():
                    return
                if self.path != "/v1/status":
                    self.reply(404, {"error": "Unknown route"})
                    return
                self.reply(200, bridge.status())

            def do_POST(self):
                if not self.authorized():
                    return
                if self.path != "/v1/action":
                    self.reply(404, {"error": "Unknown route"})
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if self.headers.get("Transfer-Encoding") or not 1 <= size <= 16384:
                        self.reply(413, {"error": "Maximum 16 KiB"})
                        return
                    result = bridge.dispatch(json.loads(self.rfile.read(size)))
                    self.reply(202, result)
                except (ValueError, TypeError, KeyError, UnicodeError):
                    self.reply(400, {"error": "Invalid request"})
                except RuntimeError:
                    self.reply(503, {"error": "Queue full"})
        self.server = ThreadingHTTPServer((config.get("host", "127.0.0.1"), int(config.get("port", 8787))), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True, name="keeper-api").start()
        self.api_status = f"http://{self.server.server_address[0]}:{self.server.server_address[1]}"

    def start_mqtt(self, config):
        import paho.mqtt.client as mqtt
        self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="keeper_" + self.engine.store.get_device()["id"])
        prefix = config.get("prefix", "keeper")
        if config.get("username"):
            self.mqtt.username_pw_set(config["username"], config.get("password", ""))
        if config.get("tls"):
            self.mqtt.tls_set()
        self.mqtt.will_set(prefix + "/availability", "offline", qos=1, retain=True)
        self.mqtt.reconnect_delay_set(2, 60)
        self.mqtt.max_queued_messages_set(200)
        self.mqtt.max_inflight_messages_set(20)
        def on_connect(client, userdata, flags, reason, properties):
            self.connected = not reason.is_failure
            self.mqtt_status = "Connected" if self.connected else "Connection refused"
            if self.connected:
                self.last_topics = set()
                client.subscribe(prefix + "/command", qos=1)
                client.subscribe(prefix + "/sensor/#", qos=0)
                client.publish(prefix + "/availability", "online", qos=1, retain=True)
                self.sync_topics(self.engine.store.snapshot())
                self.discovery(self.engine.store.snapshot())
        def on_disconnect(client, userdata, flags, reason, properties):
            self.connected = False
            self.mqtt_status = "Disconnected · retrying"
        def on_message(client, userdata, message):
            if len(message.payload) > 16384:
                return
            try:
                text = message.payload.decode("utf-8")
                if message.topic == prefix + "/command":
                    if message.retain:
                        return  # Never replay a retained command after reconnecting.
                    self.dispatch(json.loads(text))
                else:
                    self.engine.renderer.providers.extra.receive(message.topic, text)
            except (ValueError, TypeError, RuntimeError):
                self.engine.log("MQTT: invalid message discarded", "warning")
        self.mqtt.on_connect, self.mqtt.on_disconnect, self.mqtt.on_message = on_connect, on_disconnect, on_message
        self.mqtt_status = "Conectando…"
        self.mqtt.connect_async(config["host"], int(config.get("port", 1883)), 30)
        self.mqtt.loop_start()

    def sync_topics(self, data):
        if not self.mqtt or not self.connected:
            return
        from .content import all_screens
        topics = {s.get("sensor_key", "") for s in all_screens(data) if s.get("kind") == "sensor" and s.get("sensor_source", "mqtt") == "mqtt"}
        topics |= {r.get("source", "") for r in data.get("alerts", []) if r.get("metric") == "sensor" and r.get("sensor_source", "mqtt") == "mqtt"}
        topics = {t for t in topics if t and not any(c in t for c in "+#\x00") and len(t) <= 256}
        for topic in topics - self.last_topics:
            self.mqtt.subscribe(topic)
        for topic in self.last_topics - topics:
            self.mqtt.unsubscribe(topic)
        self.last_topics = topics

    def discovery(self, data):
        if not self.mqtt or not self.connected:
            return
        prefix = self.config.get("mqtt", {}).get("prefix", "keeper")
        topics = set()
        for d in data["devices"]:
            for scene in [{"id": "restore", "name": "Send layout"}, *data["scenes"]]:
                uid = "keeper_" + d["id"] + "_" + scene["id"]
                topic = "homeassistant/button/" + uid + "/config"
                topics.add(topic)
                action = {"device_id": d["id"], "action": "send"} if scene["id"] == "restore" else {"device_id": d["id"], "action": "scene", "scene_id": scene["id"]}
                self.mqtt.publish(topic, json.dumps({"name": scene["name"], "unique_id": uid,
                    "command_topic": prefix + "/command", "payload_press": json.dumps(action),
                    "availability_topic": prefix + "/availability",
                    "device": {"identifiers": ["keeper_" + d["id"]], "name": "Keeper · " + d["name"], "manufacturer": "Divoom Keeper Studio"}}), qos=1, retain=True)
        for topic in self.published - topics:
            self.mqtt.publish(topic, "", qos=1, retain=True)
        self.published = topics

    def tick(self, data, now):
        self.configure(data)
        self.notifications.tick(data, now)
        if self.mqtt and self.connected and now - self.last_publish >= 30:
            self.last_publish = now
            prefix = self.config.get("mqtt", {}).get("prefix", "keeper")
            self.mqtt.publish(prefix + "/status", json.dumps(self.status()), retain=True)
            self.discovery(data)

    def close(self):
        self.notifications.close()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.mqtt:
            prefix = self.config.get("mqtt", {}).get("prefix", "keeper")
            self.mqtt.publish(prefix + "/availability", "offline", qos=1, retain=True)
            self.mqtt.disconnect()
            self.mqtt.loop_stop()
            self.mqtt = None
        self.connected = False
        self.api_status, self.mqtt_status = "Disabled", "Disabled"
