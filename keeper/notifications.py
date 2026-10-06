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
                  "call_seconds": 20, "buzzer_on_call": False}
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
        self.retry_at = 0.

    def tick(self, data, now=None):
        now = time.monotonic() if now is None else now
        self.config = dict(data.get("integrations", {}).get("notifications") or {})
        self.device_id = data.get("active_device")
        if not self.config.get("enabled"):
            self.close()
        elif (self.thread is None or not self.thread.is_alive()) and now >= self.retry_at \
                and not self.engine.stop_event.is_set():
            self.start(now)

    def start(self, now):
        self.stop = threading.Event()
        self.status = "Starting"
        self.thread = threading.Thread(target=self.run, args=(self.stop,), daemon=True, name="divoom-notifications")
        self.thread.start()
        self.retry_at = now + RETRY_SECONDS

    def close(self):
        self.stop.set()
        self.thread = None
        self.retry_at = 0.
        self.status = "Disabled"

    def run(self, stop):
        try:
            backend = self.backend or (windows_backend if os.name == "nt" else linux_backend)
            self.status = "Running"
            for app, summary, body in backend(stop):
                if stop.is_set() or self.engine.stop_event.is_set():
                    break
                self.handle(app, summary, body)
        except Unavailable as error:
            self.status = f"Unavailable ({error})"
        except Exception as error:
            self.status = f"Unavailable ({type(error).__name__})"

    def handle(self, app, summary, body):
        """Filter, format, rate-limit and queue one notification. Never raises."""
        try:
            cfg = self.config
            if not cfg.get("enabled") or not self.device_id:
                return False
            if not app_allowed(app, cfg.get("allow_apps"), cfg.get("deny_apps")):
                return False
            if not self.limiter.allow(cfg.get("per_minute", 6)):
                return False
            teams = {**TEAMS_DEFAULTS, **(cfg.get("teams") or {})}
            found = classify_teams(app, summary, body, teams["patterns"]) if teams["enabled"] else None
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
                                                seconds, kind == "call" and bool(teams["buzzer_on_call"]), TEAMS_COLOR)
                return True
            shown = format_notification(app, summary, body, bool(cfg.get("show_body")))
            if shown is None:
                return False
            self.engine.automations.enqueue(self.device_id, panel, shown[1], shown[0], seconds, False)
            return True
        except Exception as error:
            try:
                self.engine.log(f"Notifications: {type(error).__name__}", "warning")
            except Exception:
                pass
            return False
