from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Optional

from core.models import AssetRecord, SourceConfidence, VendorType

ProgressCallback = Callable[[str, int], None]

class BaseVendorPlugin(ABC):
    """
    Abstract Base Class for all Vendor Warranty Lookup Plugins.
    To add a new hardware manufacturer, subclass BaseVendorPlugin and register it in engine.py.
    """

    @property
    @abstractmethod
    def vendor_type(self) -> VendorType:
        """Returns the VendorType enum associated with this plugin."""
        pass

    @abstractmethod
    def fetch_warranty(
        self,
        serial_number: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> AssetRecord:
        """
        Fetches warranty details for the given serial number.
        Returns a populated AssetRecord object.
        """
        pass

    def start(self) -> None:
        """Start optional plugin-owned resources. Default is intentionally inert."""

    def prewarm(self) -> None:
        """Prewarm optional plugin-owned resources. Default is intentionally inert."""

    def stop(self) -> None:
        """Release optional plugin-owned resources. Default is intentionally inert."""

    def lookup_failed(
        self,
        serial_number: str,
        error: str,
        model_name: str = "Unknown",
    ) -> AssetRecord:
        """Create an explicitly unverified record that cannot be printed."""
        return AssetRecord(
            serial_number=serial_number.strip().upper(),
            vendor=self.vendor_type,
            model_name=model_name,
            warranty_status="Lookup Failed",
            ship_date="Unknown",
            expiration_date="Unknown",
            entitlements=[],
            source_confidence=SourceConfidence.UNVERIFIED_FAILED,
            raw_source=f"{self.vendor_type.value} Warranty Lookup Failed",
            lookup_error=error,
        )
