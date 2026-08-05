import os
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from unittest import mock

import core.printers.tsc_connector as tsc_connector_module
from core.engine import WarrantyEngine
from core.models import AssetRecord, Entitlement, SourceConfidence, VendorType
from core.printers.raw_transport import RawCupsTransport
from core.printers.tsc_discovery import TSCMB341Discovery
from core.printers.tsc_connector import (
    DEFAULT_MB341_PROFILE,
    TSCPrinterConnector,
    profile_from_environment,
)


LPSTAT_P_OUTPUT = """printer TSC_MB341 is idle.  enabled since Tue Jan 01 00:00:00 2026
printer HP_OfficeJet is idle.  enabled since Tue Jan 01 00:00:00 2026"""

LPSTAT_V_OUTPUT = """device for TSC_MB341: usb://TSC/MB341?serial=000001
device for HP_OfficeJet: socket://192.168.1.100"""

LPOPTIONS_OUTPUT = """copies=1
 darkness=7
DPI=300
PageSize=Custom.4x2
"""

LPOPTIONS_L_OUTPUT = """Option 1/Print Density: *7 8 9 10 11 12 13 14 15
Option 2/Print Speed (mm/s): 20 30 40 *50 60 70 80 90
"""

LPSTAT_A_OUTPUT = "TSC_MB341 accepting requests since Tue Jan 01 00:00:00 2026\n"

LPSTAT_P_L_OUTPUT = """Printer: TSC_MB341 'TSC MB341' (Usb).
Description: TSC MB341
Make and Model: TSC MB341
Printer state: idle
"""


def _discovery_defaults():
    return {
        "lpstat -p": LPSTAT_P_OUTPUT,
        "lpstat -v": LPSTAT_V_OUTPUT,
        "lpstat -p TSC_MB341": "printer TSC_MB341 is idle.  enabled since Tue Jan 01 00:00:00 2026\n",
        "lpstat -v TSC_MB341": "device for TSC_MB341: usb://TSC/MB341?serial=000001\n",
        "lpstat -a TSC_MB341": LPSTAT_A_OUTPUT,
        "lpstat -p TSC_MB341 -l": LPSTAT_P_L_OUTPUT,
        "lpoptions -p TSC_MB341": LPOPTIONS_OUTPUT,
        "lpoptions -p TSC_MB341 -l": LPOPTIONS_L_OUTPUT,
    }


