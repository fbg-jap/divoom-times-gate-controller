import io
from pathlib import Path
import tempfile
import unittest

from keeper import selftest


class SelfTestTests(unittest.TestCase):
    def run_checks(self, checks=None, environ=None):
        out = io.StringIO()
        code = selftest.run_self_test(checks, environ if environ is not None else {}, out)
        return code, out.getvalue()

    def test_every_real_check_passes_in_the_dev_environment(self):
        code, text = self.run_checks()
        self.assertEqual(code, 0, text)
        self.assertEqual([line.split()[1] for line in text.splitlines()], [name for name, _ in selftest.CHECKS])
        self.assertTrue(all(line.startswith("ok ") for line in text.splitlines()), text)

    def test_a_failing_check_is_reported_and_the_others_still_run(self):
        def broken():
            raise RuntimeError("no codec")
        code, text = self.run_checks([("first", lambda: None), ("video", broken), ("last", lambda: None)])
        self.assertEqual(code, 1)
        self.assertEqual(text.splitlines(), ["ok first", "FAIL video: RuntimeError: no codec", "ok last"])

    def test_the_report_is_mirrored_to_the_selftest_file(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "report.txt"
            code, text = self.run_checks([("a", lambda: None)], {"KEEPER_SELFTEST_FILE": str(target)})
            self.assertEqual((code, target.read_text(encoding="utf-8")), (0, text))
            unwritable = Path(temp) / "missing" / "report.txt"
            code, _ = self.run_checks([("a", lambda: None)], {"KEEPER_SELFTEST_FILE": str(unwritable)})
            self.assertEqual(code, 1)  # a console-less build could not report: that is a failure

    def test_the_calendar_check_really_expands_the_rrule(self):
        import recurring_ical_events
        from unittest import mock
        with mock.patch.object(recurring_ical_events, "of", side_effect=ImportError("data files lost")):
            code, text = self.run_checks([("calendar", selftest.check_calendar)])
        self.assertEqual(code, 1)
        self.assertIn("FAIL calendar: ImportError: data files lost", text)


if __name__ == "__main__":
    unittest.main()
