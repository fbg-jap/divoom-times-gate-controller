import argparse
import io
import json
import os
import re
import socket
import stat
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from filelock import FileLock, Timeout

from keeper import shell
from keeper.portal import LaunchCodes, create_app, host_name

TOKEN = "unit-test-token-at-least-24-characters"
ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class PortalCase(unittest.TestCase):
    shell_mode = True

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.app = create_app(Path(self.temp.name), token=TOKEN, demo=True, shell_mode=self.shell_mode, clock=self.clock)
        self.client = TestClient(self.app, base_url="http://127.0.0.1:8765").__enter__()
        self.auth = {"Authorization": "Bearer " + TOKEN}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def launch(self, code, **kwargs):
        return self.client.post("/api/launch", json={"code": code}, **kwargs)


class LaunchCodeTests(PortalCase):
    def test_code_is_single_use_and_returns_the_token(self):
        code = self.app.state.launch_codes.issue()
        first = self.launch(code)
        self.assertEqual((first.status_code, first.json()), (200, {"token": TOKEN}))
        second = self.launch(code)
        self.assertEqual(second.status_code, 401)
        self.assertNotIn(TOKEN, second.text)

    def test_wrong_and_missing_codes(self):
        self.app.state.launch_codes.issue()
        for body in ({"code": "nope"}, {"code": ""}, {"code": 5}, {}, [1]):
            response = self.client.post("/api/launch", json=body)
            self.assertEqual(response.status_code, 401, body)
            self.assertNotIn(TOKEN, response.text)
        self.assertEqual(self.client.post("/api/launch", content=b"not json", headers={"Content-Type": "application/json"}).status_code, 401)

    def test_expiry(self):
        code = self.app.state.launch_codes.issue()
        self.clock.now += 61
        self.assertEqual(self.launch(code).status_code, 401)
        fresh = self.app.state.launch_codes.issue()
        self.clock.now += 59
        self.assertEqual(self.launch(fresh).status_code, 200)

    def test_expired_code_is_consumed(self):
        codes = LaunchCodes(self.clock)
        code = codes.issue()
        self.clock.now += 100
        self.assertFalse(codes.redeem(code))
        self.assertEqual(codes.codes, {})

    def test_at_most_eight_outstanding_codes(self):
        codes = LaunchCodes(self.clock)
        issued = [codes.issue() for _ in range(10)]
        self.assertEqual(len(codes.codes), 8)
        self.assertFalse(codes.redeem(issued[0]))
        self.assertTrue(codes.redeem(issued[-1]))

    def test_non_loopback_host_cannot_redeem(self):
        code = self.app.state.launch_codes.issue()
        response = self.launch(code, headers={"Host": "evil.example"})
        self.assertEqual(response.status_code, 421)
        self.assertNotIn(TOKEN, response.text)
        with mock.patch.dict("os.environ", {"KEEPER_HOSTS": "keeper.lan"}):
            allowed = create_app(Path(self.temp.name) / "other", token=TOKEN, demo=True, shell_mode=True)
            with TestClient(allowed) as client:
                issued = allowed.state.launch_codes.issue()
                response = client.post("/api/launch", json={"code": issued}, headers={"Host": "keeper.lan"})
                self.assertEqual(response.status_code, 401)  # KEEPER_HOSTS never makes the launch route usable
        self.assertEqual(self.launch(code).status_code, 200)

    def test_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.launch("wrong").status_code, 401)
        code = self.app.state.launch_codes.issue()
        self.assertEqual(self.launch(code).status_code, 429)
        self.clock.now += 61
        self.assertEqual(self.launch(code).status_code, 401)  # expired by now, but no longer limited

    def test_no_http_route_issues_codes(self):
        for path in ("/api/launch/new", "/api/launch/issue"):
            self.assertIn(self.client.post(path, headers=self.auth).status_code, {404, 405})
        self.assertIn(self.client.get("/api/launch", headers=self.auth).status_code, {404, 405})

    def test_exemption_is_exact(self):
        code = self.app.state.launch_codes.issue()
        body = {"json": {"code": code}}
        for method, path in [("POST", "/api/launch/"), ("POST", "//api/launch"), ("POST", "/API/launch"), ("POST", "/api/launch/x"),
                             ("POST", "/api/launchx"), ("GET", "/api/launch"), ("HEAD", "/api/launch"), ("OPTIONS", "/api/launch"),
                             ("PUT", "/api/launch"), ("DELETE", "/api/launch"), ("POST", "/api/launch%2F")]:
            response = self.client.request(method, path, **body)
            self.assertIn(response.status_code, {401, 404, 405}, (method, path))
            self.assertNotIn(TOKEN, response.text, (method, path))
        # None of the attempts consumed the code.
        self.assertEqual(self.launch(code).status_code, 200)

    def test_launch_route_does_not_exist_outside_shell_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            plain = create_app(Path(temp), token=TOKEN, demo=True)
            with TestClient(plain) as client:
                code = plain.state.launch_codes.issue()
                self.assertEqual(client.post("/api/launch", json={"code": code}).status_code, 401)


