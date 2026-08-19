# TASK-2266: Demote `published_version` from visibility gate to per-row label

**Feature**: FEAT-433 — Form Version History — repair the read path
**Spec**: `sdd/specs/form-version-history-repair.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2265
**Assigned-to**: unassigned

---

## Context

Spec Module 3, and the heart of the feature. `list_versions` drops any row
whose `published_version != version`; only `publish()` ever stamps that
field, and the editor does not call `publish()`, so 105 of 105 measured
rows are discarded.

**Read spec §0 (D1–D3) before starting.** The maintainer decision is that
the draft/published distinction is KEPT. This task does **not** retire the
comparison — it changes what the comparison decides: from *whether a row
is visible* to *how a row is labelled*.

---

## Scope

- `list_versions` stops using `published_version == version` to drop rows.
  Every stored row becomes a `VersionMeta`.
- The same comparison now labels: `is_published = (published_version ==
  version)`, and `is_frozen = is_published`. **One helper, one place** —
  put it next to `_parse_major_minor` so the two derivation rules live
  together.
- `published_at` per row: the `meta.published_at` stamp when present,
  otherwise the row's `created_at`. Keep `_published_at_from_snapshot`'s
  precedence but feed it the projected columns.
  **Do not fall back to `datetime.now()`** — that makes every draft report
  "published just now" and the history UI renders a wall of identical
  timestamps.
- `VersionMeta` gains `is_published` and stops hardcoding `is_frozen=True`.
- The handler emits the new `is_published` key. `is_current` keeps its
  existing rule (`form.published_version or form.version`).
- Rewrite the test assertions that encoded the bug (see below).

**NOT in scope**: `get_published()` (TASK-2268), the immutability guard
(TASK-2269), any UI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../services/form_version.py` | MODIFY | label helper, `VersionMeta`, `list_versions`, `published_at` precedence |
| `.../api/handlers.py` | MODIFY | emit `is_published` (`:1936-1941`) |
| `packages/parrot-formdesigner/tests/unit/test_form_version.py` | MODIFY | label tests |
| `packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py` | MODIFY | rewrite invisibility assertions |
| `packages/parrot-formdesigner/tests/unit/test_api_feat300.py` | MODIFY | response-shape tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/form_version.py
class VersionMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")   # ← adding a field means updating callers
    form_id: str
    version: str
    published_at: datetime
    tenant: str
    is_frozen: bool = True                      # ← stops being a constant
def _parse_major_minor(version: str) -> tuple[int, int]: ...    # line 69  ← put the label helper here
    @staticmethod
    def _published_at_from_snapshot(snap) -> datetime: ...      # keep precedence, drop the now() fallback

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
        current_version = form.published_version or form.version   # line 1931  ← unchanged
        return web.json_response({... "versions": [...]})          # lines 1936-1941 ← add is_published
```

### Does NOT Exist
- ~~`form_schemas.is_published` / `is_draft`~~ — no such columns; the label
  is **derived** per spec D2, never stored
- ~~a migration for this task~~ — the table is untouched

---

## Implementation Notes

### Key Constraints
- `VersionMeta` is `extra="forbid"`; adding `is_published` requires every
  construction site to be updated in the same change.
- **`is_current` and `is_published` are independent** (spec §1.1 item 4).
  The newest row is normally a *current draft*; the newest published row
  is normally *older*. Do not collapse them, and do not derive one from
  the other.
- Storage row wins over a `_meta` echo on conflict (TASK-2265's rule) —
  the row's `published_version` decides the label.

### Blast radius (spec §8 Q3 — mechanical, escalate on ambiguity)
40 `published_version` references live in the test suite. Classify each:
- asserts an **unpublished row is invisible** → encoded the bug; rewrite
  to assert `is_published is False` instead of absence;
- asserts **`publish()` stamps the field**, or that a published snapshot
  is immutable → real requirement, must stay green.
Raise it only if a reference resists this classification.

---

## Acceptance Criteria

- [ ] Rows written by the editor path (`_bump_version` + `storage.save`,
      no `publish()` anywhere in the fixture) appear in the listing
- [ ] Those rows are labelled `is_published is False` / `is_frozen is False`
- [ ] A row written by `publish()` is labelled `is_published is True`
- [ ] A draft's `published_at` equals its stored `created_at` — never
      wall-clock now
- [ ] The newest row can be `is_current=True, is_published=False` while an
      older row is `is_current=False, is_published=True`
- [ ] The endpoint response carries `is_published` per entry
- [ ] `pytest packages/parrot-formdesigner/tests/ -v` passes

---

## Test Specification

```python
async def test_editor_saved_rows_are_labelled_draft(...): ...
async def test_published_rows_are_labelled_published(...): ...
async def test_draft_and_published_coexist_in_one_history(...): ...
async def test_is_current_independent_of_is_published(...): ...
async def test_draft_published_at_is_not_now(...): ...
```

Use the `form_with_mixed_history` fixture from spec §4 — it writes through
**both** real writers on purpose; a fixture that uses only one of them is
exactly how the original defect stayed invisible.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any
