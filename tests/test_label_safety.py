import os
import tempfile
import unittest
from datetime import date, timedelta

from core.engine import WarrantyEngine
from core.models import AssetRecord, SourceConfidence, VendorType
from core.printers.windows_connector import FilePrinterConnector


class LabelSafetyTests(unittest.TestCase):
    def test_unverified_asset_is_not_saved(self):
        asset = AssetRecord(
            serial_number="MXLTEST999",
            vendor=VendorType.HP,
            model_name="Unknown",
            warranty_status="Lookup Failed",
            ship_date="Unknown",
            expiration_date="Unknown",
            source_confidence=SourceConfidence.UNVERIFIED_FAILED,
            raw_source="HP lookup failed",
        )

        with tempfile.TemporaryDirectory() as output_dir, tempfile.TemporaryDirectory() as cache_dir:
            engine = WarrantyEngine(cache_path=os.path.join(cache_dir, "cache.db"))
            engine.connectors["file"] = FilePrinterConnector(output_dir)
            result = engine.print_asset_label(asset)

            self.assertFalse(result.success)
            self.assertIsNone(result.output_path)
            self.assertEqual([], __import__("os").listdir(output_dir))

    def test_verified_cached_asset_can_be_saved(self):
        asset = AssetRecord(
            serial_number="MXLTEST002",
            vendor=VendorType.HP,
            model_name="HP TEST MODEL 001",
            warranty_status="Active",
            ship_date="January 1, 2099",
            expiration_date="January 1, 2100",
            source_confidence=SourceConfidence.CACHED_REGISTRY,
            source_verified_at=date.today().isoformat(),
        )

        with tempfile.TemporaryDirectory() as output_dir, tempfile.TemporaryDirectory() as cache_dir:
            engine = WarrantyEngine(cache_path=os.path.join(cache_dir, "cache.db"))
            engine.connectors["file"] = FilePrinterConnector(output_dir)
            result = engine.print_asset_label(asset)

            self.assertTrue(result.success)
            self.assertEqual(["LABEL_HP_MXLTEST002.txt"], __import__("os").listdir(output_dir))

    def test_stale_cached_asset_is_not_saved(self):
        asset = AssetRecord(
            serial_number="MXLTEST002",
            vendor=VendorType.HP,
            model_name="HP TEST MODEL 001",
            warranty_status="Active",
            ship_date="January 1, 2099",
            expiration_date="January 1, 2100",
            source_confidence=SourceConfidence.CACHED_REGISTRY,
            source_verified_at=(date.today() - timedelta(days=31)).isoformat(),
        )

        with tempfile.TemporaryDirectory() as output_dir, tempfile.TemporaryDirectory() as cache_dir:
            engine = WarrantyEngine(cache_path=os.path.join(cache_dir, "cache.db"))
            engine.connectors["file"] = FilePrinterConnector(output_dir)
            result = engine.print_asset_label(asset)

            self.assertFalse(result.success)
            self.assertEqual([], __import__("os").listdir(output_dir))


if __name__ == "__main__":
    unittest.main()
