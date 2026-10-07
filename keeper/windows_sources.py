"""Optional Windows readers. Fixed PowerShell programs; no user text is executed."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import threading
import time


def read_media():
    import asyncio
    import winrt.runtime
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
    from winrt.windows.storage.streams import DataReader
    import winrt.windows.foundation
    async def sample():
        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        session = manager.get_current_session()
        if session is None:
            return {"title": "", "artist": "", "status": "Nothing playing", "art": ""}
        properties = await session.try_get_media_properties_async()
        result = {"title": properties.title, "artist": properties.artist,
                  "status": session.get_playback_info().playback_status.name.title(), "art": ""}
        if properties.thumbnail:
            stream = None
            reader = None
            try:
                stream = await properties.thumbnail.open_read_async()
                if stream.size <= 2097152:
                    reader = DataReader(stream.get_input_stream_at(0))
                    count = await reader.load_async(stream.size)
                    raw = bytearray(count)
                    reader.read_bytes(raw)
                    result["art"] = base64.b64encode(raw).decode("ascii")
            except (OSError, ValueError):
                pass
            finally:
                if reader:
                    reader.close()
                if stream:
                    stream.close()
        return result
    async def bounded():
        return await asyncio.wait_for(sample(), 8)
    winrt.runtime.init_apartment(winrt.runtime.ApartmentType.MULTI_THREADED)
    try:
        return asyncio.run(bounded())
    finally:
        winrt.runtime.uninit_apartment()


HARDWARE_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$sensors = @(Get-CimInstance -Namespace 'root\LibreHardwareMonitor' -ClassName Sensor |
    Select-Object Identifier,Name,SensorType,Value)
ConvertTo-Json -InputObject $sensors -Compress
'''


def powershell_json(script):
    if os.name != "nt":
        raise RuntimeError("This source requires Windows")
    executable = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "System32/WindowsPowerShell/v1.0/powershell.exe")
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, timeout=12, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError("Windows source unavailable")
    return json.loads(result.stdout.decode("utf-8-sig"))


class AsyncProbe:
    """Reading Windows metadata never blocks image uploads or the GUI."""
    def __init__(self, script, interval=5, stale=30):
        self.script, self.interval, self.stale = script, interval, stale
        self.lock = threading.Lock()
        self.value, self.error = None, "Waiting for first reading"
        self.started, self.updated, self.running = -1e12, -1e12, False
        self.first = threading.Event()

    def read(self, wait=0.0):
        """Latest (value, error). `wait` > 0 holds the caller for at most that many seconds until the first sample
        has finished, so a widget's first draw shows data instead of a placeholder; later reads never wait."""
        with self.lock:
            now = time.monotonic()
            if not self.running and now - self.started >= self.interval:
                self.started, self.running = now, True
                threading.Thread(target=self._sample, daemon=True, name="keeper-windows-reader").start()
        if wait > 0 and not self.first.is_set():
            self.first.wait(wait)
        with self.lock:
            value = self.value if time.monotonic() - self.updated < self.stale else None
            return value, self.error

    def _sample(self):
        try:
            value = self.script() if callable(self.script) else powershell_json(self.script)
            with self.lock:
                self.value, self.updated, self.error = value, time.monotonic(), ""
        except Exception as error:
            with self.lock:
                self.value, self.error = None, str(error)
        finally:
            with self.lock:
                self.running = False
            self.first.set()


WM_CLOSE, WM_DESTROY, WM_WTSSESSION_CHANGE = 0x0010, 0x0002, 0x02B1
WTS_SESSION_LOCK, WTS_SESSION_UNLOCK = 0x7, 0x8
NOTIFY_FOR_THIS_SESSION = 0
HWND_MESSAGE = -3
ERROR_CLASS_ALREADY_EXISTS = 1410


def session_event_state(wparam):
    """WM_WTSSESSION_CHANGE wParam -> True (locked), False (unlocked) or None (irrelevant code)."""
    if wparam == WTS_SESSION_LOCK:
        return True
    if wparam == WTS_SESSION_UNLOCK:
        return False
    return None


