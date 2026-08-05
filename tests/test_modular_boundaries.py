import os
import tempfile
import unittest
from dataclasses import replace
from typing import Any, cast

from core.label_formatters.tspl_renderer import render_warranty
from core.models import AssetRecord, SourceConfidence, VendorType
from core.printers.profiles.catalog import load_builtin_profile
from core.printers.profiles.service import ProfileService
from core.printers.tsc_calibration import gap_sensor_payload
from interfaces.cli_commands import CLICommandRouter


class ModularBoundaryTests(unittest.TestCase):
    def _record(self):
        return AssetRecord(
            serial_number="MXLTEST005", vendor=VendorType.HP,
            model_name="HP TEST MODEL 002",
            warranty_status="Expired", ship_date="January 3, 2020",
            expiration_date="January 1, 2025", source_confidence=SourceConfidence.VERIFIED_LIVE,
        )

    def test_locked_profile_has_single_bounded_print_command(self):
        rendered = render_warranty(self._record(), load_builtin_profile())
        text = rendered.payload.decode("ascii")
        self.assertIn("SIZE 76.2 mm,25.4 mm", text)
        self.assertIn("GAP 3.0 mm,0 mm", text)
        self.assertIn("REFERENCE 28,0", text)
        self.assertIn("SHIFT 0,0", text)
        self.assertEqual(rendered.print_count, 1)
        self.assertLess(rendered.max_y, 300)

    def test_sensor_payload_is_not_a_print_payload(self):
        payload = gap_sensor_payload(load_builtin_profile()).decode("ascii")
        self.assertEqual(payload.count("GAPDETECT"), 1)
        self.assertNotIn("PRINT", payload)
        self.assertNotIn("CLS", payload)

    def test_profile_service_uses_saved_selection_then_environment_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "profile.json")
            service = ProfileService(path)
            profile = service.apply_adjustments({"darkness": 10})
            service.save_adjustments({"darkness": 10})
            self.assertEqual(service.resolve().darkness, 10)
            override = replace(profile, darkness=12)
            self.assertEqual(service.resolve(override).darkness, 12)

    def test_command_router_does_not_treat_scans_as_commands(self):
        class FakeEngine:
            connectors = {}
        self.assertIsNone(CLICommandRouter(cast(Any, FakeEngine()), lambda _: None).handle("MXLTEST005"))
