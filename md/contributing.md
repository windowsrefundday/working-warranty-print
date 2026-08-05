# Contributing

## Before changing code

Read [`../AGENTS.md`](../AGENTS.md) and the documentation page for the area you
will change. Keep changes focused and preserve the repository's fail-closed
behavior.

## Development rules

- Use four-space Python indentation, type annotations, and explicit imports.
- Put platform-specific behavior behind injected adapters.
- Add or update `unittest` coverage for success and failure paths.
- Do not run physical-printer tests or commit runtime data.
- Do not modify `--update-engines` as part of unrelated hardening work.

## Pull requests

Use a descriptive branch and an imperative commit message. The pull request
should explain behavior and safety impact, list local and GitHub checks, and
identify any intentionally deferred work. Keep credentials, real serials,
vendor exports, logs, screenshots with sensitive data, `.env` files, caches,
and generated labels out of the branch.

Run the checks in [`tests.md`](tests.md) before requesting review. A change is
not ready until the required macOS, Windows, Python analysis, Dependency
Review, and Actionlint checks pass.
