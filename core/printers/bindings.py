"""Versioned persistence for an explicitly selected physical printer queue."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from core.app_paths import get_app_paths


BINDING_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PrinterBinding:
    platform: str
    queue_name: str
    driver_name: str = ""
    port_name: str = ""
    model: str = "MB341"
    dpi: int = 300
    usb_identifier: Optional[str] = None
    confirmed: bool = False

    def validate(self) -> None:
        if self.platform not in {"darwin", "win32", "linux"}:
            raise ValueError(f"unsupported printer-binding platform: {self.platform}")
        if not self.queue_name.strip():
            raise ValueError("printer binding requires an explicit queue name")
        if self.model.upper() != "MB341":
            raise ValueError("printer binding must target model MB341")
        if self.dpi != 300:
            raise ValueError("printer binding must target the 300 dpi MB341")
        if self.platform == "win32" and self.port_name:
            if not self.port_name.upper().startswith("USB"):
                raise ValueError("Windows MB341 binding must use a local USB port")


def default_binding(
    queue_name: str = "TSC_MB341", platform_name: Optional[str] = None
) -> PrinterBinding:
    return PrinterBinding(
        platform=platform_name or sys.platform,
        queue_name=queue_name,
        model="MB341",
        dpi=300,
        confirmed=(platform_name or sys.platform) != "win32",
    )


def load_binding(
    path: Optional[str] = None,
    *,
    platform_name: Optional[str] = None,
    fallback_queue: str = "TSC_MB341",
) -> PrinterBinding:
    actual_platform = platform_name or sys.platform
    fallback = default_binding(fallback_queue, actual_platform)
    target = Path(path) if path else get_app_paths().binding_path
    if not target.exists():
        return fallback
    try:
        with target.open(encoding="utf-8") as handle:
            document = json.load(handle)
        if document.get("schema_version") != BINDING_SCHEMA_VERSION:
            return fallback
        binding = PrinterBinding(**document["binding"])
        binding.validate()
        if binding.platform != actual_platform:
            return fallback
        return binding
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return fallback


def save_binding(binding: PrinterBinding, path: Optional[str] = None) -> str:
    binding.validate()
    if not binding.confirmed:
        raise ValueError("only an operator-confirmed printer binding may be saved")
    target = Path(path) if path else get_app_paths().binding_path
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": BINDING_SCHEMA_VERSION,
        "binding": asdict(binding),
    }
    descriptor, temp_path = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(temp_path, target)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise
    return str(target)
