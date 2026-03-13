# TASK-332: YAML & BotManager Prompt Config Integration

**Feature**: Composable Prompt Layer System
**Spec**: `sdd/specs/composable-prompt-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-327, TASK-328, TASK-329
**Assigned-to**: —

---

## Context

> Enables YAML-based agent definitions to configure prompt layers declaratively. BotManager reads the `prompt:` section from YAML and builds a PromptBuilder accordingly, supporting preset selection, layer removal, domain layer addition, and layer customization.
> Implements spec Sections 5.4 and 5.6.

---

## Scope

- Modify `parrot/manager/manager.py` (or relevant BotManager file):
  - Add `_build_prompt_builder(bot_model) -> Optional[PromptBuilder]` method
  - Parse `prompt_config` from YAML agent definition with fields:
    - `preset` (str) — name of preset to start from (default: "default")
    - `remove` (list[str]) — layer names to remove
    - `add` (list[str | dict]) — domain layers to add (by name or inline definition)
    - `customize` (dict) — override existing layer templates
  - When `prompt_config` is set, create PromptBuilder and assign to bot's `_prompt_builder`
  - When `prompt_config` is not set, fall through to legacy `system_prompt_template` behavior
- Backward compatibility: YAML agents with `system_prompt_template` and no `prompt:` section continue working unchanged.

**NOT in scope**: DB schema changes, Chatbot migration, admin UI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/manager/manager.py` | MODIFY | Add `_build_prompt_builder()` and wire it into bot creation |

---

## Implementation Notes

- Use `get_preset(name)` from presets registry to get the base builder.
- Use `get_domain_layer(name)` from domain_layers for string-based layer references.
- For dict-based layer additions, create inline `PromptLayer` instances.
- For `customize`, get the existing layer, create a new `PromptLayer` with overridden template but same name/priority/condition.
- YAML example from spec Section 5.4 should work:
  ```yaml
  prompt:
    preset: default
    remove:
      - tools
    add:
      - name: company_context
        priority: 35
    customize:
      behavior:
        template: |
          <response_style>
          Be empathetic and supportive.
          $rationale
          </response_style>
  ```

---

## Acceptance Criteria

- [ ] YAML agents without `prompt:` section use legacy path — zero behavior change.
- [ ] YAML agents with `prompt.preset` get the named preset.
- [ ] `prompt.remove` removes specified layers from the builder.
- [ ] `prompt.add` with string name references a registered domain layer.
- [ ] `prompt.add` with dict creates an inline layer.
- [ ] `prompt.customize` overrides existing layer templates.
- [ ] Built PromptBuilder is assigned to bot's `_prompt_builder`.

---

## Test Specification

```python
# tests/manager/test_botmanager_prompt_config.py
import pytest
from unittest.mock import MagicMock


def test_build_prompt_builder_from_yaml():
    """BotManager should parse YAML prompt config and build PromptBuilder."""
    pass


def test_yaml_without_prompt_config_uses_legacy():
    """YAML agents without prompt: section should use legacy path."""
    pass


def test_yaml_preset_selection():
    """prompt.preset should select the named preset."""
    pass


def test_yaml_remove_layers():
    """prompt.remove should remove specified layers."""
    pass


def test_yaml_add_domain_layer_by_name():
    """prompt.add with string name should reference domain layer."""
    pass


def test_yaml_customize_layer_template():
    """prompt.customize should override layer template."""
    pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/composable-prompt-layer.spec.md`) Sections 5.4 and 5.6.
2. **Read `parrot/manager/manager.py`** to understand bot creation flow.
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
4. **Implement** following the scope above.
5. **Run tests**: `pytest tests/manager/ -v`
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-332-yaml-botmanager-integration.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
