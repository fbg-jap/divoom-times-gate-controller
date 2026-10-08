"""PC notifications on the Times Gate.

A listener thread receives desktop notifications and turns each into a notice via
``engine.automations.enqueue``, so queueing, expiry and restoring the previous
screen content are reused. Off by default; by default only the app name and the
summary are shown (``show_body`` opts in to the body). Nothing here raises into
the engine.
"""
from __future__ import annotations

import asyncio
import collections
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

TITLE_MAX, TEXT_MAX = 80, 500
RETRY_SECONDS = 30
MATCH_RULE = "type='method_call',interface='org.freedesktop.Notifications',member='Notify'"


class Unavailable(Exception):
    """The platform backend cannot run; the message is shown as the status."""


def clean(value, limit):
    """Strip control characters and newlines, collapse spaces, truncate."""
    if not isinstance(value, str):
        return ""
    text = "".join(" " if c in "\r\n\t" else ("" if unicodedata.category(c) in ("Cc", "Cf") else c)
                   for c in value[:limit * 4])
    return " ".join(text.split())[:limit]


def format_notification(app, summary, body, show_body=False):
    """Return (title, text), or None when there is nothing to show."""
    title = clean(app, TITLE_MAX) or "NOTIFICATION"
    text = clean(summary, TEXT_MAX)
    extra = clean(body, TEXT_MAX) if show_body else ""
    if extra:
        text = clean(f"{text} - {extra}" if text else extra, TEXT_MAX)
    return (title, text) if text else None


_installed = {"at": -1e9, "names": []}


