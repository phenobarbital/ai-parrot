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
# tools/create_form.py:223
class CreateFormInput(BaseModel):
    prompt: str                          # line 233
    form_id: str | None = None           # line 237
    persist: bool = True                 # line 241
    refine_form_id: str | None = None    # line 245

# tools/create_form.py:259
class CreateFormTool:
    # __init__: line 286
    def __init__(self, ...): ...

    # _execute: line 322
    async def _execute(self, input_data: CreateFormInput) -> ToolResult: ...

    # _generate_with_retry: line 505
    async def _generate_with_retry(self, prompt: str, ...) -> dict: ...

    # _slugify: line 183
    def _slugify(self, text: str) -> str: ...
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
*(Agent fills this in when done)*
