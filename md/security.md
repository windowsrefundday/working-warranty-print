# Security practices

Treat serial numbers, warranty responses, pairing tokens, CSV exports, labels,
logs, printer bindings, and caches as sensitive operational data.

- Keep runtime data in the per-user data directory.
- Use the secure QR pairing flow for remote phone access.
- Do not port-forward the dashboard or share pairing links publicly.
- Preserve input bounds, output escaping, no-store headers, throttling, and
  fail-closed printing.
- Use synthetic identifiers in tests and documentation.
- Report vulnerabilities privately through [`../SECURITY.md`](../SECURITY.md),
  not a public issue.

This documentation describes project controls; it is not a guarantee that a
deployment is safe on an untrusted network. Operators remain responsible for
firewall, tunnel-provider, device, and data-retention decisions.
