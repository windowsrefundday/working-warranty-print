"""Layout selection and bounded rendering for TSPL labels."""

from core.label_formatters import tspl_layout_calibration, tspl_layout_ee, tspl_layout_narrow, tspl_layout_standard, tspl_layout_warranty_3x1
from core.label_formatters.tspl_commands import RenderedPayload
from core.models import AssetRecord, EERecord
from core.printers.profiles.models import LabelProfile


def render_warranty(asset: AssetRecord, profile: LabelProfile) -> RenderedPayload:
    if not profile.is_configured():
        raise RuntimeError("Label profile dimensions are not configured; run calibration and set measured width_mm, height_mm, and gap_mm.")
    profile.validate()
    assert profile.width_mm is not None and profile.height_mm is not None
    if profile.dots(profile.height_mm) <= 400 and profile.dots(profile.width_mm) > 400:
        return tspl_layout_warranty_3x1.render(asset, profile)
    if profile.dots(profile.width_mm) <= 400:
        return tspl_layout_narrow.render(asset, profile)
    return tspl_layout_standard.render(asset, profile)


def render_calibration(profile: LabelProfile, test_serial: str = "TEST123") -> RenderedPayload:
    if not profile.is_configured():
        raise RuntimeError("Label profile dimensions are not configured; run calibration and set measured width_mm, height_mm, and gap_mm.")
    profile.validate()
    return tspl_layout_calibration.render(profile, test_serial)


def render_ee(record: EERecord, profile: LabelProfile) -> RenderedPayload:
    if not profile.is_configured():
        raise RuntimeError("Label profile dimensions are not configured; run calibration and set measured width_mm, height_mm, and gap_mm.")
    profile.validate()
    return tspl_layout_ee.render(record, profile)
