# TASK-1453: Add new public exports to scraping __init__.py

**Feature**: FEAT-222 — ScrapingFlow: Composable Long-Horizon Scraping
**Spec**: `sdd/specs/scrapingflow-composable-scraping.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1445, TASK-1448, TASK-1449, TASK-1450, TASK-1451, TASK-1452
**Assigned-to**: unassigned

---

## Context

All new modules need to be importable from `parrot_tools.scraping`. This task adds the
imports and `__all__` entries for the new public types.

Implements spec §Module 9 (Exports & integration).

---

## Scope

- Add imports for: `TemplatePlan`, `ParamSpec`, `ScrapingFlow`, `FlowNode`, `FlowExecutor`,
  `FlowResult`, `PageDriver`, `SessionManager`
- Add all to `__all__` list
- Verify all imports resolve correctly
- Run existing tests to confirm no regressions

**NOT in scope**: Any implementation changes to the new modules

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/__init__.py` | MODIFY | Add imports and __all__ entries |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Current __init__.py exports 29 symbols. Add these:
from parrot_tools.scraping.template_plan import TemplatePlan, ParamSpec  # TASK-1448
from parrot_tools.scraping.flow_models import ScrapingFlow, FlowNode, FlowResult  # TASK-1449
from parrot_tools.scraping.flow_executor import FlowExecutor  # TASK-1452
from parrot_tools.scraping.drivers.page_driver import PageDriver  # TASK-1450
from parrot_tools.scraping.session_manager import SessionManager  # TASK-1451
```

### Does NOT Exist
- ~~`parrot_tools.scraping.advanced_actions` in __all__~~ — internal module, not exported

---

## Acceptance Criteria

- [ ] All new types importable from `parrot_tools.scraping`
- [ ] `__all__` updated with all new public symbols
- [ ] Existing tests still pass: `pytest packages/ai-parrot-tools/tests/scraping/ -v`
- [ ] Import test: `from parrot_tools.scraping import TemplatePlan, ScrapingFlow, FlowExecutor`

---

## Completion Note

*(Agent fills this in when done)*
