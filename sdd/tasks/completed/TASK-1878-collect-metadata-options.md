# TASK-1878: Metadata-primary option collection in `_collect_select_options`

**Feature**: FEAT-325 — NetworkNinja Importer — Select Options from `form_metadata`
**Spec**: `sdd/specs/networkninja-metadata-select-options.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1877
**Assigned-to**: unassigned

---

## Context

Root cause link 3 of FEAT-325 (spec §1, §3 Module 2): `_collect_select_options`
only reads inline + logic-group options and never `form_metadata.options`. This
task makes metadata the **primary** source of select options, keyed by
`option_id`, with inline then logic-groups as fallback used only when a column's
metadata catalog is empty.

---

## Scope

- In `_collect_select_options`, for each option-typed column
  (`data_type in _OPTION_FIELD_TYPES`) present in `meta_index`, build options
  from `meta_index[col]["options"]` first:
  `FieldOption(value=str(option_id), label=option_value, disabled=(not is_active))`.
- Dedup by `value` (`option_id`).
- Fall back to the existing inline scan, then the logic-group scan, **only when
  a column has no metadata options**.
- Return, alongside the options map, a per-column provenance value
  (`"metadata" | "inline" | "logic_groups" | "none"`) so TASK-1880 can record it.
  Suggested shape: return `dict[str, list[FieldOption]]` plus a sibling
  `dict[str, str]` provenance map (or a small dataclass) — keep the existing
  return usable by `_map_question_to_field`.

**NOT in scope**: condition re-indexing (TASK-1879); adding the report field
(TASK-1880 wires provenance into `ImportDiffEntry`); the query/index change
(TASK-1877).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/networkninja.py` | MODIFY | `_collect_select_options` (lines 504–594); minor plumbing in `_build_form_schema` (367–369) and `_map_question_to_field` (736–739) to pass provenance through |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ...core.options import FieldOption   # options.py:13
```

### Existing Signatures to Use
```python
# core/options.py:13
class FieldOption(BaseModel):
    value: str              # line 25
    label: LocalizedString  # line 26  (accepts a plain str)
    disabled: bool = False  # line 28  ← use for is_active=false

# networkninja.py:162
_OPTION_FIELD_TYPES = {"FIELD_SELECT", "FIELD_SELECT_RADIO", "FIELD_MULTISELECT"}

# networkninja.py:504
def _collect_select_options(self, question_blocks, question_id_index, meta_index) -> dict[str, list[FieldOption]]:
    # collector: dict[str, dict[str, str]]  col_name → {value: label}  (line 525)
    # Source 1 inline options: lines 558-577
    # Source 2 logic-group conditions: lines 579-586

# networkninja.py:735-739  (consumer)
options: list[FieldOption] | None = None
if data_type in _OPTION_FIELD_TYPES:
    collected = select_options.get(col_name)
    options = collected if collected else None
```

### Does NOT Exist
- ~~a `meta` attribute on `FieldOption`~~ — use `disabled` (options.py:28)
- ~~metadata source in `_collect_select_options` today~~ — this task adds it
- ~~`option_label`~~ — the real key is `option_value`

---

## Implementation Notes

- `option_id` may arrive as `int` or `str` in JSON — cast with `str(...)`,
  mirroring `str(question.get("question_column_name", ""))` (line 673).
- Preserve dedup-by-value semantics of the current `{value: label}` collector so
  distinct ids survive duplicate labels.
- Provenance rules: `"metadata"` if metadata options populated the column;
  else `"inline"` if inline populated it; else `"logic_groups"` if a condition
  did; else `"none"` for an option-typed column that ended up empty.
- Keep `_map_question_to_field`'s existing option-attach behaviour intact — only
  extend it to read provenance if you thread it through here.

### Key Constraints
- Backwards compatible: with empty metadata options, output must match today's
  behaviour exactly.
- Async-first; `self.logger` for skips; no new dependencies.

---

## Acceptance Criteria

- [ ] Metadata options produce `FieldOption(value=option_id, label=option_value)`.
- [ ] `is_active=false` options are present with `disabled=True`.
- [ ] Metadata wins when both metadata and inline options exist for a column.
- [ ] Inline / logic-group fallback unchanged when metadata options are empty.
- [ ] Per-column provenance is available to `_map_question_to_field`.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_networkninja_importer.py -v` passes.
- [ ] `ruff check` clean on the file.

---

## Test Specification

```python
# (Full matrix lives in TASK-1881; this scaffold guards the core behaviour.)
row = {
  "formid": 1, "orgid": 1, "form_name": "F", "description": None,
  "question_blocks": [{"block_id": 1, "block_type": "simple", "block_logic_groups": [],
    "questions": [{"question_id": 1, "question_column_name": "10211",
                   "question_description": "Role", "validations": []}]}],
  "metadata": [{"column_id": 1, "column_name": "10211", "data_type": "FIELD_SELECT",
    "description": "Role", "options": [
      {"is_active": True,  "option_id": "6091", "column_name": 10211, "option_value": "Field Merchandiser"},
      {"is_active": False, "option_id": "6092", "column_name": 10211, "option_value": "Retired Role"}]}],
}
schema = NetworkninjaFormService(dsn="postgres://test").to_form_schema(row)
field = next(schema.iter_all_fields())
assert {o.value for o in field.options} == {"6091", "6092"}
assert next(o for o in field.options if o.value == "6091").label == "Field Merchandiser"
assert next(o for o in field.options if o.value == "6092").disabled is True
```

---

## Agent Instructions

Read the spec (§2, §3 Module 2, §6) and confirm TASK-1877 is in
`sdd/tasks/completed/`. Verify the Codebase Contract, set the index status to
`in-progress`, implement, run acceptance checks, move this file to completed,
set index status `done`, and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-23
**Notes**: Rewrote `_collect_select_options` to return
`(select_options, options_provenance)`. Metadata (`form_metadata.options`) is
now the primary source, deduped by `option_id`, with `disabled=not is_active`.
Inline then logic-group scans remain as fallback, applied only to columns
whose metadata catalog is empty (tracked via `metadata_populated`). Threaded
`options_provenance` through `_build_form_schema` → `_map_block_to_section` →
`_map_question_to_field` (parameter added, not yet consumed — TASK-1880 wires
it into `ImportDiffEntry`). Verified with the task's test scaffold, the full
existing unit suite (24 passed), and `ruff check` (clean).
**Deviations from spec**: none
