from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import uuid
from .content import all_screens, assets, composition, empty_playlists, validate_playlists, PLAYABLE


def uid() -> str:
    return uuid.uuid4().hex[:12]


def slot(kind="empty", **kwargs):
    return {"kind": kind, "path": "", "title": "", "text": "", "color": "#64e6ca",
            "background": "#101b2b", "fit": "contain", "refresh": 30,
            "timezone": "Europe/Madrid", "latitude": 40.4168, "longitude": -3.7038,
            "url": "", "target": "", "font_size": 24, "frame_step": 1,
            "native_id": 625, "independence": 0, "pc_view": "usage", "pc_disk": "", "native_pc_mode": "existing", **kwargs}


def device(ip="", name="Times Gate", **kwargs):
    return {"id": uid(), "name": name, "ip": ip, "mac": "", "device_id": 0, "port": 0, "local_token": "",
            "enabled": False, "suspended": False, "screens_off": False, "quality": 85, "speed": 100, "interval_minutes": 60,
            "screens": [slot() for _ in range(5)], "playlists": empty_playlists(), "rotation": [], "rotation_seconds": 300,
            **kwargs}


def defaults():
    d = device()
    return {"version": 2, "language": "en", "theme": "dark", "startup": False,
            "resend_on_startup": True, "active_device": d["id"], "devices": [d],
            "scenes": [], "schedules": [], "alerts": [], "reminders": [], "profiles": [],
            "integrations": {"api": {"enabled": False, "host": "127.0.0.1", "port": 8787, "token": ""},
                             "mqtt": {"enabled": False, "host": "", "port": 1883, "prefix": "keeper", "username": "", "password": "", "tls": False},
                             "hardware": False}}


def validate(data):
    if not isinstance(data, dict) or data.get("version") != 2:
        raise ValueError("Unsupported configuration format (version 2 required)")
    if not isinstance(data.get("devices"), list) or not data["devices"]:
        raise ValueError("The configuration needs at least one device")
    ids = set()
    for d in data["devices"]:
        if not isinstance(d, dict) or not d.get("id") or d["id"] in ids:
            raise ValueError("Duplicate or invalid device identifier")
        ids.add(d["id"])
        if 'lighting' in d:
            from .lighting import validate_lighting
            validate_lighting(d['lighting'])
        if 'lighting_restore' in d and type(d['lighting_restore']) is not bool:
            raise ValueError('Invalid RGB recovery state')
        validate_playlists(d.get("playlists", empty_playlists()))
        if len(d.get("screens", [])) != 5:
            raise ValueError("Each device needs five screens")
        if not 1 <= int(d.get("interval_minutes", 60)) <= 10080:
            raise ValueError("Invalid interval")
        for s in d["screens"]:
            if not isinstance(s, dict) or s.get("kind") not in {
                "empty", "media", "text", "clock", "pc", "weather", "countdown",
                "service", "calendar", "native", "pc_native"} | PLAYABLE:
                raise ValueError("Unknown screen type")
    if data.get("active_device") not in ids:
        raise ValueError("The active device does not exist")
    allowed_kinds = {"empty", "media", "text", "clock", "pc", "weather", "countdown", "service", "calendar", "native", "pc_native"} | PLAYABLE
    scene_ids = set()
    for scene in data.get("scenes", []):
        if not isinstance(scene, dict) or not scene.get("id") or scene["id"] in scene_ids:
            raise ValueError("Invalid scene identifier")
        scene_ids.add(scene["id"])
        validate_playlists(scene.get("playlists", empty_playlists()))
        screens = scene.get("screens", [])
        if len(screens) != 5 or any(not isinstance(s, dict) or s.get("kind") not in allowed_kinds for s in screens):
            raise ValueError("Invalid scene")
    for rule in data.get("schedules", []):
        from datetime import time
        time.fromisoformat(rule["time"])
        if rule.get("action") not in {"scene", "brightness", "on", "off"}:
            raise ValueError("Unknown scheduled action")
        if rule.get("device_id") not in ids or any(n not in range(7) for n in rule.get("days", [])):
            raise ValueError("Invalid schedule target or days")
        if rule["action"] == "scene" and rule.get("value") not in scene_ids:
            raise ValueError("The schedule points to a nonexistent scene")
        if rule["action"] == "brightness" and not 0 <= int(rule["value"]) <= 100:
            raise ValueError("Invalid schedule brightness")

    from .extensions import validate_extensions
    validate_extensions(data)


