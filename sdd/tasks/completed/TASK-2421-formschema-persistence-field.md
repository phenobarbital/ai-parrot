# TASK-2421: Add `FormSchema.persistence` and its validation

**Feature**: FEAT-457 — Autonomous FormSchema Persistence (Standalone Forms)
**Spec**: `sdd/specs/formbuilder-formschema-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2417, TASK-2420
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 2

---

## Context

The single field that makes a form autonomous, plus the validation that makes a
bad declaration fail at **authoring** time instead of at the first respondent's submit.

`core/schema.py` is the hottest shared file in this package - keep this change to one field
plus validator extensions, nothing else.

Implements spec section 3 Module 2.

---

## Scope

- Add `persistence: FormPersistenceConfig | None = None` to `FormSchema`, after `is_public` (currently `core/schema.py:374`).
- Extend the existing `@model_validator` on `FormSchema` to reject, when `persistence` is set AND the target is tabular: (a) any `field_id` or `FormMetadataField.key` colliding with `RESERVED_COLUMNS`; (b) any flattened column name that fails `validate_identifier`.
- Skip both checks for document targets (`asyncdb` with a document driver) - nesting has no column namespace to collide with.
- Update the `FormSchema` class docstring to document the new attribute.
- Write unit tests in `tests/unit/test_formschema_persistence.py`.

**NOT in scope**: Sink resolution or writing. Coordinate-immutability enforcement (TASK-2426). RBAC gating of who may author the block (spec section 8, still open). Any change to `FormSchema`'s other fields.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | One new field + validator extension + docstring |
| `packages/parrot-formdesigner/tests/unit/test_formschema_persistence.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.
>
> Verified against `dev` on 2026-08-24. All paths are relative to the repo root.
> Line numbers shift as soon as anything above them changes — **re-`grep` before editing**.

### Verified Imports

```python
# Added to core/schema.py:
from .persistence import FormPersistenceConfig            # created by TASK-2417
from ..services.sinks.mapper import RESERVED_COLUMNS      # created by TASK-2420
```

> WARNING: `core/` importing from `services/` is a new direction for this package. If it
> creates a circular import, move `RESERVED_COLUMNS` into `core/persistence.py` (TASK-2417's
> module) and have the mapper import it from there instead. Decide by running the import,
> not by guessing.

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:313
class FormSchema(BaseModel):
    form_uid: uuid.UUID = Field(default_factory=uuid.uuid4)   # line 356
    form_id: str                                              # line 357
    version: str = "1.0"                                      # line 358
    title: LocalizedString                                    # line 359
    sections: list[FormSection]                               # line 361
    submit: SubmitAction | None = None                        # line 362
    meta: dict[str, Any] | None = None                        # line 364
    created_at: datetime | None = None                        # line 365
    tenant: str | None = None                                 # line 366
    metadata: list[FormMetadataField] | None = None           # line 367
    events: FormEventsConfig | None = None                    # line 368
    form_type: FormType = FormType.SIMPLE                     # line 370
    published_version: str | None = None                      # line 372
    is_public: bool = False                                   # line 374
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py - existing validator infrastructure on this model
from pydantic import model_validator          # imported at line 18
# FormSchema already carries at least one @model_validator - locate it with:
#   grep -n "model_validator" packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
# Extend the existing one; do NOT add a competing validator that duplicates its work.
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:257 - metadata keys are already valid Postgres identifiers
class FormMetadataField(BaseModel):
    key: str      # line 292 - docstring 267-271 guarantees identifier-safety
```

### Does NOT Exist

- ~~`FormSchema.persistence`~~ - does NOT exist on `dev`. It is added by TASK-2421. Until that task lands, do not read it off a `FormSchema` instance.
- ~~a target field literally named `schema`~~ - `schema` shadows Pydantic's `BaseModel.schema`. The Postgres target field MUST be named `schema_name`.
- ~~`FormSchema.model_config = ConfigDict(extra="allow")`~~ - do not relax the model config to sneak the field in. Add a real, typed field.
- ~~a `persistence` key inside `FormSchema.meta`~~ - the spec places it as a first-class field, not inside the free-form `meta` bag (`core/schema.py:364`).

---

## Implementation Notes

### Pattern to Follow

Add the field, then extend the existing validator:

```python
class FormSchema(BaseModel):
    ...
    is_public: bool = False                       # existing, line 374
    persistence: FormPersistenceConfig | None = None   # NEW

    @model_validator(mode="after")
    def _validate(self):
        ...                                        # existing checks stay untouched
        if self.persistence is not None and _is_tabular(self.persistence.data):
            for column in column_names_for(self):
                if column in RESERVED_COLUMNS and _is_author_supplied(column):
                    raise ValueError(...)
                validate_identifier(column, kind="column")
        return self
