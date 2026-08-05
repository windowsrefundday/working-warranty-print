import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.app_paths import get_app_paths
from core.printers.bindings import (
    PrinterBinding,
    load_binding,
    save_binding,
)


class CrossPlatformPathTests(unittest.TestCase):
    def test_windows_uses_local_app_data_even_when_checkout_has_spaces(self):
        with tempfile.TemporaryDirectory(prefix="Warranty App ") as directory:
            paths = get_app_paths(
                platform_name="win32",
                environment={"LOCALAPPDATA": directory},
                home=Path(directory) / "home",
                create=False,
                migrate=False,
            )
        self.assertEqual(
            paths.data_dir, Path(directory) / "WarrantyLabelPrinter"
        )
        self.assertEqual(paths.binding_path.name, "printer_binding.json")

    def test_macos_uses_application_support(self):
        home = Path("/tmp/example-home")
        paths = get_app_paths(
            platform_name="darwin",
            environment={},
            home=home,
            create=False,
            migrate=False,
        )
        self.assertEqual(
            paths.data_dir,
            home / "Library" / "Application Support" / "WarrantyLabelPrinter",
        )

    def test_binding_round_trip_is_versioned_and_platform_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "binding.json")
            binding = PrinterBinding(
                platform="win32",
                queue_name="Warehouse MB341",
                driver_name="TSC MB341",
                port_name="USB001",
                model="MB341",
                dpi=300,
                confirmed=True,
            )
            save_binding(binding, path)
            with open(path, encoding="utf-8") as handle:
                document = json.load(handle)
            self.assertEqual(document["schema_version"], 1)
            self.assertEqual(
                load_binding(path, platform_name="win32"), binding
            )
            self.assertEqual(
                load_binding(path, platform_name="darwin").queue_name,
                "TSC_MB341",
            )

    def test_windows_binding_rejects_network_port(self):
        binding = PrinterBinding(
            platform="win32",
            queue_name="TSC",
            driver_name="TSC MB341",
            port_name="IP_192.0.2.10",
            confirmed=True,
        )
        with self.assertRaisesRegex(ValueError, "USB"):
            binding.validate()

    def test_legacy_cache_profile_and_wal_are_copied_once(self):
        with tempfile.TemporaryDirectory() as checkout, tempfile.TemporaryDirectory() as data:
            root = Path(checkout)
            (root / ".warranty_cache.db").write_bytes(b"db")
            (root / ".warranty_cache.db-wal").write_bytes(b"wal")
            (root / ".tsc_profile.json").write_text("{}", encoding="utf-8")
            with mock.patch("core.app_paths.PROJECT_ROOT", root):
                paths = get_app_paths(
                    platform_name="win32",
                    environment={"LOCALAPPDATA": data},
                    home=Path(data),
                    create=True,
                    migrate=True,
                )
                self.assertEqual(paths.cache_path.read_bytes(), b"db")
                self.assertEqual(
                    Path(f"{paths.cache_path}-wal").read_bytes(), b"wal"
                )
                self.assertEqual(paths.profile_path.read_text(), "{}")
                paths.cache_path.write_bytes(b"operator-data")
                get_app_paths(
                    platform_name="win32",
                    environment={"LOCALAPPDATA": data},
                    home=Path(data),
                    create=True,
                    migrate=True,
                )
                self.assertEqual(paths.cache_path.read_bytes(), b"operator-data")


if __name__ == "__main__":
    unittest.main()
