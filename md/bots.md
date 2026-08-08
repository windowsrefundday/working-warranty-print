# Bots and automated checks

The repository uses GitHub automation for validation and supply-chain review.
Actions are pinned to full commit SHAs, and workflows use least-privilege
permissions.

## Required checks on `main`

- `test (macos-latest)` and `test (windows-latest)` — full cross-platform
  setup, audits, tests, compilation, type checking, and diagnostics.
- `Analyze Python` — CodeQL Python analysis.
- `Dependency review` — pull-request dependency changes; blocks newly
  introduced high-severity vulnerabilities.
- `Actionlint` — workflow syntax and expression validation.

## Advisory or scheduled checks

- CodeQL JavaScript/TypeScript detection skips cleanly when no matching files
  are tracked.
- OpenSSF Scorecard runs on `main` pushes and weekly, publishing SARIF.
- Zizmor runs on pushes and the weekly schedule and reports workflow-security
  findings to code scanning.
- Dependabot checks pip, npm, and GitHub Actions dependencies weekly.
- CodeRabbit is an external pull-request reviewer; draft pull requests may be
  skipped by that integration.
- Greptile is an external pull-request reviewer and confidence check; it runs
  through its GitHub App installation rather than a tracked workflow file.

CodeRabbit and Greptile are repository integrations. Their GitHub App access
must include this repository; workflow files alone cannot install or authorize
either bot.

The tag-driven release workflow builds platform-specific managed artifacts,
including a copied Python runtime, and signs the update manifest with the
protected release key. It must keep release publication separate from ordinary
read-only verification, require approval through the protected `release`
environment, and may not publish metadata until packaging, signature, artifact,
and installation checks pass.

Do not add secrets, broad write permissions, mutable action tags, or silent
remote code installation to a workflow. Update `tools/release_audit.py` tests
when introducing a new workflow reference pattern.
