"""Large-number layout for internal ``558 EE`` scans."""

from core.label_formatters.tspl_commands import finish, header, pos, text
from core.models import EERecord
from core.printers.profiles.models import LabelProfile


def render(record: EERecord, profile: LabelProfile):
    """Center only the EE suffix in the largest safe built-in font."""
    assert profile.width_mm is not None and profile.height_mm is not None
    width_dots = profile.dots(profile.width_mm)
    height_dots = profile.dots(profile.height_mm)
    margin = pos(profile, 14)
    printable_width = width_dots - (margin * 2)
    printable_height = height_dots - (margin * 2)
    if printable_width <= 0 or printable_height <= 0:
        raise RuntimeError("The configured label is too small for an EE number.")

    # TSC built-in font 3 is 16 x 24 dots before multiplication.
    scale = min(
        8,
        printable_width // (16 * len(record.ee_number)),
        printable_height // 24,
    )
    if scale < 1:
        raise RuntimeError("The EE number does not fit within the configured label.")

    text_width = len(record.ee_number) * 16 * scale
    text_height = 24 * scale
    x = max(margin, (width_dots - text_width) // 2)
    y = max(margin, (height_dots - text_height) // 2)
    lines = header(profile)
    lines.extend([
        text(x, y, record.ee_number, font="3", scale=scale),
        "PRINT 1,1",
    ])
    return finish(profile, lines)
