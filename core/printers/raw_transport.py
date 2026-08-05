"""One safe raw-CUPS submission path shared by label connectors."""

import os
import subprocess
import tempfile
from collections.abc import Callable
from typing import Optional


class RawCupsTransport:
    """Submit printer-native bytes without choosing a system default queue.

    The caller owns queue validation and result interpretation. This class owns
    only the temporary file lifetime and the no-shell CUPS invocation.
    """

    def __init__(self, runner: Optional[Callable[..., object]] = None):
        self._runner = runner or subprocess.run

    def submit(self, payload: bytes, queue: str, timeout: int):
        temp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, suffix=".tspl"
            ) as handle:
                handle.write(payload)
                temp_path = handle.name
            return self._runner(
                ["lp", "-d", queue, "-o", "raw", temp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
