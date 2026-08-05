import io
import json
import unittest
from typing import Any, cast
from unittest import mock

from interfaces.web import WebInterfaceHandler


class WebPairingSecurityTests(unittest.TestCase):
    def setUp(self):
        self.original_token = WebInterfaceHandler.pairing_token
        self.original_rate_limit = WebInterfaceHandler.REMOTE_RATE_LIMIT_REQUESTS
        self.original_max_clients = WebInterfaceHandler.MAX_TRACKED_REMOTE_CLIENTS
        WebInterfaceHandler.pairing_token = "test-pairing-token"
        WebInterfaceHandler._remote_request_times.clear()

    def tearDown(self):
        WebInterfaceHandler.pairing_token = self.original_token
        WebInterfaceHandler.REMOTE_RATE_LIMIT_REQUESTS = self.original_rate_limit
        WebInterfaceHandler.MAX_TRACKED_REMOTE_CLIENTS = self.original_max_clients
        WebInterfaceHandler._remote_request_times.clear()

    def _make_handler(self, path: str, headers: dict[str, str] | None = None):
        handler = cast(Any, object.__new__(WebInterfaceHandler))
        handler.engine = object()
        handler.path = path
        handler.command = "GET"
        handler.client_address = ("127.0.0.1", 50000)
        handler.headers = headers or {}
        handler.rfile = io.BytesIO()
        handler.wfile = io.BytesIO()
        self.statuses: list[int] = []
        self.response_headers: list[tuple[str, str]] = []
        handler.send_response = lambda status, message=None: self.statuses.append(status)
        handler.send_header = lambda name, value: self.response_headers.append((name, value))
        handler.end_headers = lambda: None
        return handler

    def test_remote_api_is_rejected_without_pairing_cookie(self):
        handler = self._make_handler(
            "/api/profile",
            {"X-Forwarded-For": "203.0.113.20"},
        )
        handler.do_GET()

        self.assertEqual(self.statuses, [403])
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("secure QR pairing", payload["error"])

    def test_remote_pairing_requires_https(self):
        handler = self._make_handler(
            "/?pair=test-pairing-token",
            {"X-Forwarded-For": "203.0.113.20"},
        )
        handler.do_GET()

        self.assertEqual(self.statuses, [426])

    def test_https_pairing_sets_secure_cookie_and_redirects(self):
        handler = self._make_handler(
            "/?pair=test-pairing-token",
            {
                "X-Forwarded-For": "203.0.113.20",
                "X-Forwarded-Proto": "https",
            },
        )
        handler.do_GET()

        self.assertEqual(self.statuses, [303])
        response_headers = dict(self.response_headers)
        self.assertEqual(response_headers["Location"], "/")
        self.assertIn("HttpOnly", response_headers["Set-Cookie"])
        self.assertIn("Secure", response_headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", response_headers["Set-Cookie"])

    def test_remote_api_accepts_valid_pairing_cookie(self):
        handler = self._make_handler(
            "/api/plugins/mobile_camera_scanner/info",
            {
                "X-Forwarded-For": "203.0.113.20",
                "Cookie": "warranty_pair=test-pairing-token",
            },
        )
        handler.do_GET()

        self.assertEqual(self.statuses, [200])
        self.assertIn(("Cache-Control", "no-store"), self.response_headers)
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertTrue(payload["success"])

    def test_direct_lan_client_cannot_spoof_forwarded_loopback(self):
        handler = self._make_handler("/api/profile")
        handler.client_address = ("192.168.1.40", 50000)
        handler.headers = {"X-Forwarded-For": "127.0.0.1"}
        handler.do_GET()

        self.assertEqual(self.statuses, [403])

    def test_direct_lan_client_cannot_spoof_forwarded_https(self):
        handler = self._make_handler(
            "/?pair=test-pairing-token",
            {"X-Forwarded-Proto": "https"},
        )
        handler.client_address = ("192.168.1.40", 50000)
        handler.do_GET()

        self.assertEqual(self.statuses, [426])

    def test_loopback_tunnel_request_without_forwarded_for_requires_pairing(self):
        handler = self._make_handler(
            "/api/profile",
            {"X-Forwarded-Proto": "https"},
        )
        handler.do_GET()

        self.assertEqual(self.statuses, [403])

    def test_loopback_forwarded_for_value_does_not_bypass_pairing(self):
        handler = self._make_handler(
            "/api/profile",
            {"X-Forwarded-For": "127.0.0.1"},
        )
        handler.do_GET()

        self.assertEqual(self.statuses, [403])

    def test_loopback_tunnel_can_pair_without_forwarded_for(self):
        handler = self._make_handler(
            "/?pair=test-pairing-token",
            {"X-Forwarded-Proto": "https"},
        )
        handler.do_GET()

        self.assertEqual(self.statuses, [303])

    def test_pairing_qr_contains_process_token(self):
        html = WebInterfaceHandler.get_html_page(
            port=9191,
            public_url="https://scanner.example.test",
        )
        self.assertIn(
            "https://scanner.example.test?pair=test-pairing-token",
            html,
        )
        self.assertNotIn("Access-Control-Allow-Origin", html)

    def test_paired_static_zxing_asset_is_served_as_gzip(self):
        handler = self._make_handler(
            "/assets/zxing-browser-0.2.1.min.js",
            {
                "X-Forwarded-For": "203.0.113.20",
                "Cookie": "warranty_pair=test-pairing-token",
                "Accept-Encoding": "gzip",
            },
        )
        handler.do_GET()

        self.assertEqual(self.statuses, [200])
        response_headers = dict(self.response_headers)
        self.assertEqual(response_headers["Content-Encoding"], "gzip")
        self.assertEqual(
            response_headers["Content-Type"],
            "text/javascript; charset=utf-8",
        )
        self.assertGreater(len(handler.wfile.getvalue()), 100_000)

    def test_static_zxing_asset_is_decompressed_without_gzip_support(self):
        handler = self._make_handler(
            "/assets/zxing-browser-0.2.1.min.js",
            {
                "X-Forwarded-For": "203.0.113.20",
                "Cookie": "warranty_pair=test-pairing-token",
            },
        )
        handler.do_GET()

        self.assertEqual(self.statuses, [200])
        response_headers = dict(self.response_headers)
        self.assertNotIn("Content-Encoding", response_headers)
        self.assertIn(b"ZXingBrowser", handler.wfile.getvalue())

    def test_serial_query_is_bounded(self):
        handler = self._make_handler(
            "/api/scan?serial=" + ("A" * (WebInterfaceHandler.MAX_SERIAL_LENGTH + 1))
        )
        handler.do_GET()

        self.assertEqual(self.statuses, [400])
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(payload["error"], "Serial number is too long")

    def test_remote_requests_are_rate_limited(self):
        WebInterfaceHandler.REMOTE_RATE_LIMIT_REQUESTS = 2
        handler = self._make_handler(
            "/api/plugins/mobile_camera_scanner/info",
            {
                "X-Forwarded-For": "203.0.113.21",
                "Cookie": "warranty_pair=test-pairing-token",
            },
        )
        handler.do_GET()
        handler.do_GET()
        handler.do_GET()

        self.assertEqual(self.statuses, [200, 200, 429])
        self.assertIn(("Retry-After", "60"), self.response_headers)

    def test_rate_limiter_prunes_expired_clients(self):
        WebInterfaceHandler._remote_request_times.update(
            {"stale-client": [0.0], "active-client": [99.0]}
        )
        handler = self._make_handler(
            "/api/plugins/mobile_camera_scanner/info",
            {"X-Forwarded-For": "203.0.113.22"},
        )

        with mock.patch("interfaces.web.time.monotonic", return_value=100.0):
            self.assertFalse(handler._remote_request_is_rate_limited())

        self.assertNotIn("stale-client", WebInterfaceHandler._remote_request_times)
        self.assertIn("active-client", WebInterfaceHandler._remote_request_times)

    def test_rate_limiter_evicts_oldest_client_at_capacity(self):
        WebInterfaceHandler.MAX_TRACKED_REMOTE_CLIENTS = 2
        WebInterfaceHandler._remote_request_times.update(
            {"old-client": [90.0], "new-client": [99.0]}
        )
        handler = self._make_handler(
            "/api/plugins/mobile_camera_scanner/info",
            {"X-Forwarded-For": "203.0.113.23"},
        )

        with mock.patch("interfaces.web.time.monotonic", return_value=100.0):
            self.assertFalse(handler._remote_request_is_rate_limited())

        self.assertLessEqual(
            len(WebInterfaceHandler._remote_request_times),
            WebInterfaceHandler.MAX_TRACKED_REMOTE_CLIENTS,
        )
        self.assertNotIn("old-client", WebInterfaceHandler._remote_request_times)
        self.assertIn("new-client", WebInterfaceHandler._remote_request_times)
        self.assertIn("203.0.113.23", WebInterfaceHandler._remote_request_times)

    def test_csv_export_is_not_cached(self):
        handler = self._make_handler("/api/export")
        handler.engine = mock.Mock()
        handler.engine.export_csv_string.return_value = "serial,status\n"
        handler.do_GET()

        self.assertEqual(self.statuses, [200])
        self.assertIn(("Cache-Control", "no-store"), self.response_headers)

    def test_pairing_token_and_serial_are_redacted_from_request_logs(self):
        handler = self._make_handler("/")
        with mock.patch(
            "http.server.BaseHTTPRequestHandler.log_message"
        ) as base_log:
            handler.log_message(
                '"%s"',
                "GET /?pair=super-secret&serial=real-secret&next=1 HTTP/1.1",
            )

        logged_request = str(base_log.call_args.args[1])
        self.assertNotIn("super-secret", logged_request)
        self.assertNotIn("real-secret", logged_request)
        self.assertIn("pair=[REDACTED]", logged_request)
        self.assertIn("serial=[REDACTED]", logged_request)


if __name__ == "__main__":
    unittest.main()
