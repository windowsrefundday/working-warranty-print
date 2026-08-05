import subprocess
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest import mock

from tools import setup


class SetupTests(unittest.TestCase):
    def test_macos_default_commands_do_not_require_node(self) -> None:
        root = Path("/repo")
        commands = setup.build_setup_commands(
            root,
            "macos",
            "/runtime/python3",
        )

        self.assertEqual(
            commands[0].command,
            ["/runtime/python3", "-m", "venv", str(root / ".venv")],
        )
        self.assertEqual(
            commands[2].command[-1],
            str(root / "requirements.txt"),
        )
        self.assertEqual(commands[-1].command[-1], "--diagnose")

    def test_tunnel_setup_adds_locked_runtime_install(self) -> None:
        commands = setup.build_setup_commands(
            Path("/repo"),
            "macos",
            "/runtime/python3",
            "/runtime/npm",
            with_tunnel_runtime=True,
        )

        self.assertEqual(
            commands[4].command,
            ["/runtime/npm", "ci", "--omit=dev", "--ignore-scripts"],
        )

    def test_windows_uses_windows_requirements_and_venv_python(self) -> None:
        commands = setup.build_setup_commands(
            Path("C:/repo"),
            "windows",
            "C:/Python/python.exe",
            "C:/Program Files/nodejs/npm.cmd",
        )

        self.assertEqual(
            commands[1].command[0],
            str(Path("C:/repo") / ".venv" / "Scripts" / "python.exe"),
        )
        self.assertEqual(
            commands[2].command[-1],
            str(Path("C:/repo") / "requirements-windows.txt"),
        )

    def test_tunnel_setup_requires_existing_node_runtime(self) -> None:
        with mock.patch.object(setup.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Node.js/npm"):
                setup.run_setup(
                    Path("/repo"),
                    "macos",
                    with_tunnel_runtime=True,
                )

    def test_setup_never_runs_printer_or_calibration_commands(self) -> None:
        executed: list[tuple[str, list[str], Path, object]] = []

        def record(
            description: str,
            command: Sequence[str],
            cwd: Path,
            env_overrides: object,
        ) -> None:
            executed.append((description, list(command), cwd, env_overrides))

        setup.run_setup(
            Path("/repo"),
            "macos",
            python_executable="/runtime/python3",
            npm_executable="/runtime/npm",
            runner=record,
        )

        command_text = " ".join(
            argument.lower()
            for _, command, _, _ in executed
            for argument in command
        )
        self.assertNotIn("--setup-printer", command_text)
        self.assertNotIn("calibrate", command_text)
        self.assertNotIn("print", command_text)
        self.assertIn("--diagnose", command_text)
        self.assertNotIn("npm", command_text)

    def test_browser_install_failure_continues_and_reports_degraded_result(self):
        calls: list[str] = []

        def record(
            description: str,
            command: Sequence[str],
            cwd: Path,
            env_overrides: object,
        ) -> None:
            calls.append(description)
            if "playwright" in command:
                raise subprocess.CalledProcessError(1, list(command))

        with mock.patch.object(setup.platform, "machine", return_value="AMD64"):
            result = setup.run_setup(
                Path("/repo"),
                "windows",
                python_executable="C:/Python/python.exe",
                runner=record,
            )

        self.assertFalse(result.browser_install_succeeded)
        self.assertEqual(len(calls), 5)
        self.assertIn("Running read-only system and printer checks", calls[-1])

    def test_non_browser_stage_failure_remains_fatal(self):
        def record(
            description: str,
            command: Sequence[str],
            cwd: Path,
            env_overrides: object,
        ) -> None:
            if "pip" in command:
                raise subprocess.CalledProcessError(1, list(command))

        with self.assertRaises(subprocess.CalledProcessError):
            with mock.patch.object(setup.platform, "machine", return_value="AMD64"):
                setup.run_setup(
                    Path("/repo"),
                    "windows",
                    python_executable="C:/Python/python.exe",
                    runner=record,
                )

    def test_browser_ca_certificate_is_scoped_to_browser_stage(self):
        executed: list[tuple[str, object]] = []

        def record(
            description: str,
            command: Sequence[str],
            cwd: Path,
            env_overrides: object,
        ) -> None:
            executed.append((description, env_overrides))

        with mock.patch.object(Path, "is_file", return_value=True):
            with mock.patch.object(setup.platform, "machine", return_value="AMD64"):
                setup.run_setup(
                    Path("/repo"),
                    "windows",
                    python_executable="C:/Python/python.exe",
                    browser_ca_cert=Path("C:/certs/corporate.pem"),
                    runner=record,
                )

        self.assertEqual(len(executed), 5)
        self.assertIsNone(executed[0][1])
        self.assertIsNone(executed[1][1])
        self.assertIsNone(executed[2][1])
        self.assertEqual(
            executed[3][1],
            {"NODE_EXTRA_CA_CERTS": str(Path("C:/certs/corporate.pem"))},
        )
        self.assertIsNone(executed[4][1])

    def test_run_command_removes_insecure_tls_overrides_by_default(self):
        with mock.patch.dict(
            setup.os.environ,
            {
                "NODE_TLS_REJECT_UNAUTHORIZED": "0",
                "PYTHONHTTPSVERIFY": "0",
            },
            clear=False,
        ):
            with mock.patch.object(setup.subprocess, "run") as run:
                setup.run_command("diagnostics", ["python", "--diagnose"], Path("/repo"))

        environment = run.call_args.kwargs["env"]
        self.assertNotIn("NODE_TLS_REJECT_UNAUTHORIZED", environment)
        self.assertNotIn("PYTHONHTTPSVERIFY", environment)

    def test_unsupported_host_platform_is_rejected(self) -> None:
        with mock.patch.object(setup.sys, "platform", "linux"):
            with self.assertRaisesRegex(RuntimeError, "macOS and Windows"):
                setup.current_platform()


if __name__ == "__main__":
    unittest.main()
