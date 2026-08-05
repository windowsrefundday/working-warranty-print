import unittest
from unittest.mock import patch

from core import diagnostics


class BrowserDiagnosticsTests(unittest.TestCase):
    def test_system_browser_is_reported_when_bundled_chromium_is_missing(self):
        result = diagnostics.subprocess.CompletedProcess(
            args=["playwright"],
            returncode=0,
            stdout="",
            stderr="",
        )
        with patch.object(diagnostics.importlib.metadata, "version", return_value="1.60.0"):
            with patch.object(diagnostics.subprocess, "run", return_value=result):
                with patch.object(
                    diagnostics,
                    "available_system_browsers",
                    return_value=("msedge", "chrome"),
                ):
                    report = diagnostics._browser_status()

        self.assertFalse(report["chromium_installed"])
        self.assertEqual(report["system_browsers"], ["msedge", "chrome"])
        self.assertTrue(report["fallback_available"])
        self.assertEqual(report["preferred_runtime"], "msedge")

    def test_bundled_chromium_remains_preferred_over_system_browser(self):
        result = diagnostics.subprocess.CompletedProcess(
            args=["playwright"],
            returncode=0,
            stdout="chromium 1234",
            stderr="",
        )
        with patch.object(diagnostics.importlib.metadata, "version", return_value="1.60.0"):
            with patch.object(diagnostics.subprocess, "run", return_value=result):
                with patch.object(
                    diagnostics,
                    "available_system_browsers",
                    return_value=("msedge",),
                ):
                    report = diagnostics._browser_status()

        self.assertTrue(report["chromium_installed"])
        self.assertEqual(report["preferred_runtime"], "bundled-chromium")


if __name__ == "__main__":
    unittest.main()
