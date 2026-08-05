import os
import subprocess
import sys
from dataclasses import replace
from typing import Any, List, Optional, cast

from core.app_paths import get_app_paths
from core.label_formatters.tspl import TSPLLabelFormatter
from core.models import AssetRecord, EERecord, PrintJobResult
from core.printers.base import BasePrinterConnector
from core.printers.bindings import PrinterBinding, load_binding
from core.printers.contracts import PrinterDiscovery, RawTransport
from core.printers.profiles.models import LabelProfile
from core.printers.profiles.repository import load_profile, save_profile
from core.printers.profiles.service import ProfileService
from core.printers.raw_transport import RawCupsTransport
from core.printers.tsc_calibration import gap_sensor_payload
from core.printers.tsc_discovery import TSCMB341Discovery


DEFAULT_PROFILE_PATH = str(get_app_paths().profile_path)


# Default MB341 profile. Width/height/gap are intentionally unset until the
# loaded stock is measured; physical printing is disabled without them.
DEFAULT_MB341_PROFILE = LabelProfile(
    queue_name="TSC_MB341",
    model="MB341",
    dpi=300,
    width_mm=None,
    height_mm=None,
    gap_mm=None,
    darkness=7,
    speed=50,
    copies=1,
)


def load_saved_profile(path: Optional[str] = None) -> LabelProfile:
    """Load a versioned profile envelope or the supported legacy flat file."""
    return ProfileService(
        profile_path=path or DEFAULT_PROFILE_PATH,
        fallback=profile_from_environment(),
    ).resolve()


def save_profile_to_file(profile: LabelProfile, path: Optional[str] = None) -> str:
    """Persist a validated v1 profile envelope atomically."""
    return save_profile(profile, path or DEFAULT_PROFILE_PATH)


def profile_from_environment() -> LabelProfile:
    """Return an explicit one-session profile supplied through environment variables.

    Missing, partial, or invalid values deliberately return the unconfigured
    profile so an accidental shell setting cannot cause a physical print.
    """
    keys = ("TSC_LABEL_WIDTH_MM", "TSC_LABEL_HEIGHT_MM", "TSC_LABEL_GAP_MM")
    raw = {key: os.environ.get(key) for key in keys}
    if not any(raw.values()):
        return DEFAULT_MB341_PROFILE
    if not all(raw.values()):
        return DEFAULT_MB341_PROFILE
    try:
        width = float(raw["TSC_LABEL_WIDTH_MM"] or "")
        height = float(raw["TSC_LABEL_HEIGHT_MM"] or "")
        gap = float(raw["TSC_LABEL_GAP_MM"] or "")
        darkness = int(os.environ.get("TSC_LABEL_DARKNESS", "7"))
        speed = int(os.environ.get("TSC_LABEL_SPEED", "50"))
        offset_x = float(os.environ.get("TSC_LABEL_OFFSET_X_MM", "0"))
        shift_y = float(os.environ.get("TSC_LABEL_SHIFT_Y_MM", "0"))
    except ValueError:
        return DEFAULT_MB341_PROFILE
    if (
        width <= 0
        or height <= 0
        or gap < 0
        or offset_x < 0
        or not -25.4 <= shift_y <= 25.4
        or not 0 <= darkness <= 15
        or not 20 <= speed <= 90
    ):
        return DEFAULT_MB341_PROFILE
    return replace(
        DEFAULT_MB341_PROFILE.with_dimensions(width, height, gap),
        darkness=darkness,
        speed=speed,
        offset_x_mm=offset_x,
        shift_y_mm=shift_y,
    )


