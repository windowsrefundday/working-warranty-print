import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch
from core.models import SourceConfidence, VendorType
from core.vendors.lenovo_parser import (
    LenovoProductResolver,
    parse_lenovo_warranty,
)

SAMPLE_MZTEST001_DS = {
    "Serial": "MZTEST001",
    "ProductName": "LENOVO TEST MODEL 001",
    "MachineType": "TEST-MT-001",
    "Mode": "TEST-MODEL-001",
    "MTM": "TEST-MODEL-001",
    "Shiped": "2099-01-01",
    "BaseWarranties": [
        {
            "Start": "2099-01-01",
            "End": "2099-12-31",
            "StatusV2": "Active",
            "DeliveryType": "on_site",
            "Name": "TEST On-site Coverage",
            "Description": "TEST base warranty",
        }
    ],
    "UpmaWarranties": [
        {
            "Start": "2099-01-01",
            "End": "2100-01-01",
            "StatusV2": "Active",
            "DeliveryType": "on_site",
            "Name": "TEST On-site Extension",
            "Description": "TEST warranty upgrade",
        },
        {
            "Start": "2099-01-01",
            "End": "2100-01-01",
            "StatusV2": "Active",
            "DeliveryType": "unknown",
            "Name": "TEST-DRIVE-RETENTION",
            "Description": "TEST storage retention",
        },
    ],
}


class LenovoParserTests(unittest.TestCase):

    def test_valid_mztest001_style_page_produces_verified_record(self):
        record = parse_lenovo_warranty("MZTEST001", SAMPLE_MZTEST001_DS)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.serial_number, "MZTEST001")
        self.assertEqual(record.vendor, VendorType.LENOVO)
        self.assertEqual(record.model_name, "LENOVO TEST MODEL 001")
        self.assertEqual(record.warranty_status, "Active")
        self.assertEqual(record.ship_date, "2099-01-01")
        self.assertEqual(record.expiration_date, "2100-01-01")
        self.assertEqual(record.source_confidence, SourceConfidence.VERIFIED_LIVE)

        service_names = [e.service_name for e in record.entitlements]
        self.assertIn("Onsite Support", service_names)
        self.assertIn("TEST-DRIVE-RETENTION", service_names)

    def test_wrong_serial_is_rejected(self):
        record = parse_lenovo_warranty("WRONGSERIAL", SAMPLE_MZTEST001_DS)
        self.assertIsNone(record)

    def test_missing_serial_is_rejected(self):
        bad_ds = dict(SAMPLE_MZTEST001_DS)
        bad_ds.pop("Serial")
        bad_ds.pop("BaseProductId", None)
        record = parse_lenovo_warranty("MZTEST001", bad_ds)
        self.assertIsNone(record)

    def test_missing_warranty_status_and_items_is_rejected(self):
        bad_ds = dict(SAMPLE_MZTEST001_DS)
        bad_ds["BaseWarranties"] = []
        bad_ds["UpmaWarranties"] = []
        record = parse_lenovo_warranty("MZTEST001", bad_ds)
        self.assertIsNone(record)

    def test_missing_expiration_is_rejected(self):
        bad_ds = {
            "Serial": "MZTEST001",
            "ProductName": "Lenovo Test Device",
            "BaseWarranties": [{"Name": "Basic Warranty", "StatusV2": "Active"}],
        }
        record = parse_lenovo_warranty("MZTEST001", bad_ds)
        self.assertIsNone(record)

    def test_incomplete_product_data_cannot_be_verified(self):
        record = parse_lenovo_warranty(
            "MZTEST001",
            {"Serial": "MZTEST001", "BaseWarranties": [{"Name": "Warranty", "End": "2100-01-01"}]},
        )
        self.assertIsNone(record)

    def test_active_overall_with_only_expired_entitlements_is_rejected(self):
        record = parse_lenovo_warranty(
            "MZTEST001",
            {
                "Serial": "MZTEST001",
                "ProductName": "LENOVO TEST MODEL 002",
                "BaseWarranties": [{"Name": "Warranty", "StatusV2": "Expired", "End": "2100-01-01"}],
            },
        )
        self.assertIsNone(record)

    def test_generic_warranty_lookup_page_is_rejected(self):
        text = "Welcome to Lenovo Support. Search your product by serial number."
        record = parse_lenovo_warranty("MZTEST001", text)
        self.assertIsNone(record)

    def test_footer_and_marketing_text_are_not_parsed_as_entitlements(self):
        bad_ds = {
            "Serial": "MZTEST001",
            "ProductName": "Lenovo Test Device",
            "BaseWarranties": [
                {
                    "Name": "Privacy Policy & Footer Terms",
                    "StatusV2": "Invalid",
                    "End": "2098-01-01",
                }
            ],
        }
        record = parse_lenovo_warranty("MZTEST001", bad_ds)
        self.assertIsNone(record)

    def test_no_coverage_cards_are_excluded(self):
        bad_ds = {
            "Serial": "MZTEST001",
            "ProductName": "Lenovo Test Device",
            "BaseWarranties": [
                {
                    "Name": "Accidental Damage Protection",
                    "StatusV2": "No Coverage",
                    "End": "2098-01-01",
                }
            ],
        }
        record = parse_lenovo_warranty("MZTEST001", bad_ds)
        self.assertIsNone(record)

    def test_onsite_support_is_included_when_shown_as_covered(self):
        ds = {
            "Serial": "MZTEST001",
            "ProductName": "LENOVO TEST MODEL 002",
            "BaseWarranties": [
                {
                    "Name": "TEST Onsite Repair",
                    "StatusV2": "Active",
                    "DeliveryType": "on_site",
                    "End": "2100-01-01",
                }
            ],
        }
        record = parse_lenovo_warranty("MZTEST001", ds)
        self.assertIsNotNone(record)
        assert record is not None
        names = [e.service_name for e in record.entitlements]
        self.assertIn("Onsite Support", names)

    def test_text_fallback_is_not_treated_as_live_verified_warranty(self):
        text = "Serial: MZTEST001\nProduct: LENOVO TEST DEVICE\nWarranty Status: In Warranty\nExpiration: January 2100"
        record = parse_lenovo_warranty("MZTEST001", text)
        self.assertIsNone(record)


