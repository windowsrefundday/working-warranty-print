#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

printf '%s\n' "Created by Joel Manuel for the VA 2026"
printf '%s\n' "Thanks to Steve, Anthony, Chris, and Ernes"

if [[ ! -x ".venv/bin/python" ]]; then
  printf '%s\n' "Missing .venv. Run ./setup-macos.sh first." >&2
  exit 1
fi

exec .venv/bin/python main.py --mode cli "$@"
