# TASK-2411: `FormField.relation` Aspect + Combination Validator + Exports

**Feature**: FEAT-456 — Relational Field Cardinality for parrot-formdesigner
**Spec**: `sdd/specs/formbuilder-fieldtype-cardinality.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2410
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 — wires `RelationSpec` into `FormField` as an orthogonal
aspect (beside `constraints`/`options_source`/`depends_on`) and enforces the
legal (field_type × cardinality × mode) combination table from spec §2.
Gates TASK-2412/2413/2414/2415.

---

## Scope

- Add `relation: RelationSpec | None = None` to `FormField`
  (core/schema.py, after `item_template`, before `meta`).
- Add read-only property `FormField.is_relational -> bool`
  (`self.relation is not None`).
- Add a `@model_validator(mode="after")` on `FormField` enforcing, when
  `relation` is set:
  - `mode="reference"`, `cardinality="one"` → `field_type` ∈ {SELECT,
    DYNAMIC_SELECT, TREE_SELECT}
  - `mode="reference"`, `cardinality="many"` → `field_type` ∈ {MULTI_SELECT,
    TAGS, TRANSFER_LIST}
  - `mode="embed"` → `field_type == ARRAY` AND `item_template is not None`
  - Every rejection: `ValueError` naming `field_id` and the violated rule.
- Export `EntityRef`, `RelationSpec` from
  `parrot_formdesigner/core/__init__.py`.
- Unit tests (combinations legal/illegal, backcompat round-trip).

**NOT in scope**: `inverse_field` existence check inside `item_template`
(needs whole-form context — TASK-2412); extractors/renderers/validators
(TASK-2413/2414/2415).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | `relation` field + `is_relational` + validator |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` | MODIFY | export `EntityRef`, `RelationSpec` |
| `packages/parrot-formdesigner/tests/unit/core/test_formfield_relation.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.relations import EntityRef, RelationSpec  # from TASK-2410
from parrot_formdesigner.core.types import FieldType     # core/types.py:16
# core/__init__.py already re-exports from .options (line 27) and .schema (line 29) —
# follow that style for .relations
```

### Existing Signatures to Use
```python
# core/schema.py:44 (verified 2026-08-24)
class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")        # line 78
    field_uid: uuid.UUID                              # line 80
    field_id: str                                     # line 81
    field_type: FieldType                             # line 82
    constraints: FieldConstraints | None = None       # line 89
    options: list[FieldOption] | None = None          # line 90
    options_source: OptionsSource | None = None       # line 91
    depends_on: DependencyRule | None = None          # line 92
    post_depends: list[PostDependency] | None = None  # line 93
    children: list[FormField] | None = None           # line 94
    item_template: FormField | None = None            # line 95
    meta: dict[str, Any] | None = None                # line 96
# FormField.model_rebuild() at line 100 — KEEP; it must still resolve after the edit.

# core/types.py — relevant members (line numbers verified):
#   SELECT=27 MULTI_SELECT=28 ARRAY=38 DYNAMIC_SELECT=41 TRANSFER_LIST=42
#   TAGS=46 TREE_SELECT=62
```

### Does NOT Exist
- ~~`FormField.is_relational`~~ — created by THIS task.
- ~~Relational FieldType members~~ — never add any.
- ~~Changes to `controls/builtin.py`~~ — acceptance criterion: file untouched.
- ~~`OptionsSource` changes~~ — must remain its exact 7 fields (options.py:45-52).

---

## Implementation Notes

### Pattern to Follow
The combination table in spec §2 is normative. Use frozenset constants for
the legal type sets; the validator runs `mode="after"` so `field_type` and
`item_template` are populated. Pydantic properties: plain `@property` works
on BaseModel — do NOT make it a Field.

### Key Constraints
- `relation=None` (default) must change NOTHING: serialization of existing
  schemas stays byte-stable apart from optional-key absence
  (`model_dump(exclude_none=...)` behavior unchanged — add a round-trip test
  loading a pre-FEAT-456 dict).
- Error message format: `Field '<field_id>': relation <rule text>`.

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.core import EntityRef, RelationSpec` works
- [ ] All legal combinations from spec §2 table validate
- [ ] BOOLEAN+relation, MULTI_SELECT+cardinality="one", embed without ARRAY,
      embed without item_template → `ValidationError` naming the field_id
- [ ] Pre-FEAT-456 schema dict loads; `model_dump()` round-trips
- [ ] `git diff --name-only` shows NO changes to `controls/builtin.py`,
      `core/types.py`, `core/options.py`
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/core/test_formfield_relation.py -v`
- [ ] Existing suite still green: `pytest packages/parrot-formdesigner/tests/unit/ -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
import pytest
from pydantic import ValidationError
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.relations import EntityRef, RelationSpec

ODOO_PARTNER = EntityRef(namespace="odoo", entity="res.partner")


def _rel(card, mode="reference", **kw):
    return RelationSpec(cardinality=card, mode=mode, target=ODOO_PARTNER, **kw)


def test_select_reference_one_ok():
    f = FormField(field_id="customer", field_type=FieldType.SELECT,
                  label="Customer", relation=_rel("one"))
    assert f.is_relational


def test_multiselect_reference_one_rejected():
    with pytest.raises(ValidationError, match="customer"):
        FormField(field_id="customer", field_type=FieldType.MULTI_SELECT,
                  label="Customer", relation=_rel("one"))


def test_embed_requires_array_with_template():
    with pytest.raises(ValidationError):
        FormField(field_id="lines", field_type=FieldType.ARRAY, label="Lines",
                  relation=_rel("many", mode="embed", inverse_field="order_id"))
    # and with item_template it passes:
    item = FormField(field_id="line", field_type=FieldType.GROUP, label="Line",
                     children=[FormField(field_id="order_id",
                                         field_type=FieldType.HIDDEN, label="oid")])
    f = FormField(field_id="lines", field_type=FieldType.ARRAY, label="Lines",
                  item_template=item,
                  relation=_rel("many", mode="embed", inverse_field="order_id"))
    assert f.relation.mode == "embed"


def test_boolean_with_relation_rejected():
    with pytest.raises(ValidationError, match="flag"):
        FormField(field_id="flag", field_type=FieldType.BOOLEAN,
                  label="Flag", relation=_rel("one"))


def test_backcompat_no_relation_roundtrip():
    f = FormField(field_id="name", field_type=FieldType.TEXT, label="Name")
    assert not f.is_relational
    assert FormField(**f.model_dump()) == f
```

---

## Agent Instructions

1. Read spec §2 (combination table) and §6; verify TASK-2410 is in `sdd/tasks/completed/`.
2. Verify the contract above with `grep`/`read` before coding.
3. Update index status → `in-progress`; implement, test, lint.
4. Move this file to `sdd/tasks/completed/`, update index → `done`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
