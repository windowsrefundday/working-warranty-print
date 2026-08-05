"""One profile-resolution and adjustment service for every interface."""

from dataclasses import replace
from typing import Any, Mapping, Optional, cast

from core.app_paths import get_app_paths
from core.printers.profiles.catalog import load_builtin_profile
from core.printers.profiles.models import LabelProfile
from core.printers.profiles.repository import load_profile, save_profile


DEFAULT_PROFILE_PATH = str(get_app_paths().profile_path)


class ProfileService:
    """Resolve, validate, preview, and persist local TSC media profiles.

    The catalog preset is never modified. Saving a slider adjustment creates a
    local, versioned selection at ``profile_path`` instead.
    """

    def __init__(self, profile_path: Optional[str] = None, fallback: Optional[LabelProfile] = None):
        self.profile_path = profile_path or DEFAULT_PROFILE_PATH
        self.fallback = fallback or load_builtin_profile()

    def resolve(self, environment_profile: Optional[LabelProfile] = None) -> LabelProfile:
        """Return explicit one-session settings first, then local, then catalog."""
        if environment_profile is not None and environment_profile.is_configured():
            environment_profile.validate()
            return environment_profile
        return load_profile(self.profile_path, self.fallback)

    def apply_adjustments(
        self, values: Mapping[str, object], base_profile: Optional[LabelProfile] = None
    ) -> LabelProfile:
        """Build a fully validated profile from a complete or partial request."""
        base = base_profile or self.resolve()
        raw = cast(Mapping[str, Any], values)
        try:
            width = float(raw.get("width_mm", base.width_mm))
            height = float(raw.get("height_mm", base.height_mm))
            gap = float(raw.get("gap_mm", base.gap_mm))
            darkness = int(raw.get("darkness", base.darkness))
            speed = int(raw.get("speed", base.speed))
            offset_x = float(raw.get("offset_x_mm", base.offset_x_mm))
            shift_y = float(raw.get("shift_y_mm", base.shift_y_mm))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid numeric parameters: {exc}") from exc
        profile = replace(
            base.with_dimensions(width, height, gap),
            darkness=darkness,
            speed=speed,
            offset_x_mm=offset_x,
            shift_y_mm=shift_y,
        )
        profile.validate()
        return profile

    def save_adjustments(
        self, values: Mapping[str, object], base_profile: Optional[LabelProfile] = None
    ) -> tuple[LabelProfile, str]:
        profile = self.apply_adjustments(values, base_profile)
        return profile, save_profile(profile, self.profile_path)

    @staticmethod
    def public_values(profile: LabelProfile) -> dict[str, object]:
        return {
            "width_mm": profile.width_mm,
            "height_mm": profile.height_mm,
            "gap_mm": profile.gap_mm,
            "darkness": profile.darkness,
            "speed": profile.speed,
            "offset_x_mm": profile.offset_x_mm,
            "shift_y_mm": profile.shift_y_mm,
            "copies": profile.copies,
        }
from core.app_paths import get_app_paths
