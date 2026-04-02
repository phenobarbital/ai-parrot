# TASK-531: CreateFormTool

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-518, TASK-519, TASK-527, TASK-529
**Assigned-to**: unassigned

---

## Context

Implements Module 14 from the spec. New agent tool that accepts a natural language prompt and returns a validated `FormSchema`. Supports iterative refinement — when `refine_form_id` is provided, loads the existing form and applies modifications. Optionally persists via `FormRegistry` with `persist=True`.

---

## Scope

- Implement `parrot/forms/tools/create_form.py` with `CreateFormTool`
- Input schema: `prompt` (str), `form_id` (str|None), `persist` (bool=False), `refine_form_id` (str|None)
- Use the agent's LLM client to generate FormSchema JSON from the prompt
- Build a structured prompt that includes the FormSchema JSON structure and field type options
- Validate LLM output against `FormSchema` Pydantic model (retry up to 2 times with error feedback)
- Iterative refinement: when `refine_form_id` is set, load existing form from registry, include it in the prompt, and ask LLM to modify it
- Validate generated form using `FormValidator` (check for circular deps, etc.)
- Optionally register in `FormRegistry` with `persist=True`
- Write unit tests

**NOT in scope**: RequestFormTool (TASK-530), rendering the created form.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/tools/create_form.py` | CREATE | CreateFormTool |
| `packages/ai-parrot/src/parrot/forms/tools/__init__.py` | MODIFY | Export CreateFormTool |
| `packages/ai-parrot/tests/unit/forms/test_create_form_tool.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
class CreateFormInput(BaseModel):
    prompt: str = Field(..., description="Natural language description of the form to create")
    form_id: str | None = Field(None, description="Custom form ID. Auto-generated if not provided.")
    persist: bool = Field(False, description="Save form to persistent storage")
    refine_form_id: str | None = Field(None, description="Form ID to load and refine")

class CreateFormTool(AbstractTool):
    name = "create_form"
    description = "Create a form from a natural language description, or refine an existing form"
    args_schema = CreateFormInput

    def __init__(self, client: AbstractClient, registry: FormRegistry | None = None): ...

    async def _execute(self, prompt: str, form_id: str | None = None,
                       persist: bool = False, refine_form_id: str | None = None) -> ToolResult:
        # 1. Build system prompt with FormSchema structure
        # 2. If refine_form_id, load existing form and include in prompt
        # 3. Call LLM to generate JSON
        # 4. Parse and validate against FormSchema
        # 5. On validation failure, retry with error feedback (up to 2 retries)
        # 6. Validate with FormValidator (circular deps check)
        # 7. Optionally register with persist=True
        # 8. Return FormSchema in ToolResult
```

### Key Constraints
- The LLM system prompt must include: all FieldType values, FieldConstraints fields, DependencyRule structure, FormSchema structure
- Use structured output prompting: "Respond with ONLY valid JSON matching this schema: ..."
- Retry logic: parse LLM output, if Pydantic validation fails, include the error in a follow-up prompt
- For refinement: include the current form JSON in the prompt with "Modify this form based on: {prompt}"
- `form_id` auto-generation: slugify the form title if not provided
- The LLM client is passed in the constructor (not hardcoded to any provider)

### References in Codebase
- `parrot/integrations/dialogs/llm_generator.py` — `LLMFormGenerator` for LLM-assisted form generation pattern
- `parrot/tools/abstract.py` — `AbstractTool` base class

---

## Acceptance Criteria

- [ ] Generates valid FormSchema from natural language prompt
- [ ] Iterative refinement works (load form, modify based on prompt)
- [ ] Pydantic validation with retry (up to 2 retries with error feedback)
- [ ] Circular dependency detection on generated form
- [ ] `persist=True` saves to registry
- [ ] Returns FormSchema in ToolResult
- [ ] Import works: `from parrot.forms.tools import CreateFormTool`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/forms/test_create_form_tool.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/forms/test_create_form_tool.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from parrot.forms import FormSchema, FormField, FormSection, FieldType
from parrot.forms.tools.create_form import CreateFormTool


VALID_FORM_JSON = json.dumps({
    "form_id": "feedback",
    "title": "Customer Feedback",
    "sections": [{
        "section_id": "main",
        "fields": [
            {"field_id": "name", "field_type": "text", "label": "Name", "required": True},
            {"field_id": "rating", "field_type": "integer", "label": "Rating",
             "constraints": {"min_value": 1, "max_value": 5}},
        ]
    }]
})


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.completion.return_value = VALID_FORM_JSON
    return client


@pytest.fixture
def tool(mock_client):
    return CreateFormTool(client=mock_client)


class TestCreateFormTool:
    async def test_basic_creation(self, tool):
        result = await tool.execute(prompt="Create a customer feedback form")
        assert result.success
        assert "form" in result.metadata

    async def test_validation_retry(self, mock_client):
        # First call returns invalid, second returns valid
        mock_client.completion.side_effect = [
            '{"invalid": "json"}',
            VALID_FORM_JSON,
        ]
        tool = CreateFormTool(client=mock_client)
        result = await tool.execute(prompt="Create a form")
        assert result.success
        assert mock_client.completion.call_count == 2

    async def test_persist_registers_form(self, mock_client):
        registry = AsyncMock()
        tool = CreateFormTool(client=mock_client, registry=registry)
        await tool.execute(prompt="Create a form", persist=True)
        registry.register.assert_called_once()

    async def test_refinement_includes_existing(self, mock_client):
        registry = AsyncMock()
        existing = FormSchema(
            form_id="existing", title="Existing",
            sections=[FormSection(section_id="s", fields=[
                FormField(field_id="f", field_type=FieldType.TEXT, label="F")
            ])]
        )
        registry.get.return_value = existing
        tool = CreateFormTool(client=mock_client, registry=registry)
        await tool.execute(prompt="Add a phone field", refine_form_id="existing")
        # Verify the prompt included the existing form
        call_args = mock_client.completion.call_args
        assert "existing" in str(call_args).lower() or "Existing" in str(call_args)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-518, TASK-519, TASK-527, TASK-529 are in `tasks/completed/`
3. **Read** `parrot/integrations/dialogs/llm_generator.py` for existing LLM form generation patterns
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-531-create-form-tool.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: CreateFormTool with CreateFormInput schema (prompt, form_id, persist, refine_form_id). _generate_with_retry() with MAX_RETRIES=2 and error feedback to LLM on Pydantic failure. _extract_json() handles markdown code blocks. Refinement via _build_refinement_messages() loading existing form from registry. FormValidator used for schema validation. LLM client supports both completion() and ask() interfaces. 12 tests pass.

**Deviations from spec**: none
