# TASK-2432: `UnknownFieldsPolicy` enum + `FormSchema.unknown_fields`

**Feature**: FEAT-458 — Unknown-Field Capture Policy for Form Submissions
**Spec**: `sdd/specs/formdesigner-unknown-fields-capture.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none *(externally blocked — see Context)*
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 1

---

## Context

The single declaration that makes the whole feature opt-in. Everything else in
FEAT-458 reads this field; nothing else works without it.

> ⚠️ **BLOCKED ON FEAT-457** (`formbuilder-formschema-persistency`, 15 tasks,
> all `in-progress` as of 2026-08-24). Do NOT start this task until FEAT-457 has
> merged to `dev`. See the spec's Worktree Strategy for why: it is both a line
> collision and a semantic dependency.

FEAT-457/TASK-2421 adds `FormSchema.persistence` *"after `is_public` (currently
`core/schema.py:374`)"* — byte-for-byte this task's insertion point, and its own
task text calls `core/schema.py` *"the hottest shared file in this package"*.
Land after it and insert below `persistence`.

Implements spec section 3 Module 1.

---

## Scope

- Add `class UnknownFieldsPolicy(str, Enum)` to `core/schema.py` with exactly three
  members: `DROP = "drop"`, `KEEP = "keep"`, `REJECT = "reject"`.
- Add `unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP` to
  `FormSchema`, positioned AFTER `persistence` (FEAT-457) with a
  `# FEAT-458 — Unknown-Field Capture` comment, matching how `# FEAT-241 — Public
  Forms` marks `is_public` (`core/schema.py:373-374`).
- Export `UnknownFieldsPolicy` from wherever `FormType` is already exported
  (check `core/__init__.py` and the package `__init__.py`; add it to the same
  `__all__` lists).
- Write unit tests in `packages/parrot-formdesigner/tests/unit/core/test_unknown_fields_policy.py`.

**NOT in scope**: Any validator, handler, storage, renderer, or sink change. Any
`@model_validator` addition — the default makes this purely additive. Reserving
`extra_data` in `RESERVED_COLUMNS` (that is TASK-2438).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | `UnknownFieldsPolicy` enum + `FormSchema.unknown_fields` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` | MODIFY | Export the enum alongside `FormType` |
| `packages/parrot-formdesigner/tests/unit/core/test_unknown_fields_policy.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase. Use these exact
> names. Do NOT invent an import, attribute, or method not listed here.

### Verified Imports

```python
# core/schema.py already imports what this task needs — verified at its import block:
from enum import Enum                      # already present (FormType uses it, :26)
from pydantic import BaseModel, ConfigDict, Field, model_validator
```

### Existing Signatures to Use

```python
# core/schema.py:26 — the precedent to copy for a schema-level str Enum in THIS module
class FormType(str, Enum): ...

# core/schema.py:313 — NOTE: FormSchema sets NO model_config / extra="forbid",
# so adding a field is purely additive and legacy JSON keeps loading.
class FormSchema(BaseModel):
    ...
    form_type: FormType = FormType.SIMPLE          # line 370
    product_bindings: list[str] | None = None      # line 371
    published_version: str | None = None           # line 372
    # FEAT-241 — Public Forms                      # line 373
    is_public: bool = False                        # line 374  ← FEAT-457 inserts `persistence` after this
    def iter_all_fields(self) -> Iterator[FormField]: ...        # line 376
    def iter_fields_recursive(self) -> Iterator[FormField]: ...  # line 389
    @model_validator(mode="after")
    def _validate_unique_identity(self) -> "FormSchema": ...     # ~line 398

# core/schema.py — extra="forbid" is on these THREE models only (form DEFINITION
# strictness, NOT the submission payload). Do not add it to FormSchema.
#   FormField          model_config = ConfigDict(extra="forbid")   # line 78
#   FormSubsection     model_config = ConfigDict(extra="forbid")   # line 123
#   FormMetadataField  model_config = ConfigDict(extra="forbid")   # line 290
```

### Does NOT Exist

- ~~`FormSchema.unknown_fields`~~ / ~~`FormSchema.extra_fields`~~ — no such field today.
- ~~`UnknownFieldsPolicy`~~ — the enum does not exist anywhere in the repo.
- ~~`FormSchema.model_config`~~ — `FormSchema` has no `model_config` at all.
- ~~`RestCallbackInput.extra_fields` as a precedent~~ — it exists
  (`services/rest_field_resolver.py:235`) but is the outbound extra args of a REST
  *field resolver* call, unrelated to submission extras. That clash is exactly why
  this field is named `unknown_fields`.
- ~~`FormSchema.persistence`~~ — planned by FEAT-457/TASK-2421, **not landed**.
  Verify it exists before positioning the new field after it.

---

## Implementation Notes

### Pattern to Follow

```python
# core/schema.py — mirror FormType's shape (:26) and is_public's comment style (:373)
class UnknownFieldsPolicy(str, Enum):
    """Policy for top-level submission keys the schema does not declare."""

    DROP = "drop"       # discard silently (default — pre-FEAT-458 behaviour)
    KEEP = "keep"       # capture into FormSubmission.extra_data, subject to caps
    REJECT = "reject"   # fail the submission with 422
