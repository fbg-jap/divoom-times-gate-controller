"""Portal OAuth routes (POST /api/oauth/start, GET /api/oauth/callback, POST /api/oauth/complete) with a fake HTTP session."""
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from keeper.mail import new_account
from keeper.portal import create_app

TOKEN = "unit-test-token-at-least-24-characters"
SECRET = "GOOGLE-CLIENT-SECRET-VALUE"
REFRESH = "THE-REFRESH-TOKEN"
CODE = "AUTH-CODE-123"


class Reply:
    def __init__(self, status=200, body=None):
        self.status_code, self.body, self.headers = status, body, {}

    def json(self):
        return self.body


class FakeSession:
    """Records every token request; answers from a queue (default: a good token response). No network."""
    def __init__(self, replies=()):
        self.replies, self.calls = list(replies), []

    def post(self, url, data=None, **kw):
        self.calls.append((url, dict(data or {})))
        if self.replies:
            return self.replies.pop(0)
        return Reply(200, {"access_token": "ACCESS", "expires_in": 3600, "refresh_token": REFRESH})


class Clock:
    now = 1000.

    def __call__(self):
        return self.now


class OAuthPortalCase(unittest.TestCase):
    base_url = "http://127.0.0.1:8765"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.app = create_app(Path(self.temp.name), token=TOKEN, demo=True, shell_mode=True, clock=self.clock)
        self.client = TestClient(self.app, base_url=self.base_url).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.auth = {"Authorization": "Bearer " + TOKEN}
        self.session = FakeSession()
        self.app.state.oauth_session = lambda: self.session
        self.store = self.app.state.store

    def add_account(self, **values):
        account = new_account(id="acc1", name="Work", provider="google", user="me@example.test", client_id="google-client-id.apps.test",
                              client_secret=SECRET, **values)
        self.store.change(lambda d: d["integrations"].update(mail={"enabled": True, "accounts": [account]}))
        return account

    def start(self, **body):
        return self.client.post("/api/oauth/start", json=body, headers=self.auth)

    def account(self):
        return self.store.snapshot()["integrations"]["mail"]["accounts"][0]

    def assertNoSecrets(self, *responses):
        everything = json.dumps(list(self.app.state.engine.activity), default=str)
        for text in [r.text for r in responses] + [everything]:
            for secret in (REFRESH, CODE, SECRET, "ACCESS", TOKEN):
                self.assertNotIn(secret, text)


