"""Mail accounts: OAuth (Google / Microsoft), XOAUTH2 over IMAP, per-account samplers, widget and alert resolution.
Everything uses fake sessions, fake IMAP connections and a local loopback client; nothing touches the network."""
import base64
import copy
import imaplib
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import requests

from keeper import mail, oauth
from keeper.config import slot
from keeper.extensions import render_extra, validate_content
from keeper.mail import MailError, new_account
from keeper.widgets import Providers
from test_extensions import FakeImap


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self.body, self.headers = status, body if body is not None else {}, headers or {}

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class FakeSession:
    """requests.Session stand-in: pops queued responses and records every POST."""
    def __init__(self, *responses):
        self.responses, self.posts = list(responses), []

    def post(self, url, data=None, timeout=None, headers=None):
        self.posts.append((url, dict(data)))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


GOOGLE = new_account(id="g1", name="Gmail", provider="google", user="me@gmail.test", host="", client_id="gid", client_secret="gsecret", refresh_token="RT-G")
MICROSOFT = new_account(id="m1", name="Work", provider="microsoft", user="me@corp.test", client_id="mid", tenant="contoso.onmicrosoft.com", refresh_token="RT-M")
IMAP = new_account(id="i1", name="Home", host="imap.test", user="user-secret", password="pw-secret")


class AuthorizeUrlTests(unittest.TestCase):
    def query(self, provider, account):
        url = oauth.build_authorize_url(provider, account, "http://127.0.0.1:5555/callback", "STATE", "CHALLENGE")
        parsed = urlparse(url)
        return parsed.scheme + "://" + parsed.netloc + parsed.path, {k: v[0] for k, v in parse_qs(parsed.query).items()}

    def test_google(self):
        base, q = self.query("google", GOOGLE)
        self.assertEqual(base, "https://accounts.google.com/o/oauth2/v2/auth")
        self.assertEqual(q, {"client_id": "gid", "response_type": "code", "redirect_uri": "http://127.0.0.1:5555/callback",
                             "scope": "https://mail.google.com/", "state": "STATE", "code_challenge": "CHALLENGE", "code_challenge_method": "S256",
                             "access_type": "offline", "prompt": "consent"})
        self.assertNotIn("gsecret", oauth.build_authorize_url("google", GOOGLE, "http://127.0.0.1:1/callback", "s", "c"))  # the secret never goes in the URL

    def test_microsoft_puts_the_tenant_in_the_path_and_has_no_google_extras(self):
        base, q = self.query("microsoft", MICROSOFT)
        self.assertEqual(base, "https://login.microsoftonline.com/contoso.onmicrosoft.com/oauth2/v2.0/authorize")
        self.assertEqual(q["scope"], "https://outlook.office.com/IMAP.AccessAsUser.All offline_access")
        self.assertEqual((q["code_challenge_method"], q["client_id"]), ("S256", "mid"))
        self.assertNotIn("access_type", q); self.assertNotIn("prompt", q)
        self.assertIn("/common/", self.query("microsoft", {**MICROSOFT, "tenant": ""})[0])  # blank means common

    def test_bad_tenant_and_provider_are_refused(self):
        with self.assertRaises(oauth.OAuthError):
            oauth.build_authorize_url("microsoft", {**MICROSOFT, "tenant": "evil.test/../x"}, "r", "s", "c")
        for tenant in ("..", ".x", ".", "a/b"):
            with self.assertRaises(oauth.OAuthError):
                oauth.build_authorize_url("microsoft", {**MICROSOFT, "tenant": tenant}, "r", "s", "c")
        with self.assertRaises(oauth.OAuthError):
            oauth.build_authorize_url("yahoo", MICROSOFT, "r", "s", "c")


