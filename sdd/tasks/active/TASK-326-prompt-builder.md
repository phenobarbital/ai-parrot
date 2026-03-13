# TASK-326: PromptBuilder Class

**Feature**: Composable Prompt Layer System
**Spec**: `sdd/specs/composable-prompt-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-325
**Assigned-to**: —

---

## Context

> The PromptBuilder is the core orchestrator that replaces monolithic `system_prompt_template` + `create_system_prompt()` string concatenation. It manages a collection of layers, supports two-phase rendering (configure + build), and provides mutation APIs for per-agent customization.
> Implements spec Section 3.3.

---

## Scope

- Create `parrot/bots/prompts/builder.py` with `PromptBuilder` class:
  - `__init__(layers: Optional[List[PromptLayer]])` — stores layers in `Dict[str, PromptLayer]`
  - Class methods: `default()`, `minimal()`, `voice()` — factory presets
  - Mutation API: `add()`, `remove()`, `replace()`, `get()`, `clone()`
  - `configure(context)` — Phase 1: resolve CONFIGURE-phase layers via `partial_render()`, cache results
  - `build(context)` — Phase 2: resolve REQUEST-phase variables, sort by priority, assemble final prompt
  - `is_configured` property
- `default()` includes: IDENTITY, SECURITY, KNOWLEDGE, USER_SESSION, TOOLS, OUTPUT, BEHAVIOR layers
- `minimal()` includes: IDENTITY, SECURITY, USER_SESSION only
- `voice()` includes: default stack with custom voice BEHAVIOR layer (concise, conversational style)
- `build()` sorts layers by priority, renders each, filters `None`/empty, joins with `\n\n`
- Single-phase fallback: if `configure()` was never called, `build()` renders all variables in one pass

**NOT in scope**: Preset registry module, domain layers, bot integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/prompts/builder.py` | CREATE | PromptBuilder class with factory methods and two-phase rendering |

---

## Implementation Notes

- `configure()` iterates layers: CONFIGURE-phase layers get `partial_render()`, REQUEST-phase layers pass through unchanged.
- `build()` calls `render()` on all layers with the request context. CONFIGURE-phase layers already have static vars baked in.
- `clone()` uses `deepcopy` for safe per-agent customization.
- `voice()` factory creates a custom BEHAVIOR layer with voice-specific instructions (concise, conversational, no long lists).
- Import built-in layers from `layers.py` inside factory methods to avoid circular imports.

---

## Acceptance Criteria

- [ ] `PromptBuilder.default()` creates builder with all 7 built-in layers.
- [ ] `PromptBuilder.minimal()` creates builder with 3 layers (identity, security, user_session).
- [ ] `PromptBuilder.voice()` creates builder with voice-specific behavior layer.
- [ ] `add()` adds/replaces layers; `remove()` removes by name; `replace()` raises `KeyError` if not found.
- [ ] `configure()` resolves CONFIGURE-phase vars; `build()` resolves REQUEST-phase vars.
- [ ] Two-phase rendering: static vars resolved once in `configure()`, dynamic vars per `build()` call.
- [ ] Single-phase fallback: `build()` works without prior `configure()` call.
- [ ] `clone()` produces independent copy (mutations don't affect original).
- [ ] `is_configured` returns correct state.

---

## Test Specification

```python
# tests/bots/prompts/test_builder.py
import pytest
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase


def test_default_builder_has_all_layers():
    builder = PromptBuilder.default()
    assert builder.get("identity") is not None
    assert builder.get("security") is not None
    assert builder.get("knowledge") is not None
    assert builder.get("user_session") is not None
    assert builder.get("tools") is not None
    assert builder.get("output") is not None
    assert builder.get("behavior") is not None


def test_minimal_builder():
    builder = PromptBuilder.minimal()
    assert builder.get("identity") is not None
    assert builder.get("tools") is None


def test_add_remove_replace():
    builder = PromptBuilder.default()
    custom = PromptLayer(name="custom", priority=LayerPriority.CUSTOM, template="<custom>$val</custom>")
    builder.add(custom)
    assert builder.get("custom") is not None
    builder.remove("custom")
    assert builder.get("custom") is None
    with pytest.raises(KeyError):
        builder.replace("nonexistent", custom)


def test_two_phase_rendering():
    builder = PromptBuilder.default()
    configure_ctx = {"name": "Bot", "role": "helper", "goal": "", "capabilities": "", "backstory": "",
                     "extra_security_rules": "", "has_tools": False, "rationale": "",
                     "extra_tool_instructions": "", "pre_instructions_content": ""}
    builder.configure(configure_ctx)
    assert builder.is_configured
    request_ctx = {"knowledge_content": "facts here", "user_context": "user info",
                   "chat_history": "prior msgs", "output_instructions": ""}
    prompt = builder.build(request_ctx)
    assert "Bot" in prompt
    assert "facts here" in prompt


def test_single_phase_fallback():
    builder = PromptBuilder.default()
    ctx = {"name": "Bot", "role": "helper", "goal": "", "capabilities": "", "backstory": "",
           "extra_security_rules": "", "has_tools": False, "rationale": "",
           "knowledge_content": "", "user_context": "", "chat_history": "",
           "output_instructions": "", "extra_tool_instructions": "", "pre_instructions_content": ""}
    prompt = builder.build(ctx)
    assert "<agent_identity>" in prompt
    assert "Bot" in prompt


def test_clone_independence():
    original = PromptBuilder.default()
    cloned = original.clone()
    cloned.remove("tools")
    assert original.get("tools") is not None
    assert cloned.get("tools") is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/composable-prompt-layer.spec.md`) Section 3.3 for full context.
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
3. **Implement** following the scope and notes above.
4. **Run tests**: `pytest tests/bots/prompts/test_builder.py -v`
5. **Verify** all acceptance criteria are met.
6. **Move this file** to `sdd/tasks/completed/TASK-326-prompt-builder.md`.
7. **Update index** → `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
