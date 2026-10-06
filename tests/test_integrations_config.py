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
