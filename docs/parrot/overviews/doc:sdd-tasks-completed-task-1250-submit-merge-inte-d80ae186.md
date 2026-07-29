---
type: Wiki Overview
title: 'TASK-1250: Submit Merge Integration (?merge_partials)'
id: doc:sdd-tasks-completed-task-1250-submit-merge-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task extends the existing `submit_data()` handler to optionally merge
---

# TASK-1250: Submit Merge Integration (?merge_partials)

**Feature**: FEAT-186 — FormDesigner Partial Saves
**Spec**: `sdd/specs/formdesigner-partial-saves.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1248, TASK-1249
**Assigned-to**: unassigned

---

## Context

This task extends the existing `submit_data()` handler to optionally merge
cached partial answers into the final submission (Spec §2 API Contracts,
§3 Module 4). When `?merge_partials=true` is set, the backend loads cached
partials and merges them under the submitted payload before validation.

---

## Scope

- Modify `FormAPIHandler.submit_data()` to:
  - Read `merge_partials` query param from `request.query.get("merge_partials")`
  - When `"true"` and `self._partial_store` is configured:
    1. Extract session_id from request
    2. Load cached partial via `self._partial_store.get(form_id, session_id)`
    3. Merge: `merged = {**cached_partial.data, **submitted_data}` (submitted wins)
    4. Use `merged` as the validation/submission payload
  - After successful submission (stored + forwarded), delete the cached partial
- Default behavior (`merge_partials` absent or false) is UNCHANGED
- Write unit tests for the merge path

**NOT in scope**: Creating new endpoints (TASK-1249), route registration (TASK-1251).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Extend `submit_data()` with merge logic |
| `packages/parrot-formdesigner/tests/test_submit_merge.py` | CREATE | Tests for merge path |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported/available in handlers.py after TASK-1249
from ..services.partial_saves import PartialSaveStore  # TASK-1248
```

### Existing Signatures to Use
```python
# api/handlers.py:566-648 — current submit_data implementation
async def submit_data(self, request: web.Request) -> web.Response:
    form_id = request.match_info["form_id"]  # line 583
    form = await self.registry.get(form_id)  # line 584
    data = await request.json()  # line 591
    result = await self.validator.validate(form, data)  # line 596
    # ... builds FormSubmission, stores, forwards

# PartialSaveStore (from TASK-1248)
async def get(self, form_id: str, session_id: str) -> PartialFormData | None:
async def delete(self, form_id: str, session_id: str) -> bool:

# aiohttp query params
request.query.get("merge_partials")  # returns str | None
```

### Does NOT Exist
- ~~`request.query.get("merge_partials", default=False)`~~ — returns str not bool; must compare to `"true"`
- ~~`FormAPIHandler.merge_partial_data()`~~ — no such method exists; merge inline in submit_data

---

## Implementation Notes

### Pattern to Follow
```python
# Insert merge logic AFTER parsing JSON body, BEFORE validation
# in submit_data() around line 594

merge_partials = request.query.get("merge_partials", "").lower() == "true"

if merge_partials and self._partial_store is not None:
    session_id = self._extract_session_id(request)
    if session_id:
        cached = await self._partial_store.get(form_id, session_id)
        if cached:
            data = {**cached.data, **data}  # submitted values override cached
```

### Key Constraints
- If `merge_partials` is not `"true"`, skip entirely — zero behavior change
- If `self._partial_store is None`, skip merge silently (no 503 — submit still works)
- If no cached partial exists, proceed with submitted data only (no error)
- Delete cached partial AFTER successful storage/forwarding, not before
- Session extraction should use the same helper method added in TASK-1249

---

## Acceptance Criteria

- [ ] `submit_data()` reads `?merge_partials=true` query param
- [ ] When true, merges cached partial data under submitted data
- [ ] Submitted values override cached values (last-write-wins)
- [ ] After successful submit, cached partial is deleted
- [ ] Default behavior (no merge_partials param) is unchanged
- [ ] If partial_store is None, merge is silently skipped
- [ ] If no cached partial exists, proceeds normally
- [ ] Unit tests pass: `pytest packages/parrot-formdesigner/tests/test_submit_merge.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/test_submit_merge.py
import pytest


class TestSubmitMergePartials:
    async def test_merge_combines_cached_and_submitted(self):
        """Cached partial merged with submitted data."""
        ...

    async def test_merge_submitted_overrides_cached(self):
        """Submitted values take precedence over cached."""
        ...

    async def test_merge_cleanup_after_submit(self):
        """Cached partial deleted after successful submit."""
        ...

    async def test_no_merge_flag_unchanged(self):
        """Without ?merge_partials=true, behavior is identical."""
        ...

    async def test_merge_no_cached_data(self):
        """Merge with no cached partial proceeds normally."""
        ...

    async def test_merge_no_store_configured(self):
        """If partial_store is None, merge is skipped silently."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-partial-saves.spec.md` §2 last API contract
2. **Check dependencies** — verify TASK-1248 and TASK-1249 are complete
3. **Read `api/handlers.py:566-648`** — understand current submit_data flow
4. **Insert merge logic** between JSON parsing and validation
5. **Run ALL existing submit tests** to ensure no regression
6. **Run new tests**: `pytest packages/parrot-formdesigner/tests/test_submit_merge.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-05-19
**Notes**: Extended `submit_data()` in `api/handlers.py` to read `?merge_partials=true`
query param. When set, loads cached partial from `_partial_store`, merges it into the
submitted data (submitted values win), then deletes the cached partial after successful
submission. 9 unit tests all pass.

**Deviations from spec**: Cleanup (delete) runs regardless of whether cached data was
found (idempotent — harmless when nothing exists). This is simpler and equally correct.

**Deviations from spec**: none (regarding specified behavior)
