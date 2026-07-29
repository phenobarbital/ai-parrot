# TASK-1880: Add `options_source` provenance to `ImportDiffEntry`

**Feature**: FEAT-325 — NetworkNinja Importer — Select Options from `form_metadata`
**Spec**: `sdd/specs/networkninja-metadata-select-options.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1878
**Assigned-to**: unassigned

---

## Context

Spec §2 (Data Models), §3 Module 4, §5. To audit which of the ~338 live select
columns were populated from the canonical metadata catalog versus a fallback
source, `ImportDiffEntry` gains an `options_source` field, populated from the
per-column provenance produced by TASK-1878.

---

## Scope

- Add `options_source: str | None = None` to `ImportDiffEntry` (values:
  `"metadata" | "inline" | "logic_groups" | "none"`; `None` for non-option
  fields).
- In `_map_question_to_field`, set `options_source` on the emitted
  `ImportDiffEntry` for option-typed fields using the provenance from TASK-1878;
  leave `None` for all other field types.

**NOT in scope**: option collection (TASK-1878); condition re-indexing
(TASK-1879); changing `status`/`note` semantics.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/networkninja.py` | MODIFY | `ImportDiffEntry` (lines 54–74) + `_map_question_to_field` report block (741–776) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict   # already imported (networkninja.py:16)
```

### Existing Signatures to Use
```python
# networkninja.py:54
class ImportDiffEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")   # line 68  ← new field must be declared, not ad-hoc
    column_name: str            # line 70
    source_data_type: str       # line 71
    mapped_field_type: str | None = None  # line 72
    status: str                 # line 73
    note: str = ""              # line 74

# networkninja.py:644
def _map_question_to_field(self, question, meta_index, question_id_index,
                           select_options, report_entries=None) -> FormField | None:
    # report entries appended at lines 748-776 (mapeado/aproximado/requiere_intervencion)
    # options resolved at lines 736-739
```

### Does NOT Exist
- ~~`ImportDiffEntry.options_source`~~ — this task adds it
- because `model_config = ConfigDict(extra="forbid")`, the field MUST be declared
  on the model — you cannot set an undeclared attribute

---

## Implementation Notes

- Declare the field with a default of `None` so existing construction sites that
  don't set it remain valid.
- Populate it only in the option-typed branches; for `requiere_intervencion` /
  formula / non-option entries leave it `None`.
- Depends on TASK-1878 exposing per-column provenance to this method; if
  TASK-1878 chose a specific carrier (sibling dict / dataclass), read it here.

### Key Constraints
- `extra="forbid"` — the field must be a real model field.
- No behaviour change to `status`/`note`.

---

## Acceptance Criteria

- [ ] `ImportDiffEntry` has `options_source: str | None = None`.
- [ ] Option-typed fields get `options_source` ∈ `{metadata, inline, logic_groups, none}`.
- [ ] Non-option fields keep `options_source is None`.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_networkninja_importer.py -v` passes.
- [ ] `ruff check` clean on the file.

---

## Test Specification

```python
row = {  # single FIELD_SELECT with metadata options
  "formid": 1, "orgid": 1, "form_name": "F", "description": None,
  "question_blocks": [{"block_id": 1, "block_type": "simple", "block_logic_groups": [],
    "questions": [{"question_id": 1, "question_column_name": "10211",
                   "question_description": "Role", "validations": []}]}],
  "metadata": [{"column_id": 1, "column_name": "10211", "data_type": "FIELD_SELECT",
    "description": "Role", "options": [
      {"is_active": True, "option_id": "6091", "column_name": 10211, "option_value": "Field Merchandiser"}]}],
}
_, report = NetworkninjaFormService(dsn="postgres://test").import_with_report(row)
entry = next(e for e in report.fields if e.column_name == "10211")
assert entry.options_source == "metadata"
```

---

## Agent Instructions

Read the spec (§2, §3 Module 4, §6) and confirm TASK-1878 is completed. Verify
the Codebase Contract, set index status `in-progress`, implement, run acceptance
checks, move this file to completed, set index status `done`, fill the
Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-23
**Notes**: Added `options_source: str | None = None` to `ImportDiffEntry`.
In `_map_question_to_field`, computed `field_options_source` from
`options_provenance.get(col_name)` for option-typed fields only (`None`
otherwise) and passed it into all three report branches (mapeado /
aproximado / requiere_intervencion — the FIELD_SELECT_RADIO "aproximado"
branch needed it too, since render_as also flags it approximate). Verified
with the task's test scaffold, the full existing unit suite (24 passed), and
`ruff check` (clean).
**Deviations from spec**: none