class SessionLockWatcher:
    """Qt-free Windows session lock detection: a daemon thread owns a hidden message-only window registered for
    WTS session notifications. `locked` stays None until the first lock/unlock event (the initial state is not
    queried). Failures never raise; they set available=False and `error`."""

    def __init__(self):
        self.locked = None
        self.available = False
        self.error = ""
        self._thread = None
        self._hwnd = None
        self._registered = False
        self._ready = threading.Event()
        self._guard = threading.Lock()
        self._api = None
        self._refs = []

    def start(self):
        with self._guard:
            if self._thread is not None:
                if self._thread.is_alive():
                    return
                self._thread = None  # a stopped (or failed) watcher can be started again
            self._ready.clear()
            self._hwnd, self._registered, self.locked, self.available = None, False, None, False
            self.error = "Starting"
            self._thread = threading.Thread(target=self._run, daemon=True, name="keeper-session-lock")
            self._thread.start()
        self._ready.wait(3)

    def stop(self, timeout=3):
        with self._guard:
            thread = self._thread
        if thread is None:
            return
        self._ready.wait(timeout)  # the window may not exist yet; _ready is set once it does (or once the thread gave up)
        with self._guard:
            hwnd, api = self._hwnd, self._api
        try:
            if hwnd and api:
                api["user32"].PostMessageW(hwnd, WM_CLOSE, 0, 0)
        except Exception as error:
            self.error = str(error)
        thread.join(timeout)
        if not thread.is_alive():
            with self._guard:
                if self._thread is thread:
                    self._thread = None

    def _fail(self, message):
        self.available, self.error = False, message
        self._ready.set()

    def _run(self):
        try:
            self._loop()
        except Exception as error:
            self._fail(f"Session lock watcher failed: {error}")
        finally:
            self._cleanup()
            self.available = False
            self._ready.set()

    def _loop(self):
        import ctypes
        from ctypes import wintypes
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return self._fail("Windows API unavailable")
        user32, wtsapi32, kernel32 = windll.user32, windll.wtsapi32, windll.kernel32
        self._api = {"user32": user32, "wtsapi32": wtsapi32}
        lresult = ctypes.c_ssize_t
        functype = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
        wndproc_type = functype(lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", wndproc_type), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HANDLE), ("hIcon", wintypes.HANDLE),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        def set_types(function, argtypes, restype):
            function.argtypes, function.restype = argtypes, restype

        set_types(user32.DefWindowProcW, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], lresult)
        set_types(user32.RegisterClassW, [ctypes.POINTER(WNDCLASSW)], wintypes.ATOM)
        set_types(user32.CreateWindowExW, [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HANDLE,
            wintypes.HANDLE, wintypes.LPVOID], wintypes.HWND)
        set_types(user32.GetMessageW, [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT], ctypes.c_int)
        set_types(user32.TranslateMessage, [ctypes.POINTER(wintypes.MSG)], wintypes.BOOL)
        set_types(user32.DispatchMessageW, [ctypes.POINTER(wintypes.MSG)], lresult)
        set_types(kernel32.GetLastError, [], wintypes.DWORD)
        set_types(user32.PostMessageW, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL)
        set_types(user32.DestroyWindow, [wintypes.HWND], wintypes.BOOL)
        set_types(user32.PostQuitMessage, [ctypes.c_int], None)
        set_types(wtsapi32.WTSRegisterSessionNotification, [wintypes.HWND, wintypes.DWORD], wintypes.BOOL)
        set_types(wtsapi32.WTSUnRegisterSessionNotification, [wintypes.HWND], wintypes.BOOL)
        set_types(kernel32.GetModuleHandleW, [wintypes.LPCWSTR], wintypes.HANDLE)

        def window_proc(hwnd, message, wparam, lparam):
            try:
                if message == WM_WTSSESSION_CHANGE:
                    state = session_event_state(wparam)
                    if state is not None:
                        self.locked = state
                    return 0
                if message == WM_CLOSE:
                    user32.DestroyWindow(hwnd)
                    return 0
                if message == WM_DESTROY:
                    self._unregister()
                    user32.PostQuitMessage(0)
                    return 0
            except Exception as error:
                self.error = str(error)
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        callback = wndproc_type(window_proc)
        self._refs.append(callback)
        cls = WNDCLASSW()
        cls.lpfnWndProc = callback
        cls.hInstance = kernel32.GetModuleHandleW(None)
        cls.lpszClassName = "DivoomKeeperSessionWatcher"
        if not user32.RegisterClassW(ctypes.byref(cls)) and kernel32.GetLastError() != ERROR_CLASS_ALREADY_EXISTS:
            return self._fail("RegisterClassW failed")  # an already registered class (a restart) is fine
        hwnd = user32.CreateWindowExW(0, cls.lpszClassName, "Divoom Keeper session watcher", 0, 0, 0, 0, 0,
            HWND_MESSAGE, None, cls.hInstance, None)
        if not hwnd:
            return self._fail("CreateWindowExW failed")
        self._hwnd = hwnd
        if not wtsapi32.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION):
            return self._fail("WTSRegisterSessionNotification failed")
        self._registered = True
        self.available, self.error = True, ""
        self._ready.set()
        msg = wintypes.MSG()
        while True:
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result == 0:
                break
            if result < 0:
                self.error = "GetMessageW failed"
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _unregister(self):
        if self._registered and self._api:
            self._registered = False
            try:
                self._api["wtsapi32"].WTSUnRegisterSessionNotification(self._hwnd)
            except Exception as error:
                self.error = str(error)

    def _cleanup(self):
        self._unregister()
        hwnd, self._hwnd = self._hwnd, None
        if hwnd and self._api:
            try:
                self._api["user32"].DestroyWindow(hwnd)
            except Exception:
                pass
