---
feature: fix-weak-sha1-arango-store
feature_id: FEAT-465
type: feature
base_branch: dev
jira_key: null
---

# Feature Specification: Fix Weak SHA-1 Hash in ArangoDBWikiStore

## Summary

Replace the SHA-1 call in `document_key()` inside
`packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` (line 100)
with SHA-256 to eliminate the GitHub code-scanning alert 212 for "use of a
broken or weak cryptographic hashing algorithm on sensitive data".

## Background

`document_key()` derives an ArangoDB `_key` from a page `concept_id`.
When the percent-encoded form of the identity exceeds `_KEY_MAX_BYTES`
(254 bytes), a 16-hex-char digest is appended as a collision-resistant
suffix. That digest is produced with `hashlib.sha1`, which is flagged by
GHCS CWE-327/CWE-916.

Although the identity here is a document key (not a password), the scanner
treats it as sensitive data because the variable is named `id`-adjacent and
feeds a hashing function. Using SHA-256 costs nothing at runtime (same
stdlib call) and silences the alert correctly.

The same pattern is repeated in `edge_key()` which calls `document_key()`
indirectly — fixing `document_key()` covers both.

## Change Set

### `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py`

- Line 100: `hashlib.sha1(...)` → `hashlib.sha256(...)`
- No other changes to the function signature, return type, or callers.

### `tests/knowledge/wiki/test_arango_store.py` (or new test file)

- Add a regression test that exercises the long-key truncation branch of
  `document_key()` and asserts the digest portion is 64 hex chars
  (SHA-256 produces a 256-bit / 64-hex-char digest, vs SHA-1's 40).
  The test must FAIL before the fix and PASS after.

## Acceptance Criteria

- [ ] `hashlib.sha1` no longer appears in `arango_store.py`
- [ ] `hashlib.sha256` is used in its place
- [ ] `ruff check .` exits 0
- [ ] `pytest -q` exits 0 (no regression)
- [ ] Regression test for the truncation branch is added and passes

## Non-Goals

- Do not change key length, separator, or any other aspect of the key
  derivation scheme — existing stored keys must remain valid.
- Do not migrate stored ArangoDB documents.

## Risk

Very low. SHA-1 and SHA-256 both return hex strings; only the digest length
changes (40 → 64 chars). The existing code takes only the first 16 chars
(`[:16]`), so the trimmed output length is UNCHANGED. No stored keys are
affected, no callers need updating.