```

### Key Constraints

- `str, Enum` (not `StrEnum`) — matches `FormType` and keeps pydantic v2
  serialization identical to the rest of this module.
- The default MUST be `DROP`. It is the whole no-breaking-change guarantee (AC1/AC2).
- Google-style docstrings on the enum and each member's intent.

### References in Codebase

- `core/schema.py:26` — `FormType`, the enum pattern.
- `core/schema.py:373-374` — `# FEAT-241 — Public Forms` / `is_public`, the
  feature-comment + field style to copy.

---

## Acceptance Criteria

- [ ] `UnknownFieldsPolicy` has exactly `DROP`/`KEEP`/`REJECT`, serializing to
      `"drop"`/`"keep"`/`"reject"`.
- [ ] `FormSchema()` built without `unknown_fields` yields `UnknownFieldsPolicy.DROP`
      (spec AC2).
- [ ] A `FormSchema` JSON document written before this feature (no `unknown_fields`
      key) validates and defaults to `DROP` (spec AC2).
- [ ] `model_dump()` → `FormSchema(**dump)` round-trips the policy.
- [ ] `from parrot_formdesigner.core.schema import UnknownFieldsPolicy` works, and
      the enum is exported wherever `FormType` is.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/core/test_unknown_fields_policy.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/core/test_unknown_fields_policy.py
import pytest
from parrot_formdesigner.core.schema import FormSchema, UnknownFieldsPolicy


def test_policy_enum_values():
    """Members serialize as the three wire strings."""
    assert UnknownFieldsPolicy.DROP.value == "drop"
    assert UnknownFieldsPolicy.KEEP.value == "keep"
    assert UnknownFieldsPolicy.REJECT.value == "reject"
    assert len(UnknownFieldsPolicy) == 3


def test_formschema_defaults_to_drop(minimal_form_kwargs):
    """A form authored without the field gets DROP — the no-breaking-change guarantee."""
    form = FormSchema(**minimal_form_kwargs)
    assert form.unknown_fields is UnknownFieldsPolicy.DROP


def test_formschema_accepts_string_policy(minimal_form_kwargs):
    """The wire form ("keep") coerces to the enum."""
    form = FormSchema(**minimal_form_kwargs, unknown_fields="keep")
    assert form.unknown_fields is UnknownFieldsPolicy.KEEP


def test_formschema_rejects_unknown_policy(minimal_form_kwargs):
    """An invalid policy string fails at authoring time."""
    with pytest.raises(ValueError):
        FormSchema(**minimal_form_kwargs, unknown_fields="capture-everything")


def test_formschema_roundtrip_preserves_policy(minimal_form_kwargs):
    """model_dump -> FormSchema keeps the policy."""
    form = FormSchema(**minimal_form_kwargs, unknown_fields="reject")
    assert FormSchema(**form.model_dump()).unknown_fields is UnknownFieldsPolicy.REJECT


def test_legacy_form_json_loads(minimal_form_kwargs):
    """Stored form JSON with no unknown_fields key still validates (spec AC2)."""
    dumped = FormSchema(**minimal_form_kwargs).model_dump(mode="json")
    dumped.pop("unknown_fields", None)
    assert FormSchema(**dumped).unknown_fields is UnknownFieldsPolicy.DROP
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-unknown-fields-capture.spec.md` for full context.
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code: confirm each import
   still resolves and each listed signature still has the listed attributes. Line
   numbers were verified on `dev` at `72490fa14` (2026-08-24) and WILL drift once
   FEAT-456/FEAT-457 land — re-`grep` rather than trusting a number.
4. **Update status** in `sdd/tasks/index/formdesigner-unknown-fields-capture.json` → `"in-progress"`.
5. **Implement** following the scope and contract above. Nothing outside scope.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