class StartTests(OAuthPortalCase):
    def test_start_and_complete_require_the_bearer_token(self):
        for path in ("/api/oauth/start", "/api/oauth/complete"):
            self.assertEqual(self.client.post(path, json={}).status_code, 401, path)
            self.assertEqual(self.client.post(path, json={}, headers={"Authorization": "Bearer nope"}).status_code, 401, path)
        self.assertIn(self.client.get("/api/oauth/start", headers=self.auth).status_code, {404, 405})

    def test_loopback_start_for_mail_returns_the_portal_callback_and_pkce_challenge(self):
        self.add_account()
        response = self.start(service="mail", account_id="acc1")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["mode"], body["redirect_uri"]), ("loopback", self.base_url + "/api/oauth/callback"))
        query = parse_qs(urlparse(body["authorize_url"]).query)
        self.assertEqual(urlparse(body["authorize_url"]).netloc, "accounts.google.com")
        self.assertEqual(query["state"], [body["state"]])
        self.assertEqual((query["code_challenge_method"], query["redirect_uri"]), (["S256"], [body["redirect_uri"]]))
        entry = self.app.state.oauth_pending.items[body["state"]]
        self.assertNotIn(entry["verifier"], response.text)  # the verifier never leaves the server
        self.assertNotIn(SECRET, response.text)

    def test_unknown_service_account_and_non_oauth_account(self):
        self.add_account()
        self.assertEqual(self.start(service="github").status_code, 400)
        self.assertEqual(self.start(service="mail", account_id="nope").status_code, 400)
        self.assertEqual(self.start(service="mail").status_code, 400)
        self.assertEqual(self.start(service="mail", account_id=5).status_code, 400)
        self.store.change(lambda d: d["integrations"]["mail"]["accounts"][0].update(provider="imap"))
        self.assertEqual(self.start(service="mail", account_id="acc1").status_code, 400)

    def test_google_needs_a_secret_and_everyone_a_client_id(self):
        self.add_account()
        self.store.change(lambda d: d["integrations"]["mail"]["accounts"][0].update(client_secret=""))
        self.assertEqual(self.start(service="mail", account_id="acc1").status_code, 400)
        self.store.change(lambda d: d["integrations"]["mail"]["accounts"][0].update(provider="microsoft", client_id=""))
        self.assertEqual(self.start(service="mail", account_id="acc1").status_code, 400)
        self.assertEqual(self.start(service="spotify").status_code, 400)
        self.assertEqual(self.start(service="spotify", client_id="bad id&x=1").status_code, 400)

    def test_non_loopback_http_portal_is_refused_unless_the_redirect_is_https(self):
        self.add_account()
        plain = create_app(Path(self.temp.name) / "plain", token=TOKEN, demo=True)
        with TestClient(plain, base_url="http://portal.example.test") as client:
            plain.state.store.change(lambda d: d["integrations"].update(mail={"enabled": True, "accounts": [new_account(
                id="acc1", provider="microsoft", client_id="ms-client", user="u@x.test")]}))
            r = client.post("/api/oauth/start", json={"service": "mail", "account_id": "acc1"}, headers=self.auth)
            self.assertEqual(r.status_code, 400)
            self.assertIn("127.0.0.1", r.json()["error"])
            plain.state.store.change(lambda d: d["integrations"]["mail"]["accounts"][0].update(redirect_uri="https://keeper.example.test/done"))
            self.assertEqual(client.post("/api/oauth/start", json={"service": "mail", "account_id": "acc1"}, headers=self.auth).json()["mode"], "manual")

    def test_invalid_redirect_uris_are_refused(self):
        self.add_account()
        for bad in ("http://example.test/cb", "ftp://x.test", "https://u:p@x.test/cb", "https://x.test/cb#frag"):
            self.assertEqual(self.start(service="mail", account_id="acc1", redirect_uri=bad).status_code, 400, bad)

    def test_at_most_twenty_pending_attempts(self):
        self.add_account()
        for _ in range(40):
            self.start(service="mail", account_id="acc1")
        self.assertLessEqual(len(self.app.state.oauth_pending.items), 20)


