import subprocess
import tempfile
import os
from typing import List, Optional
from core.printers.base import BasePrinterConnector
from core.models import AssetRecord, PrintJobResult
from core.label_formatters.plain_text import PlainTextLabelFormatter

class CupsPrinterConnector(BasePrinterConnector):
    """macOS and Linux CUPS Printer Connector using native lp/lpr commands."""

    def __init__(self, target_printer: Optional[str] = None):
        self.target_printer = target_printer

    @property
    def connector_name(self) -> str:
        return "macOS / Linux CUPS Printer"

    def list_printers(self) -> List[str]:
        try:
            res = subprocess.run(["lpstat", "-e"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                printers = [p.strip() for p in res.stdout.splitlines() if p.strip()]
                return printers if printers else []
        except Exception:
            pass
        return []

    def print_label(self, asset: AssetRecord, printer_name: Optional[str] = None, label_format: str = "text") -> PrintJobResult:
        # Hardened: the generic CUPS connector now requires an explicit destination.
        # Bare `lp` without a queue is prohibited so the system default (which may
        # now be a label printer) cannot be selected implicitly.
        effective_printer = printer_name or self.target_printer
        if not effective_printer:
            return PrintJobResult(
                success=False,
                printer_name="CUPS",
                error_message="Generic CUPS connector requires an explicit printer destination.",
            )

        label_content = PlainTextLabelFormatter.format_asset_label(asset)

        # Create temp label file
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.txt') as tf:
            tf.write(label_content)
            temp_path = tf.name

        try:
            cmd = ["lp", "-d", effective_printer, temp_path]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

            os.unlink(temp_path)

            if res.returncode == 0:
                return PrintJobResult(success=True, printer_name=effective_printer, job_id=res.stdout.strip())
            else:
                return PrintJobResult(success=False, printer_name=effective_printer, error_message=res.stderr.strip())
        except Exception as e:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            return PrintJobResult(success=False, printer_name=effective_printer, error_message=str(e))
