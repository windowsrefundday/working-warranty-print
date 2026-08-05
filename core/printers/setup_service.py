"""Interactive-free printer binding operations shared by CLI entry points."""

from __future__ import annotations

import sys
from typing import Any, Callable, Optional, cast

from core.printers.bindings import PrinterBinding, default_binding, save_binding
from core.printers.tsc_connector import TSCPrinterConnector


def configure_printer_binding(
    connector: TSCPrinterConnector,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    binding_path: Optional[str] = None,
) -> Optional[PrinterBinding]:
    """Require an explicit operator choice; never select a queue silently."""
    candidates = connector.list_candidates()
    if not candidates:
        output_fn("No validated local USB TSC MB341 queues were found.")
        if sys.platform == "win32":
            output_fn(
                "Install the official TSC Windows driver, connect the MB341 by "
                "USB, and run this command again."
            )
        return None
    output_fn("Validated TSC MB341 queues:")
    for index, queue in enumerate(candidates, start=1):
        output_fn(f"  {index}. {queue}")
    raw = input_fn("Select a queue number (or press Enter to cancel): ").strip()
    if not raw:
        output_fn("Printer setup cancelled; no binding was changed.")
        return None
    try:
        selected = candidates[int(raw) - 1]
    except (ValueError, IndexError):
        output_fn("Invalid selection; no binding was changed.")
        return None
    discovery = cast(Any, connector._discovery)
    if hasattr(discovery, "binding_for_queue"):
        binding = discovery.binding_for_queue(selected)
    else:
        binding = default_binding(selected)
    saved_path = save_binding(binding, binding_path)
    connector.set_binding(binding)
    output_fn(f"Saved exact MB341 binding to {saved_path}")
    return binding
