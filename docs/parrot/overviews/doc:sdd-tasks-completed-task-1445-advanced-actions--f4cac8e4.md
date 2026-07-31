---
type: Wiki Overview
title: 'TASK-1445: Extract advanced actions from legacy WebScrapingTool'
id: doc:sdd-tasks-completed-task-1445-advanced-actions-extraction-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Loop and Conditional actions are fully implemented only in the legacy `WebScrapingTool`
relates_to:
- concept: mod:parrot_tools.scraping.advanced_actions
  rel: mentions
- concept: mod:parrot_tools.scraping.drivers.abstract
  rel: mentions
- concept: mod:parrot_tools.scraping.models
  rel: mentions
---

# TASK-1445: Extract advanced actions from legacy WebScrapingTool

**Feature**: FEAT-222 — ScrapingFlow: Composable Long-Horizon Scraping
**Spec**: `sdd/specs/scrapingflow-composable-scraping.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Loop and Conditional actions are fully implemented only in the legacy `WebScrapingTool`
(tool.py). The modern `WebScrapingToolkit` delegates to `execute_plan_steps`, which stubs
these actions (logs warning, returns True). This task extracts the implementations into a
shared module so they're available to the executor, the toolkit, and the future FlowExecutor.

Implements spec §Module 3 (advanced_actions).

---

## Scope

- Create `advanced_actions.py` with three standalone functions:
  - `exec_loop(driver, loop_action, dispatch_step_fn, base_url, timeout)` — extracted from
    `WebScrapingTool._exec_loop` (tool.py:2582-2664)
  - `exec_conditional(driver, cond_action, dispatch_step_fn, base_url, timeout)` — extracted from
    `WebScrapingTool._exec_conditional` (tool.py:2456-2580)
  - `substitute_template_vars(value, index, start_index, values, value_name)` — extracted from
    `WebScrapingTool._substitute_template_vars` (tool.py:3271-3338)
- Functions must be stateless: accept `AbstractDriver` and a `dispatch_step_fn` callback
  instead of referencing `self._driver`, `self._page`, `self._execute_step`
- Replace `self._current_context` condition evaluation with `driver.evaluate()`
- Write comprehensive unit tests

**NOT in scope**: Modifying executor.py or tool.py (those are TASK-1446 and TASK-1447)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py` | CREATE | Standalone exec_loop, exec_conditional, substitute_template_vars |
| `packages/ai-parrot-tools/tests/scraping/test_advanced_actions.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.models import Loop, Conditional, ScrapingStep, ACTION_MAP  # models.py:679, 651, 758, 726
from parrot_tools.scraping.drivers.abstract import AbstractDriver  # drivers/abstract.py:11
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py
class Loop(BrowserAction):  # line 679
    actions: List["ActionList"]
    iterations: Optional[int] = None
    condition: Optional[str] = None
    values: Optional[List[Any]] = None
    value_name: Optional[str] = "value"
    break_on_error: bool = True
    max_iterations: int = 100
    start_index: int = 0
    do_replace: bool = True

class Conditional(BrowserAction):  # line 651
    target: Optional[str] = None
    target_type: Literal["css", "xpath"] = "css"
    condition_type: Literal["text_contains", "exists", "not_exists", "text_equals", "attribute_equals"]
    expected_value: str
    timeout: int = 5
    actions_if_true: Optional[List["ActionList"]] = None
    actions_if_false: Optional[List["ActionList"]] = None

class ScrapingStep:  # line 758
    action: BrowserAction
    description: str = ""
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScrapingStep": ...  # line 789

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py
class AbstractDriver(ABC):  # line 11
    async def evaluate(self, expression: str) -> Any: ...  # line 233
    async def wait_for_selector(self, selector: str, timeout: int = 10, state: str = "visible") -> None: ...  # line 184
    async def get_text(self, selector: str, timeout: int = 10) -> str: ...  # line 140
    async def get_attribute(self, selector: str, attribute: str, timeout: int = 10) -> Optional[str]: ...  # line 151

# EXTRACTION SOURCES (read these for implementation logic):
# packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py
# WebScrapingTool._exec_loop: line 2582-2664
# WebScrapingTool._exec_conditional: line 2456-2580
# WebScrapingTool._substitute_template_vars: line 3271-3338
# WebScrapingTool._substitute_action_vars: line 3340 (may need extraction too)
```

### Does NOT Exist
- ~~`parrot_tools.scraping.advanced_actions`~~ — this is what you're creating
- ~~`AbstractDriver.execute_step()`~~ — not a method; step dispatch is a callback
- ~~`Loop.execute()`~~ — Loop is a data model, not executable; use exec_loop()

---

## Implementation Notes

### Pattern to Follow
Read the legacy implementations thoroughly before extracting:
```python
# The dispatch_step_fn callback signature matches executor._dispatch_step:
async def dispatch_step_fn(
    driver: AbstractDriver,
    step: ScrapingStep,
    url: str,
    timeout: int,
    step_extracted: Dict[str, Any],
) -> bool: ...
```