class TokenEndpointTests(unittest.TestCase):
    def test_exchange_sends_the_secret_only_for_google(self):
        ok = {"access_token": "AT", "expires_in": 3599, "refresh_token": "RT"}
        session = FakeSession(FakeResponse(200, ok), FakeResponse(200, ok))
        self.assertEqual(oauth.exchange_code(session, "google", GOOGLE, "CODE", "VERIFIER", "http://127.0.0.1:1/callback")["refresh_token"], "RT")
        oauth.exchange_code(session, "microsoft", {**MICROSOFT, "client_secret": "should-not-be-sent"}, "CODE", "VERIFIER", "https://x.test/cb")
        (g_url, g), (m_url, m) = session.posts
        self.assertEqual(g_url, "https://oauth2.googleapis.com/token")
        self.assertEqual(g, {"grant_type": "authorization_code", "code": "CODE", "redirect_uri": "http://127.0.0.1:1/callback",
                             "code_verifier": "VERIFIER", "client_id": "gid", "client_secret": "gsecret"})
        self.assertEqual(m_url, "https://login.microsoftonline.com/contoso.onmicrosoft.com/oauth2/v2.0/token")
        self.assertNotIn("client_secret", m)
        self.assertEqual(m["code_verifier"], "VERIFIER")

    def test_refresh_returns_access_expiry_and_rotated_token(self):
        session = FakeSession(FakeResponse(200, {"access_token": "A1", "expires_in": 3600}),
                              FakeResponse(200, {"access_token": "A2", "expires_in": 60, "refresh_token": "NEW"}))
        self.assertEqual(oauth.refresh_access_token(session, "google", GOOGLE, "RT-G"), ("A1", 3600, None))
        self.assertEqual(oauth.refresh_access_token(session, "microsoft", MICROSOFT, "RT-M"), ("A2", 60, "NEW"))
        self.assertEqual(session.posts[0][1], {"grant_type": "refresh_token", "refresh_token": "RT-G", "client_id": "gid", "client_secret": "gsecret"})

    def test_failures_use_fixed_text_without_secrets(self):
        cases = [(FakeResponse(400, {"error": "invalid_grant", "error_description": "RT-G leaked gsecret"}), oauth.OAuthAuthError),
                 (FakeResponse(429, {}, {"Retry-After": "7"}), oauth.OAuthRateLimited), (FakeResponse(503, {}), oauth.OAuthError),
                 (FakeResponse(200, {"nope": 1}), oauth.OAuthError), (requests.ConnectionError("RT-G gsecret"), oauth.OAuthError)]
        for response, kind in cases:
            with self.assertRaises(kind) as caught:
                oauth.refresh_access_token(FakeSession(response), "google", GOOGLE, "RT-G")
            for secret in ("RT-G", "gsecret", "leaked"):
                self.assertNotIn(secret, str(caught.exception))
            if kind is oauth.OAuthAuthError:
                self.assertEqual(str(caught.exception), "token request failed (HTTP 400: invalid_grant)")
            self.assertIs(type(caught.exception), kind)


