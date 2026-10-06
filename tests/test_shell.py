import argparse
import json
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
        self.assertEqual(self.client.post("/api/launch", content=b"not json").status_code, 401)

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


class HostGuardTests(PortalCase):
    def test_host_name_parsing(self):
        self.assertEqual(host_name("127.0.0.1:8765"), "127.0.0.1")
        self.assertEqual(host_name("LocalHost"), "localhost")
        self.assertEqual(host_name("[::1]:80"), "[::1]")
        self.assertEqual(host_name("[::1]x"), "")
        self.assertEqual(host_name(""), "")

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
            self.assertRegex(urls[0], r"^http://127\.0\.0\.1:\d+/#launch=[A-Za-z0-9_-]{16,}$")
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
                base, code = urls[0].split("#launch=")
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


class ImportTests(unittest.TestCase):
    def test_shell_and_portal_never_import_qt(self):
        code = "import sys, keeper.shell, keeper.portal; " \
               "assert not [m for m in sys.modules if m.startswith('PySide6')], 'PySide6 imported'"
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
