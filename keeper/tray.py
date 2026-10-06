"""Qt-free system tray helper built on the optional ``pystray`` dependency."""
import logging
import os
import sys
import threading
from pathlib import Path

log = logging.getLogger("keeper.tray")

TITLE = "Divoom Keeper Studio"
ICON_NAME = "divoom-keeper-studio.png"
WAYLAND_REASON = "no tray support on this Wayland session (install an AppIndicator extension)"


def menu_items(state, t):
    """Pure menu model: list of dicts {id, label, enabled, checked?, separator?}."""
    state = state or {}
    paused = bool(state.get("paused"))
    return [
        {"id": "open", "label": t("Abrir Keeper", "Open Keeper"), "enabled": True},
        {"id": "startup", "label": t("Iniciar con el sistema", "Start with system"), "checked": bool(state.get("startup")), "enabled": True},
        {"id": "pause", "label": t("Reanudar envío", "Resume sending") if paused else t("Pausar envío", "Pause sending"), "enabled": True},
        {"id": "-", "label": "", "enabled": False, "separator": True},
        {"id": "quit", "label": t("Salir", "Quit"), "enabled": True},
    ]


def _icon_paths():
    paths = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        paths.append(Path(bundle) / "packaging" / ICON_NAME)
    here = Path(__file__).resolve().parent
    paths += [here / "packaging" / ICON_NAME, here.parent / "packaging" / ICON_NAME]
    return paths


def _draw_icon(size):
    from PIL import Image, ImageDraw
    scale = 4
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=big * 3 // 16, fill="#101827")
    unit = big / 64
    for i, height in enumerate([21, 32, 43, 32, 21]):
        left = (7 + i * 11) * unit
        top = (64 - height) / 2 * unit
        draw.rounded_rectangle((left, top, left + 7 * unit, top + height * unit), radius=3 * unit, fill="#68e6c4" if i == 2 else "#7199f5")
    return image.resize((size, size), Image.LANCZOS)


def load_icon(size=64):
    from PIL import Image
    for path in _icon_paths():
        try:
            if path.is_file():
                with Image.open(path) as source:
                    return source.convert("RGBA").resize((size, size), Image.LANCZOS)
        except Exception:
            log.warning("could not load tray icon %s", path, exc_info=True)
    return _draw_icon(size)


def _clean(value, limit):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


class Tray:
    def __init__(self, callbacks, state_provider, t=None, backend=None):
        self.callbacks = dict(callbacks or {})
        self.state_provider = state_provider
        self.t = t or (lambda es, en: en)
        self.backend = backend
        self.reason = ""
        self.icon = None
        self.started = False
        self._pystray = None
        self._lock = threading.Lock()
        self._available = None

    def _state(self):
        try:
            return self.state_provider() or {}
        except Exception:
            log.warning("tray state provider failed", exc_info=True)
            return {}

    def _wrap(self, item_id):
        def run(*_):
            try:
                callback = self.callbacks.get(item_id)
                if callback:
                    callback()
            except Exception:
                log.exception("tray action %s failed", item_id)
        return run

    def _menu(self):
        pystray = self._pystray

        def build():
            entries = []
            for item in menu_items(self._state(), self.t):
                if item.get("separator"):
                    entries.append(pystray.Menu.SEPARATOR)
                    continue
                kwargs = {"enabled": bool(item.get("enabled", True))}
                if "checked" in item:
                    kwargs["checked"] = (lambda checked: lambda _item: checked)(item["checked"])
                entries.append(pystray.MenuItem(item["label"], self._wrap(item["id"]), default=item["id"] == "open", **kwargs))
            return tuple(entries)
        return pystray.Menu(build)

    def available(self):
        if self._available is None:
            self._available = self._probe()
        return self._available

    def _probe(self):
        if self.backend:
            os.environ["PYSTRAY_BACKEND"] = str(self.backend)
        try:
            import pystray
        except Exception as error:
            self.reason = f"pystray is not available ({error})"
            return False
        self._pystray = pystray
        linux = sys.platform.startswith("linux")
        if linux and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            self.reason = "no display available for the tray icon"
            return False
        try:
            self.icon = pystray.Icon("divoom-keeper-studio", load_icon(64), TITLE, self._menu())
        except Exception as error:
            self.reason = f"tray could not be created ({error})"
            self.icon = None
            return False
        if linux and os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            name = (type(self.icon).__module__ + " " + type(self.icon).__name__).lower()
            if "appindicator" not in name:
                self.reason = WAYLAND_REASON
                self.icon = None
                return False
        return True

    def start(self):
        with self._lock:
            if self.started:
                return True
            if not self.available():
                return False
            try:
                self.icon.title = self._title()
                if hasattr(self.icon, "run_detached"):
                    self.icon.run_detached()
                else:
                    threading.Thread(target=self.icon.run, name="keeper-tray", daemon=True).start()
                self.started = True
            except Exception as error:
                log.warning("tray failed to start", exc_info=True)
                self.reason = f"tray failed to start ({error})"
                self._available = False
                self.icon = None
            return self.started

    def _title(self):
        return TITLE + (" - " + self.t("en pausa", "paused") if self._state().get("paused") else "")

    def update(self):
        icon = self.icon
        if not self.started or icon is None:
            return
        try:
            icon.title = self._title()
            icon.update_menu()
        except Exception:
            log.warning("tray update failed", exc_info=True)

    def notify(self, title, text):
        icon = self.icon
        if not self.started or icon is None:
            return
        try:
            icon.notify(_clean(text, 200), _clean(title, 64))
        except Exception:
            log.warning("tray notification failed", exc_info=True)

    def stop(self):
        with self._lock:
            icon, was_started = self.icon, self.started
            self.icon, self.started = None, False
        if icon is not None and was_started:
            try:
                icon.stop()
            except Exception:
                log.warning("tray stop failed", exc_info=True)


class NullTray:
    """Same interface as Tray, does nothing; used when no tray is available."""

    def __init__(self, reason="tray unavailable"):
        self.reason = reason
        self.started = False

    def available(self):
        return False

    def start(self):
        return False

    def update(self):
        pass

    def notify(self, title, text):
        pass

    def stop(self):
        pass


def create(callbacks, state_provider, t=None):
    try:
        tray = Tray(callbacks, state_provider, t)
        if tray.available():
            return tray
        return NullTray(tray.reason)
    except Exception as error:
        return NullTray(str(error))
