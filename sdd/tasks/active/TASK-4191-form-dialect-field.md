# TASK-4191: `FormDialect` enum + `FormSchema.dialect` persisted flag

**Feature**: FEAT-650 — A2UI dialect for parrot-formdesigner
**Spec**: `sdd/specs/a2ui-dialect-formbuilder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (G1). The whole dialect layer keys off one persisted flag on
`FormSchema`. It must default to `json_schema` so every existing stored form
(`schema_json` JSONB rows without the key) and every legacy consumer sees no
behavioural change; it rides inside `schema_json`, so there is no migration.
The enum mirrors `UnknownFieldsPolicy` (FEAT-458) — same file, same export
pattern.

---

## Scope

- Add `FormDialect(str, Enum)` with `JSON_SCHEMA = "json_schema"` and `A2UI = "a2ui"` in `core/schema.py`, immediately after `UnknownFieldsPolicy`.
- Add `dialect: FormDialect = FormDialect.JSON_SCHEMA` to `FormSchema`, immediately after `unknown_fields`.
- Export `FormDialect` from `core/__init__.py` (import block + `__all__`), mirroring `UnknownFieldsPolicy`.
- Write `tests/unit/core/test_form_dialect.py`.

**NOT in scope**: any API negotiation (TASK-4192+), `GET /forms/{uid}` body changes (none — the key simply appears via `model_dump`), docs (TASK-4205).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | `FormDialect` enum + `FormSchema.dialect` field |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` | MODIFY | export `FormDialect` |
| `packages/parrot-formdesigner/tests/unit/core/test_form_dialect.py` | CREATE | default, round-trip, legacy-load, patch-merge tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection   # core/schema.py:65, 401, 229
from parrot_formdesigner.core import UnknownFieldsPolicy                          # core/__init__.py:42, 92
from parrot_formdesigner.core.types import FieldType                              # core/types.py:16
from parrot_formdesigner.api._utils import _deep_merge                            # api/_utils.py:11
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class UnknownFieldsPolicy(str, Enum): ...                              # line 51 — pattern to copy
class FormSchema(BaseModel):                                            # line 401
    form_uid: uuid.UUID = Field(default_factory=uuid.uuid4)             # line 453
    form_id: str                                                        # line 454
    sections: list[FormSection]                                         # line 458
    tenant: str | None = None                                           # line 463
    is_public: bool = False                                             # line 471
    persistence: FormPersistenceConfig | None = None                    # line 473
    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP      # line 475  ← insert `dialect` right after
# packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py
#   import block lists `    UnknownFieldsPolicy,` at line 42; `__all__` lists `    "UnknownFieldsPolicy",` at line 92
# packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py
def _deep_merge(base: dict, patch: dict) -> dict: ...                   # line 11 (what PATCH /forms/{uid} uses)
```

### Does NOT Exist
- ~~`FormDialect`~~ / ~~`FormSchema.dialect`~~ — this task creates them.
- ~~a DB column for the dialect~~ — the value lives inside `schema_json`; `storage.py` is NOT touched.
- ~~`parrot_formdesigner.core.dialect`~~ — no separate module; the enum lives in `core/schema.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/core/test_form_dialect.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#UnknownFieldsPolicy",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSchema",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py#_deep_merge"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The default MUST be `FormDialect.JSON_SCHEMA` (spec G1, AC1) — never `A2UI`.
- Do not add validators: an unknown string must fail pydantic validation naturally (that is the 400 source for PATCH).
- Keep the field a plain pydantic field so `model_dump(mode="json")` emits `"dialect": "json_schema"` (spec AC2 accepts exactly this one additive key).

### References in Codebase
- `core/schema.py:51` — `UnknownFieldsPolicy` (shape to copy).
- `tests/unit/test_formschema_persistence.py` — style for FormSchema field tests.

---

## Implementation Blueprint

### Steps (in order)
1. Add the enum after `UnknownFieldsPolicy` — *why*: keeps the two dialect-like policies adjacent and discoverable.
2. Add the field after `unknown_fields` — *why*: spec §6 Edit Sites fixes the position; FEAT ordering of fields is chronological.
3. Export from `core/__init__.py` in both the import block and `__all__` — *why*: `from parrot_formdesigner.core import FormDialect` is the import every later task uses.
4. Write the tests, run them, `ruff check` the three files.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` (MODIFY — enum)
```python
# occurrences: 1 (verified: grep -c 'class UnknownFieldsPolicy(str, Enum):' packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py)
# AFTER — insert below the END of the `class UnknownFieldsPolicy(str, Enum):` body (verified: core/schema.py:51; the class ends before `class FormField` at :65)


class FormDialect(str, Enum):
    """Wire dialect served by the form contract endpoints (FEAT-650).

    ``JSON_SCHEMA`` keeps the legacy ``JsonSchemaRenderer`` body on
    ``GET /forms/{uid}/schema``; ``A2UI`` serves the FEAT-544 ``createSurface``
    envelope. ``GET /forms/{uid}`` ignores this flag — it always returns the
    raw ``FormSchema``.
    """

    JSON_SCHEMA = "json_schema"
    A2UI = "a2ui"