class TSCPrinterConnector(BasePrinterConnector):
    """Dedicated TSC MB341 USB label-printer connector.

    Discovers only queues whose CUPS metadata identifies them as a TSC MB341 on
    the expected USB device, validates readiness, and submits raw TSPL-EZD.
    No system-default or non-TSC fallback is ever used.
    """

    EXPECTED_MODEL = "TSC MB341"
    EXPECTED_USB_SCHEME = "usb"
    EXPECTED_USB_VENDOR = "TSC"
    EXPECTED_USB_MODEL = "MB341"

    def __init__(
        self,
        profile: Optional[LabelProfile] = None,
        transport: Optional[RawTransport] = None,
        discovery: Optional[PrinterDiscovery] = None,
        binding: Optional[PrinterBinding] = None,
    ):
        self.profile = profile or load_saved_profile()
        self.binding = binding or load_binding(fallback_queue=self.profile.queue_name)
        if transport is None or discovery is None:
            if sys.platform == "win32":
                from core.printers.windows_spooler import (
                    RawWindowsSpoolerTransport,
                    WindowsTSCDiscovery,
                )

                transport = transport or RawWindowsSpoolerTransport()
                discovery = discovery or WindowsTSCDiscovery(self.binding)
            else:
                # Resolve subprocess.run at submission time so unit tests can
                # patch this module without ever reaching a real printer.
                transport = transport or RawCupsTransport(
                    runner=lambda *args, **kwargs: subprocess.run(*args, **kwargs)
                )
                discovery = discovery or TSCMB341Discovery(
                    runner=lambda *args, **kwargs: subprocess.run(*args, **kwargs),
                    configured_queue=self.binding.queue_name,
                )
        self._transport = transport
        self._discovery = discovery
        self._validated_queue: Optional[str] = None

    def set_profile(self, profile: LabelProfile) -> None:
        self.profile = profile

    def set_binding(self, binding: PrinterBinding) -> None:
        binding.validate()
        self.binding = binding
        discovery = cast(Any, self._discovery)
        if hasattr(discovery, "binding"):
            discovery.binding = binding
        if hasattr(discovery, "configured_queue"):
            discovery.configured_queue = binding.queue_name

    def list_candidates(self) -> List[str]:
        try:
            return self._discovery.list_candidates()
        except Exception:
            return []

    def get_status(self) -> dict:
        queues = self.list_printers()
        candidates = self.list_candidates()
        is_ready = len(queues) > 0 and self.profile.is_configured()
        error_msg = None
        if not self.profile.is_configured():
            error_msg = "Stock profile is not configured."
        elif not queues:
            error_msg = (
                f"Queue '{self.binding.queue_name}' is not detected, stopped, "
                "or failed validation."
            )
        return {
            "queue_name": self.binding.queue_name,
            "model": self.profile.model,
            "dpi": self.profile.dpi,
            "is_configured": self.profile.is_configured(),
            "detected_queues": queues,
            "candidate_queues": candidates,
            "is_ready": is_ready,
            "error_message": error_msg,
            "platform": self.binding.platform,
            "binding": {
                "queue_name": self.binding.queue_name,
                "driver_name": self.binding.driver_name,
                "port_name": self.binding.port_name,
                "model": self.binding.model,
                "dpi": self.binding.dpi,
                "confirmed": self.binding.confirmed,
            },
            "profile": {
                "width_mm": self.profile.width_mm,
                "height_mm": self.profile.height_mm,
                "gap_mm": self.profile.gap_mm,
                "darkness": self.profile.darkness,
                "speed": self.profile.speed,
                "offset_x_mm": self.profile.offset_x_mm,
                "shift_y_mm": self.profile.shift_y_mm,
                "copies": self.profile.copies,
            },
        }

    @property
    def connector_name(self) -> str:
        return f"TSC MB341 ({self.profile.dpi} dpi)"

    def list_printers(self) -> List[str]:
        """Return the validated TSC MB341 queue name, or empty list if absent."""
        try:
            queue = self._discover_validated_queue()
            return [queue] if queue else []
        except Exception:
            return []

    def print_label(
        self,
        asset: AssetRecord,
        printer_name: Optional[str] = None,
        label_format: str = "tspl",
    ) -> PrintJobResult:
        """Submit a raw TSPL job to the validated TSC MB341 queue."""
        if not self.profile.is_configured():
            return PrintJobResult(
                success=False,
                printer_name=printer_name or self.binding.queue_name,
                error_message=(
                    "TSC MB341 stock profile is not configured; "
                    "run calibration to set measured width, height, and gap."
                ),
            )
        try:
            queue = self._validate_queue_for_print(printer_name)
        except Exception as exc:
            return PrintJobResult(
                success=False,
                printer_name=printer_name or self.binding.queue_name,
                error_message=str(exc),
            )

        return self._submit_payload(
            TSPLLabelFormatter.format_tspl_label(asset, self.profile), queue, timeout=15
        )

    def print_ee_label(
        self,
        record: EERecord,
        printer_name: Optional[str] = None,
    ) -> PrintJobResult:
        """Submit one raw, large-number EE label through the platform transport."""
        if not self.profile.is_configured():
            return PrintJobResult(
                success=False,
                printer_name=printer_name or self.binding.queue_name,
                error_message=(
                    "TSC MB341 stock profile is not configured; "
                    "run calibration to set measured width, height, and gap."
                ),
            )
        try:
            queue = self._validate_queue_for_print(printer_name)
            payload = TSPLLabelFormatter.format_ee_label(record, self.profile)
        except Exception as exc:
            return PrintJobResult(
                success=False,
                printer_name=printer_name or self.binding.queue_name,
                error_message=str(exc),
            )
        return self._submit_payload(payload, queue, timeout=15)

    def print_calibration_label(
        self, printer_name: Optional[str] = None, test_serial: str = "TEST123"
    ) -> PrintJobResult:
        """Submit a calibration/test label without requiring an AssetRecord."""
        if not self.profile.is_configured():
            return PrintJobResult(
                success=False,
                printer_name=printer_name or self.binding.queue_name,
                error_message=(
                    "TSC MB341 stock profile is not configured; "
                    "run calibration to set measured width, height, and gap."
                ),
            )
        try:
            queue = self._validate_queue_for_print(printer_name)
        except Exception as exc:
            return PrintJobResult(
                success=False,
                printer_name=printer_name or self.profile.queue_name,
                error_message=str(exc),
            )

        return self._submit_payload(
            TSPLLabelFormatter.format_calibration_label(self.profile, test_serial),
            queue,
            timeout=15,
        )

    def calibrate_gap_sensor(
        self, printer_name: Optional[str] = None
    ) -> PrintJobResult:
        """Calibrate the gap sensor using the measured label and gap pitch.

        This is deliberately separate from normal printing: sensor calibration
        feeds several labels and should only be run when media is loaded or
        label skipping indicates that the stored pitch is wrong.
        """
        if not self.profile.is_configured():
            return PrintJobResult(
                success=False,
                printer_name=printer_name or self.profile.queue_name,
                error_message=(
                    "TSC MB341 stock profile is not configured; "
                    "save measured width, height, and gap first."
                ),
            )
        try:
            queue = self._validate_queue_for_print(printer_name)
        except Exception as exc:
            return PrintJobResult(
                success=False,
                printer_name=printer_name or self.profile.queue_name,
                error_message=str(exc),
            )

        return self._submit_payload(gap_sensor_payload(self.profile), queue, timeout=30)

    def _submit_payload(
        self, payload: bytes, queue: str, timeout: int
    ) -> PrintJobResult:
        """Use the selected platform's one raw transport for every native job."""
        try:
            result = self._transport.submit(payload, queue, timeout)
        except subprocess.TimeoutExpired:
            return PrintJobResult(
                success=False,
                printer_name=queue,
                error_message="raw printer submission timed out",
            )
        except Exception as exc:
            return PrintJobResult(
                success=False,
                printer_name=queue,
                error_message=str(exc),
            )
        if getattr(result, "returncode", 1) == 0:
            result_job_id = getattr(result, "job_id", None)
            if not isinstance(result_job_id, (str, int)):
                result_job_id = None
            return PrintJobResult(
                success=True,
                printer_name=queue,
                job_id=(
                    str(result_job_id) if result_job_id is not None else None
                )
                or self._parse_job_id(getattr(result, "stdout", "")),
            )
        return PrintJobResult(
            success=False,
            printer_name=queue,
            error_message=(getattr(result, "stderr", "") or "lp returned nonzero").strip(),
        )

    def _discover_validated_queue(self) -> Optional[str]:
        """Return the configured queue name only if it validates as TSC MB341.

        A renamed or alternate MB341 queue must be selected explicitly via
        printer_name; this connector never silently chooses a different queue.
        """
        return self._discovery.discover(self.binding.queue_name)

    def _validate_queue_for_print(self, printer_name: Optional[str]) -> str:
        """Resolve and validate the target queue immediately before submission."""
        queue = printer_name or self.binding.queue_name
        if not queue:
            raise RuntimeError("No TSC MB341 queue configured.")
        return self._discovery.validate_for_print(queue)

    def _parse_job_id(self, stdout: str) -> Optional[str]:
        import re
        match = re.search(r"request id is\s+(\S+)", stdout)
        return match.group(1) if match else None
