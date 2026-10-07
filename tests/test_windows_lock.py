import ctypes
import sys
import threading
import time
import unittest
from unittest.mock import patch

from keeper.config import slot
from keeper import engine as engine_module, windows_sources
from keeper.engine import Engine
from keeper.windows_sources import (NOTIFY_FOR_THIS_SESSION, SessionLockWatcher, WM_CLOSE, WM_DESTROY,
    WM_WTSSESSION_CHANGE, session_event_state)
from test_core import FixtureCase


class Fn:
    def __init__(self, result=1, on_call=None):
        self.result, self.on_call, self.calls = result, on_call, []

    def __call__(self, *args):
        self.calls.append(args)
        return self.on_call(*args) if self.on_call else self.result


class FakeWin:
    """Fake ctypes.windll: records calls; GetMessageW blocks until PostMessageW (stop) then returns 0."""
    def __init__(self, register=1, create=0x1234, wts=1, last_error=0):
        self.quit = threading.Event()
        self.wndproc = None
        self.user32 = type("U", (), {})()
        self.wtsapi32 = type("W", (), {})()
        self.kernel32 = type("K", (), {})()

        def reg(ref):
            self.wndproc = ref._obj.lpfnWndProc
            return register
        self.user32.RegisterClassW = Fn(on_call=reg)
        self.user32.CreateWindowExW = Fn(create)
        self.user32.GetMessageW = Fn(on_call=lambda *a: (self.quit.wait(5), 0)[1])
        self.user32.PostMessageW = Fn(on_call=lambda *a: self.quit.set() or 1)
        for name in ("DefWindowProcW", "DestroyWindow", "PostQuitMessage", "TranslateMessage", "DispatchMessageW"):
            setattr(self.user32, name, Fn(0))
        self.wtsapi32.WTSRegisterSessionNotification = Fn(wts)
        self.wtsapi32.WTSUnRegisterSessionNotification = Fn(1)
        self.kernel32.GetModuleHandleW = Fn(1)
        self.kernel32.GetLastError = Fn(last_error)


def patched(win):
    return patch.multiple(ctypes, windll=win, create=True)


class SessionEventState(unittest.TestCase):
    def test_table(self):
        for code, expected in ((7, True), (8, False), (0, None), (1, None), (2, None), (3, None), (9, None)):
            self.assertIs(session_event_state(code), expected, code)


