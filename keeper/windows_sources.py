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

    def read(self):
        with self.lock:
            now = time.monotonic()
            if not self.running and now - self.started >= self.interval:
                self.started, self.running = now, True
                threading.Thread(target=self._sample, daemon=True, name="keeper-windows-reader").start()
            value = self.value if now - self.updated < self.stale else None
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