class LoopbackCallbackTests(OAuthPortalCase):
    def state(self, service="mail", **body):
        if service == "mail":
            self.add_account()
            body = {"account_id": "acc1", **body}
        return self.start(service=service, client_id="abcdef1234567890" if service == "spotify" else None, **body).json()["state"]

    def test_mail_flow_stores_the_token_with_the_stored_client_settings(self):
        state = self.state()
        ok = self.client.get(f"/api/oauth/callback?code={CODE}&state={state}")  # no Authorization header
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(self.account()["refresh_token"], REFRESH)
        url, payload = self.session.calls[0]
        self.assertEqual(url, "https://oauth2.googleapis.com/token")
        self.assertEqual((payload["code"], payload["client_secret"], payload["redirect_uri"]), (CODE, SECRET, self.base_url + "/api/oauth/callback"))
        self.assertTrue(payload["code_verifier"])
        self.assertNoSecrets(ok)
        self.assertEqual(self.client.get(f"/api/oauth/callback?code={CODE}&state={state}").status_code, 400)  # single use
        self.assertEqual(len(self.session.calls), 1)

    def test_spotify_flow_stores_token_and_client_id(self):
        state = self.state("spotify")
        ok = self.client.get(f"/api/oauth/callback?code={CODE}&state={state}")
        self.assertEqual(ok.status_code, 200, ok.text)
        saved = self.store.snapshot()["integrations"]["spotify"]
        self.assertEqual((saved["refresh_token"], saved["client_id"]), (REFRESH, "abcdef1234567890"))
        self.assertNoSecrets(ok)

    def test_a_new_sign_in_replaces_the_stored_token(self):
        self.add_account(refresh_token="OLD")
        state = self.start(service="mail", account_id="acc1").json()["state"]
        self.assertEqual(self.client.get(f"/api/oauth/callback?code={CODE}&state={state}").status_code, 200)
        self.assertEqual(self.account()["refresh_token"], REFRESH)

    def test_wrong_unissued_missing_and_expired_state(self):
        state = self.state()
        for query in ("code=c&state=never-issued", f"code=c", "state=", f"code=c&state={state}x", f"code=c&state={state[:-1]}"):
            self.assertEqual(self.client.get("/api/oauth/callback?" + query).status_code, 400, query)
        self.assertEqual(self.session.calls, [])
        self.clock.now += 301
        self.assertEqual(self.client.get(f"/api/oauth/callback?code=c&state={state}").status_code, 400)
        self.assertEqual(self.account()["refresh_token"], "")
        self.assertEqual(self.session.calls, [])

    def test_denied_callback_stores_nothing_and_consumes_the_state(self):
        state = self.state()
        self.assertEqual(self.client.get(f"/api/oauth/callback?error=access_denied&state={state}").status_code, 400)
        self.assertEqual(self.client.get(f"/api/oauth/callback?code={CODE}&state={state}").status_code, 400)
        self.assertEqual((self.account()["refresh_token"], self.session.calls), ("", []))

    def test_provider_error_stores_nothing_and_reveals_nothing(self):
        self.session.replies = [Reply(400, {"error": "invalid_client", "error_description": f"bad {SECRET} {CODE}"})]
        state = self.state()
        failed = self.client.get(f"/api/oauth/callback?code={CODE}&state={state}")
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(self.account()["refresh_token"], "")
        self.assertNoSecrets(failed)
        self.assertNotIn("invalid_client", failed.text)

    def test_a_manual_state_cannot_be_used_on_the_callback(self):
        self.add_account(redirect_uri="https://keeper.example.test/done")
        state = self.start(service="mail", account_id="acc1").json()["state"]
        self.assertEqual(self.client.get(f"/api/oauth/callback?code={CODE}&state={state}").status_code, 400)
        self.assertEqual(self.session.calls, [])

    def test_account_removed_meanwhile(self):
        state = self.state()
        self.store.change(lambda d: d["integrations"]["mail"].update(accounts=[]))
        self.assertEqual(self.client.get(f"/api/oauth/callback?code={CODE}&state={state}").status_code, 502)

    def test_nothing_is_reflected_into_the_page(self):
        state = self.state()
        probe = self.client.get("/api/oauth/callback?code=<script>alert(1)</script>&error=<b>x</b>&state=" + state)
        self.assertNotIn("script", probe.text)
        self.assertNotIn("<b>", probe.text)
        bad = self.client.get("/api/oauth/callback?state=%3Cscript%3E")
        self.assertNotIn("script", bad.text)

    def test_failure_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.client.get("/api/oauth/callback?code=c&state=wrong").status_code, 400)
        state = self.state()
        self.assertEqual(self.client.get(f"/api/oauth/callback?code={CODE}&state={state}").status_code, 429)
        self.assertEqual(self.session.calls, [])
        self.clock.now += 61
        state = self.start(service="mail", account_id="acc1").json()["state"]
        self.assertEqual(self.client.get(f"/api/oauth/callback?code={CODE}&state={state}").status_code, 200)

    def test_exemption_is_exact(self):
        state = self.state()
        for method, path in [("GET", "/api/oauth/callback/"), ("GET", "//api/oauth/callback"), ("GET", "/API/oauth/callback"),
                             ("GET", "/api/oauth/callback/x"), ("GET", "/api/oauth/callbackx"), ("GET", "/api/oauth/callback%2F"),
                             ("POST", "/api/oauth/callback"), ("PUT", "/api/oauth/callback"), ("DELETE", "/api/oauth/callback"),
                             ("GET", "/api/oauth/start"), ("GET", "/api/oauth/complete"), ("GET", "/api/oauth/")]:
            response = self.client.request(method, path + f"?code={CODE}&state={state}")
            self.assertIn(response.status_code, {401, 404, 405}, (method, path))
        self.assertEqual(self.session.calls, [])
        # None of the attempts consumed the state.
        self.assertEqual(self.client.get(f"/api/oauth/callback?code={CODE}&state={state}").status_code, 200)

    def test_callback_is_refused_for_a_foreign_host_in_shell_mode(self):
        state = self.state()
        response = self.client.get(f"/api/oauth/callback?code={CODE}&state={state}", headers={"Host": "evil.example"})
        self.assertEqual(response.status_code, 421)
        self.assertEqual(self.session.calls, [])


