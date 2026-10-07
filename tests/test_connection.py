import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from keeper import engine as engine_module
from keeper.config import ConfigStore, slot
from keeper.engine import PROBE_DELAYS, Engine
from keeper.protocol import CONNECT_TIMEOUT, Client, locate


class Flaky:
    """requests-like session: fails with `error` for the first `failures` posts, then answers."""
    def __init__(self, failures, error=requests.ConnectTimeout("slow")):
        self.failures, self.error, self.calls, self.timeouts = failures, error, 0, []

    def post(self, url, json=None, timeout=None):
        self.calls += 1
        self.timeouts.append(timeout)
        if self.calls <= self.failures:
            raise self.error

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"error_code": 0}
        return Response()


class RetryTests(unittest.TestCase):
    def client(self, session, **kwargs):
        self.waits = []
        return Client("10.0.0.5", session=session, port=9000, sleep=self.waits.append, **kwargs)

    def test_a_dropped_command_is_repeated_with_growing_waits(self):
        session = Flaky(2)
        self.assertEqual(self.client(session).command({"Command": "Channel/GetAllConf"}), {"error_code": 0})
        self.assertEqual((session.calls, self.waits), (3, [0.3, 1.0]))

    def test_gives_up_after_the_retries_and_probes_do_not_retry(self):
        session = Flaky(99)
        with self.assertRaises(requests.ConnectTimeout):
            self.client(session).command({"Command": "x"})
        self.assertEqual(session.calls, 3)
        quick = Flaky(99)
        with self.assertRaises(requests.ConnectTimeout):
            self.client(quick, retries=0).command({"Command": "x"})
        self.assertEqual((quick.calls, self.waits), (1, []))

    def test_device_errors_are_not_retried_and_connect_timeout_is_short(self):
        class Rejecting(Flaky):
            def post(self, url, json=None, timeout=None):
                self.calls += 1
                self.timeouts.append(timeout)
                return type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: {"error_code": 1}})()
        session = Rejecting(0)
        with self.assertRaises(Exception):
            self.client(session).command({"Command": "x"})
        self.assertEqual(session.calls, 1)
        self.assertEqual(session.timeouts[0], (CONNECT_TIMEOUT, 10))


class FakeClient:
    def __init__(self, ip, **kwargs):
        self.ip, self.retries, self.fail, self.commands = ip, 2, False, []

    def command(self, payload):
        self.commands.append((payload, self.retries))
        if self.fail:
            raise self.fail
        return {"error_code": 0}

    def send_frames(self, frames, panel, quality, speed, stop):
        if self.fail:
            raise self.fail


class EngineConnectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = ConfigStore(Path(temp.name) / "studio", migrate=False)
        self.d = self.store.get_device()
        self.d.update(ip="192.168.1.10", enabled=True, mac="AA:BB:CC:00:11:22", device_id=77)
        for i in range(4):
            self.d["screens"][i] = slot("text", text=f"hi {i}")
        self.store.update_device(self.d)
        self.engine = Engine(self.store, client_factory=FakeClient)
        self.client = self.engine.client(self.d)

    def test_second_connection_failure_takes_the_device_offline_and_stops_the_cycle(self):
        self.client.fail = requests.ConnectTimeout("slow")
        with self.assertRaises(RuntimeError) as raised:
            self.engine.send(self.d)
        self.assertIs(self.engine.online[self.d["id"]], False)
        self.assertIn("1:", str(raised.exception))
        self.assertIn("2:", str(raised.exception))
        self.assertNotIn("3:", str(raised.exception))   # screens 3-5 were skipped
        self.assertEqual(self.engine.offline_info[self.d["id"]]["reason"], "unreachable")

    def test_one_failure_alone_does_not_flip_the_state_and_success_resets_the_count(self):
        self.client.fail = requests.ConnectionError("boom")
        with self.assertRaises(RuntimeError):
            self.engine.send(self.d, 0)
        self.assertIsNot(self.engine.online.get(self.d["id"]), False)
        self.client.fail = False
        self.engine.send(self.d, 0)
        self.assertEqual(self.engine.fail_count[self.d["id"]], 0)

    def test_reasons_are_told_apart(self):
        reason = Engine.connection_reason
        self.assertEqual(reason(requests.ReadTimeout("x")), "api_busy")
        self.assertEqual(reason(requests.ConnectionError("[Errno 111] Connection refused")), "api_down")
        self.assertEqual(reason(requests.ConnectTimeout("x")), "unreachable")

    def test_offline_device_gets_quick_probes_with_backoff_and_recovers(self):
        did = self.d["id"]
        self.client.fail = requests.ConnectTimeout("slow")
        self.engine.online[did] = True
        self.engine.health(self.d)          # was online: normal probe with the retries
        self.assertEqual(self.client.commands[-1][1], 2)
        self.assertIs(self.engine.online[did], False)
        self.engine.health(self.d)          # already offline: one quick attempt
        self.assertEqual(self.client.commands[-1][1], 0)
        self.assertEqual(self.client.retries, 2)   # restored afterwards
        self.assertEqual(self.engine.offline_probes[did], 1)
        self.assertEqual(PROBE_DELAYS[:2], (2, 5))
        self.client.fail = False
        self.engine.health(self.d)
        self.assertIs(self.engine.online[did], True)
        self.assertNotIn(did, self.engine.offline_info)
        self.assertNotIn(did, self.engine.offline_probes)

    def test_relocation_updates_the_address_only_when_the_new_one_answers(self):
        did = self.d["id"]
        self.engine.online[did] = False
        self.engine.offline_info[did] = {"since": 0, "reason": "unreachable"}   # offline for ages
        done = threading.Event()
        def run(found, answers):
            with patch.object(engine_module, "locate", return_value=found), \
                    patch.object(engine_module, "probe", return_value={"error_code": 0} if answers else None):
                self.engine.last_relocate.clear()
                self.engine.maybe_relocate(self.d)
                for thread in threading.enumerate():
                    if thread.name == "keeper-relocate":
                        thread.join(5)
        run("192.168.1.99", answers=False)
        self.assertEqual(self.store.get_device(did)["ip"], "192.168.1.10")
        run("192.168.1.99", answers=True)
        self.assertEqual(self.store.get_device(did)["ip"], "192.168.1.99")

    def test_relocation_respects_the_setting_and_needs_an_identity(self):
        did = self.d["id"]
        self.engine.offline_info[did] = {"since": 0, "reason": "unreachable"}
        self.store.change(lambda cfg: cfg.update(auto_find_device=False))
        with patch.object(engine_module, "locate", side_effect=AssertionError("must not ask")):
            self.engine.maybe_relocate(self.d)
            self.store.change(lambda cfg: cfg.update(auto_find_device=True))
            self.engine.maybe_relocate({**self.d, "mac": "", "device_id": 0})


class LocateTests(unittest.TestCase):
    def test_matches_by_mac_ignoring_case_and_separators_then_by_device_id(self):
        cloud = [{"ip": "10.0.0.8", "mac": "11-22-33-44-55-66", "device_id": 5}, {"ip": "10.0.0.9", "mac": "", "device_id": 77}]
        with patch("keeper.protocol.discover", return_value=cloud):
            self.assertEqual(locate({"mac": "11:22:33:44:55:66"}), "10.0.0.8")
            self.assertEqual(locate({"device_id": 77}), "10.0.0.9")
            self.assertEqual(locate({"mac": "de:ad:be:ef:00:00"}), "")
            self.assertEqual(locate({}), "")


if __name__ == "__main__":
    unittest.main()
