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
from keeper.mail import new_account


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
        self.assertEqual(loaded.data["integrations"]["mail"], {"enabled": False, "accounts": []})
        self.assertEqual(loaded.data["integrations"]["api"]["port"], 9000)

    def test_validation_bounds(self):
        bad = [("mail", "accounts", "x"), ("notifications", "seconds", 4), ("notifications", "panel", 6),
               ("notifications", "per_minute", 0), ("prtg", "base_url", "ftp://x"),
               ("notifications", "allow_apps", ["a"] * 51), ("spotify", "client_id", "x" * 200),
               ("mail", "enabled", "yes"), ("prtg", "verify_tls", "yes")]
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
            i["mail"]["accounts"] = [new_account(id="a1", user="fake-user@example.test", password="FAKE-MAIL-PASSWORD"),
                                     new_account(id="a2", provider="google", user="fake-g@example.test", client_secret="FAKE-GSECRET",
                                                 refresh_token="FAKE-MAIL-REFRESH", client_id="client-123")]
        self.store.change(apply)
        bundle = self.root / "backup.zip"
        self.store.export(bundle)
        with zipfile.ZipFile(bundle) as archive:
            text = archive.read("config.json").decode()
        for secret in ("FAKE-REFRESH-TOKEN", "FAKE-PRTG-TOKEN", "FAKE-MAIL-PASSWORD", "fake-user@example.test", "fake-g@example.test",
                       "FAKE-GSECRET", "FAKE-MAIL-REFRESH"):
            self.assertNotIn(secret, text)
        exported = json.loads(text)["integrations"]["mail"]
        self.assertEqual([a["id"] for a in exported["accounts"]], ["a1", "a2"])  # the structure survives, the secrets do not
        self.assertEqual(exported["accounts"][1]["client_id"], "client-123")
        self.assertFalse(any(a["enabled"] for a in exported["accounts"]))

    def test_legacy_flat_mail_config_is_migrated_to_the_first_account(self):
        raw = copy.deepcopy(self.store.data)
        raw["integrations"]["mail"] = {"enabled": True, "host": "imap.old.test", "port": 143, "user": "me@old.test", "password": "pw",
                                       "mailbox": "Work", "show_subject": True}
        validate(raw)  # an old export/backup still validates before it is migrated
        self.store.path.write_text(json.dumps(raw))
        loaded = ConfigStore(self.root / "store", migrate=False).data["integrations"]["mail"]
        self.assertEqual(set(loaded), {"enabled", "accounts"})  # the legacy keys are dropped
        self.assertTrue(loaded["enabled"])
        (account,) = loaded["accounts"]
        self.assertEqual((account["id"], account["name"], account["provider"], account["enabled"]), ("main", "me@old.test", "imap", True))
        self.assertEqual((account["host"], account["port"], account["user"], account["password"], account["mailbox"], account["show_subject"]),
                         ("imap.old.test", 143, "me@old.test", "pw", "Work", True))
        again = ConfigStore(self.root / "store", migrate=False).data["integrations"]["mail"]  # saved in the new shape: stable
        self.assertEqual(again, loaded)
        empty = copy.deepcopy(self.store.data)
        empty["integrations"]["mail"] = {"enabled": False, "host": "", "port": 993, "user": "", "password": "", "mailbox": "INBOX", "show_subject": False}
        self.store.path.write_text(json.dumps(empty))
        self.assertEqual(ConfigStore(self.root / "store", migrate=False).data["integrations"]["mail"]["accounts"], [])

    def test_mail_account_validation(self):
        def check(**changes):
            data = defaults()
            data["integrations"]["mail"]["accounts"] = [new_account(id="ok1")]
            data["integrations"]["mail"]["accounts"][0].update(changes)
            validate(data)
        check()
        check(provider="google", client_id="c", client_secret="s", redirect_uri="https://example.org/cb", tenant="common")
        check(provider="microsoft", tenant="contoso.onmicrosoft.com", redirect_uri="https://login.microsoftonline.com/common/oauth2/nativeclient")
        for changes in ({"id": "UPPER"}, {"id": ""}, {"id": "x" * 17}, {"id": 5}, {"provider": "yahoo"}, {"name": "n" * 41}, {"host": "h" * 256},
                        {"port": 0}, {"port": 70000}, {"port": "993"}, {"mailbox": 5}, {"tenant": "bad tenant!"}, {"tenant": "t" * 65}, {"tenant": ""},
                        {"redirect_uri": "http://localhost/cb"}, {"redirect_uri": "http://example.org/cb"}, {"enabled": "yes"},
                        {"show_subject": 1}, {"refresh_token": "t" * 5000}, {"client_secret": 5}):
            with self.assertRaises(ValueError, msg=repr(changes)):
                check(**changes)
        data = defaults()
        data["integrations"]["mail"]["accounts"] = [new_account(id="dup"), new_account(id="dup")]
        with self.assertRaises(ValueError):
            validate(data)
        data["integrations"]["mail"]["accounts"] = [new_account(id=f"a{n}") for n in range(11)]
        with self.assertRaises(ValueError):
            validate(data)
        data["integrations"]["mail"]["accounts"] = ["not a dict"]
        with self.assertRaises(ValueError):
            validate(data)

    def test_mail_alert_source_must_be_all_or_an_existing_account(self):
        data = defaults()
        data["integrations"]["mail"]["accounts"] = [new_account(id="acct1")]
        device_id = data["devices"][0]["id"]
        def rule(source):
            return {"id": "r1", "device_id": device_id, "metric": "mail_unread", "source": source, "text": "x"}
        for source in ("", "all", "acct1"):
            data["alerts"] = [rule(source)]
            validate(data)
        data["alerts"] = [rule("gone")]
        with self.assertRaises(ValueError):
            validate(data)

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
