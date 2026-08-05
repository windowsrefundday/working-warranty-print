"""Wrapped warranty layout for narrow rolls."""

from core.label_formatters.tspl_commands import finish, header, pos, sanitize, text
from core.label_formatters.tspl_layouts_common import compact_date, wrap
from core.models import AssetRecord
from core.printers.profiles.models import LabelProfile


def render(asset: AssetRecord, profile: LabelProfile):
    assert profile.width_mm is not None and profile.height_mm is not None
    width_dots, height_dots = profile.dots(profile.width_mm), profile.dots(profile.height_mm)
    margin, line_height, y = pos(profile, 14), pos(profile, 24), pos(profile, 12)
    max_chars = max(12, min(22, (width_dots - margin * 2) // 12))
    lines = header(profile)

    def add(value: str, max_lines: int = 1) -> None:
        nonlocal y
        for line in wrap(value, max_chars, max_lines):
            if y + line_height > height_dots - pos(profile, 16):
                return
            lines.append(text(margin, y, line, font="2"))
            y += line_height

    add(f"{sanitize(asset.vendor.value, 12).upper()} WARRANTY")
    add(f"STATUS: {sanitize(asset.warranty_status, 20).upper()}")
    add(f"SN: {sanitize(asset.serial_number, 32)}")
    add("MODEL:")
    add(asset.model_name, 3)
    add(f"START: {compact_date(asset.ship_date)}")
    add(f"EXPIRES: {compact_date(asset.expiration_date)}")
    for entitlement in asset.entitlements[:3]:
        add(f"- {entitlement.service_name}", 2)
    add("SOURCE: LIVE" if asset.source_confidence.value.startswith("VERIFIED LIVE") else "SOURCE: CACHE")
    lines.append("PRINT 1,1")
    return finish(profile, lines)
