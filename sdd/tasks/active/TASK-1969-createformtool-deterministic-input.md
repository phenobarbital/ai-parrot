# TASK-1969: CreateFormTool Deterministic Input

**Feature**: FEAT-388 — Deterministic CreateFormTool
**Spec**: `sdd/specs/deterministic-creationformtool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1968
**Assigned-to**: unassigned

---

## Context

This task wires the `FormAssembler` (created in TASK-1968) into `CreateFormTool`.
The tool gains three new optional input fields (`schema`, `sections`, `fields`)
and a branching path in `_execute()` that bypasses the LLM when structured input
is provided. The existing LLM path remains completely unchanged.

Implements spec Module 2.

---

## Scope

- Extend `CreateFormInput` with optional `schema`, `sections`, `fields` parameters
- Make `prompt` optional (default `None`) — still required when no structured input given
- Add deterministic branching in `_execute()`:
  - Detect structured input → delegate to `FormAssembler`
  - Run `FormValidator.check_schema()` on result (same as LLM path)
  - Honor `persist` and `form_id` parameters identically
  - Return `ToolResult` in the same format as the LLM path
- Add input validation:
  - Both prompt AND structured input → `ValueError`
  - Neither prompt nor structured input → `ValueError`
- Write unit tests for the new input paths

**NOT in scope**:
- Modifying `FormAssembler` (TASK-1968)
- Modifying `EditToolkit` (TASK-1970)
- Integration/roundtrip tests (TASK-1971)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py` | MODIFY | Extend CreateFormInput, add branching in _execute |
| `packages/parrot-formdesigner/tests/unit/test_create_form_deterministic.py` | CREATE | Unit tests for deterministic paths |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.assembler import FormAssembler  # assembler.py (created by TASK-1968)
from parrot_formdesigner.core.schema import FormSchema    # core/schema.py
from parrot_formdesigner.services.validators import FormValidator  # services/validators.py
from parrot_formdesigner.services.registry import FormRegistry     # services/registry.py
from parrot.tools.abstract import AbstractTool, ToolResult         # tools/create_form.py:28
from pydantic import BaseModel, Field                               # already imported in create_form.py
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py:223
class CreateFormInput(BaseModel):
    prompt: str = Field(...)                           # line 233 — CHANGE to str | None
    form_id: str | None = Field(default=None)          # line 238 — keep
    persist: bool = Field(default=False)                # line 242 — keep
    refine_form_id: str | None = Field(default=None)   # line 245 — keep

# packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py:259
class CreateFormTool(AbstractTool):
    name: str = "create_form"
    args_schema = CreateFormInput
    MAX_RETRIES = 2
    async def _execute(self, prompt: str, form_id: str | None = None,
                       persist: bool = False, refine_form_id: str | None = None,
                       **kwargs: Any) -> ToolResult:  # line 318

# packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py:189
def _slugify(text: str) -> str:  # reused for form_id generation

# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
class FormValidator:
    def check_schema(self, form: FormSchema) -> list[str]:  # returns list of error strings
