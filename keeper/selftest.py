"""`--self-test`: in-process checks of what a PyInstaller bundle can lose (data files, hidden imports, native modules)."""
from __future__ import annotations

import io
import os
from pathlib import Path
import sys
import tempfile

ICS = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//selftest//EN\r\nBEGIN:VEVENT\r\nUID:selftest@keeper\r\n"
       b"DTSTAMP:20240101T000000Z\r\nDTSTART:20240101T100000Z\r\nDTEND:20240101T110000Z\r\nRRULE:FREQ=DAILY;COUNT=5\r\n"
       b"SUMMARY:Self test\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")


def check_calendar():
    from datetime import datetime, timezone
    from icalendar import Calendar
    import recurring_ical_events
    events = recurring_ical_events.of(Calendar.from_ical(ICS)).between(
        datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 1, 4, tzinfo=timezone.utc))
    if len(events) != 3:
        raise RuntimeError(f"expected 3 recurring occurrences, got {len(events)}")


def check_gif():
    from PIL import Image
    frames = [Image.new("RGB", (16, 16), color) for color in ("red", "green", "blue")]  # identical frames would be merged
    blob = io.BytesIO()
    frames[0].save(blob, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    with Image.open(io.BytesIO(blob.getvalue())) as image:
        if getattr(image, "n_frames", 1) < 2:
            raise RuntimeError("the animated GIF lost its frames")


def check_video():
    import av
    from PIL import Image
    from .panorama_media import decode_clip
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "selftest.mp4"
        with av.open(str(path), "w") as output:
            stream = output.add_stream("mpeg4", rate=10)
            stream.width, stream.height, stream.pix_fmt = 640, 128, "yuv420p"
            for index in range(10):
                frame = av.VideoFrame.from_image(Image.new("RGB", (640, 128), "red" if index < 5 else "blue"))
                for packet in stream.encode(frame):
                    output.mux(packet)
            for packet in stream.encode():
                output.mux(packet)
        clip = decode_clip(path, duration=1, fps=5)
        if clip["count"] != 5 or len(clip["blobs"]) != 5:
            raise RuntimeError(f"unexpected clip: {clip['count']} frames, {len(clip['blobs'])} panels")


def check_psutil():
    import psutil
    value = psutil.cpu_percent(interval=.05)
    if not 0 <= value <= 100 * (psutil.cpu_count() or 1):
        raise RuntimeError(f"implausible CPU value {value}")


def check_timezone():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    if ZoneInfo("Europe/Madrid").utcoffset(datetime(2024, 7, 1)) is None:
        raise RuntimeError("no UTC offset for Europe/Madrid")


def check_platform():
    if sys.platform == "win32":
        import winrt.runtime  # noqa: F401  (what keeper.windows_sources.read_media imports)
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager  # noqa: F401
        from winrt.windows.storage.streams import DataReader  # noqa: F401
        import winrt.windows.foundation  # noqa: F401
    elif sys.platform.startswith("linux"):
        import jeepney  # noqa: F401
        from jeepney.io.blocking import open_dbus_connection  # noqa: F401


CHECKS = (("calendar", check_calendar), ("gif", check_gif), ("video", check_video), ("psutil", check_psutil),
          ("timezone", check_timezone), ("platform", check_platform))


def run_self_test(checks=None, environ=None, out=None):
    """Run every check, print one line each, mirror the text to $KEEPER_SELFTEST_FILE. Returns 0 only if all pass."""
    environ = os.environ if environ is None else environ
    out = out or sys.stdout
    lines, failed = [], False
    for name, check in (CHECKS if checks is None else checks):
        try:
            check()
            lines.append(f"ok {name}")
        except Exception as error:
            failed = True
            lines.append(f"FAIL {name}: {type(error).__name__}: {error}")
    text = "\n".join(lines) + "\n"
    out.write(text)
    out.flush()
    target = environ.get("KEEPER_SELFTEST_FILE")
    if target:
        try:
            Path(target).write_text(text, encoding="utf-8")
        except OSError:
            failed = True
    return 1 if failed else 0
