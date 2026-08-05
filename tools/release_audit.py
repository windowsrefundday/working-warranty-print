"""Fail closed when a source checkout contains common publication risks."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Any

import yaml  # pyright: ignore[reportMissingModuleSource, reportMissingTypeStubs]


ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRECTORIES = {".git", ".venv", "__pycache__", "node_modules"}
PROHIBITED_PATH_PARTS = {
    ".alumnium",
    ".codex-opencode",
    ".omx",
    ".playwright-cli",
    "labels",
    "playwright-report",
    "test-results",
}
PROHIBITED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".pem", ".p12", ".pfx"}
PROHIBITED_FILE_NAMES = {
    ".tsc_profile.json",
    "printer_binding.json",
    "tsc_profile.json",
}
APPROVED_BINARY_SHA256 = {
    "interfaces/static/zxing-browser-0.2.1.min.js.gz": (
        "6caa498bc43c0c77403f9788f3acbb5ed68173f57e813d9dbc8b5bec2a064d6a"
    ),
}
SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
)
ABSOLUTE_PATH_PATTERNS = (
    re.compile(re.escape("/" + "Users" + "/") + r"[^/\\\s]+"),
    re.compile(r"[A-Za-z]:\\" + re.escape("Users") + r"\\[^\\\s]+"),
)
WARRANTY_SERIAL_PATTERN = re.compile(r"\b(?:MXL|MZ)[0-9A-Z]{6,}\b", re.IGNORECASE)
SYNTHETIC_MARKERS = ("TEST", "SYNTHETIC", "EXAMPLE", "FAKE")
FULL_ACTION_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
DOCKER_DIGEST_PATTERN = re.compile(r"^docker://[^@\s]+@sha256:[0-9a-fA-F]{64}$")


def _workflow_action_is_pinned(reference: str) -> bool:
    """Return whether a workflow action reference is immutable."""
    if reference.startswith("docker://"):
        return bool(DOCKER_DIGEST_PATTERN.fullmatch(reference))
    if "@" not in reference:
        return False
    _, revision = reference.rsplit("@", 1)
    return bool(FULL_ACTION_SHA_PATTERN.fullmatch(revision))


def _workflow_action_references(content: str) -> list[str]:
    """Return every action reference from a parsed workflow document."""
    document: Any = yaml.safe_load(content)
    references: list[str] = []
    seen: set[int] = set()
    pending: list[Any] = [document]

    while pending:
        value = pending.pop()
        if isinstance(value, (dict, list)):
            identity = id(value)
            if identity in seen:
                continue
            seen.add(identity)
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "uses" and isinstance(child, str):
                    references.append(child)
                pending.append(child)
        elif isinstance(value, list):
            pending.extend(value)

    return references


def audit(root: Path = ROOT) -> list[str]:
    """Return all publication blockers without printing sensitive values."""
    failures: list[str] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in IGNORED_DIRECTORIES for part in relative.parts):
            continue
        if any(part in PROHIBITED_PATH_PARTS for part in relative.parts):
            failures.append(f"prohibited path: {relative}")
            continue
        if path.is_dir():
            continue
        if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
            failures.append(f"environment file: {relative}")
            continue
        if path.name in PROHIBITED_FILE_NAMES:
            failures.append(f"runtime configuration file: {relative}")
            continue
        if path.suffix.lower() in PROHIBITED_SUFFIXES:
            failures.append(f"prohibited file type: {relative}")
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            expected_hash = APPROVED_BINARY_SHA256.get(relative.as_posix())
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if not expected_hash or actual_hash != expected_hash:
                failures.append(f"non-text file requires manual review: {relative}")
            continue
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            failures.append(f"secret-like value: {relative}")
        if any(pattern.search(content) for pattern in ABSOLUTE_PATH_PATTERNS):
            failures.append(f"local absolute path: {relative}")
        if (
            relative.parts[:2] == (".github", "workflows")
            and path.suffix.lower() in {".yml", ".yaml"}
        ):
            try:
                references = _workflow_action_references(content)
            except yaml.YAMLError:
                failures.append(f"invalid workflow YAML: {relative.as_posix()}")
                continue
            for reference in references:
                if not _workflow_action_is_pinned(reference):
                    failures.append(f"unpinned workflow action: {relative.as_posix()}")
                    break
        non_synthetic = [
            value
            for value in WARRANTY_SERIAL_PATTERN.findall(content)
            if not any(marker in value.upper() for marker in SYNTHETIC_MARKERS)
        ]
        if non_synthetic:
            failures.append(f"non-synthetic warranty identifier: {relative}")
    return failures


def main() -> int:
    print("Created by Joel Manuel for the VA 2026")
    print("Thanks to Steve, Anthony, Chris, and Ernes")
    failures = audit()
    if failures:
        print("Release audit failed:")
        print("\n".join(f"- {failure}" for failure in failures))
        return 1
    print("Release audit passed: no prohibited files, secret-like values, or local paths found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
