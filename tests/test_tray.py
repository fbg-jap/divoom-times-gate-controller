import inspect
import logging
import os
import sys
import types
import unittest
from unittest.mock import patch

from keeper import tray


def es_only(es, en):
    return es


def en_only(es, en):
    return en


class FakeMenu:
    SEPARATOR = object()

    def __init__(self, items):
        self.items = items

    def build(self):
        return self.items() if callable(self.items) else self.items


class FakeMenuItem:
    def __init__(self, text, action, checked=None, enabled=True, default=False):
        self.text, self.action, self.checked, self.enabled, self.default = text, action, checked, enabled, default


def fake_pystray(raise_on_init=False, backend_module=None):
    module = types.ModuleType("pystray")
    module.Menu, module.MenuItem = FakeMenu, FakeMenuItem

    class Icon:
        instances = []

        def __init__(self, name, icon, title, menu):
            if raise_on_init:
                raise RuntimeError("boom")
            self.name, self.icon, self.title, self.menu = name, icon, title, menu
            self.calls = []
            Icon.instances.append(self)

        def run_detached(self):
            self.calls.append("run_detached")

        def update_menu(self):
            self.calls.append("update_menu")

        def notify(self, message, title):
            self.calls.append(("notify", message, title))

        def stop(self):
            self.calls.append("stop")

    if backend_module:
        Icon.__module__ = backend_module
    module.Icon = Icon
    return module


