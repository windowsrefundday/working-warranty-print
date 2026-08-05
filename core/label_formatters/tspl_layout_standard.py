"""Standard warranty layout for larger label stock."""

from core.label_formatters.tspl_commands import barcode, finish, header, pos, sanitize, text
from core.models import AssetRecord
from core.printers.profiles.models import LabelProfile


def render(asset: AssetRecord, profile: LabelProfile):
    lines = header(profile)
    vendor = sanitize(asset.vendor.value, 20)
    status = sanitize(asset.warranty_status, 30)
    model = sanitize(asset.model_name, 50)
    serial = sanitize(asset.serial_number, 64)
    expires = sanitize(asset.expiration_date, 30)
    source = sanitize(asset.source_confidence.value, 50)
    scan = sanitize(asset.timestamp, 30)
    lines.extend([
        text(20, pos(profile, 20), f"{vendor} - {status}"),
        text(20, pos(profile, 55), f"MODEL: {model}"),
        text(20, pos(profile, 90), f"SN: {serial}"),
        text(20, pos(profile, 125), f"EXP: {expires}"),
        text(20, pos(profile, 160), f"SRC: {source}"),
    ])
    for index, entitlement in enumerate(asset.entitlements[:2]):
        lines.append(text(20, pos(profile, 195 + index * 35), f"* {sanitize(entitlement.service_name, 60)}"))
    lines.extend([text(20, pos(profile, 270), f"SCAN: {scan}"), barcode(20, pos(profile, 310), serial), "PRINT 1,1"])
    return finish(profile, lines)