class MailTokenSourceTests(unittest.TestCase):
    def source(self, *responses, account=MICROSOFT, saved=None, now=None):
        self.clock = [100.0]
        self.session = FakeSession(*responses)
        return oauth.MailTokenSource(account, (lambda *a: saved.append(a)) if saved is not None else None, self.session, lambda: self.clock[0])

    def test_token_is_cached_and_refreshed_a_minute_before_expiry(self):
        s = self.source(FakeResponse(200, {"access_token": "A1", "expires_in": 3600}), FakeResponse(200, {"access_token": "A2", "expires_in": 3600}))
        self.assertEqual((s(), s()), ("A1", "A1")); self.assertEqual(len(self.session.posts), 1)
        self.clock[0] += 3539; self.assertEqual(s(), "A1")
        self.clock[0] += 2; self.assertEqual(s(), "A2"); self.assertEqual(len(self.session.posts), 2)

    def test_rotated_refresh_token_is_stored_with_the_account_id_and_old_value(self):
        saved = []
        s = self.source(FakeResponse(200, {"access_token": "A", "expires_in": 3600, "refresh_token": "RT-M2"}),
                        FakeResponse(200, {"access_token": "B", "expires_in": 1, "refresh_token": "RT-M2"}), saved=saved)
        s(); self.assertEqual(saved, [("m1", "RT-M2", "RT-M")])
        self.clock[0] += 5000; s()
        self.assertEqual(len(saved), 1)  # same token again: nothing to store
        self.assertEqual(self.session.posts[1][1]["refresh_token"], "RT-M2")  # the next refresh already uses the rotated one

    def test_dead_token_stops_all_network_calls(self):
        s = self.source(FakeResponse(400, {"error": "invalid_grant"}))
        for _ in range(3):
            with self.assertRaises(MailError) as caught:
                s()
            self.assertEqual(str(caught.exception), "authorization expired (reconnect)")
        self.assertEqual(len(self.session.posts), 1)

    def test_not_signed_in_without_a_refresh_token(self):
        s = self.source(account={**MICROSOFT, "refresh_token": ""})
        with self.assertRaises(MailError) as caught:
            s()
        self.assertEqual((str(caught.exception), self.session.posts), ("not signed in", []))

    def test_rate_limit_and_server_errors_back_off_without_marking_the_token_dead(self):
        s = self.source(FakeResponse(429, {}, {"Retry-After": "90"}), FakeResponse(503), FakeResponse(200, {"access_token": "A", "expires_in": 3600}))
        for _ in range(2):
            with self.assertRaises(MailError):
                s()
        self.assertEqual(len(self.session.posts), 1)  # blocked for 90 s: no second request
        self.clock[0] += 91
        with self.assertRaises(MailError):
            s()
        self.assertEqual(len(self.session.posts), 2)
        self.clock[0] += 30
        with self.assertRaises(MailError):
            s()
        self.assertEqual(len(self.session.posts), 2)  # transient backoff
        self.clock[0] += 61
        self.assertEqual(s(), "A")

    def test_cas_callback_only_writes_when_the_stored_token_is_unchanged(self):
        from types import SimpleNamespace
        from keeper.integrations import Bridge
        stored = {"integrations": {"mail": {"enabled": True, "accounts": [copy.deepcopy(MICROSOFT), copy.deepcopy(GOOGLE)]}}}
        engine = SimpleNamespace(store=SimpleNamespace(change=lambda fn: fn(stored)), demo=True)
        engine.renderer = SimpleNamespace(providers=SimpleNamespace(extra=SimpleNamespace()))
        bridge = Bridge(engine)
        self.addCleanup(bridge.notifications.close)
        tokens = lambda: [a["refresh_token"] for a in stored["integrations"]["mail"]["accounts"]]
        bridge.save_mail_token("m1", "RT-M2", "RT-M"); self.assertEqual(tokens(), ["RT-M2", "RT-G"])
        bridge.save_mail_token("m1", "RT-M3", "RT-M"); self.assertEqual(tokens(), ["RT-M2", "RT-G"])  # stale rotation: ignored
        bridge.save_mail_token("zzz", "X", "RT-G"); self.assertEqual(tokens(), ["RT-M2", "RT-G"])  # unknown (removed) account


class FakeOAuthImap(FakeImap):
    def __init__(self, *args, auth_error=None, **kw):
        super().__init__(*args, **kw)
        self.auth_error = auth_error

    def authenticate(self, mechanism, authobject):
        self.log.append(("authenticate", mechanism, authobject(b"")))
        if self.auth_error:
            raise self.auth_error


