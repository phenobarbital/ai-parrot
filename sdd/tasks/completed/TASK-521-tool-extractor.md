# TASK-521: Tool Extractor

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-518, TASK-520
**Assigned-to**: unassigned

---

## Context

Implements Module 4 from the spec. Extracts `FormSchema` from `AbstractTool.args_schema`. Delegates to `PydanticExtractor` with tool-specific metadata (name, description). This is used by `RequestFormTool` to generate forms on-the-fly from tool parameters.

---

## Scope

- Implement `parrot/forms/extractors/tool.py` with `ToolExtractor`
- Delegate to `PydanticExtractor` for the actual Pydantic introspection
- Add tool-specific metadata: tool name as form title, tool description as form description
- Support `exclude_fields` parameter to strip context fields (fields in `_context_fields`)
- Support `known_values` parameter to exclude pre-filled fields
- Auto-select section grouping based on field count (single section for ≤5 fields)
- Migrate logic from `FormDefinition.from_tool_schema()` in `parrot/integrations/dialogs/models.py`
- Write unit tests

**NOT in scope**: RequestFormTool migration (TASK-530), Pydantic introspection details (TASK-520).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/extractors/tool.py` | CREATE | ToolExtractor implementation |
| `packages/ai-parrot/src/parrot/forms/extractors/__init__.py` | MODIFY | Export ToolExtractor |
| `packages/ai-parrot/tests/unit/forms/test_tool_extractor.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
class ToolExtractor:
    def __init__(self, pydantic_extractor: PydanticExtractor | None = None):
        self._pydantic = pydantic_extractor or PydanticExtractor()

    def extract(
        self,
        tool: AbstractTool,
        *,
        exclude_fields: set[str] | None = None,
        known_values: dict[str, Any] | None = None,
    ) -> FormSchema:
        """Extract FormSchema from a tool's args_schema."""
```

### Key Constraints
- Must handle tools with no `args_schema` (raise `ValueError`)
- Must respect `AbstractToolArgsSchema._context_fields` — always exclude these
- `known_values` fields are excluded from the form (they're pre-filled)
- Form ID format: `"{tool.name}_form"`

### References in Codebase
- `parrot/integrations/dialogs/models.py:320-352` — `FormDefinition.from_tool_schema()` existing logic
- `parrot/tools/abstract.py` — `AbstractTool`, `AbstractToolArgsSchema._context_fields`

---

## Acceptance Criteria

- [ ] Tool with args_schema → FormSchema with tool name as title
- [ ] Context fields excluded automatically
- [ ] Known values excluded from form fields
- [ ] Tool with no args_schema raises ValueError
- [ ] Import works: `from parrot.forms.extractors import ToolExtractor`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/forms/test_tool_extractor.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/forms/test_tool_extractor.py
import pytest
from pydantic import BaseModel, Field
from parrot.forms import FieldType
from parrot.forms.extractors.tool import ToolExtractor


class MockArgsSchema(BaseModel):
    query: str = Field(..., description="Search query")
    limit: int = Field(default=10, description="Max results")


class MockTool:
    name = "search_tool"
    description = "Search for documents"
    args_schema = MockArgsSchema


class MockToolNoSchema:
    name = "no_schema"
    description = "No schema"
    args_schema = None


@pytest.fixture
def extractor():
    return ToolExtractor()


class TestToolExtractor:
    def test_basic_extraction(self, extractor):
        schema = extractor.extract(MockTool())
        assert schema.form_id == "search_tool_form"
        assert len(schema.sections[0].fields) == 2

    def test_known_values_excluded(self, extractor):
        schema = extractor.extract(MockTool(), known_values={"query": "test"})
        field_ids = [f.field_id for f in schema.sections[0].fields]
        assert "query" not in field_ids

    def test_no_schema_raises(self, extractor):
        with pytest.raises(ValueError):
            extractor.extract(MockToolNoSchema())
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-518 and TASK-520 are in `tasks/completed/`
3. **Read** `parrot/integrations/dialogs/models.py` lines 320-352 for existing `from_tool_schema()` logic
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-521-tool-extractor.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: ToolExtractor delegates to PydanticExtractor. Context fields resolved via Pydantic v2 __private_attributes__ (ModelPrivateAttr.default). known_values and exclude_fields filtering. 11 unit tests pass.

**Deviations from spec**: none
