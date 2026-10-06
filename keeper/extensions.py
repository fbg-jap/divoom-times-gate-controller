"""Additional content, bounded external reads and configuration validation."""
from __future__ import annotations

import base64
from datetime import datetime
import io
import math
import re
import threading
import time
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageOps

METRICS = [("cpu", "CPU %"), ("ram", "RAM %"), ("gpu", "GPU %"), ("disk", "Disk %"),
           ("cpu_temp", "CPU °C"), ("gpu_temp", "GPU °C"), ("download", "Descarga B/s"), ("upload", "Subida B/s")]
PRTG_METRICS = {"prtg_down", "prtg_warning"}


def finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def validate_content(s):
    from .widgets import http_url
    if s.get("panorama_speed") and int(s["panorama_speed"]) not in {100, 200, 250, 500, 1000}:
        raise ValueError("Invalid panorama speed")
    if s.get("kind") == "rss" and s.get("url"):
        http_url(s["url"])
    if not 5 <= int(s.get("news_seconds", 15)) <= 3600:
        raise ValueError("Invalid news duration")
    if s.get("kind") == "custom":
        elements = s.get("elements", [])
        if not isinstance(elements, list) or len(elements) > 20:
            raise ValueError("Maximum 20 elements per design")
        for e in elements:
            if e.get("type") not in {"text", "image", "bar"}:
                raise ValueError("Unknown design element")
            for name, low, high in [("x", 0, 127), ("y", 0, 127), ("width", 1, 128), ("height", 1, 128), ("size", 6, 64)]:
                if not low <= int(e.get(name, {"width": 112, "height": 24, "size": 16}.get(name, 0))) <= high:
                    raise ValueError("Invalid design position or size")
            if finite(e.get("maximum", 100)) is None or float(e.get("maximum", 100)) <= 0:
                raise ValueError("A bar's maximum must be positive")
            ImageColor.getrgb(e.get("color", "white"))


def validate_extensions(data):
    from .content import all_screens
    from .widgets import http_url
    for s in all_screens(data):
        validate_content(s)
    ids = {d["id"] for d in data["devices"]}
    scenes = {s["id"] for s in data.get("scenes", [])}
    for group in ("alerts", "reminders", "profiles"):
        rules = data.get(group, [])
        if not isinstance(rules, list) or len(rules) > 100:
            raise ValueError("Maximum 100 rules per category")
        seen = set()
        for r in rules:
            if not r.get("id") or r["id"] in seen or r.get("device_id") not in ids:
                raise ValueError("Invalid rule or device")
            seen.add(r["id"])
            if group == "profiles":
                if r.get("scene_id") not in scenes or r.get("trigger") not in {"process", "locked", "desktop"}:
                    raise ValueError("Invalid scene or profile condition")
                if r["trigger"] == "process" and not r.get("process", "").strip():
                    raise ValueError("Enter the executable name")
            else:
                if not 0 <= int(r.get("panel", 0)) <= 4 or not 5 <= int(r.get("seconds", 15)) <= 300:
                    raise ValueError("Invalid screen or notice duration")
                if not str(r.get("text", "")).strip() or len(r["text"]) > 500:
                    raise ValueError("Enter a notice of up to 500 characters")
                if group == "reminders" and not 1 <= int(r.get("minutes", 30)) <= 10080:
                    raise ValueError("Invalid reminder interval")
                if group == "alerts":
                    if r.get("metric") not in {k for k, _ in METRICS} | {"disk_free", "service", "sensor"} | PRTG_METRICS | {"mail_unread"}:
                        raise ValueError("Unknown alert metric")
                    if r.get("operator", "above") not in {"above", "below"} or finite(r.get("threshold", 80)) is None:
                        raise ValueError("Invalid threshold")
                    if not 0 <= int(r.get("hold", 10)) <= 3600 or not 30 <= int(r.get("cooldown", 300)) <= 86400:
                        raise ValueError("Invalid alert time")
                    if r["metric"] == "service":
                        http_url(r.get("source", ""))
    integrations = data.get("integrations", {})
    for name in ("api", "mqtt"):
        conf = integrations.get(name, {})
        if not 1 <= int(conf.get("port", 8787 if name == "api" else 1883)) <= 65535:
            raise ValueError("Invalid port")
        if conf.get("enabled"):
            if name == "api" and (conf.get("host") not in {"127.0.0.1", "0.0.0.0"} or len(conf.get("token", "")) < 24):
                raise ValueError("The API needs a valid address and a token of at least 24 characters")
            if name == "mqtt" and (not conf.get("host", "").strip() or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", conf.get("prefix", "keeper"))):
                raise ValueError("Invalid MQTT server or prefix")
    validate_new_integrations(integrations)


def _text(conf, key, limit):
    value = conf.get(key, "")
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"Invalid {key}")
    return value