class XOAuth2ImapTests(unittest.TestCase):
    def fetch(self, fake, account, token="TOKEN", **kw):
        calls = []
        def connector(host, port, timeout, context):
            calls.append((host, port)); return fake
        return mail.fetch_unread(account, connector=connector, token_provider=(lambda: token) if token else None, **kw), calls

    def test_xoauth2_string_and_authenticate_call(self):
        self.assertEqual(mail.xoauth2("a@b.test", "tok"), b"user=a@b.test\x01auth=Bearer tok\x01\x01")
        fake = FakeOAuthImap()
        result, calls = self.fetch(fake, GOOGLE)
        self.assertEqual(result["unread"], 3)
        self.assertEqual(calls, [("imap.gmail.com", 993)])  # blank host -> provider default
        self.assertEqual(fake.log[0], ("authenticate", "XOAUTH2", b"user=me@gmail.test\x01auth=Bearer TOKEN\x01\x01"))
        self.assertNotIn("login", fake.log)  # never the password login
        self.assertEqual(self.fetch(FakeOAuthImap(), MICROSOFT)[1], [("outlook.office365.com", 993)])
        self.assertEqual(self.fetch(FakeOAuthImap(), {**GOOGLE, "host": "imap.custom.test", "port": 1993, "allow_custom_host": True})[1], [("imap.custom.test", 1993)])
        self.assertTrue(base64.b64encode(mail.xoauth2("a@b.test", "tok")).startswith(b"dXNlcj1h"))  # what imaplib puts on the wire

    def test_oauth_never_uses_cleartext_port_143_and_requires_a_token_provider(self):
        fake = FakeOAuthImap()
        with self.assertRaises(MailError):
            self.fetch(fake, {**GOOGLE, "port": 143})
        with self.assertRaises(MailError) as caught:
            self.fetch(fake, GOOGLE, token=None)
        self.assertEqual(str(caught.exception), "not signed in")
        self.assertEqual(fake.log, [])  # no connection was opened

    def test_token_provider_errors_pass_through_and_nothing_leaks(self):
        def provider():
            raise MailError("authorization expired (reconnect)")
        with self.assertRaises(MailError) as caught:
            mail.fetch_unread(GOOGLE, connector=lambda *a: FakeOAuthImap(), token_provider=provider)
        self.assertEqual(str(caught.exception), "authorization expired (reconnect)")
        self.assertIn("authorization expired (reconnect)", MailError.REASONS); self.assertIn("not signed in", MailError.REASONS)

    def test_rejected_token_is_an_authentication_failure_without_the_token_in_the_text(self):
        invalidated = []
        class Provider:
            def __call__(self): return "SECRET-TOKEN"
            def invalidate(self): invalidated.append(1)
        fake = FakeOAuthImap(auth_error=imaplib.IMAP4.error("AUTHENTICATE failed SECRET-TOKEN me@gmail.test"))
        with self.assertRaises(MailError) as caught:
            mail.fetch_unread(GOOGLE, connector=lambda *a: fake, token_provider=Provider())
        self.assertEqual(str(caught.exception), "authentication failed")
        for text in ("SECRET-TOKEN", "me@gmail.test", "gmail"):
            self.assertNotIn(text, str(caught.exception))
        self.assertEqual((invalidated, fake.log[-1]), ([1], "logout"))

    def test_plain_imap_is_unchanged(self):
        fake = FakeImap()
        result = mail.fetch_unread(IMAP, connector=lambda *a: fake)
        self.assertEqual(result["unread"], 3); self.assertIn("login", fake.log)
        with self.assertRaises(MailError):
            mail.fetch_unread({**IMAP, "password": ""}, connector=lambda *a: fake)


