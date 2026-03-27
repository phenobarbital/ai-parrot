# TASK-436: WebScrapingToolkit Core

**Feature**: FEAT-014 — WebScrapingToolkit
**Spec**: `sdd/specs/scraping-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-049, TASK-050, TASK-051, TASK-052, TASK-039, TASK-040
**Assigned-to**: claude-session

---

## Context

> This task implements Module 4 from the spec: the `WebScrapingToolkit` class itself.
> This is the main entry point for all scraping/crawling operations, inheriting from
> `AbstractToolkit` so that each public async method is automatically exposed as an
> individual tool for agents and chatbots.

---

## Scope

- Implement `WebScrapingToolkit` class inheriting `AbstractToolkit`
- Constructor: accept all driver config, session mode, plans_dir, llm_client params
- Lifecycle: `start()` and `stop()` methods for session-based driver management
- Internal: `_driver_context()` async context manager (delegates to Module 2)
- Internal: `_ensure_registry()` lazy registry loader
- Internal: `_resolve_plan()` plan resolution chain (explicit → cached → auto → error)
- Tool methods:
  - `plan_create()` — generate plan via LLM (or return cached), uses PlanGenerator (TASK-052)
  - `plan_save()` — save to disk + register, uses plan_io (TASK-040)
  - `plan_load()` — load by URL or name, uses PlanRegistry (TASK-039) + plan_io
  - `plan_list()` — list plans with domain/tag filtering
  - `plan_delete()` — remove from registry + optionally from disk
  - `scrape()` — resolve plan, acquire driver, execute steps, return ScrapingResult
  - `crawl()` — resolve plan, delegate to CrawlEngine (FEAT-013), or raise NotImplementedError
- `scrape()` must also accept raw `steps` list (per approved Open Question)
- Write comprehensive unit tests with mocked dependencies

**NOT in scope**: Step executor internals (TASK-051), Plan generator internals (TASK-052),
CrawlEngine internals (FEAT-013)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/toolkit.py` | CREATE | WebScrapingToolkit class |
| `tests/tools/scraping/test_toolkit.py` | CREATE | Unit + integration tests |

---

## Implementation Notes

### Pattern to Follow
```python
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from parrot.tools.toolkit import AbstractToolkit

from .driver_context import driver_context
from .executor import execute_plan_steps
from .plan import ScrapingPlan
from .plan_generator import PlanGenerator
from .registry import PlanRegistry
from .toolkit_models import DriverConfig, PlanSaveResult, PlanSummary


class WebScrapingToolkit(AbstractToolkit):
    """Toolkit for intelligent web scraping and crawling with plan caching.

    Each public async method becomes a tool automatically via AbstractToolkit.
    """

    def __init__(self, ..., **kwargs):
        super().__init__(**kwargs)
        self._config = DriverConfig(...)
        self._session_based = session_based
        self._session_driver = None
        self._registry: Optional[PlanRegistry] = None
        self._llm_client = llm_client
        self._plans_dir = Path(plans_dir) if plans_dir else Path("scraping_plans")
        self.logger = logging.getLogger(__name__)

    async def start(self) -> None:
        """Initialize session driver if session_based=True."""
        ...

    async def stop(self) -> None:
        """Close session driver if active."""
        ...

    async def _ensure_registry(self) -> PlanRegistry:
        """Lazy-load the plan registry."""
        ...

    async def _resolve_plan(self, url, plan, objective) -> ScrapingPlan:
        """Plan resolution chain: explicit → cached → auto-generate → error."""
        ...

    # 7 public tool methods as specified in the spec...
```

### Key Constraints
- Must inherit `AbstractToolkit` — this is what makes methods into tools
- `get_tools()` must return exactly 7 tools (one per public async method)
- Plan resolution chain must follow the exact priority from spec §6
- `crawl()` should attempt to import `CrawlEngine`; if unavailable, raise `NotImplementedError`
- `plan_save()` depends on `save_plan_to_disk` from TASK-040 (plan_io)
- `plan_load()` depends on `load_plan_from_disk` from TASK-040 (plan_io)
- If TASK-040 is not yet complete, use simple JSON file I/O as a fallback
- `scrape()` accepts both `ScrapingPlan` and raw `steps` list
- Session mode is for sequential use only — document this clearly