class LaunchOriginTests(PortalCase):
    def test_cross_origin_requests_do_not_consume_or_burn_attempts(self):
        code = self.app.state.launch_codes.issue()
        evil = {"Origin": "https://evil.example"}
        # no-cors style simple request: text/plain body, no preflight
        for _ in range(15):
            response = self.client.post("/api/launch", content=json.dumps({"code": code}), headers={**evil, "Content-Type": "text/plain"})
            self.assertEqual(response.status_code, 403)
            self.assertNotIn(TOKEN, response.text)
        for _ in range(15):
            response = self.client.post("/api/launch", json={"code": code}, headers=evil)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn(TOKEN, response.text)
        self.assertEqual(self.client.post("/api/launch", json={"code": code}, headers={"Origin": "null"}).status_code, 403)
        self.assertEqual(self.app.state.launch_codes.failures.__len__(), 0)
        self.assertEqual(self.launch(code, headers={"Origin": "http://127.0.0.1:8765"}).json(), {"token": TOKEN})

    def test_ten_bad_cross_origin_attempts_do_not_lock_out_the_login(self):
        for _ in range(10):
            self.assertEqual(self.launch("wrong", headers={"Origin": "http://evil.example"}).status_code, 403)
        code = self.app.state.launch_codes.issue()
        self.assertEqual(self.launch(code).status_code, 200)

    def test_json_content_type_is_required_and_not_counted(self):
        code = self.app.state.launch_codes.issue()
        body = json.dumps({"code": code})
        for content_type in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data", None):
            headers = {"Content-Type": content_type} if content_type else {}
            self.assertEqual(self.client.post("/api/launch", content=body, headers=headers).status_code, 415, content_type)
        self.assertEqual(len(self.app.state.launch_codes.failures), 0)
        self.assertEqual(self.client.post("/api/launch", content=body, headers={"Content-Type": "application/json; charset=utf-8"}).status_code, 200)

    def test_web_client_sends_json_content_type(self):
        source = (ROOT / "web/src/api.js").read_text(encoding="utf-8")
        self.assertRegex(source, r'"/api/launch",\s*\{[^}]*"Content-Type":\s*"application/json"')


