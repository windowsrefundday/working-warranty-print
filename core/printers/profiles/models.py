"""Printer/media profile values used by renderers and connectors."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LabelProfile:
    """Immutable physical media and device settings for a label job.

    Dimensions are millimetres. A profile is intentionally unusable for a
    physical job until width, height, and gap are explicitly configured.
    """

    queue_name: str
    model: str
    dpi: int
    width_mm: Optional[float]
    height_mm: Optional[float]
    gap_mm: Optional[float]
    darkness: int
    speed: int
    copies: int
    offset_x_mm: float = 0.0
    shift_y_mm: float = 0.0

    def is_configured(self) -> bool:
        return (
            self.width_mm is not None
            and self.height_mm is not None
            and self.gap_mm is not None
            and self.width_mm > 0
            and self.height_mm > 0
            and self.gap_mm >= 0
        )

    def dots(self, mm: float) -> int:
        return int(round(mm * self.dpi / 25.4))

    def with_dimensions(
        self, width_mm: float, height_mm: float, gap_mm: float
    ) -> "LabelProfile":
        return LabelProfile(
            queue_name=self.queue_name,
            model=self.model,
            dpi=self.dpi,
            width_mm=width_mm,
            height_mm=height_mm,
            gap_mm=gap_mm,
            darkness=self.darkness,
            speed=self.speed,
            copies=self.copies,
            offset_x_mm=self.offset_x_mm,
            shift_y_mm=self.shift_y_mm,
        )

    def validate(self) -> None:
        if not self.is_configured():
            raise ValueError("width_mm, height_mm, and gap_mm must be configured")
        if not 0 <= self.darkness <= 15:
            raise ValueError("darkness must be between 0 and 15")
        if not 20 <= self.speed <= 90:
            raise ValueError("speed must be between 20 and 90 mm/s")
        if self.copies != 1:
            raise ValueError("physical warranty labels require exactly one copy")
        if self.offset_x_mm < 0:
            raise ValueError("offset_x_mm cannot be negative")
        if not -25.4 <= self.shift_y_mm <= 25.4:
            raise ValueError("shift_y_mm must be between -25.4 and 25.4")
