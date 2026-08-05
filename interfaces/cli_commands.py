"""Table-driven CLI command routing; scanner input stays outside this module."""

from collections.abc import Callable

from core.engine import WarrantyEngine
from core.printers.tsc_connector import TSCPrinterConnector
from core.printers.setup_service import configure_printer_binding


class CLICommandRouter:
    def __init__(self, engine: WarrantyEngine, output: Callable[[str], None] = print):
        self.engine = engine
        self.output = output
        self._exact = {
            "update": self._update,
            "u": self._update,
            "git": self._update,
            "file": self._file,
            "tsc": self._tsc,
            "printers": self._printers,
            "calibrate": self._calibrate,
            "sensorcal": self._sensorcal,
            "setup": self._setup,
        }

    def handle(self, raw_input: str) -> str | None:
        command = raw_input.strip().lower()
        if command in ("q", "quit", "exit"):
            self.output("\n[EXITING] Scan audit session finished.\n")
            return "quit"
        if command == "cups" or command.startswith("cups "):
            self._cups(raw_input)
            return "handled"
        handler = self._exact.get(command)
        if handler is None:
            return None
        handler()
        return "handled"

    def _tsc_connector(self) -> TSCPrinterConnector | None:
        connector = self.engine.connectors.get("tsc")
        if not isinstance(connector, TSCPrinterConnector):
            self.output("\n[ERROR] TSC connector is not available.\n")
            return None
        return connector

    def _update(self) -> None:
        self.output("\n[GITHUB UPDATER] Fetching latest community warranty engines...")
        self.engine.update_github_engines()

    def _file(self) -> None:
        self.engine.set_active_connector("file")
        self.output(f"\n[PRINTER CHANGED] Switched to virtual driver: {self.engine.get_active_connector().connector_name}\n")

    def _cups(self, raw_input: str) -> None:
        if "cups" not in self.engine.connectors:
            self.output(
                "\n[ERROR] CUPS is not available on Windows. Use 'setup' to "
                "bind the Windows TSC MB341 queue.\n"
            )
            return
        parts = raw_input.strip().split(None, 1)
        connector = self.engine.connectors["cups"]
        if len(parts) > 1:
            connector.target_printer = parts[1].strip()
            self.engine.set_active_connector("cups")
            self.output(f"\n[PRINTER CHANGED] Generic CUPS driver targeting explicit queue: {connector.target_printer}\n")
            return
        self.engine.set_active_connector("cups")
        self.output("\n[PRINTER CHANGED] Switched to physical printer driver: generic CUPS.\n  Use 'cups <queue>' to set an explicit destination; bare 'lp' is disabled.\n")

    def _tsc(self) -> None:
        connector = self._tsc_connector()
        if connector is None:
            return
        queues = connector.list_printers()
        if not queues:
            self.output("\n[TSC PRINTER] No validated TSC MB341 queue detected.\n  Ensure the TSC driver is installed and the queue is idle/accepting jobs.\n")
            return
        self.engine.set_active_connector("tsc")
        self.output(f"\n[PRINTER CHANGED] TSC MB341 ready: queue={queues[0]}, model={connector.profile.model}, dpi={connector.profile.dpi}")
        self.output(f"  Profile: {connector.profile.width_mm}mm x {connector.profile.height_mm}mm, gap={connector.profile.gap_mm}mm, darkness={connector.profile.darkness}, speed={connector.profile.speed}\n")

    def _printers(self) -> None:
        connector = self._tsc_connector()
        if connector is None:
            return
        queues = connector.list_printers()
        if not queues:
            self.output("\n[TSC PRINTER] No validated TSC MB341 queue detected.\n")
            return
        for queue in queues:
            self.output(f"\n[TSC PRINTER] {queue}: {connector.profile.model} @ {connector.profile.dpi} dpi")
        self.output("")

    def _calibrate(self) -> None:
        connector = self._tsc_connector()
        if connector is None:
            return
        result = connector.print_calibration_label()
        self.output(f"\n[CALIBRATION{' ' if result.success else ' BLOCKED '}]" + (f"Test label submitted: {result.printer_name} job={result.job_id}\n" if result.success else f"{result.error_message}\n"))

    def _sensorcal(self) -> None:
        connector = self._tsc_connector()
        if connector is None:
            return
        result = connector.calibrate_gap_sensor()
        self.output(f"\n[SENSOR CALIBRATION{' ' if result.success else ' BLOCKED '}]" + (f"Gap calibration submitted: {result.printer_name} job={result.job_id}\n" if result.success else f"{result.error_message}\n"))

    def _setup(self) -> None:
        connector = self._tsc_connector()
        if connector is not None:
            configure_printer_binding(connector, output_fn=self.output)