```

### Key Constraints

- Backwards compatibility is an acceptance criterion, not a nicety: a `FormSchema` without `persistence` must behave byte-identically to `dev`.
- Do NOT reorder, rename or retype any existing field - `core/schema.py` is shared.
- Validation must run at construction, so the API returns 422 at form registration.
- Collision detection applies to AUTHOR-supplied names only; the reserved columns the mapper itself emits are not collisions.
- Document-target forms skip column validation entirely.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:313` - the model to extend
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:267-271` - why metadata keys are already identifier-safe
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py` - `RESERVED_COLUMNS`, `column_names_for` (TASK-2420)

---

## Acceptance Criteria

- [ ] `FormSchema(...)` without `persistence` yields `persistence is None` and unchanged behaviour
- [ ] `FormSchema` with a `persistence` block round-trips through `model_dump_json()` -> `model_validate_json()`
- [ ] A `field_id` named `submission_id` on a tabular target raises `ValidationError`
- [ ] A `FormMetadataField.key` colliding with a reserved column raises `ValidationError`
- [ ] A GROUP path producing an invalid identifier raises `ValidationError`
- [ ] The same colliding form is ACCEPTED when the target is a document driver
- [ ] The pre-existing `core/schema.py` test suite still passes unchanged
- [ ] `pytest packages/parrot-formdesigner/tests/ -k schema -v` passes
- [ ] `ruff` and `mypy` clean on `core/schema.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_formschema_persistence.py
import pytest
from pydantic import ValidationError

from parrot_formdesigner.core.schema import FormSchema


class TestFormSchemaPersistence:
    def test_absent_defaults_to_none(self, minimal_form_dict):
        assert FormSchema.model_validate(minimal_form_dict).persistence is None

    def test_roundtrip_with_persistence(self, form_dict_with_persistence):
        form = FormSchema.model_validate(form_dict_with_persistence)
        assert FormSchema.model_validate_json(form.model_dump_json()) == form

    def test_reserved_field_id_rejected(self, form_dict_with_persistence):
        form_dict_with_persistence["sections"][0]["fields"][0]["field_id"] = "submission_id"
        with pytest.raises(ValidationError):
            FormSchema.model_validate(form_dict_with_persistence)

    def test_reserved_metadata_key_rejected(self, form_dict_with_persistence):
        form_dict_with_persistence["metadata"] = [{"key": "form_uid", "source": "constant"}]
        with pytest.raises(ValidationError):
            FormSchema.model_validate(form_dict_with_persistence)

    def test_document_target_skips_column_checks(self, form_dict_with_mongo_persistence):
        form_dict_with_mongo_persistence["sections"][0]["fields"][0]["field_id"] = "submission_id"
        assert FormSchema.model_validate(form_dict_with_mongo_persistence) is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** - verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** - before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source).
   - Confirm every class/method in "Existing Signatures" still has the listed attributes.
   - If anything has changed, update the contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without
     verifying it exists.
4. **Update status** in `sdd/tasks/index/formbuilder-formschema-persistency.json` ->
   `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** -> `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-24
**Notes**: Added `persistence: FormPersistenceConfig | None = None` to
`FormSchema` (after `is_public`), documented it in the class docstring,
and added `_validate_persistence` (a new `@model_validator(mode="after")`,
alongside the existing `_validate_unique_identity`/`_validate_metadata`)
that skips entirely for document `asyncdb` targets (`mongo`/`arango`) and,
for tabular targets, rejects any author-supplied flattened column that
collides with `RESERVED_COLUMNS`; invalid/too-long flattened identifiers
already raise via `column_names_for()`'s own `validate_identifier` calls.
8 new unit tests in `tests/unit/test_formschema_persistence.py`, all
passing; the pre-existing `-k schema` suite (218 tests) still passes
except 2 pre-existing, unrelated failures (`test_field_schema_snippets_
cover_all_types`, `test_endpoint_matches_schema`) confirmed to fail
identically on the pre-task commit via `git stash`.

**Deviations from spec**: The Codebase Contract flagged a likely circular
import from `core/` importing `services/`. It materialized (via
`core/persistence.py`'s top-level `services._identifiers` import
transitively pulling `services/__init__.py` -> ... -> `core.schema`, not
via the `mapper.py` import the contract anticipated). Fixed by deferring
that one import in `core/persistence.py` to call time, matching the
project's own existing lazy-import convention in
`core/schema.py:_validate_metadata`. This touched `core/persistence.py`
(a TASK-2417 file) in addition to the files TASK-2421 lists — necessary
for the feature to import at all, and explicitly anticipated by the
task's own contract note ("decide by running the import, not by
guessing").
