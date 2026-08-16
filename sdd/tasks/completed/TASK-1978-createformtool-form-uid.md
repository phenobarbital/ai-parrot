# TASK-1978: CreateFormTool form_uid generation

**Feature**: FEAT-389 — Stable UUID-Based Form Identity
**Spec**: `sdd/specs/form-uid-stable-identity.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-1972, TASK-1973
**Assigned-to**: unassigned

---

## Context

The `CreateFormTool` is the LLM-facing tool for generating forms. Currently it
works with `form_id` (slugs) for identification. It must be updated to generate
and propagate `form_uid` (immutable UUID) through the form creation pipeline.
The `refine_form_id` field is renamed to `refine_form_uid` so refinements
address forms by UUID. Implements Module 6 from the spec.

---

## Scope

- Add `form_uid: str | None = None` field to `CreateFormInput` (Pydantic model):
  - Description: "Optional UUID for the form. Auto-generated if not provided."
  - Default: `None` (auto-generated in `_execute()`).
- Update `_execute()`:
  - If `form_uid` is not provided, generate one: `form_uid = str(uuid.uuid4())`.
  - Pass `form_uid` through to the `FormSchema` constructor.
- Update `_generate_with_retry()`:
  - After LLM generates the form schema JSON, inject `form_uid` into the result
    before constructing `FormSchema`.
- Rename `refine_form_id` field to `refine_form_uid`:
  - Type stays `str | None`.
  - When set, lookup the form by UUID (via registry `get()`) instead of slug.
- Update `ToolResult.metadata` to include `form_uid` in the returned metadata dict.
- Add `import uuid` if not already present.

**NOT in scope**: Storage changes (TASK-1974), API route changes (TASK-1976),
registry changes (TASK-1973 handles that).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py` | MODIFY | Add `form_uid` to input, update generation pipeline, rename `refine_form_id` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Sole caller of `refine_form_id=` (in `edit_form`) updated to the new `refine_form_uid=` kwarg name. |
| `packages/parrot-formdesigner/tests/unit/test_create_form_tool.py` | MODIFY | Renamed `refine_form_id=` call sites to `refine_form_uid=`; added `TestCreateFormToolFormUid` (6 new tests) per this task's own Test Specification. |
| `packages/parrot-formdesigner/tests/test_create_form_toolkit.py` | MODIFY | Renamed the one `refine_form_id=` call site to `refine_form_uid=`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field  # verified: used in create_form.py
from parrot_formdesigner.core.schema import FormSchema  # verified: create_form.py imports
import uuid  # stdlib — add if not present
```

### Existing Signatures to Use
```python
# CORRECTED (2026-07-31) via full read of tools/create_form.py — the
# original contract's _execute/_generate_with_retry signatures and
# _slugify's binding were WRONG. Actual, verified signatures:

# tools/create_form.py:223
class CreateFormInput(BaseModel):
    prompt: str                          # line 233
    form_id: str | None = None           # line 237
    persist: bool = False                # line 241 (default False, not True)
    refine_form_id: str | None = None    # line 245

# tools/create_form.py:183 — MODULE-LEVEL function, NOT a method.
def _slugify(text: str) -> str: ...

# tools/create_form.py:259
class CreateFormTool(AbstractTool):
    # __init__: line 286
    def __init__(self, client, registry=None, model=None, *, tenant=None, **kwargs): ...

    # _execute: line 322 — takes UNPACKED kwargs, NOT a CreateFormInput
    # instance. CreateFormInput is only `args_schema` (LLM tool-calling
    # introspection/validation) — the actual runtime call path is
    # AbstractTool.execute(**kwargs) -> _execute(**kwargs).
    async def _execute(
        self,
        prompt: str,
        form_id: str | None = None,
        persist: bool = False,
        refine_form_id: str | None = None,
        **kwargs: Any,
    ) -> ToolResult: ...
        # existing = await self._registry.get(refine_form_id, tenant=self._tenant)  -- line 345
        # effective_form_id = form_id or refine_form_id  -- lines 375, 379 (BUG once
        #   refine_form_id becomes a UUID: this would inject the UUID into the
        #   FormSchema's form_id/slug field. Must derive from existing.form_id instead.)
        # overwrite = refine_form_id is not None  -- line 404
        # ToolResult(result={"form_id": form.form_id, ...}, metadata={"form": form.model_dump(), ...})  -- lines 411-419

    # _generate_with_retry: line 505 — takes messages + form_id, returns
    # FormSchema | None (NOT a dict).
    async def _generate_with_retry(
        self, messages: list[dict[str, str]], form_id: str | None,
    ) -> FormSchema | None: ...
        # data["form_id"] = form_id  -- line 531 (or _slugify(title) fallback, line 534)
        # form = FormSchema.model_validate(data)  -- line 536
