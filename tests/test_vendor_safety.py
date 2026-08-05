import unittest
from unittest.mock import patch

from core.models import SourceConfidence
from core.vendors.dell import DellVendorPlugin
from core.vendors.lenovo import (
    AppleVendorPlugin,
    GenericVendorPlugin,
    LenovoVendorPlugin,
)


class VendorSafetyTests(unittest.TestCase):
    def assert_unverified(self, record):
        self.assertEqual(record.source_confidence, SourceConfidence.UNVERIFIED_FAILED)
        self.assertEqual(record.warranty_status, "Lookup Failed")
        self.assertEqual(record.ship_date, "Unknown")
        self.assertEqual(record.expiration_date, "Unknown")
        self.assertEqual(record.entitlements, [])

    def test_dell_network_failure_does_not_fabricate_warranty(self):
        with patch(
            "core.vendors.dell.urllib.request.urlopen",
            side_effect=OSError("offline"),
        ):
            self.assert_unverified(DellVendorPlugin().fetch_warranty("DELLTEST001"))

    def test_lenovo_does_not_fabricate_warranty(self):
        self.assert_unverified(LenovoVendorPlugin().fetch_warranty("PFTEST001"))

    def test_apple_does_not_fabricate_warranty(self):
        self.assert_unverified(AppleVendorPlugin().fetch_warranty("APPLETEST001"))

    def test_generic_does_not_fabricate_warranty(self):
        self.assert_unverified(GenericVendorPlugin().fetch_warranty("UNKNOWN123"))


if __name__ == "__main__":
    unittest.main()
