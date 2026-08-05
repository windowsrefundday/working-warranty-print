from typing import Optional
from core.cache import WarrantyCache
from core.models import AssetRecord, SourceConfidence, VendorType
from core.vendors.base import BaseVendorPlugin, ProgressCallback
from core.vendors.lenovo_worker import LenovoBrowserWorker


class LenovoVendorPlugin(BaseVendorPlugin):
    def __init__(
        self,
        worker: Optional[LenovoBrowserWorker] = None,
        cache: Optional[WarrantyCache] = None,
    ):
        self.worker = worker
        self.cache = cache
        self.last_lookup_error: Optional[str] = None

    @property
    def vendor_type(self) -> VendorType:
        return VendorType.LENOVO

    def fetch_warranty(
        self,
        serial_number: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> AssetRecord:
        clean_sn = serial_number.strip().upper()

        if self.worker is not None:
            if progress_callback is None:
                live = self.worker.fetch_warranty(clean_sn)
            else:
                live = self.worker.fetch_warranty(clean_sn, progress_callback)

            if live.source_confidence == SourceConfidence.VERIFIED_LIVE:
                if self.cache is not None:
                    self.cache.set(live)
                return live

            self.last_lookup_error = live.lookup_error
            return live

        return self.lookup_failed(
            clean_sn,
            "A verified Lenovo warranty provider is not configured.",
        )

    def stop(self) -> None:
        if self.worker is not None:
            self.worker.stop()


class AppleVendorPlugin(BaseVendorPlugin):
    @property
    def vendor_type(self) -> VendorType:
        return VendorType.APPLE

    def fetch_warranty(
        self, serial_number: str, progress_callback: Optional[ProgressCallback] = None
    ) -> AssetRecord:
        return self.lookup_failed(
            serial_number,
            "A verified Apple coverage provider is not configured.",
        )


class GenericVendorPlugin(BaseVendorPlugin):
    @property
    def vendor_type(self) -> VendorType:
        return VendorType.GENERIC

    def fetch_warranty(
        self, serial_number: str, progress_callback: Optional[ProgressCallback] = None
    ) -> AssetRecord:
        return self.lookup_failed(
            serial_number,
            "The manufacturer could not be identified from this barcode.",
        )
