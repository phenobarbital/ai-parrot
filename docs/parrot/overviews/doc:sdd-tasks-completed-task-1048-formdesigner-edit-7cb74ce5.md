---
type: Wiki Overview
title: 'TASK-1048: `PATCH /api/v1/forms/{id}/operations` — atomic batched edit API'
id: doc:sdd-tasks-completed-task-1048-formdesigner-edit-operations-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wave 2d of FEAT-152 — parallelizable with TASK-1045 / 1046 / 1047.
---

# TASK-1048: `PATCH /api/v1/forms/{id}/operations` — atomic batched edit API

**Feature**: FEAT-152 — parrot-formdesigner Structural Refactor
**Spec**: `sdd/specs/formdesigner-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1044
**Assigned-to**: unassigned

---

## Context

Wave 2d of FEAT-152 — parallelizable with TASK-1045 / 1046 / 1047.

Replaces the Wave 1 `501 Not Implemented` stub at
`api/operations.py` (created by TASK-1042) with the full atomic
batched-edit endpoint described in spec §2 Internal Behavior — Edit
operations PATCH.

Per Q1 (resolved): V1 supports optional optimistic concurrency via
`If-Match: <version>` header (returns `412 Precondition Failed` on
mismatch).
Per Q2 (resolved): the existing PUT (`update_form`) and RFC-7396 PATCH
(`patch_form`) endpoints stay alongside `/operations` — full-replace
and merge-patch use cases differ from granular UI edits.

Spec sections: §1 Goals (transactional batched-edit endpoint); §2
Internal Behavior — Edit operations PATCH (full algorithm); §2 Data
Models (operations envelope discriminated union); §3 Module 9; §6
Codebase Contract; §8 Q1, Q2.

---

## Scope

1. **Replace the stub body** of
   `packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py`
   (created by TASK-1042 returning 501) with the real implementation.

2. **Pydantic operation models** — define the discriminated union per
   spec §2 Data Models:
   - `_OpBase(BaseModel)` with `op: str` discriminator.
   - `AddSection`, `AddField`, `MoveField`, `RemoveField`,
     `UpdateField`, `UpdateSectionMeta`, `UpdateFormMeta`,
     `DuplicateField`.
   - `Operation = Annotated[Union[...], Field(discriminator="op")]`.
   - `OperationsEnvelope(BaseModel)` with `operations: list[Operation]`.
   - Note: Pydantic does not allow Python's `from` keyword as a field
     name. Use `from_: dict = Field(alias="from")` in `MoveField` and
     `DuplicateField`. Set
     `model_config = ConfigDict(populate_by_name=True)`.

3. **Per-op apply functions** — pure helpers in `operations.py`:
   ```python
   def _apply_add_section(form: FormSchema, op: AddSection) -> FormSchema: ...
   def _apply_add_field(form: FormSchema, op: AddField) -> FormSchema: ...
   def _apply_move_field(form: FormSchema, op: MoveField) -> FormSchema: ...
   def _apply_remove_field(form: FormSchema, op: RemoveField) -> FormSchema: ...
   def _apply_update_field(form: FormSchema, op: UpdateField) -> FormSchema: ...
   def _apply_update_section_meta(form: FormSchema, op: UpdateSectionMeta) -> FormSchema: ...
   def _apply_update_form_meta(form: FormSchema, op: UpdateFormMeta) -> FormSchema: ...
   def _apply_duplicate_field(form: FormSchema, op: DuplicateField) -> FormSchema: ...
   ```
   Each function:
   - Operates on a Pydantic-deep-copied working copy
     (`form.model_copy(deep=True)`).
   - Raises `OperationError(index, op_name, message)` on failure.
   - Validates `field_id` uniqueness within section for any op that
     adds or moves a field.
   - Uses `_deep_merge` (from `api/_utils.py`) for `update_*` ops.

4. **Handler** — `async def handle_operations(request) -> web.Response`:
   1. Parse `form_id` from match_info.
   2. Load form: `form = await registry.get(form_id)`. If `None`,
      return 404.
   3. Read body, validate against `OperationsEnvelope`. On
      `ValidationError`, return 422 with the Pydantic error list.
   4. **`If-Match` check (Q1)**: if `If-Match` header is present and
      its value (after stripping quotes) does NOT equal `form.version`,
      return 412 with `{"detail": "version mismatch", "current":
      form.version}`.
   5. Apply ops sequentially on a working copy. On the first
      `OperationError`, return 422 with `{"errors": [{"index":
      e.index, "op": e.op_name, "message": e.message}]}` and the
      original form unchanged in the registry.
   6. Run `FormValidator.check_schema(working_copy)`; on non-empty
      result, return 422 with `{"errors": [{"index": null, "op":
      null, "message": err} for err in result]}`.
   7. Bump version: `working_copy.version = _bump_version(form.version)`.
   8. `await registry.register(working_copy, persist=True,
      overwrite=True)`.
   9. Return 200 with `{"form": working_copy.model_dump()}`.

5. **Logging** — every code path logs at INFO when a request
   succeeds, WARNING when it fails. Use module-level
   `logger = logging.getLogger(__name__)`.

6. **Tests** at
   `packages/parrot-formdesigner/tests/unit/api/test_operations.py`
   and `tests/integration/test_operations_e2e.py`:
   - Discriminator picks the right `Operation` subclass per `op`
     value.
   - Atomic-failure: two ops where the second's target is missing
     → 422, `errors[0].index == 1`, registry form unchanged.
   - Duplicate `field_id` within a section blocked at apply time →
     422.
   - Successful round-trip: add_section + add_field + move_field
     leaves the form in the expected shape; `version` bumps.
   - `If-Match: <wrong-version>` → 412.
   - `If-Match: <correct-version>` → 200.
   - Circular `depends_on` introduced by an op → 422 from the
     post-apply `FormValidator.check_schema` step.

**NOT in scope:**
- Cross-request distributed locking. Atomicity is per-request only,
  per spec §7 Known Risks. Concurrent unconditional PATCH = last-write
  wins.
- Operation history / undo / audit log — not in V1.
- Op types not listed above (e.g. `move_section`, `remove_section`)
  — Wave 2d delivers exactly the ops in the spec §2 Internal Behavior
  example. Add only those.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py` | MODIFY | Replace 501 stub with real impl |
