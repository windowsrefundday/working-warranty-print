import re
import unittest

from core.label_formatters.tspl import LabelProfile, TSPLLabelFormatter
from core.models import AssetRecord, Entitlement, SourceConfidence, VendorType


class TSPLLabelFormatterTests(unittest.TestCase):
    def setUp(self):
        # 4" x 2" label at 300 dpi with 3 mm gap; representative test profile.
        self.profile = LabelProfile(
            queue_name="TSC_MB341",
            model="MB341",
            dpi=300,
            width_mm=101.6,
            height_mm=50.8,
            gap_mm=3.0,
            darkness=7,
            speed=50,
            copies=1,
        )

    def _hp_record(self) -> AssetRecord:
        return AssetRecord(
            serial_number="MXLTEST001",
            vendor=VendorType.HP,
            model_name="HP TEST MODEL 001",
            warranty_status="Active",
            ship_date="January 1, 2099",
            expiration_date="January 1, 2100",
            entitlements=[
                Entitlement("TEST-SUPPORT", "Active"),
                Entitlement("Defective Media Retention", "Active"),
            ],
            source_confidence=SourceConfidence.VERIFIED_LIVE,
            raw_source="Live HP Warranty Portal",
            source_verified_at="2099-01-01",
            timestamp="2099-01-01 00:00:00",
        )

    def _lenovo_record(self) -> AssetRecord:
        return AssetRecord(
            serial_number="PFTEST001",
            vendor=VendorType.LENOVO,
            model_name="LENOVO TEST MODEL 002",
            warranty_status="Coverage Expiring",
            ship_date="January 2, 2099",
            expiration_date="January 1, 2100",
            entitlements=[Entitlement("TEST-PREMIUM-SUPPORT", "Active")],
            source_confidence=SourceConfidence.CACHED_REGISTRY,
            raw_source="Synthetic cached fixture",
            source_verified_at="2099-01-01",
            timestamp="2099-01-01 00:00:00",
        )

    def test_profile_converts_dimensions_to_dots(self):
        self.assertEqual(self.profile.dots(25.4), 300)  # 1 inch
        self.assertEqual(self.profile.dots(101.6), 1200)  # 4 inches

    def test_hp_label_contains_required_tspl_elements(self):
        payload = TSPLLabelFormatter.format_tspl_label(
            self._hp_record(), self.profile
        ).decode("ascii")

        # SIZE must be expressed in physical units (mm), not dots.
        self.assertIn("SIZE 101.6 mm,50.8 mm", payload)
        self.assertIn("GAP 3.0 mm,0 mm", payload)
        self.assertIn("DENSITY 7", payload)
        self.assertIn("SPEED 50", payload)
        self.assertIn("CLS", payload)
        self.assertIn("BARCODE", payload)
        self.assertIn('"MXLTEST001"', payload)
        # TSPL Code 128 symbology is selected with "128" in the BARCODE command.
        self.assertIn('BARCODE', payload)
        self.assertIn('"128"', payload)
        self.assertIn("PRINT 1,1", payload)
        # Exactly one print command
        self.assertEqual(payload.count("PRINT"), 1)
        # No stray extra copies setting
        self.assertNotIn("PRINT 2", payload)

    def test_lenovo_label_reflects_status_and_vendor(self):
        payload = TSPLLabelFormatter.format_tspl_label(
            self._lenovo_record(), self.profile
        ).decode("ascii")

        self.assertIn("Lenovo", payload)
        self.assertIn("Coverage Expiring", payload)
        self.assertIn('"PFTEST001"', payload)

    def test_long_model_name_does_not_inject_or_overlap(self):
        record = self._hp_record()
        record.model_name = "Very Long Model Name " * 20
        payload = TSPLLabelFormatter.format_tspl_label(record, self.profile).decode(
            "ascii"
        )

        # Still one label, one barcode, one print command.
        self.assertEqual(payload.count("BARCODE"), 1)
        self.assertEqual(payload.count("PRINT"), 1)
        # Truncated text stays inside a single quoted TEXT argument; no line breaks
        # or additional TSPL commands are injected from the long model name.
        text_args = re.findall(r'TEXT [\d,]+,"[^"]*"', payload)
        self.assertTrue(all("\n" not in arg for arg in text_args))

    def test_empty_entitlements_does_not_break(self):
        record = self._hp_record()
        record.entitlements = []
        payload = TSPLLabelFormatter.format_tspl_label(record, self.profile).decode(
            "ascii"
        )
        self.assertIn("PRINT 1,1", payload)

    def test_non_ascii_and_quotes_are_sanitized(self):
        record = self._hp_record()
        record.model_name = 'HP "EliteDesk" with \\backslash\\ and \x00\x01'
        record.serial_number = "PRINT;CLS\nBARCODE"
        payload = TSPLLabelFormatter.format_tspl_label(record, self.profile)

        self.assertNotIn(b'"EliteDesk"', payload)
        self.assertNotIn(b"\\", payload)
        self.assertNotIn(b"\x00", payload)
        # The literal injected newline must not survive into the data fields.
        self.assertNotIn(b'SN: PRINT\r\nBARCODE', payload)
        self.assertNotIn(b";", payload)
        self.assertIn(b"PRINT 1,1", payload)

    def test_embedded_print_and_cls_strings_do_not_execute(self):
        record = self._hp_record()
        record.model_name = "CLS PRINT 99,99\r\n"
        record.entitlements = [Entitlement("RAW COMMAND", "CLS")]
        payload = TSPLLabelFormatter.format_tspl_label(record, self.profile).decode(
            "ascii"
        )

        # Sanitized text still appears, but not as commands
        self.assertIn("RAW COMMAND", payload)
        # The only PRINT command is the legitimate terminal print.
        self.assertIn("PRINT 1,1", payload)
        print_lines = [line for line in payload.splitlines() if line.startswith("PRINT")]
        self.assertEqual(print_lines, ["PRINT 1,1"])
        cls_lines = [line for line in payload.splitlines() if line.startswith("CLS")]
        self.assertEqual(cls_lines, ["CLS"])

    def test_different_dpi_changes_dot_math(self):
        profile_203 = LabelProfile(
            queue_name="TSC_MB341",
            model="MB341",
            dpi=203,
            width_mm=101.6,
            height_mm=50.8,
            gap_mm=3.0,
            darkness=7,
            speed=50,
            copies=1,
        )
        self.assertEqual(profile_203.dots(25.4), 203)
        payload = TSPLLabelFormatter.format_tspl_label(
            self._hp_record(), profile_203
        ).decode("ascii")
        # Physical SIZE directive is independent of dpi.
        self.assertIn("SIZE 101.6 mm,50.8 mm", payload)
        # Physical gap is independent of dpi.
        self.assertIn("GAP 3.0 mm,0 mm", payload)
        # Coordinate/barcode geometry also changes (barcode at y=310 becomes y=210).
        self.assertIn("BARCODE 20,210", payload)

    def test_calibration_label_shows_profile_and_bounds(self):
        payload = TSPLLabelFormatter.format_calibration_label(
            self.profile, test_serial="CAL123"
        ).decode("ascii")

        self.assertIn("SIZE 101.6 mm,50.8 mm", payload)
        self.assertIn("300 dpi", payload)
        self.assertIn("101.6mm", payload)
        self.assertIn("CAL123", payload)
        self.assertIn("PRINT 1,1", payload)
        self.assertEqual(payload.count("PRINT"), 1)

    def test_unconfigured_profile_rejects_physical_label(self):
        unconfigured = LabelProfile(
            queue_name="TSC_MB341",
            model="MB341",
            dpi=300,
            width_mm=None,
            height_mm=None,
            gap_mm=None,
            darkness=7,
            speed=50,
            copies=1,
        )
        with self.assertRaises(RuntimeError) as ctx:
            TSPLLabelFormatter.format_tspl_label(self._hp_record(), unconfigured)
        self.assertIn("calibration", str(ctx.exception).lower())

    def test_one_by_three_profile_uses_wrapped_readable_narrow_layout(self):
        narrow = LabelProfile(
            queue_name="TSC_MB341",
            model="MB341",
            dpi=300,
            width_mm=25.4,
            height_mm=76.2,
            gap_mm=3.0,
            darkness=10,
            speed=50,
            copies=1,
        )
        payload = TSPLLabelFormatter.format_tspl_label(self._hp_record(), narrow).decode("ascii")

        self.assertIn("SIZE 25.4 mm,76.2 mm", payload)
        self.assertIn("GAP 3.0 mm,0 mm", payload)
        self.assertIn('"HP WARRANTY"', payload)
        self.assertIn('"SN: MXLTEST001"', payload)
        self.assertIn('"START: 2099-01-01"', payload)
        self.assertIn('"EXPIRES: 2100-01-01"', payload)
        self.assertIn('TEXT 14,12,"2",0,1,1,"HP WARRANTY"', payload)
        self.assertNotIn('"2",1,1,0,', payload)
        self.assertIn("REFERENCE 0,0", payload)
        self.assertEqual(payload.count("BARCODE"), 0)
        self.assertEqual(payload.count("PRINT"), 1)

    def test_three_by_one_profile_fits_text_on_one_physical_label(self):
        short_wide = LabelProfile(
            queue_name="TSC_MB341",
            model="MB341",
            dpi=300,
            width_mm=76.2,
            height_mm=25.4,
            gap_mm=3.0,
            darkness=10,
            speed=50,
            copies=1,
            offset_x_mm=2.4,
            shift_y_mm=0.0,
        )
        payload = TSPLLabelFormatter.format_tspl_label(
            self._hp_record(), short_wide
        ).decode("ascii")

        self.assertIn("SIZE 76.2 mm,25.4 mm", payload)
        self.assertIn("REFERENCE 28,0", payload)
        self.assertIn("SHIFT 0,0", payload)
        self.assertIn('TEXT 14,16,"3",0,2,2,"HP WARRANTY: ACTIVE"', payload)
        self.assertIn('"SN: MXLTEST001 | START: 2099-01-01"', payload)
        self.assertIn("MODEL: HP TEST MODEL 001", payload)
        self.assertIn('TEXT 14,116,"3",0,1,1,"SOURCE: LIVE"', payload)
        self.assertIn('TEXT 14,238,"3",0,2,2,"EXPIRES: 2100-01-01"', payload)
        self.assertNotIn("BARCODE", payload)
        self.assertEqual(payload.count("PRINT"), 1)
        self.assertEqual(payload.count("\r\nTEXT "), 5)
        # The 2x expiration row ends at dot 286, leaving white space before
        # the 300-dot label edge and 3 mm gap.
        self.assertLessEqual(238 + 48, short_wide.dots(25.4))
        for match in re.finditer(r"TEXT \d+,(\d+),", payload):
            self.assertLess(int(match.group(1)), 300)

    def test_three_by_one_expired_status_uses_a_separate_large_line(self):
        expired = self._hp_record()
        expired.warranty_status = "Coverage Expired"
        short_wide = LabelProfile(
            queue_name="TSC_MB341", model="MB341", dpi=300,
            width_mm=76.2, height_mm=25.4, gap_mm=3.0,
            darkness=10, speed=50, copies=1, offset_x_mm=2.4,
        )

        payload = TSPLLabelFormatter.format_tspl_label(expired, short_wide).decode("ascii")

        self.assertIn('TEXT 14,16,"3",0,2,2,"HP WARRANTY"', payload)
        self.assertIn('TEXT 14,68,"3",0,2,2,"COVERAGE EXPIRED"', payload)
        self.assertNotIn('"HP WARRANTY: COVERAGE EXPIRED"', payload)
        self.assertIn('TEXT 14,120,"3",0,1,1,"SN: MXLTEST001', payload)
        self.assertIn('TEXT 14,168,"3",0,1,1,"SOURCE: LIVE"', payload)
        self.assertIn('TEXT 14,238,"3",0,2,2,"EXPIRES: 2100-01-01"', payload)
        self.assertEqual(payload.count("PRINT"), 1)


if __name__ == "__main__":
    unittest.main()
