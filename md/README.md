# Repository documentation

This folder explains how the repository is organized, how its interfaces fit
together, and how changes move through testing and release checks.

## Start here

- [`../README.md`](../README.md) — user setup and operating instructions.
- [`../AGENTS.md`](../AGENTS.md) — rules for agents and contributors working
  in this repository.
- [`../SECURITY.md`](../SECURITY.md) — private vulnerability reporting.

## Repository areas

- [`architecture.md`](architecture.md) — boundaries and data flow.
- [`core.md`](core.md) — domain engine, models, cache, rendering, and
  composition.
- [`vendors.md`](vendors.md) — live warranty lookup plugins and fail-closed
  behavior.
- [`printers.md`](printers.md) — printer connectors, profiles, and safe output.
- [`interfaces.md`](interfaces.md) — CLI, web dashboard, scanner, and plugins.
- [`operations.md`](operations.md) — setup, diagnostics, runtime modes, and
  runtime data.
- [`security.md`](security.md) — operational security practices and data
  handling.
- [`tests.md`](tests.md) — test organization and validation commands.
- [`bots.md`](bots.md) — GitHub Actions, dependency automation, and required
  checks.
- [`tools-and-release.md`](tools-and-release.md) — release auditing and
  public-release controls.
- [`contributing.md`](contributing.md) — branch, review, and contribution
  workflow.

Detailed extension guides remain next to the code they describe:

- [`../core/vendors/VENDOR_GUIDE.md`](../core/vendors/VENDOR_GUIDE.md)
- [`../core/printers/CONNECTOR_GUIDE.md`](../core/printers/CONNECTOR_GUIDE.md)
