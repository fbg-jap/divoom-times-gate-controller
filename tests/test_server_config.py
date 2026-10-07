import unittest

import server


class ServerConfigTests(unittest.TestCase):
    def test_uvicorn_has_no_access_log_because_it_would_record_oauth_callback_queries(self):
        options = server.uvicorn_options("127.0.0.1", 8080)
        self.assertIs(options["access_log"], False)
        self.assertEqual((options["host"], options["port"], options["workers"], options["proxy_headers"]), ("127.0.0.1", 8080, 1, False))


if __name__ == "__main__":
    unittest.main()
