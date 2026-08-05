"""Explicit TSC sensor-calibration payload generation."""

from core.printers.profiles.models import LabelProfile


def gap_sensor_payload(profile: LabelProfile) -> bytes:
    """Generate only the measured gap-detect command; never a print job."""
    profile.validate()
    assert profile.width_mm is not None
    assert profile.height_mm is not None
    assert profile.gap_mm is not None
    return (
        f"SIZE {profile.width_mm} mm,{profile.height_mm} mm\r\n"
        f"GAP {profile.gap_mm} mm,0 mm\r\n"
        f"GAPDETECT {profile.dots(profile.height_mm)},{profile.dots(profile.gap_mm)}\r\n"
    ).encode("ascii")
