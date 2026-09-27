import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from keeper.config import ConfigStore, slot, uid
from keeper.content import composition, empty_playlists, split_panorama, validate_playlists
from keeper.engine import Engine
from keeper.widgets import Providers, Renderer, format_rate
from test_core import FixtureCase, FakeClient


def entry(text, seconds=5):
    return {"id": uid(), "seconds": seconds, "screen": slot("text", text=text, refresh=5)}


class PlaylistTests(FixtureCase):
    def setUp(self):
        super().setUp()
        self.now = 100.0
        self.clock = patch("keeper.engine.time.monotonic", lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.d["enabled"] = True
        self.d["screens"][0] = slot("text", text="fallback")
        self.d["playlists"][0] = {"enabled": True, "items": [entry("A"), entry("B", 10)]}
        self.store.update_device(self.d)
        self.engine = Engine(self.store, client_factory=FakeClient)
        self.client = self.engine.client(self.d)

    def test_independent_durations_loop_and_other_panel_untouched(self):
        self.d["playlists"][1] = {"enabled": True, "items": [entry("X", 20), entry("Y")]}
        self.engine.send(self.d, force=False)
        self.assertEqual([u[0] for u in self.client.uploads], [0, 1])
        self.now = 106
        self.engine.send(self.d, force=False)
        self.assertEqual([u[0] for u in self.client.uploads], [0, 1, 0])
        self.assertEqual(self.engine.playlist_cursors[(self.d["id"], 0)].index, 1)
        self.now = 117
        self.engine.send(self.d, force=False)
        self.assertEqual(self.client.uploads[0], self.client.uploads[-1])
        self.assertEqual(self.engine.playlist_cursors[(self.d["id"], 1)].index, 0)

    def test_preview_does_not_start_dwell_and_upload_time_is_excluded(self):
        self.engine.preview(self.d, 0)
        cursor = self.engine.playlist_cursors[(self.d["id"], 0)]
        self.assertIsNone(cursor.started)
        original = self.client.send_frames
        def slow(*args):
            self.now += 12
            original(*args)
        self.client.send_frames = slow
        self.engine.send_panel(self.d, 0, True)
        self.assertEqual(cursor.started, 112)
        self.now = 114
        self.engine.send_panel(self.d, 0)
        self.assertEqual(len(self.client.uploads), 1)

    def test_failed_next_item_retries_without_advancing(self):
        self.engine.send_panel(self.d, 0)
        self.now = 106
        self.client.fail = True
        self.engine.send_panel(self.d, 0)
        cursor = self.engine.playlist_cursors[(self.d["id"], 0)]
        self.assertEqual((cursor.index, cursor.started), (0, 100))
        self.now = 107
        self.client.fail = False
        self.engine.send_panel(self.d, 0)
        self.assertEqual(len(self.client.uploads), 1)
        self.now = 112
        self.engine.send_panel(self.d, 0)
        self.assertEqual((cursor.index, cursor.started), (1, 112))

    def test_disable_returns_to_fallback(self):
        self.engine.send_panel(self.d, 0, True)
        self.d["playlists"][0]["enabled"] = False
        self.engine.invalidate(self.d["id"], 0)
        self.engine.send_panel(self.d, 0, True)
        self.assertNotEqual(self.client.uploads[0], self.client.uploads[1])
        self.assertFalse(self.engine.playlist_cursors)

    def test_duplicate_content_still_advances_and_keeps_duration(self):
        self.d["playlists"][0]["items"][1]["screen"] = copy.deepcopy(self.d["playlists"][0]["items"][0]["screen"])
        self.engine.send_panel(self.d, 0)
        self.now = 106
        self.engine.send_panel(self.d, 0)
        self.assertEqual(self.client.uploads[0], self.client.uploads[1])
        self.assertEqual(self.engine.playlist_cursors[(self.d["id"], 0)].index, 1)

    def test_widget_refresh_does_not_restart_item_duration(self):
        self.d["playlists"][0]["items"][0].update(seconds=20)
        with patch.object(self.engine.renderer, "render", side_effect=[Image.new("RGB", (128, 128), c) for c in ["red", "blue"]]):
            self.engine.send_panel(self.d, 0)
            self.now = 106
            self.engine.send_panel(self.d, 0)
        self.assertEqual(len(self.client.uploads), 2)
        self.assertEqual(self.engine.playlist_cursors[(self.d["id"], 0)].started, 100)

    def test_pause_and_disabled_automatic_do_not_advance(self):
        self.engine.send_panel(self.d, 0)
        self.now = 200
        self.engine.paused.add(self.d["id"])
        self.engine.tick()
        self.assertEqual(len(self.client.uploads), 1)
        self.engine.paused.clear()
        self.store.update_fields(self.d["id"], enabled=False)
        self.engine.tick()
        self.assertEqual(len(self.client.uploads), 1)

    def test_notification_restores_active_item_then_restarts_dwell(self):
        self.engine.send_panel(self.d, 0)
        first = self.client.uploads[-1]
        self.engine.process("notification", self.d["id"], {"panel": 0, "text": "notice", "seconds": 10})
        self.now = 111
        self.engine.tick()
        self.assertEqual(self.client.uploads[-1], first)
        self.assertEqual(self.engine.playlist_cursors[(self.d["id"], 0)].started, 111)

    def test_scenes_include_lists_and_legacy_scenes_clear_them(self):
        saved = {"id": uid(), "name": "list", **composition(self.d)}
        legacy = {"id": uid(), "name": "old", "screens": self.d["screens"]}
        self.store.change(lambda data: data.update(scenes=[saved, legacy]))
        self.engine.apply_scene(self.d, saved["id"])
        self.assertTrue(self.store.get_device()["playlists"][0]["enabled"])
        self.engine.apply_scene(self.d, legacy["id"])
        self.assertFalse(any(p["enabled"] for p in self.store.get_device()["playlists"]))

    def test_portable_backup_includes_playlist_and_scene_media(self):
        source = self.image()
        self.d["playlists"][0]["items"][0]["screen"] = slot("media", path=str(source))
        self.store.update_device(self.d)
        self.store.change(lambda data: data["scenes"].append({"id": uid(), "name": "list", **composition(self.d)}))
        bundle = self.root / "bundle.zip"
        self.store.export(bundle)
        source.unlink()
        other = ConfigStore(self.root / "other", migrate=False)
        other.import_bundle(bundle)
        self.assertFalse(other.get_device()["enabled"])
        for owner in [other.get_device(), other.snapshot()["scenes"][0]]:
            self.assertTrue(Path(owner["playlists"][0]["items"][0]["screen"]["path"]).is_file())

    def test_invalid_lists_rejected_without_changing_configuration(self):
        for invalid in [{"enabled": True, "items": []},
                        {"enabled": True, "items": [{"id": "a", "seconds": 5, "screen": slot("native")}]},
                        {"enabled": True, "items": [entry("A", 0)]}]:
            lists = empty_playlists()
            lists[0] = invalid
            before = self.store.snapshot()
            with self.assertRaises(ValueError):
                self.store.update_fields(self.d["id"], playlists=lists)
            self.assertEqual(self.store.snapshot(), before)


class PanoramaTests(FixtureCase):
    def panorama(self):
        path = self.root / "panorama.png"
        image = Image.new("RGB", (640, 128))
        draw = ImageDraw.Draw(image)
        colors = ["red", "green", "blue", "yellow", "purple"]
        for i, color in enumerate(colors):
            draw.rectangle((i * 128, 0, (i + 1) * 128 - 1, 127), fill=color)
        image.save(path)
        return path, colors

    def test_split_preserves_order_and_edges(self):
        path, colors = self.panorama()
        for fit in ["cover", "contain", "stretch"]:
            for tile, color in zip(split_panorama(path, fit), colors):
                expected = Image.new("RGB", (128, 128), color)
                self.assertEqual(tile.tobytes(), expected.tobytes())

    def test_apply_saves_recovery_scene_and_disables_lists(self):
        self.d["playlists"][1] = {"enabled": True, "items": [entry("keep")]}
        self.store.update_device(self.d)
        before = composition(self.d)
        path, colors = self.panorama()
        self.store.apply_panorama(split_panorama(path))
        path.unlink()
        after = self.store.get_device()
        self.assertEqual(composition(self.store.snapshot()["scenes"][0]), before)
        self.assertFalse(any(p["enabled"] for p in after["playlists"]))
        self.assertEqual(after["playlists"][1]["items"], before["playlists"][1]["items"])
        self.assertTrue(all(Path(s["path"]).is_file() for s in after["screens"]))

    def test_animated_panorama_rejected_without_changing_store(self):
        path = self.root / "moving.gif"
        Image.new("RGB", (10, 10), "red").save(path, save_all=True, append_images=[Image.new("RGB", (10, 10), "blue")])
        before = self.store.snapshot()
        with self.assertRaises(ValueError):
            split_panorama(path)
        self.assertEqual(self.store.snapshot(), before)


class MetricsTests(unittest.TestCase):
    def test_network_rates_cache_and_counter_reset(self):
        provider = Providers()
        provider.nvidia = None
        counters = [SimpleNamespace(bytes_recv=1000, bytes_sent=100),
                    SimpleNamespace(bytes_recv=6120, bytes_sent=2660),
                    SimpleNamespace(bytes_recv=1, bytes_sent=1)]
        with patch("keeper.widgets.time.monotonic", return_value=100) as clock, \
             patch("keeper.widgets.psutil.net_io_counters", side_effect=counters) as network, \
             patch("keeper.widgets.psutil.cpu_percent", return_value=10), \
             patch("keeper.widgets.psutil.virtual_memory", return_value=SimpleNamespace(percent=20)), \
             patch.object(provider, "disk", return_value={"percent": 40}):
            self.assertIsNone(provider.pc()["download"])
            provider.pc()
            self.assertEqual(network.call_count, 1)
            clock.return_value = 105
            values = provider.pc()
            self.assertEqual(values["download"], 1024)
            self.assertEqual(values["upload"], 512)
            self.assertEqual(len(provider.pc_history), 2)
            clock.return_value = 110
            self.assertIsNone(provider.pc()["download"])

    def test_all_pc_views_render_and_missing_disk_is_explicit(self):
        renderer = Renderer(demo=True)
        for view in ["usage", "history", "network", "temperature", "storage"]:
            self.assertEqual(renderer.render(slot("pc", pc_view=view)).size, (128, 128))
        with patch("keeper.widgets.psutil.disk_usage", side_effect=OSError("missing")):
            provider = Providers()
            self.assertIsNone(provider.disk("missing")["percent"])
        self.assertEqual(format_rate(1024), "1.0 KiB/s")
