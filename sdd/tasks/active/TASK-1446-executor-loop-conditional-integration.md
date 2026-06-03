# TASK-1446: Integrate advanced actions into executor

**Feature**: FEAT-222 — ScrapingFlow: Composable Long-Horizon Scraping
**Spec**: `sdd/specs/scrapingflow-composable-scraping.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1445
**Assigned-to**: unassigned

---

## Context

`execute_plan_steps` currently stubs Loop and Conditional actions (executor.py:280-292),
logging a warning and returning True. This task replaces that stub with calls to
`advanced_actions.exec_loop` / `exec_conditional`, fixing the existing gap in
`WebScrapingToolkit`.

Implements spec §Module 4 (executor integration).

---

## Scope

- Modify `_dispatch_step` in executor.py to call `exec_loop` for "loop" actions and
  `exec_conditional` for "conditional" actions
- Create a `dispatch_step_fn` closure wrapping `_dispatch_step` itself for recursive execution
- Only promote `loop` and `conditional` — other stubbed actions remain as-is
- Add tests verifying the executor now dispatches these action types

**NOT in scope**: Modifying tool.py (TASK-1447), creating advanced_actions (TASK-1445)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` | MODIFY | Replace stub with advanced_actions calls |
| `packages/ai-parrot-tools/tests/scraping/test_executor.py` | MODIFY | Add tests for loop/conditional dispatch |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.advanced_actions import exec_loop, exec_conditional  # created in TASK-1445
from parrot_tools.scraping.models import Loop, Conditional, ScrapingStep  # models.py:679, 651, 758
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py
# The stub to replace (lines 280-292):
#   elif action_type in ("get_cookies", "set_cookies", "authenticate",
#       "await_human", "await_keypress", "await_browser_event",
#       "upload_file", "wait_for_download", "loop", "conditional"):
#       logger.warning(...)
#       return True

# _dispatch_step signature (called by execute_plan_steps in the step loop):
async def _dispatch_step(
    driver: AbstractDriver,
    step: ScrapingStep,
    url: str,
    timeout: int,
    step_extracted: Dict[str, Any],
) -> bool: ...
```

### Does NOT Exist
- ~~`execute_plan_steps` handling Loop natively~~ — it's currently stubbed; this task fixes that
- ~~`executor.exec_loop`~~ — lives in advanced_actions, not executor

---

## Implementation Notes

### Key Constraints
- Split "loop" and "conditional" out of the existing stub's `elif` block into their own branches
- The remaining actions (get_cookies, set_cookies, authenticate, await_human, etc.) stay stubbed
- The dispatch_step_fn closure must match the callback signature from TASK-1445

---

## Acceptance Criteria

- [ ] `_dispatch_step` calls `exec_loop` when action_type is "loop"
- [ ] `_dispatch_step` calls `exec_conditional` when action_type is "conditional"
- [ ] Other stubbed actions (get_cookies, authenticate, etc.) remain unchanged
- [ ] Recursive loops (loop-within-loop) work via the dispatch_step_fn closure
- [ ] Existing executor tests still pass: `pytest packages/ai-parrot-tools/tests/scraping/test_executor.py -v`

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_executor_dispatches_loop():
    """Loop action is now executed, not stubbed."""
    driver = AsyncMock()
    plan = ScrapingPlan(url="http://example.com", objective="test", steps=[
        {"action": "loop", "iterations": 2, "actions": [{"action": "click", "selector": ".item"}]}
    ], tags=[])
    result = await execute_plan_steps(driver, plan)
    assert driver.click.call_count == 2

@pytest.mark.asyncio
async def test_executor_dispatches_conditional():
    """Conditional action is now executed, not stubbed."""
    driver = AsyncMock()
    driver.wait_for_selector = AsyncMock()
    # ... test conditional dispatch
```

---

## Completion Note

*(Agent fills this in when done)*
