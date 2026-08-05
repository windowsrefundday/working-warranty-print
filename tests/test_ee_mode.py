import os
import tempfile
import unittest
from typing import Any, cast

from core.engine import WarrantyEngine
from core.label_formatters.tspl import TSPLLabelFormatter
from core.models import EERecord
from core.printers.file_connector import FilePrinterConnector
from core.printers.profiles.catalog import load_builtin_profile
from core.printers.tsc_connector import TSCPrinterConnector
from core.scanner import BarcodeScannerParser
from interfaces.web import WebInterfaceHandler


class _Discovery:
    def list_candidates(self):
        return ["TSC_MB341"]

    def discover(self, configured_queue):
        return configured_queue

    def validate_for_print(self, queue):
        return queue


class _TransportResult:
    returncode = 0
    stdout = ""
    stderr = ""
    job_id = 128


class _Transport:
    def __init__(self):
        self.calls = []

    def submit(self, payload, queue, timeout):
        self.calls.append((payload, queue, timeout))
        return _TransportResult()


class EEModeTests(unittest.TestCase):
    def test_record_rejects_values_that_could_escape_output_path(self):
        for value in ("", "../escaped", "12/34", "12A34", "\uff11\uff12\uff13", "1" * 21):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    EERecord(value, f"558 EE{value}")

    def test_parser_extracts_only_number_after_558_ee(self):
        accepted = {
            "558 EE128003": "128003",
            "558EE128003": "128003",
            "558 EE 128003": "128003",
            "558-ee-128003": "128003",
            "  558 ee128003  ": "128003",
        }
        for scan, expected in accepted.items():
            with self.subTest(scan=scan):
                self.assertEqual(
                    BarcodeScannerParser.parse_ee_number(scan), expected
                )

    def test_parser_rejects_non_ee_or_malformed_scans(self):
        for scan in (
            "128003",
            "558 EF128003",
            "X558 EE128003",
            "558 EE",
            "558 EE12A003",
            "558 EE123456789012345678901",
        ):
            with self.subTest(scan=scan):
                self.assertIsNone(BarcodeScannerParser.parse_ee_number(scan))

    def test_engine_recognizes_ee_without_vendor_lookup(self):
        record = WarrantyEngine.parse_ee_scan("558 EE128003")
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.ee_number, "128003")
        self.assertEqual(record.raw_code, "558 EE128003")

    def test_virtual_label_contains_only_printable_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            connector = FilePrinterConnector(directory)
            result = connector.print_ee_label(
                EERecord("128003", "558 EE128003")
            )

            self.assertTrue(result.success)
            self.assertEqual(
                os.path.basename(result.output_path or ""),
                "LABEL_EE_128003.txt",
            )
            with open(result.output_path or "", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "128003\n")

    def test_tspl_uses_large_centered_suffix_and_one_copy(self):
        record = EERecord("128003", "558 EE128003")
        payload = TSPLLabelFormatter.format_ee_label(
            record, load_builtin_profile()
        ).decode("ascii")

        self.assertIn('TEXT 66,54,"3",0,8,8,"128003"', payload)
        self.assertNotIn("558 EE", payload)
        self.assertEqual(
            [line for line in payload.splitlines() if line.startswith("PRINT ")],
            ["PRINT 1,1"],
        )

    def test_tsc_connector_submits_same_raw_payload_once(self):
        transport = _Transport()
        connector = TSCPrinterConnector(
            profile=load_builtin_profile(),
            transport=transport,
            discovery=_Discovery(),
        )
        record = EERecord("128003", "558 EE128003")

        result = connector.print_ee_label(record)

        self.assertTrue(result.success)
        self.assertEqual(result.job_id, "128")
        self.assertEqual(len(transport.calls), 1)
        payload, queue, timeout = transport.calls[0]
        self.assertEqual(
            payload,
            TSPLLabelFormatter.format_ee_label(record, load_builtin_profile()),
        )
        self.assertEqual(queue, "TSC_MB341")
        self.assertEqual(timeout, 15)

    def test_web_ui_has_dedicated_ee_result(self):
        html = WebInterfaceHandler.get_html_page()
        self.assertIn("data.mode === 'ee'", html)
        self.assertIn("escapeHtml(data.ee_number)", html)
        self.assertIn("INTERNAL EE LABEL", html)

    def test_web_api_routes_ee_scan_without_warranty_lookup(self):
        class FakeEngine:
            lookup_called = False
            printed = None

            def parse_ee_scan(self, raw):
                return EERecord("128003", raw)

            def lookup_asset(self, raw):
                self.lookup_called = True
                raise AssertionError("EE scans must not use warranty lookup")

            def print_ee_label(self, record):
                self.printed = record
                return type("Result", (), {
                    "success": True,
                    "printer_name": "Virtual_File_Printer",
                    "output_path": "/tmp/LABEL_EE_128003.txt",
                    "error_message": None,
                })()

        fake_engine = FakeEngine()
        handler = cast(Any, object.__new__(WebInterfaceHandler))
        handler.engine = fake_engine
        handler.path = "/api/scan?serial=558%20EE128003&print=true"
        response = {}

        def capture(data, status=200):
            response["data"] = data
            response["status"] = status

        handler.send_json = capture
        handler.do_GET()

        data = response["data"]
        self.assertEqual(response["status"], 200)
        self.assertEqual(data["mode"], "ee")
        self.assertEqual(data["ee_number"], "128003")
        self.assertTrue(data["print_result"]["success"])
        self.assertFalse(fake_engine.lookup_called)
        self.assertIsNotNone(fake_engine.printed)


if __name__ == "__main__":
    unittest.main()
