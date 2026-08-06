import unittest
from typing import Optional

from core.printers.bindings import PrinterBinding
from core.printers.windows_spooler import (
    RawWindowsSpoolerTransport,
    WindowsTSCDiscovery,
)


class FakeWindowsAPI:
    def __init__(self):
        self.items = [
            {
                "pPrinterName": "Warehouse MB341",
                "pDriverName": "TSC MB341",
                "pPortName": "USB001",
                "Status": 0,
            },
            {
                "pPrinterName": "Office Laser",
                "pDriverName": "Generic Laser",
                "pPortName": "USB002",
                "Status": 0,
            },
        ]
        self.resolution_values = [(203, 203), (300, 300)]
        self.status_mask = 0x00000080
        self.calls = []
        self.write_count: Optional[int] = None
        self.fail_write = False

    def enum_local_printers(self):
        return self.items

    def get_printer(self, queue):
        return next(item for item in self.items if item["pPrinterName"] == queue)

    def resolutions(self, queue, port):
        self.calls.append(("resolutions", queue, port))
        return self.resolution_values

    def error_status_mask(self):
        return self.status_mask

    def open_printer(self, queue):
        self.calls.append(("open", queue))
        return "HANDLE"

    def start_doc(self, handle, document_name):
        self.calls.append(("start_doc", handle, document_name))
        return 42

    def start_page(self, handle):
        self.calls.append(("start_page", handle))

    def write(self, handle, payload):
        self.calls.append(("write", handle, payload))
        if self.fail_write:
            raise RuntimeError("write failed")
        return self.write_count if self.write_count is not None else len(payload)

    def end_page(self, handle):
        self.calls.append(("end_page", handle))

    def end_doc(self, handle):
        self.calls.append(("end_doc", handle))

    def abort(self, handle):
        self.calls.append(("abort", handle))

    def close(self, handle):
        self.calls.append(("close", handle))


def binding():
    return PrinterBinding(
        platform="win32",
        queue_name="Warehouse MB341",
        driver_name="TSC MB341",
        port_name="USB001",
        model="MB341",
        dpi=300,
        confirmed=True,
    )


class WindowsDiscoveryTests(unittest.TestCase):
    def test_only_validated_usb_mb341_is_listed(self):
        api = FakeWindowsAPI()
        discovery = WindowsTSCDiscovery(binding(), api=api)
        self.assertEqual(discovery.list_candidates(), ["Warehouse MB341"])
        self.assertEqual(
            discovery.validate_for_print("Warehouse MB341"), "Warehouse MB341"
        )

    def test_alternate_queue_is_rejected_even_if_it_exists(self):
        api = FakeWindowsAPI()
        discovery = WindowsTSCDiscovery(binding(), api=api)
        with self.assertRaisesRegex(RuntimeError, "bound printer queue"):
            discovery.validate_for_print("Office Laser")

    def test_unconfirmed_default_binding_cannot_print(self):
        api = FakeWindowsAPI()
        unconfirmed = PrinterBinding(
            platform="win32",
            queue_name="Warehouse MB341",
            model="MB341",
            dpi=300,
        )
        discovery = WindowsTSCDiscovery(unconfirmed, api=api)
        self.assertIsNone(discovery.discover("Warehouse MB341"))
        with self.assertRaisesRegex(RuntimeError, "operator-confirmed"):
            discovery.validate_for_print("Warehouse MB341")

    def test_network_port_wrong_dpi_and_error_status_fail_closed(self):
        api = FakeWindowsAPI()
        discovery = WindowsTSCDiscovery(binding(), api=api)

        api.items[0]["Status"] = api.status_mask
        with self.assertRaisesRegex(RuntimeError, "paused, offline"):
            discovery.validate_for_print("Warehouse MB341")

    def test_binding_records_exact_driver_and_port(self):
        api = FakeWindowsAPI()
        discovered = WindowsTSCDiscovery(binding(), api=api).binding_for_queue(
            "Warehouse MB341"
        )
        self.assertEqual(discovered.driver_name, "TSC MB341")
        self.assertEqual(discovered.port_name, "USB001")


class WindowsRawTransportTests(unittest.TestCase):
    def test_exact_tspl_bytes_and_real_job_id_are_returned(self):
        api = FakeWindowsAPI()
        payload = b"SIZE 76.2 mm,25.4 mm\r\nPRINT 1,1\r\n"
        result = RawWindowsSpoolerTransport(api=api).submit(
            payload, "Warehouse MB341", 15
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.job_id, "42")
        self.assertEqual(result.bytes_written, len(payload))
        self.assertIn(("write", "HANDLE", payload), api.calls)
        self.assertEqual(api.calls[-1], ("close", "HANDLE"))

    def test_partial_write_aborts_without_retry(self):
        api = FakeWindowsAPI()
        api.write_count = 2
        result = RawWindowsSpoolerTransport(api=api).submit(
            b"PRINT 1,1\r\n", "Warehouse MB341", 15
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("accepted 2 of", result.stderr)
        self.assertEqual(
            [call for call in api.calls if call[0] == "write"],
            [("write", "HANDLE", b"PRINT 1,1\r\n")],
        )
        self.assertIn(("abort", "HANDLE"), api.calls)
        self.assertEqual(api.calls[-1], ("close", "HANDLE"))


if __name__ == "__main__":
    unittest.main()
