"""Verify a signed release manifest and its local platform artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.updater import Manifest, UpdateError


def verify_release(
    manifest_path: Path,
    assets: Mapping[str, Path],
    *,
    trusted_keys: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> Manifest:
    """Verify signature, lifetime, target set, sizes, and SHA-256 digests."""
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("Release manifest is unreadable or invalid JSON") from exc
    if not isinstance(document, dict):
        raise UpdateError("Release manifest must be a JSON object")

    manifest = Manifest.from_mapping(document)
    manifest.verify_signature(trusted_keys)
    manifest.validate_time(now)
    if set(assets) != set(manifest.targets):
        raise UpdateError("Local release assets do not match the signed target set")

    for target_name, path in assets.items():
        target = manifest.target_for(target_name)
        try:
            size = path.stat().st_size
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise UpdateError(f"Release asset is unreadable: {target_name}") from exc
        if size != target.size or digest != target.sha256:
            raise UpdateError(f"Release asset does not match manifest: {target_name}")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    """Verify a signed manifest against `TARGET=PATH` asset arguments."""
    parser = argparse.ArgumentParser(description="Verify signed release metadata")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--asset",
        action="append",
        required=True,
        metavar="TARGET=PATH",
    )
    args = parser.parse_args(argv)
    assets: dict[str, Path] = {}
    for specification in args.asset:
        target, separator, filename = specification.partition("=")
        if not separator or not target or not filename:
            parser.error(f"Invalid --asset: {specification}")
        if target in assets:
            parser.error(f"Duplicate asset target: {target}")
        assets[target] = Path(filename)
    try:
        verify_release(args.manifest, assets)
    except (OSError, UpdateError, ValueError) as exc:
        parser.error(str(exc))
    print("Signed release manifest and artifacts verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
