#!/usr/bin/env python3
"""Divoom Keeper Studio. Use --demo for a device-free preview."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description="Divoom Keeper Studio")
    parser.add_argument("--demo", action="store_true", help="Synthetic data; no device/network writes")
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--screenshot-dir", type=Path, help="Render all pages in isolated demo mode and exit")
    args = parser.parse_args()
    if args.screenshot_dir:
        args.demo = True
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QLockFile, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtGui import QFontDatabase, QFont
    from keeper.config import ConfigStore, slot, uid
    from keeper.engine import Engine
    from keeper.ui import Window
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Divoom Keeper Studio")
    app.setDesktopFileName("divoom-keeper-studio")
    app.setOrganizationName("DivoomKeeperStudio")
    app.setStyle("Fusion")
    # Explicit font loading also makes Qt's offscreen renderer work on Windows.
    fonts = Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts"
    for filename in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        if (fonts / filename).exists():
            QFontDatabase.addApplicationFont(str(fonts / filename))
    app.setFont(QFont("Segoe UI" if os.name == "nt" else "DejaVu Sans", 10))
    temp = tempfile.TemporaryDirectory(prefix="divoom-studio-demo-") if args.demo and not args.config_dir else None
    root = Path(temp.name) if temp else args.config_dir
    from keeper.platform_support import data_directory
    root = root or data_directory()
    root.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(root / "studio.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "Divoom Keeper Studio", "Studio is already open with this configuration. Check the system tray.")
        return 1
    handler = RotatingFileHandler(root / "studio.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s [%(levelname)s] %(message)s")
    try:
        store = ConfigStore(root, migrate=not args.demo)
    except Exception as error:
        QMessageBox.critical(None, "Settings", f"The settings were not modified.\n{error}\n\nFolder: {root}")
        lock.unlock()
        return 1
    if args.demo:
        d = store.get_device()
        d.update(name="Times Gate · Desktop", ip="192.168.1.116", enabled=False)
        d["screens"] = [slot("clock", title="MADRID"), slot("pc", title="WORKSTATION", pc_view="history", refresh=5),
                        slot("text", title="FOCUS MODE", text="Make\nsomething\ngreat.", color="#a799ff"),
                        slot("weather", title="MADRID", color="#ffc879"),
                        slot("pc", title="NETWORK", pc_view="network", refresh=5, color="#71a8ff")]
        d["playlists"][2] = {"enabled": True, "items": [
            {"id": uid(), "seconds": 15, "screen": d["screens"][2]},
            {"id": uid(), "seconds": 30, "screen": slot("clock", timezone="Asia/Tokyo", title="TOKYO")}]}
        store.update_device(d)
        from keeper.content import composition
        scenes = [{"id": uid(), "name": name, **composition(d)} for name in ["Desktop", "Focus", "Night"]]
        store.change(lambda data: data.update(language="en", scenes=scenes, schedules=[
            {"id": uid(), "device_id": d["id"], "time": "22:30", "days": list(range(7)), "action": "brightness", "value": 15, "enabled": True},
            {"id": uid(), "device_id": d["id"], "time": "08:00", "days": list(range(5)), "action": "scene", "value": scenes[0]["id"], "enabled": True}]))
    elif store.snapshot().get("startup"):
        # Preserve an already enabled preference when launching a new release.
        from keeper.startup import set_startup
        try:
            set_startup(True, store.root)
        except OSError as error:
            logging.warning("Could not update autostart: %s", error)
    engine = Engine(store, demo=args.demo)
    window = Window(store, engine, demo=args.demo, tray=not (args.no_tray or args.screenshot_dir))
    engine.start()
    if not args.minimized or not window.tray:
        window.show()
    if args.screenshot_dir:
        args.screenshot_dir.mkdir(parents=True, exist_ok=True)
        # Exercise packaged optional modules and resources without network access.
        from datetime import datetime, timedelta
        from icalendar import Calendar, Event
        from keeper.widgets import Providers
        from keeper.protocol import media_frames
        from PIL import Image
        media_smoke = {"available": False}
        if os.name == "nt":
            from keeper.windows_sources import read_media
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as pool:
                media = pool.submit(read_media).result(timeout=15)
            media_smoke = {"available": True, "has_title": bool(media.get("title")), "has_art": bool(media.get("art"))}
        pc_sample = Providers().pc()
        assert all(isinstance(pc_sample[key], (int, float)) for key in ("cpu", "ram", "disk"))
        cal, event = Calendar(), Event()
        event.add("uid", "studio-smoke-event")
        event.add("dtstart", datetime.now().astimezone() + timedelta(hours=1))
        event.add("summary", "Smoke calendar")
        event.add("rrule", {"freq": "daily", "count": 2})
        cal.add_component(event)
        test_calendar = root / "smoke.ics"
        test_calendar.write_bytes(cal.to_ical())
        assert Providers().calendar(str(test_calendar))[0] == "Smoke calendar"
        test_gif = root / "smoke.gif"
        Image.new("RGB", (128, 128), "red").save(test_gif, save_all=True,
            append_images=[Image.new("RGB", (128, 128), "blue")], duration=100)
        assert len(media_frames(test_gif)) == 2
        # Exercise FFmpeg codec DLLs from the packaged application as well as Pillow.
        import av
        from keeper.panorama_media import decode_clip
        test_video = root / "smoke.mp4"
        with av.open(str(test_video), "w") as output:
            stream = output.add_stream("mpeg4", rate=5)
            stream.width, stream.height, stream.pix_fmt = 640, 128, "yuv420p"
            from PIL import ImageDraw
            for index in range(10):
                frame_image = Image.new("RGB", (640, 128), "#101827")
                draw = ImageDraw.Draw(frame_image)
                for panel in range(5):
                    x = panel * 128
                    draw.text((x+58, 18), str(panel+1), fill="#64e6ca", font_size=24)
                    draw.rectangle((x+10+index*8, 72, x+24+index*8, 95), fill="#7199f5")
                for packet in stream.encode(av.VideoFrame.from_image(frame_image)):
                    output.mux(packet)
            for packet in stream.encode():
                output.mux(packet)
        video_smoke = decode_clip(test_video, duration=2, fps=5)
        assert video_smoke["count"] == 10 and len(video_smoke["blobs"]) == 5
        assert decode_clip(test_gif, duration=1, fps=10)["count"] == 2
        captures = ["screens", "scenes", "device", "tools", "schedules", "activity", "settings", "automations", "integrations"]
        progress = {"index": 0}

        def capture():
            i = progress["index"]
            if i < len(captures):
                window.nav.setCurrentRow(i)
                app.processEvents()
                window.grab().save(str(args.screenshot_dir / f"{i+1:02}-{captures[i]}.png"))
                progress["index"] += 1
                QTimer.singleShot(150, capture)
            else:
                from keeper.dialogs import PlaylistDialog, PanoramaDialog
                from keeper.widgets import Renderer
                from keeper.content import PC_VIEWS
                from PIL import ImageDraw
                window.select_panel(1)
                window.nav.setCurrentRow(0)
                app.processEvents()
                window.grab().save(str(args.screenshot_dir / "09-pc-editor.png"))
                playlist = PlaylistDialog(window, store, 2)
                playlist.show()
                app.processEvents()
                playlist.grab().save(str(args.screenshot_dir / "10-playlist.png"))
                playlist.reject()
                panorama_source = root / "panorama-smoke.png"
                wide = Image.new("RGB", (640, 128), "#101827")
                draw = ImageDraw.Draw(wide)
                for x in range(640):
                    draw.line((x, 0, x, 127), fill=(20 + x // 5, 90 + x // 8, 170 - x // 8))
                for x in range(0, 640, 32):
                    draw.line((x, 128, x + 90, 40, x + 130, 90), fill="#64e6ca", width=3)
                wide.save(panorama_source)
                panorama = PanoramaDialog(window)
                panorama.path.setText(str(panorama_source))
                panorama.refresh_preview()
                panorama.show()
                app.processEvents()
                panorama.grab().save(str(args.screenshot_dir / "11-panorama.png"))
                panorama.reject()
                clip_dialog = PanoramaDialog(window)
                clip_dialog.path.setText(str(test_video)); clip_dialog.refresh_preview()
                clip_dialog.convert_timer.stop()
                clip_dialog.results.put((clip_dialog.generation, video_smoke, ""))
                clip_dialog.poll_clip(); clip_dialog.show(); app.processEvents()
                clip_dialog.grab().save(str(args.screenshot_dir / "18-panorama-video.png"))
                clip_dialog.reject(); clip_dialog.deleteLater()
                from keeper.designer import DesignerDialog
                design = slot("custom", elements=[
                    {"type": "text", "x": 8, "y": 8, "width": 112, "height": 24, "size": 16, "text": "WORKSTATION", "color": "#64e6ca"},
                    {"type": "text", "x": 8, "y": 45, "width": 112, "height": 24, "size": 20, "text": "CPU {cpu}%", "color": "white"},
                    {"type": "bar", "x": 8, "y": 80, "width": 112, "height": 10, "metric": "cpu", "maximum": 100, "color": "#64e6ca"},
                    {"type": "text", "x": 8, "y": 101, "width": 112, "height": 22, "size": 14, "text": "{time}", "color": "#7199f5"}])
                designer = DesignerDialog(window, design); designer.show(); app.processEvents()
                designer.grab().save(str(args.screenshot_dir / "14-designer.png")); designer.reject()
                from keeper.extra_ui import RuleDialog
                for group in ("alerts", "profiles", "reminders"):
                    dialog = RuleDialog(window, group); dialog.show(); app.processEvents()
                    dialog.grab().save(str(args.screenshot_dir / f"15-{group}.png")); dialog.reject()
                from keeper.dialogs import ItemEditor
                for kind in ("rss", "music", "sensor", "pomodoro"):
                    dialog = ItemEditor(window, slot(kind)); dialog.show(); app.processEvents()
                    dialog.grab().save(str(args.screenshot_dir / f"16-{kind}.png")); dialog.reject()
                renderer = Renderer(demo=True)
                extras = Image.new("RGB", (640, 128))
                for index, content in enumerate([slot("music"), slot("rss", url="https://example.test/rss"), design, slot("pomodoro"), slot("sensor", sensor_source="hardware", sensor_key="/demo/cpu/temperature/0", sensor_unit="°C", title="CPU TEMP")]):
                    extras.paste(renderer.render(content), (index*128, 0))
                extras.resize((1280, 256)).save(args.screenshot_dir / "17-new-widgets.png")
                renderer = Renderer(demo=True)
                sheet = Image.new("RGB", (640, 128))
                for i, (key, _, _) in enumerate(PC_VIEWS):
                    sheet.paste(renderer.render(slot("pc", pc_view=key, title=key.upper())), (128 * i, 0))
                sheet.resize((1280, 256)).save(args.screenshot_dir / "12-pc-views.png")
                store.change(lambda data: data.update(theme="light"))
                window.apply_theme()
                window.nav.setCurrentRow(0)
                app.processEvents()
                window.grab().save(str(args.screenshot_dir / "08-light.png"))
                (args.screenshot_dir / "smoke-result.json").write_text(json.dumps({"ok": True, "pages": len(captures), "demo": True, "calendar_recurrence": True, "gif_decode": True, "panorama_gif": True, "panorama_video_frames": video_smoke["count"], "pc_sample": pc_sample, "windows_media": media_smoke, "frozen": bool(getattr(sys, "frozen", False))}), encoding="utf-8")
                window.quit_app()
        QTimer.singleShot(2500, capture)
    result = app.exec()
    engine.stop()
    engine.join(timeout=12)
    lock.unlock()
    handler.close()
    if temp:
        temp.cleanup()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
