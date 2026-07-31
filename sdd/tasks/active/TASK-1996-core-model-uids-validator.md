# TASK-1996: Core model UIDs + canonical traversal + uniqueness validator

**Feature**: FEAT-393 — Stable UUID-Based Field Identity (field_uid)
**Spec**: `sdd/specs/formdesigner-field-uid.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1995
**Assigned-to**: unassigned

---

## Context

Implements Module 2 of FEAT-393 (spec §3, blueprint §9). The root of the
feature: `field_uid`/`section_uid`/`subsection_uid` on the core models, ONE
canonical recursive traversal, and the full-tree uniqueness validator that
closes today's silent-duplicate hole.

---

## Scope

- Add `field_uid: uuid.UUID = Field(default_factory=uuid.uuid4)` to
  `FormField` (first field); same pattern for `FormSubsection.subsection_uid`
  and `FormSection.section_uid`.
- Add module-level `walk_fields(items)` generator (recurses subsections,
  GROUP `children`, ARRAY `item_template`) and
  `FormSchema.iter_fields_recursive()`.
- Add `FormSchema._validate_unique_identity` model validator (mode="after"):
  rejects duplicate section/subsection/field UIDs AND duplicate `field_id`
  per form, over the full tree.
- Add `RenderWarning.field_uid: uuid.UUID | None = None`.
- Docstring on `iter_all_fields()` (:324): layout-order only, NOT the
  uniqueness traversal.
- Unit tests per spec §4 (Module 2 rows).

**NOT in scope**: rule models / resolution (TASK-1997); consumers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | UID fields, walk_fields, validator, RenderWarning |
| `packages/parrot-formdesigner/tests/unit/core/test_uid_identity.py` | CREATE | uniqueness + traversal tests |

---

## Codebase Contract (Anti-Hallucination)

> Anchors verified on dev@94d8fc543; re-verify after FEAT-389 + TASK-1995
> (FormSchema region shifts).

### Verified Imports
```python
from parrot_formdesigner.core.schema import (
    FormField, FormSchema, FormSection, FormSubsection, RenderWarning, SectionItem,
)
```

### Existing Signatures to Use
```python
# core/schema.py
class FormField(BaseModel):            # :43-93; extra="forbid" (:72)
    field_id: str                      # :74
    children: list[FormField] | None   # :87 — GROUP nesting
    item_template: FormField | None    # :88 — ARRAY template
FormField.model_rebuild()              # :93 — MUST remain after model changes
class FormSubsection(BaseModel):       # :96-121; subsection_id: str (:116); fields: list[FormField] (:119)
class FormSection(BaseModel):          # :127-159; section_id: str (:146); fields: list[SectionItem] (:149)
SectionItem = Union[FormField, FormSubsection]   # :124
class FormSchema(BaseModel):           # form_id (:305), iter_all_fields (:324-327)
# _validate_metadata (:329-373) — existing validator; keep it using iter_all_fields
class RenderWarning(BaseModel):        # :376-390; field_id: str (:387)
```

### Does NOT Exist
- ~~`walk_fields` / `iter_fields_recursive` / `_validate_unique_identity`~~ — created HERE
- ~~duplicate-`field_id` validation anywhere in FormSchema~~ — `:338` builds a set only for metadata-key collision; your validator is the first
- ~~`FieldFallback` class~~ — the fallback-warning model is `RenderWarning`

---

## Implementation Notes

### Pattern to Follow
Spec §9 "Module 2" blueprint is authoritative — `walk_fields`,
`iter_fields_recursive`, and `_validate_unique_identity` bodies are given
there verbatim; apply them as written.

### Key Constraints
- `field_uid` placed as the FIRST field of each model (identity-first
  convention).
- Keep `extra="forbid"` on all three models; keep `FormField.model_rebuild()`.
- `walk_fields` yields the GROUP/ARRAY parent BEFORE recursing into
  `children`/`item_template` (deterministic order — the migration in
  TASK-2008 replays it).
- Error messages must name the form (`self.form_id`) and the duplicate value.
- Do NOT alter `_validate_metadata` semantics.

### References in Codebase
- `services/validators.py:736,753` — `_collect_fields`/`_collect_nested_fields`, the
  pre-existing recursive traversal your `walk_fields` supersedes (do not delete them here;
  TASK-1998 re-keys the validator)

---

## Acceptance Criteria

- [ ] All three UID fields auto-generate uuid4 and accept valid client-supplied values
- [ ] Duplicate `field_uid`/`section_uid`/`subsection_uid` anywhere in the tree → ValidationError
- [ ] Duplicate `field_id` per form → ValidationError (incl. inside `children`/`item_template`/subsections)
- [ ] `RenderWarning.field_uid` optional, defaults None
- [ ] Existing suite still passes (UID defaults are backward-transparent): `pytest packages/parrot-formdesigner/tests/ -v`
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/core/`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/core/test_uid_identity.py
import uuid
import pytest
from pydantic import ValidationError
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection

def _field(fid: str, **kw) -> FormField: ...

def test_field_uid_auto_generated(): ...
def test_field_uid_client_supplied_accepted(): ...

def test_duplicate_field_uid_rejected():
    uid = uuid.uuid4()
    with pytest.raises(ValidationError, match="Duplicate field_uid"):
        FormSchema(form_id="f", title=..., sections=[FormSection(
            section_id="s", fields=[_field("a", field_uid=uid), _field("b", field_uid=uid)])])

def test_duplicate_field_id_rejected(): ...

def test_uniqueness_covers_nested_fields():
    """Duplicate hidden inside GROUP children AND inside a subsection is caught."""

def test_section_subsection_uids_unique(): ...

def test_walk_fields_order_deterministic():
    """Parent GROUP yields before its children; subsection fields in declaration order."""
```

---

## Agent Instructions

1. **Read the spec** §9 Module 2; verify TASK-1995 is in `sdd/tasks/completed/`.
2. **Verify the contract** anchors post-merge; update the contract first if shifted.
3. **Update status** in `sdd/tasks/index/formdesigner-field-uid.json` → `"in-progress"`.
4. **Implement**, run tests, verify acceptance criteria.
5. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
