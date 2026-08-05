"""Safe low-level TSPL-EZD command construction."""

import re
from dataclasses import dataclass

from core.printers.profiles.models import LabelProfile

_SAFE_CHARS_RE = re.compile(r"[^\x20-\x7E]")
_TSPL_SPECIAL_RE = re.compile(r"[\"',;\\\\]")
_POSITION_RE = re.compile(r"^(?:TEXT|BARCODE)\s+(\d+),(\d+),")


def sanitize(value: str, max_length: int = 80) -> str:
    value = value.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    value = _TSPL_SPECIAL_RE.sub("", value)
    return _SAFE_CHARS_RE.sub("", value).strip()[:max_length]


def pos(profile: LabelProfile, dots_at_300: int) -> int:
    return int(round(dots_at_300 * profile.dpi / 300))


def text(x: int, y: int, value: str, font: str = "3", scale: int = 1) -> str:
    return f'TEXT {x},{y},"{font}",0,{scale},{scale},"{sanitize(value)}"'


def barcode(x: int, y: int, serial: str) -> str:
    return f'BARCODE {x},{y},"128",80,1,0,2,4,"{sanitize(serial, 64)}"'


def header(profile: LabelProfile) -> list[str]:
    profile.validate()
    assert profile.width_mm is not None and profile.height_mm is not None and profile.gap_mm is not None
    return [
        f"SIZE {profile.width_mm} mm,{profile.height_mm} mm",
        f"GAP {profile.gap_mm} mm,0 mm",
        "DIRECTION 1",
        f"REFERENCE {profile.dots(profile.offset_x_mm)},0",
        f"SHIFT 0,{profile.dots(profile.shift_y_mm)}",
        f"DENSITY {profile.darkness}",
        f"SPEED {profile.speed}",
        "CLS",
    ]


@dataclass(frozen=True)
class RenderedPayload:
    payload: bytes
    max_x: int
    max_y: int
    print_count: int


def finish(profile: LabelProfile, lines: list[str]) -> RenderedPayload:
    """Encode and reject malformed/overflowing render output before printing."""
    if lines.count("PRINT 1,1") != 1 or sum(line.startswith("PRINT ") for line in lines) != 1:
        raise RuntimeError("A label layout must emit exactly one PRINT 1,1 command.")
    max_x = max_y = 0
    for line in lines:
        match = _POSITION_RE.match(line)
        if match:
            max_x = max(max_x, int(match.group(1)))
            max_y = max(max_y, int(match.group(2)))
    assert profile.width_mm is not None and profile.height_mm is not None
    if max_x >= profile.dots(profile.width_mm) or max_y >= profile.dots(profile.height_mm):
        raise RuntimeError("Rendered TSPL coordinates exceed configured label bounds.")
    return RenderedPayload(
        payload=("\r\n".join(lines) + "\r\n").encode("ascii", errors="ignore"),
        max_x=max_x,
        max_y=max_y,
        print_count=1,
    )
