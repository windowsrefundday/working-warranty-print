"""Expiration-emphasis warranty layout for the MB341 3x1 stock."""

from core.label_formatters.tspl_commands import finish, header, pos, sanitize, text
from core.label_formatters.tspl_layouts_common import compact_date
from core.models import AssetRecord
from core.printers.profiles.models import LabelProfile


def render(asset: AssetRecord, profile: LabelProfile):
    assert profile.width_mm is not None and profile.height_mm is not None
    width_dots, height_dots = profile.dots(profile.width_mm), profile.dots(profile.height_mm)
    margin = pos(profile, 14)
    positive_shift = max(0, profile.dots(profile.shift_y_mm))
    expiration_y = height_dots - positive_shift - pos(profile, 14) - pos(profile, 48)
    if expiration_y < pos(profile, 144):
        raise RuntimeError("The configured vertical shift leaves too little printable height for the enlarged 3x1 warranty layout.")
    model_chars = max(1, max(20, (width_dots - margin * 2) // 16) - len("MODEL: "))
    confidence = "LIVE" if asset.source_confidence.value.startswith("VERIFIED LIVE") else "CACHE"
    vendor = sanitize(asset.vendor.value, 12).upper()
    status = sanitize(asset.warranty_status, 24).upper()
    # The large header is intentionally split for expired assets. "EXPIRED"
    # appended to the vendor header can reach the right edge at 2x scale.
    expired_status = "EXPIRED" in status
    serial_y = 120 if expired_status else 68
    model_y = 144 if expired_status else 92
    source_y = 168 if expired_status else 116
    minimum_expiration_y = source_y + pos(profile, 24) + pos(profile, 14)
    if expiration_y < minimum_expiration_y:
        raise RuntimeError("The configured vertical shift leaves too little printable height for the enlarged 3x1 warranty layout.")
    lines = header(profile)
    lines.append(
        text(
            margin,
            pos(profile, 16),
            f"{vendor} WARRANTY" if expired_status else f"{vendor} WARRANTY: {status}",
            scale=2,
        )
    )
    if expired_status:
        lines.append(text(margin, pos(profile, 68), status, scale=2))
    lines.extend([
        text(margin, pos(profile, serial_y), f"SN: {sanitize(asset.serial_number, 32)} | START: {compact_date(asset.ship_date)}"),
        text(margin, pos(profile, model_y), f"MODEL: {sanitize(asset.model_name, model_chars)}"),
        text(margin, pos(profile, source_y), f"SOURCE: {confidence}"),
        text(margin, expiration_y, f"EXPIRES: {compact_date(asset.expiration_date)}", scale=2),
        "PRINT 1,1",
    ])
    return finish(profile, lines)