```

### Does NOT Exist
- ~~`CreateFormInput.schema`~~ — does not exist yet; this task adds it
- ~~`CreateFormInput.sections`~~ — does not exist yet
- ~~`CreateFormInput.fields`~~ — does not exist yet
- ~~`CreateFormTool.assemble()`~~ — no such method; use `FormAssembler` directly
- ~~`CreateFormTool._execute_deterministic()`~~ — not a separate method; branching is inline in `_execute`

---

## Implementation Notes

### Pattern to Follow

The deterministic branch should be added at the TOP of `_execute()`, before the
existing `refine_form_id` and LLM logic:

```python
async def _execute(
    self,
    prompt: str | None = None,
    form_id: str | None = None,
    persist: bool = False,
    refine_form_id: str | None = None,
    schema: dict[str, Any] | None = None,
    sections: list[dict[str, Any]] | None = None,
    fields: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> ToolResult:
    has_structured = schema is not None or sections is not None or fields is not None

    if has_structured and prompt is not None:
        return ToolResult(
            success=False, status="error", result=None,
            metadata={"error": "Provide either 'prompt' or structured input (schema/sections/fields), not both"},
        )
    if not has_structured and not prompt:
        return ToolResult(
            success=False, status="error", result=None,
            metadata={"error": "Either 'prompt' or structured input (schema/sections/fields) is required"},
        )

    if has_structured:
        return await self._execute_from_schema(
            schema=schema, sections=sections, fields=fields,
            form_id=form_id, persist=persist,
        )

    # ... existing LLM path continues unchanged ...
```

### Key Constraints
- `prompt` parameter type changes from `str` to `str | None` with `default=None`
- The `_execute` signature must accept the new kwargs — `AbstractTool` passes `**kwargs` from `CreateFormInput`
- Return `ToolResult` in the exact same format as the LLM path (success, status, result, metadata)
- `FormValidator.check_schema()` must run on deterministic output (report in metadata, don't raise)
- `persist=True` must register via `self._registry.register()` (same as LLM path)

### Pydantic field name `schema`
If `schema` causes issues as a Pydantic v2 field name, use `form_schema` with
`Field(alias="schema")`. Test this during implementation.

---

## Acceptance Criteria

- [ ] `CreateFormInput` has optional `schema`, `sections`, `fields` parameters
- [ ] `prompt` is optional (default `None`)
- [ ] `_execute` with `schema` dict produces a valid `FormSchema` without LLM call
- [ ] `_execute` with `sections` list produces a valid `FormSchema` without LLM call
- [ ] `_execute` with `fields` list produces a valid `FormSchema` without LLM call
- [ ] Prompt-only input still uses the existing LLM path (backward compatible)
- [ ] Both `prompt` + structured input → error `ToolResult`
- [ ] Neither `prompt` nor structured input → error `ToolResult`
- [ ] `persist=True` registers deterministic forms in registry
- [ ] `FormValidator.check_schema()` runs on deterministic output
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_create_form_deterministic.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_create_form_deterministic.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot_formdesigner.tools.create_form import CreateFormTool, CreateFormInput


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.completion = AsyncMock()
    return client


@pytest.fixture
def tool(mock_client):
    return CreateFormTool(client=mock_client)


class TestDeterministicInput:
    @pytest.mark.asyncio
    async def test_schema_input_no_llm(self, tool, mock_client):
        result = await tool.execute(
            schema={
                "form_id": "test",
                "title": "Test",
                "sections": [{"section_id": "s1", "fields": [
                    {"field_id": "name", "field_type": "text", "label": "Name"},
                ]}],
            },
        )
        assert result.success is True
        assert result.metadata["form"]["form_id"] == "test"
        mock_client.completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_sections_input(self, tool, mock_client):
        result = await tool.execute(
            sections=[{"title": "Info", "fields": [
                {"label": "Name", "field_type": "text"},
            ]}],
            form_id="test-sections",
        )
        assert result.success is True
        mock_client.completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_fields_input(self, tool, mock_client):
        result = await tool.execute(
            fields=[
                {"label": "Name", "field_type": "text", "required": True},
                {"label": "Age", "field_type": "integer"},
            ],
            form_id="test-fields",
        )
        assert result.success is True
        assert len(result.metadata["form"]["sections"]) == 1
        mock_client.completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_prompt_and_schema_error(self, tool):
        result = await tool.execute(
            prompt="Make a form",
            schema={"form_id": "x", "title": "X", "sections": []},
        )
        assert result.success is False
        assert "not both" in result.metadata["error"]

    @pytest.mark.asyncio
    async def test_neither_prompt_nor_schema_error(self, tool):
        result = await tool.execute()
        assert result.success is False
        assert "required" in result.metadata["error"].lower()

    @pytest.mark.asyncio
    async def test_invalid_schema_fails_fast(self, tool):
        result = await tool.execute(schema={"invalid": "data"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_persist_with_schema(self, tool):
        mock_registry = AsyncMock()
        tool._registry = mock_registry
        await tool.execute(
            schema={
                "form_id": "persist-test",
                "title": "Persist",
                "sections": [{"section_id": "s", "fields": [
                    {"field_id": "x", "field_type": "text", "label": "X"},
                ]}],
            },
            persist=True,
        )
        mock_registry.register.assert_called_once()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/deterministic-creationformtool.spec.md` for full context
2. **Check dependencies** — verify TASK-1968 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `CreateFormInput` and `CreateFormTool` signatures
4. **Modify** `create_form.py` — extend `CreateFormInput`, add branching in `_execute`
5. **Create** `test_create_form_deterministic.py`
6. **Run tests**: `pytest packages/parrot-formdesigner/tests/unit/test_create_form_deterministic.py -v`
7. **Run existing tests**: `pytest packages/parrot-formdesigner/tests/ -v` (ensure no regressions)
8. **Update status** in per-spec index → `"done"`
9. **Move** this file to `sdd/tasks/completed/`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
