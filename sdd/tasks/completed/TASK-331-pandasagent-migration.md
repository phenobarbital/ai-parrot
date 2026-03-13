# TASK-331: PandasAgent Prompt Migration

**Feature**: Composable Prompt Layer System
**Spec**: `sdd/specs/composable-prompt-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-329, TASK-328
**Assigned-to**: —

---

## Context

> Migrates PandasAgent to use the default PromptBuilder preset with the `DATAFRAME_CONTEXT_LAYER` domain layer added. This replaces the data-specific prompt template with composable layers.
> Implements spec Section 5.3.

---

## Scope

- Modify `parrot/bots/data.py` (PandasAgent):
  - In `__init__()`, set `prompt_preset="default"` (or initialize `_prompt_builder` directly)
  - Add `DATAFRAME_CONTEXT_LAYER` from domain_layers to the builder
  - Optionally add `STRICT_GROUNDING_LAYER` if PandasAgent needs strict data grounding behavior
  - Ensure dataframe schema info is passed as `dataframe_schemas` in the context
- Verify the prompt includes `<dataframe_context>` when dataframe schemas are available

**NOT in scope**: Modifying other bot types, changing dataframe schema extraction logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/data.py` | MODIFY | Add PromptBuilder with dataframe context layer |

---

## Implementation Notes

- Import `DATAFRAME_CONTEXT_LAYER` from `parrot.bots.prompts.domain_layers`.
- The existing dataframe schema logic (how schemas are extracted from DataFrames) stays unchanged — only the prompt assembly changes.
- PandasAgent may also benefit from `STRICT_GROUNDING_LAYER` since it works with structured data (spec Section 7.2).
- Check existing `parrot/bots/prompts/data.py` for any data-specific prompt content that needs to be preserved as a layer.

---

## Acceptance Criteria

- [ ] PandasAgent uses PromptBuilder with `DATAFRAME_CONTEXT_LAYER` added.
- [ ] When dataframe schemas are available, prompt includes `<dataframe_context>`.
- [ ] When no schemas, the dataframe context layer is conditionally omitted.
- [ ] Existing data analysis functionality unchanged.
- [ ] Existing PandasAgent tests still pass (if any).

---

## Test Specification

```python
# tests/bots/prompts/test_pandasagent_prompt.py
import pytest


def test_pandasagent_has_dataframe_layer():
    """PandasAgent should have DATAFRAME_CONTEXT_LAYER in its builder."""
    from parrot.bots.data import PandasAgent
    # Check that the builder includes dataframe_context layer
    pass


def test_pandasagent_prompt_includes_schema():
    """When dataframe schemas are provided, prompt should include them."""
    pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/composable-prompt-layer.spec.md`) Sections 3.5 and 5.3.
2. **Read `parrot/bots/data.py`** to understand current PandasAgent structure.
3. **Read `parrot/bots/prompts/data.py`** for existing data-specific prompts.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** following the scope above.
6. **Run tests**: `pytest tests/bots/ -v -k pandas or data`
7. **Verify** all acceptance criteria are met.
8. **Move this file** to `sdd/tasks/completed/TASK-331-pandasagent-migration.md`.
9. **Update index** → `"done"`.
10. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
