# TASK-3911: formdesigner F3 — schema-snippet coverage for all 45 FieldTypes

**Feature**: FEAT-618 — Merge-Tier Gate Integrity & parrot-formdesigner Baseline Repair
**Spec**: `sdd/specs/tests-test-wheel-layout-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4 (failure cluster **F3**, 1 of the 40). This is the
only genuine *product* gap in the formdesigner baseline.

`_FIELD_SCHEMA_SNIPPETS` (`tools/field_helpers.py:15`) is the LLM-facing catalog
of example JSON per form field type — `get_form_field_schema_snippets()` is what
an agent reads to learn how to build a field. It holds **34** of the **45**
`FieldType` members, so eleven field types are invisible to any agent using the
toolkit. `test_field_helpers.py::test_field_schema_snippets_cover_all_types`
asserts the catalog is complete and fails.

Measured at spec time, the 11 missing keys are exactly:
`ai_capture`, `audio`, `color_picker`, `credit_card`, `cron`, `emoji`,
`masked`, `place`, `search`, `signature_pad`, `tree_select`.

It also seeds `controls/builtin.py`, which registers one control per
`FieldType`. **Verified at spec time**: all 45 DO register today, so
`controls/builtin.py` needs no change — do not touch it.

---

## Scope

- Add a schema snippet for each of the 11 missing `FieldType` values to
  `_FIELD_SCHEMA_SNIPPETS`, matching the shape of the existing 34 entries.
- Keep the test as the contract — do not weaken it.

**NOT in scope**: `controls/builtin.py` (verified complete); the
`len(controls) == 32` pin in `test_controls_registry.py` (TASK-3913 owns it);
the registry fixture pollution (TASK-3912); any other cluster.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py` | MODIFY | add the 11 missing snippet entries |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.types import FieldType                 # verified: core/types.py:16  (45 members)
from parrot_formdesigner.tools.field_helpers import (                # verified: tools/field_helpers.py:319,325
    get_form_field_schema_snippets,
    list_supported_form_field_types,
)
from parrot_formdesigner.core.schema import FormField                # verified: tests/unit/test_field_helpers.py:41
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py
_FIELD_SCHEMA_SNIPPETS: dict[str, dict[str, Any]] = {   # line 15 — keys are FieldType *values* (str), not members
    ...
}
def list_supported_form_field_types() -> list[str]:      # line 319
def get_form_field_schema_snippets() -> dict[str, dict[str, Any]]:  # line 325
    return deepcopy(_FIELD_SCHEMA_SNIPPETS)              # line 331 — defensive copy; tests rely on it

# verified entry shape (key "array"):
#   {"field_id": "items", "field_type": "array", "label": "Items",
#    "item_template": {"field_id": "item", "field_type": "text", "label": "Item"}}

# packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py  — DO NOT MODIFY
#   seeds the control registry from get_form_field_schema_snippets();
#   verified: registers all 45 FieldType values, 0 missing.
```

### Does NOT Exist
- ~~a missing control registration~~ — **verified**: `import parrot_formdesigner.controls.builtin; len(get_controls()) == 45` with no `FieldType` value absent. The `KeyError: 'text'` failures elsewhere are fixture pollution (TASK-3912), not a registry gap.
- ~~`FieldType.SIGNATURE_PAD` being the same as `FieldType.SIGNATURE`~~ — they are distinct members; check `core/types.py` before assuming an alias.
- ~~`_FIELD_SCHEMA_SNIPPETS` being keyed by `FieldType` members~~ — it is keyed by the **string values** (`"array"`, not `FieldType.ARRAY`).
- ~~a snippet generator / factory~~ — the dict is a hand-written literal; there is no code path that derives entries.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py#get_form_field_schema_snippets",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py#FieldType"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every snippet must **round-trip through `FormField.model_validate()`** — an
  existing test (`test_rest_snippet_roundtrips_to_form_field`) proves that is
  the bar for a snippet, and a new entry that does not validate is worse than a
  missing one.
- These snippets are read by an LLM. Give each a realistic `label` and
  `field_id` that teaches the field's purpose (the existing `"array"` entry is
  the model: a plausible example, not a placeholder).
- Each entry's `field_type` value MUST equal its dict key.
- Do not re-order or re-format the existing 34 entries — keep the diff to
  additions so review is cheap.

### References in Codebase
- `tools/field_helpers.py:15-318` — the existing 34 entries; copy their shape.
- `core/types.py:16` — `FieldType`, the authoritative member list.
- `tests/unit/test_field_helpers.py:21-45` — the defensive-copy and round-trip contracts.

---

## Implementation Blueprint

### Steps (in order)
1. Re-measure the gap — *why*: the 11 names were measured at spec time and `FieldType` may have grown again.
2. Read each missing type's definition in `core/types.py` and its control metadata — *why*: the snippet must reflect what the field actually accepts, not a guess.
3. Add one entry per missing key — *why*: `test_field_schema_snippets_cover_all_types` compares key sets exactly.
4. Verify each new entry round-trips through `FormField` — *why*: an invalid snippet teaches an agent to emit invalid forms.

### `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^_FIELD_SCHEMA_SNIPPETS' tools/field_helpers.py)
# INSIDE the dict literal opened at `_FIELD_SCHEMA_SNIPPETS: dict[str, dict[str, Any]] = {` (verified: tools/field_helpers.py:15)
# Add one entry per missing FieldType value, in the dict's existing ordering convention.
#
# Shape, verified from the existing "array" entry:
#     "<field_type_value>": {
#         "field_id": "<snake_case example id>",
#         "field_type": "<field_type_value>",   # MUST equal the key
#         "label": "<human label an LLM can learn from>",
#         # ...any type-specific keys this FieldType requires
#     },
#
# FILL IN: the 11 entries — ai_capture, audio, color_picker, credit_card, cron,
# emoji, masked, place, search, signature_pad, tree_select — bounded by
# (a) key set == {m.value for m in FieldType}, and
# (b) FormField.model_validate(snippet) succeeding for every new entry.
# Re-measure first; do not trust this list blindly:
#     python -c "from parrot_formdesigner.tools.field_helpers import get_form_field_schema_snippets as g; \
#                from parrot_formdesigner.core.types import FieldType; \
#                print(sorted({m.value for m in FieldType} - set(g())))"
```
**Why this shape**: the dict is keyed by the `FieldType` *string value* and the
test compares key sets exactly, so a typo'd key fails as loudly as a missing
one. `get_form_field_schema_snippets()` deep-copies on every call
(`field_helpers.py:331`), so nested dicts inside an entry are safe to use as
literals — the defensive-copy test depends on that remaining true.

### FILL IN checklist
- [ ] 11 × `_FIELD_SCHEMA_SNIPPETS` entries; bounded by exact key-set equality with `FieldType`
- [ ] each new entry validates via `FormField.model_validate()`; bounded by the existing round-trip contract

---

## Acceptance Criteria

- [ ] `test_field_schema_snippets_cover_all_types` passes.
- [ ] `set(get_form_field_schema_snippets()) == {m.value for m in FieldType}` — exact equality, both directions.
- [ ] Every newly added snippet round-trips through `FormField.model_validate()`.
- [ ] The existing 34 entries are unchanged (diff shows additions only).
- [ ] `controls/builtin.py` is NOT modified.
- [ ] **AC7** `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/test_field_helpers.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/controls/test_control_registry_capabilities.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_core_models.py -q`

---

## Test Specification

No new test file — `test_field_schema_snippets_cover_all_types` is the
specification. If a new snippet makes a *different* test fail on a count, that
failure belongs to TASK-3913 (pinned constants); do not fix it here.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug tests-test-wheel-layout-tech-debt --feature-id FEAT-618`)
2. **Read the spec** §3 Module 4 and §2's taxonomy row **F3**.
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — re-measure the missing key set before writing entries.
5. **Update status** in the per-spec index → `"in-progress"`.
6. **Implement** from the blueprint.
7. **Verify** the Validation Commands. Prefix with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only `field_helpers.py`.
9. **Close** with `scripts/sdd/close_task.sh TASK-3911 tests-test-wheel-layout-tech-debt verified`.
10. **Fill in the Completion Note** with the new package failure count.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: The 11 snippets added, and the new `parrot-formdesigner` failure count (was 40).

**Deviations from spec**: none | describe if any