| `packages/parrot-formdesigner/tests/unit/api/test_operations.py` | CREATE | Per-op + envelope unit tests |
| `packages/parrot-formdesigner/tests/integration/test_operations_e2e.py` | CREATE | Round-trip via aiohttp client |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:21,68,108
from parrot_formdesigner.services.registry import FormRegistry
# verified: services/registry.py:105
from parrot_formdesigner.services.validators import FormValidator
# verified: services/validators.py:66; check_schema at line 446
from parrot_formdesigner.api._utils import _deep_merge, _bump_version
# from TASK-1042 — verify these exist before importing
from pydantic import BaseModel, Field, ConfigDict, ValidationError
from typing import Annotated, Literal, Union, Any
from aiohttp import web
import logging
```

### `FormRegistry` methods used

```python
# services/registry.py
async def get(self, form_id: str) -> FormSchema | None: ...        # line 203
async def register(self, form: FormSchema, *, persist: bool = False,
                   overwrite: bool = True) -> None: ...            # line 135
```

### `FormValidator.check_schema` signature

```python
# services/validators.py:446
def check_schema(self, form: FormSchema) -> list[str]: ...
# Returns list of error strings. EMPTY list == valid.
# Currently only detects circular depends_on cycles.
```

### Helpers from `api/_utils.py` (created by TASK-1042)

```python
def _deep_merge(base: dict, patch: dict) -> dict: ...   # RFC 7396 merge
def _bump_version(version: str) -> str: ...             # "1.0" → "1.1"
def _loc_to_str(value: object) -> str | None: ...       # not used by this task
```

### `FormSchema.version`

```python
# core/schema.py:130
version: str = "1.0"
# Bump rule: increment minor; "_bump_version" handles the parsing.
```

### Does NOT Exist (Anti-Hallucination)

- ~~`FormValidator.validate_operations(envelope)`~~ — does NOT
  exist. Per-op validation lives in this task's `_apply_*` functions.
- ~~`FormSchema.copy_with(...)`~~, ~~`FormField.bump()`~~ — not
  methods on the models. Use `model_copy(deep=True)` (Pydantic v2)
  and the `_bump_version` helper.
- ~~`FormSection.find_field(field_id)`~~ — does NOT exist. Iterate
  `section.fields` and match on `field_id` yourself.
- ~~A `move_section` op~~ — out of scope per spec. Don't add it
  even if it seems trivially adjacent.
- ~~`registry.update(form_id, form)`~~ — `FormRegistry` has no
  `update` method. Use `register(working_copy, persist=True,
  overwrite=True)`.
- ~~`request.headers["If-Match"]` always present~~ — it's optional;
  use `request.headers.get("If-Match")`.
- ~~`web.HTTPPreconditionFailed`~~ — `aiohttp` doesn't ship that
  exception. Just return `web.json_response(..., status=412)`.

---

## Implementation Notes

### `OperationError` exception shape

```python
class OperationError(Exception):
    def __init__(self, index: int, op_name: str, message: str):
        self.index = index
        self.op_name = op_name
        self.message = message
        super().__init__(f"op[{index}] ({op_name}): {message}")
