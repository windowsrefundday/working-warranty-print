import json
import os
import tempfile
import unittest

from core.printers.profiles.catalog import (
    MB341_3X1_WARRANTY_PROFILE_ID,
    builtin_profile_metadata,
    load_builtin_profile,
)
from core.printers.profiles.repository import load_profile, save_profile


class PrinterProfileTests(unittest.TestCase):
    def test_locked_mb341_preset_has_the_confirmed_values(self):
        profile = load_builtin_profile()
        self.assertEqual(MB341_3X1_WARRANTY_PROFILE_ID, "tsc-mb341-300dpi-3x1-warranty-v1")
        self.assertEqual(profile.queue_name, "TSC_MB341")
        self.assertEqual(profile.model, "MB341")
        self.assertEqual(profile.dpi, 300)
        self.assertEqual((profile.width_mm, profile.height_mm, profile.gap_mm), (76.2, 25.4, 3.0))
        self.assertEqual((profile.darkness, profile.speed, profile.copies), (11, 50, 1))
        self.assertEqual((profile.offset_x_mm, profile.shift_y_mm), (2.4, 0.0))
        self.assertEqual(builtin_profile_metadata()["sensor_calibration"], {"label_dots": 300, "gap_dots": 35})

    def test_legacy_flat_profile_loads_without_losing_values(self):
        profile = load_builtin_profile()
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, ".tsc_profile.json")
            legacy = {
                "queue_name": "TSC_MB341",
                "model": "MB341",
                "dpi": 300,
                "width_mm": 76.2,
                "height_mm": 25.4,
                "gap_mm": 3.0,
                "darkness": 11,
                "speed": 50,
                "copies": 1,
                "offset_x_mm": 2.4,
                "shift_y_mm": 0.0,
            }
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(legacy, handle)
            self.assertEqual(load_profile(path, profile), profile)

    def test_save_uses_a_versioned_envelope_and_round_trips(self):
        profile = load_builtin_profile()
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "profile.json")
            self.assertEqual(save_profile(profile, path), path)
            with open(path, encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved["schema_version"], 1)
            self.assertEqual(saved["profile"]["shift_y_mm"], 0.0)
            self.assertEqual(load_profile(path, profile), profile)

    def test_invalid_profile_fails_closed_to_fallback(self):
        fallback = load_builtin_profile()
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "profile.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"profile": {"width_mm": -1}}')
            self.assertEqual(load_profile(path, fallback), fallback)