def _flag(conf, key):
    if not isinstance(conf.get(key, False), bool):
        raise ValueError(f"Invalid {key}")


def _bounded(conf, key, low, high, default):
    value = conf.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"Invalid {key}")


def _names(conf, key):
    values = conf.get(key, [])
    if not isinstance(values, list) or len(values) > 50 or any(not isinstance(v, str) or len(v) > 64 for v in values):
        raise ValueError(f"Invalid {key}")


def validate_new_integrations(integrations):
    from .widgets import http_url
    for name in ("spotify", "prtg", "mail", "notifications"):
        conf = integrations.get(name, {})
        if not isinstance(conf, dict):
            raise ValueError(f"Invalid {name} settings")
        for key in ("enabled", "verify_tls", "show_subject", "show_body"):
            _flag(conf, key)
        if name == "spotify":
            _text(conf, "client_id", 128); _text(conf, "refresh_token", 1024)
        elif name == "prtg":
            _text(conf, "token", 512)
            if _text(conf, "base_url", 300):
                http_url(conf["base_url"])
        elif name == "mail":
            _bounded(conf, "port", 1, 65535, 993)
            for key, limit in (("host", 255), ("user", 256), ("password", 256), ("mailbox", 128)):
                _text(conf, key, limit)
        else:
            _bounded(conf, "panel", 1, 5, 1); _bounded(conf, "seconds", 5, 60, 8); _bounded(conf, "per_minute", 1, 60, 6)
            _names(conf, "allow_apps"); _names(conf, "deny_apps")


# Legacy Spanish phase values; only used to migrate previously saved/loaded state.
LEGACY_PHASES = {"Preparado": "Ready", "Trabajo": "Work", "Descanso": "Break", "Descanso largo": "Long break"}


def normalize_phase(phase):
    return LEGACY_PHASES.get(phase, phase)


