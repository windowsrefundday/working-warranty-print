# Architecture

The application is a source-only Python program with optional Node.js support
for the HTTPS tunnel runtime. `main.py` composes the engine and selects the CLI
or web interface.

```text
scanner / browser
        |
        v
 CLI or web interface  -->  WarrantyEngine  -->  vendor plugin
        |                         |                    |
        |                         v                    v
        +------------------> printer connector   live vendor portal
                                  |
                                  v
                         virtual file or TSC MB341
```

## Boundaries

- `core/` owns domain models, warranty lookup, caching, label formatting,
  printer contracts, and platform composition.
- `interfaces/` owns user-facing input/output: terminal scanning, HTTP routes,
  browser plugins, and profile operations.
- `tests/` owns standard-library `unittest` coverage and mocks external
  browsers, operating-system printer APIs, and queues.
- `tools/` owns setup orchestration and publication-safety auditing.
- `.github/` owns automated validation and dependency/security checks.

Keep platform-specific code behind injected discovery and transport contracts.
Shared warranty and TSPL logic must not depend on CUPS, Windows spooler APIs, or
the default printer.
