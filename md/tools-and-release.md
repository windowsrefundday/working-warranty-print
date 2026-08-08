# Tools and public release

## Release audit

Run `python tools/release_audit.py` before committing or publishing. It rejects
runtime data, environment files, local paths, secret-like values,
non-synthetic warranty identifiers, unapproved binary files, and workflow
actions that are not pinned to immutable revisions.

## Source-checkout updater

The application uses a deliberately small source-checkout updater. At startup,
and then every six hours while the application is running, it fetches
`origin/main` and applies only a fast-forward update. It refuses failed fetches,
diverged history, and failed merges; it never resets local work or performs a
merge. Set `WARRANTY_LABEL_DISABLE_AUTO_UPDATE=1` to skip the startup and
background updater.

This updater changes the checkout for the next process start. It does not
install dependencies, run migrations, restart the current process, or replace
the source checkout with a staged release. Those operations remain explicit
operator/deployment responsibilities.

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
