# TASK-1775: Register `crew_report` Infographic Template Variant

**Feature**: FEAT-308 — AgentCrew ResultAgent End-of-Flow Multi-Tab Infographic Node
**Spec**: `sdd/specs/agentcrew-node-infographic.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Spec §3 Module 1. The existing `multi_tab` template hard-clamps `TAB_VIEW`
> to `min_items=3, max_items=7` (infographic_templates.py:476-477). A crew
> run with 1 agent (3 tabs) or 8+ agents (10+ tabs) would raise
> `SLOT_ITEM_COUNT_INVALID`. This task registers a bound-relaxed
> `crew_report` variant that allows dynamic tab counts (min 1, no max).

---

## Scope

- Define `TEMPLATE_CREW_REPORT` as an `InfographicTemplate` with:
  - `name="crew_report"`
  - `block_specs`: TITLE (required) + TAB_VIEW (required, **no** `min_items`/`max_items`).
- Register it on `infographic_registry` at module import.
- Write unit test: `test_crew_report_template_registered`.

**NOT in scope**: Modifying the existing `multi_tab` template. Modifying `InfographicToolkit`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/infographic_templates.py` | MODIFY | Add `TEMPLATE_CREW_REPORT` definition and register in `_register_builtins` |
| `tests/unit/test_crew_report_template.py` | CREATE | Unit test for template registration and schema validation |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, class names, and method signatures.

### Verified Imports
```python
from parrot.models.infographic_templates import (
    InfographicTemplate,    # verified: infographic_templates.py
    BlockSpec,              # verified: infographic_templates.py
    BlockType,              # verified: infographic_templates.py (enum)
    infographic_registry,   # verified: infographic_templates.py:559
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/infographic_templates.py

# Line 452 — existing multi_tab template (reference pattern, DO NOT modify)
TEMPLATE_MULTI_TAB = InfographicTemplate(
    name="multi_tab",
    # ...
    block_specs=[
        BlockSpec(block_type=BlockType.TITLE, description="...", required=True),
        BlockSpec(block_type=BlockType.TAB_VIEW, description="...", required=True,
                  min_items=3, max_items=7),  # ← the clamp to relax
    ],
)

# Line 485
class InfographicTemplateRegistry:
    def register(self, template: InfographicTemplate) -> None: ...   # L509
    def get(self, name: str) -> InfographicTemplate: ...             # L517
    def list_templates(self) -> List[str]: ...                       # L538

# Line 559 — module singleton
infographic_registry = InfographicTemplateRegistry()

# Lines 496-507 — _register_builtins() registers all built-in templates
```

### Does NOT Exist
- ~~`crew_report` template~~ — not registered; this task creates it.
- ~~`BlockSpec.unbounded` or `BlockSpec(dynamic=True)`~~ — no such API; omit `min_items`/`max_items` to leave unclamped.

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the TEMPLATE_MULTI_TAB pattern at line 452
TEMPLATE_CREW_REPORT = InfographicTemplate(
    name="crew_report",
    description="Crew execution report: exec summary + final result + per-agent tabs.",
    default_theme="light",
    block_specs=[
        BlockSpec(block_type=BlockType.TITLE, description="Report title", required=True),
        BlockSpec(
            block_type=BlockType.TAB_VIEW,
            description="1..N tabs: Exec Summary, Final Result, then one per research agent.",
            required=True,
            # NO min_items / max_items — dynamic count
        ),
    ],
)
```

### Key Constraints
- Register inside `_register_builtins()` alongside the other built-in templates.
- Do NOT modify `TEMPLATE_MULTI_TAB` or any other existing template.
- The `TAB_VIEW` BlockSpec must have **no** `min_items` and **no** `max_items`.

---

## Acceptance Criteria

- [ ] `infographic_registry.get("crew_report")` returns a template
- [ ] Template has a `TAB_VIEW` block with no min/max items
- [ ] Template has a required `TITLE` block
- [ ] Existing `multi_tab` template is unchanged (min_items=3, max_items=7)
- [ ] Unit test passes: `pytest tests/unit/test_crew_report_template.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models/infographic_templates.py`

---

## Test Specification

```python
# tests/unit/test_crew_report_template.py
import pytest
from parrot.models.infographic_templates import infographic_registry, BlockType


class TestCrewReportTemplate:
    def test_crew_report_template_registered(self):
        """crew_report is discoverable in the registry."""
        tpl = infographic_registry.get("crew_report")
        assert tpl is not None
        assert tpl.name == "crew_report"

    def test_tab_view_no_clamp(self):
        """TAB_VIEW block has no min_items / max_items."""
        tpl = infographic_registry.get("crew_report")
        tab_spec = next(s for s in tpl.block_specs if s.block_type == BlockType.TAB_VIEW)
        assert tab_spec.min_items is None or tab_spec.min_items == 0
        assert tab_spec.max_items is None or tab_spec.max_items == 0

    def test_multi_tab_unchanged(self):
        """Existing multi_tab template retains its 3-7 clamp."""
        tpl = infographic_registry.get("multi_tab")
        tab_spec = next(s for s in tpl.block_specs if s.block_type == BlockType.TAB_VIEW)
        assert tab_spec.min_items == 3
        assert tab_spec.max_items == 7
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentcrew-node-infographic.spec.md` §3 Module 1
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm `infographic_templates.py` still has `_register_builtins` and the `TEMPLATE_MULTI_TAB` pattern
4. **Implement** the `TEMPLATE_CREW_REPORT` definition and register it
5. **Write and run** unit tests
6. **Update status** and move to completed when done

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
