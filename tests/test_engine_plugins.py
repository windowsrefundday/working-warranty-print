import os
import tempfile
import unittest

from core.engine import WarrantyEngine
from core.models import AssetRecord, SourceConfidence, VendorType
from core.vendors.base import BaseVendorPlugin, ProgressCallback


class RecordingVendor(BaseVendorPlugin):
    def __init__(self):
        self.received = []
        self.started = self.prewarmed = self.stopped = 0

    @property
    def vendor_type(self) -> VendorType:
        return VendorType.HP

    def fetch_warranty(self, serial_number: str, progress_callback: ProgressCallback | None = None) -> AssetRecord:
        self.received.append((serial_number, progress_callback))
        if progress_callback:
            progress_callback("Fake vendor complete", 100)
        return AssetRecord(
            serial_number=serial_number,
            vendor=self.vendor_type,
            model_name="Test Device",
            warranty_status="Lookup Failed",
            ship_date="Unknown",
            expiration_date="Unknown",
            source_confidence=SourceConfidence.UNVERIFIED_FAILED,
        )

    def start(self) -> None:
        self.started += 1

    def prewarm(self) -> None:
        self.prewarmed += 1

    def stop(self) -> None:
        self.stopped += 1


class EnginePluginTests(unittest.TestCase):
    def test_engine_dispatches_and_lifecycles_through_plugin_contract(self):
        plugin = RecordingVendor()
        with tempfile.TemporaryDirectory() as directory:
            engine = WarrantyEngine(
                cache_path=os.path.join(directory, "cache.db"),
                vendors={VendorType.HP: plugin, VendorType.GENERIC: plugin},
            )
            events = []
            engine.start()
            record = engine.lookup_asset(
                "mxltest001",
                progress_callback=lambda stage, pct: events.append((stage, pct)),
            )
            engine.stop()

        self.assertEqual(plugin.received[0][0], "MXLTEST001")
        self.assertEqual(events, [("Fake vendor complete", 100)])
        self.assertEqual((plugin.started, plugin.prewarmed, plugin.stopped), (1, 1, 1))
        self.assertEqual(record.source_confidence, SourceConfidence.UNVERIFIED_FAILED)
