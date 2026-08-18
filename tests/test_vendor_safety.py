import unittest
import urllib.request
from unittest.mock import MagicMock, patch

from core.models import SourceConfidence
from core.vendors.dell import DellVendorPlugin
from core.vendors.http import _SameOriginRedirectHandler, open_allowed_https
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
            "core.vendors.http.urllib.request.build_opener",
            side_effect=OSError("offline"),
        ):
            self.assert_unverified(DellVendorPlugin().fetch_warranty("DELLTEST001"))

    def test_dell_rejects_invalid_service_tag_before_request(self):
        with patch("core.vendors.http.urllib.request.build_opener") as urlopen:
            self.assert_unverified(DellVendorPlugin().fetch_warranty("../DELLTEST001"))
        urlopen.assert_not_called()

    def test_vendor_http_rejects_cross_origin_redirect(self):
        response = MagicMock()
        response.geturl.return_value = "https://attacker.example/redirect"
        opened = MagicMock()
        opened.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = opened
        request = urllib.request.Request("https://www.dell.com/fixed")
        with (
            patch("core.vendors.http.urllib.request.build_opener", return_value=opener),
            self.assertRaisesRegex(ValueError, "outside the allowed HTTPS origin"),
        ):
            with open_allowed_https(
                request,
                allowed_host="www.dell.com",
                timeout=8,
            ):
                self.fail("cross-origin redirect must not be yielded")
        opened.__exit__.assert_called_once()

    def test_vendor_redirect_handler_rejects_before_following(self):
        handler = _SameOriginRedirectHandler("www.dell.com")
        request = urllib.request.Request("https://www.dell.com/fixed")
        for unsafe_url in (
            "https://attacker.example/redirect",
            "http://www.dell.com/redirect",
            "https://www.dell.com:8443/redirect",
        ):
            with self.subTest(url=unsafe_url), self.assertRaises(ValueError):
                handler.redirect_request(
                    request,
                    None,
                    302,
                    "Found",
                    {},
                    unsafe_url,
                )

    def test_lenovo_does_not_fabricate_warranty(self):
        self.assert_unverified(LenovoVendorPlugin().fetch_warranty("PFTEST001"))

    def test_apple_does_not_fabricate_warranty(self):
        self.assert_unverified(AppleVendorPlugin().fetch_warranty("APPLETEST001"))

    def test_generic_does_not_fabricate_warranty(self):
        self.assert_unverified(GenericVendorPlugin().fetch_warranty("UNKNOWN123"))


if __name__ == "__main__":
    unittest.main()