ENV = {"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}


class MenuModelTests(unittest.TestCase):
    def test_labels_and_order(self):
        items = tray.menu_items({"startup": True, "paused": False}, en_only)
        self.assertEqual([i["id"] for i in items], ["open", "startup", "pause", "-", "quit"])
        self.assertEqual([i["label"] for i in items if not i.get("separator")], ["Open Keeper", "Start with system", "Pause sending", "Quit"])
        self.assertTrue(items[3]["separator"])
        self.assertEqual(items[-1]["id"], "quit")
        spanish = tray.menu_items({}, es_only)
        self.assertEqual(spanish[0]["label"], "Abrir Keeper")
        self.assertEqual(spanish[-1]["label"], "Salir")

    def test_checkbox_and_pause_toggle(self):
        on = tray.menu_items({"startup": True, "paused": True}, en_only)
        off = tray.menu_items({"startup": False, "paused": False}, en_only)
        self.assertIs(on[1]["checked"], True)
        self.assertIs(off[1]["checked"], False)
        self.assertEqual(on[2]["label"], "Resume sending")
        self.assertEqual(off[2]["label"], "Pause sending")
        self.assertNotIn("checked", off[0])
        self.assertTrue(all("enabled" in i for i in on))


class IconTests(unittest.TestCase):
    def test_load_icon_size_and_mode(self):
        for size in (32, 64):
            image = tray.load_icon(size)
            self.assertEqual(image.size, (size, size))
            self.assertEqual(image.mode, "RGBA")

    def test_fallback_drawing_when_png_missing(self):
        with patch.object(tray, "_icon_paths", return_value=[]):
            image = tray.load_icon(64)
        self.assertEqual((image.size, image.mode), ((64, 64), "RGBA"))
        self.assertEqual(image.getpixel((32, 32))[:3], (0x68, 0xe6, 0xc4))
        self.assertEqual(image.getpixel((32, 4))[:3], (0x10, 0x18, 0x27))


class TrayTests(unittest.TestCase):
    def make(self, callbacks=None, state=None, module=None, env=None, **kwargs):
        self.module = module or fake_pystray()
        self.state = state if state is not None else {"startup": False, "paused": False}
        for p in (patch.dict(sys.modules, {"pystray": self.module}), patch.dict(os.environ, env or ENV)):
            p.start()
            self.addCleanup(p.stop)
        return tray.Tray(callbacks or {}, lambda: self.state, en_only, **kwargs)

    def test_start_builds_icon_and_runs_detached(self):
        t = self.make()
        self.assertTrue(t.start())
        icon = self.module.Icon.instances[-1]
        self.assertEqual(icon.title, "Divoom Keeper Studio")
        self.assertEqual(icon.icon.size, (64, 64))
        self.assertIn("run_detached", icon.calls)
        self.assertTrue(t.start())
        self.assertEqual(icon.calls.count("run_detached"), 1)

    def test_menu_callbacks_fire_and_checked_reflects_state(self):
        fired = []
        t = self.make({"open": lambda: fired.append("open"), "quit": lambda: fired.append("quit")}, {"startup": True, "paused": False})
        t.start()
        menu = self.module.Icon.instances[-1].menu
        entries = menu.build()
        self.assertIs(entries[3], FakeMenu.SEPARATOR)
        self.assertTrue(entries[0].default)
        self.assertTrue(entries[1].checked(entries[1]))
        entries[0].action(None, entries[0])
        entries[-1].action()
        self.assertEqual(fired, ["open", "quit"])
        self.state = {"startup": False, "paused": True}
        entries = menu.build()
        self.assertFalse(entries[1].checked(entries[1]))
        self.assertEqual(entries[2].text, "Resume sending")

    def test_callback_exceptions_are_swallowed_and_logged(self):
        def bad():
            raise ValueError("nope")
        t = self.make({"pause": bad})
        t.start()
        entries = self.module.Icon.instances[-1].menu.build()
        with self.assertLogs("keeper.tray", level=logging.ERROR) as logs:
            entries[2].action()
        self.assertIn("pause", logs.output[0])

    def test_update_refreshes_title_and_menu(self):
        t = self.make()
        t.start()
        icon = self.module.Icon.instances[-1]
        self.state = {"paused": True}
        t.update()
        self.assertIn("update_menu", icon.calls)
        self.assertIn("paused", icon.title)

    def test_notify_caps_text(self):
        t = self.make()
        t.start()
        t.notify("T" * 200, "line\none " + "x" * 500)
        _, message, title = self.module.Icon.instances[-1].calls[-1]
        self.assertLessEqual(len(message), 200)
        self.assertLessEqual(len(title), 64)
        self.assertNotIn("\n", message)

    def test_noop_when_unavailable(self):
        t = self.make(module=fake_pystray(raise_on_init=True))
        t.notify("a", "b")
        t.update()
        t.stop()
        self.assertFalse(t.start())
        self.assertIn("boom", t.reason)

    def test_stop_idempotent(self):
        t = self.make()
        t.start()
        icon = self.module.Icon.instances[-1]
        t.stop()
        t.stop()
        self.assertEqual(icon.calls.count("stop"), 1)
        t.notify("a", "b")
        self.assertNotIn("notify", [c[0] for c in icon.calls if isinstance(c, tuple)])

    def test_import_error_reason(self):
        with patch.dict(sys.modules, {"pystray": None}):
            t = tray.Tray({}, dict, en_only)
            self.assertFalse(t.available())
            self.assertFalse(t.start())
            self.assertIn("pystray", t.reason)

    def test_wayland_with_xorg_backend_unavailable(self):
        t = self.make(module=fake_pystray(backend_module="pystray._xorg"), env={"DISPLAY": ":0", "XDG_SESSION_TYPE": "wayland"})
        with patch.object(sys, "platform", "linux"):
            self.assertFalse(t.available())
        self.assertEqual(t.reason, tray.WAYLAND_REASON)

    def test_wayland_with_appindicator_is_available(self):
        t = self.make(module=fake_pystray(backend_module="pystray._appindicator"), env={"WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland"})
        with patch.object(sys, "platform", "linux"):
            self.assertTrue(t.available())

    def test_linux_without_display_unavailable(self):
        t = self.make()
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "platform", "linux"):
            self.assertFalse(t.available())
        self.assertIn("display", t.reason)


