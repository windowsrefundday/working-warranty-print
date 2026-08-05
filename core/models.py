from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum
from datetime import datetime

class VendorType(str, Enum):
    DELL = "Dell"
    HP = "HP"
    LENOVO = "Lenovo"
    APPLE = "Apple"
    GENERIC = "Generic"

class SourceConfidence(str, Enum):
    VERIFIED_LIVE = "VERIFIED LIVE (Vendor Portal)"
    CACHED_REGISTRY = "VERIFIED REGISTRY (Internal Database)"
    UNVERIFIED_FAILED = "UNVERIFIED (Lookup Failed)"

@dataclass
class Entitlement:
    service_name: str
    status: str  # "Active", "Expired", etc.
    start_date: Optional[str] = None
    end_date: Optional[str] = None

@dataclass
class AssetRecord:
    serial_number: str
    vendor: VendorType
    model_name: str
    warranty_status: str  # "Active", "Expired", "Coverage Expiring", etc.
    ship_date: str
    expiration_date: str
    entitlements: List[Entitlement] = field(default_factory=list)
    source_confidence: SourceConfidence = SourceConfidence.UNVERIFIED_FAILED
    raw_source: str = "System Registry"
    source_verified_at: Optional[str] = None
    lookup_error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

@dataclass(frozen=True)
class EERecord:
    """An internal EE label request, separate from warranty evidence."""

    ee_number: str
    raw_code: str
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def __post_init__(self) -> None:
        if not (
            isinstance(self.ee_number, str)
            and 1 <= len(self.ee_number) <= 20
            and self.ee_number.isascii()
            and self.ee_number.isdigit()
        ):
            raise ValueError("EERecord.ee_number must contain 1-20 ASCII digits")

@dataclass
class PrintJobResult:
    success: bool
    printer_name: str
    job_id: Optional[str] = None
    error_message: Optional[str] = None
    output_path: Optional[str] = None
