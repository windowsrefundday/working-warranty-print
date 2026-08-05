# Warranty vendors

Vendor plugins are responsible for obtaining authoritative warranty evidence.
They must never fabricate a record when a portal is unavailable, incomplete,
or returns data for a different serial number.

## Current paths

- HP uses the browser worker and portal parser in `core/vendors/hp_worker.py`,
  `hp_parser.py`, and `hp.py`.
- Lenovo uses the browser worker and structured/text parsers in the Lenovo
  modules.
- Dell, Apple, and generic paths fail closed when no verified lookup is
  implemented.

Each verified result must contain matching serial data, model information,
warranty status, dates, and source confidence. Synthetic fixtures are allowed
only for tests and must be clearly synthetic.

For a new vendor, follow [`../core/vendors/VENDOR_GUIDE.md`](../core/vendors/VENDOR_GUIDE.md),
add parser and failure tests, register the plugin through composition, and do
not add an internal fallback registry.
