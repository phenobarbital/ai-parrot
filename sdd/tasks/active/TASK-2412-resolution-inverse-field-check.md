# TASK-2412: Embed-Mode `inverse_field` Existence Check at the Resolution Boundary

**Feature**: FEAT-456 — Relational Field Cardinality for parrot-formdesigner
**Spec**: `sdd/specs/formbuilder-fieldtype-cardinality.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2411
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. Per-field Pydantic validators cannot see the whole form,
so verifying that an embed-mode relation's `inverse_field` actually names a
field inside its `item_template` tree must happen at the form-level
resolution boundary — the same place `resolve_rule_references` rewrites
rule references (spec §7 "inverse_field check placement").

---

## Scope

- In `core/resolution.py`, add the check: for every field with
  `relation.mode == "embed"`, walk the field's `item_template` tree and
  require a field whose `field_id == relation.inverse_field`; otherwise
  raise `ValueError` naming the owning `field_id` and the missing
  `inverse_field`.
- Invoke the check from `resolve_rule_references(form)` (single traversal
  entry point — either inline in its field loop or as a helper called by it).
- Unit tests for pass/fail cases.

**NOT in scope**: submission-value validation (TASK-2415); any change to
rule/UID resolution logic itself.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/resolution.py` | MODIFY | embed inverse_field existence check |
| `packages/parrot-formdesigner/tests/unit/core/test_resolution_relation.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.schema import walk_fields  # used by resolution.py:21 already
from parrot_formdesigner.core.relations import RelationSpec  # TASK-2410
```

### Existing Signatures to Use
```python
# core/resolution.py:28 (verified 2026-08-24)
def resolve_rule_references(form: FormSchema) -> FormSchema:
    # walks form.iter_fields_recursive() (line 55, 115); raises ValueError with
    # messages of the form "Field '<owner>': ..." — match that error style.

# core/schema.py — traversal helpers:
#   FormSchema.iter_fields_recursive() — yields every FormField, parents first
#     (docstring at schema.py:176-195: recurses subsections, GROUP children,
#      ARRAY item_template)
#   walk_fields(fields) — module-level helper used by find_field_by_uid (resolution.py:172)
```

### Does NOT Exist
- ~~`FormSchema.find_field(field_id)`~~ — no such helper; walk explicitly.
- ~~`RelationSpec.validate_against_form(...)`~~ — no such method; the check
  lives in resolution.py.
- ~~`item_template.iter_fields_recursive()`~~ — that method is on
  `FormSchema`, NOT on `FormField`; for a template subtree use
  `walk_fields([...])` or recurse `children`/`item_template` manually.

---

## Implementation Notes

### Pattern to Follow
Mirror the existing error convention in `resolve_rule_references`
(e.g. resolution.py:57-60, 66, 73-75): `ValueError` with
`f"Field {owner!r}: ..."`. The check is idempotent by nature (read-only).

### Key Constraints
- Only `mode="embed"` fields are checked; reference-mode relations have no
  `inverse_field` requirement.
- Nested embeds (ARRAY inside item_template) must be handled by the same
  recursive walk — `iter_fields_recursive` already yields nested fields, so
  checking each embed field independently covers it.

---

## Acceptance Criteria

- [ ] Embed field whose `item_template` tree contains `inverse_field` → passes
- [ ] Missing `inverse_field` in the template tree → `ValueError` naming the
      owning field_id and the missing inverse_field
- [ ] Reference-mode relations unaffected; forms without relations unaffected
      (existing resolution tests still green)
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/core/test_resolution_relation.py -v`
- [ ] Existing suite green: `pytest packages/parrot-formdesigner/tests/unit/ -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
import pytest
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.relations import EntityRef, RelationSpec
from parrot_formdesigner.core.resolution import resolve_rule_references


def _embed_form(inverse: str) -> FormSchema:
    item = FormField(field_id="line", field_type=FieldType.GROUP, label="Line",
                     children=[FormField(field_id="order_id",
                                         field_type=FieldType.HIDDEN, label="oid"),
                               FormField(field_id="qty",
                                         field_type=FieldType.INTEGER, label="Qty")])
    lines = FormField(
        field_id="lines", field_type=FieldType.ARRAY, label="Lines",
        item_template=item,
        relation=RelationSpec(cardinality="many", mode="embed", inverse_field=inverse,
                              target=EntityRef(namespace="db", entity="public.lines")))
    return FormSchema(form_id="t", title="T",
                      sections=[FormSection(section_id="s", fields=[lines])])


def test_inverse_field_exists_passes():
    resolve_rule_references(_embed_form("order_id"))


def test_inverse_field_missing_raises():
    with pytest.raises(ValueError, match="lines"):
        resolve_rule_references(_embed_form("nope"))
```

---

## Agent Instructions

1. Verify TASK-2411 is in `sdd/tasks/completed/`; read spec §3 Module 3 + §7.
2. Verify the contract with `grep`/`read` (especially the traversal helpers).
3. Update index → `in-progress`; implement, test, lint.
4. Move this file to `sdd/tasks/completed/`, update index → `done`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
