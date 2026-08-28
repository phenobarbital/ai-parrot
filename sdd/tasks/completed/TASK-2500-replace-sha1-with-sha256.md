# TASK-2500: Replace SHA-1 with SHA-256 in document_key()

**Feature**: fix-weak-sha1-arango-store
**Feature-ID**: FEAT-465
**Spec**: sdd/specs/fix-weak-sha1-arango-store.spec.md
**Status**: [ ] pending | [ ] in-progress | [x] done
**Priority**: high
**Depends-on**: none
**Assigned-to**: unassigned

## Context

GitHub code-scanning alert 212 flags `hashlib.sha1` in `document_key()`
(`packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py`, line 100)
as a weak/broken cryptographic hash. Although the hash is not used for
password storage, the scanner treats the `identity` argument as sensitive
because it names the page's `concept_id`.

SHA-256 is a drop-in replacement: same `hashlib` API, longer digest string
(but we only use `[:16]`, so output length is IDENTICAL).

## Scope

Single one-line change in `arango_store.py`. No API change, no migration.

## Files to Modify

- `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` — line 100

## Implementation Notes

```python
# BEFORE (line ~100)
digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]

# AFTER
digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
```

The `[:16]` slice means the output is still 16 hex chars regardless of
whether we use SHA-1 (40-char digest) or SHA-256 (64-char digest).
All existing stored ArangoDB `_key` values that were derived from identities
shorter than `_KEY_MAX_BYTES` are unaffected (they never go through this
branch). For identities that do exceed the limit, this is a new deployment
so keys were never persisted in production with the old hash.

## Acceptance Criteria

- [ ] `hashlib.sha1` no longer appears anywhere in `arango_store.py`
- [ ] `hashlib.sha256` is used in `document_key()` for the fallback digest
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` exits 0
- [ ] `pytest tests/knowledge/wiki/ -q` exits 0

## Output

When complete, move to `sdd/tasks/completed/` and update the feature index status to "done".

### Completion Note

Replaced `hashlib.sha1` with `hashlib.sha256` on line 100 of
`packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py`.
The `[:16]` slice keeps output length identical (16 hex chars).
`ruff check --select S` passes with no security violations.
