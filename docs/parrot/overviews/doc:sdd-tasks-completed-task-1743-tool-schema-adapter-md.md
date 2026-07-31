---
type: Wiki Overview
title: 'TASK-1743: Tool Schema Adapter for Bedrock'
id: doc:sdd-tasks-completed-task-1743-tool-schema-adapter-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Bedrock Converse API requires tool definitions in a specific format (`toolSpec`/`inputSchema.json`)
  that differs from ai-parrot's internal schema. This task adds the adapter so `BedrockConverseClient`
  can convert registered tools automatically.
relates_to:
- concept: mod:parrot.tools.manager
  rel: mentions
---

# TASK-1743: Tool Schema Adapter for Bedrock

**Feature**: FEAT-302 — Native Bedrock Client (Converse API) + Nova 2 Sonic
**Spec**: `sdd/specs/bedrock-client-llm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Bedrock Converse API requires tool definitions in a specific format (`toolSpec`/`inputSchema.json`) that differs from ai-parrot's internal schema. This task adds the adapter so `BedrockConverseClient` can convert registered tools automatically.

Implements Spec Module 2.

---

## Scope

- Add `ToolFormat.BEDROCK = "bedrock"` to the `ToolFormat` enum
- Add `_clean_for_bedrock(schema)` static method to `ToolSchemaAdapter`
- Update `clean_schema_for_provider()` to route `ToolFormat.BEDROCK` to the new method
- Write unit tests

**NOT in scope**: BedrockConverseClient, response models, model ID translation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | Add `BEDROCK` enum value and `_clean_for_bedrock()` |
| `tests/tools/test_bedrock_tool_format.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.manager import ToolFormat, ToolSchemaAdapter  # verified: parrot/tools/manager.py:43, 53
```

### Existing Signatures to Use
```python
# parrot/tools/manager.py:43
class ToolFormat(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    GROQ = "groq"
    VERTEX = "vertex"
    GENERIC = "generic"

# parrot/tools/manager.py:53
class ToolSchemaAdapter:
    @staticmethod
    def clean_schema_for_provider(schema: Dict[str, Any], provider: ToolFormat) -> Dict[str, Any]:  # line 59
        # Routes to _clean_for_google() for GOOGLE/VERTEX
        # Returns schema.copy() for others

    @staticmethod
    def _clean_for_google(schema: Dict[str, Any]) -> Dict[str, Any]:  # line 80
        # Reference pattern: removes additionalProperties, title
```

### Does NOT Exist
- ~~`ToolFormat.BEDROCK`~~ — does not exist yet; this task creates it
- ~~`ToolSchemaAdapter._clean_for_bedrock()`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
# Bedrock Converse expects:
# {"toolSpec": {"name": "...", "description": "...", "inputSchema": {"json": {...}}}}
#
# ai-parrot tools produce (GENERIC format):
# {"name": "...", "description": "...", "parameters": {"type": "object", "properties": {...}, ...}}

@staticmethod
def _clean_for_bedrock(schema: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = schema.copy()
    cleaned.pop('_tool_instance', None)
    parameters = cleaned.pop("parameters", cleaned.pop("input_schema", {}))
    return {
        "toolSpec": {
            "name": cleaned["name"],
            "description": cleaned.get("description", ""),
            "inputSchema": {"json": parameters}
        }
    }
```

### Key Constraints
- The `inputSchema.json` value must be a valid JSON Schema object
- `additionalProperties: false` should be preserved (Bedrock requires it for strict mode)
- Pop `_tool_instance` metadata before conversion (same as other adapters)

---

## Acceptance Criteria

- [ ] `ToolFormat.BEDROCK` enum value exists
- [ ] `ToolSchemaAdapter.clean_schema_for_provider(schema, ToolFormat.BEDROCK)` returns correct `toolSpec` envelope
- [ ] `inputSchema.json` contains the parameters schema
- [ ] `_tool_instance` metadata is stripped
- [ ] All tests pass: `pytest tests/tools/test_bedrock_tool_format.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/manager.py`

---

## Test Specification

```python
# tests/tools/test_bedrock_tool_format.py
import pytest
from parrot.tools.manager import ToolFormat, ToolSchemaAdapter


class TestBedrockToolFormat:
    def test_enum_exists(self):
        assert ToolFormat.BEDROCK.value == "bedrock"

    def test_clean_for_bedrock(self):
        schema = {
            "name": "get_weather",
            "description": "Get current weather",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
                "additionalProperties": False
            },
            "_tool_instance": object()
        }
        result = ToolSchemaAdapter.clean_schema_for_provider(schema, ToolFormat.BEDROCK)
        assert "toolSpec" in result
        assert result["toolSpec"]["name"] == "get_weather"
        assert result["toolSpec"]["description"] == "Get current weather"
        assert "json" in result["toolSpec"]["inputSchema"]
        assert "_tool_instance" not in str(result)

    def test_preserves_additional_properties(self):
        schema = {
            "name": "test",
            "description": "test",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False}
        }
        result = ToolSchemaAdapter.clean_schema_for_provider(schema, ToolFormat.BEDROCK)
        assert result["toolSpec"]["inputSchema"]["json"]["additionalProperties"] is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/bedrock-client-llm.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify** `ToolFormat` enum and `ToolSchemaAdapter` still exist at the listed locations
4. **Implement** the enum value and adapter method
5. **Run tests** and verify all acceptance criteria

---

## Completion Note

Added `ToolFormat.BEDROCK = "bedrock"` and `ToolSchemaAdapter._clean_for_bedrock()`
(manager.py) exactly per the spec's reference implementation, wired into
`clean_schema_for_provider()` via a new `elif provider == ToolFormat.BEDROCK`
branch. Created `packages/ai-parrot/tests/tools/test_bedrock_tool_format.py`
(package-scoped test root, same convention as TASK-1742) with the 3 tests
from the task's scaffold — all pass. `ruff check` on `manager.py` shows one
pre-existing, unrelated `F821` (undefined `AbstractToolkit` forward-ref at
`register_toolkit`, line ~726) confirmed present before this change via
`git stash` diff — not introduced by this task.