class Watcher(unittest.TestCase):
    def test_import_without_windll(self):
        self.assertTrue(hasattr(windows_sources, "SessionLockWatcher"))
        self.assertFalse(hasattr(ctypes, "windll") and sys.platform != "win32")

    def test_registers_and_dispatches(self):
        win = FakeWin()
        with patched(win):
            watcher = SessionLockWatcher()
            watcher.start()
            try:
                self.assertTrue(watcher.available)
                self.assertIsNone(watcher.locked)
                self.assertEqual(win.wtsapi32.WTSRegisterSessionNotification.calls, [(0x1234, NOTIFY_FOR_THIS_SESSION)])
                self.assertEqual(win.user32.CreateWindowExW.calls[0][8], -3)
                proc = win.wndproc
                proc(0x1234, WM_WTSSESSION_CHANGE, 7, 1)
                self.assertTrue(watcher.locked)
                proc(0x1234, WM_WTSSESSION_CHANGE, 5, 1)
                self.assertTrue(watcher.locked)
                proc(0x1234, WM_WTSSESSION_CHANGE, 8, 1)
                self.assertFalse(watcher.locked)
                proc(0x1234, 0x0001, 0, 0)
                self.assertEqual(len(win.user32.DefWindowProcW.calls), 1)
                proc(0x1234, WM_CLOSE, 0, 0)
                self.assertEqual(win.user32.DestroyWindow.calls, [(0x1234,)])
                proc(0x1234, WM_DESTROY, 0, 0)
                self.assertEqual(len(win.wtsapi32.WTSUnRegisterSessionNotification.calls), 1)
                self.assertEqual(win.user32.PostQuitMessage.calls, [(0,)])
            finally:
                watcher.stop()

    def test_stop_posts_close_unregisters_and_joins(self):
        win = FakeWin()
        with patched(win):
            watcher = SessionLockWatcher()
            watcher.start()
            thread = watcher._thread
            self.assertTrue(thread.is_alive() and thread.daemon)
            watcher.stop()
            self.assertEqual(win.user32.PostMessageW.calls, [(0x1234, WM_CLOSE, 0, 0)])
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(win.wtsapi32.WTSUnRegisterSessionNotification.calls), 1)
            self.assertFalse(watcher.available)

    def test_start_is_idempotent_and_stop_without_start(self):
        SessionLockWatcher().stop()
        win = FakeWin()
        with patched(win):
            watcher = SessionLockWatcher()
            watcher.start(); watcher.start()
            watcher.stop()
        self.assertEqual(len(win.user32.RegisterClassW.calls), 1)

    def test_class_already_exists_is_success_and_start_after_stop_works(self):
        win = FakeWin(register=0, last_error=1410)
        with patched(win):
            watcher = SessionLockWatcher()
            watcher.start()
            self.assertTrue(watcher.available, watcher.error)
            watcher.stop()
            self.assertFalse(watcher.available)
            win.quit.clear()
            watcher.start()
            self.assertTrue(watcher.available, watcher.error)
            self.assertTrue(watcher._thread.is_alive())
            watcher.stop()
        self.assertEqual(len(win.user32.CreateWindowExW.calls), 2)
        self.assertEqual(len(win.wtsapi32.WTSRegisterSessionNotification.calls), 2)

    def test_message_pump_functions_get_argtypes(self):
        win = FakeWin()
        with patched(win):
            watcher = SessionLockWatcher()
            watcher.start()
            watcher.stop()
        for name in ("TranslateMessage", "DispatchMessageW"):
            self.assertTrue(getattr(win.user32, name).argtypes, name)
            self.assertIsNotNone(getattr(win.user32, name).restype, name)

    def test_stop_right_after_start_waits_for_the_window(self):
        win = FakeWin()
        release = threading.Event()
        win.user32.CreateWindowExW = Fn(on_call=lambda *a: (release.wait(5), 0x1234)[1])
        with patched(win):
            watcher = SessionLockWatcher()
            thread = threading.Thread(target=watcher.start, daemon=True)
            thread.start()
            deadline = time.monotonic() + 5
            while watcher._thread is None and time.monotonic() < deadline:
                time.sleep(.01)
            threading.Timer(.2, release.set).start()
            watcher.stop()  # called before the hwnd exists
            thread.join(5)
            self.assertEqual(win.user32.PostMessageW.calls, [(0x1234, WM_CLOSE, 0, 0)])
            self.assertIsNone(watcher._thread)

    def failing(self, win, message):
        with patched(win):
            watcher = SessionLockWatcher()
            watcher.start()
            watcher.stop()
        self.assertFalse(watcher.available)
        self.assertIn(message, watcher.error)
        self.assertIsNone(watcher.locked)

    def test_failures(self):
        self.failing(FakeWin(register=0), "RegisterClassW")
        self.failing(FakeWin(create=0), "CreateWindowExW")
        self.failing(FakeWin(wts=0), "WTSRegisterSessionNotification")

    def test_windll_missing(self):
        watcher = SessionLockWatcher()
        with patch.object(ctypes, "windll", None, create=True):
            watcher.start()
            watcher.stop()
        self.assertFalse(watcher.available)
        self.assertTrue(watcher.error)

    def test_api_exception_does_not_raise(self):
        win = FakeWin()
        win.user32.RegisterClassW = Fn(on_call=lambda ref: 1 / 0)
        self.failing(win, "failed")


class FakeWatcher:
    def __init__(self, locked=None):
        self.locked, self.started, self.stopped = locked, 0, 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


class EngineWiring(FixtureCase):
    def profile(self):
        scene = {"id": "s1", "name": "Lock", "screens": [slot("text", text="L") for _ in range(5)]}
        rule = {"id": "r1", "device_id": self.d["id"], "enabled": True, "trigger": "locked", "scene_id": "s1"}
        self.store.change(lambda data: data.update(scenes=[scene], profiles=[rule]))

    def test_non_windows_has_no_watcher(self):
        with patch.object(engine_module, "uses_session_watcher", lambda demo: False):
            self.assertIsNone(Engine(self.store).session_watcher)

    def test_demo_has_no_watcher(self):
        with patch.object(engine_module.sys, "platform", "win32"):
            self.assertFalse(engine_module.uses_session_watcher(True))
            self.assertTrue(engine_module.uses_session_watcher(False))
        self.assertIsNone(Engine(self.store, demo=True).session_watcher)

    def test_windows_tick_sets_locked(self):
        with patch.object(engine_module, "uses_session_watcher", lambda demo: True), \
                patch.object(windows_sources, "SessionLockWatcher", FakeWatcher):
            engine = Engine(self.store)
        watcher = engine.session_watcher
        self.assertIsInstance(watcher, FakeWatcher)
        engine.tick()
        self.assertEqual(watcher.started, 0)  # lazy: no locked profile yet
        self.profile()
        engine.tick()
        self.assertEqual(watcher.started, 1)
        self.assertFalse(engine.automations.locked)  # unknown state leaves the flag alone
        watcher.locked = True
        engine.tick()
        self.assertTrue(engine.automations.locked)
        watcher.locked = False
        engine.tick()
        self.assertFalse(engine.automations.locked)

    def test_linux_probe_unchanged(self):
        class Probe:
            def read(self):
                return True, ""
        engine = Engine(self.store)
        engine.session_probe = Probe()
        self.profile()
        engine.tick()
        self.assertTrue(engine.automations.locked)


if __name__ == "__main__":
    unittest.main()
