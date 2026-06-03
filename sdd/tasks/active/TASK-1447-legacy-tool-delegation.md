# TASK-1447: Delegate legacy WebScrapingTool loop/conditional to advanced_actions

**Feature**: FEAT-222 — ScrapingFlow: Composable Long-Horizon Scraping
**Spec**: `sdd/specs/scrapingflow-composable-scraping.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1445
**Assigned-to**: unassigned

---

## Context

The legacy `WebScrapingTool` has the original Loop/Conditional implementations. Now that
they're extracted to `advanced_actions`, the legacy tool should delegate to the extracted
module to eliminate duplication.

Implements spec §Module 5 (legacy tool delegation).

---

## Scope

- Modify `WebScrapingTool._exec_loop` (tool.py:2582) to delegate to `advanced_actions.exec_loop`
- Modify `WebScrapingTool._exec_conditional` (tool.py:2456) to delegate to `advanced_actions.exec_conditional`
- Modify `WebScrapingTool._substitute_template_vars` (tool.py:3271) to delegate to `advanced_actions.substitute_template_vars`
- Create a `dispatch_step_fn` callback wrapping `self._execute_step` for the delegation
- Ensure all existing WebScrapingTool tests still pass (behavioral parity)

**NOT in scope**: Modifying executor.py (TASK-1446), removing the legacy methods entirely
(they become thin wrappers, not deleted — avoids breaking any direct callers)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py` | MODIFY | Delegate _exec_loop, _exec_conditional, _substitute_template_vars |
| `packages/ai-parrot-tools/tests/scraping/test_toolkit.py` | MODIFY | Verify delegation doesn't break existing behavior |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.advanced_actions import exec_loop, exec_conditional, substitute_template_vars  # TASK-1445
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py
class WebScrapingTool:  # line 119
    async def _exec_conditional(self, action: Conditional, base_url: str = "", args=None) -> bool: ...  # line 2456
    async def _exec_loop(self, action: Loop, base_url: str) -> bool: ...  # line 2582
    def _substitute_template_vars(self, value, index, start_index=0, values=None, value_name="value"): ...  # line 3271
    def _substitute_action_vars(self, action, index, start_index=0, values=None, value_name="value"): ...  # line 3340
```

### Does NOT Exist
- ~~`WebScrapingToolkit._exec_loop`~~ — only on legacy WebScrapingTool, not on the modern toolkit

---

## Acceptance Criteria

- [ ] `_exec_loop` delegates to `advanced_actions.exec_loop`
- [ ] `_exec_conditional` delegates to `advanced_actions.exec_conditional`
- [ ] `_substitute_template_vars` delegates to `advanced_actions.substitute_template_vars`
- [ ] All existing WebScrapingTool tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_toolkit.py -v`
- [ ] No behavioral changes from the user's perspective

---

## Completion Note

*(Agent fills this in when done)*
