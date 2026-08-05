# Core domain

The core layer turns a scanned identifier into a verified domain record and
then sends that record to an explicitly selected output connector.

- `core/models.py` defines `AssetRecord`, `EERecord`, warranty entitlements,
  vendor types, confidence states, and print results.
- `core/scanner.py` cleans scans, recognizes internal EE scans, and detects
  supported vendor patterns.
- `core/engine.py` coordinates vendor plugins, verified cache access, scan
  history, label printing, and CSV export.
- `core/vendors/` contains HP, Lenovo, Dell, Apple, and generic plugin paths.
  Live lookup failures become unverified results and cannot create labels.
- `core/cache.py` stores only successful verified records in the per-user
  runtime data directory.
- `core/label_formatters/` renders safe text and TSPL layouts without allowing
  model, serial, or entitlement text to inject printer commands.
- `core/printers/` defines connector contracts, discovery, profiles, transport,
  calibration, and platform composition.

The community engine updater remains intentionally unchanged and is tracked as
a separate hardening decision. Do not silently install remote code from a new
feature or test.
