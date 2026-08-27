# TASK-2501: Add regression test for long-key truncation branch

**Feature**: fix-weak-sha1-arango-store
**Feature-ID**: FEAT-465
**Spec**: sdd/specs/fix-weak-sha1-arango-store.spec.md
**Status**: [ ] pending | [ ] in-progress | [x] done
**Priority**: medium
**Depends-on**: TASK-2500
**Assigned-to**: unassigned

## Context

The `document_key()` function has two branches:
1. Short identity → percent-encode and return directly.
2. Long identity (> `_KEY_MAX_BYTES` bytes) → trim + append a 16-hex-char digest.

The existing test suite covers branch 1 but has no explicit assertion that
branch 2 produces a digest from SHA-256 (not SHA-1). Add a regression test
that covers branch 2 and validates the digest algorithm.

## Scope

Add one or two test functions to `tests/knowledge/wiki/test_arango_store.py`
(or a dedicated `test_document_key.py` if the existing file is ArangoDB-live).

## Files to Modify / Create

- `tests/knowledge/wiki/test_arango_store.py` — add test(s) OR
- `tests/knowledge/wiki/test_document_key.py` — new file (pure unit, no DB)

## Implementation Notes

```python
from parrot.knowledge.wiki.arango_store import document_key, _KEY_MAX_BYTES
import hashlib

def test_document_key_long_identity_uses_sha256():
    """Long identity falls back to truncated-with-digest form; digest is SHA-256."""
    # Build an identity guaranteed to exceed _KEY_MAX_BYTES after percent-encoding
    long_id = "a" * 300
    key = document_key(long_id)
    # Key must end with '$' + 16 hex chars (the digest separator + truncated digest)
    assert "$" in key, "Expected digest separator '$' in long-key output"
    digest_part = key.rsplit("$", 1)[-1]
    assert len(digest_part) == 16, f"Expected 16-char digest, got {len(digest_part)}"
    # The 16-char prefix must match the first 16 chars of SHA-256, not SHA-1
    expected_sha256_prefix = hashlib.sha256(long_id.encode()).hexdigest()[:16]
    expected_sha1_prefix   = hashlib.sha1(long_id.encode()).hexdigest()[:16]
    assert digest_part == expected_sha256_prefix, (
        f"Digest {digest_part!r} does not match SHA-256 prefix "
        f"{expected_sha256_prefix!r}; SHA-1 prefix would be {expected_sha1_prefix!r}"
    )
```

## Acceptance Criteria

- [ ] Test `test_document_key_long_identity_uses_sha256` is added and passes after TASK-2500
- [ ] The test explicitly asserts SHA-256 prefix, NOT SHA-1
- [ ] `pytest tests/knowledge/wiki/ -q` exits 0

## Output

When complete, move to `sdd/tasks/completed/` and update the feature index status to "done".

### Completion Note

Created `tests/knowledge/wiki/test_document_key.py` — a pure-unit test file
(no ArangoDB server required). 7 tests including
`test_document_key_long_identity_uses_sha256` which explicitly asserts
the SHA-256 prefix and confirms it differs from SHA-1. All 7 pass.
