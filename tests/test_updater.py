import base64
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools import updater


class _Response:
    def __init__(self, payload: bytes, status: int = 200):
        self._payload = io.BytesIO(payload)
        self.status = status
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, size: int = -1) -> bytes:
        return self._payload.read(size)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = updater.UpdatePaths.from_root(self.root / "updates")
        self.key = Ed25519PrivateKey.generate()
        self.public = base64.urlsafe_b64encode(
            self.key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        ).decode().rstrip("=")

    def tearDown(self):
        self.temp.cleanup()

    def _manifest(self, *, package: bytes = b"package", version: str = "1.2.3"):
        now = datetime.now(timezone.utc)
        target = {
            "url": "https://updates.example.test/release.zip",
            "sha256": hashlib.sha256(package).hexdigest(),
            "size": len(package),
        }
        document = {
            "schema_version": 1,
            "channel": "stable",
            "version": version,
            "min_launcher_version": "1.0.0",
            "published_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(days=2)).isoformat(),
            "rollout_percentage": 100,
            "targets": {"macos-arm64": target},
        }
        signature = self.key.sign(
            updater._canonical_json(document)
        )
        document["signature"] = {
            "key_id": "test-key",
            "value": base64.urlsafe_b64encode(signature).decode().rstrip("="),
        }
        manifest = updater.Manifest.from_mapping(document)
        return manifest, document

    def _archive(self, version: str = "1.2.3") -> bytes:
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("release.json", json.dumps({"version": version}))
            bundle.writestr("app/main.py", "print('healthy')\n")
        return payload.getvalue()

    def test_manifest_signature_and_time_are_verified(self):
        manifest, _ = self._manifest()
        manifest.verify_signature({"test-key": self.public})
        manifest.validate_time()

        with self.assertRaises(updater.UpdateError):
            manifest.verify_signature({"other-key": self.public})

        future = manifest.published_at - timedelta(seconds=1)
        with self.assertRaises(updater.UpdateError):
            manifest.validate_time(future)

    def test_manifest_rejects_insecure_or_malformed_targets(self):
        _, document = self._manifest()
        document["targets"]["macos-arm64"]["url"] = "http://updates.example.test/release.zip"
        with self.assertRaises(updater.UpdateError):
            updater.Manifest.from_mapping(document)

        _, document = self._manifest()
        document["targets"]["macos-arm64"]["size"] = updater.MAX_PACKAGE_BYTES + 1
        with self.assertRaises(updater.UpdateError):
            updater.Manifest.from_mapping(document)

    def test_redirect_downgrade_is_rejected(self):
        with self.assertRaises(updater.UpdateError):
            updater.fetch_manifest(
                "http://updates.example.test/manifest.json",
                opener=lambda *_args, **_kwargs: _Response(b"{}"),
            )

        class RedirectResponse(_Response):
            def geturl(self):
                return "http://updates.example.test/release.zip"

        with self.assertRaises(updater.UpdateError):
            updater.fetch_manifest(
                "https://updates.example.test/manifest.json",
                opener=lambda *_args, **_kwargs: RedirectResponse(b"{}"),
            )

    def test_download_checks_hash_and_size(self):
        package = b"verified package"
        target = updater.Target(
            "https://updates.example.test/release.zip",
            hashlib.sha256(package).hexdigest(),
            len(package),
        )
        destination = self.root / "staging" / "release.zip"
        with mock.patch.object(updater.urllib.request, "urlopen", return_value=_Response(package)):
            updater.download_target(target, destination)
        self.assertEqual(destination.read_bytes(), package)
        self.assertFalse(destination.with_name("release.zip.partial").exists())

        bad = updater.Target(target.url, "0" * 64, target.size)
        with mock.patch.object(updater.urllib.request, "urlopen", return_value=_Response(package)):
            with self.assertRaises(updater.UpdateError):
                updater.download_target(bad, self.root / "bad.zip")

    def test_download_resumes_only_from_a_valid_range_response(self):
        package = b"prefix-and-resumed-body"
        target = updater.Target(
            "https://updates.example.test/release.zip",
            hashlib.sha256(package).hexdigest(),
            len(package),
        )
        destination = self.root / "resume.zip"
        destination.with_name("resume.zip.partial").write_bytes(package[:7])
        requests = []

        def opener(request, timeout):
            requests.append(request)
            return _Response(package[7:], status=206)

        updater.download_target(target, destination, opener=opener)
        self.assertEqual(destination.read_bytes(), package)
        self.assertEqual(requests[0].headers["Range"], "bytes=7-")

    def test_archive_rejects_traversal_and_special_files(self):
        archive = self.root / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("../escape.txt", "no")
        with self.assertRaises(updater.UpdateError):
            updater.extract_archive(archive, self.root / "out")
        self.assertFalse((self.root / "escape.txt").exists())

    def test_archive_rejects_newer_runtime_data_schema(self):
        archive = self.root / "future.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(
                "release.json",
                json.dumps({"schema_version": 1, "version": "1.2.3", "data_schema_version": 2}),
            )
        with self.assertRaises(updater.UpdateError):
            updater.extract_archive(archive, self.root / "future-out")

    def test_prune_is_safe_before_versions_directory_exists(self):
        updater.prune_versions(self.paths, updater.UpdateState())

    def test_archive_preserves_runtime_executable_mode(self):
        archive = self.root / "mode.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            marker = zipfile.ZipInfo("release.json")
            marker.external_attr = (0o100644) << 16
            bundle.writestr(marker, json.dumps({"version": "1.2.3"}))
            runtime = zipfile.ZipInfo("runtime/bin/python")
            runtime.external_attr = (0o100755) << 16
            bundle.writestr(runtime, "python")
        destination = updater.extract_archive(archive, self.root / "mode-out")
        with zipfile.ZipFile(archive) as bundle:
            stored_mode = (bundle.getinfo("runtime/bin/python").external_attr >> 16) & 0o777
        self.assertEqual(stored_mode, 0o755)
        if os.name == "nt":
            # Windows does not expose POSIX execute bits through st_mode.
            self.assertTrue((destination / "runtime/bin/python").is_file())
        else:
            self.assertTrue(os.stat(destination / "runtime/bin/python").st_mode & 0o111)

    def test_prepare_activate_health_and_rollback(self):
        package = self._archive()
        target = updater.Target(
            "https://updates.example.test/release.zip",
            hashlib.sha256(package).hexdigest(),
            len(package),
        )
        manifest, _ = self._manifest(package=package)
        self.paths.ensure()
        with mock.patch.object(updater.urllib.request, "urlopen", return_value=_Response(package)):
            installed = updater.prepare_and_install(
                self.paths,
                manifest,
                "macos-arm64",
                trusted_keys={"test-key": self.public},
            )
        self.assertTrue((installed / "app" / "main.py").exists())
        state = updater.activate(self.paths, manifest.version)
        self.assertEqual(state.pending_version, manifest.version)
        state = updater.mark_healthy(self.paths, manifest.version)
        self.assertEqual(state.current_version, manifest.version)

        second_package = self._archive("1.2.4")
        second_manifest, _ = self._manifest(package=second_package, version="1.2.4")
        with mock.patch.object(updater.urllib.request, "urlopen", return_value=_Response(second_package)):
            updater.prepare_and_install(
                self.paths,
                second_manifest,
                "macos-arm64",
                trusted_keys={"test-key": self.public},
            )
        updater.activate(self.paths, "1.2.4")
        rolled = updater.rollback(self.paths, "probe failed")
        self.assertEqual(rolled.current_version, "1.2.3")
        self.assertIn("1.2.4", rolled.failed_versions)
        with self.assertRaises(updater.UpdateError):
            updater.activate(self.paths, "1.2.4")

    def test_prepare_rejects_invalid_signature_before_io(self):
        package = self._archive()
        _, document = self._manifest(package=package)
        document["signature"]["value"] = "invalid"
        manifest = updater.Manifest.from_mapping(document)
        opener = mock.Mock(side_effect=AssertionError("network must not be used"))

        with self.assertRaises(updater.UpdateError):
            updater.prepare_and_install(
                self.paths,
                manifest,
                "macos-arm64",
                opener=opener,
                trusted_keys={"test-key": self.public},
            )

        opener.assert_not_called()
        self.assertFalse(self.paths.root.exists())

    def test_healthy_activation_prunes_only_obsolete_releases(self):
        self.paths.ensure()
        for version in ("1.0.0", "1.1.0", "1.2.0", "1.3.0"):
            (self.paths.versions / version).mkdir()
        state = updater.UpdateState(
            current_version="1.2.0",
            previous_version="1.1.0",
            pending_version="1.3.0",
        )
        state.save(self.paths)
        updater.mark_healthy(self.paths, "1.3.0")
        self.assertTrue((self.paths.versions / "1.3.0").exists())
        self.assertTrue((self.paths.versions / "1.2.0").exists())
        self.assertFalse((self.paths.versions / "1.0.0").exists())

    def test_mark_healthy_requires_installed_non_downgrade(self):
        self.paths.ensure()
        updater.UpdateState(current_version="2.0.0").save(self.paths)
        with self.assertRaises(updater.UpdateError):
            updater.mark_healthy(self.paths, "2.1.0")

        (self.paths.versions / "1.9.0").mkdir()
        with self.assertRaises(updater.UpdateError):
            updater.mark_healthy(self.paths, "1.9.0")

    def test_state_corruption_fails_closed(self):
        self.paths.ensure()
        self.paths.state.write_text("{not json", encoding="utf-8")
        with self.assertRaises(updater.UpdateError):
            updater.UpdateState.load(self.paths)

    def test_state_field_types_fail_closed(self):
        self.paths.ensure()
        invalid_documents = (
            {"install_id": 123},
            {"current_version": 123},
            {"last_check": 123},
            {"last_error": 123},
            {"failed_versions": ["1.0.0", 123]},
        )
        for fields in invalid_documents:
            document = {"schema_version": 1, **fields}
            self.paths.state.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(updater.UpdateError):
                updater.UpdateState.load(self.paths)

    def test_state_backup_recovers_from_torn_primary(self):
        self.paths.ensure()
        original = updater.UpdateState(current_version="1.0.0")
        original.save(self.paths)
        newer = updater.UpdateState.load(self.paths)
        newer.current_version = "1.1.0"
        newer.save(self.paths)
        self.paths.state.write_text("{torn", encoding="utf-8")
        recovered = updater.UpdateState.load(self.paths)
        self.assertEqual(recovered.current_version, "1.0.0")

    def test_lock_is_released_by_scope_and_blocks_second_owner(self):
        self.paths.ensure()
        with updater.FileLock(self.paths.lock):
            with self.assertRaises(updater.UpdateError):
                with updater.FileLock(self.paths.lock):
                    pass
        with updater.FileLock(self.paths.lock):
            pass

    def test_pending_release_probe_failure_rolls_back_before_launch(self):
        self.paths.ensure()
        release = self.paths.versions / "1.2.3"
        (release / "app").mkdir(parents=True)
        executable = release / "runtime"
        executable.write_text("placeholder", encoding="utf-8")
        state = updater.UpdateState(
            current_version="1.0.0",
            previous_version="1.0.0",
            pending_version="1.2.3",
        )
        state.save(self.paths)
        with mock.patch.object(
            updater.subprocess, "run", return_value=mock.Mock(returncode=1)
        ) as probe, mock.patch.object(updater.subprocess, "Popen") as launch:
            result = updater.run_child(self.paths, release, executable, [])
        self.assertEqual(result, 1)
        probe.assert_called_once()
        launch.assert_not_called()
        rolled = updater.UpdateState.load(self.paths)
        self.assertEqual(rolled.current_version, "1.0.0")
        self.assertIn("1.2.3", rolled.failed_versions)

    def test_rollout_is_stable_and_anti_rollback_applies(self):
        manifest, _ = self._manifest()
        state = updater.UpdateState(install_id="fixed")
        self.assertTrue(
            updater.choose_update(
                manifest,
                state,
                "macos-arm64",
                channel="stable",
                trusted_keys={"test-key": self.public},
            )
        )
        self.assertFalse(
            updater.choose_update(
                manifest,
                state,
                "macos-x86_64",
                trusted_keys={"test-key": self.public},
            )
        )
        state.current_version = "9.0.0"
        self.assertFalse(
            updater.choose_update(
                manifest,
                state,
                "macos-arm64",
                channel="stable",
                trusted_keys={"test-key": self.public},
            )
        )

    def test_platform_target_is_explicit(self):
        self.assertEqual(updater.platform_target("win32", "AMD64"), "windows-x86_64")
        self.assertEqual(updater.platform_target("darwin", "arm64"), "macos-arm64")
        with self.assertRaises(updater.UpdateError):
            updater.platform_target("linux", "x86_64")


if __name__ == "__main__":
    unittest.main()
