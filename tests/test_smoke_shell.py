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


class ReadUrlFileTests(unittest.TestCase):
    def test_reads_the_launch_url_from_a_file_and_tolerates_missing_or_garbage(self):
        import os
        import tempfile
        from tools import smoke_shell
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "launch-url.txt")
            self.assertIsNone(smoke_shell.read_url_file(path))             # not written yet
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("not a url\n")
            self.assertIsNone(smoke_shell.read_url_file(path))
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("http://127.0.0.1:8123/#launch=" + "a" * 32 + "\n")
            self.assertEqual(smoke_shell.read_url_file(path), (8123, "a" * 32))


class SelfTestStepTests(unittest.TestCase):
    def script(self, folder, body):
        import os
        path = os.path.join(folder, "fake.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return [sys.executable, path]

    def test_passes_and_reads_the_report_file_or_stdout(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            to_file = self.script(folder, "import os\nopen(os.environ['KEEPER_SELFTEST_FILE'], 'w').write('ok a\\n')\n")
            self.assertEqual(smoke_shell.self_test(to_file), "ok a\n")
            to_stdout = self.script(folder, "print('ok b')\n")
            self.assertEqual(smoke_shell.self_test(to_stdout).strip(), "ok b")

    def test_a_failing_check_fails_the_smoke_run_with_the_report(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            failing = self.script(folder, "import os, sys\nopen(os.environ['KEEPER_SELFTEST_FILE'], 'w').write('ok a\\nFAIL video: boom\\n')\nsys.exit(1)\n")
            with self.assertRaises(smoke_shell.SmokeError) as caught:
                smoke_shell.self_test(failing)
            self.assertIn("FAIL video: boom", str(caught.exception))
            silent = self.script(folder, "import sys\nsys.exit(0)\n")  # exits 0 but reports nothing: not trusted
            with self.assertRaises(smoke_shell.SmokeError):
                smoke_shell.self_test(silent)
