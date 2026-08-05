# Testing and validation

Tests use Python's standard-library `unittest` runner. They must not contact a
physical printer, alter calibration, use a default queue, or depend on
operational serial numbers.

## Local checks

```bash
python -m unittest discover -s tests -v
python -m compileall -q core interfaces main.py tests
npx pyright
python tools/release_audit.py
npm audit --audit-level=high
```

The repository workflows additionally run `pip-audit`, Chromium installation,
PowerShell syntax checks on Windows, read-only diagnostics, Actionlint,
Dependency Review, CodeQL, Scorecard, and Zizmor as applicable.

## Test ownership

- `test_*vendor*` and parser tests cover live lookup parsing and fail-closed
  behavior.
- printer and formatter tests cover profile, TSPL, queue, transport, and
  one-copy safety.
- web tests cover pairing, input limits, throttling, logs, headers, plugins,
  and escaped output.
- `test_release_audit.py` protects the public-source boundary, including
  workflow action pinning.
