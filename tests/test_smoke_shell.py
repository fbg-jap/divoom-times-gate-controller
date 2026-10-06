from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import smoke_shell  # noqa: E402


class SmokeHelperTests(unittest.TestCase):
    def test_build_command_appends_the_shell_flags(self):
        cmd = smoke_shell.build_command(["app.AppImage", "--appimage-extract-and-run"], "/tmp/x", 9000)
        self.assertEqual(cmd, ["app.AppImage", "--appimage-extract-and-run", "--demo", "--minimized", "--config-dir", "/tmp/x",
                               "--port", "9000", "--print-launch-url"])

    def test_parse_launch_url(self):
        self.assertEqual(smoke_shell.parse_launch_url("http://127.0.0.1:8765/#launch=abc_-123\n"), (8765, "abc_-123"))
        self.assertIsNone(smoke_shell.parse_launch_url("Keeper portal started"))
        self.assertIsNone(smoke_shell.parse_launch_url("http://evil.example:80/#launch=x"))

    def test_free_port_is_usable(self):
        self.assertGreater(smoke_shell.free_port(), 0)


if __name__ == "__main__":
    unittest.main()
