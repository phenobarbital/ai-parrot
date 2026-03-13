# TASK-328: Domain-Specific Layers

**Feature**: Composable Prompt Layer System
**Spec**: `sdd/specs/composable-prompt-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-325
**Assigned-to**: —

---

## Context

> Domain-specific layers provide reusable prompt components for specialized bot types (PandasAgent, SQL agents, company bots, crew orchestration). These extend the built-in layers without modifying them.
> Implements spec Section 3.5.

---

## Scope

- Create `parrot/bots/prompts/domain_layers.py` with:
  - `DATAFRAME_CONTEXT_LAYER` — priority KNOWLEDGE+5, conditional on `dataframe_schemas`, `<dataframe_context>` XML wrapper
  - `SQL_DIALECT_LAYER` — priority TOOLS+5, conditional on `dialect`, `<sql_policy>` XML wrapper with `$dialect` and `$top_k`
  - `COMPANY_CONTEXT_LAYER` — priority KNOWLEDGE+10, conditional on `company_information`, `<company_information>` XML wrapper
  - `CREW_CONTEXT_LAYER` — priority KNOWLEDGE+15, conditional on `crew_context`, `<prior_agent_results>` XML wrapper
  - `STRICT_GROUNDING_LAYER` — priority BEHAVIOR-5, `<grounding_policy>` XML wrapper (for data-analysis agents)
  - `get_domain_layer(name) -> PromptLayer` — lookup function for registered domain layers (used by BotManager)
- All layers use XML tags for structure (spec Section 4.2 rules).

**NOT in scope**: PromptBuilder, presets, bot integration, BotManager YAML parsing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/prompts/domain_layers.py` | CREATE | Domain-specific layer constants + lookup function |

---

## Implementation Notes

- Import `PromptLayer` and `LayerPriority` from `layers.py` (TASK-325).
- Priorities use arithmetic on `LayerPriority` values (e.g., `LayerPriority.KNOWLEDGE + 5`) to position domain layers between built-in layers.
- `get_domain_layer()` maintains an internal dict mapping names to layer instances. Raises `KeyError` with available names if not found.
- `STRICT_GROUNDING_LAYER` replaces the removed anti-hallucination block from `AGENT_PROMPT` (spec Section 7.2).

---

## Acceptance Criteria

- [ ] All 5 domain layers defined with correct priorities, templates, and conditions.
- [ ] Each layer uses XML tags for structure, no Markdown headers as delimiters.
- [ ] Conditional layers return `None` when their data is empty/missing.
- [ ] `get_domain_layer("dataframe_context")` returns `DATAFRAME_CONTEXT_LAYER`.
- [ ] `get_domain_layer("unknown")` raises `KeyError` with available names.
- [ ] Module imports cleanly alongside `layers.py`.

---

## Test Specification

```python
# tests/bots/prompts/test_domain_layers.py
import pytest
from parrot.bots.prompts.domain_layers import (
    DATAFRAME_CONTEXT_LAYER, SQL_DIALECT_LAYER,
    COMPANY_CONTEXT_LAYER, CREW_CONTEXT_LAYER,
    STRICT_GROUNDING_LAYER, get_domain_layer,
)
from parrot.bots.prompts.layers import LayerPriority


def test_dataframe_layer_conditional():
    assert DATAFRAME_CONTEXT_LAYER.render({"dataframe_schemas": ""}) is None
    result = DATAFRAME_CONTEXT_LAYER.render({"dataframe_schemas": "col1: int, col2: str"})
    assert "<dataframe_context>" in result


def test_sql_dialect_layer():
    ctx = {"dialect": "PostgreSQL", "top_k": "10"}
    result = SQL_DIALECT_LAYER.render(ctx)
    assert "PostgreSQL" in result
    assert "<sql_policy>" in result


def test_company_context_conditional():
    assert COMPANY_CONTEXT_LAYER.render({"company_information": ""}) is None
    result = COMPANY_CONTEXT_LAYER.render({"company_information": "Acme Corp"})
    assert "<company_information>" in result


def test_strict_grounding_layer():
    result = STRICT_GROUNDING_LAYER.render({})
    assert "<grounding_policy>" in result


def test_get_domain_layer():
    layer = get_domain_layer("dataframe_context")
    assert layer is DATAFRAME_CONTEXT_LAYER


def test_get_domain_layer_unknown():
    with pytest.raises(KeyError):
        get_domain_layer("nonexistent")


def test_priority_ordering():
    assert DATAFRAME_CONTEXT_LAYER.priority > LayerPriority.KNOWLEDGE
    assert SQL_DIALECT_LAYER.priority > LayerPriority.TOOLS
    assert STRICT_GROUNDING_LAYER.priority < LayerPriority.BEHAVIOR
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/composable-prompt-layer.spec.md`) Sections 3.5 and 7.2 for full context.
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
3. **Implement** following the scope and notes above.
4. **Run tests**: `pytest tests/bots/prompts/test_domain_layers.py -v`
5. **Verify** all acceptance criteria are met.
6. **Move this file** to `sdd/tasks/completed/TASK-328-domain-layers.md`.
7. **Update index** → `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
