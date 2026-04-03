# TASK-530: RequestFormTool Migration

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-518, TASK-521, TASK-527
**Assigned-to**: unassigned

---

## Context

Implements Module 13 from the spec. Migrates `RequestFormTool` from `parrot/integrations/msteams/tools/request_form.py` to `parrot/forms/tools/request_form.py`. The tool is no longer Teams-specific — any integration wrapper can detect the `form_requested` status and render the form using the appropriate renderer.

---

## Scope

- Create `parrot/forms/tools/` package with `__init__.py`
- Implement `parrot/forms/tools/request_form.py` with `RequestFormTool`
- Migrate logic from `parrot/integrations/msteams/tools/request_form.py`:
  - `RequestFormInput` schema (target_tool, known_values, fields_to_collect, form_title, context_message)
  - `FormRequestResult` dataclass
  - Core `_execute()` logic: validate target tool exists, generate FormSchema via `ToolExtractor`, filter fields, return form in ToolResult metadata
- Use `ToolExtractor` (TASK-521) instead of direct `FormDefinition.from_tool_schema()`
- Return `FormSchema` (not `FormDefinition`) in ToolResult metadata
- Write unit tests

**NOT in scope**: CreateFormTool (TASK-531), Teams wrapper changes (TASK-532).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/tools/__init__.py` | CREATE | Package init |
| `packages/ai-parrot/src/parrot/forms/tools/request_form.py` | CREATE | RequestFormTool |
| `packages/ai-parrot/src/parrot/forms/__init__.py` | MODIFY | Export RequestFormTool |
| `packages/ai-parrot/tests/unit/forms/test_request_form_tool.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

Migrate from `parrot/integrations/msteams/tools/request_form.py`. Key flow:

1. LLM calls `request_form` with `target_tool` name and optional `known_values`
2. Tool looks up target tool in `ToolManager`
3. Uses `ToolExtractor.extract()` to generate `FormSchema`, passing `known_values` and `fields_to_collect`
4. Returns `ToolResult(success=True, status="form_requested", metadata={"form": schema.model_dump(), ...})`

```python
class RequestFormTool(AbstractTool):
    name = "request_form"
    description = "Request structured data collection from the user via a form"
    args_schema = RequestFormInput

    def __init__(self, tool_manager: ToolManager, form_registry: FormRegistry | None = None): ...
    async def _execute(self, **kwargs) -> ToolResult: ...
```

### Key Constraints
- Must return `ToolResult` with `status="form_requested"` — this is the signal for wrappers
- `FormSchema` goes in `ToolResult.metadata["form"]` as a dict (not Pydantic model)
- Must validate that target tool exists and has `args_schema`
- Must handle `fields_to_collect` filter (only include specified fields)

### References in Codebase
- `parrot/integrations/msteams/tools/request_form.py` — existing implementation
- `parrot/tools/abstract.py` — `AbstractTool` and `ToolResult`

---

## Acceptance Criteria

- [ ] RequestFormTool generates FormSchema from target tool
- [ ] Known values excluded from form
- [ ] fields_to_collect filter works
- [ ] Returns ToolResult with status="form_requested"
- [ ] Invalid target tool raises clear error
- [ ] Import works: `from parrot.forms.tools import RequestFormTool`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/forms/test_request_form_tool.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/forms/test_request_form_tool.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from pydantic import BaseModel, Field
from parrot.forms.tools.request_form import RequestFormTool


class MockSchema(BaseModel):
    query: str = Field(..., description="Search query")
    limit: int = Field(default=10)


class MockTargetTool:
    name = "search"
    description = "Search docs"
    args_schema = MockSchema


@pytest.fixture
def tool_manager():
    mgr = MagicMock()
    mgr.get_tool.return_value = MockTargetTool()
    return mgr


@pytest.fixture
def request_form_tool(tool_manager):
    return RequestFormTool(tool_manager=tool_manager)


class TestRequestFormTool:
    async def test_generates_form(self, request_form_tool):
        result = await request_form_tool.execute(target_tool="search")
        assert result.status == "form_requested"
        assert "form" in result.metadata

    async def test_known_values_excluded(self, request_form_tool):
        result = await request_form_tool.execute(
            target_tool="search", known_values={"query": "test"})
        form = result.metadata["form"]
        field_ids = [f["field_id"] for s in form["sections"] for f in s["fields"]]
        assert "query" not in field_ids

    async def test_invalid_tool_error(self, tool_manager):
        tool_manager.get_tool.return_value = None
        tool = RequestFormTool(tool_manager=tool_manager)
        result = await tool.execute(target_tool="nonexistent")
        assert not result.success
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-518, TASK-521, TASK-527 are in `tasks/completed/`
3. **Read** `parrot/integrations/msteams/tools/request_form.py` for existing logic to migrate
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-530-request-form-tool.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: RequestFormTool in parrot/forms/tools/request_form.py. RequestFormInput schema with target_tool, known_values, fields_to_collect, form_title, context_message. _execute() validates tool existence and args_schema, delegates to ToolExtractor.extract(), applies fields_to_collect filtering, returns ToolResult(status="form_requested", metadata={"form": schema.model_dump()}). 10 tests pass.

**Deviations from spec**: none
