"""Default dependency composition for vendors and platform printer adapters."""

import sys
from typing import Mapping, Optional

from core.cache import WarrantyCache
from core.models import VendorType
from core.printers.base import BasePrinterConnector
from core.printers.bindings import load_binding
from core.printers.cups_connector import CupsPrinterConnector
from core.printers.file_connector import FilePrinterConnector
from core.printers.profiles.service import ProfileService
from core.printers.raw_transport import RawCupsTransport
from core.printers.tsc_connector import TSCPrinterConnector
from core.printers.tsc_discovery import TSCMB341Discovery
from core.vendors.base import BaseVendorPlugin
from core.vendors.dell import DellVendorPlugin
from core.vendors.hp import HPVendorPlugin
from core.vendors.hp_worker import HPBrowserWorker
from core.vendors.lenovo import AppleVendorPlugin, GenericVendorPlugin, LenovoVendorPlugin
from core.vendors.lenovo_worker import LenovoBrowserWorker


def build_default_vendors(
    cache: WarrantyCache,
    hp_worker: Optional[HPBrowserWorker] = None,
    lenovo_worker: Optional[LenovoBrowserWorker] = None,
) -> Mapping[VendorType, BaseVendorPlugin]:
    return {
        VendorType.DELL: DellVendorPlugin(),
        VendorType.HP: HPVendorPlugin(worker=hp_worker or HPBrowserWorker(cache=cache), cache=cache),
        VendorType.LENOVO: LenovoVendorPlugin(worker=lenovo_worker or LenovoBrowserWorker(cache=cache), cache=cache),
        VendorType.APPLE: AppleVendorPlugin(),
        VendorType.GENERIC: GenericVendorPlugin(),
    }


def build_default_printer_connectors(
    platform_name: Optional[str] = None,
) -> Mapping[str, BasePrinterConnector]:
    """Compose the shared TSC coordinator with one platform backend."""
    actual_platform = platform_name or sys.platform
    profile = ProfileService().resolve()
    binding = load_binding(
        platform_name=actual_platform, fallback_queue=profile.queue_name
    )
    connectors: dict[str, BasePrinterConnector] = {
        "file": FilePrinterConnector(),
    }
    if actual_platform == "win32":
        from core.printers.windows_spooler import (
            RawWindowsSpoolerTransport,
            WindowsTSCDiscovery,
        )

        connectors["tsc"] = TSCPrinterConnector(
            profile=profile,
            binding=binding,
            discovery=WindowsTSCDiscovery(binding),
            transport=RawWindowsSpoolerTransport(),
        )
    else:
        connectors["cups"] = CupsPrinterConnector()
        connectors["tsc"] = TSCPrinterConnector(
            profile=profile,
            binding=binding,
            discovery=TSCMB341Discovery(configured_queue=binding.queue_name),
            transport=RawCupsTransport(),
        )
    return connectors