class LenovoProductResolverTests(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_exact_serial_result_is_accepted(self, mock_urlopen):
        resp_json = json.dumps([
            {
                "Id": "DESKTOPS-AND-ALL-IN-ONES/TEST-SERIES/TEST-MODEL/TEST-MT-001/TEST-MT-001TEST-MODEL-001/MZTEST001",
                "Name": "LENOVO TEST MODEL 001",
                "Serial": "MZTEST001",
                "Type": "Product.Serial",
            }
        ]).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = resp_json
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        pid, name, err = LenovoProductResolver.resolve_product("mztest001")
        self.assertIsNone(err)
        self.assertEqual(pid, "DESKTOPS-AND-ALL-IN-ONES/TEST-SERIES/TEST-MODEL/TEST-MT-001/TEST-MT-001TEST-MODEL-001/MZTEST001")
        self.assertEqual(name, "LENOVO TEST MODEL 001")

    @patch("urllib.request.urlopen")
    def test_case_differences_normalize_correctly(self, mock_urlopen):
        resp_json = json.dumps([
            {
                "Id": "PROD/123/mztest001",
                "Name": "LENOVO TEST MODEL 003",
                "Serial": "MZTEST001",
            }
        ]).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = resp_json
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        pid, _name, err = LenovoProductResolver.resolve_product("mztest001")
        self.assertIsNone(err)
        self.assertEqual(pid, "PROD/123/mztest001")

    @patch("urllib.request.urlopen")
    def test_empty_response_is_rejected(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"[]"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        pid, _name, err = LenovoProductResolver.resolve_product("MZTEST001")
        self.assertIsNotNone(err)
        self.assertIsNone(pid)

    @patch("urllib.request.urlopen")
    def test_invalid_json_is_rejected(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"NOT_JSON"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        _pid, _name, err = LenovoProductResolver.resolve_product("MZTEST001")
        self.assertIsNotNone(err)

    @patch("urllib.request.urlopen")
    def test_wrong_serial_response_is_rejected(self, mock_urlopen):
        resp_json = json.dumps([
            {
                "Id": "PROD/123/OTHER",
                "Name": "LENOVO TEST MODEL 003",
                "Serial": "WRONGSERIAL",
            }
        ]).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = resp_json
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        _pid, _name, err = LenovoProductResolver.resolve_product("MZTEST001")
        self.assertIsNotNone(err)

    @patch("urllib.request.urlopen")
    def test_missing_id_is_rejected(self, mock_urlopen):
        resp_json = json.dumps([
            {
                "Id": "",
                "Name": "LENOVO TEST MODEL 003",
                "Serial": "MZTEST001",
            }
        ]).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = resp_json
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        _pid, _name, err = LenovoProductResolver.resolve_product("MZTEST001")
        self.assertIsNotNone(err)

    @patch("urllib.request.urlopen")
    def test_missing_official_product_name_is_rejected(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps([{"Id": "PROD/123/MZTEST001", "Serial": "MZTEST001"}]).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        pid, name, err = LenovoProductResolver.resolve_product("MZTEST001")
        self.assertIsNone(pid)
        self.assertIsNone(name)
        self.assertIn("product name", err or "")

    @patch("urllib.request.urlopen")
    def test_http_network_failure_returns_explicit_failure(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        _pid, _name, err = LenovoProductResolver.resolve_product("MZTEST001")
        self.assertIsNotNone(err)
        self.assertIn("URLError", err or "")
