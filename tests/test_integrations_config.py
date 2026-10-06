import copy
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import unittest.mock
import zipfile

from keeper.config import ConfigStore, defaults, validate


class IntegrationConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ConfigStore(self.root / "store", migrate=False)

    def test_old_config_without_new_sections_loads(self):
        raw = copy.deepcopy(self.store.data)
        for key in ("spotify", "prtg", "mail", "notifications"):
            raw["integrations"].pop(key)
        raw["integrations"]["api"]["port"] = 9000
        self.store.path.write_text(json.dumps(raw))
        loaded = ConfigStore(self.root / "store", migrate=False)
        self.assertEqual(loaded.data["integrations"]["mail"]["port"], 993)
        self.assertEqual(loaded.data["integrations"]["api"]["port"], 9000)

    def test_old_notifications_config_gets_teams_defaults(self):
        raw = copy.deepcopy(self.store.data)
        raw["integrations"]["notifications"].pop("teams")
        self.store.path.write_text(json.dumps(raw))
        teams = ConfigStore(self.root / "store", migrate=False).data["integrations"]["notifications"]["teams"]
        self.assertFalse(teams["enabled"]); self.assertEqual(teams["call_seconds"], 20); self.assertIn("microsoft teams", teams["patterns"])

    def test_teams_validation(self):
        for key, value in (("enabled", 1), ("chats", "y"), ("panel", 6), ("seconds", 3), ("seconds", 61), ("call_seconds", 4),
                           ("patterns", ["a"] * 21), ("patterns", [""]), ("patterns", ["a" * 65]), ("patterns", "teams")):
            data = defaults()
            data["integrations"]["notifications"]["teams"][key] = value
            with self.assertRaises(ValueError, msg=f"{key}={value!r}"):
                validate(data)
        data = defaults()
        data["integrations"]["notifications"]["teams"].update(enabled=True, panel=0, seconds=0, call_seconds=60, patterns=["a"] * 20)
        validate(data)

    def test_validation_bounds(self):
        bad = [("mail", "port", 70000), ("notifications", "seconds", 4), ("notifications", "panel", 6),
               ("notifications", "per_minute", 0), ("prtg", "base_url", "ftp://x"),
               ("notifications", "allow_apps", ["a"] * 51), ("spotify", "client_id", "x" * 200),
               ("mail", "host", 5), ("prtg", "verify_tls", "yes")]
        for name, key, value in bad:
            data = defaults()
            data["integrations"][name][key] = value
            with self.assertRaises(ValueError, msg=f"{name}.{key}"):
                validate(data)
        data = defaults()
        data["integrations"]["prtg"]["base_url"] = "https://prtg.example.test"
        validate(data)

    def test_spotify_redirect_uri_validation(self):
        good = ["", "https://example.org/callback", "https://keeper.example.com:8443/a?b=1", "http://127.0.0.1/callback",
                "http://127.0.0.1:8888/callback", "http://[::1]:9/cb"]
        bad = ["http://localhost/callback", "http://example.org/cb", "https://user:pw@example.org/cb", "https://example.org/cb#frag",
               "https:///cb", "ftp://example.org", "https://example.org/" + "a" * 300, "example.org/cb", 5]
        for value in good:
            data = defaults()
            data["integrations"]["spotify"]["redirect_uri"] = value
            validate(data)
        for value in bad:
            data = defaults()
            data["integrations"]["spotify"]["redirect_uri"] = value
            with self.assertRaises(ValueError, msg=repr(value)):
                validate(data)

    def test_old_spotify_section_without_redirect_uri_loads(self):
        raw = copy.deepcopy(self.store.data)
        raw["integrations"]["spotify"] = {"enabled": True, "client_id": "c", "refresh_token": "T"}
        self.store.path.write_text(json.dumps(raw))
        loaded = ConfigStore(self.root / "store", migrate=False)
        self.assertEqual(loaded.data["integrations"]["spotify"]["redirect_uri"], "")
        self.assertEqual(loaded.data["integrations"]["spotify"]["client_id"], "c")

    def test_export_blanks_new_secrets(self):
        def apply(data):
            i = data["integrations"]
            i["spotify"].update(client_id="fake-client", refresh_token="FAKE-REFRESH-TOKEN")
            i["prtg"].update(token="FAKE-PRTG-TOKEN")
            i["mail"].update(user="fake-user@example.test", password="FAKE-MAIL-PASSWORD")
        self.store.change(apply)
        bundle = self.root / "backup.zip"
        self.store.export(bundle)
        with zipfile.ZipFile(bundle) as archive:
            text = archive.read("config.json").decode()
        for secret in ("FAKE-REFRESH-TOKEN", "FAKE-PRTG-TOKEN", "FAKE-MAIL-PASSWORD", "fake-user@example.test"):
            self.assertNotIn(secret, text)

    @unittest.skipIf(sys.platform == "win32", "POSIX permissions")
    def test_config_file_mode_0600(self):
        self.store.save()
        self.assertEqual(stat.S_IMODE(os.stat(self.store.path).st_mode), 0o600)

    @unittest.skipIf(sys.platform == "win32", "POSIX permissions")
    def test_save_never_exposes_a_loose_temp_file(self):
        temp = self.store.path.with_suffix(".tmp")
        temp.write_text("stale")
        os.chmod(temp, 0o666)
        seen = []
        real = os.replace
        def spy(src, dst):
            seen.append(stat.S_IMODE(os.stat(src).st_mode))
            return real(src, dst)
        with unittest.mock.patch("keeper.config.os.replace", spy):
            self.store.save()
        self.assertEqual(seen, [0o600])
        self.assertEqual(stat.S_IMODE(os.stat(self.store.path).st_mode), 0o600)
        self.assertFalse(temp.exists())

    @unittest.skipIf(sys.platform == "win32", "POSIX permissions")
    def test_new_root_is_private_and_admin_token_is_0600(self):
        from keeper.portal import create_app
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "new" / "data"
            ConfigStore(root, migrate=False)
            self.assertEqual(stat.S_IMODE(os.stat(root).st_mode), 0o700)
            create_app(root)
            self.assertEqual(stat.S_IMODE(os.stat(root / "admin.token").st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