class TSCPrinterConnectorTests(unittest.TestCase):
    def setUp(self):
        # Use a measured stock profile for tests that exercise physical submission.
        self.profile = DEFAULT_MB341_PROFILE.with_dimensions(101.6, 50.8, 3.0)
        self.connector = self._cups_connector()

    def _cups_connector(self, profile=None):
        selected_profile = profile or self.profile

        def runner(*args, **kwargs):
            return tsc_connector_module.subprocess.run(*args, **kwargs)

        return TSCPrinterConnector(
            profile=selected_profile,
            transport=RawCupsTransport(runner=runner),
            discovery=TSCMB341Discovery(
                runner=runner,
                configured_queue=selected_profile.queue_name,
            ),
        )

    def _make_record(self, confidence=SourceConfidence.VERIFIED_LIVE) -> AssetRecord:
        return AssetRecord(
            serial_number="MXLTEST001",
            vendor=VendorType.HP,
            model_name="HP TEST MODEL 001",
            warranty_status="Active",
            ship_date="Jan 1, 2099",
            expiration_date="Jan 1, 2100",
            entitlements=[Entitlement("TEST-SUPPORT", "Active")],
            source_confidence=confidence,
            source_verified_at=date.today().isoformat(),
        )

    def _configure_mock(self, subprocess_run, discovery_overrides=None, lp_result=None):
        """Set up mock subprocess.run for CUPS discovery and optional lp result."""
        discovery = _discovery_defaults()
        if discovery_overrides:
            discovery.update(discovery_overrides)

        def side_effect(cmd, **kwargs):
            if cmd[0] == "lp":
                if lp_result is None:
                    return mock.MagicMock(returncode=0, stdout="", stderr="")
                return mock.MagicMock(**lp_result)
            key = " ".join(cmd)
            out = discovery.get(key, "")
            return mock.MagicMock(returncode=0, stdout=out, stderr="")

        subprocess_run.side_effect = side_effect

    @mock.patch("core.printers.tsc_connector.subprocess.run")
    def test_list_printers_finds_only_validated_tsc_mb341(self, subprocess_run):
        self._configure_mock(subprocess_run)

        printers = self.connector.list_printers()

        self.assertEqual(printers, ["TSC_MB341"])

    @mock.patch("core.printers.tsc_connector.subprocess.run")
    def test_list_printers_rejects_non_tsc_and_wrong_uri(self, subprocess_run):
        self._configure_mock(
            subprocess_run,
            discovery_overrides={
                "lpstat -p": "printer TSC_MB341 is idle.  enabled since Tue Jan 01 00:00:00 2026\n",
                "lpstat -v": "device for TSC_MB341: usb://Brother/QL820?serial=000001\n",
                "lpstat -p TSC_MB341": "printer TSC_MB341 is idle.  enabled since Tue Jan 01 00:00:00 2026\n",
                "lpstat -v TSC_MB341": "device for TSC_MB341: usb://Brother/QL820?serial=000001\n",
            },
        )

        printers = self.connector.list_printers()

        self.assertEqual(printers, [])

    @mock.patch("core.printers.tsc_connector.subprocess.run")
    def test_list_printers_rejects_stopped_or_non_accepting_queue(self, subprocess_run):
        self._configure_mock(
            subprocess_run,
            discovery_overrides={
                "lpstat -p": "printer TSC_MB341 disabled since Tue Jan 01 00:00:00 2026 -\n",
                "lpstat -p TSC_MB341": "printer TSC_MB341 disabled since Tue Jan 01 00:00:00 2026 -\n",
            },
        )

        printers = self.connector.list_printers()

        self.assertEqual(printers, [])

    @mock.patch("core.printers.tsc_connector.subprocess.run")
    def test_print_label_submits_exact_lp_argument_array(self, subprocess_run):
        self._configure_mock(
            subprocess_run,
            lp_result={
                "returncode": 0,
                "stdout": "request id is TSC_MB341-42 (1 file(s))\n",
                "stderr": "",
            },
        )

        asset = self._make_record()
        result = self.connector.print_label(asset)

        self.assertTrue(result.success)
        self.assertEqual(result.printer_name, "TSC_MB341")
        self.assertEqual(result.job_id, "TSC_MB341-42")

        calls = [c.args[0] for c in subprocess_run.call_args_list]
        lp_call = next(c for c in calls if c[0] == "lp")
        self.assertEqual(lp_call[:5], ["lp", "-d", "TSC_MB341", "-o", "raw"])
        self.assertIsInstance(lp_call[5], str)
        # The temp file is removed in finally; after the call returns it is gone.
        self.assertFalse(os.path.exists(lp_call[5]))

    @mock.patch("core.printers.tsc_connector.subprocess.run")
    def test_print_label_cleans_temp_file_on_failure(self, subprocess_run):
        captured_paths = []

        def side_effect(cmd, **kwargs):
            if cmd[0] == "lp":
                captured_paths.append(cmd[-1])
                return mock.MagicMock(returncode=1, stdout="", stderr="CUPS failure")
            discovery = _discovery_defaults()
            key = " ".join(cmd)
            out = discovery.get(key, "")
            return mock.MagicMock(returncode=0, stdout=out, stderr="")

        subprocess_run.side_effect = side_effect

        asset = self._make_record()
        result = self.connector.print_label(asset)

        self.assertFalse(result.success)
        assert result.error_message is not None
        self.assertIn("CUPS failure", result.error_message)
        self.assertTrue(captured_paths)
        self.assertFalse(os.path.exists(captured_paths[0]))

    @mock.patch("core.printers.tsc_connector.subprocess.run")
    def test_print_label_fails_when_no_tsc_queue(self, subprocess_run):
        self._configure_mock(
            subprocess_run,
            discovery_overrides={
                "lpstat -p": "",
                "lpstat -v": "",
                "lpstat -p TSC_MB341": "",
                "lpstat -v TSC_MB341": "",
                "lpstat -a TSC_MB341": "",
                "lpstat -p TSC_MB341 -l": "",
                "lpoptions -p TSC_MB341": "",
                "lpoptions -p TSC_MB341 -l": "",
            },
        )

        asset = self._make_record()
        result = self.connector.print_label(asset)

        self.assertFalse(result.success)
        assert result.error_message is not None
        self.assertIn("TSC MB341", result.error_message)
        lp_calls = [c.args[0] for c in subprocess_run.call_args_list if c.args[0][0] == "lp"]
        self.assertEqual(lp_calls, [])

    @mock.patch("core.printers.tsc_connector.subprocess.run")
    def test_gap_sensor_calibration_uses_measured_pitch(self, subprocess_run):
        profile = replace(
            DEFAULT_MB341_PROFILE.with_dimensions(76.2, 25.4, 3.0),
            offset_x_mm=2.4,
            shift_y_mm=10.1,
        )
        connector = self._cups_connector(profile)
        submitted_payload = b""

        def side_effect(cmd, **kwargs):
            nonlocal submitted_payload
            if cmd[0] == "lp":
                with open(cmd[-1], "rb") as payload_file:
                    submitted_payload = payload_file.read()
                return mock.MagicMock(
                    returncode=0,
                    stdout="request id is TSC_MB341-77\n",
                    stderr="",
                )
            output = _discovery_defaults().get(" ".join(cmd), "")
            return mock.MagicMock(returncode=0, stdout=output, stderr="")

        subprocess_run.side_effect = side_effect
        result = connector.calibrate_gap_sensor()

        self.assertTrue(result.success)
        self.assertEqual(result.job_id, "TSC_MB341-77")
        self.assertEqual(
            submitted_payload,
            (
                b"SIZE 76.2 mm,25.4 mm\r\n"
                b"GAP 3.0 mm,0 mm\r\n"
                b"GAPDETECT 300,35\r\n"
            ),
        )

    @mock.patch("core.printers.tsc_connector.subprocess.run")
    def test_print_label_revalidates_before_submission(self, subprocess_run):
        # First discovery returns valid queue.
        self._configure_mock(
            subprocess_run,
            lp_result={
                "returncode": 0,
                "stdout": "request id is TSC_MB341-1\n",
                "stderr": "",
            },
        )
        asset = self._make_record()
        result = self.connector.print_label(asset)
        self.assertTrue(result.success)

        # Now simulate queue changed to a different device with same name.
        self._configure_mock(
            subprocess_run,
            discovery_overrides={
                "lpstat -p": "printer TSC_MB341 is idle.  enabled since Tue Jan 01 00:00:00 2026\n",
                "lpstat -v": "device for TSC_MB341: usb://Brother/QL820?serial=000001\n",
                "lpstat -p TSC_MB341": "printer TSC_MB341 is idle.  enabled since Tue Jan 01 00:00:00 2026\n",
                "lpstat -v TSC_MB341": "device for TSC_MB341: usb://Brother/QL820?serial=000001\n",
                "lpstat -a TSC_MB341": LPSTAT_A_OUTPUT,
                "lpstat -p TSC_MB341 -l": LPSTAT_P_L_OUTPUT,
            },
        )
        result = self.connector.print_label(asset)
        self.assertFalse(result.success)

    @mock.patch(
        "core.printers.tsc_connector.load_saved_profile",
        return_value=DEFAULT_MB341_PROFILE,
    )
    def test_print_label_fails_when_profile_not_configured(self, _load_saved_profile):
        # Keep this test independent of any real calibration profile saved in
        # the workspace by the web UI.
        connector = TSCPrinterConnector()
        asset = self._make_record()
        result = connector.print_label(asset)

        self.assertFalse(result.success)
        assert result.error_message is not None
        self.assertIn("not configured", result.error_message.lower())
        self.assertIn("calibration", result.error_message.lower())

    def test_environment_profile_requires_complete_valid_media_values(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(profile_from_environment().is_configured())
        with mock.patch.dict(
            os.environ,
            {
                "TSC_LABEL_WIDTH_MM": "25.4",
                "TSC_LABEL_HEIGHT_MM": "76.2",
                "TSC_LABEL_GAP_MM": "3.0",
                "TSC_LABEL_DARKNESS": "10",
                "TSC_LABEL_OFFSET_X_MM": "2.8",
                "TSC_LABEL_SHIFT_Y_MM": "-10.0",
            },
            clear=True,
        ):
            profile = profile_from_environment()
            self.assertTrue(profile.is_configured())
            self.assertEqual((profile.width_mm, profile.height_mm, profile.gap_mm), (25.4, 76.2, 3.0))
            self.assertEqual(profile.darkness, 10)
            self.assertEqual(profile.offset_x_mm, 2.8)
            self.assertEqual(profile.shift_y_mm, -10.0)
        with mock.patch.dict(os.environ, {"TSC_LABEL_WIDTH_MM": "25.4"}, clear=True):
            self.assertFalse(profile_from_environment().is_configured())

    def test_saved_profile_persistence(self):
        from core.printers.tsc_connector import load_saved_profile, save_profile_to_file
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, ".tsc_profile.json")
            prof = self.profile.with_dimensions(76.2, 25.4, 3.0)
            prof = replace(prof, darkness=10, speed=50, offset_x_mm=2.8, shift_y_mm=-5.0)

            saved_path = save_profile_to_file(prof, file_path)
            self.assertEqual(saved_path, file_path)

            loaded = load_saved_profile(file_path)
            self.assertTrue(loaded.is_configured())
            self.assertEqual(loaded.width_mm, 76.2)
            self.assertEqual(loaded.height_mm, 25.4)
            self.assertEqual(loaded.gap_mm, 3.0)
            self.assertEqual(loaded.darkness, 10)
            self.assertEqual(loaded.speed, 50)
            self.assertEqual(loaded.offset_x_mm, 2.8)
            self.assertEqual(loaded.shift_y_mm, -5.0)

    @mock.patch("core.printers.tsc_connector.subprocess.run")
    def test_connector_get_status(self, subprocess_run):
        self._configure_mock(subprocess_run)
        status = self.connector.get_status()
        self.assertTrue(status["is_configured"])
        self.assertTrue(status["is_ready"])
        self.assertEqual(status["detected_queues"], ["TSC_MB341"])
        self.assertEqual(status["profile"]["width_mm"], 101.6)

    @mock.patch("core.printers.tsc_connector.subprocess.run")
    def test_print_label_rejects_not_accepting_jobs(self, subprocess_run):
        self._configure_mock(
            subprocess_run,
            discovery_overrides={
                "lpstat -a TSC_MB341": "TSC_MB341 not accepting requests since Tue Jan 01 00:00:00 2026\n",
            },
        )
        asset = self._make_record()
        result = self.connector.print_label(asset)

        self.assertFalse(result.success)
        assert result.error_message is not None
        self.assertIn("not accepting", result.error_message.lower())
        lp_calls = [c.args[0] for c in subprocess_run.call_args_list if c.args[0][0] == "lp"]
        self.assertEqual(lp_calls, [])

    @mock.patch("core.printers.tsc_connector.subprocess.run")
    def test_print_label_rejects_wrong_make_model(self, subprocess_run):
        self._configure_mock(
            subprocess_run,
            discovery_overrides={
                "lpstat -p TSC_MB341 -l": "Make and Model: Brother QL-820NWB\n",
            },
        )
        asset = self._make_record()
        result = self.connector.print_label(asset)

        self.assertFalse(result.success)
        assert result.error_message is not None
        self.assertIn("make/model", result.error_message.lower())
        lp_calls = [c.args[0] for c in subprocess_run.call_args_list if c.args[0][0] == "lp"]
        self.assertEqual(lp_calls, [])

    @mock.patch("core.printers.tsc_connector.subprocess.run")
    def test_default_connector_does_not_silently_select_alternate_mb341(self, subprocess_run):
        # Only an alternate TSC_MB341B queue exists, not the configured TSC_MB341.
        self._configure_mock(
            subprocess_run,
            discovery_overrides={
                "lpstat -p": "printer TSC_MB341B is idle.  enabled since Tue Jan 01 00:00:00 2026\n",
                "lpstat -v": "device for TSC_MB341B: usb://TSC/MB341?serial=000002\n",
                "lpstat -p TSC_MB341": "",
                "lpstat -v TSC_MB341": "",
                "lpstat -a TSC_MB341": "",
                "lpstat -p TSC_MB341 -l": "",
                "lpoptions -p TSC_MB341": "",
                "lpoptions -p TSC_MB341 -l": "",
            },
        )
        asset = self._make_record()
        result = self.connector.print_label(asset)

        self.assertFalse(result.success)
        assert result.error_message is not None
        self.assertIn("TSC MB341", result.error_message)
        lp_calls = [c.args[0] for c in subprocess_run.call_args_list if c.args[0][0] == "lp"]
        self.assertEqual(lp_calls, [])

    @mock.patch("core.printers.tsc_connector.subprocess.run")
    def test_engine_blocks_unverified_asset_before_connector(self, subprocess_run):
        self._configure_mock(subprocess_run)

        with tempfile.TemporaryDirectory() as cache_dir:
            engine = WarrantyEngine(cache_path=os.path.join(cache_dir, "cache.db"))
            engine.connectors["tsc"] = self._cups_connector()
            engine.set_active_connector("tsc")

            asset = self._make_record(SourceConfidence.UNVERIFIED_FAILED)
            result = engine.print_asset_label(asset)

            self.assertFalse(result.success)
            assert result.error_message is not None
            self.assertIn("not verified", result.error_message.lower())
            lp_calls = [c.args[0] for c in subprocess_run.call_args_list if c.args[0][0] == "lp"]
            self.assertEqual(lp_calls, [])

    @mock.patch("core.printers.tsc_connector.subprocess.run")
    def test_engine_blocks_stale_cached_asset_before_connector(self, subprocess_run):
        self._configure_mock(subprocess_run)

        with tempfile.TemporaryDirectory() as cache_dir:
            engine = WarrantyEngine(cache_path=os.path.join(cache_dir, "cache.db"))
            engine.connectors["tsc"] = self._cups_connector()
            engine.set_active_connector("tsc")

            asset = AssetRecord(
                serial_number="MXLTEST001",
                vendor=VendorType.HP,
                model_name="HP TEST MODEL 001",
                warranty_status="Active",
                ship_date="Jan 1, 2099",
                expiration_date="Jan 1, 2100",
                source_confidence=SourceConfidence.CACHED_REGISTRY,
                source_verified_at=(date.today() - timedelta(days=31)).isoformat(),
            )
            result = engine.print_asset_label(asset)

            self.assertFalse(result.success)
            assert result.error_message is not None
            self.assertIn("older than 30 days", result.error_message)
            lp_calls = [c.args[0] for c in subprocess_run.call_args_list if c.args[0][0] == "lp"]
            self.assertEqual(lp_calls, [])


if __name__ == "__main__":
    unittest.main()
