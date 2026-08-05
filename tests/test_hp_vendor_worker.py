import os
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from unittest import mock

from core.cache import WarrantyCache
from core.models import AssetRecord, Entitlement, SourceConfidence, VendorType
from core.vendors.hp import HPVendorPlugin


class FakeHPBrowserWorker:
    def __init__(self, results=None, failures=None):
        self.results = results or {}
        self.failures = failures or set()
        self.calls: list[str] = []
        self.refreshes: list[str] = []
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def prewarm(self):
        pass

    def stop(self):
        self.stopped = True

    def fetch_warranty(self, serial: str) -> AssetRecord:
        self.calls.append(serial)
        if serial in self.failures:
            return AssetRecord(
                serial_number=serial,
                vendor=VendorType.HP,
                model_name="Unknown",
                warranty_status="Lookup Failed",
                ship_date="Unknown",
                expiration_date="Unknown",
                entitlements=[],
                source_confidence=SourceConfidence.UNVERIFIED_FAILED,
                raw_source="HP Warranty Portal Lookup Failed",
                lookup_error="Simulated live failure",
            )
        return self.results[serial]

    def enqueue_refresh(self, serial: str) -> None:
        self.refreshes.append(serial)


class HPVendorPluginWorkerTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.cache = WarrantyCache(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass

    def _make_record(self, serial: str, verified_at: str | None = None) -> AssetRecord:
        return AssetRecord(
            serial_number=serial,
            vendor=VendorType.HP,
            model_name="HP TEST MODEL 001",
            warranty_status="Active",
            ship_date="January 1, 2099",
            expiration_date="January 1, 2100",
            entitlements=[Entitlement("TEST-SUPPORT", "Active")],
            source_confidence=SourceConfidence.VERIFIED_LIVE,
            raw_source="Live HP Warranty Portal",
            source_verified_at=verified_at or date.today().isoformat(),
        )

    def test_plugin_returns_worker_verified_live_result(self):
        live = self._make_record("MXLTEST010")
        worker = FakeHPBrowserWorker(results={"MXLTEST010": live})
        plugin = HPVendorPlugin(worker=worker, cache=self.cache)  # type: ignore[arg-type]

        result = plugin.fetch_warranty("MXLTEST010")

        self.assertIs(result, live)
        self.assertEqual(worker.calls, ["MXLTEST010"])

    def test_plugin_caches_successful_worker_result(self):
        live = self._make_record("MXLTEST010")
        worker = FakeHPBrowserWorker(results={"MXLTEST010": live})
        plugin = HPVendorPlugin(worker=worker, cache=self.cache)  # type: ignore[arg-type]

        plugin.fetch_warranty("MXLTEST010")

        cached = self.cache.get("HP", "MXLTEST010")
        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertEqual(cached.source_confidence, SourceConfidence.VERIFIED_LIVE)

    def test_plugin_returns_worker_verified_cache_hit_without_embedded_fallback(self):
        cached = replace(
            self._make_record("MXLTEST004"),
            source_confidence=SourceConfidence.CACHED_REGISTRY,
            raw_source="HP Cached Warranty Registry",
        )
        worker = FakeHPBrowserWorker(results={"MXLTEST004": cached})
        plugin = HPVendorPlugin(worker=worker, cache=self.cache)  # type: ignore[arg-type]

        result = plugin.fetch_warranty("MXLTEST004")

        self.assertIs(result, cached)
        self.assertEqual(result.model_name, "HP TEST MODEL 001")
        self.assertNotEqual(result.source_confidence, SourceConfidence.UNVERIFIED_FAILED)

    def test_plugin_fails_closed_when_worker_fails(self):
        worker = FakeHPBrowserWorker(failures={"MXLTEST002"})
        plugin = HPVendorPlugin(worker=worker, cache=self.cache)  # type: ignore[arg-type]

        result = plugin.fetch_warranty("MXLTEST002")

        self.assertEqual(result.source_confidence, SourceConfidence.UNVERIFIED_FAILED)
        self.assertEqual(result.model_name, "Unknown")
        self.assertEqual(result.entitlements, [])

    def test_plugin_returns_unverified_when_worker_fails_without_embedded_record(self):
        worker = FakeHPBrowserWorker(failures={"MXLTEST404"})
        plugin = HPVendorPlugin(worker=worker, cache=self.cache)  # type: ignore[arg-type]

        result = plugin.fetch_warranty("MXLTEST404")

        self.assertEqual(result.source_confidence, SourceConfidence.UNVERIFIED_FAILED)

    def test_plugin_without_worker_uses_direct_lookup_path(self):
        """Backward compatibility: no worker means the direct portal path is used."""
        plugin = HPVendorPlugin(worker=None, cache=None)
        live = self._make_record("MXLTEST010")
        with mock.patch.object(
            plugin, "_parse_live_hp_portal", return_value=(live, None)
        ):
            result = plugin.fetch_warranty("MXLTEST010")
        self.assertIs(result, live)


if __name__ == "__main__":
    unittest.main()
