# Tools and public release

## Release audit

Run `python tools/release_audit.py` before committing or publishing. It rejects
runtime data, environment files, local paths, secret-like values,
non-synthetic warranty identifiers, unapproved binary files, and workflow
actions that are not pinned to immutable revisions.

## Application release contract

Managed artifacts are ZIP files containing `release.json`, `app/`, a copied
Python runtime, and (when available) a bundled browser runtime. Build them with
`tools/package_release.py` and produce signed `update-manifest.json` metadata
with `tools/sign_manifest.py`. The manifest uses Ed25519 signatures, explicit
platform targets, bounded artifact sizes, SHA-256 digests, expiry timestamps,
and a minimum launcher version.

The workflow downloads a versioned python-build-standalone archive for each
platform, verifies its pinned SHA-256 digest before extraction, and packages
that relocatable runtime. `tools/verify_release.py` re-verifies the signed
manifest and every local artifact before the draft release is published.

The signing private key must remain outside the repository and be injected only
through the protected `release` GitHub Environment after reviewer approval.
The public key is pinned in
`tools/updater.py`; rotate it by overlapping old and new keys in a launcher
release. Before enabling the tag workflow, configure the
environment secret `UPDATE_SIGNING_KEY_B64` with the URL-safe Base64 encoding of exactly 32
raw Ed25519 private-key bytes (Base64 padding is optional) corresponding to the
pinned public key; the signer refuses a mismatched key. Publish artifacts first
and promote the signed manifest only after clean Windows and macOS packaging,
signature verification, and installation checks pass.

The source-checkout launcher retains its existing git-pull update behavior.
Managed ZIP artifacts and their signed manifest are a separate release channel;
do not silently switch an installation between these channels or mutate a
managed artifact's bundled `.venv` in place.

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
