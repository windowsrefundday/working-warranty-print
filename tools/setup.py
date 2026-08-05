"""Shared, read-only-safe setup flow for the macOS and Windows launchers."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SetupStage:
    """One setup command and its explicit failure policy."""

    description: str
    command: list[str]
    allow_failure: bool = False
    env_overrides: Mapping[str, str] | None = None


@dataclass(frozen=True)
class SetupResult:
    """Summary of setup stages that completed or degraded safely."""

    browser_install_succeeded: bool


CommandRunner = Callable[
    [str, Sequence[str], Path, Mapping[str, str] | None], None
]
MINIMUM_PYTHON_VERSION = (3, 11)


def repository_root() -> Path:
    """Return the repository root regardless of the caller's directory."""
    return Path(__file__).resolve().parents[1]


def current_platform() -> str:
    """Return the supported platform key for the running interpreter."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    raise RuntimeError("Setup is supported on macOS and Windows only.")


def validate_python(system: str) -> None:
    """Reject unsupported Python versions and Windows architectures."""
    if sys.version_info < MINIMUM_PYTHON_VERSION:
        required = ".".join(map(str, MINIMUM_PYTHON_VERSION))
        raise RuntimeError(f"Python {required} or newer is required.")
    machine = platform.machine().lower()
    if system == "windows" and machine not in {"amd64", "x86_64"}:
        raise RuntimeError("64-bit Python is required on Windows.")


def venv_python(root: Path, system: str) -> Path:
    """Return the platform-specific Python executable within the venv."""
    if system == "windows":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def requirements_file(root: Path, system: str) -> Path:
    """Return the requirements file that matches the selected platform."""
    filename = (
        "requirements-windows.txt" if system == "windows" else "requirements.txt"
    )
    return root / filename


def build_setup_commands(
    root: Path,
    system: str,
    python_executable: str,
    npm_executable: str | None = None,
    *,
    with_tunnel_runtime: bool = False,
    browser_ca_cert: Path | None = None,
) -> list[SetupStage]:
    """Build the safe, deterministic setup command sequence."""
    environment_python = str(venv_python(root, system))
    browser_env = (
        {"NODE_EXTRA_CA_CERTS": str(browser_ca_cert)}
        if browser_ca_cert is not None
        else None
    )
    commands = [
        SetupStage(
            "Creating or refreshing the isolated .venv",
            [python_executable, "-m", "venv", str(root / ".venv")],
        ),
        SetupStage(
            "Upgrading pip",
            [environment_python, "-m", "pip", "install", "--upgrade", "pip"],
        ),
        SetupStage(
            "Installing application dependencies",
            [
                environment_python,
                "-m",
                "pip",
                "install",
                "-r",
                str(requirements_file(root, system)),
            ],
        ),
        SetupStage(
            "Installing the application-managed Chromium browser",
            [environment_python, "-m", "playwright", "install", "chromium"],
            allow_failure=True,
            env_overrides=browser_env,
        ),
        SetupStage(
            "Running read-only system and printer checks",
            [environment_python, str(root / "main.py"), "--diagnose"],
        ),
    ]
    if with_tunnel_runtime:
        if npm_executable is None:
            raise RuntimeError(
                "npm is required when --with-tunnel-runtime is selected."
            )
        commands.insert(
            -1,
            SetupStage(
                "Installing the locked HTTPS tunnel runtime",
                [npm_executable, "ci", "--omit=dev", "--ignore-scripts"],
            ),
        )
    return commands


def run_command(
    description: str,
    command: Sequence[str],
    cwd: Path,
    env_overrides: Mapping[str, str] | None = None,
) -> None:
    """Run one setup stage with only the explicitly supplied environment."""
    environment = dict(os.environ)
    environment.pop("NODE_TLS_REJECT_UNAUTHORIZED", None)
    environment.pop("PYTHONHTTPSVERIFY", None)
    if env_overrides:
        environment.update(env_overrides)
    subprocess.run(command, cwd=cwd, check=True, env=environment)


def run_setup(
    root: Path,
    system: str,
    *,
    python_executable: str | None = None,
    npm_executable: str | None = None,
    with_tunnel_runtime: bool = False,
    browser_ca_cert: Path | None = None,
    runner: CommandRunner = run_command,
) -> SetupResult:
    """Run the common setup stages without performing printer actions."""
    validate_python(system)
    npm = npm_executable
    if with_tunnel_runtime:
        npm = npm or shutil.which("npm")
        if npm is None:
            raise RuntimeError(
                "Node.js/npm is required when tunnel setup is selected. "
                "Install Node.js LTS and rerun setup with tunnel setup enabled."
            )
    if browser_ca_cert is not None and not browser_ca_cert.is_file():
        raise RuntimeError(f"Browser CA certificate was not found: {browser_ca_cert}")
    python = python_executable or sys.executable
    commands = build_setup_commands(
        root,
        system,
        python,
        npm,
        with_tunnel_runtime=with_tunnel_runtime,
        browser_ca_cert=browser_ca_cert,
    )
    browser_install_succeeded = True
    for index, stage in enumerate(commands, start=1):
        print(f"[{index}/{len(commands)}] {stage.description}")
        try:
            runner(stage.description, stage.command, root, stage.env_overrides)
        except (OSError, subprocess.CalledProcessError) as exc:
            if not stage.allow_failure:
                raise
            browser_install_succeeded = False
            print(
                "\n[WARNING] Playwright Chromium could not be downloaded. "
                "Setup will continue with system-browser fallback when available.",
                file=sys.stderr,
            )
            print(f"[WARNING] Browser installation error: {exc}\n", file=sys.stderr)
    return SetupResult(browser_install_succeeded=browser_install_succeeded)


def main(argv: Sequence[str] | None = None) -> int:
    """Run setup for the host platform and return an operator-friendly status."""
    print("Created by Joel Manuel for the VA 2026")
    print("Thanks to Steve, Anthony, Chris, and Ernes")
    parser = argparse.ArgumentParser(
        description="Set up the Warranty Label Printer safely."
    )
    parser.add_argument(
        "--with-tunnel-runtime",
        action="store_true",
        help="Also install the locked localtunnel runtime for phone-camera HTTPS mode.",
    )
    parser.add_argument(
        "--browser-ca-cert",
        type=Path,
        help="Trusted corporate CA certificate used only for the Playwright download.",
    )
    args = parser.parse_args(argv)
    try:
        root = repository_root()
        result = run_setup(
            root,
            current_platform(),
            with_tunnel_runtime=args.with_tunnel_runtime,
            browser_ca_cert=args.browser_ca_cert,
        )
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1
    if result.browser_install_succeeded:
        print("Setup completed successfully.")
    else:
        print("Setup completed with a browser-download warning.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
