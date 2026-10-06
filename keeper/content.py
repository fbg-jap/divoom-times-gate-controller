"""Content composition helpers; device transport stays in protocol.py."""
from __future__ import annotations

import copy
from dataclasses import dataclass
import json
from pathlib import Path

from PIL import Image, ImageOps

PC_VIEWS = [
    ("usage", "Uso de CPU / RAM / GPU", "CPU / RAM / GPU usage"),
    ("history", "Gráficas de CPU / RAM / GPU", "CPU / RAM / GPU graphs"),
    ("network", "Red · descarga y subida", "Network · download and upload"),
    ("temperature", "Temperaturas", "Temperatures"),
    ("storage", "Disco y memoria", "Disk and memory"),
]
EXTRA_KINDS = [("music", "Música en reproducción", "Now playing"), ("rss", "Noticias RSS / Atom", "RSS / Atom news"),
               ("custom", "Diseño personalizado", "Custom design"), ("pomodoro", "Pomodoro", "Pomodoro"),
               ("sensor", "Sensor MQTT / hardware", "MQTT / hardware sensor")]
PLAYABLE = {"media", "text", "clock", "pc", "weather", "countdown", "service", "calendar"} | {x[0] for x in EXTRA_KINDS}


def empty_playlists():
    return [{"enabled": False, "items": []} for _ in range(5)]


def validate_playlists(playlists):
    if not isinstance(playlists, list) or len(playlists) != 5:
        raise ValueError("Five playlists are required")
    for playlist in playlists:
        if not isinstance(playlist, dict) or not isinstance(playlist.get("enabled", False), bool):
            raise ValueError("Invalid playlist")
        items = playlist.get("items", [])
        if not isinstance(items, list) or len(items) > 50:
            raise ValueError("Maximum 50 items per playlist")
        if playlist.get("enabled") and not items:
            raise ValueError("Add content before enabling the playlist")
        ids = set()
        for item in items:
            if not isinstance(item, dict) or not item.get("id") or item["id"] in ids:
                raise ValueError("Invalid item identifier")
            ids.add(item["id"])
            if not 5 <= int(item.get("seconds", 0)) <= 86400:
                raise ValueError("Duration must be between 5 seconds and 24 hours")
            screen = item.get("screen", {})
            if not isinstance(screen, dict) or screen.get("kind") not in PLAYABLE:
                raise ValueError("Playlists support images and widgets; no native modes or nested playlists")


def all_screens(data):
    """Include playlist media in portable backups and scene exports."""
    for owner in [*data["devices"], *data.get("scenes", [])]:
        yield from owner["screens"]
        for playlist in owner.get("playlists", []):
            for item in playlist.get("items", []):
                yield item["screen"]


@dataclass
class PlaylistCursor:
    fingerprint: str
    index: int = 0
    started: float | None = None

    @classmethod
    def for_list(cls, playlist):
        return cls(json.dumps(playlist, sort_keys=True))

    def candidate(self, items, now, advance=True):
        if advance and self.started is not None and now - self.started >= int(items[self.index]["seconds"]):
            return (self.index + 1) % len(items), True
        return self.index, self.started is None


def panorama_canvas(image, fit="cover", position=(.5, .5), zoom=1):
    """Normalized travel across the excess crop; zoom is relative to cover."""
    x, y = (max(0, min(1, float(v))) for v in position)
    zoom = max(1, min(8, float(zoom)))
    if fit == "cover":
        scale = max(640 / image.width, 128 / image.height) * zoom
        width, height = 640 / scale, 128 / scale
        left, top = (image.width - width) * x, (image.height - height) * y
        return image.resize((640, 128), Image.Resampling.LANCZOS, box=(left, top, left + width, top + height))
    if fit == "contain":
        return ImageOps.pad(image, (640, 128), method=Image.Resampling.LANCZOS, color="black", centering=(x, y))
    if fit == "stretch":
        return image.resize((640, 128), Image.Resampling.LANCZOS)
    raise ValueError("Unknown panorama fit")


def split_panorama(path, fit="cover", position=(.5, .5), zoom=1):
    if Path(path).stat().st_size > 100 * 1024 * 1024:
        raise ValueError("The image exceeds 100 MB")
    with Image.open(path) as source:
        if getattr(source, "is_animated", False):
            raise ValueError("Panorama supports still images. Choose a PNG or JPG.")
        image = ImageOps.exif_transpose(source).convert("RGBA")
        background = Image.new("RGBA", image.size, "black")
        image = Image.alpha_composite(background, image).convert("RGB")
        canvas = panorama_canvas(image, fit, position, zoom)
    return [canvas.crop((i * 128, 0, (i + 1) * 128, 128)) for i in range(5)]


def composition(owner):
    return {"screens": copy.deepcopy(owner["screens"]),
            "playlists": copy.deepcopy(owner.get("playlists", empty_playlists()))}


def assets(screen):
    yield screen
    yield from screen.get("elements", []) if screen.get("kind") == "custom" else []
