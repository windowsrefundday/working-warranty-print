import os
import tempfile
import unittest
from datetime import date
from unittest.mock import MagicMock

from core.cache import WarrantyCache
from core.engine import WarrantyEngine
from core.models import AssetRecord, Entitlement, SourceConfidence, VendorType
from core.scanner import BarcodeScannerParser
from core.vendors.lenovo import LenovoVendorPlugin


class LenovoVendorPluginWorkerTests(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.cache = WarrantyCache(self.temp_db.name)

    def tearDown(self):
        if os.path.exists(self.temp_db.name):
            os.remove(self.temp_db.name)

    def _sample_live_record(self, serial="MZTEST001"):
        return AssetRecord(
            serial_number=serial,
            vendor=VendorType.LENOVO,
            model_name="LENOVO TEST MODEL 001",
            warranty_status="Active",
            ship_date="2099-01-01",
            expiration_date="2100-01-01",
            entitlements=[Entitlement(service_name="TEST-ONSITE-SUPPORT", status="Active")],
            source_confidence=SourceConfidence.VERIFIED_LIVE,
            raw_source="Live Lenovo Warranty Portal",
            source_verified_at=date.today().isoformat(),
        )

    def test_plugin_returns_worker_verified_live_result(self):
        mock_worker = MagicMock()
        mock_worker.fetch_warranty.return_value = self._sample_live_record("MZTEST001")

        plugin = LenovoVendorPlugin(worker=mock_worker, cache=self.cache)
        rec = plugin.fetch_warranty("MZTEST001")

        self.assertEqual(rec.serial_number, "MZTEST001")
        self.assertEqual(rec.source_confidence, SourceConfidence.VERIFIED_LIVE)

    def test_plugin_caches_successful_worker_result(self):
        mock_worker = MagicMock()
        mock_worker.fetch_warranty.return_value = self._sample_live_record("MZTEST001")

        plugin = LenovoVendorPlugin(worker=mock_worker, cache=self.cache)
        plugin.fetch_warranty("MZTEST001")

        cached = self.cache.get("Lenovo", "MZTEST001")
        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertEqual(cached.serial_number, "MZTEST001")
        self.assertEqual(cached.model_name, "LENOVO TEST MODEL 001")

    def test_plugin_returns_unverified_when_worker_fails(self):
        mock_worker = MagicMock()
        failed_rec = AssetRecord(
            serial_number="MZTEST001",
            vendor=VendorType.LENOVO,
            model_name="Unknown",
            warranty_status="Lookup Failed",
            ship_date="Unknown",
            expiration_date="Unknown",
            entitlements=[],
            source_confidence=SourceConfidence.UNVERIFIED_FAILED,
            raw_source="Lenovo Warranty Portal Lookup Failed",
            lookup_error="Lenovo portal did not return a complete verified result",
        )
        mock_worker.fetch_warranty.return_value = failed_rec

        plugin = LenovoVendorPlugin(worker=mock_worker, cache=self.cache)
        rec = plugin.fetch_warranty("MZTEST001")

        self.assertEqual(rec.source_confidence, SourceConfidence.UNVERIFIED_FAILED)
        self.assertEqual(rec.warranty_status, "Lookup Failed")

    def test_failed_lenovo_result_cannot_create_label(self):
        mock_worker = MagicMock()
        failed_rec = AssetRecord(
            serial_number="MZTEST001",
            vendor=VendorType.LENOVO,
            model_name="Unknown",
            warranty_status="Lookup Failed",
            ship_date="Unknown",
            expiration_date="Unknown",
            entitlements=[],
            source_confidence=SourceConfidence.UNVERIFIED_FAILED,
            raw_source="Lenovo Warranty Portal Lookup Failed",
            lookup_error="Failed to resolve product",
        )
        mock_worker.fetch_warranty.return_value = failed_rec

        engine = WarrantyEngine(cache_path=self.temp_db.name, lenovo_worker=mock_worker)
        res = engine.print_asset_label(failed_rec)

        self.assertFalse(res.success)
        self.assertIn("Label not created", res.error_message or "")

    def test_fresh_cached_lenovo_result_may_create_label(self):
        live_rec = self._sample_live_record("MZTEST001")
        self.cache.set(live_rec)

        cached_rec = self.cache.get("Lenovo", "MZTEST001")
        self.assertIsNotNone(cached_rec)
        assert cached_rec is not None

        engine = WarrantyEngine(cache_path=self.temp_db.name)
        res = engine.print_asset_label(cached_rec)

        self.assertTrue(res.success)
        self.assertIsNotNone(res.output_path)

    def test_synthetic_lenovo_serial_is_detected_as_lenovo(self):
        vendor = BarcodeScannerParser.detect_vendor("MZTEST01")
        self.assertEqual(vendor, VendorType.LENOVO)