class ManualCompleteTests(OAuthPortalCase):
    REDIRECT = "https://keeper.example.test/spotify-done"

    def begin(self, service="mail", **extra):
        if service == "mail":
            self.add_account(redirect_uri=self.REDIRECT)
            body = self.start(service="mail", account_id="acc1", **extra).json()
        else:
            self.store.change(lambda d: d["integrations"]["spotify"].update(client_id="abcdef1234567890", redirect_uri=self.REDIRECT))
            body = self.start(service="spotify", **extra).json()
        self.assertEqual((body["mode"], body["redirect_uri"]), ("manual", self.REDIRECT))
        return body

    def complete(self, state, pasted, **kwargs):
        return self.client.post("/api/oauth/complete", json={"state": state, "pasted": pasted}, **{"headers": self.auth, **kwargs})

    def test_mail_paste_back_success_uses_the_same_redirect_uri_and_server_side_verifier(self):
        body = self.begin()
        verifier = self.app.state.oauth_pending.items[body["state"]]["verifier"]
        self.assertEqual(parse_qs(urlparse(body["authorize_url"]).query)["redirect_uri"], [self.REDIRECT])
        done = self.complete(body["state"], f"{self.REDIRECT}?code={CODE}&state={body['state']}")
        self.assertEqual((done.status_code, done.json()), (200, {"connected": True}))
        self.assertEqual(self.account()["refresh_token"], REFRESH)
        payload = self.session.calls[0][1]
        self.assertEqual((payload["redirect_uri"], payload["code_verifier"], payload["code"]), (self.REDIRECT, verifier, CODE))
        self.assertNoSecrets(done)
        self.assertEqual(self.complete(body["state"], f"?code={CODE}&state={body['state']}").status_code, 400)  # reused
        self.assertEqual(len(self.session.calls), 1)

    def test_spotify_paste_back(self):
        body = self.begin("spotify")
        done = self.complete(body["state"], f"{self.REDIRECT}?code={CODE}&state={body['state']}")
        self.assertEqual(done.json(), {"connected": True})
        self.assertEqual(self.store.snapshot()["integrations"]["spotify"]["refresh_token"], REFRESH)
        self.assertEqual(self.session.calls[0][1]["redirect_uri"], self.REDIRECT)

    def test_bare_query_string_is_accepted_too(self):
        body = self.begin()
        self.assertEqual(self.complete(body["state"], f"code={CODE}&state={body['state']}").status_code, 200)

    def test_bad_pastes_fail_with_fixed_messages_and_consume_the_attempt(self):
        for pasted in ("", "x" * 5000, f"{self.REDIRECT}?code={CODE}&state=other", f"{self.REDIRECT}?state=SAME-STATE", f"{self.REDIRECT}?error=access_denied"):
            body = self.begin()
            pasted = pasted.replace("SAME-STATE", body["state"])
            failed = self.complete(body["state"], pasted)
            self.assertEqual(failed.status_code, 400, pasted[:40])
            self.assertNotIn(CODE, failed.text)
            self.assertEqual(self.complete(body["state"], f"?code={CODE}&state={body['state']}").status_code, 400)
        self.assertEqual((self.account()["refresh_token"], self.session.calls), ("", []))

    def test_redirect_uri_mismatch_at_the_provider_is_reported_without_details(self):
        self.session.replies = [Reply(400, {"error": "redirect_uri_mismatch", "error_description": f"{CODE} {SECRET}"})]
        body = self.begin()
        failed = self.complete(body["state"], f"{self.REDIRECT}?code={CODE}&state={body['state']}")
        self.assertEqual(failed.status_code, 400)
        self.assertNotIn("redirect_uri_mismatch", failed.text)
        self.assertEqual(self.account()["refresh_token"], "")
        self.assertNoSecrets(failed)

    def test_the_client_cannot_change_the_redirect_uri_at_completion(self):
        body = self.begin()
        done = self.client.post("/api/oauth/complete", headers=self.auth, json={
            "state": body["state"], "pasted": f"code={CODE}&state={body['state']}", "redirect_uri": "https://evil.example/cb"})
        self.assertEqual(done.status_code, 200)
        self.assertEqual(self.session.calls[0][1]["redirect_uri"], self.REDIRECT)

    def test_wrong_unknown_expired_and_loopback_states(self):
        body = self.begin()
        self.assertEqual(self.complete("never-issued", "code=c&state=never-issued").status_code, 400)
        self.assertEqual(self.client.post("/api/oauth/complete", json={"state": 5, "pasted": "x"}, headers=self.auth).status_code, 400)
        self.assertEqual(self.client.post("/api/oauth/complete", json={"state": "x"}, headers=self.auth).status_code, 400)
        self.clock.now += 301
        self.assertEqual(self.complete(body["state"], f"code={CODE}&state={body['state']}").status_code, 400)
        self.store.change(lambda d: d["integrations"]["mail"]["accounts"][0].update(redirect_uri=""))
        loop = self.start(service="mail", account_id="acc1").json()
        self.assertEqual(loop["mode"], "loopback")
        self.assertEqual(self.complete(loop["state"], f"code={CODE}&state={loop['state']}").status_code, 400)  # callback-only state
        self.assertEqual(self.session.calls, [])

    def test_failure_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.complete("wrong", "code=c&state=wrong").status_code, 400)
        body = self.begin()
        self.assertEqual(self.complete(body["state"], f"code={CODE}&state={body['state']}").status_code, 429)
        self.assertEqual(self.session.calls, [])
        self.clock.now += 61
        body = self.begin()
        self.assertEqual(self.complete(body["state"], f"code={CODE}&state={body['state']}").status_code, 200)

    def test_cross_origin_complete_is_rejected(self):
        body = self.begin()
        r = self.complete(body["state"], f"code={CODE}&state={body['state']}", headers={**self.auth, "Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.session.calls, [])


class StateEndpointTests(OAuthPortalCase):
    def test_legacy_spotify_routes_still_work_next_to_the_new_ones(self):
        self.app.state.spotify_session = lambda: self.session
        r = self.client.post("/api/spotify/connect", json={"client_id": "abcdef1234567890"}, headers=self.auth)
        self.assertEqual(r.status_code, 200)
        state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
        self.assertEqual(self.client.get(f"/api/spotify/callback?code={CODE}&state={state}").status_code, 200)
        self.assertEqual(self.store.snapshot()["integrations"]["spotify"]["refresh_token"], REFRESH)
        # a legacy state is not valid on the new callback and vice versa
        legacy = self.client.post("/api/spotify/connect", json={"client_id": "abcdef1234567890"}, headers=self.auth)
        legacy_state = parse_qs(urlparse(legacy.json()["url"]).query)["state"][0]
        self.assertEqual(self.client.get(f"/api/oauth/callback?code={CODE}&state={legacy_state}").status_code, 400)


if __name__ == "__main__":
    unittest.main()
