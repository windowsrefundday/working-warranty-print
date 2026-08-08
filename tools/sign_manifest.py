"""Create signed update metadata for a tagged GitHub release."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from cryptography.hazmat.primitives import serialization

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.updater import _canonical_json, _safe_url, _version


def _private_key(value: str) -> "Ed25519PrivateKey":
    """Decode a raw base64url Ed25519 private key."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        return Ed25519PrivateKey.from_private_bytes(raw)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("UPDATE_SIGNING_KEY_B64 is not a raw Ed25519 private key") from exc


def create_manifest(
    version: str,
    channel: str,
    key_id: str,
    private_key_b64: str,
    assets: dict[str, Path],
    base_url: str,
    *,
    now: datetime | None = None,
    lifetime_days: int = 14,
) -> dict[str, object]:
    """Create a signed update manifest from release assets."""
    _version(version)
    _safe_url(base_url)
    if not 1 <= lifetime_days <= 365:
        raise RuntimeError("Manifest lifetime must be between 1 and 365 days")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    targets: dict[str, object] = {}
    for target, path in assets.items():
        asset_name = path.name
        if urllib.parse.quote(asset_name, safe="._-") != asset_name:
            raise RuntimeError("Asset filenames must contain only URL-safe characters")
        payload = path.read_bytes()
        asset_url = _safe_url(f"{base_url.rstrip('/')}/{asset_name}")
        targets[target] = {
            "url": asset_url,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
    document: dict[str, object] = {
        "schema_version": 1,
        "channel": channel,
        "version": version,
        "min_launcher_version": "1.0.0",
        "published_at": current.isoformat(),
        "expires_at": (current + timedelta(days=lifetime_days)).isoformat(),
        "rollout_percentage": 100,
        "targets": targets,
    }
    signing_key = _private_key(private_key_b64)
    signature = signing_key.sign(_canonical_json(document))
    document["signature"] = {
        "key_id": key_id,
        "value": base64.urlsafe_b64encode(signature).decode().rstrip("="),
    }
    return document


def verify_private_key_matches_pinned_key(key_id: str, private_key_b64: str) -> None:
    """Refuse to publish metadata if CI has the wrong signing secret."""
    from tools.updater import TRUSTED_UPDATE_KEYS

    signing_key = _private_key(private_key_b64)
    public = signing_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    encoded = base64.urlsafe_b64encode(public).decode().rstrip("=")
    if TRUSTED_UPDATE_KEYS.get(key_id) != encoded:
        raise RuntimeError("Release key does not match the public key pinned in the launcher")


def main(argv: Sequence[str] | None = None) -> int:
    """Sign a release manifest from command-line arguments."""
    parser = argparse.ArgumentParser(description="Sign application update metadata")
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=("stable", "beta"), default="stable")
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lifetime-days", type=int, default=14)
    parser.add_argument(
        "--asset",
        action="append",
        required=True,
        metavar="TARGET=PATH",
        help="Target key and local artifact path, for example windows-x86_64=dist/app.zip",
    )
    args = parser.parse_args(argv)
    secret = os.environ.get("UPDATE_SIGNING_KEY_B64")
    if not secret:
        parser.error("UPDATE_SIGNING_KEY_B64 is required")
    assets: dict[str, Path] = {}
    for specification in args.asset:
        target, separator, filename = specification.partition("=")
        if not separator or not target or not filename:
            parser.error(f"Invalid --asset: {specification}")
        path = Path(filename)
        if target in assets:
            parser.error(f"Duplicate asset target: {target}")
        if not path.is_file():
            parser.error(f"Asset file does not exist: {filename}")
        assets[target] = path
    try:
        verify_private_key_matches_pinned_key(args.key_id, secret)
        manifest = create_manifest(
            args.version,
            args.channel,
            args.key_id,
            secret,
            assets,
            args.base_url,
            lifetime_days=args.lifetime_days,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
