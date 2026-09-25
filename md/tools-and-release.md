# Tools and public release

## Release audit

Run `python tools/release_audit.py` before committing or publishing. It rejects
runtime data, environment files, local paths, secret-like values,
non-synthetic warranty identifiers, unapproved binary files, and workflow
actions that are not pinned to immutable revisions.

## Source-checkout updater

`updater.py` is a self-healing source-checkout updater. It imports only the
standard library, and `main.py` runs it before importing any application
module, so a broken application commit cannot stop the next fix from arriving.

At startup it fetches `origin/main` and applies only a fast-forward update. It
refuses failed fetches and diverged history, and never creates merge commits or
discards local work. After a fast-forward:

1. If `requirements.txt` or `requirements-windows.txt` changed, it installs the
   platform requirements file into the running interpreter's environment, then
   tries `playwright install chromium` (optional; Edge/Chrome are preferred).
2. It runs `main.py --self-test`, which imports every application module.
3. If the install or self-test fails, it returns to the previous commit with
   `git reset --keep` and reinstalls the previous requirements. A commit that
   fails its self-test is recorded in `.git/warranty-updater.json` and never
   retried; a failed install (for example, a blocked network) is retried on the
   next start.

While the application runs, a background thread checks every six hours and
applies only code-only updates; dependency changes wait for the next start.
The updated code takes effect on the next start. The startup banner prints the
running commit (`Version: <sha> (<date>)`) so operators can report it.

`main.py --self-test` is part of the update contract: every future `main.py`
must keep it working, or clients will refuse the update. Set
`WARRANTY_LABEL_DISABLE_AUTO_UPDATE=1` to skip the updater.

## History and visibility

The working tree audit is not a history scrub. Before publishing a repository
that previously contained sensitive data:

1. Keep the source repository private while creating a fresh backup mirror.
2. Build an uncommitted replacement map and rewrite every reachable ref.
3. Verify the rewritten history from fresh clones, including hidden refs and
   tags.
4. Confirm no serials, warranty exports, credentials, caches, labels, local
   paths, or environment files remain.
5. Apply branch protection and security settings.
6. Change visibility only after the fresh-clone release gate passes.

Never place replacement maps, raw vendor responses, operational labels, or
credentials in the repository.
