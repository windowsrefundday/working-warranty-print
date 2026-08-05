"""Compatibility imports for the retired plain-text Windows connector.

Windows TSC printing is composed through ``WindowsTSCDiscovery`` and
``RawWindowsSpoolerTransport``. No generic/default-printer implementation is
kept here because it could bypass the MB341 identity and TSPL safety checks.
"""

from core.printers.file_connector import FilePrinterConnector
from core.printers.windows_spooler import (
    RawWindowsSpoolerTransport,
    WindowsTSCDiscovery,
)

__all__ = [
    "FilePrinterConnector",
    "RawWindowsSpoolerTransport",
    "WindowsTSCDiscovery",
]