class ConfigStore:
    def __init__(self, root: Path | None = None, migrate=True):
        from .platform_support import data_directory
        self.root = root or data_directory()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "config.json"
        self.media_dir = self.root / "media"
        self.media_dir.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.migration_note = ""
        self.data = defaults()
        if self.path.exists():
            # Never overwrite a damaged config with defaults.
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
            validate(raw)
            self.data = {**defaults(), **raw}
        elif migrate:
            old = Path(os.getenv("APPDATA", str(Path.home()))) / "DivoomKeeper" / "config.json"
            if old.exists():
                shutil.copy2(old, self.root / "legacy-config.original.json")
                self._migrate(json.loads(old.read_text(encoding="utf-8-sig")))
        self.save()

    def _migrate(self, raw):
        profiles = dict(raw.get("device_profiles", {}))
        active_ip = raw.get("device_ip", "")
        profiles[active_ip] = {"screens": raw.get("screens", [])}
        migrated = []
        for ip, profile in profiles.items():
            if not ip:
                continue
            d = device(ip, f"Times Gate · {ip}", quality=raw.get("quality", 85),
                       speed=raw.get("speed", 100), interval_minutes=raw.get("interval_minutes", 60))
            for i, source in enumerate(profile.get("screens", [])[:5]):
                path = source.get("path", "")
                if path:
                    owned = self.import_media(path) if Path(path).is_file() else path
                    d["screens"][i] = slot("media", path=owned, fit="stretch")
            migrated.append(d)
            if ip == active_ip:
                self.data["active_device"] = d["id"]
        if migrated:
            self.data["devices"] = migrated
        self.data["theme"] = raw.get("ui_theme", "dark")
        self.data["language"] = raw.get("ui_lang", "en")
        self.data["resend_on_startup"] = raw.get("resend_on_startup", True)
        self.migration_note = "Profiles imported. Enable Automatic when you want to start."

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.data)

    def save(self):
        with self.lock:
            validate(self.data)
            temp = self.path.with_suffix(".tmp")
            with temp.open("w", encoding="utf-8") as stream:
                json.dump(self.data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)

    def change(self, callback):
        with self.lock:
            old = copy.deepcopy(self.data)
            try:
                result = callback(self.data)
                self.save()
                return result
            except Exception:
                self.data = old
                raise

    def get_device(self, device_id=None):
        data = self.snapshot()
        return next(d for d in data["devices"] if d["id"] == (device_id or data["active_device"]))

    def update_device(self, updated):
        def update(data):
            idx = next(i for i, d in enumerate(data["devices"]) if d["id"] == updated["id"])
            data["devices"][idx] = copy.deepcopy(updated)
        self.change(update)

    def update_fields(self, device_id, /, **fields):
        # Positional-only so a stored field can itself be named "device_id".
        self.change(lambda data: next(d for d in data["devices"] if d["id"] == device_id).update(copy.deepcopy(fields)))

    def update_screen(self, device_id, index, screen):
        def update(data):
            d = next(d for d in data["devices"] if d["id"] == device_id)
            d["screens"][index] = copy.deepcopy(screen)
        self.change(update)

    def import_media(self, path):
        source = Path(path)
        if not source.is_file():
            raise ValueError("File not found")
        if source.stat().st_size > 100 * 1024 * 1024:
            raise ValueError("The file exceeds 100 MB")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:20]
        target = self.media_dir / (digest + source.suffix.lower())
        if not target.exists():
            shutil.copy2(source, target)
        return str(target)

    def apply_panorama(self, images, title="Panorama"):
        from datetime import datetime
        from .widgets import png_bytes
        if len(images) != 5 or any(image.size != (128, 128) for image in images):
            raise ValueError("Panorama needs five 128 × 128 images")
        screens = []
        for i, image in enumerate(images):
            blob = png_bytes(image)
            path = self.media_dir / (hashlib.sha256(blob).hexdigest()[:20] + ".png")
            path.write_bytes(blob)
            screens.append(slot("media", path=str(path), fit="stretch", title=f"{title} · {i + 1}"))
        def update(data):
            d = next(d for d in data["devices"] if d["id"] == data["active_device"])
            data["scenes"].append({"id": uid(), "name": "Before panorama · " + datetime.now().strftime("%d/%m %H:%M:%S"), **composition(d)})
            d["screens"] = screens
            # Retain the lists for later use, but don't let them replace the panorama.
            for playlist in d.get("playlists", []):
                playlist["enabled"] = False
        self.change(update)

    def apply_panorama_animation(self, blobs, speed, title="Animated panorama"):
        import io
        from datetime import datetime
        from .panorama_media import animation_frames
        if len(blobs) != 5:
            raise ValueError("Five parts are required")
        counts = [len(animation_frames(io.BytesIO(blob), speed)) for blob in blobs]
        if not counts[0] or len(set(counts)) != 1:
            raise ValueError("All five parts must have the same duration")
        screens = []
        for i, blob in enumerate(blobs):
            path = self.media_dir / (hashlib.sha256(blob).hexdigest()[:20] + ".gif")
            path.write_bytes(blob)
            screens.append(slot("media", path=str(path), fit="stretch", title=f"{title} · {i+1}", panorama_speed=int(speed)))
        def update(data):
            d = next(d for d in data["devices"] if d["id"] == data["active_device"])
            data["scenes"].append({"id": uid(), "name": "Before panorama · " + datetime.now().strftime("%d/%m %H:%M:%S"), **composition(d)})
            d["screens"] = screens
            for playlist in d.get("playlists", []):
                playlist["enabled"] = False
        self.change(update)

    def export(self, path):
        # Portable zip: package every referenced local image/ICS, including scenes.
        import zipfile
        data = self.snapshot()
        for conf in data.get("integrations", {}).values():
            if isinstance(conf, dict):
                conf["enabled"] = False
                for secret in ("token", "password"):
                    if secret in conf:
                        conf[secret] = ""
        media_assets = {}
        for s in (asset for screen in all_screens(data) for asset in assets(screen)):
            p = Path(s.get("path", ""))
            if p.is_file():
                name = "media/" + hashlib.sha256(p.read_bytes()).hexdigest()[:20] + p.suffix.lower()
                media_assets[name] = p
                s["path"] = name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("config.json", json.dumps(data, ensure_ascii=False, indent=2))
            for name, p in media_assets.items():
                archive.write(p, name)

    def import_bundle(self, path):
        import zipfile
        with zipfile.ZipFile(path) as archive:
            if sum(i.file_size for i in archive.infolist()) > 250 * 1024 * 1024:
                raise ValueError("The backup exceeds 250 MB")
            data = json.loads(archive.read("config.json"))
            validate(data)
            for s in (asset for screen in all_screens(data) for asset in assets(screen)):
                name = s.get("path", "")
                if name.startswith("media/"):
                    p = Path(name)
                    if ".." in p.parts or len(p.parts) != 2:
                        raise ValueError("Invalid path in the backup")
                    blob = archive.read(name)
                    target = self.media_dir / (hashlib.sha256(blob).hexdigest()[:20] + p.suffix.lower())
                    target.write_bytes(blob)
                    s["path"] = str(target)
            for d in data["devices"]:
                d["enabled"] = False
                d["lighting_restore"] = False
            data["integrations"] = copy.deepcopy(defaults()["integrations"])
            data["startup"] = self.data.get("startup", False)
            shutil.copy2(self.path, self.root / "config.before-import.json")
            self.change(lambda current: (current.clear(), current.update(data)))