class ExtraSources:
    def __init__(self, providers):
        from .windows_sources import AsyncProbe, read_media, HARDWARE_SCRIPT
        import os
        from .platform_support import linux_music, linux_hardware
        self.providers = providers
        self.media_probe = AsyncProbe(read_media if os.name == "nt" else linux_music)
        self.hardware_probe = AsyncProbe(HARDWARE_SCRIPT if os.name == "nt" else linux_hardware, 10)
        self.hardware_enabled = False
        self.sensor_lock = threading.Lock()
        self.mqtt_values = {}
        self.pomodoro = {"phase": "Ready", "remaining": 1500, "total": 1500, "running": False, "cycle": 0}
        self.news_cursor = {}
        self.prtg_conf, self.prtg_key, self.prtg_probe = {}, None, None
        self.mail_conf, self.mail_key, self.mail_probe = {}, None, None
        self.spotify_conf, self.spotify_save, self.spotify_source, self.spotify_probe = {}, None, None, None

    def music(self):
        if self.providers.demo:
            return {"title": "Midnight City", "artist": "Demo player", "status": "Playing", "art": ""}
        value, error = self.media_probe.read()
        return value or {"title": "", "artist": "", "status": error or "Nothing playing", "art": ""}

    def hardware(self):
        if self.providers.demo:
            return [{"Identifier": "/demo/cpu/temperature/0", "Name": "CPU Package", "SensorType": "Temperature", "Value": 54}]
        if not self.hardware_enabled:
            return []
        value, _ = self.hardware_probe.read()
        return value if isinstance(value, list) else []

    def receive(self, topic, payload):
        with self.sensor_lock:
            if topic not in self.mqtt_values and len(self.mqtt_values) >= 200:
                self.mqtt_values.pop(next(iter(self.mqtt_values)))
            self.mqtt_values[topic] = (str(payload)[:4096], time.monotonic())

    def sensor(self, source, key, field="", stale=300):
        if source == "hardware":
            item = next((s for s in self.hardware() if s["Identifier"] == key), None)
            return item.get("Value") if item else None
        with self.sensor_lock:
            value, stamp = self.mqtt_values.get(key, (None, -1e12))
        if time.monotonic() - stamp > max(10, stale):
            return None
        if field and value is not None:
            import json
            try:
                value = json.loads(value)
                for part in field.split("."):
                    value = value[int(part)] if isinstance(value, list) else value[part]
            except (KeyError, ValueError, TypeError, IndexError):
                return None
        return value if isinstance(value, (str, int, float)) else None

    def prtg_state(self):
        """(data, error): data is the status counts or None; error is "", "not configured" or a short reason. Never blocks."""
        conf = self.prtg_conf or {}
        if self.providers.demo:
            return {"up": 118, "warning": 3, "down": 1, "paused": 4, "unusual": 0, "worst": "web-01 · HTTP"}, ""
        if not conf.get("enabled") or not conf.get("base_url") or not conf.get("token"):
            return None, "not configured"
        key = (conf["base_url"], conf["token"], conf.get("verify_tls", True))
        if key != self.prtg_key:
            from .windows_sources import AsyncProbe
            def sample():
                try:
                    return self.providers.prtg_fetch(*key)
                except Exception:
                    raise RuntimeError("PRTG request failed") from None  # the original message can carry the URL with the token
            self.prtg_key, self.prtg_probe = key, AsyncProbe(sample, 30, 120)
        value, error = self.prtg_probe.read()
        return value, error or ""

    def prtg(self):
        """Status counts from integrations.prtg, or None (not configured/unreachable/not sampled yet)."""
        return self.prtg_state()[0]

    def mail_state(self):
        """(data, error): data is {"unread","subject"} or None; error is "" or a short reason."""
        conf = self.mail_conf or {}
        if self.providers.demo:
            return {"unread": 3, "subject": "Weekly report" if conf.get("show_subject") else None}, ""
        if not conf.get("enabled") or not conf.get("host") or not conf.get("user") or not conf.get("password"):
            return None, "not configured"
        key = tuple(conf.get(k) for k in ("host", "port", "user", "password", "mailbox", "show_subject"))
        if key != self.mail_key:
            from .mail import fetch_unread
            from .windows_sources import AsyncProbe
            snapshot = dict(conf)
            self.mail_key, self.mail_probe = key, AsyncProbe(lambda: fetch_unread(snapshot), 120, 600)
        value, error = self.mail_probe.read()
        return value, error or ""

    def mail(self):
        return self.mail_state()[0]

    def spotify_state(self):
        """(data, error): data is a track dict or {"idle": True}; error is "", "not connected" or a short reason."""
        conf = self.spotify_conf or {}
        if self.providers.demo:
            return {"title": "Midnight City", "artist": "Demo player", "playing": True, "art": "",
                    "progress_ms": 95000, "duration_ms": 240000, "sampled": time.monotonic()}, ""
        if not conf.get("enabled") or not conf.get("client_id") or not conf.get("refresh_token"):
            return None, "not connected"
        source = self.spotify_source
        if (source is None or source.client_id != conf["client_id"]
                or conf["refresh_token"] not in (source.initial_token, source.refresh_token)):
            from .spotify import SpotifySource
            from .windows_sources import AsyncProbe
            # Started lazily (first render of a Spotify widget) and rebuilt when the client id or a reconnected token changes.
            source = self.spotify_source = SpotifySource(conf["client_id"], conf["refresh_token"], self.spotify_save)
            self.spotify_probe = AsyncProbe(source.poll, 5, 30)
        value, error = self.spotify_probe.read()
        return value, error or ""

    def news(self, url, seconds=15):
        if not url:
            return "Configure an RSS source", "RSS"
        if self.providers.demo:
            return "Your favorite news, on your desktop", "DEMO · 1/3"
        from .widgets import http_url
        def fetch():
            from defusedxml import ElementTree
            import html
            with self.providers.session.get(http_url(url), timeout=6, stream=True) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 2 * 1024**2:
                        raise ValueError("The source exceeds 2 MB")
                    chunks.append(chunk)
            root = ElementTree.fromstring(b"".join(chunks))
            titles = []
            for entry in root.iter():
                if entry.tag.rsplit("}", 1)[-1] in {"item", "entry"}:
                    title = next((x for x in entry if x.tag.rsplit("}", 1)[-1] == "title"), None)
                    if title is not None:
                        text = html.unescape("".join(title.itertext()))
                        text = re.sub(r"<[^>]*>", "", text).strip()[:500]
                        if text:
                            titles.append(text)
            return titles[:50]
        try:
            titles = self.providers.cached(("rss", url), 300, fetch)
        except Exception:
            # Cache failures too so a broken source doesn't get polled every frame.
            self.providers.cache[("rss", url)] = (time.monotonic(), [])
            return "Source unavailable", "RSS · ERROR"
        if not titles:
            return "No headlines available", "RSS"
        cursor = self.news_cursor.setdefault(url, [0, time.monotonic()])
        if time.monotonic() - cursor[1] >= seconds:
            cursor[:] = [(cursor[0] + 1) % len(titles), time.monotonic()]
        cursor[0] %= len(titles)
        return titles[cursor[0]], f"RSS · {cursor[0] + 1}/{len(titles)}"


