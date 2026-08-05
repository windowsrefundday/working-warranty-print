"""Interface-facing profile operations shared by CLI and web routes."""

from dataclasses import replace
from typing import Callable, Mapping, Optional

from core.printers.profiles.catalog import load_builtin_profile
from core.printers.profiles.models import LabelProfile
from core.printers.profiles.service import ProfileService
from core.printers.tsc_connector import TSCPrinterConnector


class PrinterProfileService:
    """Keep request parsing and connector updates out of HTTP/terminal code."""

    def __init__(self, persistence: Optional[ProfileService] = None):
        self.persistence = persistence or ProfileService()

    def base_profile(self, connector: object) -> LabelProfile:
        if isinstance(connector, TSCPrinterConnector) and connector.profile.is_configured():
            return connector.profile
        return load_builtin_profile()

    def adjusted_profile(self, values: Mapping[str, object], connector: object) -> LabelProfile:
        return self.persistence.apply_adjustments(values, self.base_profile(connector))

    def save(
        self,
        values: Mapping[str, object],
        connector: object,
        saver: Callable[[LabelProfile], str],
    ) -> tuple[LabelProfile, str]:
        profile = self.adjusted_profile(values, connector)
        return profile, saver(profile)

    def calibration_profile(self, values: Mapping[str, object], connector: object) -> LabelProfile:
        # Omitted fields deliberately inherit from the active/built-in profile.
        return self.adjusted_profile(values, connector)

    @staticmethod
    def response_values(profile: LabelProfile) -> dict[str, object]:
        return ProfileService.public_values(profile)