def installed_apps(now=None, environ=None):
    """Names of installed desktop applications (Linux .desktop entries; cached for a minute). Empty elsewhere."""
    if os.name == "nt":
        return []
    now = time.monotonic() if now is None else now
    if now - _installed["at"] < 60:
        return _installed["names"]
    env = os.environ if environ is None else environ
    dirs = [Path(env.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")]
    dirs += [Path(p) for p in (env.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if p]
    names = set()
    for base in dirs:
        try:
            files = list((base / "applications").glob("*.desktop"))[:1500]
        except OSError:
            continue
        for path in files:
            try:
                name, hidden = "", False
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:80]:
                    if line.startswith("[") and line.strip() != "[Desktop Entry]":
                        break
                    if line.startswith("Name=") and not name:
                        name = line[5:].strip()
                    elif line.strip() in ("NoDisplay=true", "Hidden=true"):
                        hidden = True
                if name and not hidden:
                    names.add(clean(name, 64))
            except OSError:
                continue
    _installed.update(at=now, names=sorted(names, key=str.casefold)[:500])
    return _installed["names"]


def color_of(value, fallback):
    return value if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) else fallback


def app_allowed(app, allow, deny):
    """Case-insensitive; deny wins; an empty allow list allows every app."""
    name = str(app or "").casefold()
    if name in {str(a).casefold() for a in deny or []}:
        return False
    allowed = {str(a).casefold() for a in allow or []}
    return not allowed or name in allowed


TEAMS_DEFAULTS = {"enabled": False, "patterns": ["microsoft teams", "msteams", "teams-for-linux", "teams.microsoft.com",
                                                  "teams.cloud.microsoft", "teams.live.com"],
                  "show_preview": False, "chats": True, "mentions": True, "calls": True, "panel": 0, "seconds": 0,
                  "call_seconds": 20, "buzzer_on_call": False, "color": "#6264a7"}
NOTICE_COLOR = "#ff7a3d"
TEAMS_COLOR = "#6264a7"
CALL_WORDS = ("calling", "incoming call", "is calling", "meeting started", "joined the meeting", "ringer", "llamando", "ruft an")
MENTION_WORDS = ("mentioned", "nævnte", "mencionó", "erwähnt")
# An @-mention starts a word; an @ inside an address such as ana@example.com is not one.
AT_MENTION = re.compile(r"(?<!\S)@\S")


def classify_teams(app, summary, body, patterns):
    """None when this is not a Teams notification, else {'kind': call|mention|chat, 'sender', 'preview'}."""
    try:
        if not all(isinstance(v, str) for v in (app, summary, body)) or not isinstance(patterns, (list, tuple)):
            return None
        sender, preview = clean(summary, TEXT_MAX), clean(body, TEXT_MAX)
        haystack = f"{clean(app, TITLE_MAX)} {sender} {preview}".casefold()
        if not any(isinstance(p, str) and p.strip() and p.strip().casefold() in haystack for p in patterns):
            return None
        text = f"{sender} {preview}".casefold()
        kind = "call" if any(w in text for w in CALL_WORDS) else \
            "mention" if any(w in text for w in MENTION_WORDS) or AT_MENTION.search(text) else "chat"
        cuts = [i for i in (sender.casefold().find(" " + w) for w in CALL_WORDS[:3] + MENTION_WORDS[:1]) if i > 0]
        sender = sender[:min(cuts)] if cuts else sender
        for suffix in (" (via teams)", " in "):
            cut = sender.casefold().rfind(suffix)
            if cut > 0:
                sender = sender[:cut]
        return {"kind": kind, "sender": sender[:TITLE_MAX - 8].strip() or "Teams", "preview": preview}
    except Exception:
        return None


class RateLimiter:
    """Sliding window; extra notifications inside the window are dropped."""
    def __init__(self, clock=time.monotonic):
        self.clock, self.stamps = clock, collections.deque()

    def allow(self, per_minute):
        now = self.clock()
        while self.stamps and now - self.stamps[0] >= 60:
            self.stamps.popleft()
        if len(self.stamps) >= max(int(per_minute), 1):
            return False
        self.stamps.append(now)
        return True


def new_toasts(items, seen):
    """Dedup helper for pollers: items are (id, app, summary, body); returns the unseen ones.
    ``seen`` is updated in place and pruned to the ids still present."""
    fresh = [item for item in items if item[0] not in seen]
    seen.clear()
    seen.update(item[0] for item in items)
    return [(app, summary, body) for _, app, summary, body in fresh]


def linux_backend(stop):
    """Yield (app, summary, body) from the session bus using the D-Bus Monitoring interface."""
    try:
        from jeepney import DBusAddress, HeaderFields, new_method_call
        from jeepney.io.blocking import open_dbus_connection
    except ImportError:
        raise Unavailable("jeepney not installed")
    try:
        connection = open_dbus_connection(bus="SESSION")
    except Exception as error:
        raise Unavailable("no session D-Bus: " + type(error).__name__)
    try:
        bus = DBusAddress("/org/freedesktop/DBus", bus_name="org.freedesktop.DBus",
                          interface="org.freedesktop.DBus.Monitoring")
        try:
            connection.send_and_get_reply(new_method_call(bus, "BecomeMonitor", "asu", ([MATCH_RULE], 0)))
        except Exception as error:
            raise Unavailable("monitoring refused: " + type(error).__name__)
        while not stop.is_set():
            try:
                message = connection.receive(timeout=1)
            except TimeoutError:
                continue
            if message.header.fields.get(HeaderFields.member) != "Notify":
                continue
            body = message.body
            if len(body) >= 5 and all(isinstance(body[i], str) for i in (0, 3, 4)):
                yield body[0], body[3], body[4]   # app_name, summary, body
    finally:
        connection.close()


def windows_backend(stop):
    """Poll UserNotificationListener every ~2 s.

    UNVERIFIED: written from the winrt API but never run on a real Windows machine.
    """
    try:
        import winrt.runtime
        from winrt.windows.ui.notifications import NotificationKinds
        from winrt.windows.ui.notifications.management import (
            UserNotificationListener, UserNotificationListenerAccessStatus)
    except ImportError:
        raise Unavailable("winrt not installed")

    async def access():
        listener = UserNotificationListener.current
        status = await listener.request_access_async()
        if status != UserNotificationListenerAccessStatus.ALLOWED:
            raise Unavailable("notification access not granted in Windows settings")
        return listener

    async def poll(listener):
        items = []
        for n in await listener.get_notifications_async(NotificationKinds.TOASTS):
            binding = n.notification.visual.get_binding("ToastGeneric")
            texts = [t.text for t in binding.get_text_elements()] if binding else []
            items.append((n.id, n.app_info.display_info.display_name,
                          texts[0] if texts else "", " ".join(texts[1:])))
        return items

    try:
        winrt.runtime.init_apartment(winrt.runtime.ApartmentType.MULTI_THREADED)
    except Exception:
        pass
    loop = asyncio.new_event_loop()
    try:
        try:
            listener = loop.run_until_complete(access())
        except Unavailable:
            raise
        except Exception as error:
            raise Unavailable("notification access failed: " + type(error).__name__)
        seen, first = set(), True
        while not stop.is_set():
            fresh = new_toasts(loop.run_until_complete(poll(listener)), seen)
            if not first:        # what is already in the action center is not new
                yield from fresh
            first = False
            stop.wait(2)
    finally:
        loop.close()


class NotificationService:
    """Owned by the Bridge. ``tick`` reconciles the thread with the current config."""
    def __init__(self, engine, backend=None):
        self.engine = engine
        self.backend = backend
        self.thread = None
        self.stop = threading.Event()
        self.config, self.device_id = {}, None
        self.limiter = RateLimiter()
        self.status = "Disabled"
        self.seen_apps = collections.OrderedDict()   # app names that sent a notification, most recent last
        self.logged = "Disabled"
        self.retry_at = 0.

    def set_status(self, value):
        self.status = value
        if value != "Running":   # "Running" is set before the backend has connected; tick() logs it once it has held
            self.log_change()

    def log_change(self):
        """Log each status change once (never the content of a notification)."""
        value = self.status
        if value == "Starting" or value == self.logged:
            return
        self.logged = value
        try:
            self.engine.log("Notification listener: " + value, "warning" if value.startswith("Unavailable") else "info")
        except Exception:
            pass

    def tick(self, data, now=None):
        now = time.monotonic() if now is None else now
        self.config = dict(data.get("integrations", {}).get("notifications") or {})
        self.device_id = data.get("active_device")
        if not (self.config.get("enabled") or (self.config.get("teams") or {}).get("enabled")):
            self.close()
        elif (self.thread is None or not self.thread.is_alive()) and now >= self.retry_at \
                and not self.engine.stop_event.is_set():
            self.start(now)
        self.log_change()

    def start(self, now):
        self.stop = threading.Event()
        self.set_status("Starting")
        self.thread = threading.Thread(target=self.run, args=(self.stop,), daemon=True, name="divoom-notifications")
        self.thread.start()
        self.retry_at = now + RETRY_SECONDS

    def close(self):
        self.stop.set()
        self.thread = None
        self.retry_at = 0.
        self.set_status("Disabled")

    def run(self, stop):
        try:
            backend = self.backend or (windows_backend if os.name == "nt" else linux_backend)
            self.set_status("Running")
            for app, summary, body in backend(stop):
                if stop.is_set() or self.engine.stop_event.is_set():
                    break
                self.handle(app, summary, body)
        except Unavailable as error:
            self.set_status(f"Unavailable ({error})")
        except Exception as error:
            self.set_status(f"Unavailable ({type(error).__name__})")

    def remember_app(self, app):
        name = clean(app, 64)
        if name:
            for other in [k for k in self.seen_apps if k.casefold() == name.casefold()]:
                del self.seen_apps[other]
            self.seen_apps[name] = True
            while len(self.seen_apps) > 100:
                self.seen_apps.popitem(last=False)

    def known_apps(self):
        """{seen: names that sent a notification, installed: installed application names} for the app pickers."""
        return {"seen": sorted(self.seen_apps, key=str.casefold), "installed": installed_apps()}

    def handle(self, app, summary, body):
        """Filter, format, rate-limit and queue one notification. Never raises."""
        try:
            self.remember_app(app)
            cfg = self.config
            teams = {**TEAMS_DEFAULTS, **(cfg.get("teams") or {})}
            general = bool(cfg.get("enabled"))
            if not (general or teams["enabled"]) or not self.device_id:
                return False
            if not app_allowed(app, [], cfg.get("deny_apps")):
                return False
            # A Teams notification is recognised by its own patterns, so the allow list (meant for general notifications) does not apply to it.
            found = classify_teams(app, summary, body, teams["patterns"]) if teams["enabled"] else None
            if not found and not (general and app_allowed(app, cfg.get("allow_apps"), [])):
                return False   # Teams alone: everything that is not Teams is dropped, and does not use up the rate limit
            if not self.limiter.allow(cfg.get("per_minute", 6)):
                return False
            panel = min(max(int(cfg.get("panel", 1)), 1), 5) - 1
            seconds = min(max(int(cfg.get("seconds", 8)), 5), 60)
            if found:
                kind = found["kind"]
                if not teams[{"chat": "chats", "mention": "mentions", "call": "calls"}[kind]]:
                    return False
                preview = found["preview"] if teams["show_preview"] else ""
                text = {"chat": preview or "New message", "mention": clean(f"Mentioned you {preview}", TEXT_MAX),
                        "call": "Incoming call"}[kind]
                if teams["panel"]:
                    panel = min(max(int(teams["panel"]), 1), 5) - 1
                if kind == "call":
                    seconds = min(max(int(teams["call_seconds"]), 5), 60)
                elif teams["seconds"]:
                    seconds = min(max(int(teams["seconds"]), 5), 60)
                self.engine.automations.enqueue(self.device_id, panel, text, clean("Teams · " + found["sender"], TITLE_MAX),
                                                seconds, kind == "call" and bool(teams["buzzer_on_call"]),
                                                color_of(teams.get("color"), TEAMS_COLOR), cfg.get("border", True) is not False,
                                                cfg.get("blink", True) is not False)
                return True
            shown = format_notification(app, summary, body, bool(cfg.get("show_body")))
            if shown is None:
                return False
            self.engine.automations.enqueue(self.device_id, panel, shown[1], shown[0], seconds, False,
                                            color_of(cfg.get("color"), NOTICE_COLOR), cfg.get("border", True) is not False,
                                            cfg.get("blink", True) is not False)
            return True
        except Exception as error:
            try:
                self.engine.log(f"Notifications: {type(error).__name__}", "warning")
            except Exception:
                pass
            return False