class LoopbackAndManualTests(unittest.TestCase):
    def test_loopback_flow_with_a_browser_that_follows_the_redirect(self):
        seen = {}
        def opener(url):
            q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
            seen["q"] = q
            def visit():
                requests.get(q["redirect_uri"], params={"code": "CODE-1", "state": q["state"]}, timeout=5)
            threading.Thread(target=visit, daemon=True).start()
            return True
        session = FakeSession(FakeResponse(200, {"access_token": "A", "expires_in": 3600, "refresh_token": "RT-NEW"}))
        token = oauth.connect_loopback("microsoft", MICROSOFT, opener, session, timeout=10)
        self.assertEqual(token, "RT-NEW")
        self.assertTrue(seen["q"]["redirect_uri"].startswith("http://127.0.0.1:"))
        post = session.posts[0][1]
        self.assertEqual((post["code"], post["redirect_uri"]), ("CODE-1", seen["q"]["redirect_uri"]))
        import hashlib
        challenge = base64.urlsafe_b64encode(hashlib.sha256(post["code_verifier"].encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, seen["q"]["code_challenge"])  # PKCE: the verifier belongs to the challenge that was sent

    def test_wrong_state_is_rejected_and_the_flow_times_out_without_exchanging(self):
        seen = []
        def opener(url):
            q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
            def visit():
                seen.append(requests.get(q["redirect_uri"], params={"code": "EVIL", "state": "WRONG"}, timeout=5).status_code)
            threading.Thread(target=visit, daemon=True).start()
            return True
        session = FakeSession()
        with self.assertRaises(oauth.OAuthError) as caught:
            oauth.connect_loopback("google", GOOGLE, opener, session, timeout=1)
        self.assertEqual(str(caught.exception), "timed out waiting for the sign-in")
        self.assertEqual((session.posts, seen), ([], [400]))

    def test_provider_error_and_browser_failure_have_fixed_messages(self):
        def deny(url):
            q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
            threading.Thread(target=lambda: requests.get(q["redirect_uri"], params={"error": "access_denied", "state": q["state"]}, timeout=5), daemon=True).start()
            return True
        with self.assertRaises(oauth.OAuthError) as caught:
            oauth.connect_loopback("google", GOOGLE, deny, FakeSession(), timeout=10)
        self.assertEqual(str(caught.exception), "sign-in was not authorized: access_denied")
        with self.assertRaises(oauth.OAuthError) as caught:
            oauth.connect_loopback("google", GOOGLE, lambda url: False, FakeSession(), timeout=10)
        self.assertEqual(str(caught.exception), "could not open the browser")

    def test_paste_back_flow(self):
        redirect = "https://login.microsoftonline.com/common/oauth2/nativeclient"
        url, verifier, state = oauth.begin_manual("microsoft", MICROSOFT, redirect)
        self.assertEqual(parse_qs(urlparse(url).query)["redirect_uri"], [redirect])
        ok = {"access_token": "A", "expires_in": 1, "refresh_token": "RT-PASTE"}
        for pasted in (f"{redirect}?code=C1&state={state}", f"{redirect}#code=C1&state={state}", f"code=C1&state={state}"):
            session = FakeSession(FakeResponse(200, ok))
            self.assertEqual(oauth.finish_manual(session, "microsoft", MICROSOFT, redirect, verifier, state, pasted), "RT-PASTE")
            self.assertEqual((session.posts[0][1]["code"], session.posts[0][1]["code_verifier"]), ("C1", verifier))
        for pasted in ("", "x" * 3000, f"{redirect}?code=C1&state=WRONG", f"{redirect}?code=C1", f"{redirect}?state={state}",
                       f"{redirect}?error=access_denied&state={state}"):
            session = FakeSession()
            with self.assertRaises(oauth.OAuthError) as caught:
                oauth.finish_manual(session, "microsoft", MICROSOFT, redirect, verifier, state, pasted)
            self.assertEqual(session.posts, [])
            for secret in ("C1", verifier, state):
                self.assertNotIn(secret, str(caught.exception))


class MailStateTests(unittest.TestCase):
    """Per-account samplers, the shared first-read budget and the combined state."""
    def setUp(self):
        patcher = patch("keeper.extensions.FIRST_READ_WAIT", 0)
        patcher.start(); self.addCleanup(patcher.stop)
        self.extra = Providers().extra
        self.counts = {"i1": 4, "i2": 6}

    def configure(self, *accounts, enabled=True):
        self.extra.mail_conf = {"enabled": enabled, "accounts": [copy.deepcopy(a) for a in accounts]}

    def settle(self, account="all", expect=None):
        for _ in range(300):
            data, error = self.extra.mail_state(account)
            if data is not None or (expect and error == expect):
                return data, error
            time.sleep(0.01)
        return data, error

    def fake_fetch(self, fail=()):
        def fetch(conf, **kw):
            if conf["id"] in fail:
                raise MailError("cannot connect")
            return {"unread": self.counts[conf["id"]], "subject": "Hello" if conf.get("show_subject") else None}
        return fetch

    def test_not_configured_and_missing_account(self):
        self.assertEqual(self.extra.mail_state(), (None, "not configured"))
        self.configure(IMAP, enabled=False)
        self.assertEqual(self.extra.mail_state(), (None, "not configured"))
        self.configure({**IMAP, "enabled": False})
        self.assertEqual(self.extra.mail_state(), (None, "not configured"))
        self.configure(IMAP)
        self.assertEqual(self.extra.mail_state("gone"), (None, "account missing"))

    def test_single_account_and_sum_with_partial_failure(self):
        second = {**IMAP, "id": "i2", "name": "Work", "show_subject": True}
        self.configure(IMAP, second)
        with patch("keeper.mail.fetch_unread", self.fake_fetch()):
            one, _ = self.settle("i2")
            self.assertEqual((one["unread"], one["subject"], one["failed"]), (6, "Hello", 0))
            self.assertEqual(one["accounts"], [{"id": "i2", "name": "Work", "unread": 6, "error": ""}])
            for _ in range(300):
                total, _ = self.extra.mail_state("all")
                if total and all(a["unread"] is not None for a in total["accounts"]):
                    break
                time.sleep(0.01)
            self.assertEqual((total["unread"], total["subject"], total["failed"]), (10, None, 0))
            self.assertEqual([a["id"] for a in total["accounts"]], ["i1", "i2"])
        with patch("keeper.mail.fetch_unread", self.fake_fetch(fail={"i2"})):
            self.configure(IMAP, {**second, "host": "other.test"})  # connection change -> new sampler -> fails
            partial, _ = self.settle("all", expect="never")
            for _ in range(300):
                partial, _ = self.extra.mail_state("all")
                if partial and partial["failed"]:
                    break
                time.sleep(0.01)
            self.assertEqual((partial["unread"], partial["failed"]), (4, 1))
            self.assertEqual([(a["id"], a["error"]) for a in partial["accounts"] if a["error"]], [("i2", "cannot connect")])

    def test_all_accounts_failing_is_an_error_not_zero(self):
        self.configure(IMAP, {**IMAP, "id": "i2"})
        with patch("keeper.mail.fetch_unread", self.fake_fetch(fail={"i1", "i2"})):
            self.assertEqual(self.settle("all", expect="cannot connect"), (None, "cannot connect"))

    def test_probes_are_lazy_single_flight_and_rebuilt_only_when_the_connection_changes(self):
        gate = threading.Event()
        calls = []
        def slow(conf, **kw):
            calls.append(conf["id"]); gate.wait(2); return {"unread": 1, "subject": None}
        self.configure(IMAP, {**IMAP, "id": "i2"})
        with patch("keeper.mail.fetch_unread", slow):
            self.assertEqual(calls, [])  # nothing sampled before the first read
            for _ in range(5):
                self.extra.mail_state("all")
            time.sleep(0.1)
            self.assertEqual(sorted(calls), ["i1", "i2"])  # one in-flight fetch per account
            gate.set()
            self.settle("all")
            before = {k: v["probe"] for k, v in self.extra.mail_probes.items()}
            self.configure({**IMAP, "name": "Renamed", "enabled": True}, {**IMAP, "id": "i2"})  # a rename is not a connection change
            self.extra.mail_state("all")
            self.assertTrue(all(self.extra.mail_probes[k]["probe"] is before[k] for k in before))
            self.configure({**IMAP, "password": "new-pw"}, {**IMAP, "id": "i2"})
            self.extra.mail_state("all")
            self.assertIsNot(self.extra.mail_probes["i1"]["probe"], before["i1"])
            self.assertIs(self.extra.mail_probes["i2"]["probe"], before["i2"])
            self.configure({**IMAP, "password": "new-pw"})  # an account that is gone loses its sampler
            self.extra.mail_state("all")
            self.assertEqual(list(self.extra.mail_probes), ["i1"])

    def test_oauth_probe_survives_token_rotation_but_not_a_reconnect(self):
        self.configure(GOOGLE)
        with patch("keeper.mail.fetch_unread", lambda conf, **kw: {"unread": 2, "subject": None}):
            self.settle("g1")
            first = self.extra.mail_probes["g1"]
            self.assertIsInstance(first["source"], oauth.MailTokenSource)
            first["source"].refresh_token = "RT-ROTATED"  # the source rotated it and the CAS wrote the same value to the config
            self.configure({**GOOGLE, "refresh_token": "RT-ROTATED"}); self.extra.mail_state("g1")
            self.assertIs(self.extra.mail_probes["g1"], first)
            self.configure({**GOOGLE, "refresh_token": "RT-RECONNECT"}); self.extra.mail_state("g1")
            self.assertIsNot(self.extra.mail_probes["g1"], first)
            self.assertEqual(self.extra.mail_probes["g1"]["source"].initial_token, "RT-RECONNECT")

    def test_first_read_of_several_accounts_shares_one_budget(self):
        release = threading.Event()
        self.addCleanup(release.set)
        self.configure(*[{**IMAP, "id": f"a{n}"} for n in range(4)])
        with patch("keeper.extensions.FIRST_READ_WAIT", 0.4), patch("keeper.mail.fetch_unread", lambda conf, **kw: (release.wait(5), {"unread": 1, "subject": None})[1]):
            started = time.monotonic()
            data, error = self.extra.mail_state("all")
            elapsed = time.monotonic() - started
        self.assertIsNone(data); self.assertTrue(error.startswith("Waiting"))
        self.assertLess(elapsed, 0.9)  # 4 accounts x 0.4 s would be 1.6 s

    def test_legacy_flat_conf_still_works_in_the_sampler(self):
        self.extra.mail_conf = {"enabled": True, "host": "imap.test", "port": 993, "user": "u", "password": "p", "mailbox": "INBOX", "show_subject": False}
        with patch("keeper.mail.fetch_unread", lambda conf, **kw: {"unread": 9, "subject": None}):
            data, _ = self.settle("main")
        self.assertEqual(data["unread"], 9)

    def test_legacy_mail_wrapper_is_the_combined_count(self):
        self.configure(IMAP)
        with patch("keeper.mail.fetch_unread", self.fake_fetch()):
            self.settle("all")
            self.assertEqual(self.extra.mail()["unread"], 4)


class RenderTests(unittest.TestCase):
    ROW = [{"id": "i1", "name": "Home", "unread": 3, "error": ""}]

    def draw(self, state, **screen):
        p = Providers()
        with patch.object(p.extra, "mail_state", return_value=state) as mocked:
            image = render_extra(slot("mail", **screen), p)
        return image, mocked

    def test_screen_account_is_passed_to_mail_state(self):
        _, state = self.draw((None, "not configured"))
        state.assert_called_with("all")
        _, state = self.draw((None, "not configured"), mail_account="abc12")
        state.assert_called_with("abc12")

    def test_states_render_differently(self):
        single = ({"unread": 3, "subject": None, "accounts": self.ROW, "failed": 0}, "")
        failed = ({"unread": 3, "subject": None, "accounts": self.ROW, "failed": 2}, "")
        images = {name: self.draw(state, **kw)[0].tobytes() for name, state, kw in (
            ("single", single, {"mail_account": "i1"}), ("all", single, {}), ("failed", failed, {}), ("failed-single", failed, {"mail_account": "i1"}),
            ("missing", (None, "account missing"), {}), ("unconfigured", (None, "not configured"), {}))}
        self.assertNotEqual(images["single"], images["all"])      # account name vs "All accounts"
        self.assertNotEqual(images["all"], images["failed"])      # red "!" and "N account(s) failed"
        self.assertEqual(images["single"], images["failed-single"])  # a single-account widget never shows the combined failure marker
        self.assertNotEqual(images["missing"], images["unconfigured"])
        red = self.draw(({"unread": 3, "subject": None, "accounts": self.ROW, "failed": 1}, ""))[0]
        self.assertIn((255, 77, 77), red.getdata())
        self.assertIn((255, 107, 107), self.draw((None, "account missing"))[0].getdata())  # red text

    def test_validate_content(self):
        for value in ("all", "abc123", "a"):
            validate_content(slot("mail", mail_account=value))
        for value in (5, None, "UPPER", "has space", "", "x" * 17):
            with self.assertRaises(ValueError, msg=repr(value)):
                validate_content(slot("mail", mail_account=value))
        validate_content(slot("mail"))


if __name__ == "__main__":
    unittest.main()


class HostPinningTests(unittest.TestCase):
    def fetch(self, **values):
        from keeper.mail import fetch_unread, MailError
        calls = []
        def connector(host, port, timeout, context):
            calls.append(host)
            raise OSError("no network")
        account = {**GOOGLE, **values}
        with self.assertRaises(MailError) as caught:
            fetch_unread(account, connector=connector, token_provider=lambda: "TOKEN")
        return str(caught.exception), calls

    def test_oauth_token_is_never_sent_to_an_unpinned_host(self):
        self.assertEqual(self.fetch(host="imap.attacker.example"), ("protocol error", []))
        self.assertEqual(self.fetch(provider="microsoft", host="imap.gmail.com"), ("protocol error", []))
        self.assertEqual(self.fetch(host="imap.gmail.com.attacker.example"), ("protocol error", []))

    def test_pinned_and_default_hosts_connect(self):
        self.assertEqual(self.fetch(host="")[1], ["imap.gmail.com"])
        self.assertEqual(self.fetch(host="imap.gmail.com")[1], ["imap.gmail.com"])
        for host in ("outlook.office365.com", "outlook.office.com"):
            self.assertEqual(self.fetch(provider="microsoft", host=host)[1], [host])

    def test_allow_custom_host_permits_another_server(self):
        self.assertEqual(self.fetch(host="imap.own.example", allow_custom_host=True)[1], ["imap.own.example"])
        self.assertEqual(self.fetch(host="imap.own.example", allow_custom_host="yes"), ("protocol error", []))

    def test_plain_imap_is_unaffected(self):
        from keeper.mail import host_allowed
        self.assertTrue(host_allowed({"provider": "imap", "host": "mail.anywhere.example"}))

    def test_xoauth2_refuses_a_user_with_the_sasl_separator(self):
        from keeper.mail import xoauth2, MailError
        with self.assertRaises(MailError):
            xoauth2("me@x.test\x01auth=Bearer evil", "T")
        self.assertIn(b"user=me@x.test", xoauth2("me@x.test", "T"))
