# Tools and public release

## Release audit

Run `python tools/release_audit.py` before committing or publishing. It rejects
runtime data, environment files, local paths, secret-like values,
non-synthetic warranty identifiers, unapproved binary files, and workflow
actions that are not pinned to immutable revisions.

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
