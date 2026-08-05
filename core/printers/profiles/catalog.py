"""Immutable built-in printer/media presets."""

import json
from importlib import resources
from typing import Any

from core.printers.profiles.models import LabelProfile


MB341_3X1_WARRANTY_PROFILE_ID = "tsc-mb341-300dpi-3x1-warranty-v1"


def _load_document(profile_id: str) -> dict[str, Any]:
    if profile_id != MB341_3X1_WARRANTY_PROFILE_ID:
        raise KeyError(f"Unknown built-in printer profile: {profile_id}")
    resource = resources.files(__package__).joinpath(
        "builtin/tsc-mb341-300dpi-3x1-warranty-v1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def load_builtin_profile(profile_id: str = MB341_3X1_WARRANTY_PROFILE_ID) -> LabelProfile:
    """Return a fresh immutable profile from the shipped, versioned catalog."""
    data = _load_document(profile_id)["profile"]
    profile = LabelProfile(**data)
    profile.validate()
    return profile


def builtin_profile_metadata(
    profile_id: str = MB341_3X1_WARRANTY_PROFILE_ID,
) -> dict[str, Any]:
    """Return catalog metadata without making it part of a print payload."""
    return _load_document(profile_id)
