# Interfaces

## CLI

`interfaces/cli.py` runs the scanner loop and delegates commands to
`interfaces/cli_commands.py`. It starts with virtual output unless the
validated TSC connector is explicitly available. Commands include printer
selection, safe file output, calibration, sensor calibration, and quit.

## Web dashboard

`interfaces/web.py` serves the local dashboard and JSON/CSV APIs. It provides:

- HTTPS pairing for remote phone access.
- Secure cookies and escaped dynamic browser content.
- Bounded POST bodies and serial inputs.
- Remote request throttling and redacted request logs.
- `Cache-Control: no-store` for API and CSV responses.
- Fail-closed printing and profile operations.

Do not expose the raw HTTP port to the internet or use a public issue,
screenshot, or chat message to share a pairing token or serial number.

## Web plugins

`interfaces/plugins/` contains the registration and routing contracts for
browser UI extensions. Built-in plugin metadata is trusted source code; values
that reach HTML or JavaScript must remain escaped and bounded.