class HostGuardTests(PortalCase):
    def test_host_name_parsing(self):
        self.assertEqual(host_name("127.0.0.1:8765"), "127.0.0.1")
        self.assertEqual(host_name("LocalHost"), "localhost")
        self.assertEqual(host_name("[::1]:80"), "[::1]")
        self.assertEqual(host_name("[::1]x"), "")
        self.assertEqual(host_name(""), "")
        for bad in ("127.0.0.1:8765@evil.com", "localhost:evil.com", "127.0.0.1:99999", "evil.com\\localhost",
                    "127.0.0.1:", "a b", "127.0.0.1,evil.com", "[::1]:99999", "localhost:1:2"):
            self.assertEqual(host_name(bad), "", bad)
        self.assertEqual(host_name("LOCALHOST:65535"), "localhost")

    def test_strict_host_rejections_and_acceptances(self):
        for host in ("127.0.0.1:8765@evil.com", "localhost:evil.com", "127.0.0.1:99999", "localhost.", "127.0.0.1.", ""):
            self.assertEqual(self.client.get("/healthz", headers={"Host": host}).status_code, 421, host)
        for host in ("LOCALHOST", "LocalHost:8765", "[::1]:8765", "127.0.0.1:65535"):
            self.assertEqual(self.client.get("/healthz", headers={"Host": host}).status_code, 200, host)

    def test_duplicate_host_header_is_rejected(self):
        response = self.client.get("/healthz", headers=[("Host", "127.0.0.1:8765"), ("Host", "127.0.0.1:8765")])
        self.assertEqual(response.status_code, 421)
        self.assertEqual(self.client.get("/healthz", headers=[("Host", "127.0.0.1"), ("Host", "evil.example")]).status_code, 421)

    def test_shell_mode_rejects_foreign_hosts_everywhere(self):
        for host in ("evil.example", "evil.example:8765", "127.0.0.1.evil.example", "localhost.evil.example", ""):
            for path in ("/healthz", "/", "/api/state", "/index.html"):
                response = self.client.get(path, headers={"Host": host, **self.auth})
                self.assertEqual(response.status_code, 421, (host, path))

    def test_shell_mode_accepts_loopback_hosts(self):
        for host in ("127.0.0.1", "127.0.0.1:1234", "localhost", "localhost:9", "[::1]", "[::1]:8765"):
            self.assertEqual(self.client.get("/healthz", headers={"Host": host}).status_code, 200, host)

    def test_keeper_hosts_extends_the_guard(self):
        with mock.patch.dict("os.environ", {"KEEPER_HOSTS": "keeper.lan, other.lan"}):
            app = create_app(Path(self.temp.name) / "hosts", token=TOKEN, demo=True, shell_mode=True)
        with TestClient(app) as client:
            self.assertEqual(client.get("/healthz", headers={"Host": "keeper.lan:80"}).status_code, 200)
            self.assertEqual(client.get("/healthz", headers={"Host": "evil.lan"}).status_code, 421)

    def test_default_create_app_accepts_any_host(self):
        with tempfile.TemporaryDirectory() as temp:
            app = create_app(Path(temp), token=TOKEN, demo=True)
            with TestClient(app) as client:
                self.assertEqual(client.get("/healthz", headers={"Host": "anything.example"}).status_code, 200)
                self.assertEqual(client.get("/api/state", headers={"Host": "anything.example", **self.auth}).status_code, 200)


class ShellRoutesTests(PortalCase):
    def test_state_reports_desktop(self):
        self.assertIs(self.client.get("/api/state", headers=self.auth).json()["desktop"], True)

    def test_routes_require_bearer(self):
        for method, path in [("GET", "/api/startup"), ("POST", "/api/startup"), ("POST", "/api/open"), ("POST", "/api/quit")]:
            self.assertEqual(self.client.request(method, path, json={}).status_code, 401, path)
        self.assertFalse(self.app.state.quit_event.is_set())

    def test_startup_roundtrip(self):
        calls = []
        fake = types.ModuleType("keeper.startup")
        fake.set_startup = lambda enabled, root: calls.append((enabled, Path(root)))
        with mock.patch.dict(sys.modules, {"keeper.startup": fake}):
            self.assertEqual(self.client.get("/api/startup", headers=self.auth).json(), {"enabled": False})
            response = self.client.post("/api/startup", json={"enabled": True}, headers=self.auth)
            self.assertEqual(response.json(), {"enabled": True})
            self.assertEqual(self.client.get("/api/startup", headers=self.auth).json(), {"enabled": True})
            self.assertEqual(self.client.post("/api/startup", json={"enabled": "yes"}, headers=self.auth).status_code, 400)
        self.assertEqual(calls, [(True, self.app.state.store.root)])

    def test_open_is_whitelisted(self):
        opened = []
        self.app.state.open_external = lambda path: opened.append(Path(path)) or True
        store = self.app.state.store
        self.assertEqual(self.client.post("/api/open", json={"what": "data"}, headers=self.auth).json(), {"opened": True})
        self.assertEqual(self.client.post("/api/open", json={"what": "library"}, headers=self.auth).json(), {"opened": True})
        for what in ("/etc", "../..", "", None, ["data"], "DATA"):
            self.assertEqual(self.client.post("/api/open", json={"what": what}, headers=self.auth).status_code, 400, what)
        self.assertEqual(self.client.post("/api/open", json={"what": "data", "path": "/etc"}, headers=self.auth).status_code, 200)
        self.assertEqual(opened, [store.root, store.media_dir, store.root])

    def test_quit_sets_the_event_after_responding(self):
        response = self.client.post("/api/quit", headers=self.auth)
        self.assertEqual(response.json(), {"quitting": True})
        self.assertTrue(self.app.state.quit_event.is_set())

    def test_routes_are_absent_outside_shell_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            app = create_app(Path(temp), token=TOKEN, demo=True)
            with TestClient(app) as client:
                self.assertIs(client.get("/api/state", headers=self.auth).json()["desktop"], False)
                for method, path in [("GET", "/api/startup"), ("POST", "/api/startup"), ("POST", "/api/open"), ("POST", "/api/quit")]:
                    self.assertIn(client.request(method, path, json={"what": "data", "enabled": True}, headers=self.auth).status_code, {404, 405}, path)
                self.assertFalse(app.state.quit_event.is_set())


