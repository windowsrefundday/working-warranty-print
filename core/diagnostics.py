"""Read-only environment diagnostics for source checkouts."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from typing import Any, Optional

from core.app_paths import get_app_paths
from core.engine import WarrantyEngine
from core.printers.tsc_connector import TSCPrinterConnector
from core.vendors.browser_runtime import available_system_browsers


def build_diagnostic_report(
    engine: Optional[WarrantyEngine] = None,
) -> dict[str, Any]:
    paths = get_app_paths()
    owned_engine = engine is None
    actual_engine = engine or WarrantyEngine()
    try:
        tsc = actual_engine.connectors.get("tsc")
        printer_status = (
            tsc.get_status()
            if isinstance(tsc, TSCPrinterConnector)
            else {
                "is_ready": False,
                "error_message": "TSC connector is unavailable.",
            }
        )
        browser = _browser_status()
        return {
            "application": "Warranty Label Printer",
            "platform": sys.platform,
            "os": platform.platform(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "supported": sys.version_info >= (3, 11)
            and (sys.platform != "win32" or platform.machine().lower() in {"amd64", "x86_64"}),
            "paths": {
                "data_dir": str(paths.data_dir),
                "cache": str(paths.cache_path),
                "profile": str(paths.profile_path),
                "binding": str(paths.binding_path),
                "labels": str(paths.labels_dir),
                "writable": os.access(paths.data_dir, os.W_OK),
            },
            "browser": browser,
            "printer": printer_status,
            "physical_print_attempted": False,
        }
    finally:
        if owned_engine:
            actual_engine.stop()


def _browser_status() -> dict[str, Any]:
    try:
        version = importlib.metadata.version("playwright")
    except importlib.metadata.PackageNotFoundError:
        return {
            "playwright_installed": False,
            "chromium_installed": False,
            "error": "Playwright is not installed.",
        }
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--list"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        combined = f"{result.stdout}\n{result.stderr}".lower()
        chromium_installed = result.returncode == 0 and "chromium" in combined
        error = None if result.returncode == 0 else (result.stderr.strip() or "Browser check failed.")
    except Exception as exc:
        chromium_installed = False
        error = str(exc)
    system_browsers = available_system_browsers()
    preferred_runtime = (
        "bundled-chromium"
        if chromium_installed
        else system_browsers[0]
        if system_browsers
        else None
    )
    return {
        "playwright_installed": True,
        "playwright_version": version,
        "chromium_installed": chromium_installed,
        "system_browsers": list(system_browsers),
        "fallback_available": bool(system_browsers),
        "preferred_runtime": preferred_runtime,
        "error": error,
    }


def print_diagnostic_report(report: dict[str, Any]) -> None:
    print(json.dumps(report, indent=2, sort_keys=True))
