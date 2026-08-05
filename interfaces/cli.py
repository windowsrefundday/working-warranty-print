"""Terminal application shell; commands and scanner mechanics live elsewhere."""

import os
import time

from core.engine import WarrantyEngine
from core.label_formatters.plain_text import PlainTextLabelFormatter
from core.printers.tsc_connector import TSCPrinterConnector
from interfaces.cli_commands import CLICommandRouter
from interfaces.scanner_input import play_scan_beep, read_barcode_auto_submit


def run_cli_mode(initial_connector: str | None = None):
    engine = WarrantyEngine()
    engine.start()
    engine.set_active_connector("file")
    if initial_connector != "file" or os.environ.get("TSC_PRINTER_MODE") == "1":
        tsc = engine.connectors.get("tsc")
        if isinstance(tsc, TSCPrinterConnector) and tsc.profile.is_configured() and tsc.list_printers():
            engine.set_active_connector("tsc")

    printing = "ENABLED" if engine.active_connector_key == "tsc" else "DISABLED (Virtual File Output Only)"
    print("\n" + "=" * 60)
    print("  UNIVERSAL WARRANTY LOOKUP (CLI MODE)")
    print("  Created by Joel Manuel for the VA 2026")
    print("  Thanks to Steve, Anthony, Chris, and Ernes")
    print("=" * 60)
    print(f"  Physical Printing   : {printing}")
    print(f"  Active Output Driver: {engine.get_active_connector().connector_name}")
    print("  Commands: setup, file, tsc, printers, calibrate, sensorcal, cups <queue>, q")
    print("=" * 60 + "\n")
    commands = CLICommandRouter(engine)
    try:
        while True:
            try:
                raw_input = read_barcode_auto_submit(f"[{engine.get_active_connector().connector_name}] Scan Barcode > ")
                if not raw_input:
                    continue
                command_result = commands.handle(raw_input)
                if command_result == "quit":
                    break
                if command_result == "handled":
                    continue
                play_scan_beep()
                ee_record = engine.parse_ee_scan(raw_input)
                if ee_record is not None:
                    print("\n" + PlainTextLabelFormatter.format_ee_terminal(ee_record))
                    result = engine.print_ee_label(ee_record)
                    if result.success and result.output_path:
                        print(f"[LABEL SAVED] Virtual EE label created at: {result.output_path}\n")
                    elif result.success:
                        print(f"[LABEL PRINTED] EE number sent to: {result.printer_name}\n")
                    else:
                        print(f"[LABEL BLOCKED] {result.error_message}\n")
                    continue

                started = time.perf_counter()

                def show_progress(stage: str, percent: int) -> None:
                    width = 24
                    filled = round(width * percent / 100)
                    print(f"\r[{'█' * filled}{'░' * (width - filled)}] {percent:3d}% {stage:<30} {time.perf_counter() - started:5.1f}s", end="", flush=True)

                asset = engine.lookup_asset(raw_input, progress_callback=show_progress)
                print("\n\n" + PlainTextLabelFormatter.format_terminal_label(asset))
                result = engine.print_asset_label(asset)
                if result.success and result.output_path:
                    print(f"[LABEL SAVED] Virtual label file created at: {result.output_path}\n")
                elif not result.success:
                    print(f"[LABEL BLOCKED] {result.error_message}\n")
            except KeyboardInterrupt:
                print("\n[EXITING] Exiting scanner session.")
                break
            except Exception as exc:
                print(f"\n[ERROR] {exc}\n")
    finally:
        engine.stop()