class BrowserTests(unittest.TestCase):
    def test_first_known_browser_wins_in_order(self):
        present = {"chromium": "/usr/bin/chromium", "google-chrome": "/usr/bin/google-chrome"}
        self.assertEqual(shell.find_app_browser(which=present.get, platform="linux"), "/usr/bin/google-chrome")
        self.assertEqual(shell.find_app_browser(which=lambda name: f"/b/{name}" if name == "brave-browser" else None, platform="linux"), "/b/brave-browser")
        self.assertIsNone(shell.find_app_browser(which=lambda name: None, platform="linux"))

    def test_windows_program_files_paths(self):
        env = {"PROGRAMFILES": r"C:\PF", "LOCALAPPDATA": r"C:\Local"}
        found = shell.find_app_browser(which=lambda n: None, exists=lambda p: p.endswith("msedge.exe"), environ=env, platform="win32")
        self.assertTrue(found.endswith("msedge.exe"))
        self.assertIsNone(shell.find_app_browser(which=lambda n: None, exists=lambda p: False, environ=env, platform="win32"))
        self.assertIsNone(shell.find_app_browser(which=lambda n: None, exists=lambda p: True, environ=env, platform="linux"))

    def test_app_mode_launch_uses_external_environment_and_detaches(self):
        popen = mock.Mock()
        with mock.patch("keeper.platform_support.external_environment", return_value={"CLEAN": "1"}) as environment:
            self.assertTrue(shell.open_ui("http://127.0.0.1:1/#launch=x", find=lambda: "/usr/bin/brave", popen=popen))
        environment.assert_called_once_with()
        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["/usr/bin/brave", "--app=http://127.0.0.1:1/#launch=x"])
        self.assertEqual(kwargs["env"], {"CLEAN": "1"})
        self.assertIs(kwargs["start_new_session"], True)
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)

    def test_fallback_when_no_browser_or_start_fails(self):
        fallback = mock.Mock(return_value=True)
        self.assertTrue(shell.open_ui("http://x/", find=lambda: None, popen=mock.Mock(), fallback=fallback))
        fallback.assert_called_once_with("http://x/")
        fallback.reset_mock()
        self.assertTrue(shell.open_ui("http://x/", find=lambda: "/b", popen=mock.Mock(side_effect=OSError), fallback=fallback))
        fallback.assert_called_once_with("http://x/")
        self.assertFalse(shell.open_ui("http://x/", find=lambda: None, fallback=lambda url: False))


def launch_target(argv):
    """Path of the single file:// argument of a fake browser command line."""
    uris = [a.removeprefix("--app=") for a in argv if a.removeprefix("--app=").startswith("file://")]
    assert len(uris) == 1, argv
    from urllib.parse import unquote, urlparse
    return Path(unquote(urlparse(uris[0]).path))