### Key Constraints
- Functions must be async (exec_loop, exec_conditional)
- substitute_template_vars is sync (string manipulation only)
- Use safe eval for arithmetic in template vars (no builtins) — replicate the existing
  safety pattern from tool.py
- The regex pattern for Loop vars is: `r'\{([^}]*(?:i|index|iteration)[^}]*)\}'`
- Support {i}, {index}, {iteration}, {i+1}, {i-1}, {i*2}, {value}
- `exec_loop` must handle: fixed iterations, value-list iteration, JS condition loops,
  break_on_error, max_iterations safety limit, start_index offset
- `exec_conditional` must handle: exists, not_exists, text_contains, text_equals,
  attribute_equals condition types

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py:2456-2664` — source of extraction
- `packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py:3271-3340` — template vars source

---

## Acceptance Criteria

- [ ] `exec_loop` handles fixed iterations with template var substitution
- [ ] `exec_loop` handles value-list iteration with {value} substitution
- [ ] `exec_loop` handles JS condition-based loops
- [ ] `exec_loop` respects break_on_error and max_iterations
- [ ] `exec_conditional` evaluates all 5 condition_types correctly
- [ ] `exec_conditional` dispatches to actions_if_true / actions_if_false
- [ ] `substitute_template_vars` handles {i}, {index}, arithmetic, {value}, nested dicts/lists
- [ ] All functions are stateless (no self references)
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_advanced_actions.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot_tools.scraping.advanced_actions import exec_loop, exec_conditional, substitute_template_vars
from parrot_tools.scraping.models import Loop, Conditional


class TestSubstituteTemplateVars:
    def test_simple_index(self):
        assert substitute_template_vars("item-{i}", 3) == "item-3"

    def test_arithmetic(self):
        assert substitute_template_vars("page-{i+1}", 0) == "page-1"

    def test_value_substitution(self):
        assert substitute_template_vars("{value}", 0, values=["a", "b"], value_name="value") == "a"

    def test_nested_dict(self):
        result = substitute_template_vars({"url": "page-{i}", "count": 5}, 2)
        assert result == {"url": "page-2", "count": 5}

    def test_nested_list(self):
        result = substitute_template_vars(["item-{i}", "other"], 1)
        assert result == ["item-1", "other"]


class TestExecLoop:
    @pytest.mark.asyncio
    async def test_fixed_iterations(self):
        driver = AsyncMock()
        dispatch = AsyncMock(return_value=True)
        action = Loop(actions=[{"action": "click", "selector": ".btn"}], iterations=3)
        result = await exec_loop(driver, action, dispatch)
        assert dispatch.call_count == 3

    @pytest.mark.asyncio
    async def test_break_on_error(self):
        driver = AsyncMock()
        dispatch = AsyncMock(side_effect=[True, False])
        action = Loop(actions=[{"action": "click", "selector": ".btn"}], iterations=5, break_on_error=True)
        result = await exec_loop(driver, action, dispatch)
        assert dispatch.call_count == 2


class TestExecConditional:
    @pytest.mark.asyncio
    async def test_true_branch(self):
        driver = AsyncMock()
        driver.wait_for_selector = AsyncMock()
        dispatch = AsyncMock(return_value=True)
        action = Conditional(
            target=".element", condition_type="exists", expected_value="true",
            actions_if_true=[{"action": "click", "selector": ".btn"}],
        )
        await exec_conditional(driver, action, dispatch)
        assert dispatch.called
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Read the extraction sources**: tool.py lines 2456-2664 and 3271-3340
4. **Verify the Codebase Contract** — confirm Loop/Conditional models still match
5. **Implement** the three functions, keeping them stateless
6. **Run tests** to verify all acceptance criteria
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

Created `advanced_actions.py` with three stateless helpers:
`substitute_template_vars` (sync), `exec_loop` and `exec_conditional` (async).
Functions accept an `AbstractDriver` + a `dispatch_step_fn` callback matching
`executor._dispatch_step`'s signature `(driver, step, url, timeout, step_extracted)`.

- `substitute_template_vars` supports `{i}`, `{index}`, `{iteration}`,
  arithmetic (`{i+1}`, `{i-1}`, `{i*2}`, `{index+1}`) via no-builtins `eval`,
  `{value}` / `{<value_name>}` substitution, and recursive dict/list walking.
  Arithmetic token replacement uses word boundaries (longest-first) to fix the
  legacy bug where `{index+1}` was corrupted by the single-letter `i` replace.
- `exec_loop` handles fixed iterations, value-list iteration, JS condition
  gating (via `driver.evaluate`), `break_on_error`, `max_iterations`, and
  `start_index`.
- `exec_conditional` evaluates all 5 condition types (`exists`, `not_exists`,
  `text_contains`, `text_equals`, `attribute_equals`) through `AbstractDriver`
  and dispatches the true/false branch.

`_substitute_action_vars` was extracted as a private helper (model_dump →
substitute → reconstruct) since it is reused by `exec_loop` and is generic.

28 unit tests pass; `ruff` clean. Did NOT modify `executor.py` or `tool.py`
(reserved for TASK-1446 / TASK-1447).
