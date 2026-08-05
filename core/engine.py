import os
import sys
import csv
import io
from datetime import date, datetime
from typing import Callable, Dict, List, Mapping, Optional
from core.cache import WarrantyCache
from core.models import AssetRecord, EERecord, VendorType, PrintJobResult, SourceConfidence
from core.scanner import BarcodeScannerParser
from core.vendors.base import BaseVendorPlugin
from core.vendors.dell import DellVendorPlugin
from core.vendors.hp import HPVendorPlugin
from core.vendors.lenovo import LenovoVendorPlugin, AppleVendorPlugin, GenericVendorPlugin
from core.vendors.hp_worker import HPBrowserWorker
from core.vendors.lenovo_worker import LenovoBrowserWorker
from core.application.composition import (
    build_default_printer_connectors,
    build_default_vendors,
)
from core.printers.base import BasePrinterConnector
from core.engine_downloader import GitHubEngineDownloader
from core.app_paths import get_app_paths

DEFAULT_CACHE_PATH = str(get_app_paths().cache_path)

class WarrantyEngine:
    """
    Central Coordinator for Warranty Lookups and Label Printing.
    Manages native plugins, external GitHub community engines, printer connectors,
    and persistent HP/Lenovo warranty cache and browser worker lifecycles.
    """

    def __init__(
        self,
        cache_path: Optional[str] = None,
        hp_worker: Optional[HPBrowserWorker] = None,
        lenovo_worker: Optional[LenovoBrowserWorker] = None,
        vendors: Optional[Mapping[VendorType, BaseVendorPlugin]] = None,
    ):
        # 0. External GitHub Engine Manager
        self.downloader: Optional[GitHubEngineDownloader] = None

        # Persistent verified-warranty cache (keyed by vendor + serial)
        self.cache = WarrantyCache(cache_path or DEFAULT_CACHE_PATH)

        # Legacy worker injection remains supported for existing integrations,
        # but the engine itself now talks only to the vendor registry.
        self.vendors: Dict[VendorType, BaseVendorPlugin] = dict(
            vendors or build_default_vendors(self.cache, hp_worker, lenovo_worker)
        )

        # 2. Register Printer Connectors
        self.connectors: Dict[str, BasePrinterConnector] = dict(
            build_default_printer_connectors()
        )

        # Default to "file" (Virtual File Printer / Screen Only)
        self.active_connector_key = "file"

        # Session Scan Audit History
        self.scan_history: List[AssetRecord] = []

    @staticmethod
    def parse_ee_scan(raw_barcode: str) -> Optional[EERecord]:
        """Recognize an internal EE scan without invoking a warranty vendor."""
        ee_number = BarcodeScannerParser.parse_ee_number(raw_barcode)
        if ee_number is None:
            return None
        return EERecord(ee_number=ee_number, raw_code=raw_barcode)

    def start(self) -> None:
        """Start/prewarm plugin-owned resources without OEM special cases."""
        for plugin in self._unique_plugins():
            plugin.start()
            plugin.prewarm()

    def stop(self) -> None:
        """Release all plugin-owned resources exactly once."""
        for plugin in self._unique_plugins():
            plugin.stop()

    def _unique_plugins(self) -> List[BaseVendorPlugin]:
        unique: List[BaseVendorPlugin] = []
        seen: set[int] = set()
        for plugin in self.vendors.values():
            if id(plugin) not in seen:
                unique.append(plugin)
                seen.add(id(plugin))
        return unique

    def update_github_engines(self) -> Dict[str, bool]:
        """Downloads or updates community warranty repositories from GitHub."""
        if self.downloader is None:
            self.downloader = GitHubEngineDownloader()
        return self.downloader.update_all_engines()

    def set_active_connector(self, connector_key: str):
        if connector_key in self.connectors:
            self.active_connector_key = connector_key
        else:
            raise ValueError(f"Unknown printer connector: {connector_key}. Valid options: {list(self.connectors.keys())}")

    def get_active_connector(self) -> BasePrinterConnector:
        return self.connectors[self.active_connector_key]

    def lookup_asset(
        self,
        raw_barcode: str,
        override_vendor: Optional[str] = None,
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ) -> AssetRecord:
        """Parses barcode, auto-detects vendor, and queries warranty records."""
        clean_serial = BarcodeScannerParser.clean_barcode(raw_barcode)

        if override_vendor and override_vendor.upper() in VendorType.__members__:
            vendor_enum = VendorType[override_vendor.upper()]
        else:
            vendor_enum = BarcodeScannerParser.detect_vendor(clean_serial)

        plugin = self.vendors.get(vendor_enum, self.vendors[VendorType.GENERIC])
        record = plugin.fetch_warranty(clean_serial, progress_callback)

        # Add to audit history
        self.scan_history.insert(0, record)
        return record

    def print_asset_label(self, asset: AssetRecord, printer_name: Optional[str] = None) -> PrintJobResult:
        """Dispatches asset tag print job to active printer connector."""
        connector = self.get_active_connector()
        if asset.source_confidence == SourceConfidence.UNVERIFIED_FAILED:
            return PrintJobResult(
                success=False,
                printer_name=connector.connector_name,
                error_message=(
                    "Label not created: warranty lookup was not verified by a "
                    "vendor source."
                ),
            )
        if asset.source_confidence == SourceConfidence.CACHED_REGISTRY:
            cache_age = self._cache_age_days(asset)
            if cache_age is None or cache_age > 30:
                return PrintJobResult(
                    success=False,
                    printer_name=connector.connector_name,
                    error_message=(
                        "Label not created: cached warranty evidence is missing "
                        "or older than 30 days. A fresh vendor lookup is required."
                    ),
                )
        return connector.print_label(asset, printer_name=printer_name)

    def print_ee_label(
        self,
        record: EERecord,
        printer_name: Optional[str] = None,
    ) -> PrintJobResult:
        """Dispatch a recognized internal EE number through the active connector."""
        return self.get_active_connector().print_ee_label(
            record, printer_name=printer_name
        )

    @staticmethod
    def _cache_age_days(asset: AssetRecord) -> Optional[int]:
        if not asset.source_verified_at:
            return None
        try:
            verified = datetime.strptime(
                asset.source_verified_at, "%Y-%m-%d"
            ).date()
        except ValueError:
            return None
        return (date.today() - verified).days

    def export_csv_string(self) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Scan Timestamp", "Vendor", "Service Tag / Serial Number", "Model Name", "Warranty Status", "Expiration Date", "Source Confidence"])
        for r in self.scan_history:
            writer.writerow([r.timestamp, r.vendor.value, r.serial_number, r.model_name, r.warranty_status, r.expiration_date, r.source_confidence.value])
        return output.getvalue()
