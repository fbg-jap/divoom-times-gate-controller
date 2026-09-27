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

METRICS = [("cpu", "CPU %"), ("ram", "RAM %"), ("gpu", "GPU %"), ("disk", "Disco %"),
           ("cpu_temp", "CPU °C"), ("gpu_temp", "GPU °C"), ("download", "Descarga B/s"), ("upload", "Subida B/s")]


def finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def validate_content(s):
    from .widgets import http_url
    if s.get("panorama_speed") and int(s["panorama_speed"]) not in {100, 200, 250, 500, 1000}:
        raise ValueError("Velocidad de panorámica inválida")
    if s.get("kind") == "rss" and s.get("url"):
        http_url(s["url"])
    if not 5 <= int(s.get("news_seconds", 15)) <= 3600:
        raise ValueError("Duración de noticia inválida")
    if s.get("kind") == "custom":
        elements = s.get("elements", [])
        if not isinstance(elements, list) or len(elements) > 20:
            raise ValueError("Máximo 20 elementos por diseño")
        for e in elements:
            if e.get("type") not in {"text", "image", "bar"}:
                raise ValueError("Elemento del diseño desconocido")
            for name, low, high in [("x", 0, 127), ("y", 0, 127), ("width", 1, 128), ("height", 1, 128), ("size", 6, 64)]:
                if not low <= int(e.get(name, {"width": 112, "height": 24, "size": 16}.get(name, 0))) <= high:
                    raise ValueError("Posición o tamaño del diseño inválido")
            if finite(e.get("maximum", 100)) is None or float(e.get("maximum", 100)) <= 0:
                raise ValueError("El máximo de una barra debe ser positivo")
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
            raise ValueError("Máximo 100 reglas por categoría")
        seen = set()
        for r in rules:
            if not r.get("id") or r["id"] in seen or r.get("device_id") not in ids:
                raise ValueError("Regla o dispositivo inválido")
            seen.add(r["id"])
            if group == "profiles":
                if r.get("scene_id") not in scenes or r.get("trigger") not in {"process", "locked", "desktop"}:
                    raise ValueError("Escena o condición de perfil inválida")
                if r["trigger"] == "process" and not r.get("process", "").strip():
                    raise ValueError("Escribe el nombre del ejecutable")
            else:
                if not 0 <= int(r.get("panel", 0)) <= 4 or not 5 <= int(r.get("seconds", 15)) <= 300:
                    raise ValueError("Pantalla o duración de aviso inválida")
                if not str(r.get("text", "")).strip() or len(r["text"]) > 500:
                    raise ValueError("Escribe un aviso de hasta 500 caracteres")
                if group == "reminders" and not 1 <= int(r.get("minutes", 30)) <= 10080:
                    raise ValueError("Intervalo de recordatorio inválido")
                if group == "alerts":
                    if r.get("metric") not in {k for k, _ in METRICS} | {"disk_free", "service", "sensor"}:
                        raise ValueError("Métrica de alerta desconocida")
                    if r.get("operator", "above") not in {"above", "below"} or finite(r.get("threshold", 80)) is None:
                        raise ValueError("Umbral inválido")
                    if not 0 <= int(r.get("hold", 10)) <= 3600 or not 30 <= int(r.get("cooldown", 300)) <= 86400:
                        raise ValueError("Tiempo de alerta inválido")
                    if r["metric"] == "service":
                        http_url(r.get("source", ""))
    integrations = data.get("integrations", {})
    for name in ("api", "mqtt"):
        conf = integrations.get(name, {})
        if not 1 <= int(conf.get("port", 8787 if name == "api" else 1883)) <= 65535:
            raise ValueError("Puerto inválido")
        if conf.get("enabled"):
            if name == "api" and (conf.get("host") not in {"127.0.0.1", "0.0.0.0"} or len(conf.get("token", "")) < 24):
                raise ValueError("La API necesita una dirección válida y un token de al menos 24 caracteres")
            if name == "mqtt" and (not conf.get("host", "").strip() or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", conf.get("prefix", "keeper"))):
                raise ValueError("Servidor o prefijo MQTT inválido")


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
        self.pomodoro = {"phase": "Preparado", "remaining": 1500, "total": 1500, "running": False, "cycle": 0}
        self.news_cursor = {}

    def music(self):
        if self.providers.demo:
            return {"title": "Midnight City", "artist": "Demo player", "status": "Playing", "art": ""}
        value, error = self.media_probe.read()
        return value or {"title": "", "artist": "", "status": error or "Sin reproducción", "art": ""}

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

    def news(self, url, seconds=15):
        if not url:
            return "Configura una fuente RSS", "RSS"
        if self.providers.demo:
            return "Tus noticias favoritas, en el escritorio", "DEMO · 1/3"
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
                        raise ValueError("La fuente supera 2 MB")
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
            return "Fuente no disponible", "RSS · ERROR"
        if not titles:
            return "Sin titulares disponibles", "RSS"
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
                draw.text((0, 0), "Imagen N/D", fill=color, font=font(10))
        elif e["type"] == "bar":
            value = finite(values.get(e.get("metric", "cpu")))
            draw.rectangle((0, 0, w-1, h-1), fill="#26334b")
            if value is not None:
                end = round(w * max(0, min(1, value / float(e.get("maximum", 100)))))
                if end:
                    draw.rectangle((0, 0, end-1, h-1), fill=color)
            else:
                draw.text((2, 0), "N/D", fill=color, font=font(10))
        else:
            text = str(e.get("text", "Texto"))
            for key, value in {**values, "time": datetime.now().strftime("%H:%M"), "date": datetime.now().strftime("%d/%m")}.items():
                text = text.replace("{" + key + "}", "N/D" if value is None else f"{value:.0f}" if isinstance(value, (float, int)) else str(value))
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
            except (ValueError, OSError):
                pass
        if not data.get("art"):
            draw.ellipse((9, 7, 57, 55), outline=accent, width=2)
            draw.text((25, 13), "♪", fill=accent, font=font(25))
        draw.text((66, 12), "PLAY" if data.get("status") == "Playing" else "PAUSE", fill=accent, font=font(10))
        lines(data.get("title") or "Sin reproducción", 61, 13, 2)
        lines(data.get("artist") or data.get("status", ""), 95, 10, 2, accent)
    elif kind == "rss":
        title, state = extra.news(s.get("url", ""), int(s.get("news_seconds", 15)))
        lines(s.get("title") or state, 7, 10, 1, accent)
        lines(title, 28, int(s.get("news_size", 13)), 5)
    elif kind == "pomodoro":
        data = extra.pomodoro
        lines(s.get("title") or data["phase"].upper(), 8, 12, 1, accent)
        seconds = max(0, math.ceil(data["remaining"]))
        lines(f"{seconds//60:02}:{seconds%60:02}", 40, 32, 1)
        lines(f"Ciclo {data['cycle']} · {'Activo' if data['running'] else 'Pausa'}", 96, 11, 1, accent)
        draw.rectangle((8, 117, 119, 120), fill="#26334b")
        end = 8 + int(111 * (1 - seconds / max(1, data["total"])))
        if end > 8:
            draw.rectangle((8, 117, end, 120), fill=accent)
    elif kind == "sensor":
        value = extra.sensor(s.get("sensor_source", "mqtt"), s.get("sensor_key", ""), s.get("sensor_field", ""), int(s.get("sensor_stale", 300)))
        lines(s.get("title") or "SENSOR", 8, 12, 1, accent)
        number = finite(value)
        text = "N/D" if value is None else f"{number:.1f}" if number is not None else str(value)
        lines(text[:60], 42, 25, 2)
        lines(s.get("sensor_unit", ""), 104, 12, 1, accent)
    return image
