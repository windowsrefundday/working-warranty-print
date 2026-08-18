## Summary

Describe the behavior changed, the safety impact, and any operator-visible
effect. Link the relevant issue when one exists.

## Safety checklist

- [ ] This change does not add credentials, `.env` files, local printer
      bindings, caches, generated labels, or `.venv` content.
- [ ] Physical printing, calibration, and setup-time test jobs remain disabled
      unless the pull request explicitly documents authorized hardware testing.
- [ ] Printer output keeps explicit queue selection, RAW TSPL submission,
      one-copy enforcement, and fail-safe virtual output.
- [ ] No default-printer fallback, ambiguous automatic retry, or admin-only
      bypass was introduced.
- [ ] Warranty data remains verified or fails closed; no plausible fallback
      values are fabricated.

## Validation checklist

- [ ] `python -m unittest discover -s tests -v`
- [ ] `python tools/release_audit.py`
- [ ] `python -m compileall -q core interfaces main.py tests`
- [ ] `npx pyright`
- [ ] macOS matrix job passed: `test (macos-latest)`
- [ ] Windows matrix job passed: `test (windows-latest)`
- [ ] CodeQL, Dependency Review, Actionlint, and Zizmor completed as expected.
- [ ] CodeRabbit and Greptile feedback was reviewed, or the reason either bot
      did not run is documented.

## Release impact

- [ ] Not release-related.
- [ ] Release-related: signing, artifact contents, rollback/installation checks,
      and required secrets are described below.

Release notes and platform-specific evidence:
