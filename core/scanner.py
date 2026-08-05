import re
from core.models import VendorType

class BarcodeScannerParser:
    _EE_NUMBER_RE = re.compile(r"^\s*558[\s-]*EE[\s-]*([0-9]{1,20})\s*$", re.IGNORECASE)

    @classmethod
    def parse_ee_number(cls, raw_input: str) -> str | None:
        """Return the numeric suffix from an anchored internal ``558 EE`` scan."""
        if not raw_input:
            return None
        match = cls._EE_NUMBER_RE.fullmatch(raw_input)
        return match.group(1) if match else None

    @staticmethod
    def clean_barcode(raw_input: str) -> str:
        """Sanitizes raw barcode input from USB scanner, stripping non-printable characters."""
        if not raw_input:
            return ""
        # Remove non-alphanumeric except hyphens
        cleaned = re.sub(r'[^A-Za-z0-9\-]', '', raw_input).strip().upper()
        return cleaned

    @classmethod
    def detect_vendor(cls, serial: str) -> VendorType:
        """Detects hardware vendor from serial number structure and prefixes."""
        cleaned = cls.clean_barcode(serial)

        if not cleaned:
            return VendorType.GENERIC

        # Dell: Exactly 7 alphanumeric characters (e.g. 7X8K2M1, B123456)
        if len(cleaned) == 7 and cleaned.isalnum():
            return VendorType.DELL

        # HP: 10 to 12 alphanumeric characters, often starting with specific prefixes
        hp_prefixes = ('5CD', 'CNU', '5CG', '2UA', 'MXL', 'CND', 'CZC', 'SGH', 'SHG')
        if len(cleaned) in (10, 11, 12) and any(cleaned.startswith(p) for p in hp_prefixes):
            return VendorType.HP

        # Lenovo: 8 characters, often starting with PF, R9, MP, 1S, 8S
        lenovo_prefixes = ('PF', 'R9', 'MP', '1S', '8S', 'YK', 'LR')
        if len(cleaned) == 8 and (cleaned.isalnum() or any(cleaned.startswith(p) for p in lenovo_prefixes)):
            return VendorType.LENOVO

        # Apple: 10-12 characters starting with C02, F4H, D25, G8V, FVF, W8
        apple_prefixes = ('C02', 'F4H', 'D25', 'G8V', 'FVF', 'W8', 'C07')
        if len(cleaned) in (10, 11, 12) and any(cleaned.startswith(p) for p in apple_prefixes):
            return VendorType.APPLE

        # Generic heuristics
        if len(cleaned) <= 7:
            return VendorType.DELL
        elif len(cleaned) == 8:
            return VendorType.LENOVO
        else:
            return VendorType.HP
