import argparse
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.engine import WarrantyEngine
from interfaces.cli import run_cli_mode
from interfaces.web import run_web_mode
from core.diagnostics import build_diagnostic_report, print_diagnostic_report
from core.printers.setup_service import configure_printer_binding
from core.printers.tsc_connector import TSCPrinterConnector

LOCAL_TUNNEL_ENTRYPOINT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "node_modules",
    "localtunnel",
    "bin",
    "lt.js",
)


def is_valid_https_url(value: str) -> bool:
    """Accept only well-formed HTTPS URLs with a hostname."""
    try:
        parsed = urllib.parse.urlsplit(value)
        _ = parsed.port
        return parsed.scheme.lower() == "https" and bool(parsed.hostname)
    except ValueError:
        return False


def stop_tunnel_process(tunnel_process: subprocess.Popen) -> None:
    """Terminate and reap the tunnel child process."""
    if tunnel_process.poll() is not None:
        tunnel_process.wait()
        return
    tunnel_process.terminate()
    try:
        tunnel_process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        tunnel_process.kill()
        tunnel_process.wait()


def launch_https_tunnel(port: int, timeout_seconds: float = 20.0):
    """Launch localtunnel and return its process and verified HTTPS URL."""
    if not os.path.isfile(LOCAL_TUNNEL_ENTRYPOINT):
        npm_bin = shutil.which("npm") or shutil.which("npm.cmd")
        if npm_bin and shutil.which("node"):
            try:
                subprocess.run(
                    [npm_bin, "ci", "--omit=dev", "--ignore-scripts"],
                    cwd=str(Path(__file__).resolve().parent),
                    check=True,
                    timeout=45,
                    capture_output=True,
                )
            except Exception:
                pass
    if not os.path.isfile(LOCAL_TUNNEL_ENTRYPOINT):
        raise RuntimeError(
            "The locked localtunnel runtime is not installed. Run the platform "
            "setup script before using --tunnel."
        )
    node_executable = shutil.which("node")
    if node_executable is None:
        raise RuntimeError(
            "Node.js was not found on PATH. Run the platform setup script "
            "before using --tunnel."
        )
    launch_finished = threading.Event()
    tunnel_process = subprocess.Popen(
        [node_executable, LOCAL_TUNNEL_ENTRYPOINT, "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    tunnel_ready = False
    try:
        output_lines: queue.Queue[str] = queue.Queue()
        reader_finished = threading.Event()

        def read_output() -> None:
            if tunnel_process.stdout is None:
                reader_finished.set()
                return
            try:
                for line in tunnel_process.stdout:
                    if not launch_finished.is_set():
                        output_lines.put(line)
            finally:
                reader_finished.set()

        threading.Thread(target=read_output, daemon=True).start()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                line = output_lines.get(
                    timeout=max(0.0, min(0.25, deadline - time.monotonic()))
                )
            except queue.Empty:
                if tunnel_process.poll() is not None and reader_finished.is_set():
                    break
                continue
            print(line, end="")
            if "your url is:" not in line.lower():
                continue
            public_url = line.split("is:", 1)[-1].strip()
            if is_valid_https_url(public_url):
                tunnel_ready = True
                return tunnel_process, public_url
            break

        raise RuntimeError(
            "Could not establish a verified HTTPS tunnel. "
            "Phone camera mode was not started."
        )
    finally:
        launch_finished.set()
        if not tunnel_ready:
            stop_tunnel_process(tunnel_process)


GIT_PULL_INTERVAL_SECONDS = 6 * 60 * 60


def run_git_pull() -> bool:
    """Fast-forward to verified `origin/main`; fail closed if history diverges."""
    git_bin = shutil.which("git")
    if not git_bin:
        return False
    repo_root = os.path.dirname(os.path.abspath(__file__))
    try:
        fetch = subprocess.run(
            [git_bin, "fetch", "--no-tags", "origin", "main"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if fetch.returncode != 0:
            return False
        head = subprocess.run(
            [git_bin, "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        remote = subprocess.run(
            [git_bin, "rev-parse", "origin/main"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if head.returncode != 0 or remote.returncode != 0:
            return False
        if head.stdout.strip() == remote.stdout.strip():
            return False
        ancestor = subprocess.run(
            [git_bin, "merge-base", "--is-ancestor", "HEAD", "origin/main"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if ancestor.returncode != 0:
            return False
        update = subprocess.run(
            [git_bin, "merge", "--ff-only", "origin/main"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if update.returncode != 0:
            return False
        print(f"[GIT UPDATE] {update.stdout.strip()}")
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _background_git_pull_loop(stop_event: threading.Event) -> None:
    """Schedule git pull every 6 hours while the app is running."""
    while not stop_event.wait(GIT_PULL_INTERVAL_SECONDS):
        run_git_pull()


def start_background_git_updater() -> tuple[threading.Event, threading.Thread]:
    """Start daemon thread for periodic 6-hour git pull updates."""
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_background_git_pull_loop,
        args=(stop_event,),
        name="git-auto-updater",
        daemon=True,
    )
    thread.start()
    return stop_event, thread


def main():
    parser = argparse.ArgumentParser(description="Universal Warranty Lookup & Label Printer Application")
    parser.add_argument("--mode", choices=["cli", "web"], default="cli", help="Interface mode to run (cli or web). Default: cli")
    parser.add_argument("--port", type=int, default=9191, help="Port to run web server on when in web mode. Default: 9191")
    parser.add_argument(
        "--printer",
        choices=["file", "tsc"],
        default="tsc",
        help="CLI output connector. Defaults to the validated TSC MB341; use --printer file to disable physical printing.",
    )
    parser.add_argument("--tunnel", action="store_true", help="Launch a public HTTPS tunnel for phone camera access over 4G/5G or isolated workplace Wi-Fi.")
    parser.add_argument("--public-url", type=str, default=None, help="Explicit public HTTPS URL for phone QR pairing.")
    parser.add_argument("--update-engines", action="store_true", help="Download/update community open-source warranty engines from GitHub.")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Run read-only platform, browser, path, profile, and printer checks.",
    )
    parser.add_argument(
        "--setup-printer",
        action="store_true",
        help="Select and save one explicitly validated USB TSC MB341 queue.",
    )


    args = parser.parse_args()

    if args.diagnose:
        print_diagnostic_report(build_diagnostic_report())
        return

    print("Created by Joel Manuel for the VA 2026")
    print("Thanks to Steve, Anthony, Chris, and Ernes")

    if not os.environ.get("WARRANTY_LABEL_DISABLE_AUTO_UPDATE"):
        run_git_pull()
        start_background_git_updater()

    if args.setup_printer:
        engine = WarrantyEngine()
        connector = engine.connectors.get("tsc")
        if not isinstance(connector, TSCPrinterConnector):
            print("TSC connector is unavailable on this platform.", file=sys.stderr)
            sys.exit(1)
        configured = configure_printer_binding(connector)
        sys.exit(0 if configured is not None else 1)

    if args.update_engines:
        engine = WarrantyEngine()
        engine.update_github_engines()
        sys.exit(0)

    if args.mode == "web":
        pub_url = args.public_url
        tunnel_proc = None
        if pub_url and not is_valid_https_url(pub_url):
            parser.error(
                "--public-url must be a valid HTTPS URL with a hostname"
            )
        if args.tunnel and not pub_url:
            print(f"\n[TUNNEL] Launching public HTTPS tunnel on port {args.port}...")
            tunnel_proc, pub_url = launch_https_tunnel(args.port)
            print(f"[TUNNEL READY] Public URL: {pub_url}\n")

        try:
            run_web_mode(port=args.port, public_url=pub_url)
        finally:
            if tunnel_proc:
                stop_tunnel_process(tunnel_proc)

    else:
        run_cli_mode(initial_connector=args.printer)


if __name__ == "__main__":
    main()