class FactoryTests(unittest.TestCase):
    def test_create_returns_null_tray_with_reason(self):
        with patch.dict(sys.modules, {"pystray": None}):
            result = tray.create({}, dict, en_only)
        self.assertIsInstance(result, tray.NullTray)
        self.assertTrue(result.reason)
        self.assertFalse(result.start())

    def test_create_returns_tray_when_available(self):
        with patch.dict(sys.modules, {"pystray": fake_pystray()}), patch.dict(os.environ, ENV):
            self.assertIsInstance(tray.create({}, dict, en_only), tray.Tray)

    def test_null_tray_interface_parity(self):
        def public(cls):
            return {n for n, _ in inspect.getmembers(cls, inspect.isfunction) if not n.startswith("_")}
        self.assertEqual(public(tray.NullTray), public(tray.Tray))
        for name in ("available", "start", "update", "notify", "stop"):
            self.assertEqual(inspect.signature(getattr(tray.NullTray, name)), inspect.signature(getattr(tray.Tray, name)))


if __name__ == "__main__":
    unittest.main()


class StartTrayAdapterTests(unittest.TestCase):
    def setUp(self):
        self.module = fake_pystray()
        for p in (patch.dict(sys.modules, {"pystray": self.module}), patch.dict(os.environ, ENV)):
            p.start()
            self.addCleanup(p.stop)
        self.calls, self.startup = [], {"on": False}

    def callbacks(self, **extra):
        return {"open": lambda: self.calls.append("open"), "quit": lambda: self.calls.append("quit"),
                "startup_enabled": lambda: self.startup["on"],
                "set_startup": lambda value: (self.startup.__setitem__("on", value), self.calls.append(("startup", value))), **extra}

    def entries(self):
        return self.module.Icon.instances[-1].menu.build()

    def test_menu_has_no_pause_entry_when_the_host_cannot_pause(self):
        started = tray.start_tray(self.callbacks())
        self.assertIsNotNone(started)
        self.assertEqual([e.text for e in self.entries() if e is not FakeMenu.SEPARATOR], ["Open Keeper", "Start with system", "Quit"])

    def test_open_quit_and_startup_toggle_reach_the_shell(self):
        tray.start_tray(self.callbacks())
        by_text = {e.text: e for e in self.entries() if e is not FakeMenu.SEPARATOR}
        by_text["Open Keeper"].action()
        by_text["Quit"].action()
        by_text["Start with system"].action()
        self.assertEqual(self.calls, ["open", "quit", ("startup", True)])
        checked = {e.text: e.checked(e) for e in self.entries() if e is not FakeMenu.SEPARATOR and e.checked is not None}
        self.assertEqual(checked, {"Start with system": True})   # refreshed state shows the new setting
        {e.text: e for e in self.entries() if e is not FakeMenu.SEPARATOR}["Start with system"].action()
        self.assertEqual(self.calls[-1], ("startup", False))

    def test_pause_entry_appears_when_a_pause_callback_exists(self):
        tray.start_tray(self.callbacks(pause=lambda: self.calls.append("pause")))
        texts = [e.text for e in self.entries() if e is not FakeMenu.SEPARATOR]
        self.assertIn("Pause sending", texts)

    def test_returns_none_when_no_tray_is_available(self):
        with patch.dict(sys.modules, {"pystray": None}):
            self.assertIsNone(tray.start_tray(self.callbacks()))
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}):
            module = fake_pystray()
            with patch.dict(sys.modules, {"pystray": module}):
                self.assertIsNone(tray.start_tray(self.callbacks()))   # xorg backend on Wayland

    def test_a_failing_startup_state_never_breaks_the_menu(self):
        def boom():
            raise RuntimeError("x")
        started = tray.start_tray({"open": lambda: None, "quit": lambda: None, "startup_enabled": boom, "set_startup": lambda v: None})
        self.assertIsNotNone(started)
        self.assertEqual(len(self.entries()), 4)   # open, startup, separator, quit