def custom_image(screen, values):
    from .widgets import font, wrap_text
    image = Image.new("RGB", (128, 128), screen.get("background", "#101b2b"))
    for e in screen.get("elements", []):
        x, y = int(e.get("x", 8)), int(e.get("y", 8))
        w, h = int(e.get("width", 112)), int(e.get("height", 24))
        layer = Image.new("RGBA", (w, h))
        draw = ImageDraw.Draw(layer)
        color = e.get("color", "#64e6ca")
        if e["type"] == "image":
            try:
                with Image.open(e.get("path", "")) as source:
                    layer = ImageOps.fit(ImageOps.exif_transpose(source).convert("RGBA"), (w, h))
            except (OSError, ValueError):
                draw.text((0, 0), "Image N/A", fill=color, font=font(10))
        elif e["type"] == "bar":
            value = finite(values.get(e.get("metric", "cpu")))
            draw.rectangle((0, 0, w-1, h-1), fill="#26334b")
            if value is not None:
                end = round(w * max(0, min(1, value / float(e.get("maximum", 100)))))
                if end:
                    draw.rectangle((0, 0, end-1, h-1), fill=color)
            else:
                draw.text((2, 0), "N/A", fill=color, font=font(10))
        else:
            text = str(e.get("text", "Text"))
            for key, value in {**values, "time": datetime.now().strftime("%H:%M"), "date": datetime.now().strftime("%d/%m")}.items():
                text = text.replace("{" + key + "}", "N/A" if value is None else f"{value:.0f}" if isinstance(value, (float, int)) else str(value))
            size = int(e.get("size", 16))
            for n, line in enumerate(wrap_text(draw, text, font(size), w)[:h // max(1, size) + 1]):
                draw.text((0, n * (size + 2)), line, font=font(size), fill=color)
        image.paste(layer, (x, y), layer)
    return image


def render_extra(s, providers):
    from .widgets import font, wrap_text
    extra = providers.extra
    if s["kind"] == "custom":
        return custom_image(s, providers.pc())
    image = Image.new("RGB", (128, 128), s.get("background", "#101b2b"))
    draw = ImageDraw.Draw(image)
    accent = s.get("color", "#64e6ca")
    def lines(text, y, size=13, count=3, color="white"):
        face = font(size)
        wrapped, current = [], ""
        for word in str(text).split():
            candidate = (current + " " + word).strip()
            if draw.textlength(candidate, font=face) <= 112:
                current = candidate
            else:
                if current:
                    wrapped.append(current)
                parts = wrap_text(draw, word, face, 112)
                wrapped.extend(parts[:-1]); current = parts[-1]
        if current:
            wrapped.append(current)
        if len(wrapped) > count:
            last = wrapped[count-1]
            while last and draw.textlength(last + "…", font=face) > 112:
                last = last[:-1]
            wrapped[count-1] = last + "…"
        for n, line in enumerate(wrapped[:count]):
            draw.text((8, y+n*(size+2)), line, fill=color, font=face)
    kind = s["kind"]
    if kind == "music":
        data = extra.music()
        if data.get("art"):
            try:
                with Image.open(io.BytesIO(base64.b64decode(data["art"]))) as art:
                    image.paste(ImageOps.fit(art.convert("RGB"), (52, 52)), (8, 6))
            except Exception:
                pass
        if not data.get("art"):
            draw.ellipse((9, 7, 57, 55), outline=accent, width=2)
            draw.text((25, 13), "♪", fill=accent, font=font(25))
        draw.text((66, 12), "PLAY" if data.get("status") == "Playing" else "PAUSE", fill=accent, font=font(10))
        lines(data.get("title") or "Nothing playing", 61, 13, 2)
        lines(data.get("artist") or data.get("status", ""), 95, 10, 2, accent)
    elif kind == "rss":
        title, state = extra.news(s.get("url", ""), int(s.get("news_seconds", 15)))
        lines(s.get("title") or state, 7, 10, 1, accent)
        lines(title, 28, int(s.get("news_size", 13)), 5)
    elif kind == "pomodoro":
        data = extra.pomodoro
        phase = normalize_phase(data["phase"])
        lines(s.get("title") or phase.upper(), 8, 12, 1, accent)
        seconds = max(0, math.ceil(data["remaining"]))
        lines(f"{seconds//60:02}:{seconds%60:02}", 40, 32, 1)
        lines(f"Cycle {data['cycle']} · {'Active' if data['running'] else 'Paused'}", 96, 11, 1, accent)
        draw.rectangle((8, 117, 119, 120), fill="#26334b")
        end = 8 + int(111 * (1 - seconds / max(1, data["total"])))
        if end > 8:
            draw.rectangle((8, 117, end, 120), fill=accent)
    elif kind == "sensor":
        value = extra.sensor(s.get("sensor_source", "mqtt"), s.get("sensor_key", ""), s.get("sensor_field", ""), int(s.get("sensor_stale", 300)))
        lines(s.get("title") or "SENSOR", 8, 12, 1, accent)
        number = finite(value)
        text = "N/A" if value is None else f"{number:.1f}" if number is not None else str(value)
        lines(text[:60], 42, 25, 2)
        lines(s.get("sensor_unit", ""), 104, 12, 1, accent)
    elif kind == "prtg":
        data, error = extra.prtg_state()
        lines(s.get("title") or "PRTG", 7, 11, 1, accent)
        if data is None and error.startswith("Waiting"):
            lines("Connecting…", 40, 13, 2, "#9aa4b5")
        elif data is None:
            lines("Source unavailable", 40, 13, 3, "#ff6b6b")
        else:
            face = font(22, True)
            for n, (key, color) in enumerate((("up", "#4ade80"), ("warning", "#facc15"), ("down", "#ff4d4d"), ("paused", "#9aa4b5"))):
                x, y = 8 + (n % 2) * 56, 26 + (n // 2) * 30
                draw.text((x, y), str(data[key]), fill=color, font=face)
                draw.text((x, y + 24), key.upper(), fill=color, font=font(8))
            lines(data["worst"] or "All sensors OK", 92, 10, 3, "white" if data["worst"] else "#4ade80")
    elif kind == "spotify":
        data, error = extra.spotify_state()
        lines(s.get("title") or "Spotify", 7, 11, 1, accent)
        if data is None and error in {"not connected", "reconnect"}:
            lines("Spotify not connected", 40, 13, 3, "#ff6b6b")
        elif data is None and error.startswith("Waiting"):
            lines("Connecting…", 40, 13, 2, "#9aa4b5")
        elif data is None:
            lines("Spotify unavailable", 40, 13, 3, "#ff6b6b")
        elif data.get("idle"):
            lines("Nothing playing", 40, 13, 3, "#9aa4b5")
        else:
            if data.get("art"):
                try:
                    with Image.open(io.BytesIO(base64.b64decode(data["art"]))) as art:
                        image.paste(ImageOps.fit(art.convert("RGB"), (52, 52)), (8, 22))
                except Exception:
                    data = {**data, "art": ""}
            if not data.get("art"):
                draw.ellipse((9, 23, 57, 71), outline=accent, width=2)
                draw.text((25, 29), "♪", fill=accent, font=font(25))
            draw.text((66, 28), "PLAY" if data.get("playing") else "PAUSE", fill=accent, font=font(10))
            lines(data.get("title") or "Spotify", 77, 13, 2)
            lines(data.get("artist", ""), 105, 10, 1, accent)
            total = int(data.get("duration_ms") or 0)
            if total > 0:
                progress = int(data.get("progress_ms") or 0)
                if data.get("playing"):
                    progress += int((time.monotonic() - data.get("sampled", time.monotonic())) * 1000)
                end = 8 + int(111 * max(0, min(1, progress / total)))
                draw.rectangle((8, 122, 119, 124), fill="#26334b")
                if end > 8:
                    draw.rectangle((8, 122, end, 124), fill=accent)
    elif kind == "mail":
        data, error = extra.mail_state()
        lines(s.get("title") or "Unread mail", 7, 11, 1, accent)
        if data is None and error == "not configured":
            lines("Mail not configured", 40, 13, 3, "#ff6b6b")
        elif data is None and error.startswith("Waiting"):
            lines("Checking mail…", 40, 13, 2, "#9aa4b5")
        elif data is None:
            lines("Mail unavailable", 34, 13, 1, "#ff6b6b")
            lines(error or "protocol error", 56, 10, 3, "#9aa4b5")
        else:
            color = "#4ade80" if data["unread"] == 0 else "#fbbf24"
            text = str(data["unread"])
            face = font(46, True)
            draw.text(((128 - draw.textlength(text, font=face)) / 2, 28), text, fill=color, font=face)
            if data.get("subject"):
                lines(data["subject"], 92, 10, 3)
    return image
