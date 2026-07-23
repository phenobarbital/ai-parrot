# TASK-1879: Re-index `EQUALS` conditions to `option_id`

**Feature**: FEAT-325 — NetworkNinja Importer — Select Options from `form_metadata`
**Spec**: `sdd/specs/networkninja-metadata-select-options.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1877
**Assigned-to**: unassigned

---

## Context

Spec §2, §3 Module 3. Because select option values become `option_id`
(TASK-1878), the `EQUALS` conditions built in `_map_logic_groups` — which today
use `condition_comparison_value` (the human text) — must be translated to the
matching `option_id` so `FieldCondition.value` lives in the same value-space as
`FieldOption.value`. Otherwise conditional show/hide silently breaks for every
select backed by metadata options.

---

## Scope

- Add a helper `_build_option_id_catalog(meta_index) -> dict[str, dict[str, str]]`
  producing `column_name → {option_value: option_id}` from
  `form_metadata.options`.
- Thread the catalog from `_build_form_schema` into `_map_logic_groups`.
- In `_map_logic_groups`, when the referenced column has a metadata catalog,
  translate `condition_comparison_value` → `option_id` before building the
  `FieldCondition`. When the column has no catalog, keep the current text value
  (fallback). When the `comparison_value` is not found in the catalog, keep the
  original value and log at `debug` (do not drop the condition).

**NOT in scope**: option collection (TASK-1878); report provenance (TASK-1880);
non-`EQUALS` operators (still skipped as today).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/networkninja.py` | MODIFY | new `_build_option_id_catalog`; `_build_form_schema` (364–369, 382–388) threads catalog; `_map_logic_groups` (792–869) translates value at line 843 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ...core.constraints import ConditionOperator, DependencyRule, FieldCondition  # already imported
```

### Existing Signatures to Use
```python
# core/constraints.py:144
class FieldCondition(BaseModel):
    value: Any = None   # line 158  ← receives the re-indexed option_id

# networkninja.py:792
def _map_logic_groups(self, question, question_id_index) -> DependencyRule | None:
    # builds FieldCondition(field_id=..., operator=ConditionOperator.EQ,
    #   value=comparison_value)  at lines 845-851 (comparison_value = line 843)
    # only condition_logic == "EQUALS" is handled (line 827)

# networkninja.py:328  (caller that must pass the new catalog through)
def _build_form_schema(self, row, report_entries=None) -> FormSchema:
    # calls _map_block_to_section (382-388) → _map_question_to_field → _map_logic_groups
```

### Does NOT Exist
- ~~`_build_option_id_catalog`~~ — create it in this task
- ~~a reverse index from text → option_id today~~ — this task adds it

---

## Implementation Notes

- The catalog maps `option_value` (text) → `str(option_id)`; cast ids to str.
- `_map_logic_groups` currently takes `(question, question_id_index)`; extend its
  signature (and the call sites in `_map_question_to_field` / block mapping) to
  also accept the catalog. Keep the change minimal and internal.
- Translation must be per-referenced-column: use `question_id_index` to resolve
  `condition_question_reference_id` → `ref_col`, then look up
  `catalog.get(ref_col, {}).get(str(comparison_value))`.
- If `ref_col` has a catalog but the value isn't found, keep the original text
  and `self.logger.debug(...)` — never drop the condition.

### Key Constraints
- Backwards compatible: columns without a metadata catalog keep text comparison.
- Async-first; no new dependencies.

---

## Acceptance Criteria

- [ ] `_build_option_id_catalog` returns `column_name → {option_value: option_id}`.
- [ ] `EQUALS` condition on a metadata-backed select yields
      `FieldCondition.value == option_id`.
- [ ] Condition on a column with no metadata catalog keeps the text value.
- [ ] Unmatched `comparison_value` keeps the original value (no crash; debug log).
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_networkninja_importer.py -v` passes.
- [ ] `ruff check` clean on the file.

---

## Test Specification

```python
# A select with metadata options + a dependent field whose EQUALS condition
# references the select by comparison_value (text) must yield an option_id value.
# Given options [{option_id:"6091", option_value:"Field Merchandiser"}], a
# condition comparison_value="Field Merchandiser" must produce
# FieldCondition.value == "6091".
# (Concrete row + assertions authored in TASK-1881.)
```

---

## Agent Instructions

Read the spec (§2, §3 Module 3, §6) and confirm TASK-1877 is completed. Verify
the Codebase Contract, set index status `in-progress`, implement, run acceptance
checks, move this file to completed, set index status `done`, fill the
Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-23
**Notes**: Added `_build_option_id_catalog(meta_index) -> dict[str, dict[str, str]]`
(column_name → {option_value: option_id}). Threaded `option_id_catalog` from
`_build_form_schema` through `_map_block_to_section` / `_map_question_to_field`
into `_map_logic_groups`, which now re-indexes `condition_comparison_value` to
`option_id` when the referenced column has a catalog entry, preserves text
comparison when no catalog exists, and keeps the original value (with a debug
log) when the comparison value is not found. Verified with a manual smoke
test (condition on a metadata-backed select re-indexes "Field Merchandiser" →
"6091"), the full existing unit suite (24 passed), and `ruff check` (clean).
**Deviations from spec**: none
