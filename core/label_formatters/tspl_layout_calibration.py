"""Calibration/test-label renderers, intentionally separate from sensor calibration."""

from core.label_formatters.tspl_commands import barcode, finish, header, pos, sanitize, text
from core.printers.profiles.models import LabelProfile


def render(profile: LabelProfile, test_serial: str = "TEST123"):
    assert profile.width_mm is not None and profile.height_mm is not None and profile.gap_mm is not None
    width_dots, height_dots = profile.dots(profile.width_mm), profile.dots(profile.height_mm)
    lines = header(profile)
    if height_dots <= 400 and width_dots > 400:
        margin = pos(profile, 14)
        lines.extend([
            text(margin, pos(profile, 24), f"PROFILE: {profile.model} @ {profile.dpi} dpi"),
            text(margin, pos(profile, 56), f"SIZE: {profile.width_mm}mm x {profile.height_mm}mm GAP: {profile.gap_mm}mm", font="2"),
            text(margin, pos(profile, 86), f"DARK: {profile.darkness} SPEED: {profile.speed} OFF: {profile.offset_x_mm}mm SHIFT: {profile.shift_y_mm}mm", font="2"),
            text(margin, pos(profile, 114), f"TEST S/N: {sanitize(test_serial, 32)} - CALIBRATION OK", font="2"),
            "PRINT 1,1",
        ])
        return finish(profile, lines)
    lines.extend([
        text(20, pos(profile, 20), f"PROFILE: {profile.model} @ {profile.dpi} dpi"),
        text(20, pos(profile, 55), f"SIZE: {profile.width_mm}mm x {profile.height_mm}mm"),
        text(20, pos(profile, 90), f"GAP: {profile.gap_mm}mm  DARK: {profile.darkness}  SPEED: {profile.speed}"),
        text(20, pos(profile, 125), "TOP-LEFT BOUND"),
        text(20, pos(profile, 195), "BOTTOM BOUND"),
        barcode(20, pos(profile, 230), test_serial),
        "PRINT 1,1",
    ])
    return finish(profile, lines)