### References in Codebase
- `parrot/tools/toolkit.py:183-220` — how AbstractToolkit discovers methods as tools
- `parrot/tools/scraping/tool.py` — existing WebScrapingTool for reference
- `parrot/tools/scraping/registry.py` — PlanRegistry API
- `parrot/tools/scraping/plan.py` — ScrapingPlan model

---

## Acceptance Criteria

- [ ] `WebScrapingToolkit` inherits `AbstractToolkit`
- [ ] `get_tools()` returns exactly 7 tools
- [ ] `plan_create()` returns cached plan on registry hit, calls LLM on miss
- [ ] `scrape()` resolves plan via priority chain: explicit → cached → auto-generate → error
- [ ] `scrape()` accepts raw `steps` list without a full ScrapingPlan
- [ ] `crawl()` delegates to CrawlEngine or raises NotImplementedError
- [ ] `plan_save()` persists to disk and registers in PlanRegistry
- [ ] `plan_load()` retrieves plan by URL (lookup) or by name
- [ ] `plan_list()` supports domain and tag filtering
- [ ] `plan_delete()` removes from registry and optionally from disk
- [ ] Session mode reuses driver across calls
- [ ] Fresh mode creates/destroys driver per operation
- [ ] All tests pass: `pytest tests/tools/scraping/test_toolkit.py -v`
- [ ] No linting errors: `ruff check parrot/tools/scraping/toolkit.py`
- [ ] Import works: `from parrot.tools.scraping.toolkit import WebScrapingToolkit`

---

## Test Specification

```python
# tests/tools/scraping/test_toolkit.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.tools.scraping.toolkit import WebScrapingToolkit
from parrot.tools.scraping.plan import ScrapingPlan


@pytest.fixture
def mock_llm_client():
    import json
    client = AsyncMock()
    client.complete = AsyncMock(return_value=json.dumps({
        "url": "https://example.com",
        "objective": "Test",
        "steps": [{"action": "navigate", "url": "https://example.com"}],
    }))
    return client


@pytest.fixture
def toolkit(tmp_path, mock_llm_client):
    return WebScrapingToolkit(
        headless=True,
        plans_dir=tmp_path / "plans",
        llm_client=mock_llm_client,
    )


class TestWebScrapingToolkit:
    def test_inherits_abstract_toolkit(self, toolkit):
        from parrot.tools.toolkit import AbstractToolkit
        assert isinstance(toolkit, AbstractToolkit)

    def test_get_tools_returns_seven(self, toolkit):
        tools = toolkit.get_tools()
        assert len(tools) == 7

    @pytest.mark.asyncio
    async def test_plan_list_empty(self, toolkit):
        plans = await toolkit.plan_list()
        assert plans == []

    @pytest.mark.asyncio
    async def test_plan_delete_nonexistent(self, toolkit):
        result = await toolkit.plan_delete("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_scrape_no_plan_raises(self, toolkit):
        with pytest.raises(ValueError):
            await toolkit.scrape("https://example.com")

    @pytest.mark.asyncio
    async def test_crawl_not_implemented(self, toolkit):
        """crawl() raises NotImplementedError if CrawlEngine unavailable."""
        with pytest.raises(NotImplementedError):
            await toolkit.crawl("https://example.com")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scraping-toolkit.spec.md` — especially §2, §4, §5
2. **Check dependencies** — verify TASK-049, TASK-050, TASK-051, TASK-052, TASK-039 are done
3. **Read** `parrot/tools/toolkit.py` — understand `AbstractToolkit` and how `get_tools()` works
4. **Read** all dependency task implementations (toolkit_models, driver_context, executor, plan_generator, registry)
5. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
6. **Implement** following the scope and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-436-toolkit-core.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Implemented `WebScrapingToolkit` in `parrot/tools/scraping/toolkit.py` inheriting `AbstractToolkit`. The class exposes 7 public async methods as tools: `plan_create`, `plan_save`, `plan_load`, `plan_list`, `plan_delete`, `scrape`, `crawl`. Constructor accepts all DriverConfig params, session_based flag, plans_dir, and llm_client. `start()`/`stop()` manage session driver lifecycle. Internal `_ensure_registry()` lazy-loads PlanRegistry, `_resolve_plan()` implements the priority chain (explicit → cached → auto-generate → error). `scrape()` accepts both ScrapingPlan and raw steps lists. `crawl()` attempts to import CrawlEngine and raises NotImplementedError if unavailable. 40 unit tests pass covering all acceptance criteria.

**Deviations from spec**: none
