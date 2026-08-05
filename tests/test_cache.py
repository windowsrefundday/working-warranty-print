import os
import tempfile
import threading
import unittest
from datetime import date, timedelta

from core.cache import WarrantyCache
from core.models import AssetRecord, Entitlement, SourceConfidence, VendorType


class WarrantyCacheTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.cache = WarrantyCache(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass

    def _make_record(
        self,
        serial: str = "MXLTEST001",
        verified_at: str | None = None,
        confidence: SourceConfidence = SourceConfidence.VERIFIED_LIVE,
        model_name: str = "HP TEST MODEL 001",
    ) -> AssetRecord:
        return AssetRecord(
            serial_number=serial,
            vendor=VendorType.HP,
            model_name=model_name,
            warranty_status="Active",
            ship_date="January 1, 2099",
            expiration_date="January 1, 2100",
            entitlements=[Entitlement("TEST-SUPPORT", "Active")],
            source_confidence=confidence,
            raw_source="Live HP Warranty Portal",
            source_verified_at=verified_at or date.today().isoformat(),
        )

    def test_round_trip(self):
        record = self._make_record()
        self.cache.set(record)
        fetched = self.cache.get("HP", "MXLTEST001")
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertEqual(fetched.serial_number, "MXLTEST001")
        self.assertEqual(fetched.source_confidence, SourceConfidence.VERIFIED_LIVE)
        self.assertEqual(fetched.entitlements[0].service_name, "TEST-SUPPORT")

    def test_missing_record_returns_none(self):
        self.assertIsNone(self.cache.get("HP", "UNKNOWN"))

    def test_only_verified_live_records_may_be_cached(self):
        cached = self._make_record(confidence=SourceConfidence.CACHED_REGISTRY)
        with self.assertRaises(ValueError):
            self.cache.set(cached)

    def test_set_replaces_existing_record(self):
        self.cache.set(self._make_record(model_name="First"))
        self.cache.set(self._make_record(model_name="Second"))
        fetched = self.cache.get("HP", "MXLTEST001")
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertEqual(fetched.model_name, "Second")

    def test_clear_removes_all_records(self):
        self.cache.set(self._make_record("MXLTEST001"))
        self.cache.set(self._make_record("MXLTEST003"))
        self.cache.clear()
        self.assertIsNone(self.cache.get("HP", "MXLTEST001"))
        self.assertIsNone(self.cache.get("HP", "MXLTEST003"))

    def test_concurrent_reads_and_writes_are_safe(self):
        self.cache.set(self._make_record())
        errors = []

        def writer():
            try:
                for i in range(50):
                    r = self._make_record(model_name=f"Model {i}")
                    self.cache.set(r)
            except Exception as exc:
                errors.append(exc)

        def reader():
            try:
                for _ in range(50):
                    self.cache.get("HP", "MXLTEST001")
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        fetched = self.cache.get("HP", "MXLTEST001")
        self.assertIsNotNone(fetched)


if __name__ == "__main__":
    unittest.main()
