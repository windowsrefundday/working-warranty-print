"""Validated, atomic persistence for local printer profile selections."""

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from core.printers.profiles.models import LabelProfile
from core.printers.profiles.catalog import MB341_3X1_WARRANTY_PROFILE_ID


PROFILE_SCHEMA_VERSION = 1


def _profile_from_mapping(data: dict) -> LabelProfile:
    profile_data = data.get("profile", data)
    profile = LabelProfile(
        queue_name=str(profile_data.get("queue_name", "TSC_MB341")),
        model=str(profile_data.get("model", "MB341")),
        dpi=int(profile_data.get("dpi", 300)),
        width_mm=(
            float(profile_data["width_mm"])
            if profile_data.get("width_mm") is not None
            else None
        ),
        height_mm=(
            float(profile_data["height_mm"])
            if profile_data.get("height_mm") is not None
            else None
        ),
        gap_mm=(
            float(profile_data["gap_mm"])
            if profile_data.get("gap_mm") is not None
            else None
        ),
        darkness=int(profile_data.get("darkness", 7)),
        speed=int(profile_data.get("speed", 50)),
        copies=int(profile_data.get("copies", 1)),
        offset_x_mm=float(profile_data.get("offset_x_mm", 0.0)),
        shift_y_mm=float(profile_data.get("shift_y_mm", 0.0)),
    )
    profile.validate()
    return profile


def load_profile(path: str, fallback: LabelProfile) -> LabelProfile:
    """Load a v1 envelope or legacy flat JSON; invalid files fail closed."""
    target = Path(path)
    if not target.exists():
        return fallback
    try:
        with target.open(encoding="utf-8") as handle:
            return _profile_from_mapping(json.load(handle))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return fallback


def save_profile(profile: LabelProfile, path: str) -> str:
    """Atomically write a versioned local profile envelope."""
    profile.validate()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        # Local slider edits are derived selections, never edits to the
        # immutable catalog JSON. The timestamped ID also makes a support dump
        # auditable without changing the media preset itself.
        "profile_id": f"local-derived-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "based_on": MB341_3X1_WARRANTY_PROFILE_ID,
        "saved_at": datetime.now(UTC).isoformat(),
        "calibration_status": "candidate",
        "profile": {
            "queue_name": profile.queue_name,
            "model": profile.model,
            "dpi": profile.dpi,
            "width_mm": profile.width_mm,
            "height_mm": profile.height_mm,
            "gap_mm": profile.gap_mm,
            "darkness": profile.darkness,
            "speed": profile.speed,
            "copies": profile.copies,
            "offset_x_mm": profile.offset_x_mm,
            "shift_y_mm": profile.shift_y_mm,
        },
    }
    file_descriptor, temp_path = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(temp_path, target)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise
    return str(target)
