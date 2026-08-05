"""Safe virtual output connector used when no physical printer is selected."""

import os
from pathlib import Path
from typing import List, Optional

from core.app_paths import get_app_paths
from core.label_formatters.plain_text import PlainTextLabelFormatter
from core.models import AssetRecord, EERecord, PrintJobResult
from core.printers.base import BasePrinterConnector


class FilePrinterConnector(BasePrinterConnector):
    """Write a readable label to a caller-configurable local directory."""

    def __init__(self, output_dir: Optional[str] = None):
        default_dir = get_app_paths().labels_dir
        self.output_dir = str(Path(output_dir) if output_dir else default_dir)
        os.makedirs(self.output_dir, exist_ok=True)

    @property
    def connector_name(self) -> str:
        return "Virtual File Printer (Save to TXT/PDF)"

    def list_printers(self) -> List[str]:
        return ["Virtual_File_Printer (Save to Disk)"]

    def print_label(
        self,
        asset: AssetRecord,
        printer_name: Optional[str] = None,
        label_format: str = "text",
    ) -> PrintJobResult:
        label_content = PlainTextLabelFormatter.format_asset_label(asset)
        filename = f"LABEL_{asset.vendor.value.upper()}_{asset.serial_number}.txt"
        file_path = os.path.join(self.output_dir, filename)
        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(label_content)
            return PrintJobResult(
                success=True,
                printer_name="Virtual_File_Printer",
                output_path=file_path,
            )
        except OSError as exc:
            return PrintJobResult(
                success=False,
                printer_name="Virtual_File_Printer",
                error_message=str(exc),
            )

    def print_ee_label(
        self,
        record: EERecord,
        printer_name: Optional[str] = None,
    ) -> PrintJobResult:
        file_path = os.path.join(self.output_dir, f"LABEL_EE_{record.ee_number}.txt")
        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(PlainTextLabelFormatter.format_ee_label(record))
            return PrintJobResult(
                success=True,
                printer_name="Virtual_File_Printer",
                output_path=file_path,
            )
        except OSError as exc:
            return PrintJobResult(
                success=False,
                printer_name="Virtual_File_Printer",
                error_message=str(exc),
            )
