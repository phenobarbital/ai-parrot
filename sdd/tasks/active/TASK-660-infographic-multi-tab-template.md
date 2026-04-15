# TASK-660: Multi-Tab Template Definition

**Feature**: Multi-Tab Infographic Template + New Component Blocks
**Spec**: `sdd/specs/multi-tab-infographic.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-659
**Assigned-to**: unassigned

---

## Context

This task implements Spec Section 3 (Module 2: Multi-Tab Template). It creates the `TEMPLATE_MULTI_TAB` template definition and extends `to_prompt_instruction()` to generate LLM instructions that describe the tab_view block structure, allowed inner block types, and nesting constraints.

---

## Scope

- Define `TEMPLATE_MULTI_TAB` as an `InfographicTemplate` with:
  - `name="multi_tab"`
  - Block specs: TITLE (required) + TAB_VIEW (required, min_items=3, max_items=7)
  - `default_theme="light"`
  - Description covering multi-section reports, methodologies, process documentation
- Extend `InfographicTemplate.to_prompt_instruction()` to handle TAB_VIEW block type:
  - Generate instructions describing TabPane structure (id, label, icon, blocks)
  - List allowed inner block types for tab panes
  - Specify nesting constraints (no TabView inside tabs, no Accordion inside Accordion)
  - Indicate that the first tab should contain an overview/introduction
- Register `TEMPLATE_MULTI_TAB` in `_register_builtins()`
- Write tests for the new template and prompt generation

**NOT in scope**: Template auto-detection logic (TASK-665), renderer changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/infographic_templates.py` | MODIFY | Add TEMPLATE_MULTI_TAB, extend to_prompt_instruction(), update _register_builtins() |
| `tests/test_infographic_html.py` or new test file | MODIFY | Add tests for template registration and prompt generation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.infographic import BlockType  # verified: infographic.py:40
from parrot.models.infographic_templates import (
    BlockSpec,                    # verified: infographic_templates.py:21
    InfographicTemplate,          # verified: infographic_templates.py:47
    InfographicTemplateRegistry,  # verified: infographic_templates.py:310
    infographic_registry,         # verified: infographic_templates.py:382
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/infographic_templates.py:21-44
class BlockSpec(BaseModel):
    block_type: BlockType                               # line 22
    required: bool = True                               # line 23
    description: Optional[str] = None                   # line 24
    min_items: Optional[int] = None                     # line 25
    max_items: Optional[int] = None                     # line 26
    constraints: Optional[Dict[str, str]] = {}          # line 27

# packages/ai-parrot/src/parrot/models/infographic_templates.py:47-93
class InfographicTemplate(BaseModel):
    name: str                                           # line 49
    description: str                                    # line 50
    block_specs: List[BlockSpec]                        # line 51
    default_theme: Optional[str] = None                 # line 55
    def to_prompt_instruction(self) -> str: ...         # line 60

# packages/ai-parrot/src/parrot/models/infographic_templates.py:320-330
def _register_builtins(self) -> None:
    for tpl in (
        TEMPLATE_BASIC, TEMPLATE_EXECUTIVE, TEMPLATE_DASHBOARD,
        TEMPLATE_COMPARISON, TEMPLATE_TIMELINE_REPORT, TEMPLATE_MINIMAL,
    ):
        self._templates[tpl.name] = tpl
```

### Does NOT Exist
- ~~`TEMPLATE_MULTI_TAB`~~ — to be created in this task
- ~~`BlockType.TAB_VIEW`~~ — created by TASK-659 (dependency)
- ~~`BlockType.ACCORDION`~~ — created by TASK-659
- ~~`BlockType.CHECKLIST`~~ — created by TASK-659

---

## Implementation Notes

### Pattern to Follow
```python
# Follow existing template pattern, e.g. TEMPLATE_EXECUTIVE (infographic_templates.py:133-179)
TEMPLATE_MULTI_TAB = InfographicTemplate(
    name="multi_tab",
    description="Multi-section report organized as tabbed views...",
    default_theme="light",
    block_specs=[
        BlockSpec(block_type=BlockType.TITLE, description="Main report title and subtitle"),
        BlockSpec(
            block_type=BlockType.TAB_VIEW,
            description="Tabbed navigation containing 3-7 tabs...",
            min_items=3, max_items=7,
        ),
    ],
)
```

### Key Constraints
- `to_prompt_instruction()` must detect when a BlockSpec has `block_type=BlockType.TAB_VIEW` and generate extended instructions for the LLM describing the TabPane structure.
- The extended instructions must list all allowed inner block types: summary, bullet_list, table, accordion, checklist, chart, hero_card, timeline, callout, progress, divider, quote, image.
- Must specify nesting constraints: "tab_view blocks must be top-level only", "accordion blocks inside tabs must not contain nested accordions".

### References in Codebase
- `packages/ai-parrot/src/parrot/models/infographic_templates.py` — the file being modified
- `packages/ai-parrot/src/parrot/models/infographic.py` — BlockType enum (modified by TASK-659)

---

## Acceptance Criteria

- [ ] `TEMPLATE_MULTI_TAB` is defined with correct BlockSpecs
- [ ] `infographic_registry.get("multi_tab")` returns the template
- [ ] `to_prompt_instruction()` generates tab-specific instructions when TAB_VIEW BlockSpec is present
- [ ] Prompt instructions include TabPane structure, allowed block types, and nesting constraints
- [ ] Existing templates still produce identical prompt instructions (zero regression)
- [ ] All tests pass: `pytest tests/ -v -k "infographic"`

---

## Test Specification

```python
import pytest
from parrot.models.infographic_templates import infographic_registry


class TestMultiTabTemplate:
    def test_registered(self):
        tpl = infographic_registry.get("multi_tab")
        assert tpl.name == "multi_tab"

    def test_block_specs(self):
        tpl = infographic_registry.get("multi_tab")
        types = [s.block_type.value for s in tpl.block_specs]
        assert "title" in types
        assert "tab_view" in types

    def test_prompt_instruction_contains_tab_info(self):
        tpl = infographic_registry.get("multi_tab")
        prompt = tpl.to_prompt_instruction()
        assert "tab_view" in prompt
        assert "tabs" in prompt.lower()
        assert "blocks" in prompt.lower()

    def test_existing_templates_unchanged(self):
        """Ensure basic template prompt is not affected."""
        tpl = infographic_registry.get("basic")
        prompt = tpl.to_prompt_instruction()
        assert "tab_view" not in prompt
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/multi-tab-infographic.spec.md` for full context
2. **Check dependencies** — verify TASK-659 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm BlockType.TAB_VIEW exists (added by TASK-659)
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-660-infographic-multi-tab-template.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
