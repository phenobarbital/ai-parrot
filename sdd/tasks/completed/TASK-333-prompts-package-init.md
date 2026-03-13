# TASK-333: Prompts Package __init__.py & Legacy Compat

**Feature**: Composable Prompt Layer System
**Spec**: `sdd/specs/composable-prompt-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-325, TASK-326, TASK-327, TASK-328
**Assigned-to**: —

---

## Context

> Updates the `parrot/bots/prompts/__init__.py` to re-export new prompt layer components while maintaining backward compatibility with existing imports of legacy prompt constants.
> Implements spec Section 9 (File Structure).

---

## Scope

- Modify `parrot/bots/prompts/__init__.py`:
  - Re-export new components: `PromptLayer`, `LayerPriority`, `RenderPhase`, `PromptBuilder`, all built-in layers, `get_preset`, `register_preset`, `list_presets`
  - Keep existing re-exports of `BASIC_SYSTEM_PROMPT`, `AGENT_PROMPT`, `COMPANY_SYSTEM_PROMPT`, `BASIC_VOICE_PROMPT_TEMPLATE` etc. for backward compatibility
  - Add deprecation comments on legacy exports
- Optionally create `parrot/bots/prompts/legacy.py`:
  - Move legacy prompt constants here (or keep them in their original locations with re-exports)
  - Only if the spec calls for it and existing imports won't break

**NOT in scope**: Deleting any legacy prompt constants, modifying bot code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/prompts/__init__.py` | MODIFY | Add re-exports for new modules, keep legacy exports |

---

## Implementation Notes

- Read the current `__init__.py` first to understand existing exports.
- The goal is additive: new imports work alongside old ones.
- Use `# Deprecated: use PromptBuilder instead` comments on legacy exports.
- Do NOT use `warnings.warn()` yet — that's for Phase 6 (deprecation phase).

---

## Acceptance Criteria

- [ ] `from parrot.bots.prompts import PromptLayer, PromptBuilder` works.
- [ ] `from parrot.bots.prompts import BASIC_SYSTEM_PROMPT` still works (backward compat).
- [ ] `from parrot.bots.prompts import get_preset, register_preset` works.
- [ ] `from parrot.bots.prompts.layers import IDENTITY_LAYER` works.
- [ ] No import errors when loading the package.

---

## Test Specification

```python
# tests/bots/prompts/test_prompts_init.py
import pytest


def test_new_imports():
    from parrot.bots.prompts import PromptLayer, PromptBuilder, LayerPriority
    assert PromptLayer is not None
    assert PromptBuilder is not None


def test_legacy_imports():
    from parrot.bots.prompts import BASIC_SYSTEM_PROMPT
    assert isinstance(BASIC_SYSTEM_PROMPT, str)


def test_preset_imports():
    from parrot.bots.prompts import get_preset, list_presets
    assert callable(get_preset)
    names = list_presets()
    assert "default" in names
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/composable-prompt-layer.spec.md`) Section 9.
2. **Read `parrot/bots/prompts/__init__.py`** to understand existing exports.
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
4. **Implement** following the scope above.
5. **Run tests**: `pytest tests/bots/prompts/test_prompts_init.py -v`
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-333-prompts-package-init.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
