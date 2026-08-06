"""Windows-only MB341 discovery and raw Win32 spooler transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol

from core.printers.bindings import PrinterBinding
from core.printers.contracts import SubmissionResult


TSC_DOWNLOAD_URL = "https://usca.tscprinters.com/en/downloads"


class WindowsSpoolerAPI(Protocol):
    def enum_local_printers(self) -> list[dict[str, Any]]: ...
    def get_printer(self, queue: str) -> dict[str, Any]: ...
    def resolutions(self, queue: str, port: str) -> list[tuple[int, int]]: ...
    def error_status_mask(self) -> int: ...
    def open_printer(self, queue: str) -> object: ...
    def start_doc(self, handle: object, document_name: str) -> int: ...
    def start_page(self, handle: object) -> None: ...
    def write(self, handle: object, payload: bytes) -> int: ...
    def end_page(self, handle: object) -> None: ...
    def end_doc(self, handle: object) -> None: ...
    def abort(self, handle: object) -> None: ...
    def close(self, handle: object) -> None: ...


class PyWin32SpoolerAPI:
    """Lazy pywin32 facade so importing the project remains portable."""

    def __init__(self) -> None:
        try:
            import win32con  # pyright: ignore[reportMissingModuleSource]
            import win32print  # pyright: ignore[reportMissingModuleSource]
        except ImportError as exc:
            raise RuntimeError(
                "Windows printer support requires pywin32. "
                "Run setup-windows.ps1 or install requirements-windows.txt."
            ) from exc
        self.win32con = win32con
        self.win32print = win32print

    def enum_local_printers(self) -> list[dict[str, Any]]:
        flags = self.win32print.PRINTER_ENUM_LOCAL
        return [
            dict(item)
            for item in self.win32print.EnumPrinters(flags, None, 2)
        ]

    def get_printer(self, queue: str) -> dict[str, Any]:
        handle = self.win32print.OpenPrinter(queue)
        try:
            return dict(self.win32print.GetPrinter(handle, 2))
        finally:
            self.win32print.ClosePrinter(handle)

    def resolutions(self, queue: str, port: str) -> list[tuple[int, int]]:
        value: Any = self.win32print.DeviceCapabilities(
            queue, port, self.win32con.DC_ENUMRESOLUTIONS
        )
        resolutions: list[tuple[int, int]] = []
        for item in value or []:
            if isinstance(item, dict):
                x = item.get("xdpi", item.get("x", item.get("X", 0)))
                y = item.get("ydpi", item.get("y", item.get("Y", 0)))
            else:
                x, y = item[0], item[1]
            resolutions.append((int(x), int(y)))
        return resolutions

    def error_status_mask(self) -> int:
        names = (
            "PRINTER_STATUS_ERROR",
            "PRINTER_STATUS_OFFLINE",
            "PRINTER_STATUS_PAPER_JAM",
            "PRINTER_STATUS_PAPER_OUT",
            "PRINTER_STATUS_PAPER_PROBLEM",
            "PRINTER_STATUS_PAUSED",
            "PRINTER_STATUS_DOOR_OPEN",
            "PRINTER_STATUS_NOT_AVAILABLE",
            "PRINTER_STATUS_NO_TONER",
            "PRINTER_STATUS_USER_INTERVENTION",
        )
        return sum(int(getattr(self.win32print, name, 0)) for name in names)

    def open_printer(self, queue: str):
        return self.win32print.OpenPrinter(queue)

    def start_doc(self, handle, document_name: str) -> int:
        return int(
            self.win32print.StartDocPrinter(
                handle, 1, (document_name, None, "RAW")
            )
        )

    def start_page(self, handle) -> None:
        self.win32print.StartPagePrinter(handle)

    def write(self, handle, payload: bytes) -> int:
        return int(self.win32print.WritePrinter(handle, payload))

    def end_page(self, handle) -> None:
        self.win32print.EndPagePrinter(handle)

    def end_doc(self, handle) -> None:
        self.win32print.EndDocPrinter(handle)

    def abort(self, handle) -> None:
        self.win32print.AbortPrinter(handle)

    def close(self, handle) -> None:
        self.win32print.ClosePrinter(handle)


@dataclass(frozen=True)
class WindowsPrinterDetails:
    queue_name: str
    driver_name: str
    port_name: str
    status: int


class WindowsTSCDiscovery:
    """Validate thermal label printer queues with TSC MB341 as primary recommended."""

    EXCLUDED_DRIVERS = (
        "PDF", "ONENOTE", "XPS", "FAX", "LASER", "LASERJET", "OFFICEJET",
        "DESKJET", "INKJET", "CANON", "LBP", "PIXMA"
    )
    THERMAL_KEYWORDS = (
        "TSC", "MB341", "ZEBRA", "ZDESIGNER", "GODEX", "DYMO",
        "CITIZEN", "HONEYWELL", "BIXOLON", "SATO", "INTERMEC",
        "DATAMAX", "PRINTRONIX", "BROTHER", "THERMAL", "LABEL", "POS", "GENERIC"
    )

    def __init__(
        self,
        binding: PrinterBinding,
        api: Optional[WindowsSpoolerAPI] = None,
    ) -> None:
        self.binding = binding
        self._api = api

    @property
    def api(self):
        if self._api is None:
            self._api = PyWin32SpoolerAPI()
        return self._api

    def list_candidates(self) -> list[str]:
        try:
            tsc_candidates = []
            generic_candidates = []
            for item in self.api.enum_local_printers():
                details = self._details(item)
                if self._identity_is_valid(details):
                    if self._is_tsc_mb341(details):
                        tsc_candidates.append(details.queue_name)
                    else:
                        generic_candidates.append(details.queue_name)
            tsc_sorted = sorted(set(tsc_candidates), key=str.casefold)
            generic_sorted = sorted(set(generic_candidates), key=str.casefold)
            return tsc_sorted + generic_sorted
        except Exception:
            return []

    def discover(self, configured_queue: str) -> Optional[str]:
        if not self.binding.confirmed:
            return None
        if configured_queue != self.binding.queue_name:
            return None
        try:
            self.validate_for_print(configured_queue)
            return configured_queue
        except Exception:
            return None

    def validate_for_print(self, queue: str) -> str:
        if not self.binding.confirmed:
            raise RuntimeError(
                "Windows label printing requires an operator-confirmed binding. "
                "Run main.py --setup-printer."
            )
        if queue != self.binding.queue_name:
            raise RuntimeError(
                f"Queue {queue!r} is not the explicitly bound printer queue."
            )
        try:
            details = self._details(self.api.get_printer(queue))
        except Exception as exc:
            raise RuntimeError(f"Windows queue {queue!r} is unavailable: {exc}") from exc
        if not self._identity_is_valid(details):
            raise RuntimeError(
                f"Queue {queue!r} is not a valid thermal label printer."
            )
        if self.binding.driver_name and details.driver_name != self.binding.driver_name:
            raise RuntimeError(f"Queue {queue!r} driver changed after printer setup.")
        if self.binding.port_name and details.port_name != self.binding.port_name:
            raise RuntimeError(f"Queue {queue!r} USB port changed after printer setup.")
        if details.status & int(self.api.error_status_mask()):
            raise RuntimeError(f"Queue {queue!r} is paused, offline, or in an error state.")
        return queue

    def binding_for_queue(self, queue: str) -> PrinterBinding:
        details = self._details(self.api.get_printer(queue))
        if not self._identity_is_valid(details):
            raise RuntimeError(f"Queue {queue!r} is not a valid thermal label printer.")
        is_tsc = self._is_tsc_mb341(details)
        model_name = "MB341" if is_tsc else details.driver_name
        dpi_val = self._detected_dpi(details)
        return PrinterBinding(
            platform="win32",
            queue_name=details.queue_name,
            driver_name=details.driver_name,
            port_name=details.port_name,
            model=model_name,
            dpi=dpi_val,
            confirmed=True,
        )

    @staticmethod
    def _details(item: dict[str, Any]) -> WindowsPrinterDetails:
        return WindowsPrinterDetails(
            queue_name=str(item.get("pPrinterName") or ""),
            driver_name=str(item.get("pDriverName") or ""),
            port_name=str(item.get("pPortName") or ""),
            status=int(item.get("Status") or 0),
        )

    @classmethod
    def _identity_is_valid(cls, details: WindowsPrinterDetails) -> bool:
        if not details.queue_name:
            return False
        driver_upper = details.driver_name.upper()
        queue_upper = details.queue_name.upper()
        # Exclude paper document printers
        if any(ex in driver_upper or ex in queue_upper for ex in cls.EXCLUDED_DRIVERS):
            return False
        # Include thermal label printers or USB ports
        is_thermal = any(kw in driver_upper or kw in queue_upper for kw in cls.THERMAL_KEYWORDS)
        is_usb = details.port_name.upper().startswith("USB")
        return is_thermal or is_usb

    @classmethod
    def _is_tsc_mb341(cls, details: WindowsPrinterDetails) -> bool:
        driver = details.driver_name.upper()
        queue = details.queue_name.upper()
        return ("TSC" in driver or "TSC" in queue) and ("MB341" in driver or "MB341" in queue)

    def _detected_dpi(self, details: WindowsPrinterDetails) -> int:
        try:
            resolutions = self.api.resolutions(
                details.queue_name, details.port_name
            )
            for x, y in resolutions:
                if int(x) in (203, 300, 600) and int(x) == int(y):
                    return int(x)
        except Exception:
            pass
        return 300


class RawWindowsSpoolerTransport:
    """Submit printer-native TSPL bytes to one explicit Windows queue."""

    def __init__(self, api: Optional[WindowsSpoolerAPI] = None) -> None:
        self._api = api

    @property
    def api(self):
        if self._api is None:
            self._api = PyWin32SpoolerAPI()
        return self._api

    def submit(self, payload: bytes, queue: str, timeout: int) -> SubmissionResult:
        del timeout  # Win32 spooler calls are synchronous and have no timeout option.
        handle = None
        document_started = False
        page_started = False
        job_id: Optional[int] = None
        try:
            handle = self.api.open_printer(queue)
            job_id = self.api.start_doc(handle, "Warranty Label (TSPL)")
            if job_id <= 0:
                raise RuntimeError("Windows spooler did not return a valid job ID.")
            document_started = True
            self.api.start_page(handle)
            page_started = True
            written = self.api.write(handle, payload)
            if written != len(payload):
                raise RuntimeError(
                    f"Windows spooler accepted {written} of {len(payload)} TSPL bytes."
                )
            self.api.end_page(handle)
            page_started = False
            self.api.end_doc(handle)
            document_started = False
            return SubmissionResult(
                returncode=0,
                job_id=str(job_id),
                bytes_written=written,
                stdout=f"Windows spooler job {job_id}",
            )
        except Exception as exc:
            if handle is not None and document_started:
                try:
                    self.api.abort(handle)
                except Exception:
                    pass
            return SubmissionResult(
                returncode=1,
                job_id=str(job_id) if job_id else None,
                stderr=str(exc),
            )
        finally:
            # EndPage is not required after AbortPrinter, and calling it can mask
            # the original failure. The flag exists to document that distinction.
            _ = page_started
            if handle is not None:
                try:
                    self.api.close(handle)
                except Exception:
                    pass
