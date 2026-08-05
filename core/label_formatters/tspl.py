"""Compatibility facade for the modular TSPL renderer."""

from core.label_formatters.tspl_commands import barcode as _barcode_command
from core.label_formatters.tspl_commands import pos as _pos
from core.label_formatters.tspl_commands import sanitize as _sanitize
from core.label_formatters.tspl_commands import text as _text_command
from core.label_formatters.tspl_renderer import render_calibration, render_ee, render_warranty
from core.models import AssetRecord, EERecord
from core.printers.profiles.models import LabelProfile


class TSPLLabelFormatter:
    """Legacy API retained while rendering is delegated to focused modules."""

    _sanitize = staticmethod(_sanitize)
    _text_command = staticmethod(_text_command)
    _barcode_command = staticmethod(_barcode_command)
    _pos = staticmethod(_pos)

    @staticmethod
    def format_tspl_label(asset: AssetRecord, profile: LabelProfile) -> bytes:
        return render_warranty(asset, profile).payload

    @staticmethod
    def format_calibration_label(profile: LabelProfile, test_serial: str = "TEST123") -> bytes:
        return render_calibration(profile, test_serial).payload

    @staticmethod
    def format_ee_label(record: EERecord, profile: LabelProfile) -> bytes:
        return render_ee(record, profile).payload


__all__ = ["LabelProfile", "TSPLLabelFormatter"]
