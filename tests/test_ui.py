import copy
from datetime import datetime, timedelta
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox

from keeper.config import ConfigStore, device, slot, uid
from keeper.engine import Engine
from keeper.ui import Window, KINDS


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        for name in ["segoeui.ttf", "segoeuib.ttf"]:
            QFontDatabase.addApplicationFont(str(Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts" / name))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ConfigStore(self.root, migrate=False)
        d = self.store.get_device()
        d["ip"] = "192.168.1.10"
        d["screens"][0] = slot("text", text="original")
        self.store.update_device(d)
        self.engine = Engine(self.store, demo=True)
        self.window = Window(self.store, self.engine, demo=True, tray=False)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.dirty = False
        self.window.quitting = True
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def drain(self):
        while True:
            try:
                key, action, device_id, args = self.engine.jobs.get_nowait()
            except queue.Empty:
                break
            self.engine.process(action, device_id, args)
            self.engine.pending.discard(key)
        self.window.poll()
        self.app.processEvents()

    def test_color_picker_cancel_accept_and_legacy_named_colors(self):
        from keeper.color_ui import ColorButton, ColorDialog
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QDialog
        button = ColorButton('white')
        self.assertEqual(button.text(), '#ffffff')
        def cancel(dialog):
            dialog.choose(QColor('#a799ff'))
            return QDialog.DialogCode.Rejected
        with patch.object(ColorDialog, 'exec', cancel):
            button.choose()
        self.assertEqual(button.text(), '#ffffff')
        def accept(dialog):
            dialog.choose(QColor('#a799ff'))
            dialog.accept()
            return QDialog.DialogCode.Accepted
        with patch.object(ColorDialog, 'exec', accept):
            button.choose()
        self.assertEqual(button.text(), '#a799ff')
        self.assertIn('#a799ff', ColorDialog.recent)
        self.assertNotIn('#', button.accessibleName())

    def test_rgb_preview_waits_for_apply_and_does_not_pause_screens(self):
        self.drain()  # Discard the screen preview requested when opening the window.
        panel = self.window.lighting
        panel.effects.button(7).click()
        panel.zone.setCurrentIndex(2)
        panel.preset(2)
        self.assertEqual(panel.settings()['effect'], 7)
        self.assertEqual(panel.settings()['zone'], 2)
        self.assertNotIn('lighting', self.store.get_device())
        self.assertTrue(self.engine.jobs.empty())
        panel.applyRequested.emit()
        self.drain()
        saved = self.store.get_device()
        self.assertEqual(saved['lighting'], panel.settings())
        self.assertEqual(saved['screens'][0]['text'], 'original')
        self.assertNotIn(saved['id'], self.engine.paused)

    def test_english_is_default_and_spanish_remains_selectable(self):
        self.assertEqual(self.window.lang, "en")
        self.assertEqual([self.window.language.itemData(i) for i in range(self.window.language.count())], ["en", "es"])
        self.assertEqual(self.window.t("Hola", "Hello"), "Hello")
        self.store.change(lambda data: data.update(language="es"))
        spanish = Window(self.store, self.engine, demo=True, tray=False)
        try:
            self.assertEqual(spanish.t("Hola", "Hello"), "Hola")
            self.assertEqual(spanish.language.currentData(), "es")
        finally:
            spanish.dirty = False; spanish.quitting = True; spanish.close(); spanish.deleteLater()

    def test_solid_color_disables_cycle_and_names_follow_the_zone(self):
        self.drain()
        panel = self.window.lighting
        self.assertEqual(panel.effects.button(4).text(), 'Breathing')
        panel.zone.setCurrentIndex(2)
        self.assertEqual(panel.effects.button(4).text(), 'Pulse')
        self.assertEqual(panel.effects.button(5).text(), 'Solid color')
        panel.cycle.setChecked(True)
        panel.effects.button(5).click()
        self.assertFalse(panel.cycle.isChecked())
        panel.color.setText('#a799ff')
        panel.effects.button(7).click()
        panel.cycle.setChecked(True)
        panel.on.setChecked(False)
        panel.zone.setCurrentIndex(0)
        panel.solid.click()
        self.assertEqual(panel.settings(), dict(color='#a799ff', brightness=50, zone=2, effect=5, on=True, cycle=False, keys=True))
        self.assertTrue(self.engine.jobs.empty())
        panel.applyRequested.emit()
        self.drain()
        self.window.load_device()
        self.assertTrue(panel.solid.isChecked())
        self.assertEqual(self.store.get_device()['lighting']['effect'], 5)
        self.assertEqual(self.store.get_device()['screens'][0]['text'], 'original')

    def test_crop_position_and_zoom_apply_the_displayed_pixels(self):
        from keeper.dialogs import PanoramaDialog
        from PIL import ImageDraw
        path = self.root / "crop.png"
        image = Image.new("RGB", (640, 640), "red")
        ImageDraw.Draw(image).rectangle((0, 320, 639, 639), fill="blue")
        image.save(path)
        dialog = PanoramaDialog(self.window)
        dialog.path.setText(str(path)); dialog.refresh_preview()
        dialog.set_position(.5, 1); dialog.zoom.setValue(200)
        self.assertTrue(all(im.getpixel((64, 64)) == (0, 0, 255) for im in dialog.images))
        self.store.apply_panorama(dialog.images)
        with Image.open(self.store.get_device()["screens"][0]["path"]) as saved:
            self.assertEqual(saved.getpixel((64, 64)), (0, 0, 255))
        dialog.reject()

    def test_rss_editor_and_new_playlist_widgets(self):
        from keeper.dialogs import ItemEditor, PlaylistDialog
        from PySide6.QtWidgets import QDialog, QMenu
        self.window.kind.setCurrentIndex(self.window.kind.findData("rss"))
        def edit(dialog):
            dialog.extra_fields.url.setText("https://example.test/feed")
            dialog.extra_fields.seconds.setValue(20)
            dialog.accept()
            return QDialog.DialogCode.Accepted
        with patch.object(ItemEditor, "exec", edit):
            self.window.configure_extra()
        self.assertTrue(self.window.save_editor())
        saved = self.store.get_device()["screens"][0]
        self.assertEqual((saved["url"], saved["news_seconds"]), ("https://example.test/feed", 20))
        playlist = PlaylistDialog(self.window, self.store, 0)
        texts = [a.text() for menu in playlist.findChildren(QMenu) for a in menu.actions()]
        self.assertTrue(any("Now playing" in text for text in texts))
        playlist.reject()

    def test_designer_drag_persists_and_cancel_is_independent(self):
        from keeper.designer import DesignerDialog
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        original = slot("custom", elements=[])
        dialog = DesignerDialog(self.window, original); dialog.add("text")
        dialog.show(); self.app.processEvents()
        QTest.mousePress(dialog.canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
        QTest.mouseMove(dialog.canvas, QPoint(90, 90))
        QTest.mouseRelease(dialog.canvas, Qt.MouseButton.LeftButton, pos=QPoint(90, 90))
        self.assertEqual(dialog.screen["elements"][0]["x"], 28)
        self.assertEqual(original["elements"], [])
        dialog.accept()

    def test_rules_and_integrations_save_without_network_in_demo(self):
        from keeper.extra_ui import RuleDialog
        dialog = RuleDialog(self.window, "alerts")
        dialog.name.setText("High CPU"); dialog.text.setPlainText("Check the PC")
        dialog.accept()
        self.assertEqual(dialog.rule["metric"], "cpu")
        self.window.integration_panel.api_on.setChecked(True)
        self.window.integration_panel.save()
        self.engine.bridge.configure(self.store.snapshot())
        self.assertIsNone(self.engine.bridge.server)
        self.assertTrue(self.store.snapshot()["integrations"]["api"]["enabled"])
        self.window.automation_panel.control("start"); self.drain()
        self.assertTrue(self.engine.automations.pomodoro.running)

    def test_edit_widget_save_and_send(self):
        self.window.text_content.setPlainText("Hello world")
        self.window.save_send()
        self.drain()
        self.assertEqual(self.store.get_device()["screens"][0]["text"], "Hello world")
        self.assertIn((self.store.get_device()["id"], 0), self.engine.hashes)
        self.assertFalse(self.window.panel_images[0].pixmap().isNull())

    def test_playlist_editor_saves_order_duration_and_sends_first_item(self):
        from keeper.dialogs import PlaylistDialog
        from PySide6.QtWidgets import QDialog
        def edit(dialog):
            dialog.append(slot("text", text="first"))
            dialog.append(slot("clock"))
            dialog.seconds.setValue(17)
            dialog.move(-1)
            dialog.enabled.setChecked(True)
            dialog.accept()
            return QDialog.DialogCode.Accepted
        with patch.object(PlaylistDialog, "exec", edit):
            self.window.open_playlist()
        self.drain()
        playlist = self.store.get_device()["playlists"][0]
        self.assertTrue(playlist["enabled"])
        self.assertEqual(playlist["items"][0]["screen"]["kind"], "clock")
        self.assertEqual(playlist["items"][0]["seconds"], 17)
        self.assertIn("1/2", self.window.panel_titles[0].text())
        self.assertTrue(self.window.playlist_hint.isVisible())

    def test_cancel_playlist_does_not_change_configuration(self):
        from keeper.dialogs import PlaylistDialog
        dialog = PlaylistDialog(self.window, self.store, 0)
        before = self.store.snapshot()
        dialog.append(slot("pc", pc_view="network"))
        dialog.enabled.setChecked(True)
        dialog.reject()
        self.assertEqual(self.store.snapshot(), before)

    def test_panorama_preview_apply_and_recovery_scene(self):
        from keeper.dialogs import PanoramaDialog
        from PySide6.QtWidgets import QDialog
        path = self.root / "wide.png"
        Image.new("RGB", (640, 128), "orange").save(path)
        original = copy.deepcopy(self.store.get_device()["screens"])
        def edit(dialog):
            dialog.path.setText(str(path))
            dialog.refresh_preview()
            self.assertTrue(dialog.apply.isEnabled())
            self.assertTrue(all(not image.pixmap().isNull() for image in dialog.previews))
            dialog.accept()
            return QDialog.DialogCode.Accepted
        with patch.object(PanoramaDialog, "exec", edit):
            self.window.open_panorama()
        self.drain()
        self.assertEqual(self.store.snapshot()["scenes"][-1]["screens"], original)
        self.assertTrue(all(s["kind"] == "media" for s in self.store.get_device()["screens"]))

    def test_animated_panorama_preview_save_reload_and_cancel(self):
        import time
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QDialog
        from keeper.dialogs import PanoramaDialog
        path = self.root / "moving.gif"
        Image.new("RGB", (640, 128), "red").save(path, save_all=True,
            append_images=[Image.new("RGB", (640, 128), "blue")], duration=400, loop=0)
        def edit(dialog):
            dialog.path.setText(str(path)); dialog.refresh_preview()
            deadline = time.monotonic() + 10
            while not dialog.apply.isEnabled() and time.monotonic() < deadline:
                QTest.qWait(20)
            self.assertTrue(dialog.apply.isEnabled(), dialog.message.text())
            self.assertEqual(len(dialog.animation_frames), 4)
            dialog.toggle_play(); dialog.frame_slider.setValue(3)
            self.assertEqual(dialog.images[0].getpixel((64, 64)), (0, 0, 255))
            dialog.accept()
            return QDialog.DialogCode.Accepted
        with patch.object(PanoramaDialog, "exec", edit):
            self.window.open_panorama()
        self.drain()
        self.window.load_editor()
        self.window.frame_step.setValue(3)
        self.assertTrue(self.window.save_editor())
        screen = self.store.get_device()["screens"][0]
        self.assertEqual((screen["panorama_speed"], screen["frame_step"], screen["fit"]), (200, 1, "stretch"))
        original = self.store.snapshot()
        dialog = PanoramaDialog(self.window)
        dialog.path.setText(str(path)); dialog.refresh_preview()
        dialog.reject()
        self.assertTrue(dialog.cancel_conversion.is_set())
        self.assertFalse(dialog.convert_timer.isActive())
        self.assertEqual(self.store.snapshot(), original)

    def test_stale_panorama_result_cannot_override_new_preview(self):
        from keeper.dialogs import PanoramaDialog
        from keeper.panorama_media import decode_clip
        path = self.root / "still.gif"
        Image.new("RGB", (640, 128), "blue").save(path, duration=1000)
        result = decode_clip(path, duration=1)
        dialog = PanoramaDialog(self.window)
        dialog.path.setText(str(path)); dialog.refresh_preview()
        self.assertTrue(dialog.apply.isEnabled())
        dialog.results.put((dialog.generation-1, result, ""))
        dialog.results.put((dialog.generation-1, None, "obsolete error"))
        dialog.poll_clip()
        self.assertEqual(dialog.animation_blobs, [])
        self.assertTrue(dialog.apply.isEnabled())
        self.assertNotIn("obsolete", dialog.message.text())
        dialog.reject()

    def test_advanced_pc_view_and_disk_survive_save_reload(self):
        self.window.kind.setCurrentIndex(self.window.kind.findData("pc"))
        self.window.pc_view.setCurrentIndex(self.window.pc_view.findData("history"))
        self.window.pc_disk.setEditText("Z:\\")
        self.assertTrue(self.window.save_editor())
        self.window.load_editor()
        self.assertEqual(self.window.pc_view.currentData(), "history")
        self.assertEqual(self.window.pc_disk.currentText(), "Z:\\")

    def test_all_screen_editors_save_valid_configuration(self):
        media = self.root / "source.png"
        Image.new("RGB", (128, 128), "purple").save(media)
        ics = self.root / "source.ics"
        ics.write_text("BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n")
        for kind, _, _ in KINDS:
            with self.subTest(kind=kind):
                self.window.kind.setCurrentIndex(self.window.kind.findData(kind))
                self.window.media_path.setText(str(media))
                self.window.calendar_path.setText(str(ics))
                self.window.calendar_url.clear()
                self.window.service_url.setText("https://example.com/health")
                self.window.pc_independence.setValue(123)
                self.assertTrue(self.window.save_editor())
                self.assertEqual(self.store.get_device()["screens"][0]["kind"], kind)

    def test_switching_panels_saves_draft(self):
        self.window.text_content.setPlainText("Draft")
        self.window.select_panel(1)
        self.assertEqual(self.store.get_device()["screens"][0]["text"], "Draft")
        self.assertEqual(self.window.selected, 1)

    def test_native_monitor_can_save_and_send_without_cloud_ids(self):
        self.window.kind.setCurrentIndex(self.window.kind.findData("pc_native"))
        self.window.pc_native_mode.setCurrentIndex(self.window.pc_native_mode.findData("existing"))
        self.window.pc_independence.setValue(0)
        self.window.save_send()
        self.drain()
        saved = self.store.get_device()["screens"][0]
        self.assertEqual(saved["native_pc_mode"], "existing")
        self.assertEqual(saved["independence"], 0)
        self.assertEqual(self.engine.hashes[(self.store.get_device()["id"], 0)], "native-pc")

    def test_invalid_draft_does_not_switch_panels(self):
        self.window.kind.setCurrentIndex(self.window.kind.findData("clock"))
        self.window.timezone.setText("Invalid/Zone")
        with patch.object(QMessageBox, "warning") as warning:
            self.window.select_panel(1)
        warning.assert_called_once()
        self.assertEqual(self.window.selected, 0)
        self.assertEqual(self.store.get_device()["screens"][0]["kind"], "text")

    def test_device_switch_saves_to_previous_device(self):
        d2 = device("192.168.1.20", "Second")
        self.store.change(lambda data: data["devices"].append(d2))
        self.window.load_devices()
        self.window.text_content.setPlainText("Previous device draft")
        self.window.device_picker.setCurrentIndex(1)
        self.assertEqual(self.store.snapshot()["devices"][0]["screens"][0]["text"], "Previous device draft")
        self.assertEqual(self.store.get_device()["id"], d2["id"])

    def test_native_tool_pauses_and_restore_resumes(self):
        self.window.native_tool("Tools/SetTimer", Minute=1, Second=0, Status=1)
        self.drain()
        self.assertTrue(self.store.get_device()["suspended"])
        self.window.job("resume")
        self.drain()
        self.assertFalse(self.store.get_device()["suspended"])

    def test_scenes_apply_and_rotation_save(self):
        scene = {"id": uid(), "name": "New scene", "screens": [slot("text", text="scene")]+[slot() for _ in range(4)]}
        self.store.change(lambda data: data["scenes"].append(scene))
        self.window.refresh_lists()
        self.window.scene_list.setCurrentRow(0)
        self.window.apply_scene()
        self.drain()
        self.assertEqual(self.store.get_device()["screens"][0]["text"], "scene")

    def test_schedules_add_toggle_delete(self):
        self.window.schedule_action.setCurrentIndex(self.window.schedule_action.findData("brightness"))
        self.window.add_schedule()
        self.assertEqual(len(self.store.snapshot()["schedules"]), 1)
        self.window.schedule_table.selectRow(0)
        self.window.toggle_schedule()
        self.assertFalse(self.store.snapshot()["schedules"][0]["enabled"])
        self.window.schedule_table.selectRow(0)
        self.window.delete_schedule()
        self.assertEqual(self.store.snapshot()["schedules"], [])

    def test_demo_settings_never_write_registry(self):
        with patch("keeper.startup.set_startup") as startup:
            self.window.startup.setChecked(True)
            self.window.save_settings()
            startup.assert_not_called()

    def test_small_window_all_pages_scroll_without_horizontal_overflow(self):
        self.window.resize(1120, 760)
        for i in range(self.window.pages.count()):
            self.window.nav.setCurrentRow(i)
            self.app.processEvents()
            scroll = self.window.pages.widget(i)
            self.assertEqual(scroll.horizontalScrollBar().maximum(), 0, f"Horizontal overflow on page {i}")


if __name__ == "__main__":
    unittest.main()
