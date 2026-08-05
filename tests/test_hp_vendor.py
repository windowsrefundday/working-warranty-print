import unittest
from unittest.mock import patch

from core.models import AssetRecord, Entitlement, SourceConfidence, VendorType
from core.vendors.hp import HPVendorPlugin


PORTAL_TEXT = """Coverage details
Active
TEST-CARE-PACK
HP TEST MODEL 001
Serial: MXLTEST001
Product: TEST-SKU-001
Coverage type
TEST-COVERAGE
Service type
TEST-SUPPORT
Status
Active
Start date
January 1, 2099
End date
January 1, 2100
Service level
Defective Media Retention
Standard
Deliverables
Material
Onsite Support
HW Problem Diagnosis
Coverage type
Factory warranty
Status
Expired
"""


class HPVendorPluginTests(unittest.TestCase):
    def setUp(self):
        self.plugin = HPVendorPlugin()

    def test_portal_text_parser_extracts_verified_care_pack(self):
        record = self.plugin._parse_portal_text("MXLTEST001", PORTAL_TEXT)

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(
            record.model_name,
            "HP TEST MODEL 001",
        )
        self.assertEqual(record.warranty_status, "Active")
        self.assertEqual(record.ship_date, "January 1, 2099")
        self.assertEqual(record.expiration_date, "January 1, 2100")
        self.assertEqual(record.source_confidence, SourceConfidence.VERIFIED_LIVE)
        self.assertEqual(
            [ent.service_name for ent in record.entitlements],
            [
                "TEST-SUPPORT",
                "Defective Media Retention",
                "Material",
                "Onsite Support",
                "HW Problem Diagnosis",
            ],
        )

    def test_portal_text_parser_rejects_wrong_serial(self):
        self.assertIsNone(
            self.plugin._parse_portal_text("MXLTEST002", PORTAL_TEXT)
        )

    def test_portal_text_parser_rejects_incomplete_result(self):
        incomplete = PORTAL_TEXT.replace("End date\nJanuary 1, 2100\n", "")
        self.assertIsNone(
            self.plugin._parse_portal_text("MXLTEST001", incomplete)
        )

    def test_portal_text_parser_does_not_treat_footer_as_entitlements(self):
        text = PORTAL_TEXT.split("Coverage type\nFactory warranty", 1)[0]
        text += "\nAbout Us\nContact HP\nPrivacy\n"
        record = self.plugin._parse_portal_text("MXLTEST001", text)

        self.assertIsNotNone(record)
        assert record is not None
        services = [ent.service_name for ent in record.entitlements]
        self.assertNotIn("About Us", services)
        self.assertNotIn("Contact HP", services)
        self.assertNotIn("Privacy", services)

    def test_live_result_is_preferred_over_failed_lookup(self):
        live = AssetRecord(
            serial_number="MXLTEST002",
            vendor=VendorType.HP,
            model_name="HP TEST LIVE MODEL",
            warranty_status="Active",
            ship_date="January 1, 2099",
            expiration_date="January 1, 2100",
            entitlements=[Entitlement("TEST-LIVE-SUPPORT", "Active")],
            source_confidence=SourceConfidence.VERIFIED_LIVE,
            raw_source="Live HP Warranty Portal",
        )
        with patch.object(
            self.plugin, "_parse_live_hp_portal", return_value=(live, None)
        ):
            self.assertIs(self.plugin.fetch_warranty("mxltest002"), live)

    def test_live_lookup_failure_fails_closed(self):
        with patch.object(
            self.plugin, "_parse_live_hp_portal", return_value=(None, None)
        ):
            record = self.plugin.fetch_warranty("MXLTEST002")

        self.assertEqual(record.source_confidence, SourceConfidence.UNVERIFIED_FAILED)
        self.assertEqual(record.model_name, "Unknown")
        self.assertEqual(record.entitlements, [])

    def test_unknown_serial_never_gets_fabricated_warranty(self):
        with patch.object(
            self.plugin,
            "_parse_live_hp_portal",
            return_value=(None, "Simulated direct failure"),
        ):
            record = self.plugin.fetch_warranty("MXLTEST999")

        self.assertEqual(record.source_confidence, SourceConfidence.UNVERIFIED_FAILED)
        self.assertEqual(record.model_name, "Unknown")
        self.assertEqual(record.warranty_status, "Lookup Failed")
        self.assertEqual(record.ship_date, "Unknown")
        self.assertEqual(record.expiration_date, "Unknown")
        self.assertEqual(record.entitlements, [])
        self.assertNotIn("Dynamic", record.raw_source)
        self.assertEqual(record.lookup_error, "Simulated direct failure")

if __name__ == "__main__":
    unittest.main()
