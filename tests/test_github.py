import json
import tempfile
import unittest
from pathlib import Path

import requests

from keeper.config import ConfigStore, slot
from keeper.extensions import ExtraSources, validate_content, validate_new_integrations
from keeper.widgets import GITHUB_API, Providers, Renderer, github_reason


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self.headers = status, headers or {}
        self.body = json.dumps(body if body is not None else {}).encode()

    def iter_content(self, size):
        yield self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("boom https://api.github.com/secret-url", response=self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, response):
        self.response, self.calls = response, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


SEARCH = {"total_count": 7, "items": [
    {"number": 12, "title": "Fix the thing", "repository_url": "https://api.github.com/repos/acme/keeper",
     "user": {"login": "ana"}, "draft": True},
    {"number": 9, "title": "Another", "repository_url": "https://api.github.com/repos/acme/web", "user": {"login": "bo"}}]}


class FetchTests(unittest.TestCase):
    def providers(self, response):
        providers = Providers(demo=False)
        providers.session = FakeSession(response)
        return providers

    def test_search_request_and_parsing(self):
        providers = self.providers(FakeResponse(body=SEARCH))
        result = providers.github_fetch("tok123", "is:pr is:open author:@me")
        url, kwargs = providers.session.calls[0]
        self.assertEqual(url, GITHUB_API + "/search/issues")
        self.assertEqual(kwargs["params"]["q"], "is:pr is:open author:@me")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok123")
        self.assertIs(kwargs["allow_redirects"], False)
        self.assertEqual(result["count"], 7)
        self.assertEqual(result["items"][0], {"number": 12, "title": "Fix the thing", "repo": "acme/keeper", "author": "ana", "draft": True})

    def test_no_token_sends_no_authorization(self):
        providers = self.providers(FakeResponse(body=SEARCH))
        providers.github_fetch("", "is:pr repo:acme/keeper")
        self.assertNotIn("Authorization", providers.session.calls[0][1]["headers"])

    def test_ci_state_from_the_latest_run(self):
        def run(status, conclusion):
            return FakeResponse(body={"workflow_runs": [{"status": status, "conclusion": conclusion, "name": "CI", "head_branch": "main", "event": "push"}]})
        for status, conclusion, state in (("completed", "success", "success"), ("completed", "failure", "failure"), ("completed", "timed_out", "failure"),
                                          ("in_progress", None, "running"), ("completed", "cancelled", "other")):
            providers = self.providers(run(status, conclusion))
            result = providers.github_ci("tok", "acme/keeper")
            self.assertEqual(result, {"state": state, "name": "CI", "branch": "main", "event": "push"})
        self.assertEqual(providers.session.calls[0][0], GITHUB_API + "/repos/acme/keeper/actions/runs")
        self.assertEqual(providers.session.calls[0][1]["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(self.providers(FakeResponse(body={"workflow_runs": []})).github_ci("", "a/b")["state"], "none")

    def test_reasons_are_fixed_texts_without_urls_or_tokens(self):
        def error(status, headers=None):
            return requests.HTTPError("x https://api.github.com/?access_token=SECRET", response=FakeResponse(status, headers=headers))
        self.assertEqual(github_reason(error(401)), "bad token")
        self.assertEqual(github_reason(error(403, {"X-RateLimit-Remaining": "0"})), "rate limited")
        self.assertEqual(github_reason(error(429)), "rate limited")
        self.assertEqual(github_reason(error(403)), "access denied")
        self.assertEqual(github_reason(error(422)), "repository not found")
        self.assertEqual(github_reason(error(500)), "unexpected response")
        self.assertEqual(github_reason(requests.ConnectTimeout("SECRET")), "timeout")
        self.assertEqual(github_reason(requests.ConnectionError("SECRET")), "cannot connect")


class StateTests(unittest.TestCase):
    def extra(self, conf, response=None):
        providers = Providers(demo=False)
        providers.session = FakeSession(response or FakeResponse(body=SEARCH))
        extra = ExtraSources(providers)
        extra.github_conf = conf
        return extra

    def test_unconfigured_and_missing_inputs_do_not_call_the_api(self):
        extra = self.extra({"enabled": False, "token": "t"})
        self.assertEqual(extra.github_state({"github_query": "review"}), (None, "not configured"))
        extra = self.extra({"enabled": True, "token": ""})
        self.assertEqual(extra.github_state({"github_query": "review"}), (None, "token required"))
        self.assertEqual(extra.github_state({"github_query": "repo", "github_repo": "nonsense"}), (None, "choose a repository"))
        self.assertEqual(extra.providers.session.calls, [])

    def test_public_repo_works_without_a_token_and_each_query_has_its_own_sampler(self):
        extra = self.extra({"enabled": True, "token": ""})
        data, error = extra.github_state({"github_query": "repo", "github_repo": "acme/keeper"})
        self.assertEqual((error, data["count"]), ("", 7))
        self.assertIn("repo:acme/keeper", extra.providers.session.calls[0][1]["params"]["q"])
        extra.github_conf = {"enabled": True, "token": "t"}
        extra.github_state({"github_query": "mine"})
        extra.github_state({"github_query": "review"})
        self.assertEqual(len(extra.github_probes), 3)
        extra.github_state({"github_query": "mine"})
        self.assertEqual(len(extra.github_probes), 3)

    def test_failure_reason_reaches_the_screen_without_the_token(self):
        extra = self.extra({"enabled": True, "token": "SECRET-TOKEN"}, FakeResponse(401))
        data, error = extra.github_state({"github_query": "mine"})
        self.assertIsNone(data)
        self.assertEqual(error, "bad token")
        self.assertNotIn("SECRET", error)


class NewQueryTests(unittest.TestCase):
    extra = StateTests.extra

    def test_issue_and_mention_queries_use_the_token_owner(self):
        extra = self.extra({"enabled": True, "token": "t"})
        extra.github_state({"github_query": "issues"})
        extra.github_state({"github_query": "mentions"})
        queries = [call[1]["params"]["q"] for call in extra.providers.session.calls]
        self.assertTrue(any("is:issue" in q and "assignee:@me" in q for q in queries))
        self.assertTrue(any("mentions:@me" in q for q in queries))
        self.assertEqual(self.extra({"enabled": True, "token": ""}).github_state({"github_query": "issues"}), (None, "token required"))

    def test_ci_needs_a_repository_and_works_without_a_token(self):
        extra = self.extra({"enabled": True, "token": ""}, FakeResponse(body={"workflow_runs": [{"status": "completed", "conclusion": "success", "name": "CI"}]}))
        self.assertEqual(extra.github_state({"github_query": "ci"}), (None, "choose a repository"))
        data, error = extra.github_state({"github_query": "ci", "github_repo": "acme/keeper"})
        self.assertEqual((error, data["state"]), ("", "success"))


class ValidationAndRenderTests(unittest.TestCase):
    def test_slot_validation(self):
        validate_content(slot("github", github_query="repo", github_repo="acme/keeper"))
        validate_content(slot("github"))
        for query in ("issues", "mentions", "ci"):
            validate_content(slot("github", github_query=query, github_repo="acme/keeper"))
        for bad in ({"github_query": "everything"}, {"github_repo": "no-slash"}, {"github_repo": "a/b/c"}, {"github_repo": 5}):
            with self.assertRaises(ValueError):
                validate_content(slot("github", **bad))

    def test_integration_validation_and_export_strips_the_token(self):
        validate_new_integrations({"github": {"enabled": True, "token": "x"}})
        with self.assertRaises(ValueError):
            validate_new_integrations({"github": {"enabled": "yes", "token": "x"}})
        with tempfile.TemporaryDirectory() as temp:
            store = ConfigStore(Path(temp) / "s", migrate=False)
            store.change(lambda cfg: cfg["integrations"]["github"].update(enabled=True, token="ghp_SECRET"))
            target = Path(temp) / "out.zip"
            store.export(target)
            import zipfile
            with zipfile.ZipFile(target) as archive:
                text = "".join(archive.read(n).decode("utf-8", "replace") for n in archive.namelist() if n.endswith(".json"))
            self.assertNotIn("ghp_SECRET", text)

    def test_demo_render_and_error_render(self):
        for query in ("review", "mine", "repo", "issues", "mentions", "ci"):
            image = Renderer(demo=True).render(slot("github", github_query=query, github_repo="acme/keeper"))
            self.assertEqual(image.size, (128, 128))
        real = Renderer(demo=False)
        real.providers.extra.github_conf = {"enabled": True, "token": ""}
        self.assertEqual(real.render(slot("github", github_query="review")).size, (128, 128))

    def test_ci_render_states(self):
        images = []
        for state in ("success", "failure", "running", "none", "other"):
            real = Renderer(demo=False)
            real.providers.extra.github_state = lambda s, state=state: ({"state": state, "name": "CI", "branch": "main", "event": "push"}, "")
            images.append(real.render(slot("github", github_query="ci", github_repo="acme/keeper")).tobytes())
        self.assertEqual(len(set(images)), 5)


if __name__ == "__main__":
    unittest.main()
