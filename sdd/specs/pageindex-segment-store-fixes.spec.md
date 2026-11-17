---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [pageindex, segment-store, injection-scan, ledger-fix]
---

# Feature Specification: SegmentStore revision replacement on scan upgrade

**Feature ID**: FEAT-850
**Date**: 2026-11-09
**Author**: Jesus Lara (via /sdd-fix)
**Status**: approved
**Target version**: next minor

**Ledger origin**: `issue:fa6a5f71a22f` — *Revision file never replaced: earlier
unscanned import shadows later scanned one* (kind `bug`, severity `major`,
discovered from `spec:FEAT-840`). Plan group `fixgroup:a1e050e6931d`, lane `sdd`.

---

## 1. Motivation & Business Requirements

### Problem Statement

`SegmentStore.save_revision` (`packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py`)
is a no-op when `<doc_id>.<revision>.json` already exists. `revision_id()` hashes
only segment texts, so re-importing identical text with `scan_injection=True`
after an import with scanning off (or with another engine/threshold) keeps the
old file: `scored_by=None`, no per-segment `flags`/`injection`. Injection flags
are silently lost.

### Goals

- G1: A revision saved with scan results that differ from the stored file's
  replaces it atomically (and the LRU entry is evicted).
- G2: An unscanned revision (`scored_by is None`) never overwrites a scanned one.
- G3: Saving an identical revision stays a true no-op (mtime unchanged).

### Non-Goals

- Changing `revision_id()` or the on-disk file naming.
- Changing generation publication in `generation.py` (it keeps calling `save_revision`).

---

## 2. Architectural Design

Single-file change. On collision `save_revision` reads the existing file
(`DocumentRevision.model_validate_json`); an unreadable/corrupt file is replaced.
Define "scan state" = `(scored_by, [(s.flags, s.injection) for s in segments])`.
Replace iff `rev.scored_by is not None` and the scan states differ. Replacement
uses `_atomic_write` and `_cache_evict((tree_name, doc_id, revision))`.

---

## 3. Module Breakdown

### Module 1: `save_revision` scan-aware collision handling
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py` (MODIFY);
  `packages/ai-parrot/tests/knowledge/pageindex/test_segment_store.py` (MODIFY)
- **Interface**: `def save_revision(self, tree_name: str, rev: DocumentRevision) -> Path`
  (signature unchanged; docstring updated).

---

## 4. Test Specification

| Test | Description |
|---|---|
| `test_save_revision_upgrades_unscanned_to_scanned` | save unscanned, then same-text scanned (`scored_by="regex"`, flagged segment): file and `load_revision` return flags |
| `test_save_revision_never_downgrades_scanned` | save scanned, then unscanned: stored file keeps flags |
| `test_save_revision_replaces_on_different_engine` | scanned by `regex` then by another engine: replaced |
| `test_save_revision_replace_evicts_cache` | `load_revision` before replace is not served stale after |
| `test_save_revision_replaces_corrupt_file` | garbage file at the path is overwritten |

Existing `test_save_revision_atomic_and_idempotent` must keep passing.

---

## 5. Acceptance Criteria

- [ ] AC1: the §4 tests pass, plus all of `packages/ai-parrot/tests/knowledge/pageindex/test_segment_store.py` and `test_generation.py`.
- [ ] AC2: `ruff check` clean on the two touched files.
- [ ] AC3: no public signature change.
- [ ] AC4: `issue:fa6a5f71a22f` closed with `--resolved-by task:TASK-5384`.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.knowledge.pageindex.content_store import _atomic_write   # segment_store.py:12
from parrot.knowledge.pageindex.segments import DocumentRevision     # segment_store.py:13
```

### Existing Signatures
```python
class SegmentStore:
    def save_revision(self, tree_name: str, rev: DocumentRevision) -> Path: ...   # segment_store.py:~55
    def _cache_evict(self, key: tuple[str, str, str]) -> None: ...
class DocumentRevision(BaseModel):  # segments.py:59
    scored_by: Optional[str]; segments: list[Segment]
class Segment(BaseModel):  # segments.py:~33
    flags: list[str]; injection: Optional[InjectionMark]
```
Caller: `generation.py:258` (`asyncio.to_thread(self._segments.save_revision, ...)`).

### Does NOT Exist
- ~~`SegmentStore.replace_revision`~~ / ~~a scan-config field in `revision_id()`~~.

---

## 7. Implementation Notes

Sync, no new imports beyond stdlib/pydantic already present; Google docstrings; 120 cols.
Concurrent `to_thread` saves of the same file are safe because `_atomic_write` replaces atomically.

## 8. Open Questions

None.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-11-09 | agent:sdd-fix | Initial spec from ledger issue fa6a5f71a22f |
