---
type: Wiki Overview
title: 'TASK-1227: FormRegistry.clone_form'
id: doc:sdd-tasks-completed-task-1227-registry-clone-form-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the core task for FEAT-183. It adds a `clone_form` async method to
---

# TASK-1227: FormRegistry.clone_form

**Feature**: FEAT-183 — FormDesigner Clone Form
**Spec**: `sdd/specs/formdesigner-clone-form.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the core task for FEAT-183. It adds a `clone_form` async method to
`FormRegistry` that deep-copies an existing `FormSchema`, assigns a new
`form_id`, resets the version to `"1.0"`, optionally applies an RFC 7396
merge-patch, validates the result, records `cloned_from` provenance in `meta`,
and registers + persists the new form.

Implements spec §2 Overview and §3 Module 1.

---

## Scope

- Add `async def clone_form(...)` to `FormRegistry` in
  `services/registry.py`.
- The method must:
  1. Load the source form via `self.get(source_form_id)`.
  2. Raise `KeyError` if not found.
  3. Check `self.contains(new_form_id)` — raise `ValueError` if already exists.
  4. `model_copy(deep=True)` the source form.
  5. Replace `form_id` with `new_form_id`.
  6. Reset `version` to `"1.0"` and `created_at` to `None`.
  7. Set `meta["cloned_from"]` to the source `form_id` (per resolved Q2).
  8. If `patch` is provided, apply it via `_deep_merge` on the
     `model_dump()`, then `model_validate` the result. Force `form_id`
     back to `new_form_id` after merge (patch cannot override it).
     Strip `created_at` from the merged dict.
  9. Run `FormValidator().check_schema(clone)` — raise `ValueError` with
     the error list if validation fails.
  10. Call `self.register(clone, persist=persist, overwrite=False)`.
  11. Return the cloned `FormSchema`.
- Import `_deep_merge` from `..api._utils` (verified path).
- Import `FormValidator` from `.validators`.
- Add the method to the class's public surface (no `__all__` change needed —
  the module doesn't use `__all__`).

**NOT in scope**: REST endpoint (TASK-1228), tests (TASK-1229).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py` | MODIFY | Add `clone_form` method to `FormRegistry` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_formdesigner.core.schema import FormSchema  # verified: core/schema.py:153
from parrot_formdesigner.services.registry import FormRegistry  # verified: services/registry.py:116
from parrot_formdesigner.services.validators import FormValidator  # verified: services/validators.py:91
from parrot_formdesigner.api._utils import _deep_merge  # verified: api/_utils.py:11
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:                           # line 116
    def __init__(self, storage: FormStorage | None = None) -> None:  # line 133
    _forms: dict[str, FormSchema]             # line 139
    _lock: asyncio.Lock                       # line 140
    _storage: FormStorage | None              # line 141
    logger: logging.Logger                    # line 144

    async def register(
        self, form: FormSchema, *, persist: bool = False, overwrite: bool = True
    ) -> None:                                # line 146

    async def get(self, form_id: str) -> FormSchema | None:  # line 214
    async def contains(self, form_id: str) -> bool:          # line 244

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema(BaseModel):                  # line 153
    form_id: str                              # line 178
    version: str = "1.0"                      # line 179
    title: LocalizedString                    # line 180
    meta: dict[str, Any] | None = None        # line 185
    created_at: datetime | None = None        # line 186
    tenant: str | None = None                 # line 187
    # model_copy(deep=True) → deep clone
    # model_dump() → dict
    # model_validate(dict) → FormSchema

# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
class FormValidator:                          # line 91
    def check_schema(self, form: FormSchema) -> list[str]:  # line 762

# packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py
def _deep_merge(base: dict, patch: dict) -> dict:  # line 11
```

### Does NOT Exist

- ~~`FormRegistry.clone`~~ — does not exist (you are creating `clone_form`)
- ~~`FormRegistry.duplicate`~~ — does not exist
- ~~`FormSchema.clone()`~~ — no such method; use `model_copy(deep=True)`
- ~~`FormStorage.clone`~~ — no clone on the ABC

---

## Implementation Notes

### Pattern to Follow

Follow the same style as `FormRegistry.register()` (line 146): acquire the
lock for state checks, use `self.logger` for debug/info, delegate persistence
to `self.register(persist=...)`.

```python
# Reference: how handle_operations deep-copies a form (api/operations.py:418)
working = form.model_copy(deep=True)
```

```python
# Reference: how patch_form applies merge-patch (api/handlers.py:458-459)
existing_dict = existing.model_dump()
merged = _deep_merge(existing_dict, body)
```

### Key Constraints

- Must be fully async.
- Use `self.logger` for logging.
- The `_deep_merge` import crosses from `services/` into `api/_utils.py` — this
  is acceptable as `_utils.py` is side-effect-free. If preferred, the import
  can be deferred to method body.
- `overwrite=False` on `register` ensures we don't silently overwrite if a
  race condition creates the form between the `contains` check and the
  `register` call.

---

## Acceptance Criteria

- [ ] `FormRegistry.clone_form` exists and is async
- [ ] Deep-copies source form, assigns new `form_id`, resets version to `"1.0"`
- [ ] Sets `created_at=None` on the clone
- [ ] Sets `meta["cloned_from"]` to the source `form_id`
- [ ] Applies optional RFC 7396 merge-patch via `_deep_merge`
- [ ] Patch cannot override `form_id` — it is forced back after merge
- [ ] Raises `KeyError` if source not found
- [ ] Raises `ValueError` if `new_form_id` already exists
- [ ] Raises `ValueError` if `FormValidator.check_schema` returns errors
- [ ] Calls `self.register(persist=persist, overwrite=False)` on success
- [ ] Returns the cloned `FormSchema`

---

## Test Specification

```python
# Tests are in TASK-1229 — this section shows the expected behavior.
import pytest
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot_formdesigner.core.types import FieldType


@pytest.fixture
def sample_form() -> FormSchema:
    return FormSchema(
        form_id="source-form",
        title="Source Form",
        version="2.3",
        sections=[
            FormSection(
                section_id="sec1",
                title="Section 1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="Full Name",
                        required=True,
                    ),
                ],
            ),
        ],
    )


async def test_clone_basic(sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    clone = await registry.clone_form("source-form", "cloned-form")
    assert clone.form_id == "cloned-form"
    assert clone.version == "1.0"
    assert clone.created_at is None
    assert clone.meta["cloned_from"] == "source-form"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-clone-form.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm all imports/signatures are still accurate
4. **Implement** `clone_form` in `registry.py` following the scope above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-1227-registry-clone-form.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: SDD Worker (claude-sonnet-4-6)
**Date**: 2026-05-18
**Notes**: Added `clone_form` async method to `FormRegistry`. Deep-copies the
source form using `model_copy(deep=True)`, assigns `new_form_id`, resets
`version` to "1.0", sets `created_at=None`, records `meta["cloned_from"]`
for provenance, applies optional RFC 7396 merge-patch via `_deep_merge`,
validates with `FormValidator.check_schema`, and calls
`register(persist=persist, overwrite=False)`. All acceptance criteria met.

**Deviations from spec**: none
