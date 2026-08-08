import base64
import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.package_release import PackageError, build_package
from tools.sign_manifest import create_manifest
from tools.updater import Manifest, UpdateError, platform_target
from tools.verify_release import verify_release


ROOT = Path(__file__).resolve().parents[1]


class ReleasePackagingTests(unittest.TestCase):
    def test_package_contains_marker_application_and_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "python").write_text("runtime", encoding="utf-8")
            output = root / "release.zip"
            build_package(
                ROOT,
                "1.2.3",
                platform_target(),
                output,
                runtime=runtime,
            )
            with zipfile.ZipFile(output) as bundle:
                names = set(bundle.namelist())
                self.assertIn("release.json", names)
                self.assertIn("app/main.py", names)
                self.assertIn("runtime/python", names)
                marker = json.loads(bundle.read("release.json"))
                self.assertEqual(marker["version"], "1.2.3")
                self.assertEqual(marker["target"], platform_target())
                self.assertEqual(
                    bundle.getinfo("runtime/python").compress_type,
                    zipfile.ZIP_DEFLATED,
                )

    def test_browser_symlinks_are_dereferenced_inside_browser_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "python").write_text("runtime", encoding="utf-8")
            browsers = root / "browsers"
            real_browser = browsers / "real"
            real_browser.mkdir(parents=True)
            (real_browser / "marker").write_text("browser", encoding="utf-8")
            try:
                (browsers / "linked").symlink_to(real_browser, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                if os.name == "nt":
                    self.skipTest(f"symlinks unavailable: {exc}")
                raise
            output = root / "release.zip"
            build_package(
                ROOT,
                "1.2.3",
                platform_target(),
                output,
                runtime=runtime,
                browsers=browsers,
            )
            with zipfile.ZipFile(output) as bundle:
                self.assertEqual(bundle.read("browsers/linked/marker"), b"browser")

    def test_runtime_symlinks_are_dereferenced_inside_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            real_python = runtime / "python3"
            real_python.write_text("runtime", encoding="utf-8")
            try:
                (runtime / "python").symlink_to(real_python)
            except (OSError, NotImplementedError) as exc:
                if os.name == "nt":
                    self.skipTest(f"symlinks unavailable: {exc}")
                raise
            output = root / "release.zip"
            build_package(
                ROOT,
                "1.2.3",
                platform_target(),
                output,
                runtime=runtime,
            )
            with zipfile.ZipFile(output) as bundle:
                self.assertEqual(bundle.read("runtime/python"), b"runtime")

    def test_runtime_symlink_escaping_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            runtime = root / "runtime"
            runtime.mkdir()
            try:
                (runtime / "escaped").symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                if os.name == "nt":
                    self.skipTest(f"symlinks unavailable: {exc}")
                raise
            with self.assertRaises(PackageError):
                build_package(
                    ROOT,
                    "1.2.3",
                    platform_target(),
                    root / "release.zip",
                    runtime=runtime,
                )

    def test_browser_symlink_cycles_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "python").write_text("runtime", encoding="utf-8")
            browsers = root / "browsers"
            browsers.mkdir()
            try:
                (browsers / "cycle").symlink_to(browsers, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                if os.name == "nt":
                    self.skipTest(f"symlinks unavailable: {exc}")
                raise
            with self.assertRaises(PackageError):
                build_package(
                    ROOT,
                    "1.2.3",
                    platform_target(),
                    root / "release.zip",
                    runtime=runtime,
                    browsers=browsers,
                )

    def test_node_modules_symlinks_are_dereferenced_inside_node_modules_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "python").write_text("runtime", encoding="utf-8")
            node_modules = root / "node_modules"
            real_pkg = node_modules / "localtunnel" / "bin"
            real_pkg.mkdir(parents=True)
            (real_pkg / "client.js").write_text("console.log('lt');", encoding="utf-8")
            bin_dir = node_modules / ".bin"
            bin_dir.mkdir(parents=True)
            try:
                (bin_dir / "lt").symlink_to(
                    Path("..") / "localtunnel" / "bin" / "client.js"
                )
            except (OSError, NotImplementedError) as exc:
                if os.name == "nt":
                    self.skipTest(f"symlinks unavailable: {exc}")
                raise
            output = root / "release.zip"
            build_package(
                ROOT,
                "1.2.3",
                platform_target(),
                output,
                runtime=runtime,
                node_modules=node_modules,
            )
            with zipfile.ZipFile(output) as bundle:
                self.assertEqual(
                    bundle.read("app/node_modules/.bin/lt"),
                    b"console.log('lt');",
                )

    def test_node_modules_symlink_escaping_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "python").write_text("runtime", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            node_modules = root / "node_modules"
            node_modules.mkdir()
            try:
                (node_modules / "escaped").symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                if os.name == "nt":
                    self.skipTest(f"symlinks unavailable: {exc}")
                raise
            with self.assertRaises(PackageError):
                build_package(
                    ROOT,
                    "1.2.3",
                    platform_target(),
                    root / "release.zip",
                    runtime=runtime,
                    node_modules=node_modules,
                )

    def test_signed_manifest_round_trips_through_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "release.zip"
            asset.write_bytes(b"release")
            private = Ed25519PrivateKey.generate()
            private_b64 = base64.urlsafe_b64encode(
                private.private_bytes(
                    serialization.Encoding.Raw,
                    serialization.PrivateFormat.Raw,
                    serialization.NoEncryption(),
                )
            ).decode().rstrip("=")
            public_b64 = base64.urlsafe_b64encode(
                private.public_key().public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw
                )
            ).decode().rstrip("=")
            document = create_manifest(
                "1.2.3",
                "stable",
                "test-key",
                private_b64,
                {"macos-arm64": asset},
                "https://updates.example.test/v1",
            )
            manifest = Manifest.from_mapping(document)
            manifest.verify_signature({"test-key": public_b64})
            self.assertEqual(
                manifest.targets["macos-arm64"].sha256,
                hashlib.sha256(b"release").hexdigest(),
            )

            document["version"] = "1.2.4"
            tampered = Manifest.from_mapping(document)
            with self.assertRaises(UpdateError):
                tampered.verify_signature({"test-key": public_b64})

            unsafe_asset = root / "release #1.zip"
            unsafe_asset.write_bytes(b"release")
            with self.assertRaises(RuntimeError):
                create_manifest(
                    "1.2.3",
                    "stable",
                    "test-key",
                    private_b64,
                    {"macos-arm64": unsafe_asset},
                    "https://updates.example.test/v1",
                )

    def test_release_verifier_rejects_tampered_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "release.zip"
            asset.write_bytes(b"release")
            private = Ed25519PrivateKey.generate()
            private_b64 = base64.urlsafe_b64encode(
                private.private_bytes(
                    serialization.Encoding.Raw,
                    serialization.PrivateFormat.Raw,
                    serialization.NoEncryption(),
                )
            ).decode().rstrip("=")
            public_b64 = base64.urlsafe_b64encode(
                private.public_key().public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw
                )
            ).decode().rstrip("=")
            document = create_manifest(
                "1.2.3",
                "stable",
                "test-key",
                private_b64,
                {"macos-arm64": asset},
                "https://updates.example.test/v1",
            )
            manifest_path = root / "update-manifest.json"
            manifest_path.write_text(json.dumps(document), encoding="utf-8")
            verify_release(
                manifest_path,
                {"macos-arm64": asset},
                trusted_keys={"test-key": public_b64},
            )

            asset.write_bytes(b"tampered")
            with self.assertRaises(UpdateError):
                verify_release(
                    manifest_path,
                    {"macos-arm64": asset},
                    trusted_keys={"test-key": public_b64},
                )


if __name__ == "__main__":
    unittest.main()