```

### Atomicity pattern

```python
working = form.model_copy(deep=True)
for i, op in enumerate(envelope.operations):
    try:
        working = _DISPATCH[op.op](working, op)
    except OperationError as e:
        return web.json_response(
            {"errors": [{"index": e.index, "op": e.op_name, "message": e.message}]},
            status=422,
        )
errors = FormValidator().check_schema(working)
if errors:
    return web.json_response(
        {"errors": [{"index": None, "op": None, "message": err} for err in errors]},
        status=422,
    )
working.version = _bump_version(form.version)
await registry.register(working, persist=True, overwrite=True)
return web.json_response({"form": working.model_dump()}, status=200)
```

The `_DISPATCH = {"add_section": _apply_add_section, ...}` map can
be defined at module load.

### `If-Match` parsing

```python
if_match = request.headers.get("If-Match")
if if_match is not None:
    candidate = if_match.strip('"').strip("'")
    if candidate != form.version:
        return web.json_response(
            {"detail": "version mismatch", "current": form.version},
            status=412,
        )
```

(Strong vs weak ETag distinction is not relevant here — `version` is
opaque to the consumer.)

### Key Constraints

- Use `model_copy(deep=True)` (Pydantic v2) for the working copy.
- Validate `field_id` uniqueness per section AS PART OF the per-op
  apply, not via `FormValidator` (which doesn't check this).
- Never mutate the original `form` returned by `registry.get()`.
- `update_field`, `update_section_meta`, `update_form_meta` use
  `_deep_merge`. After merging, re-validate via
  `FormField.model_validate(...)` / `FormSection.model_validate(...)`
  to catch any merged value that breaks the schema.
- Logger pattern matches the rest of the package.

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.api.operations import handle_operations`
      succeeds.
- [ ] `OperationsEnvelope` with `op: "add_section"` validates as an
      `AddSection`; with `op: "move_field"` as `MoveField`; etc.
- [ ] `PATCH /api/v1/forms/{id}/operations` with a valid envelope
      returns 200 + bumped version (`form.version`).
- [ ] Two ops where the second targets a missing `field_id` →
      registry form unchanged, response is 422 with `errors[0].index
      == 1`.
- [ ] An op that introduces a duplicate `field_id` within a section
      → 422 with the offending op's index.
- [ ] An op that introduces a circular `depends_on` → 422 from the
      post-apply `FormValidator.check_schema()` step.
- [ ] `If-Match: 1.0` when registry has version `1.1` → 412 with
      `{"detail": "version mismatch", "current": "1.1"}`.
- [ ] `If-Match: 1.1` when registry has version `1.1` → 200, version
      bumps to `1.2`.
- [ ] `update_form_meta` op merges into `form.meta` via RFC 7396
      semantics and the result re-validates as a `FormSchema`.
- [ ] All tests in `tests/unit/api/test_operations.py` and
      `tests/integration/test_operations_e2e.py` pass.
- [ ] No linting errors:
      `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py`.

---

## Test Specification

