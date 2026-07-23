# TASK-1881: Tests — unit + integration for metadata select options

**Feature**: FEAT-325 — NetworkNinja Importer — Select Options from `form_metadata`
**Spec**: `sdd/specs/networkninja-metadata-select-options.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1877, TASK-1878, TASK-1879, TASK-1880
**Assigned-to**: unassigned

---

## Context

Spec §4, §5. Lock in the FEAT-325 behaviour with the full test matrix and fix
the pre-existing fixture bug where the integration test used `option_label`
instead of the real `option_value`.

---

## Scope

- Add unit tests to `test_networkninja_importer.py` covering: metadata options
  populate selects; 1–10 scale; inactive → `disabled`; metadata-primary over
  inline; inline fallback when metadata empty; logic-group fallback when no
  metadata; condition re-indexed to `option_id`; unmatched comparison_value
  preserved; `options_source` provenance; int `option_id` cast to str.
- Fix `test_feat300_integration.py`: change the fixture's `option_label` key to
  `option_value` (lines ~106–111) and assert SELECT/RADIO/MULTISELECT fields
  carry options.
- Add an integration-style end-to-end test for a metadata-backed select form
  (options id-keyed, condition consistent).

**NOT in scope**: importer logic changes (owned by TASK-1877–1880). If a test
reveals a logic gap, note it and coordinate — do not silently patch logic here
beyond what the spec's acceptance criteria require.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/unit/test_networkninja_importer.py` | MODIFY | add the unit matrix above |
| `packages/parrot-formdesigner/tests/integration/test_feat300_integration.py` | MODIFY | fix `option_label` → `option_value`; assert options flow |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# In the test modules today:
from parrot_formdesigner.tools.services.networkninja import NetworkninjaFormService
from parrot_formdesigner.core.schema import FormType
from parrot_formdesigner.core.types import FieldType
```

### Existing Signatures to Use
```python
# tests/unit/test_networkninja_importer.py
#   _make_row(data_type) helper builds a single-field row; metadata entries
#   already carry "options": [] (e.g. lines 45-51, 71-77, 107-113, 152-158)
#   svc = NetworkninjaFormService(dsn=...) via a _svc() helper

# tests/integration/test_feat300_integration.py:85-128
#   _row_with_all_live_types() builds metadata with:
#     "options": [{"option_id": 1, "option_label": "A"}] if SELECT-family else []
#   ← BUG: real column key is "option_value", not "option_label"

# schema.iter_all_fields()  → iterate fields for assertions
# FieldOption.value / .label / .disabled  (core/options.py:25-28)
# FieldCondition.value  (core/constraints.py:158)
```

### Does NOT Exist
- ~~`option_label` in the real `form_metadata.options`~~ — real key is `option_value`
- ~~a `meta` attribute on `FieldOption`~~ — assert on `disabled`

---

## Implementation Notes

- Use the real option shape in fixtures:
  `{"is_active": bool, "option_id": str, "column_name": int, "option_value": str}`.
- For the condition test, wire a dependent question with a
  `logic_groups`/`question_logic_groups` `EQUALS` condition whose
  `condition_question_reference_id` resolves (via `question_column_name`) to a
  metadata-backed select, and `condition_comparison_value` equal to an
  `option_value`; assert the resulting `FieldCondition.value` equals that
  option's `option_id`.
- Keep existing tests green — do not weaken current assertions.

### Key Constraints
- pytest + pytest-asyncio conventions already used in the suite.
- No new dependencies.

---

## Acceptance Criteria

- [ ] All new unit tests present and passing.
- [ ] Integration fixture uses `option_value`; SELECT-family fields carry options.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_networkninja_importer.py -v` passes.
- [ ] `pytest packages/parrot-formdesigner/tests/integration/test_feat300_integration.py -v` passes.
- [ ] Full spec §5 acceptance criteria demonstrably covered by tests.
- [ ] `ruff check` clean on both test modules.

---

## Test Specification

> See §4 of the spec for the full test table. Minimum tests to author:
> `test_metadata_options_populate_select`, `test_metadata_options_scale_1_10`,
> `test_inactive_option_marked_disabled`, `test_metadata_primary_over_inline`,
> `test_inline_fallback_when_metadata_empty`,
> `test_logic_group_fallback_when_no_metadata`,
> `test_condition_reindexed_to_option_id`,
> `test_condition_unmatched_comparison_value_preserved`,
> `test_options_source_provenance`, `test_option_id_cast_to_str`.

---

## Agent Instructions

Read the spec (§4, §5, §6) and confirm TASK-1877–1880 are all in
`sdd/tasks/completed/`. Verify the Codebase Contract, set index status
`in-progress`, implement the tests, run the acceptance checks, move this file to
completed, set index status `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
