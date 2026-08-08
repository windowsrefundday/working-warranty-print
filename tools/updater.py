"""High-reliability application update and rollback primitives.

The updater deliberately lives outside the application package.  It only uses
the standard library plus the small, pinned ``cryptography`` dependency for
Ed25519 verification, so a broken application release cannot prevent rollback.
It never mutates a running checkout; releases are extracted into immutable,
versioned directories and selected through an atomically replaced state file.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


MANIFEST_SCHEMA_VERSION = 1
SUPPORTED_DATA_SCHEMA_VERSION = 1
LAUNCHER_VERSION = "1.0.0"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 50_000
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MANIFEST_URL = (
    "https://github.com/WindowsRefundDay/working-warranty-print/"
    "releases/latest/download/update-manifest.json"
)

# This is a release public key only.  The corresponding private key is kept
# outside the repository and supplied to the release workflow as a secret.
# Rotate it by shipping a new launcher with both the old and new key during the
# overlap window, then removing the old key in a later launcher release.
TRUSTED_UPDATE_KEYS: dict[str, str] = {
    "release-2026-01": "teO2o-2sN9piZyIMU2Mt-CeiLAHrfhEZLne4KKJ0ioM",
}

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class UpdateError(RuntimeError):
    """A safe, operator-visible update failure."""


def _version(value: str) -> tuple[int, int, int]:
    match = _SEMVER.fullmatch(value)
    if not match:
        raise UpdateError(f"Invalid semantic version: {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _b64decode(value: str, label: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise UpdateError(f"Invalid {label} encoding") from exc


def _utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UpdateError(f"Invalid {label} timestamp") from exc
    if parsed.tzinfo is None:
        raise UpdateError(f"{label} timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _safe_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise UpdateError("Update URLs must be HTTPS host URLs without credentials")
    return value


def _validate_response_url(response: Any) -> None:
    """Reject a redirect that downgrades a signed HTTPS URL."""
    get_url = getattr(response, "geturl", None)
    if callable(get_url):
        _safe_url(str(get_url()))


@dataclass(frozen=True)
class Target:
    """One platform-specific release artifact."""

    url: str
    sha256: str
    size: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Target":
        try:
            url = _safe_url(str(value["url"]))
            digest = str(value["sha256"]).lower()
            size = int(value["size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UpdateError("Malformed update target") from exc
        if not _SHA256.fullmatch(digest):
            raise UpdateError("Update target has an invalid SHA-256 digest")
        if size <= 0 or size > MAX_PACKAGE_BYTES:
            raise UpdateError("Update target size is outside the safe limit")
        return cls(url=url, sha256=digest, size=size)


@dataclass(frozen=True)
class Manifest:
    """Validated and signed update metadata."""

    channel: str
    version: str
    min_launcher_version: str
    published_at: datetime
    expires_at: datetime
    rollout_percentage: int
    targets: dict[str, Target]
    key_id: str
    signature: str
    _signed_document: dict[str, Any] = field(repr=False)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Manifest":
        if value.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise UpdateError("Unsupported update manifest schema")
        try:
            channel = str(value["channel"])
            version = str(value["version"])
            minimum = str(value["min_launcher_version"])
            published = _utc(str(value["published_at"]), "published_at")
            expires = _utc(str(value["expires_at"]), "expires_at")
            rollout = int(value.get("rollout_percentage", 100))
            raw_targets = value["targets"]
            raw_signature = value["signature"]
            key_id = str(raw_signature["key_id"])
            signature = str(raw_signature["value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise UpdateError("Malformed update manifest") from exc
        if channel not in {"stable", "beta"}:
            raise UpdateError("Unsupported update channel")
        _version(version)
        _version(minimum)
        if not isinstance(raw_targets, Mapping) or not raw_targets:
            raise UpdateError("Update manifest has no targets")
        if not 0 <= rollout <= 100:
            raise UpdateError("Rollout percentage must be between 0 and 100")
        if expires <= published:
            raise UpdateError("Manifest expiry must follow publication")
        targets = {
            str(name): Target.from_mapping(target)
            for name, target in raw_targets.items()
            if isinstance(target, Mapping)
        }
        if len(targets) != len(raw_targets):
            raise UpdateError("Malformed update target mapping")
        signed = json.loads(json.dumps(value))
        signed.pop("signature", None)
        if not key_id or not signature:
            raise UpdateError("Update manifest has no signature")
        return cls(
            channel=channel,
            version=version,
            min_launcher_version=minimum,
            published_at=published,
            expires_at=expires,
            rollout_percentage=rollout,
            targets=targets,
            key_id=key_id,
            signature=signature,
            _signed_document=signed,
        )

    def verify_signature(self, trusted_keys: Mapping[str, str] | None = None) -> None:
        """Verify the detached Ed25519 signature before using any target URL."""
        keys = TRUSTED_UPDATE_KEYS if trusted_keys is None else trusted_keys
        encoded_key = keys.get(self.key_id)
        if encoded_key is None:
            raise UpdateError(f"Unknown update signing key: {self.key_id}")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )

            public_key = Ed25519PublicKey.from_public_bytes(
                _b64decode(encoded_key, "public key")
            )
            public_key.verify(
                _b64decode(self.signature, "signature"),
                _canonical_json(self._signed_document),
            )
        except ImportError as exc:
            raise UpdateError(
                "The cryptography runtime is unavailable; refusing unsigned updates"
            ) from exc
        except (ValueError, TypeError) as exc:
            raise UpdateError("Invalid update signature") from exc
        except Exception as exc:
            # cryptography raises InvalidSignature, deliberately not exposed as
            # an implementation detail to operators or logs.
            raise UpdateError("Update signature verification failed") from exc

    def validate_time(self, now: datetime | None = None) -> None:
        """Reject future, expired, and otherwise replayable metadata."""
        current = now or datetime.now(timezone.utc)
        current = current.astimezone(timezone.utc)
        if self.published_at > current:
            raise UpdateError("Update manifest is dated in the future")
        if self.expires_at <= current:
            raise UpdateError("Update manifest has expired")

    def target_for(self, target_name: str) -> Target:
        try:
            return self.targets[target_name]
        except KeyError as exc:
            raise UpdateError(f"No update is published for {target_name}") from exc


@dataclass(frozen=True)
class UpdatePaths:
    """Filesystem layout for managed releases."""

    root: Path
    versions: Path
    staging: Path
    state: Path
    lock: Path

    @classmethod
    def from_root(cls, root: Path) -> "UpdatePaths":
        root = root.expanduser().resolve()
        return cls(root, root / "versions", root / "staging", root / "state.json", root / ".lock")

    def ensure(self) -> None:
        self.versions.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)


@dataclass
class UpdateState:
    """Durable pointer and rollback state."""

    install_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    current_version: str | None = None
    previous_version: str | None = None
    pending_version: str | None = None
    last_check: str | None = None
    last_error: str | None = None
    failed_versions: list[str] = field(default_factory=list)

    @classmethod
    def _parse(cls, path: Path) -> "UpdateState":
        """Parse and validate one durable update-state document."""
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, Mapping):
            raise ValueError
        if document.get("schema_version") != 1:
            raise ValueError

        def optional_text(name: str) -> str | None:
            value = document.get(name)
            if value is not None and not isinstance(value, str):
                raise ValueError
            return value

        raw_failed_versions = document.get("failed_versions", [])
        if not isinstance(raw_failed_versions, list) or not all(
            isinstance(value, str) for value in raw_failed_versions
        ):
            raise ValueError
        state = cls(
            install_id=optional_text("install_id") or uuid.uuid4().hex,
            current_version=optional_text("current_version"),
            previous_version=optional_text("previous_version"),
            pending_version=optional_text("pending_version"),
            last_check=optional_text("last_check"),
            last_error=optional_text("last_error"),
            failed_versions=raw_failed_versions,
        )
        for version in (state.current_version, state.previous_version, state.pending_version):
            if version is not None:
                _version(version)
        return state

    @classmethod
    def load(cls, paths: UpdatePaths) -> "UpdateState":
        if not paths.state.exists():
            return cls()
        try:
            return cls._parse(paths.state)
        except (OSError, json.JSONDecodeError, TypeError, ValueError, UpdateError):
            backup = paths.state.with_name(paths.state.name + ".bak")
            try:
                return cls._parse(backup)
            except (OSError, json.JSONDecodeError, TypeError, ValueError, UpdateError) as exc:
                raise UpdateError("Update state is corrupt; refusing to change releases") from exc

    def save(self, paths: UpdatePaths) -> None:
        _atomic_json_write(paths.state, self.to_mapping())

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "install_id": self.install_id,
            "current_version": self.current_version,
            "previous_version": self.previous_version,
            "pending_version": self.pending_version,
            "last_check": self.last_check,
            "last_error": self.last_error,
            "failed_versions": self.failed_versions[-20:],
        }


def _atomic_json_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    backup = path.with_name(path.name + ".bak")
    encoded = json.dumps(value, sort_keys=True, indent=2).encode("utf-8")
    try:
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            shutil.copy2(path, backup)
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Windows does not permit directory fsync; the atomic replace still
            # provides the important invariant there.
            pass
    finally:
        temporary.unlink(missing_ok=True)


class FileLock:
    """Cross-process lock released by the OS even if the updater is killed."""

    def __init__(self, path: Path):
        self.path = path
        self._handle: Any = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+", encoding="ascii")
        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                self._handle.write("0")
                self._handle.flush()
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._handle.seek(0)
            self._handle.truncate()
            self._handle.write(f"{os.getpid()}\n")
            self._handle.flush()
        except (BlockingIOError, OSError) as exc:
            self._handle.close()
            self._handle = None
            raise UpdateError("Another update operation is already running") from exc
        return self

    def __exit__(self, *_: object) -> None:
        if self._handle is not None:
            try:
                if os.name == "nt":
                    import msvcrt

                    self._handle.seek(0)
                    try:
                        msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl

                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
                self._handle.close()
            finally:
                self._handle = None


def platform_target(system: str | None = None, machine: str | None = None) -> str:
    """Return the stable artifact key for the host platform."""
    actual_system = system or sys.platform
    actual_machine = (machine or platform.machine()).lower()
    if actual_system == "win32" and actual_machine in {"amd64", "x86_64"}:
        return "windows-x86_64"
    if actual_system == "darwin" and actual_machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    if actual_system == "darwin" and actual_machine in {"amd64", "x86_64"}:
        return "macos-x86_64"
    raise UpdateError("This platform is not supported by managed updates")


def fetch_manifest(
    url: str,
    *,
    opener: Callable[..., Any] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Fetch a bounded HTTPS manifest; signature verification is separate."""
    safe_url = _safe_url(url)
    request = urllib.request.Request(safe_url, headers={"Accept": "application/json"})
    try:
        fetch = opener or urllib.request.urlopen
        with fetch(request, timeout=timeout) as response:
            _validate_response_url(response)
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_MANIFEST_BYTES:
                raise UpdateError("Update manifest is too large")
            payload = response.read(MAX_MANIFEST_BYTES + 1)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise UpdateError(f"Could not fetch update manifest: {exc}") from exc
    if len(payload) > MAX_MANIFEST_BYTES:
        raise UpdateError("Update manifest is too large")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("Update manifest is not valid UTF-8 JSON") from exc
    if not isinstance(document, Mapping):
        raise UpdateError("Update manifest must be a JSON object")
    return dict(document)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_target(
    target: Target,
    destination: Path,
    *,
    opener: Callable[..., Any] | None = None,
    timeout: float = 30.0,
) -> Path:
    """Download, resume, size-check, and hash-check one release artifact."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    try:
        required_space = min(MAX_PACKAGE_BYTES, target.size * 2 + 16 * 1024 * 1024)
        if shutil.disk_usage(destination.parent).free < required_space:
            raise UpdateError("Insufficient disk space for a safe staged update")
    except OSError as exc:
        raise UpdateError(f"Could not inspect update storage: {exc}") from exc
    existing = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(target.url)
    fetch = opener or urllib.request.urlopen
    mode = "w"
    if 0 < existing < target.size:
        request.add_header("Range", f"bytes={existing}-")
        try:
            response = fetch(request, timeout=timeout)
            response_status = getattr(response, "status", None)
            if response_status is None and hasattr(response, "getcode"):
                response_status = response.getcode()
            if response_status == 206:
                mode = "a"
            else:
                response.close()
                response = fetch(urllib.request.Request(target.url), timeout=timeout)
        except (OSError, urllib.error.URLError) as exc:
            raise UpdateError(f"Could not download update: {exc}") from exc
    else:
        if existing >= target.size:
            partial.unlink(missing_ok=True)
        try:
            response = fetch(request, timeout=timeout)
        except (OSError, urllib.error.URLError) as exc:
            raise UpdateError(f"Could not download update: {exc}") from exc
    try:
        written = existing if mode == "a" else 0
        with response, partial.open(mode + "b") as handle:
            _validate_response_url(response)
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > target.size:
                    raise UpdateError("Downloaded update exceeds its signed size")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, urllib.error.URLError) as exc:
        raise UpdateError(f"Could not write update artifact: {exc}") from exc
    if partial.stat().st_size != target.size or _sha256(partial) != target.sha256:
        partial.unlink(missing_ok=True)
        raise UpdateError("Downloaded update failed size or hash verification")
    os.replace(partial, destination)
    return destination


def _validate_member(info: zipfile.ZipInfo) -> None:
    name = info.filename.replace("\\", "/")
    path = Path(name)
    if (
        not name
        or "\x00" in name
        or path.is_absolute()
        or re.match(r"^[A-Za-z]:/", name) is not None
        or ".." in path.parts
    ):
        raise UpdateError("Update archive contains an unsafe path")
    mode = (info.external_attr >> 16) & 0xFFFF
    if stat.S_ISLNK(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode) or stat.S_ISFIFO(mode):
        raise UpdateError("Update archive contains an unsafe special file")


def extract_archive(archive: Path, destination: Path) -> Path:
    """Extract a bounded, regular-file-only ZIP into a new staging directory."""
    temporary = destination.with_name(destination.name + ".tmp")
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            if len(infos) > MAX_ARCHIVE_FILES:
                raise UpdateError("Update archive contains too many files")
            total = 0
            written = 0
            names: set[str] = set()
            for info in infos:
                _validate_member(info)
                normalized_name = info.filename.replace("\\", "/")
                if normalized_name in names:
                    raise UpdateError("Update archive contains duplicate paths")
                names.add(normalized_name)
                total += info.file_size
                if total > MAX_ARCHIVE_BYTES:
                    raise UpdateError("Update archive is too large when extracted")
                target = (temporary / info.filename).resolve()
                if temporary.resolve() not in target.parents and target != temporary.resolve():
                    raise UpdateError("Update archive escapes its staging directory")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, target.open("wb") as sink:
                    while True:
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        written += len(block)
                        if written > MAX_ARCHIVE_BYTES:
                            raise UpdateError("Update archive is too large when extracted")
                        sink.write(block)
                mode = (info.external_attr >> 16) & 0o777
                if mode:
                    os.chmod(target, mode)
        marker = temporary / "release.json"
        if not marker.is_file():
            raise UpdateError("Update archive has no release marker")
        try:
            release = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateError("Update release marker is invalid") from exc
        if (
            not isinstance(release, Mapping)
            or release.get("schema_version", 1) != 1
            or not isinstance(release.get("version"), str)
        ):
            raise UpdateError("Update release marker is incomplete")
        _version(str(release["version"]))
        data_schema = release.get("data_schema_version", SUPPORTED_DATA_SCHEMA_VERSION)
        if not isinstance(data_schema, int) or data_schema > SUPPORTED_DATA_SCHEMA_VERSION:
            raise UpdateError("Release requires an unsupported runtime-data schema")
        os.replace(temporary, destination)
        return destination
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _release_dir(paths: UpdatePaths, version: str) -> Path:
    _version(version)
    return paths.versions / version


def reset_blocked(paths: UpdatePaths) -> UpdateState:
    """Clear all blocked versions and recorded errors from the updater state."""
    paths.ensure()
    with FileLock(paths.lock):
        try:
            state = UpdateState.load(paths)
        except UpdateError:
            state = UpdateState()
        state.failed_versions.clear()
        state.last_error = None
        state.save(paths)
        return state


def activate(paths: UpdatePaths, version: str, *, force: bool = False) -> UpdateState:
    """Atomically make an already-validated version pending for next launch."""
    paths.ensure()
    with FileLock(paths.lock):
        state = UpdateState.load(paths)
        release = _release_dir(paths, version)
        if not release.is_dir():
            raise UpdateError(f"Release {version} is not installed")
        if state.current_version == version:
            return state
        if state.current_version is not None and _version(version) <= _version(state.current_version):
            raise UpdateError("Refusing to activate an older or equal release")
        if version in state.failed_versions:
            if force:
                state.failed_versions.remove(version)
            else:
                raise UpdateError(f"Release {version} is locally blocked after a failed start")
        state.previous_version = state.current_version
        state.pending_version = version
        state.last_error = None
        state.save(paths)
        return state


def mark_healthy(paths: UpdatePaths, version: str) -> UpdateState:
    """Commit a pending release after its startup probe succeeds."""
    with FileLock(paths.lock):
        state = UpdateState.load(paths)
        if state.pending_version not in {None, version}:
            raise UpdateError("Healthy report does not match the pending release")
        if not _release_dir(paths, version).is_dir():
            raise UpdateError(f"Release {version} is not installed")
        if (
            state.current_version is not None
            and _version(version) < _version(state.current_version)
        ):
            raise UpdateError("Refusing to commit an older release")
        state.previous_version = state.current_version if state.current_version != version else state.previous_version
        state.current_version = version
        state.pending_version = None
        state.last_error = None
        state.save(paths)
        prune_versions(paths, state)
        return state


def prune_versions(paths: UpdatePaths, state: UpdateState, keep: int = 2) -> None:
    """Remove only obsolete managed release directories, never active versions."""
    if not paths.versions.is_dir():
        return
    protected = {
        version
        for version in (state.current_version, state.previous_version, state.pending_version)
        if version is not None
    }
    candidates: list[tuple[tuple[int, int, int], Path]] = []
    for path in paths.versions.iterdir():
        if not path.is_dir() or path.is_symlink():
            continue
        try:
            candidates.append((_version(path.name), path))
        except UpdateError:
            continue
    candidates.sort(reverse=True)
    retained = 0
    for _, path in candidates:
        if path.name in protected or retained < keep:
            retained += 1
            continue
        shutil.rmtree(path)


def rollback(paths: UpdatePaths, reason: str = "startup health check failed") -> UpdateState:
    """Restore the last known-good version and block the failed version."""
    with FileLock(paths.lock):
        state = UpdateState.load(paths)
        if state.pending_version is None and state.previous_version is None:
            raise UpdateError("No previous release is available for rollback")
        failed = state.pending_version or state.current_version
        if failed and failed not in state.failed_versions:
            state.failed_versions.append(failed)
        state.current_version = state.previous_version
        state.pending_version = None
        state.previous_version = None
        state.last_error = reason[:500]
        state.save(paths)
        return state


def prepare_and_install(
    paths: UpdatePaths,
    manifest: Manifest,
    target_name: str,
    *,
    opener: Callable[..., Any] | None = None,
    trusted_keys: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> Path:
    """Fetch and extract a signed target without activating it."""
    manifest.verify_signature(trusted_keys)
    manifest.validate_time(now)
    paths.ensure()
    target = manifest.target_for(target_name)
    if (paths.versions / manifest.version).exists():
        return paths.versions / manifest.version
    with FileLock(paths.lock):
        if (paths.versions / manifest.version).exists():
            return paths.versions / manifest.version
        work = Path(tempfile.mkdtemp(prefix=f"{manifest.version}-", dir=paths.staging))
        try:
            archive = work / "release.zip"
            download_target(target, archive, opener=opener)
            extracted = work / "release"
            extract_archive(archive, extracted)
            marker = json.loads((extracted / "release.json").read_text(encoding="utf-8"))
            if marker.get("schema_version", 1) != 1:
                raise UpdateError("Release marker schema is unsupported")
            if marker.get("version") != manifest.version:
                raise UpdateError("Release marker version does not match signed manifest")
            if marker.get("target") not in {None, target_name}:
                raise UpdateError("Release marker target does not match signed manifest")
            data_schema = marker.get("data_schema_version", SUPPORTED_DATA_SCHEMA_VERSION)
            if not isinstance(data_schema, int) or data_schema > SUPPORTED_DATA_SCHEMA_VERSION:
                raise UpdateError("Release requires an unsupported runtime-data schema")
            final = paths.versions / manifest.version
            os.replace(extracted, final)
            return final
        finally:
            shutil.rmtree(work, ignore_errors=True)


def choose_update(
    manifest: Manifest,
    state: UpdateState,
    target_name: str,
    *,
    channel: str = "stable",
    now: datetime | None = None,
    trusted_keys: Mapping[str, str] | None = None,
) -> bool:
    """Return whether this installation is eligible for the manifest."""
    manifest.verify_signature(trusted_keys)
    manifest.validate_time(now)
    if manifest.channel != channel:
        return False
    if _version(manifest.version) <= _version(state.current_version or "0.0.0"):
        return False
    if _version(manifest.min_launcher_version) > _version(LAUNCHER_VERSION):
        raise UpdateError("This launcher is too old for the available update")
    try:
        manifest.target_for(target_name)
    except UpdateError:
        return False
    if manifest.rollout_percentage == 0:
        return False
    bucket = int(hashlib.sha256(f"{state.install_id}:{manifest.version}".encode()).hexdigest()[:8], 16) % 100
    return bucket < manifest.rollout_percentage


def run_child(
    paths: UpdatePaths,
    release_root: Path,
    executable: Path,
    arguments: Sequence[str],
    *,
    startup_grace_seconds: float = 8.0,
    runner: Callable[..., Any] = subprocess.Popen,
) -> int:
    """Run a managed application and report a pending release healthy."""
    state = UpdateState.load(paths)
    command = [str(executable), str(release_root / "app" / "main.py"), *arguments]
    environment = os.environ.copy()
    environment["WARRANTY_LABEL_MANAGED_ROOT"] = str(release_root)
    environment["PLAYWRIGHT_BROWSERS_PATH"] = str(release_root / "browsers")
    if state.pending_version:
        probe = [str(executable), str(release_root / "app" / "main.py"), "--diagnose"]
        try:
            probe_result = subprocess.run(
                probe,
                cwd=str(release_root / "app"),
                env=environment,
                capture_output=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            rollback(paths, f"release {state.pending_version} startup probe failed: {exc}")
            return 1
        if probe_result.returncode != 0:
            rollback(
                paths,
                f"release {state.pending_version} startup probe exited with code {probe_result.returncode}",
            )
            return int(probe_result.returncode or 1)
    try:
        process = runner(command, cwd=str(release_root / "app"), env=environment)
    except OSError as exc:
        if state.pending_version:
            rollback(paths, f"release {state.pending_version} could not start: {exc}")
        return 1
    pending = state.pending_version
    if pending:
        try:
            code = process.wait(timeout=startup_grace_seconds)
        except subprocess.TimeoutExpired:
            mark_healthy(paths, pending)
        else:
            if int(code) == 0:
                mark_healthy(paths, pending)
            else:
                rollback(paths, f"release {pending} exited during startup with code {code}")
            return int(code)
    return int(process.wait())


def _data_root() -> Path:
    override = os.environ.get("WARRANTY_LABEL_UPDATE_ROOT")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "WarrantyLabelPrinter" / "updates"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "WarrantyLabelPrinter" / "updates"
    return Path.home() / ".local" / "share" / "WarrantyLabelPrinter" / "updates"


def _cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Warranty Label Printer application updater")
    parser.add_argument("command", choices=("status", "rollback"))
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    paths = UpdatePaths.from_root(args.root or _data_root())
    try:
        if args.command == "status":
            print(json.dumps(UpdateState.load(paths).to_mapping(), indent=2, sort_keys=True))
        else:
            print(json.dumps(rollback(paths, "operator requested rollback").to_mapping(), indent=2, sort_keys=True))
        return 0
    except UpdateError as exc:
        print(f"Update failed safely: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