```python
# tests/unit/api/test_operations.py
import pytest
from parrot_formdesigner.api.operations import (
    OperationsEnvelope, AddSection, AddField, MoveField, _apply_add_field,
    OperationError,
)
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot_formdesigner.core.types import FieldType


@pytest.fixture
def form() -> FormSchema:
    return FormSchema(
        form_id="t", version="1.0", title={"en": "T"},
        sections=[FormSection(section_id="s1", fields=[
            FormField(field_id="name", field_type=FieldType.TEXT,
                      label={"en": "N"}),
        ])],
    )


def test_envelope_discriminates():
    env = OperationsEnvelope.model_validate({
        "operations": [
            {"op": "add_section",
             "section": {"section_id": "s2", "fields": []}, "position": 0},
        ],
    })
    assert isinstance(env.operations[0], AddSection)


def test_add_field_duplicate_rejected(form):
    op = AddField.model_validate({
        "op": "add_field", "section_id": "s1",
        "field": {"field_id": "name", "field_type": "text",
                  "label": {"en": "Dup"}},
    })
    with pytest.raises(OperationError):
        _apply_add_field(form, op)


# tests/integration/test_operations_e2e.py
import pytest
from aiohttp import web
from parrot_formdesigner.api import setup_form_api
from parrot_formdesigner.services.registry import FormRegistry
# ... build app + register sample form ...

async def test_atomic_failure_no_change(aiohttp_client, sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    app = web.Application()
    setup_form_api(app, registry)
    client = await aiohttp_client(app)
    resp = await client.patch(
        f"/api/v1/forms/{sample_form.form_id}/operations",
        json={"operations": [
            {"op": "add_section", "section": {"section_id": "x", "fields": []}},
            {"op": "remove_field", "section_id": "MISSING", "field_id": "no"},
        ]},
    )
    assert resp.status == 422
    body = await resp.json()
    assert body["errors"][0]["index"] == 1
    # registry unchanged
    again = await registry.get(sample_form.form_id)
    assert len(again.sections) == len(sample_form.sections)


async def test_if_match_mismatch_412(aiohttp_client, sample_form):
    # ... boot ...
    resp = await client.patch(
        f"/api/v1/forms/{sample_form.form_id}/operations",
        headers={"If-Match": "0.9"},
        json={"operations": []},
    )
    assert resp.status == 412
```

---

## Agent Instructions

1. Read the spec, especially §2 Internal Behavior — Edit operations
   PATCH (the algorithm) and §2 Data Models (the discriminated
   union).
2. Verify TASK-1044 completed — Wave 1 is done; the 501 stub is in
   place at `api/operations.py`.
3. Verify `api/_utils.py` exposes `_deep_merge` and `_bump_version`
   (TASK-1042 contract).
4. Implement the Pydantic models, then the per-op apply functions,
   then the handler.
5. Move this task to `sdd/tasks/completed/`, update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-05-07
**Notes**:
- Replaced the Wave 1 501 stub at `api/operations.py` with the full implementation.
- Pydantic discriminated-union models for all 8 ops (`AddSection`, `AddField`, `MoveField`, `RemoveField`, `UpdateField`, `UpdateSectionMeta`, `UpdateFormMeta`, `DuplicateField`); `MoveField` and `DuplicateField` use `Field(alias="from")` + `populate_by_name=True` to handle the Python keyword.
- Per-op apply functions raise `OperationError(index, op_name, message)` for any per-op failure including duplicate `field_id` within a section / unknown section / unknown field.
- `_DISPATCH` map drives the op execution; atomicity is per-request (first failure aborts, registry unchanged).
- Post-apply runs `FormValidator.check_schema(working_copy)` for circular `depends_on` detection; on failure returns 422 with `index: null`.
- **Q1 RESOLVED**: `If-Match` header (optional) supports optimistic concurrency. Mismatched version returns 412 with `{detail: "version mismatch", current: <version>}`. Quote-stripping handles ETag-style values.
- **Q2 RESOLVED**: existing PUT (`update_form`) and RFC-7396 PATCH (`patch_form`) endpoints stay alongside `/operations` — different use cases.
- After all ops apply successfully, `_bump_version` increments the version and `registry.register(working_copy, persist=True, overwrite=True)` persists.
- Removed `tests/unit/api/test_operations_stub.py` (TASK-1042 placeholder, no longer needed).
- Tests: 18 unit (all 8 op types covered + duplicate/missing rejection + RFC-7396 null-deletion) + 9 integration (round-trip, atomic failure, duplicate, circular, If-Match, 404, 422 envelope, move). All pass.
- **Final state**: full FEAT-152 test suite — 256 passed, 1 pre-existing failure (`test_example_form_server_is_short`, unrelated to FEAT-152, asserts unrelated example file's line count).
- Set `completed_at` on the per-spec index header to mark FEAT-152 as feature-complete.
