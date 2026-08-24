# TASK-2410: Relation Core Models (`EntityRef`, `RelationSpec`)

**Feature**: FEAT-456 — Relational Field Cardinality for parrot-formdesigner
**Spec**: `sdd/specs/formbuilder-fieldtype-cardinality.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation of FEAT-456 (spec §3 Module 1). Everything else in this feature
imports these two models. Relations are modeled as an *aspect* attached to
`FormField` (Option C from the brainstorm) — this task creates only the
models themselves; wiring into `FormField` is TASK-2411.

---

## Scope

- Create `packages/parrot-formdesigner/src/parrot_formdesigner/core/relations.py`
  with Pydantic models `EntityRef` and `RelationSpec` exactly as shaped in
  spec §2 Data Models (both `model_config = ConfigDict(extra="forbid")`).
- `RelationSpec` model-validator: `mode="embed"` requires
  `inverse_field is not None` and `cardinality == "many"` (spec-local
  validation only — field_type combinations belong to TASK-2411).
- Google-style docstrings on both models documenting the namespace
  conventions (`odoo`, `db`, `api`, `formdesigner` — free-form by design,
  no validation of unknown namespaces) and the `on_delete` passthrough-hint
  semantics (no enforcement in v1).
- Unit tests at
  `packages/parrot-formdesigner/tests/unit/core/test_relations.py`.

**NOT in scope**: `FormField.relation` field, `is_relational` property,
field_type combination validation, exports in `core/__init__.py` (all
TASK-2411); resolution checks (TASK-2412).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/relations.py` | CREATE | `EntityRef`, `RelationSpec` |
| `packages/parrot-formdesigner/tests/unit/core/test_relations.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, model_validator  # pydantic>=2, in project
from typing import Any, Literal
# Style reference — core/options.py uses exactly this pattern (verified this session)
```

### Existing Signatures to Use
```python
# core/options.py:32 — the model style to follow (BaseModel + typed fields):
class OptionsSource(BaseModel):
    source_type: str          # line 45
    source_ref: str           # line 46
# NOTE: OptionsSource does NOT use extra="forbid"; the NEW relation models
# MUST use it per spec §2 (follow core/schema.py FormField line 78 instead).
```

### Does NOT Exist
- ~~`core/relations.py`~~ — this task creates it; nothing imports it yet.
- ~~Any relational `FieldType`~~ (`MANY_TO_ONE`, `RELATION`, `REFERENCE`) —
  never add enum members in this feature.
- ~~`OptionsSource.target_entity` / `.cardinality`~~ — do not touch
  `core/options.py` at all.
- ~~`tests/unit/core/` may not exist~~ — check; create with `__init__.py`
  if missing (there IS `tests/unit/` with other suites).

---

## Implementation Notes

### Pattern to Follow
Spec §2 Data Models is normative:
```python
class EntityRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    namespace: str
    entity: str
    key_field: str | None = None

class RelationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cardinality: Literal["one", "many"]
    target: EntityRef
    mode: Literal["reference", "embed"] = "reference"
    display_field: str | None = None
    inverse_field: str | None = None
    on_delete: Literal["restrict", "cascade", "set_null"] | None = None
    filters: dict[str, Any] | None = None
```

### Key Constraints
- Error messages from the embed validator must be actionable (state what is
  missing), they will be surfaced verbatim by `FormField` validation later.
- No I/O, no imports from elsewhere in the package (keeps Module 1 leaf-level).

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.core.relations import EntityRef, RelationSpec` works
- [ ] `RelationSpec(mode="embed", ...)` without `inverse_field` raises `ValidationError`
- [ ] `RelationSpec(mode="embed", cardinality="one", ...)` raises `ValidationError`
- [ ] Unknown extra keys rejected (`extra="forbid"`)
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/core/test_relations.py -v`
- [ ] `ruff check` clean on new files

---

## Test Specification

```python
import pytest
from pydantic import ValidationError
from parrot_formdesigner.core.relations import EntityRef, RelationSpec


def test_reference_one_minimal():
    spec = RelationSpec(cardinality="one",
                        target=EntityRef(namespace="odoo", entity="res.partner"))
    assert spec.mode == "reference" and spec.on_delete is None


def test_embed_requires_inverse_field():
    with pytest.raises(ValidationError):
        RelationSpec(cardinality="many", mode="embed",
                     target=EntityRef(namespace="db", entity="public.lines"))


def test_embed_requires_cardinality_many():
    with pytest.raises(ValidationError):
        RelationSpec(cardinality="one", mode="embed", inverse_field="order_id",
                     target=EntityRef(namespace="db", entity="public.lines"))


def test_extra_forbidden():
    with pytest.raises(ValidationError):
        EntityRef(namespace="odoo", entity="res.partner", bogus=1)
```

---

## Agent Instructions

1. Read spec §2 (Data Models) and §6 (Codebase Contract).
2. Verify the contract above with `grep`/`read` before coding.
3. Update status in `sdd/tasks/index/formbuilder-fieldtype-cardinality.json` → `in-progress`.
4. Implement, test, lint.
5. Move this file to `sdd/tasks/completed/`, update index → `done`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