```

### Does NOT Exist
- ~~`CreateFormInput.form_uid`~~ — does not exist. This task adds it.
- ~~`CreateFormInput.refine_form_uid`~~ — does not exist. `refine_form_id`
  is renamed to this.
- ~~`uuid` import in create_form.py~~ — verify; likely needs to be added.

---

## Implementation Notes

### `CreateFormInput` changes
```python
class CreateFormInput(BaseModel):
    prompt: str = Field(..., description="...")
    form_id: str | None = Field(default=None, description="Human-readable slug")
    form_uid: str | None = Field(
        default=None,
        description="Optional UUID for the form. Auto-generated if not provided."
    )
    persist: bool = Field(default=True, description="...")
    refine_form_uid: str | None = Field(
        default=None,
        description="UUID of an existing form to refine (replaces refine_form_id)."
    )
```

### `_execute()` changes
```python
async def _execute(self, input_data: CreateFormInput) -> ToolResult:
    form_uid = input_data.form_uid or str(uuid.uuid4())
    # ... pass form_uid through to FormSchema construction
    # ... include in ToolResult.metadata
    return ToolResult(
        result=...,
        metadata={"form_uid": form_uid, "form_id": form_id, ...}
    )
```

### `_generate_with_retry()` changes
```python
async def _generate_with_retry(self, prompt, ..., form_uid: str = None) -> dict:
    result = await self._call_llm(prompt)
    # Inject form_uid into the LLM result dict
    if form_uid:
        result["form_uid"] = form_uid
    return result
```

### Backward Compatibility
- `refine_form_id` removal: if there are external callers using this field,
  consider keeping it as a deprecated alias. Check for usages first.
- `form_id` field remains for slug purposes — `form_uid` is additive.

### Key Constraints
- The LLM does NOT generate `form_uid` — it is always injected by the tool code.
- `_slugify()` continues to generate `form_id` (slug) — no change needed there.
- `ToolResult.metadata` must include both `form_uid` and `form_id`.

---

## Acceptance Criteria

- [ ] `CreateFormInput` has `form_uid: str | None = None` field
- [ ] `CreateFormInput.refine_form_id` is renamed to `refine_form_uid`
- [ ] `_execute()` auto-generates `form_uid` if not provided
- [ ] `_execute()` passes `form_uid` to `FormSchema` construction
- [ ] `_generate_with_retry()` injects `form_uid` into LLM result
- [ ] `ToolResult.metadata` includes `form_uid`
- [ ] Existing form creation without explicit `form_uid` still works (auto-gen)
- [ ] Refinement via `refine_form_uid` looks up by UUID

---

## Test Specification
```python
import pytest

@pytest.mark.asyncio
async def test_create_form_auto_generates_uid(create_form_tool):
    """CreateFormTool generates form_uid when not provided."""
    input_data = CreateFormInput(prompt="Create a contact form")
    result = await create_form_tool._execute(input_data)
    assert "form_uid" in result.metadata
    # Verify it's a valid UUID
    import uuid
    uuid.UUID(result.metadata["form_uid"])  # Should not raise

@pytest.mark.asyncio
async def test_create_form_with_explicit_uid(create_form_tool):
    """CreateFormTool uses provided form_uid."""
    uid = "550e8400-e29b-41d4-a716-446655440000"
    input_data = CreateFormInput(prompt="Create a form", form_uid=uid)
    result = await create_form_tool._execute(input_data)
    assert result.metadata["form_uid"] == uid

@pytest.mark.asyncio
async def test_refine_form_uid_lookup(create_form_tool):
    """refine_form_uid looks up existing form by UUID."""
    uid = "550e8400-e29b-41d4-a716-446655440000"
    input_data = CreateFormInput(
        prompt="Add an email field",
        refine_form_uid=uid
    )
    # Should attempt to load existing form by UUID
    result = await create_form_tool._execute(input_data)
    assert result is not None

