"""CUPS identity and readiness checks for the TSC MB341 only."""

import re
import subprocess
from collections.abc import Callable
from typing import Optional
from urllib.parse import urlparse


class TSCMB341Discovery:
    EXPECTED_USB_SCHEME = "usb"
    EXPECTED_USB_VENDOR = "TSC"
    EXPECTED_USB_MODEL = "MB341"

    def __init__(
        self,
        runner: Optional[Callable[..., object]] = None,
        configured_queue: str = "TSC_MB341",
    ):
        self._runner = runner or subprocess.run
        self.configured_queue = configured_queue

    def discover(self, configured_queue: str) -> Optional[str]:
        printers = self._run(["lpstat", "-p", configured_queue])
        devices = self._run(["lpstat", "-v", configured_queue])
        if printers is None or devices is None:
            return None
        printer_line = printers.splitlines()[0] if printers.strip() else ""
        uri = self._uri_for_queue(devices, configured_queue)
        if self._queue_is_accepting_from_line(printer_line) and self._is_valid_uri(uri):
            return configured_queue
        return None

    def list_candidates(self) -> list[str]:
        """CUPS v1 intentionally exposes only the configured exact queue."""
        queue = self.discover(self.configured_queue)
        return [queue] if queue else []

    def validate_for_print(self, queue: str) -> str:
        printers = self._run(["lpstat", "-p", queue]) or ""
        devices = self._run(["lpstat", "-v", queue]) or ""
        printer_line = printers.splitlines()[0] if printers else ""
        if not self._queue_is_accepting_from_line(printer_line):
            raise RuntimeError(f"Queue {queue} is not idle/accepting jobs for TSC MB341.")
        accepting = self._run(["lpstat", "-a", queue]) or ""
        if not self._queue_is_accepting_from_lpstat_a(accepting, queue):
            raise RuntimeError(f"Queue {queue} is not accepting jobs (lpstat -a) for TSC MB341.")
        if not self._is_valid_uri(self._uri_for_queue(devices, queue)):
            raise RuntimeError(f"Queue {queue} is not the validated TSC MB341 USB device.")
        detailed = self._run(["lpstat", "-p", queue, "-l"]) or ""
        if detailed.strip() and not self._confirm_make_model(detailed):
            raise RuntimeError(f"Queue {queue} does not report make/model TSC MB341 in CUPS.")
        options = self._run(["lpoptions", "-p", queue]) or ""
        capabilities = self._run(["lpoptions", "-p", queue, "-l"]) or ""
        if not self._confirm_300_dpi(options + "\n" + capabilities):
            raise RuntimeError(f"Queue {queue} does not report 300 dpi for TSC MB341.")
        return queue

    def _run(self, cmd: list[str]) -> Optional[str]:
        try:
            result = self._runner(cmd, capture_output=True, text=True, timeout=5)
            return getattr(result, "stdout", "")
        except Exception:
            return None

    @staticmethod
    def _uri_for_queue(stdout: str, queue: str) -> str:
        match = re.search(rf"device for {re.escape(queue)}:\s*(\S+)", stdout)
        return match.group(1) if match else ""

    @staticmethod
    def _queue_is_accepting_from_line(line: str) -> bool:
        lower = line.lower()
        return bool(line.strip()) and "disabled" not in lower and ("idle" in lower or "processing" in lower)

    @staticmethod
    def _queue_is_accepting_from_lpstat_a(stdout: str, queue: str) -> bool:
        for line in stdout.splitlines():
            line = line.strip()
            if line.lower().startswith(queue.lower()):
                return "not accepting" not in line.lower() and "accepting requests" in line.lower()
        return False

    @staticmethod
    def _confirm_make_model(detailed_lpstat: str) -> bool:
        for line in detailed_lpstat.splitlines():
            match = re.match(r"Make and Model:\s*(.+)", line.strip(), re.IGNORECASE)
            if match:
                value = match.group(1).upper()
                return "TSC" in value and "MB341" in value
        return True

    @classmethod
    def _is_valid_uri(cls, uri: str) -> bool:
        try:
            parsed = urlparse(uri)
        except Exception:
            return False
        return (
            parsed.scheme.lower() == cls.EXPECTED_USB_SCHEME
            and (parsed.hostname or "").upper() == cls.EXPECTED_USB_VENDOR
            and parsed.path.lstrip("/").upper() == cls.EXPECTED_USB_MODEL
        )

    @staticmethod
    def _confirm_300_dpi(options: str) -> bool:
        for line in options.splitlines():
            normalized = line.strip().lower()
            if normalized.startswith("dpi=") or normalized.startswith("resolution/"):
                return "300dpi" in normalized or "300" in normalized
        return "300" in options
