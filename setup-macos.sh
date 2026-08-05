#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

printf '%s\n' "Created by Joel Manuel for the VA 2026"
printf '%s\n' "Thanks to Steve, Anthony, Chris, and Ernes"

PYTHON_BIN="${PYTHON_BIN:-python3}"
SETUP_ARGS=()
if [[ "${1:-}" == "--with-tunnel-runtime" ]]; then
    SETUP_ARGS+=("--with-tunnel-runtime")
    shift
fi
if [[ $# -gt 0 ]]; then
    printf '%s\n' "Usage: ./setup-macos.sh [--with-tunnel-runtime]" >&2
    exit 2
fi
command -v "$PYTHON_BIN" >/dev/null || {
    printf '%s\n' "Python 3.11 or newer was not found. Set PYTHON_BIN or install Python 3.11+." >&2
    exit 1
}
if [ ${#SETUP_ARGS[@]} -gt 0 ]; then
  "$PYTHON_BIN" tools/setup.py "${SETUP_ARGS[@]}"
else
  "$PYTHON_BIN" tools/setup.py
fi

printf '%s\n' "Setup complete. Start the scanner with ./run-macos.sh"
