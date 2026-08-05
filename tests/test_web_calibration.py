import io
import json
import os
import tempfile
import unittest
from typing import Any, cast
from unittest import mock

from core.engine import WarrantyEngine
from core.printers.tsc_connector import TSCPrinterConnector
from interfaces.web import WebInterfaceHandler


class WebCalibrationApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self.temp_dir.name, "cache.db")
        self.engine = WarrantyEngine(cache_path=self.cache_path)
        WebInterfaceHandler.engine = self.engine

    def tearDown(self):
        WebInterfaceHandler.engine = None
        self.temp_dir.cleanup()

    def _make_handler(
        self,
        path: str = "/",
        method: str = "GET",
        body: dict[str, object] | None = None,
        raw_body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> WebInterfaceHandler:
        handler = WebInterfaceHandler.__new__(WebInterfaceHandler)
        handler.engine = self.engine
        handler.path = path
        handler.command = method
        body_bytes = (
            raw_body
            if raw_body is not None
            else json.dumps(body).encode("utf-8") if body is not None else b""
        )
        handler.headers = cast(
            Any,
            headers if headers is not None else {"Content-Length": str(len(body_bytes))},
        )
        handler.rfile = cast(Any, io.BytesIO(body_bytes))

        self.sent_responses = []

        def mock_send_response(code: int, message: str | None = None):
            self.sent_responses.append(code)

        def mock_send_header(keyword: str, value: str):
            pass

        def mock_end_headers():
            pass

        handler.send_response = cast(Any, mock_send_response)
        handler.send_header = cast(Any, mock_send_header)
        handler.end_headers = cast(Any, mock_end_headers)

        self.written_output = []

        class DummyWFile:
            def __init__(self, out_list):
                self.out_list = out_list

            def write(self, data):
                self.out_list.append(data)

        handler.wfile = cast(Any, DummyWFile(self.written_output))
        return handler

    def test_post_rejects_malformed_content_length(self):
        handler = self._make_handler(
            path="/api/profile",
            method="POST",
            raw_body=b"{}",
            headers={"Content-Length": "not-a-number"},
        )
        handler.do_POST()

        self.assertEqual(self.sent_responses, [400])
        response = json.loads(self.written_output[0].decode("utf-8"))
        self.assertEqual(response["error"], "Malformed Content-Length")

    def test_post_rejects_oversized_body_before_reading_it(self):
        handler = self._make_handler(
            path="/api/profile",
            method="POST",
            raw_body=b"{}",
            headers={"Content-Length": str(WebInterfaceHandler.MAX_POST_BODY_BYTES + 1)},
        )
        handler.do_POST()

        self.assertEqual(self.sent_responses, [413])
        response = json.loads(self.written_output[0].decode("utf-8"))
        self.assertEqual(response["error"], "Request body is too large")

    def test_post_rejects_malformed_json_without_echoing_parser_details(self):
        handler = self._make_handler(
            path="/api/profile",
            method="POST",
            raw_body=b"{not-json",
        )
        handler.do_POST()

        self.assertEqual(self.sent_responses, [400])
        response = json.loads(self.written_output[0].decode("utf-8"))
        self.assertEqual(response["error"], "Invalid JSON payload")

    def test_calibration_rejects_oversized_test_serial(self):
        body: dict[str, object] = {
            "test_serial": "A" * (WebInterfaceHandler.MAX_SERIAL_LENGTH + 1)
        }
        handler = self._make_handler(path="/api/calibrate", method="POST", body=body)
        handler.do_POST()

        self.assertEqual(self.sent_responses, [400])
        response = json.loads(self.written_output[0].decode("utf-8"))
        self.assertEqual(response["error"], "Serial number is too long")

    def test_get_profile_returns_status_and_profile(self):
        handler = self._make_handler(path="/api/profile", method="GET")
        handler.do_GET()

        self.assertEqual(self.sent_responses, [200])
        response_data = json.loads(self.written_output[0].decode("utf-8"))
        self.assertEqual(response_data["active_connector"], "file")
        self.assertIn("tsc_status", response_data)
        self.assertIn("profile", response_data["tsc_status"])

    def test_save_profile_persists_settings_and_updates_connector(self):
        profile_path = os.path.join(self.temp_dir.name, ".tsc_profile.json")
        with mock.patch("interfaces.web.save_profile_to_file") as mock_save:
            mock_save.return_value = profile_path
            body = {
                "width_mm": 76.2,
                "height_mm": 25.4,
                "gap_mm": 3.0,
                "darkness": 10,
                "speed": 50,
                "offset_x_mm": 2.8,
                "shift_y_mm": -5.0,
                "activate_tsc": True,
            }
            handler = self._make_handler(path="/api/profile", method="POST", body=body)
            handler.do_POST()

            self.assertEqual(self.sent_responses, [200])
            res = json.loads(self.written_output[0].decode("utf-8"))
            self.assertTrue(res["success"])
            self.assertEqual(res["active_connector"], "tsc")
            self.assertEqual(res["profile"]["width_mm"], 76.2)
            self.assertEqual(res["profile"]["shift_y_mm"], -5.0)

            # TSC connector profile updated in engine
            tsc = self.engine.connectors["tsc"]
            assert isinstance(tsc, TSCPrinterConnector)
            self.assertEqual(tsc.profile.width_mm, 76.2)
            self.assertEqual(tsc.profile.shift_y_mm, -5.0)

    def test_save_profile_rejects_invalid_values(self):
        body = {
            "width_mm": -10,  # invalid negative width
            "height_mm": 25.4,
            "gap_mm": 3.0,
            "darkness": 10,
            "speed": 50,
            "offset_x_mm": 2.8,
            "shift_y_mm": -5.0,
        }
        handler = self._make_handler(path="/api/profile", method="POST", body=body)
        handler.do_POST()

        self.assertEqual(self.sent_responses, [400])
        res = json.loads(self.written_output[0].decode("utf-8"))
        self.assertIn("error", res)

    def test_preview_returns_tspl_command_output(self):
        body = {
            "width_mm": 76.2,
            "height_mm": 25.4,
            "gap_mm": 3.0,
            "darkness": 10,
            "speed": 50,
            "offset_x_mm": 2.8,
            "shift_y_mm": -5.0,
        }
        handler = self._make_handler(path="/api/preview", method="POST", body=body)
        profile_lock = mock.MagicMock()
        with mock.patch.object(
            WebInterfaceHandler,
            "tsc_profile_lock",
            profile_lock,
        ):
            handler.do_POST()

        self.assertEqual(self.sent_responses, [200])
        profile_lock.__enter__.assert_called_once_with()
        profile_lock.__exit__.assert_called_once()
        res = json.loads(self.written_output[0].decode("utf-8"))
        self.assertTrue(res["success"])
        self.assertIn("SIZE 76.2 mm,25.4 mm", res["tspl"])
        self.assertIn("DENSITY 10", res["tspl"])
        self.assertIn("SHIFT 0,-59", res["tspl"])

    @mock.patch("core.printers.tsc_connector.TSCPrinterConnector.print_calibration_label")
    def test_calibrate_invokes_printer_submission(self, mock_print):
        from core.models import PrintJobResult
        mock_print.return_value = PrintJobResult(
            success=True, printer_name="TSC_MB341", job_id="TSC_MB341-99"
        )
        body = {
            "width_mm": 76.2,
            "height_mm": 25.4,
            "gap_mm": 3.0,
            "darkness": 10,
            "speed": 50,
            "offset_x_mm": 2.8,
            "shift_y_mm": -5.0,
            "test_serial": "TEST999",
        }
        tsc = self.engine.connectors["tsc"]
        assert isinstance(tsc, TSCPrinterConnector)
        original_profile = tsc.profile
        handler = self._make_handler(path="/api/calibrate", method="POST", body=body)
        handler.do_POST()

        self.assertEqual(self.sent_responses, [200])
        res = json.loads(self.written_output[0].decode("utf-8"))
        self.assertTrue(res["success"])
        self.assertEqual(res["job_id"], "TSC_MB341-99")
        self.assertIn("TEST999", res["tspl"])
        self.assertIs(tsc.profile, original_profile)

    def test_toggle_printer_switches_active_connector(self):
        handler = self._make_handler(path="/api/printer/toggle", method="POST", body={"connector": "tsc"})
        handler.do_POST()

        self.assertEqual(self.sent_responses, [200])
        res = json.loads(self.written_output[0].decode("utf-8"))
        self.assertTrue(res["success"])
        self.assertEqual(self.engine.active_connector_key, "tsc")


if __name__ == "__main__":
    unittest.main()
