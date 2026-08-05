"""Small contracts shared by platform-specific printer adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(frozen=True)
class SubmissionResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    job_id: Optional[str] = None
    bytes_written: Optional[int] = None


class PrinterDiscovery(Protocol):
    def discover(self, configured_queue: str) -> Optional[str]: ...

    def validate_for_print(self, queue: str) -> str: ...

    def list_candidates(self) -> list[str]: ...


class RawTransport(Protocol):
    def submit(
        self, payload: bytes, queue: str, timeout: int
    ) -> object: ...
