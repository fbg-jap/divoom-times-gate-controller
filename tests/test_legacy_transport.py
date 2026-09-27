"""Compare the new transport to the saved working sender, including JPEG bytes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image
from keeper.protocol import Client, DeviceError, media_frames

spec = importlib.util.spec_from_file_location("legacy_sender", Path(__file__).parent / "fixtures/legacy_sender.py")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)


class LegacyTransportTests(unittest.TestCase):
    def test_jpeg_png_and_animated_gif_match_working_sender(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGB", (170, 90), "coral").save(root / "still.jpg")
            Image.new("RGBA", (170, 90), (255, 0, 0, 0)).save(root / "alpha.png")
            Image.new("RGB", (170, 90), "red").save(root / "moving.gif", save_all=True,
                append_images=[Image.new("RGB", (170, 90), "blue")], duration=100)
            for path in root.iterdir():
                for panel in range(5):
                    with self.subTest(file=path.name, panel=panel):
                        response = MagicMock()
                        response.json.return_value = {"error_code": 0}
                        with patch("requests.post", return_value=response) as post, patch("time.time", return_value=1790529000), patch("time.sleep") as sleep:
                            legacy.DivoomSender.send_to_screen("192.168.1.10", panel + 1, str(path), 85, 100)
                            expected = post.call_args_list[:]
                            pauses = sleep.call_args_list[:]
                            post.reset_mock(); sleep.reset_mock()
                            Client("192.168.1.10").send_frames(media_frames(path, "stretch"), panel, 85, 100)
                            self.assertEqual(post.call_args_list, expected)
                            self.assertEqual(sleep.call_args_list, pauses)

    def test_worker_paces_still_image_and_last_frame(self):
        session, stop = MagicMock(), MagicMock()
        session.post.return_value.json.return_value = {"error_code": 0}
        stop.is_set.return_value = False
        Client("192.168.1.10", session).send_frames([Image.new("RGB", (128, 128))], 0, stop=stop)
        stop.wait.assert_called_once_with(.1)

    def test_picture_ids_increase_for_rapid_sends_and_clock_rollback(self):
        session = MagicMock()
        session.post.return_value.json.return_value = {"error_code": 0}
        client = Client("192.168.1.10", session)
        with patch("time.time", side_effect=[1790529000, 1790529000, 1790520000]), patch("time.sleep"):
            for panel in range(3):
                client.send_frames([Image.new("RGB", (128, 128))], panel)
        self.assertEqual([c.kwargs["json"]["PicID"] for c in session.post.call_args_list],
                         [1790529000, 1790529001, 1790529002])

    def test_native_zero_group_rejected_before_http(self):
        session = MagicMock()
        client = Client("192.168.1.10", session)
        for payload in [
            {"Command": "Channel/SetClockSelectId", "ClockId": 625, "LcdIndex": 1, "LcdIndependence": 0},
            {"Command": "Channel/Set5LcdChannelType", "ChannelType": 1, "LcdIndependence": 0},
        ]:
            with self.assertRaises(DeviceError):
                client.command(payload)
        session.post.assert_not_called()
