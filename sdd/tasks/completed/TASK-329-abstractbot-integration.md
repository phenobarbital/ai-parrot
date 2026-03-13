# TASK-329: AbstractBot PromptBuilder Integration

**Feature**: Composable Prompt Layer System
**Spec**: `sdd/specs/composable-prompt-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-6h)
**Depends-on**: TASK-326, TASK-327
**Assigned-to**: —

---

## Context

> This is the most critical task: wiring the PromptBuilder into `AbstractBot` so that bots can optionally use the layer-based prompt system while maintaining full backward compatibility with the legacy `system_prompt_template` path.
> Implements spec Section 5.1.

---

## Scope

- Modify `parrot/bots/abstract.py`:
  - Add `_prompt_builder: Optional[PromptBuilder] = None` class attribute
  - Add `prompt_preset: str = None` parameter to `__init__()` — when set, initializes `_prompt_builder` from preset registry
  - Add `prompt_builder` property (getter/setter)
  - Modify `configure()` to call `_configure_prompt_builder()` when `_prompt_builder` is set and not yet configured
  - Add `_configure_prompt_builder()` method — Phase 1: resolves static variables (name, role, goal, backstory, rationale, pre_instructions, dynamic_values, has_tools, etc.)
  - Modify `create_system_prompt()` to branch: if `_prompt_builder` is set → call `_build_prompt_from_layers()`, else → legacy path (unchanged)
  - Add `_build_prompt_from_layers()` method — Phase 2: assembles `knowledge_content` from multiple sources (pageindex, vector, kb, metadata as XML sub-tags), resolves REQUEST-phase variables, calls `builder.build()`
- The legacy path (`_build_prompt_legacy()` or existing code) must remain completely unchanged for bots without `_prompt_builder`.

**NOT in scope**: Migrating VoiceBot, PandasAgent, Chatbot, or BotManager. Those are separate tasks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/abstract.py` | MODIFY | Add PromptBuilder support alongside legacy path |

---

## Implementation Notes

- **Backward compatibility is critical**: Any bot that doesn't set `prompt_preset` or `_prompt_builder` must behave exactly as before.
- `_configure_prompt_builder()` resolves dynamic_values via `dynamic_values.get_all_names()` and `get_value()` (existing pattern in `create_system_prompt`).
- `_build_prompt_from_layers()` assembles `knowledge_content` using XML sub-tags per spec Section 4.4:
  - `<document_structure>` for pageindex_context
  - `<documents>` for vector_context
  - `<facts>` for kb_context
  - `<metadata>` for metadata dict
- Pre-instructions formatting: `"\n".join(f"- {inst}" for inst in pre_instructions)` when building configure context.
- The `configure_context` dict for Phase 1 includes: name, role, goal, capabilities, backstory, pre_instructions_content, extra_security_rules, has_tools, extra_tool_instructions, rationale, and all dynamic_values.
- The `request_context` dict for Phase 2 includes: knowledge_content, user_context, chat_history, output_instructions, and extra kwargs.

---

## Acceptance Criteria

- [ ] Bots without `_prompt_builder` continue using legacy path — zero behavior change.
- [ ] `prompt_preset="default"` in `__init__()` initializes builder from preset registry.
- [ ] `configure()` calls `_configure_prompt_builder()` to resolve CONFIGURE-phase vars.
- [ ] `create_system_prompt()` branches correctly between layer and legacy paths.
- [ ] `_build_prompt_from_layers()` assembles knowledge using XML sub-tags.
- [ ] Dynamic values are resolved during configure, not on every ask.
- [ ] Two-phase rendering works: static vars cached, dynamic vars resolved per request.

---

## Test Specification

```python
# tests/bots/prompts/test_abstractbot_prompt_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_bot_without_builder_uses_legacy():
    """Bots without _prompt_builder must use existing legacy path."""
    # Create AbstractBot subclass without prompt_builder
    # Call create_system_prompt with known args
    # Assert output matches legacy behavior exactly
    pass


@pytest.mark.asyncio
async def test_bot_with_preset_uses_layers():
    """Bot with prompt_preset='default' uses PromptBuilder."""
    # Create bot with prompt_preset="default"
    # Call configure()
    # Call create_system_prompt with context
    # Assert output contains XML layer structure
    pass


@pytest.mark.asyncio
async def test_configure_resolves_static_vars():
    """configure() should bake static vars into CONFIGURE-phase layers."""
    # Create bot with builder, set name/role/goal
    # Call configure()
    # Assert builder.is_configured is True
    pass


@pytest.mark.asyncio
async def test_knowledge_assembled_with_xml_subtags():
    """_build_prompt_from_layers assembles knowledge with XML sub-tags."""
    # Create bot with builder
    # Call _build_prompt_from_layers with vector_context and kb_context
    # Assert output contains <documents> and <facts> tags
    pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/composable-prompt-layer.spec.md`) Section 5.1 for full context.
2. **Read `parrot/bots/abstract.py`** carefully — understand `configure()`, `create_system_prompt()`, and `_define_prompt()`.
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
4. **Implement** following the scope and notes above.
5. **Run tests**: `pytest tests/bots/prompts/ -v`
6. **Verify** all acceptance criteria are met, especially backward compatibility.
7. **Move this file** to `sdd/tasks/completed/TASK-329-abstractbot-integration.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
