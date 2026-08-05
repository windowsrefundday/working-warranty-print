# Developer Guide: How to Write a Custom Label Printer Connector

This application uses a pluggable printer connector architecture. You can easily add support for any label maker brand (e.g., Dymo LabelWriter, Brother QL series, Zebra ZPL, Seiko Smart Label Printer, EPSON) by creating a new connector subclass.

---

## Step 1: Inherit from `BasePrinterConnector`

Create a new Python file in `core/printers/` (e.g., `dymo_connector.py` or `brother_connector.py`).

Subclass `BasePrinterConnector` and implement the three required members:
1. `@property def connector_name(self) -> str`
2. `def list_printers(self) -> List[str]`
3. `def print_label(self, asset: AssetRecord, printer_name: Optional[str] = None, label_format: str = "text") -> PrintJobResult`

---

## Step 2: Complete Code Template for Custom Label Printer

Below is a complete starter template for a custom Dymo / Brother / Thermal label connector:

```python
import subprocess
from typing import List, Optional
from core.printers.base import BasePrinterConnector
from core.models import AssetRecord, PrintJobResult
from core.label_formatters.plain_text import PlainTextLabelFormatter

class CustomDymoPrinterConnector(BasePrinterConnector):
    """Custom Printer Connector for Dymo LabelWriter 450 / 550."""

    @property
    def connector_name(self) -> str:
        return "Dymo LabelWriter Driver"

    def list_printers(self) -> List[str]:
        """Detect Dymo printers connected via USB or network CUPS queue."""
        # Query system printer queues or SDK
        return ["DYMO_LabelWriter_450", "DYMO_LabelWriter_550"]

    def print_label(self, asset: AssetRecord, printer_name: Optional[str] = None, label_format: str = "text") -> PrintJobResult:
        # 1. Format label text or ZPL/PNG image
        label_text = PlainTextLabelFormatter.format_asset_label(asset)
        target = printer_name or "DYMO_LabelWriter_450"

        try:
            # 2. Execute print command / SDK call
            # Example using CUPS raw stream or Dymo CLI:
            res = subprocess.run(["lp", "-d", target, "-o", "media=w162h90"],
                                 input=label_text.encode('utf-8'),
                                 capture_output=True,
                                 timeout=5)

            if res.returncode == 0:
                return PrintJobResult(success=True, printer_name=target, job_id=res.stdout.strip())
            else:
                return PrintJobResult(success=False, printer_name=target, error_message=res.stderr.strip())
        except Exception as e:
            return PrintJobResult(success=False, printer_name=target, error_message=str(e))
```

---

## Step 3: Register Your Connector in Application Composition

Register platform-specific adapters in `core/application/composition.py` so the
engine remains independent of operating-system details:

```python
from core.printers.dymo_connector import CustomDymoPrinterConnector

# Inside build_default_printer_connectors:
connectors["dymo"] = CustomDymoPrinterConnector()
```

Now users can select your Dymo connector from the CLI or Web UI dropdown!

---

## TSC MB341 Connector Reference

The shared `tsc` connector coordinates the profile, TSPL renderer, discovery,
and raw transport for the TSC MB341. macOS uses CUPS adapters; Windows uses the
Win32 spooler adapters. Both require one explicit queue and use identical TSPL.

### Confirmed local state

- TSC macOS driver package: `tsc.com.tscPrinterDriver.TSC.pkg`, version `1.0`.
- PPDs: `/Library/Printers/TSC/PPDs/MB241.ppd` and
  `/Library/Printers/TSC/PPDs/MB341.ppd`.
- Expected default queue name: `TSC_MB341`.
- Device URI: `usb://TSC/MB341?serial=000001`.
- CUPS make/model: `TSC MB341`, driver/PPD version `1.0`, resolution `300 dpi`.
- Raster filter: `/Library/Printers/TSC/Filter/rastertobarcodetspl`.
- Locked 3-by-1 warranty profile:
  `tsc-mb341-300dpi-3x1-warranty-v1` — 76.2 × 25.4 mm, 3.0 mm gap, 300 dpi,
  darkness 11, speed 50, X offset +2.4 mm, Y shift 0.0 mm, one copy.

### Diagnostics (read-only)

```bash
lpstat -p -d
lpstat -v
lpstat -a TSC_MB341
lpstat -p TSC_MB341 -l
lpoptions -p TSC_MB341 -l
python main.py --diagnose
```

### Safety rules

- **Versioned media profile:** the locked 3-by-1 profile ships under
  `core/printers/profiles/builtin/`. Local calibration changes must become a
  separate saved profile; do not silently overwrite this known-good preset.
- **Configured queue only:** the default connector only uses the configured queue
  name `TSC_MB341`. A renamed or alternate MB341 queue must be selected
  explicitly via `printer_name`; the connector never silently chooses another
  queue.
- **Make/model validation:** the strongest portable check parses
  `lpstat -p <queue> -l` for a `Make and Model:` line that contains both `TSC`
  and `MB341`. If CUPS does not expose that line on a given platform, the
  connector falls back to parsing the USB device URI (`usb://TSC/MB341?...`)
  but never relies on URI alone as proof of make/model.
- **Accepting state:** in addition to `lpstat -p` idle/processing state, the
  connector requires `lpstat -a <queue>` to report `accepting requests`. Stopped,
  disabled, or non-accepting queues are rejected before a job is created.
- **Revalidation:** the queue identity, readiness, and resolution are revalidated
  immediately before every submission.
- **Raw TSPL:** jobs are submitted as raw TSPL with `lp -d <queue> -o raw <file>`.
  The `SIZE` command is emitted in physical millimeters (e.g. `SIZE 101.6 mm,50.8 mm`);
  coordinate/barcode geometry is scaled to the profile dpi.
- **Windows RAW TSPL:** `RawWindowsSpoolerTransport` uses `StartDocPrinter`
  with datatype `RAW` and verifies that `WritePrinter` accepted every byte.
- **Platform composition:** `build_default_printer_connectors` injects the
  CUPS or Windows discovery/transport pair into the same `TSCPrinterConnector`.
- **No automatic retry, no shell, no fallback** to the system default or another
  printer.
- **Calibration:** `calibrate` prints one layout test. `sensorcal` runs
  `GAPDETECT 300,35` for the locked media and intentionally feeds several
  labels once; it is never part of normal warranty printing.

### Cancelling a CUPS job

```bash
cancel TSC_MB341-<job-id>
# or cancel all TSC jobs:
cancel -a TSC_MB341
```

### Automated tests

Unit tests mock `lpstat`, `lpoptions`, and `lp`. They never contact the physical
printer.
