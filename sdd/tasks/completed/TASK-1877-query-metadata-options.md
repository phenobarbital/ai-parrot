# TASK-1877: Carry `form_metadata.options` through query + metadata index

**Feature**: FEAT-325 — NetworkNinja Importer — Select Options from `form_metadata`
**Spec**: `sdd/specs/networkninja-metadata-select-options.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Root cause link 1 & 2 of FEAT-325 (spec §1, §3 Module 1): `_FORM_QUERY` never
selects `m.options`, and `_build_metadata_index` never stores it. Every later
stage is blind to the canonical option catalog because of these two omissions.
This task makes the options data available to the rest of the pipeline; it does
not yet consume them.

---

## Scope

- Add `'options', m.options` to the `jsonb_build_object(...)` inside `_FORM_QUERY`
  so the aggregated `metadata` array carries each column's options.
- In `_build_metadata_index`, store the raw `options` list on each column record
  (default to `[]` when null/absent).

**NOT in scope**: consuming the options (TASK-1878), condition re-indexing
(TASK-1879), report provenance (TASK-1880), tests beyond a smoke check
(TASK-1881 owns the full test matrix).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/networkninja.py` | MODIFY | `_FORM_QUERY` (lines 28–43) + `_build_metadata_index` (lines 449–469) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No new imports required for this task.
```

### Existing Signatures to Use
```python
# networkninja.py:28-43  — the SQL string (jsonb_build_object at lines 33-36)
_FORM_QUERY = """... jsonb_build_object(
    'column_id', m.column_id, 'column_name', m.column_name,
    'description', m.description, 'data_type', m.data_type
) AS metadata ... FROM networkninja.forms f
JOIN networkninja.form_metadata m USING(formid) ..."""

# networkninja.py:449
def _build_metadata_index(self, raw_metadata: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    # currently stores column_id / data_type / description per column (lines 464-468)
```

### Verified source shape (staging navigator_staging, 2026-07-23)
```json
{"is_active": true, "option_id": "6091", "column_name": 10211, "option_value": "Field Merchandiser"}
```
`networkninja.form_metadata.options` is a `jsonb` column (may be `null`).

### Does NOT Exist
- ~~`m.options` in `_FORM_QUERY` today~~ — this task adds it
- ~~`options` key in the `_build_metadata_index` record today~~ — this task adds it
- ~~`option_label` in the real column~~ — the real key is `option_value`

---

## Implementation Notes

- Keep the `GROUP BY` unchanged — `m.options` is inside the aggregate, not a
  grouped column.
- Store options verbatim (list of dicts); do not transform here — TASK-1878
  interprets them.

### Key Constraints
- Async-first; no blocking I/O. No new dependencies.
- Preserve existing behaviour when `options` is null → store `[]`.

---

## Acceptance Criteria

- [ ] `_FORM_QUERY` selects `m.options` inside `jsonb_build_object`.
- [ ] `_build_metadata_index` records include an `options` key (list; `[]` when null).
- [ ] Existing importer tests still pass: `pytest packages/parrot-formdesigner/tests/unit/test_networkninja_importer.py -v`
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/networkninja.py`

---

## Test Specification

```python
# A metadata index built from a row carrying options exposes them:
svc = NetworkninjaFormService(dsn="postgres://test")
idx = svc._build_metadata_index([
    {"column_id": 1, "column_name": "10211", "data_type": "FIELD_SELECT",
     "description": "Role",
     "options": [{"is_active": True, "option_id": "6091", "column_name": 10211,
                  "option_value": "Field Merchandiser"}]},
])
assert idx["10211"]["options"][0]["option_id"] == "6091"
# Null options → empty list
idx2 = svc._build_metadata_index([
    {"column_id": 2, "column_name": "9", "data_type": "FIELD_TEXT", "description": "x", "options": None},
])
assert idx2["9"]["options"] == []
```

---

## Agent Instructions

Read the spec (§1, §3 Module 1, §6) first. Verify the Codebase Contract lines
before editing. Update the per-spec index status to `in-progress`, implement,
run the acceptance checks, move this file to `sdd/tasks/completed/`, set the
index status to `done`, and fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-23
**Notes**: Added `'options', m.options` to the `jsonb_build_object` in
`_FORM_QUERY`; `_build_metadata_index` now stores `options` (defaulting to
`[]` when null/absent). Verified with the task's test scaffold, the full
existing unit suite (`test_networkninja_importer.py`, 24 passed), and
`ruff check` (clean).
**Deviations from spec**: none
