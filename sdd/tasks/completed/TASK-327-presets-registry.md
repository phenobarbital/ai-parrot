# TASK-327: Presets Registry

**Feature**: Composable Prompt Layer System
**Spec**: `sdd/specs/composable-prompt-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-326
**Assigned-to**: —

---

## Context

> The presets registry provides named factory functions for common PromptBuilder configurations. This enables YAML-based agent definitions and BotManager to reference prompt stacks by name.
> Implements spec Section 3.4.

---

## Scope

- Create `parrot/bots/prompts/presets.py` with:
  - `_PRESETS: Dict[str, Callable[[], PromptBuilder]]` — internal registry mapping names to factory functions
  - Built-in presets: `"default"`, `"minimal"`, `"voice"`, `"agent"`
  - `register_preset(name, factory)` — register a named preset
  - `get_preset(name) -> PromptBuilder` — get preset by name, raises `KeyError` if not found
  - `list_presets() -> list[str]` — list available preset names
- The `"agent"` preset: default stack + `STRICT_GROUNDING_LAYER` (from domain_layers or inline) for agents that need strict data grounding
- Add `PromptBuilder.agent()` class method to `builder.py` if not already present (or wire it through the preset)

**NOT in scope**: Domain layers module, bot integration, YAML parsing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/prompts/presets.py` | CREATE | Preset registry with register/get/list functions |
| `parrot/bots/prompts/builder.py` | MODIFY | Add `agent()` class method if needed |

---

## Implementation Notes

- Keep it simple: presets are just named factory callables that return `PromptBuilder` instances.
- `get_preset()` returns a fresh builder each time (calls the factory), not a shared instance.
- Error message in `get_preset()` should list available presets for discoverability.

---

## Acceptance Criteria

- [ ] `register_preset()` adds a new named preset.
- [ ] `get_preset("default")` returns a PromptBuilder equivalent to `PromptBuilder.default()`.
- [ ] `get_preset("unknown")` raises `KeyError` with helpful message listing available presets.
- [ ] `list_presets()` returns `["default", "minimal", "voice", "agent"]` (at minimum).
- [ ] Each call to `get_preset()` returns a new independent builder instance.

---

## Test Specification

```python
# tests/bots/prompts/test_presets.py
import pytest
from parrot.bots.prompts.presets import register_preset, get_preset, list_presets


def test_get_default_preset():
    builder = get_preset("default")
    assert builder.get("identity") is not None
    assert builder.get("security") is not None


def test_get_unknown_preset_raises():
    with pytest.raises(KeyError, match="Unknown preset"):
        get_preset("nonexistent")


def test_list_presets():
    names = list_presets()
    assert "default" in names
    assert "minimal" in names
    assert "voice" in names


def test_register_custom_preset():
    from parrot.bots.prompts.builder import PromptBuilder
    register_preset("custom_test", PromptBuilder.minimal)
    builder = get_preset("custom_test")
    assert builder.get("identity") is not None
    assert builder.get("tools") is None


def test_preset_returns_independent_instances():
    b1 = get_preset("default")
    b2 = get_preset("default")
    b1.remove("tools")
    assert b2.get("tools") is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/composable-prompt-layer.spec.md`) Section 3.4 for full context.
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
3. **Implement** following the scope and notes above.
4. **Run tests**: `pytest tests/bots/prompts/test_presets.py -v`
5. **Verify** all acceptance criteria are met.
6. **Move this file** to `sdd/tasks/completed/TASK-327-presets-registry.md`.
7. **Update index** → `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
