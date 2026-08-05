"""Shared non-command helpers for warranty TSPL layouts."""

from datetime import datetime

from core.label_formatters.tspl_commands import sanitize


def compact_date(value: str) -> str:
    value = sanitize(value, 32)
    for pattern in ("%B %d, %Y", "%B %d %Y", "%Y-%m-%d", "%b %d, %Y", "%b %d %Y"):
        try:
            return datetime.strptime(value, pattern).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


def wrap(value: str, width: int, max_lines: int) -> list[str]:
    words = sanitize(value, width * max_lines).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            if len(lines) == max_lines:
                return lines
        current = word[:width]
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]
