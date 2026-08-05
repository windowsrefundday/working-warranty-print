# Printer subsystem

The printer subsystem separates discovery, validation, formatting, and raw
transport. The normal safe output is the virtual file connector; physical
output requires an explicitly configured and revalidated TSC MB341 queue.

## Safety invariants

- Use the locked 300-dpi, 3 × 1 inch profile for the approved MB341 media.
- Require the selected queue, make/model, USB identity, resolution, and ready
  state immediately before submission.
- Submit exactly one raw TSPL job with no automatic retry or default-printer
  fallback.
- Refuse unverified or stale warranty data before a physical print.
- Keep setup, diagnostics, and automated tests from printing or calibrating.

Platform adapters belong in `core/application/composition.py`. CUPS and Windows
spooler implementations satisfy the same connector and transport contracts.

For a connector implementation, see
[`../core/printers/CONNECTOR_GUIDE.md`](../core/printers/CONNECTOR_GUIDE.md).