def test_create_form_input_has_form_uid_field():
    """CreateFormInput schema includes form_uid."""
    fields = CreateFormInput.model_fields
    assert "form_uid" in fields
    assert "refine_form_uid" in fields
    assert "refine_form_id" not in fields  # Renamed
```

---

## Agent Instructions

1. Read this task file and the spec (Module 6).
2. Read `tools/create_form.py` in full.
3. Verify TASK-1972 is complete (`FormSchema.form_uid` exists).
4. Verify TASK-1973 is complete (`FormRegistry.get()` accepts `form_uid`).
5. Grep for all references to `refine_form_id` across the codebase to check for callers.
6. Implement all scope items.
7. Run existing tests: `pytest packages/parrot-formdesigner/tests/ -v -k create_form`
8. Add new tests per test specification.
9. Commit with message: `sdd: TASK-1978 — CreateFormTool form_uid generation`
10. Update this task status to `done`.

---

## Completion Note

Implemented largely as specified, on top of a substantially corrected
Codebase Contract (documented inline in this file): the original contract
assumed `_execute(self, input_data: CreateFormInput) -> ToolResult` and
`_generate_with_retry(self, prompt, ...) -> dict`, and a bound
`self._slugify()` — all wrong. The real calling convention is
`_execute(self, prompt, form_id=None, persist=False, refine_form_id=None,
**kwargs)` (unpacked kwargs; `CreateFormInput` is only `args_schema` for
LLM tool-calling introspection), `_generate_with_retry` returns
`FormSchema | None`, and `_slugify()` is a module-level function.

Added `form_uid: str | None` to `CreateFormInput` and to `_execute()`'s
signature; renamed `refine_form_id` → `refine_form_uid` throughout
(`CreateFormInput`, `_execute()`'s parameter, all internal references,
logging, error messages, the `overwrite = refine_form_uid is not None`
check). `_generate_with_retry()` gained a `form_uid` parameter, injected
into the LLM-generated dict before `FormSchema.model_validate()` — the LLM
itself never sees or generates `form_uid`, per the spec's Key Constraints.
`ToolResult.metadata` now includes a top-level `"form_uid"` key (in
addition to the nested `metadata["form"]["form_uid"]`, which was already
present via `form.model_dump()` since TASK-1972).

**Real bug found and fixed**: the pre-existing line
`effective_form_id = form_id or refine_form_id` reused the refinement
identifier AS THE NEW FORM'S SLUG when no explicit `form_id` was given.
Before FEAT-389 this was harmless (`refine_form_id` WAS a slug). Now that
the refinement identifier is a UUID (`refine_form_uid`), naively reusing
it would inject a UUID string into the `form_id`/slug field. Fixed by
deriving the slug from `existing.form_id` instead
(`effective_form_id = form_id or existing.form_id`) when refining — the
slug is preserved (or explicitly overridden), never replaced by the
form_uid. **Also**: `form_uid` is now correctly held constant across a
refinement (`effective_form_uid = existing.form_uid`, ignoring any
`form_uid=` kwarg during refinement) — a refinement changes content and
optionally the slug, but never the immutable identity.

**Consumer audit** (per the task's own instruction to grep for
`refine_form_id` callers first): found exactly one production caller —
`api/handlers.py::edit_form()` (already using `refine_form_id=form_uid` as
a stopgap per TASK-1976's completion note) — updated to
`refine_form_uid=form_uid`. Two test files
(`tests/unit/test_create_form_tool.py`,
`tests/test_create_form_toolkit.py`) had 3 more call sites, all using
fully-mocked registries where the exact identifier string is opaque to
the mock — renamed the keyword only, values unchanged.

**New tests**: added `TestCreateFormToolFormUid` (6 tests) to
`test_create_form_tool.py` — auto-generation, explicit UID, uniqueness
across two forms, refinement identity preservation (including that the
slug survives unchanged too), and the `CreateFormInput` schema-shape
assertion from the task's own Test Specification.

All 25 `-k create_form` tests pass (17 in `test_create_form_tool.py`
alone). Full `pytest tests/unit/` and `tests/integration/` suites: zero
new failures, zero previously-broken tests fixed this time (this task's
blast radius was small — a single production caller). Ruff: identical
error count (52) to baseline.
