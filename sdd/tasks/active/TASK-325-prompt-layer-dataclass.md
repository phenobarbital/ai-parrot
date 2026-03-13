# TASK-325: PromptLayer Dataclass & Built-in Layers

**Feature**: Composable Prompt Layer System
**Spec**: `sdd/specs/composable-prompt-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: —
**Assigned-to**: —

---

## Context

> Foundation module for the composable prompt system. Defines the core data structures (`PromptLayer`, `LayerPriority`, `RenderPhase`) and all built-in layers that replace the monolithic prompt templates.
> Implements spec Sections 3.1 and 3.2.

---

## Scope

- Create `parrot/bots/prompts/layers.py` with:
  - `LayerPriority(IntEnum)` — IDENTITY=10, PRE_INSTRUCTIONS=15, SECURITY=20, KNOWLEDGE=30, USER_SESSION=40, TOOLS=50, OUTPUT=60, BEHAVIOR=70, CUSTOM=80
  - `RenderPhase(str, Enum)` — CONFIGURE, REQUEST
  - `PromptLayer` frozen dataclass with fields: `name`, `priority`, `template`, `phase`, `condition`, `required_vars`
  - `render(context)` method — renders template with `Template.safe_substitute()`, returns `None` if condition fails
  - `partial_render(context)` method — partial substitution for two-phase rendering, returns new `PromptLayer` with `phase=REQUEST`
- Define all built-in layer instances as module-level constants:
  - `IDENTITY_LAYER` (CONFIGURE phase) — `<agent_identity>` XML wrapper
  - `PRE_INSTRUCTIONS_LAYER` (CONFIGURE phase) — conditional on `pre_instructions_content`
  - `SECURITY_LAYER` (CONFIGURE phase) — `<security_policy>` XML wrapper
  - `KNOWLEDGE_LAYER` (REQUEST phase) — conditional on `knowledge_content`
  - `USER_SESSION_LAYER` (REQUEST phase) — `<user_session>` with `<conversation_history>` sub-tag
  - `TOOLS_LAYER` (CONFIGURE phase) — conditional on `has_tools`
  - `OUTPUT_LAYER` (REQUEST phase) — conditional on `output_instructions`
  - `BEHAVIOR_LAYER` (CONFIGURE phase) — conditional on `rationale`

**NOT in scope**: PromptBuilder, presets, domain layers, or integration with existing bots.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/prompts/layers.py` | CREATE | Core dataclass + built-in layer constants |

---

## Implementation Notes

- Use `string.Template` for `$variable` placeholder rendering (not f-strings or Jinja).
- `PromptLayer` must be `@dataclass(frozen=True)` — layers are immutable after creation.
- All layer templates use XML tags for structure (never Markdown headers as delimiters). See spec Section 4.2.
- Conditions use `lambda ctx:` patterns for conditional inclusion.
- `partial_render()` is key to two-phase rendering: CONFIGURE phase resolves static vars, leaving REQUEST `$placeholders` intact via `safe_substitute`.

---

## Acceptance Criteria

- [ ] `LayerPriority` enum has all 9 priority levels with correct integer values.
- [ ] `RenderPhase` enum has CONFIGURE and REQUEST values.
- [ ] `PromptLayer.render()` returns rendered string or `None` when condition fails.
- [ ] `PromptLayer.partial_render()` returns new PromptLayer with partially resolved template.
- [ ] All 8 built-in layers defined with correct priorities, phases, templates, and conditions.
- [ ] Module imports cleanly: `from parrot.bots.prompts.layers import PromptLayer, LayerPriority, IDENTITY_LAYER`

---

## Test Specification

```python
# tests/bots/prompts/test_layers.py
import pytest
from parrot.bots.prompts.layers import (
    PromptLayer, LayerPriority, RenderPhase,
    IDENTITY_LAYER, SECURITY_LAYER, KNOWLEDGE_LAYER,
    USER_SESSION_LAYER, TOOLS_LAYER, BEHAVIOR_LAYER,
    PRE_INSTRUCTIONS_LAYER, OUTPUT_LAYER,
)


def test_layer_render_with_context():
    ctx = {"name": "TestBot", "role": "assistant", "goal": "", "capabilities": "", "backstory": ""}
    result = IDENTITY_LAYER.render(ctx)
    assert "<agent_identity>" in result
    assert "TestBot" in result


def test_layer_render_condition_false():
    ctx = {"knowledge_content": ""}
    result = KNOWLEDGE_LAYER.render(ctx)
    assert result is None


def test_layer_render_condition_true():
    ctx = {"knowledge_content": "some facts"}
    result = KNOWLEDGE_LAYER.render(ctx)
    assert "<knowledge_context>" in result
    assert "some facts" in result


def test_partial_render_preserves_unresolved_vars():
    ctx = {"name": "Bot", "role": "helper"}
    new_layer = IDENTITY_LAYER.partial_render(ctx)
    assert "Bot" in new_layer.template
    assert "$goal" in new_layer.template  # unresolved
    assert new_layer.phase == RenderPhase.REQUEST


def test_tools_layer_conditional():
    assert TOOLS_LAYER.render({"has_tools": False}) is None
    result = TOOLS_LAYER.render({"has_tools": True, "extra_tool_instructions": ""})
    assert "<tool_policy>" in result


def test_layer_priorities_ordering():
    assert LayerPriority.IDENTITY < LayerPriority.SECURITY < LayerPriority.KNOWLEDGE
    assert LayerPriority.KNOWLEDGE < LayerPriority.USER_SESSION < LayerPriority.TOOLS
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/composable-prompt-layer.spec.md`) Sections 3.1, 3.2, and 4.2 for full context.
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
3. **Implement** following the scope and notes above.
4. **Run tests**: `pytest tests/bots/prompts/test_layers.py -v`
5. **Verify** all acceptance criteria are met.
6. **Move this file** to `sdd/tasks/completed/TASK-325-prompt-layer-dataclass.md`.
7. **Update index** → `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