```
**Why this shape**: `str, Enum` so the JSONB value is the bare string and pydantic accepts both the enum and `"a2ui"` from a PATCH body. Default stays legacy by construction (G1).

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` (MODIFY — field)
```python
# occurrences: 1 (verified: grep -c '    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP' packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py)
# AFTER — insert below `    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP` (verified: core/schema.py:475)
    # FEAT-650 — A2UI dialect flag (default keeps every legacy consumer unchanged)
    dialect: FormDialect = FormDialect.JSON_SCHEMA
```
**Why**: pydantic default ⇒ older `schema_json` rows without the key load unchanged; `_deep_merge` on PATCH overwrites it like any other top-level key. Also add `dialect:` to the `FormSchema` class docstring attribute list (same style as `unknown_fields:` at line 447).

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    UnknownFieldsPolicy,' packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py)
# AFTER — insert below `    UnknownFieldsPolicy,` in the `from .schema import (` block (verified: core/__init__.py:42)
    FormDialect,
# occurrences: 1 (verified: grep -c '    "UnknownFieldsPolicy",' packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py)
# AFTER — insert below `    "UnknownFieldsPolicy",` in `__all__` (verified: core/__init__.py:92)
    "FormDialect",
```
**Why**: mirrors how `UnknownFieldsPolicy` is exposed; keeps `__all__` honest.

### `packages/parrot-formdesigner/tests/unit/core/test_form_dialect.py` (CREATE)
```python
"""FormSchema.dialect — FEAT-650 TASK-4191."""

from __future__ import annotations

import json

from parrot_formdesigner.api._utils import _deep_merge  # api/_utils.py:11
from parrot_formdesigner.core import FormDialect
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType


def _form(**kw) -> FormSchema:
    return FormSchema(
        form_id="f",
        title={"en": "F"},
        tenant="navigator",
        sections=[FormSection(section_id="s", fields=[FormField(field_id="a", field_type=FieldType.TEXT, label={"en": "A"})])],
        **kw,
    )


def test_default_is_json_schema():
    assert _form().dialect is FormDialect.JSON_SCHEMA


def test_dump_emits_bare_string_and_roundtrips():
    f = _form(dialect="a2ui")
    dumped = json.loads(f.model_dump_json())
    assert dumped["dialect"] == "a2ui"
    assert FormSchema.model_validate_json(f.model_dump_json()).dialect is FormDialect.A2UI


def test_legacy_dump_without_key_loads_as_default():
    data = _form().model_dump(mode="json")
    data.pop("dialect")
    assert FormSchema.model_validate(data).dialect is FormDialect.JSON_SCHEMA


def test_patch_deep_merge_sets_dialect():
    merged = _deep_merge(_form().model_dump(), {"dialect": "a2ui"})
    assert FormSchema.model_validate(merged).dialect is FormDialect.A2UI


def test_unknown_value_rejected():
    # FILL IN: assert pydantic ValidationError for dialect="xml" — bounded by AC1 (no custom validator; pydantic enum error)
    raise NotImplementedError
```
**Why this shape**: the four behaviours AC1 names (default, round-trip, legacy load, PATCH merge) plus the negative case; `_deep_merge` is the exact helper `patch_form` uses (handlers.py:1425), so the merge test is faithful.

### FILL IN checklist
- [ ] `test_form_dialect.py::test_unknown_value_rejected` — `pytest.raises(ValidationError)`; bounded by AC1.
- [ ] `core/schema.py` — `FormSchema` docstring attribute entry for `dialect`; bounded by Google-docstring convention.

---

## Acceptance Criteria

- [ ] `FormSchema().dialect` defaults to `FormDialect.JSON_SCHEMA`; `model_dump(mode="json")` emits `"dialect": "json_schema"`.
- [ ] A pre-FEAT-650 dump (no `dialect` key) loads unchanged; `"a2ui"` round-trips through `model_dump_json`/`model_validate_json`.
- [ ] `from parrot_formdesigner.core import FormDialect` works and `FormDialect` is in `core.__all__`.
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/core/test_form_dialect.py -v`
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/core/test_form_dialect.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_formschema_persistence.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_core_models.py -q`

---

## Test Specification

See the CREATE block above — it is the scaffold. Add a `test_clone_preserves_dialect` only if `FormRegistry.clone` is cheap to drive in a unit test (it is covered again by TASK-4205's integration round-trip).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug a2ui-dialect-formbuilder --feature-id FEAT-650`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — `grep -n 'class UnknownFieldsPolicy' packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` and the `unknown_fields:` anchor before editing
5. **Update status** in `sdd/tasks/index/a2ui-dialect-formbuilder.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** with `PYTHONPATH=packages/parrot-formdesigner/src` + the Validation Commands
8. **Commit the code** — stage only the three files above
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4191 a2ui-dialect-formbuilder verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
