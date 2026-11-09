# TASK-5384: Scan-aware `SegmentStore.save_revision` + tests

**Feature**: FEAT-850 — SegmentStore revision replacement on scan upgrade
**Spec**: `sdd/specs/pageindex-segment-store-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:fa6a5f71a22f`

---

## Context

Implements spec §3 Module 1. `save_revision` skips writing when the file exists,
losing injection flags when an unscanned import precedes a scanned one.

## Scope

- In `segment_store.py`, make `save_revision` read an existing file and replace it
  atomically (evicting the cache entry) iff `rev.scored_by is not None` and the scan
  state `(scored_by, per-segment flags/injection)` differs, or the file is unreadable.
  Identical or unscanned incoming → untouched (mtime unchanged).
- Update the docstring. Add the five tests of spec §4 to `test_segment_store.py`.

**NOT in scope**: `revision_id()`, `generation.py`, file naming.

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py` (MODIFY)
- `packages/ai-parrot/tests/knowledge/pageindex/test_segment_store.py` (MODIFY)

## Codebase Contract

### Verified Imports
```python
from parrot.knowledge.pageindex.content_store import _atomic_write
from parrot.knowledge.pageindex.segments import DocumentRevision
```
### Existing Signatures
```python
def save_revision(self, tree_name: str, rev: DocumentRevision) -> Path   # segment_store.py
def _cache_evict(self, key: tuple[str, str, str]) -> None
```
Test helper `_rev(doc_id="d", text="Hello.")` exists in the test file; `segment_pages`, `revision_id`, `SourceInfo` already imported there.
### Does NOT Exist
- ~~`SegmentStore.replace_revision`~~

## Implementation Notes

Anchor: `        if not path.is_file():` inside `save_revision` (1 occurrence). Catch
`(OSError, ValueError)` (pydantic `ValidationError` is a `ValueError`) when reading the existing file.
Flag a segment in tests via `rev.segments[0].flags = ["injection"]`.

## Acceptance Criteria

- [ ] Spec §4 tests pass; existing `test_segment_store.py` and `test_generation.py` pass.
- [ ] `ruff check` clean on both files.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_store.py packages/ai-parrot/tests/knowledge/pageindex/test_generation.py -q
ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py packages/ai-parrot/tests/knowledge/pageindex/test_segment_store.py
```

## Test Specification

See spec §4.

## Agent Instructions

Implement exactly the above; close with `parrot sdd task close TASK-5384 pageindex-segment-store-fixes verified`.

## Completion Note

Implemented as specified: `save_revision` replaces an existing file atomically (cache evicted) only when the incoming revision is scanned and its scan state differs or the file is unreadable. 6 new tests; 34 pass with test_generation.py; ruff clean. Commit db7c30ed7c.