@unittest.skipIf(os.name == "nt", "POSIX permissions")
class LaunchPageTests(unittest.TestCase):
    def test_launch_page_is_private_exclusive_and_redirects(self):
        with tempfile.TemporaryDirectory() as temp:
            url = "http://127.0.0.1:8765/#launch=abc_DEF-123456789012345"
            path = shell.launch_page(Path(temp), url)
            self.assertRegex(path.name, r"^open-[0-9a-f]{16}\.html$")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            text = path.read_text(encoding="utf-8")
            self.assertIn('charset="utf-8"', text)
            self.assertIn(f'<meta http-equiv="refresh" content="0;url={url}">', text)
            self.assertIn(f"location.replace({json.dumps(url)})", text)
            with mock.patch("keeper.shell.secrets.token_hex", return_value=path.name[5:-5]):
                with self.assertRaises(FileExistsError):
                    shell.launch_page(Path(temp), url)

    def test_pages_removed_on_redeem_and_on_ttl_and_failure_falls_back(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = Clock()
            codes = LaunchCodes(clock)
            pages = shell.LaunchPages(Path(temp), codes, clock)
            first, second = pages.create("http://127.0.0.1:1/"), pages.create("http://127.0.0.1:1/")
            files = sorted(Path(temp).glob("open-*.html"))
            self.assertEqual(len(files), 2)
            code = re.search(r"#launch=([\w-]+)", files[0].read_text()).group(1)
            self.assertTrue(codes.redeem(code))  # hook sweeps immediately
            self.assertEqual(len(list(Path(temp).glob("open-*.html"))), 1)
            clock.now += 59
            pages.sweep()
            self.assertEqual(len(list(Path(temp).glob("open-*.html"))), 1)
            clock.now += 2
            pages.sweep()
            self.assertEqual(list(Path(temp).glob("open-*.html")), [])
            pages.create("http://127.0.0.1:1/")
            pages.close()
            self.assertEqual(list(Path(temp).glob("open-*.html")), [])
            with mock.patch("keeper.shell.launch_page", side_effect=OSError("disk full")):
                self.assertIsNone(pages.create("http://127.0.0.1:1/"))

    def test_browser_argv_never_contains_the_code_or_token(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "data"
            argvs, snapshots = [], []
            popen = mock.Mock()
            popen.side_effect = lambda argv, **kw: argvs.append(list(argv)) or snapshots.append(
                launch_target(argv).read_text(encoding="utf-8"))
            opener = lambda url: shell.open_ui(url, find=lambda: "/usr/bin/brave", popen=popen, fallback=lambda u: argvs.append([u]))
            (root).mkdir(mode=0o700)
            (root / "open-stale.html").write_text("old")
            quit_event = threading.Event()
            captured = {}
            def serve(app, sock):
                captured["app"], captured["port"] = app, sock.getsockname()[1]
                return FakeServer(), types.SimpleNamespace(is_alive=lambda: True, join=lambda t=None: None)
            def opener_and_quit(url):
                opener(url)
                path = launch_target(argvs[0])
                captured["mode"] = stat.S_IMODE(path.stat().st_mode)
                captured["dir_mode"] = stat.S_IMODE(path.parent.stat().st_mode)
                captured["stale"] = (root / "open-stale.html").exists()
                code = re.search(r"#launch=([\w-]+)", snapshots[0]).group(1)
                captured["code"] = code
                captured["page"] = path
                with TestClient(captured["app"], base_url=f"http://127.0.0.1:{captured['port']}") as client:
                    captured["token"] = client.post("/api/launch", json={"code": code}).json()["token"]
                captured["after_redeem"] = path.exists()
                quit_event.set()
            self.assertEqual(shell.run(args_for(root, port=0), serve=serve, healthy=lambda p: True, opener=opener_and_quit,
                                       tray_loader=lambda: None, quit_event=quit_event), 0)
            joined = " ".join(" ".join(a) for a in argvs)
            self.assertNotIn("#launch=", joined)
            self.assertNotIn(captured["code"], joined)
            self.assertNotIn(captured["token"], joined)
            self.assertTrue(argvs[0][1].startswith("--app=file://"))
            self.assertEqual((captured["mode"], captured["dir_mode"]), (0o600, 0o700))
            self.assertFalse(captured["stale"])
            self.assertIn(f"http://127.0.0.1:{captured['port']}/#launch={captured['code']}", snapshots[0])
            self.assertFalse(captured["after_redeem"])
            self.assertEqual(list(root.glob("open-*.html")), [])

    def test_write_failure_opens_only_the_plain_url(self):
        with tempfile.TemporaryDirectory() as temp:
            urls = []
            quit_event = threading.Event()
            quit_event.set()
            serve = lambda app, sock: (FakeServer(), types.SimpleNamespace(is_alive=lambda: True, join=lambda t=None: None))
            with mock.patch("keeper.shell.launch_page", side_effect=OSError("read-only")):
                shell.run(args_for(Path(temp)), serve=serve, healthy=lambda p: True, opener=urls.append, tray_loader=lambda: None, quit_event=quit_event)
            self.assertEqual(len(urls), 1)
            self.assertRegex(urls[0], r"^http://127\.0\.0\.1:\d+/$")


class FakeServer:
    def __init__(self):
        self.should_exit = False


def args_for(root, **kwargs):
    values = dict(demo=True, config_dir=root, minimized=False, port=0, print_launch_url=False, no_tray=False)
    values.update(kwargs)
    return argparse.Namespace(**values)


class SingleInstanceTests(unittest.TestCase):
    def test_second_instance_opens_the_running_one_and_exits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "shell.json").write_text(json.dumps({"port": 4321, "pid": 1}))
            held = FileLock(root / "studio.lock", timeout=0)
            held.acquire()
            try:
                with self.assertRaises(Timeout):
                    FileLock(root / "studio.lock", timeout=0).acquire()
                opened = []
                self.assertEqual(shell.run(args_for(root), opener=opened.append), 0)
                self.assertEqual(opened, ["http://127.0.0.1:4321/"])
                opened.clear()
                shell.run(args_for(root, minimized=True), opener=opened.append)
                self.assertEqual(opened, [])
            finally:
                held.release()
            self.assertTrue((root / "shell.json").exists())  # the second instance must not touch the first one's file

    def test_pick_socket_falls_back_when_busy(self):
        first = shell.pick_socket(0)
        try:
            busy = first.getsockname()[1]
            second = shell.pick_socket(busy)
            self.assertNotEqual(second.getsockname()[1], busy)
            second.close()
        finally:
            first.close()


class LifecycleTests(unittest.TestCase):
    def test_run_and_quit_with_fake_server_and_tray(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            servers, urls, tray_events = [], [], []
            class Tray:
                def stop(self):
                    tray_events.append("stop")
            def serve(app, sock):
                server = FakeServer()
                servers.append((app, server))
                return server, types.SimpleNamespace(is_alive=lambda: not server.should_exit, join=lambda timeout=None: tray_events.append("joined"))
            quit_event = threading.Event()
            def tray_loader():
                def start(callbacks):
                    tray_events.append(sorted(callbacks))
                    threading.Timer(.2, callbacks["quit"]).start()
                    return Tray()
                return start
            code = shell.run(args_for(root), serve=serve, healthy=lambda port: True, opener=urls.append, tray_loader=tray_loader, quit_event=quit_event)
            self.assertEqual(code, 0)
            self.assertTrue(servers[0][1].should_exit)
            self.assertEqual(len(urls), 1)
            self.assertRegex(urls[0], r"^file:///.*/open-[0-9a-f]{16}\.html$")
            self.assertEqual(tray_events[0], ["open", "quit", "set_startup", "startup_enabled"])
            self.assertEqual(tray_events[1:], ["stop", "joined"])
            self.assertFalse((root / "shell.json").exists())
            FileLock(root / "studio.lock", timeout=0).acquire()  # released

    def test_minimized_does_not_open_a_browser_and_missing_tray_is_fine(self):
        with tempfile.TemporaryDirectory() as temp:
            urls = []
            quit_event = threading.Event()
            quit_event.set()
            serve = lambda app, sock: (FakeServer(), types.SimpleNamespace(is_alive=lambda: True, join=lambda t=None: None))
            self.assertEqual(shell.run(args_for(Path(temp), minimized=True), serve=serve, healthy=lambda p: True,
                                       opener=urls.append, tray_loader=lambda: None, quit_event=quit_event), 0)
            self.assertEqual(urls, [])

    def test_unhealthy_portal_returns_an_error_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as temp:
            serve = lambda app, sock: (FakeServer(), types.SimpleNamespace(is_alive=lambda: True, join=lambda t=None: None))
            code = shell.run(args_for(Path(temp)), serve=serve, healthy=lambda p: False, opener=lambda u: True, tray_loader=lambda: None)
            self.assertEqual(code, 1)
            self.assertFalse((Path(temp) / "shell.json").exists())

    def test_load_tray_is_optional(self):
        with mock.patch.dict(sys.modules, {"keeper.tray": None}):
            self.assertIsNone(shell.load_tray())

    def test_real_server_end_to_end_in_demo_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            quit_event = threading.Event()
            urls = []
            result = []
            runner = threading.Thread(target=lambda: result.append(shell.run(
                args_for(root, port=0), opener=urls.append, tray_loader=lambda: None, quit_event=quit_event)))
            runner.start()
            try:
                deadline = time.monotonic() + 30
                while not urls and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(urls, "shell did not open the UI")
                from urllib.parse import unquote, urlparse
                base, code = re.search(r'location\.replace\("([^"#]+)#launch=([\w-]+)"\)', Path(unquote(urlparse(urls[0]).path)).read_text()).groups()
                import httpx
                reply = httpx.post(base + "api/launch", json={"code": code}, timeout=10)
                self.assertEqual(reply.status_code, 200)
                token = reply.json()["token"]
                self.assertEqual(httpx.post(base + "api/launch", json={"code": code}, timeout=10).status_code, 401)
                state = httpx.get(base + "api/state", headers={"Authorization": "Bearer " + token}, timeout=10).json()
                self.assertTrue(state["desktop"])
                self.assertEqual(httpx.get(base + "healthz", headers={"Host": "evil.example"}, timeout=10).status_code, 421)
                self.assertEqual(httpx.post(base + "api/quit", headers={"Authorization": "Bearer " + token}, timeout=10).status_code, 200)
                runner.join(40)
                self.assertFalse(runner.is_alive())
                self.assertEqual(result, [0])
            finally:
                quit_event.set()
                runner.join(40)


class HardeningTests(unittest.TestCase):
    def run_shell(self, root, args=None, **kwargs):
        quit_event = threading.Event()
        quit_event.set()
        serve = lambda app, sock: (FakeServer(), types.SimpleNamespace(is_alive=lambda: True, join=lambda t=None: None))
        kwargs.setdefault("opener", lambda url: True)
        kwargs.setdefault("tray_loader", lambda: None)
        return shell.run(args or args_for(root), serve=serve, healthy=lambda p: True, quit_event=quit_event, **kwargs)

    def test_busy_default_port_falls_back_with_warning_notice_and_flag(self):
        busy = socket.socket()
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        wanted = busy.getsockname()[1]
        notes, seen = [], []
        class Tray:
            def stop(self): pass
            def notify(self, title, text): notes.append((title, text))
        real = shell.write_private
        def spy(path, text):
            seen.append(json.loads(text))
            real(path, text)
        try:
            with tempfile.TemporaryDirectory() as temp, self.assertLogs("keeper.shell", "WARNING") as logs, \
                    mock.patch("keeper.shell.write_private", spy):
                self.run_shell(Path(temp), args_for(Path(temp), port=wanted), tray_loader=lambda: (lambda callbacks: Tray()))
        finally:
            busy.close()
        self.assertTrue(seen[0]["fallback"])
        self.assertNotEqual(seen[0]["port"], wanted)
        self.assertTrue(any(str(wanted) in line and str(seen[0]["port"]) in line for line in logs.output))
        self.assertEqual(notes, [("Keeper", f"Port {wanted} is in use; using {seen[0]['port']}")])

    def test_free_port_is_not_a_fallback(self):
        seen = []
        with tempfile.TemporaryDirectory() as temp, mock.patch("keeper.shell.write_private", lambda path, text: seen.append(json.loads(text))):
            self.run_shell(Path(temp))
        self.assertIs(seen[0]["fallback"], False)

    def test_windows_socket_is_exclusive(self):
        sock = mock.MagicMock()
        with mock.patch("keeper.shell.os.name", "nt"), mock.patch("keeper.shell.socket.socket", return_value=sock), \
                mock.patch("keeper.shell.socket.SO_EXCLUSIVEADDRUSE", 4294967291, create=True):
            shell.pick_socket(8765)
        self.assertEqual(sock.setsockopt.call_args_list, [mock.call(socket.SOL_SOCKET, 4294967291, 1)])

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_data_files_and_directory_are_private(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "new" / "data"
            with mock.patch("keeper.shell.os.chmod", wraps=os.chmod):
                self.run_shell(root)
            mode = lambda p: stat.S_IMODE(p.stat().st_mode)
            self.assertEqual(mode(root), 0o700)
            self.assertEqual(mode(root / "studio.log"), 0o600)
            self.assertEqual(mode(root / "studio.lock"), 0o600)
            owned = Path(temp) / "owned"
            owned.mkdir(mode=0o755)
            os.chmod(owned, 0o755)
            self.run_shell(owned, args_for(None, config_dir=None, demo=True))  # demo temp dir is owned by the shell

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_shell_json_is_0600_even_when_it_already_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "shell.json"
            path.write_text("{}")
            os.chmod(path, 0o644)
            shell.write_private(path, "{}")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_default_data_dir_is_tightened_but_a_given_config_dir_is_not(self):
        with tempfile.TemporaryDirectory() as temp:
            given, default = Path(temp) / "given", Path(temp) / "default"
            for path in (given, default):
                path.mkdir()
                os.chmod(path, 0o755)
            self.run_shell(given, args_for(given))
            self.assertEqual(stat.S_IMODE(given.stat().st_mode), 0o755)
            with mock.patch("keeper.platform_support.data_directory", return_value=default):
                self.run_shell(default, args_for(None, config_dir=None, demo=False))
            self.assertEqual(stat.S_IMODE(default.stat().st_mode), 0o700)

    def print_url(self, tty, env):
        out, err = io.StringIO(), io.StringIO()
        out.isatty = lambda: tty
        with tempfile.TemporaryDirectory() as temp, mock.patch("sys.stdout", out), mock.patch("sys.stderr", err), \
                mock.patch.dict("os.environ", env):
            os.environ.pop("KEEPER_ALLOW_PIPED_LAUNCH_URL", None) if "KEEPER_ALLOW_PIPED_LAUNCH_URL" not in env else None
            self.run_shell(Path(temp), args_for(Path(temp), print_launch_url=True, minimized=True))
        return out.getvalue(), err.getvalue()

    def test_launch_url_is_printed_only_to_a_terminal_or_with_the_test_opt_in(self):
        out, _ = self.print_url(True, {})
        self.assertRegex(out, r"#launch=[\w-]{16,}")
        out, err = self.print_url(False, {})
        self.assertNotIn("#launch=", out)
        self.assertRegex(out.strip(), r"^http://127\.0\.0\.1:\d+/$")
        self.assertIn("launch URL suppressed", err)
        out, _ = self.print_url(False, {"KEEPER_ALLOW_PIPED_LAUNCH_URL": "1"})
        self.assertRegex(out, r"#launch=[\w-]{16,}")


class ParseArgsTests(unittest.TestCase):
    def test_options_match_the_web_ui_of_app_py(self):
        args = shell.parse_args(["--demo", "--config-dir", "/tmp/x", "--minimized", "--port", "0", "--print-launch-url", "--ui", "web"])
        self.assertEqual((args.demo, args.config_dir, args.minimized, args.port, args.print_launch_url, args.ui),
                         (True, Path("/tmp/x"), True, 0, True, "web"))
        self.assertEqual(shell.parse_args([]).ui, "web")

    def test_run_registers_the_web_ui_for_autostart(self):
        from keeper import startup
        done = threading.Thread(target=lambda: None)
        done.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                shell.run(shell.parse_args(["--config-dir", temp, "--minimized"]), serve=lambda app, sock: (FakeServer(), done),
                          healthy=lambda p: False)
            self.assertEqual(startup._ui_args, ["--ui", "web"])
        finally:
            startup.set_ui_args([])


class ImportTests(unittest.TestCase):
    def test_shell_and_portal_never_import_qt(self):
        code = "import sys, shell_main, keeper.shell, keeper.portal; " \
               "assert not [m for m in sys.modules if m.startswith('PySide6')], 'PySide6 imported'"
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
