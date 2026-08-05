import unittest
from unittest import mock
from typing import cast

from core.application.composition import build_default_printer_connectors
from core.printers.raw_transport import RawCupsTransport
from core.printers.tsc_connector import TSCPrinterConnector
from core.printers.windows_spooler import RawWindowsSpoolerTransport


class PlatformCompositionTests(unittest.TestCase):
    @mock.patch("core.application.composition.ProfileService")
    @mock.patch("core.application.composition.load_binding")
    def test_platform_selects_only_its_transport(
        self, load_binding_mock, profile_service_mock
    ):
        from core.printers.bindings import default_binding
        from core.printers.profiles.catalog import load_builtin_profile

        profile_service_mock.return_value.resolve.return_value = load_builtin_profile()
        load_binding_mock.side_effect = lambda platform_name, fallback_queue: (
            default_binding(fallback_queue, platform_name)
        )

        windows = build_default_printer_connectors("win32")
        self.assertEqual(set(windows), {"file", "tsc"})
        self.assertIsInstance(windows["tsc"], TSCPrinterConnector)
        windows_tsc = cast(TSCPrinterConnector, windows["tsc"])
        self.assertIsInstance(
            windows_tsc._transport, RawWindowsSpoolerTransport
        )

        mac = build_default_printer_connectors("darwin")
        self.assertEqual(set(mac), {"file", "cups", "tsc"})
        mac_tsc = cast(TSCPrinterConnector, mac["tsc"])
        self.assertIsInstance(mac_tsc._transport, RawCupsTransport)


if __name__ == "__main__":
    unittest.main()
