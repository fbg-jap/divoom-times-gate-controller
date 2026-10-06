import unittest

import requests

from keeper.protocol import Client, DeviceError, endpoint_candidates, reply_ok


class FakeSession:
    def __init__(self, reachable, reply):
        self.reachable, self.reply, self.calls = reachable, reply, []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        if not any(url.startswith("http://10.0.0.5/" if p == 80 else f"http://10.0.0.5:{p}/") for p in self.reachable):
            raise requests.ConnectionError("refused")
        reply = self.reply

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return reply
        return Response()


class EndpointTests(unittest.TestCase):
    def test_candidates(self):
        self.assertEqual(endpoint_candidates(0), [(80, "/post"), (9000, "/divoom_api")])
        self.assertEqual(endpoint_candidates(9000), [(9000, "/divoom_api")])
        self.assertEqual(endpoint_candidates(8080), [(8080, "/post")])

    def test_reply_formats(self):
        self.assertTrue(reply_ok({"error_code": 0}))
        self.assertTrue(reply_ok({"ReturnCode": 0}))
        self.assertFalse(reply_ok({"error_code": 1, "ReturnCode": 0}))
        self.assertFalse(reply_ok({"ReturnCode": 1}))
        self.assertFalse(reply_ok([]))

    def test_auto_falls_back_to_9000_and_remembers_it(self):
        session = FakeSession({9000}, {"ReturnCode": 0})
        client = Client("10.0.0.5", session=session, token="207245")
        client.command({"Command": "Channel/GetAllConf"})
        client.command({"Command": "Channel/GetAllConf"})
        urls = [url for url, _ in session.calls]
        self.assertEqual(urls, ["http://10.0.0.5/post", "http://10.0.0.5:9000/divoom_api",
                                "http://10.0.0.5:9000/divoom_api"])
        self.assertTrue(all(body["LocalToken"] == "207245" for _, body in session.calls))

    def test_device_error_and_no_token_by_default(self):
        session = FakeSession({80}, {"error_code": 1})
        with self.assertRaises(DeviceError):
            Client("10.0.0.5", session=session).command({"Command": "X"})
        self.assertNotIn("LocalToken", session.calls[0][1])

    def test_all_endpoints_down_raises_connection_error(self):
        with self.assertRaises(requests.ConnectionError):
            Client("10.0.0.5", session=FakeSession(set(), {})).command({"Command": "X"})


if __name__ == "__main__":
    unittest.main()
