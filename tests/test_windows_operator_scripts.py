import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsOperatorScriptTests(unittest.TestCase):
    def test_setup_is_location_independent_and_never_prints(self) -> None:
        script = (ROOT / "setup-windows.ps1").read_text(encoding="utf-8")

        self.assertIn("Set-Location -LiteralPath $PSScriptRoot", script)
        self.assertIn('"$PSScriptRoot\\tools\\setup.py"', script)
        self.assertIn("WithTunnelRuntime", script)
        self.assertNotIn("main.py --mode", script)
        self.assertNotIn("main.py --setup-printer", script)
        self.assertNotIn("Out-Printer", script)

    def test_macos_setup_delegates_to_shared_safe_setup(self) -> None:
        script = (ROOT / "setup-macos.sh").read_text(encoding="utf-8")

        self.assertIn('"$PYTHON_BIN" tools/setup.py', script)
        self.assertIn("--with-tunnel-runtime", script)
        self.assertNotIn("main.py --mode", script)
        self.assertNotIn("main.py --setup-printer", script)
        self.assertNotIn("npm install", script)

    def test_operator_helper_exposes_safe_and_physical_modes_explicitly(self) -> None:
        script = (ROOT / "warranty-windows.ps1").read_text(encoding="utf-8")

        self.assertIn("--printer file", script)
        self.assertIn("--printer tsc", script)
        self.assertIn("main.py --diagnose", script)
        self.assertIn("main.py --setup-printer", script)
        self.assertIn("ValidateSet", script)

    def test_operator_helper_has_interactive_menu_and_preserves_explicit_commands(self) -> None:
        script = (ROOT / "warranty-windows.ps1").read_text(encoding="utf-8")

        self.assertIn('[string]$Command = "menu"', script)
        self.assertIn("function Invoke-Menu", script)
        self.assertIn("1. Start CLI printer mode", script)
        self.assertIn("6. Run environment setup", script)
        self.assertIn('& $PSCommandPath cli', script)
        self.assertIn('"menu" {', script)

    def test_readme_leads_with_windows_and_documents_operator_helper(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertLess(
            readme.index("## Windows 11 x64 setup"),
            readme.index("## macOS secondary setup"),
        )
        self.assertIn(r".\warranty-windows.ps1 safe", readme)
        self.assertIn(r".\warranty-windows.ps1 doctor", readme)
        self.assertIn(r".\setup-windows.ps1 -WithTunnelRuntime", readme)
        self.assertIn("./setup-macos.sh --with-tunnel-runtime", readme)
        self.assertIn("Setup and diagnostics never print or calibrate.", readme)


if __name__ == "__main__":
    unittest.main()
