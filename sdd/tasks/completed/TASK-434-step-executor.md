# TASK-434: Step Executor

**Feature**: FEAT-014 — WebScrapingToolkit
**Spec**: `sdd/specs/scraping-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-050
**Assigned-to**: claude-session

---

## Context

> This task implements Module 3 from the spec: extracting the step-execution logic
> from `WebScrapingTool._execute` into a standalone, reusable async function. This
> allows both `WebScrapingToolkit.scrape()` and `CrawlEngine` to share the same
> execution pipeline without duplicating code.

---

## Scope

- Extract step-execution logic from `WebScrapingTool._execute` into `execute_plan_steps()`
- Function signature: `async def execute_plan_steps(driver, plan, config) -> ScrapingResult`
- Handle action dispatch, retry logic, delay between actions, overlay housekeeping
- Support selector-based data extraction after steps complete
- Accept raw `steps` list (without full ScrapingPlan) for ad-hoc usage (per Open Question §7)
- Write unit tests with mock driver

**NOT in scope**: WebScrapingToolkit class (TASK-053), CrawlEngine (FEAT-013)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/executor.py` | CREATE | `execute_plan_steps()` function |
| `tests/tools/scraping/test_executor.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
import logging
import time
from typing import Any, Dict, List, Optional, Union

from .models import ScrapingResult, ScrapingStep
from .plan import ScrapingPlan
from .toolkit_models import DriverConfig

logger = logging.getLogger(__name__)


async def execute_plan_steps(
    driver: Any,
    plan: Optional[ScrapingPlan] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    selectors: Optional[List[Dict[str, Any]]] = None,
    config: Optional[DriverConfig] = None,
    base_url: Optional[str] = None,
) -> ScrapingResult:
    """Execute a scraping plan's steps against a browser driver.

    Accepts either a full ScrapingPlan or raw steps list for ad-hoc usage.
    Steps are executed sequentially; selectors are applied after all steps.

    Args:
        driver: Browser driver instance.
        plan: Full ScrapingPlan (takes priority if provided).
        steps: Raw steps list for ad-hoc usage (used if plan is None).
        selectors: Content extraction selectors (used if plan is None).
        config: Driver configuration for retry/delay settings.
        base_url: Base URL for the scraping operation.

    Returns:
        ScrapingResult with extracted data and metadata.
    """
    ...
```

### Key Constraints
- Must handle both `ScrapingPlan` objects and raw `steps` dicts (per approved Open Question)
- Reuse existing `ScrapingStep.from_dict()` for action deserialization
- Respect `config.retry_attempts` and `config.delay_between_actions`
- Catch per-step exceptions and record them without aborting the entire plan
- Preserve existing behavior from `WebScrapingTool._execute` — don't change semantics
- Return `ScrapingResult` with `success=False` on critical failures, not exceptions

### References in Codebase
- `parrot/tools/scraping/tool.py:381-427` — existing `_execute` method to extract from
- `parrot/tools/scraping/models.py` — `ScrapingStep`, `BrowserAction`, `ScrapingResult`
- `parrot/tools/scraping/orchestrator.py` — existing orchestration patterns

---

## Acceptance Criteria

- [ ] `execute_plan_steps()` accepts a `ScrapingPlan` and executes all steps in order
- [ ] `execute_plan_steps()` accepts raw `steps` list for ad-hoc usage
- [ ] Steps are executed sequentially with configurable delay between them
- [ ] Selector-based data extraction runs after all steps complete
- [ ] Individual step failures are captured in result, don't abort remaining steps
- [ ] Critical failures return `ScrapingResult(success=False, error_message=...)`
- [ ] All tests pass: `pytest tests/tools/scraping/test_executor.py -v`
- [ ] No linting errors: `ruff check parrot/tools/scraping/executor.py`
- [ ] Import works: `from parrot.tools.scraping.executor import execute_plan_steps`

---

## Test Specification

```python
# tests/tools/scraping/test_executor.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.tools.scraping.executor import execute_plan_steps
from parrot.tools.scraping.plan import ScrapingPlan
from parrot.tools.scraping.toolkit_models import DriverConfig


@pytest.fixture
def mock_driver():
    driver = AsyncMock()
    driver.page_source = "<html><body><h1>Test</h1></body></html>"
    return driver


@pytest.fixture
def sample_plan():
    return ScrapingPlan(
        url="https://example.com",
        objective="Test",
        steps=[
            {"action": "navigate", "url": "https://example.com"},
            {"action": "wait", "condition": "h1", "condition_type": "selector"},
        ],
    )


class TestExecutePlanSteps:
    @pytest.mark.asyncio
    async def test_executes_steps_from_plan(self, mock_driver, sample_plan):
        result = await execute_plan_steps(mock_driver, plan=sample_plan)
        assert result is not None

    @pytest.mark.asyncio
    async def test_executes_raw_steps(self, mock_driver):
        result = await execute_plan_steps(
            mock_driver,
            steps=[{"action": "navigate", "url": "https://example.com"}],
            base_url="https://example.com",
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_handles_step_failure(self, mock_driver, sample_plan):
        """Failed step captured in result, doesn't crash."""
        # Configure mock to raise on navigate
        mock_driver.get = AsyncMock(side_effect=Exception("Network error"))
        result = await execute_plan_steps(mock_driver, plan=sample_plan)
        assert result.success is False or result.error_message is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scraping-toolkit.spec.md` for full context
2. **Check dependencies** — verify TASK-050 is in `sdd/tasks/completed/`
3. **Read** `parrot/tools/scraping/tool.py` carefully — understand `_execute()` logic
4. **Read** `parrot/tools/scraping/models.py` — understand action dispatch
5. **Read** `parrot/tools/scraping/orchestrator.py` — understand orchestration pattern
6. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
7. **Implement** following the scope and notes above
8. **Verify** all acceptance criteria are met
9. **Move this file** to `sdd/tasks/completed/TASK-434-step-executor.md`
10. **Update index** → `"done"`
11. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Implemented `execute_plan_steps()` in `parrot/tools/scraping/executor.py` as a standalone async function that accepts either a `ScrapingPlan` or raw `steps`/`selectors` dicts. The executor converts step dicts via `ScrapingStep.from_dict()`, dispatches each action to dedicated handler functions (navigate, wait, click, fill, scroll, evaluate, refresh, back, press_key, select, screenshot, get_text, get_html), applies configurable delay between steps, and extracts content via `_apply_selectors()` using BeautifulSoup. Non-critical step failures are captured in metadata without aborting; critical actions (navigate, authenticate) abort the pipeline. Advanced actions (loop, conditional, cookies, etc.) that require full WebScrapingTool context skip gracefully with a warning. 30 unit tests pass covering plan execution, raw steps, selectors, failure handling, abort logic, delays, and helper functions.

**Deviations from spec**: Advanced actions (loop, conditional, authenticate, cookies, upload, download, await_human, await_keypress, await_browser_event) are logged as warnings and skipped in standalone mode since they require the full WebScrapingTool class context. They return `True` to not block the pipeline. The full WebScrapingToolkit (TASK-053) can override this behavior by calling the tool's own action handlers.
