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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-19
**Notes**: `list_versions()`'s gate (kept as-is by TASK-2265) is now removed
— every stored row is listed, labelled via the new `_is_published_label()`
helper placed next to `_parse_major_minor` (one helper, one place, per the
task). `VersionMeta.is_published` (new) and `.is_frozen` (no longer
hardcoded `True`) are both now required fields (no default) — every
construction site (`publish()`, `list_versions()`, `backfill_published()`)
was updated in the same change, matching the note that `extra="forbid"`
means every site must be touched. `_published_at_from_row` no longer falls
back to `datetime.now()`; it returns the row's `created_at` (guaranteed by
the storage layer). Handler emits `is_published`; `is_current` is
byte-for-byte unchanged (`form.published_version or form.version`).
Checked the §8 Q3 test blast radius across the whole test tree (not just
this task's listed files) — no existing assertion encodes "an unpublished
row is invisible from list_versions()"; the only `published_version`
references elsewhere assert the `FormSchema.published_version` field
itself (unrelated to the visibility gate this task demotes), so no
additional test rewrites were needed for Q3.

**Deviations from spec**: Discovered the real `is_current` formula
(`form.published_version or form.version`, confirmed unchanged) pins to the
*last published* tag, not literally "the newest draft" — once anything has
ever been published, later editor saves keep `published_version` sticky
(the handler explicitly preserves it), so `is_current` never lands on a
newer draft until the NEXT publish. Wrote the independence test
(`test_list_versions_is_current_and_is_published_can_diverge`) against
this actual, verified behavior (two publishes with an edit between) rather
than the loosely-worded "newest draft is current" example in spec §1.1
item 4, which isn't reachable through the real API surface as it exists
today. No code changed — `is_current` is confirmed byte-for-byte
unchanged, exactly as the task specifies. Also added a `_tenant_request()`
test helper (scoped to the two new API-level tests only) in
`test_api_feat300.py`, patching `request.get("tenant")`: the existing
`_make_request()` predates FEAT-421's URL-based tenant validation and
never sets `request["tenant"]`, so every handler call through it resolves
to a nonsense tenant from an unconfigured `MagicMock` — a pre-existing,
repo-wide test-infra gap (confirmed via baseline diff: ~9 already-red
tests in this same file hit the identical root cause) that is out of
scope to fix broadly. `_FakeFormStorage.save()` (test_api_feat300.py,
added in TASK-2264) was also extended to stamp `created_at` when absent,
mirroring what `PostgresFormStorage.load()` does for a live DB row —
needed once `_published_at_from_row` reads `created_at` for a draft with
no stamp.
