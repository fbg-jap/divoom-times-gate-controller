import io
import threading
from unittest.mock import patch

from PIL import Image, ImageDraw

from test_core import FixtureCase, FakeClient
from keeper.config import ConfigStore, slot
from keeper.engine import Engine
from keeper.panorama_media import animation_frames, decode_clip, encode_panels


def make_video(path):
    import av
    with av.open(str(path), "w") as output:
        stream = output.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 640, 128, "yuv420p"
        for index in range(20):
            frame = av.VideoFrame.from_image(Image.new("RGB", (640, 128), "red" if index < 10 else "blue"))
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)


class PanoramaMediaTests(FixtureCase):
    def gif(self):
        path = self.root / "source.gif"
        frames = []
        for color in ("red", "green", "blue"):
            frame = Image.new("RGB", (640, 128), "black")
            ImageDraw.Draw(frame).rectangle((128, 0, 639, 127), fill=color)
            frames.append(frame)
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=[200, 600, 200], loop=0)
        return path

    def test_gif_variable_durations_and_static_panel_share_timeline(self):
        result = decode_clip(self.gif(), duration=1, fps=5)
        self.assertEqual((result["count"], result["speed"], result["duration"]), (5, 200, 1))
        for index, blob in enumerate(result["blobs"]):
            frames = animation_frames(io.BytesIO(blob), 200)
            self.assertEqual(len(frames), 5)
            colors = [frame.getpixel((64, 64)) for frame in frames]
            expected = [(0, 0, 0)] * 5 if index == 0 else [(255, 0, 0)] + [(0, 128, 0)] * 3 + [(0, 0, 255)]
            self.assertEqual(colors, expected)
        with Image.open(io.BytesIO(result["blobs"][0])) as static:
            self.assertEqual(static.n_frames, 1)  # GIF deduplication must not shorten the device loop.

    def test_gif_trim_does_not_loop_source_or_pad_past_end(self):
        result = decode_clip(self.gif(), start=.8, duration=4, fps=5)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["frames"][0].getpixel((200, 64)), (0, 0, 255))
        with self.assertRaisesRegex(ValueError, "No frames"):
            decode_clip(self.gif(), start=2)

    def test_mp4_decode_seek_and_end_of_clip(self):
        path = self.root / "video.mp4"
        make_video(path)
        result = decode_clip(path, start=.8, duration=.8, fps=5)
        self.assertEqual(result["count"], 4)
        colors = [frame.getpixel((320, 64)) for frame in result["frames"]]
        self.assertGreater(colors[0][0], 230)
        self.assertTrue(all(color[2] > 230 for color in colors[1:]))
        self.assertEqual(decode_clip(path, start=1.8, duration=4, fps=5)["count"], 1)
        with self.assertRaisesRegex(ValueError, "end of the video"):
            decode_clip(path, start=3)

    def test_rotation_and_crop_are_applied_to_every_frame(self):
        source = Image.new("RGB", (640, 640), "red")
        ImageDraw.Draw(source).rectangle((0, 320, 639, 639), fill="blue")
        path = self.root / "square.gif"
        source.save(path, duration=1000)
        for position, rotation, expected in [((.5, 1), 0, (0, 0, 255)), ((.5, 1), 180, (255, 0, 0))]:
            result = decode_clip(path, duration=.4, position=position, zoom=2, rotation=rotation)
            self.assertTrue(all(frame.getpixel((320, 64)) == expected for frame in result["frames"]))

    def test_bad_limits_cancellation_and_source_fail_without_config_change(self):
        path = self.gif()
        before = self.store.snapshot()
        for args in [dict(start=-1), dict(duration=31), dict(duration=30, fps=5), dict(fps=30), dict(start=float("nan"))]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                decode_clip(path, **args)
        event = threading.Event(); event.set()
        with self.assertRaises(InterruptedError):
            decode_clip(path, stop=event)
        bad = self.root / "bad.mp4"; bad.write_bytes(b"not video")
        with self.assertRaises(Exception):
            decode_clip(bad)
        self.assertEqual(self.store.snapshot(), before)

    def test_import_keeps_timeline_and_previous_composition(self):
        self.d["screens"][0] = slot("text", text="Recover me")
        self.d["playlists"][0] = {"enabled": True, "items": [{"id": "test", "seconds": 10, "screen": slot("clock")}]}
        self.store.update_device(self.d)
        result = decode_clip(self.gif(), duration=1)
        self.store.apply_panorama_animation(result["blobs"], result["speed"])
        self.assertFalse(self.store.get_device()["playlists"][0]["enabled"])
        self.assertEqual(self.store.snapshot()["scenes"][-1]["screens"], self.d["screens"])
        self.assertEqual(self.store.snapshot()["scenes"][-1]["playlists"], self.d["playlists"])
        archive = self.root / "portable.zip"
        self.store.export(archive)
        restored = ConfigStore(self.root / "restored", migrate=False)
        restored.import_bundle(archive)
        for screen in restored.get_device()["screens"]:
            self.assertEqual(screen["panorama_speed"], 200)
            self.assertEqual(len(animation_frames(screen["path"], 200)), 5)

    def test_mismatched_parts_rejected_before_config_mutation(self):
        result = decode_clip(self.gif(), duration=1)
        result["blobs"][0] = encode_panels([Image.new("RGB", (640, 128))], 200)[0]
        before = self.store.snapshot()
        with self.assertRaisesRegex(ValueError, "same duration"):
            self.store.apply_panorama_animation(result["blobs"], 200)
        self.assertEqual(self.store.snapshot(), before)

    def test_sender_uses_clip_speed_and_expands_static_frames(self):
        result = decode_clip(self.gif(), duration=1)
        self.store.apply_panorama_animation(result["blobs"], 200)
        d = self.store.get_device(); d["speed"] = 70
        engine = Engine(self.store, client_factory=FakeClient)
        with patch.object(engine.client(d), "send_frames") as send:
            engine.send(d)
            self.assertEqual(send.call_count, 5)
            for args, kwargs in send.call_args_list:
                self.assertEqual((len(args[0]), args[3]), (5, 200))
            d["screens"][0] = slot("media", path=str(self.gif()))
            engine.send_panel(d, 0, force=True)
            self.assertEqual(send.call_args.args[3], 70)
            self.assertEqual(len(send.call_args.args[0]), 3)
