# TASK-063: Define Request/Response Pydantic Models for Scraping API

**Feature**: ScrapingToolkit HTTP Handler (FEAT-016)
**Spec**: `sdd/specs/scrapingtoolkit-handler.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

FEAT-016 exposes the `WebScrapingToolkit` over HTTP. Before building any handler, we need
well-defined Pydantic v2 models for request validation and response serialization. These
models are consumed by both `ScrapingHandler` (TASK-065) and `ScrapingInfoHandler` (TASK-064),
and form the data contract with the `navigator-frontend-next` Svelte UI.

This implements **Module 1** from the spec.

---

## Scope

- Create `parrot/handlers/scraping/models.py` with:
  - `PlanCreateRequest` — POST /plans body (url, objective, hints, force_regenerate, save)
  - `ScrapeRequest` — POST /scrape body (url, plan_name, plan, objective, steps, selectors, save_plan, browser_config_override)
  - `CrawlRequest` — POST /crawl body (start_url, depth, max_pages, follow_selector, follow_pattern, plan_name, plan, objective, save_plan, strategy, concurrency)
  - `PlanSaveRequest` — PUT /plans/{name} body (plan dict, overwrite flag)
  - `ActionInfo` — response model for browser action catalog
  - `DriverTypeInfo` — response model for driver types
  - `StrategyInfo` — response model for crawl strategies
- Write unit tests validating each model with valid and invalid payloads.

**NOT in scope**: Handler logic, route registration, info introspection logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/scraping/__init__.py` | CREATE | Package init (empty or minimal exports) |
| `parrot/handlers/scraping/models.py` | CREATE | All Pydantic request/response models |
| `tests/handlers/test_scraping_models.py` | CREATE | Unit tests for model validation |

---

## Implementation Notes

### Pattern to Follow
```python
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class PlanCreateRequest(BaseModel):
    """Request body for POST /plans (create a new plan via LLM)."""
    url: str
    objective: str
    hints: Optional[Dict[str, Any]] = None
    force_regenerate: bool = False
    save: bool = False
```

### Key Constraints
- Use Pydantic v2 (`BaseModel` from `pydantic`)
- All fields must have type hints
- Use `Literal` for constrained string fields (e.g., `strategy: Literal["bfs", "dfs"]`)
- Default values must match what the spec defines
- Models should be JSON-serializable (for response models, ensure `.model_dump()` works cleanly)

### References in Codebase
- `parrot/tools/scraping/toolkit_models.py` — existing DriverConfig, PlanSummary, PlanSaveResult models
- `parrot/tools/scraping/plan.py` — ScrapingPlan model
- `parrot/tools/scraping/crawl_graph.py` — CrawlResult model

---

## Acceptance Criteria

- [ ] All 7 Pydantic models created with correct field types and defaults
- [ ] `PlanCreateRequest` validates url and objective are required
- [ ] `ScrapeRequest` accepts all field combinations from spec
- [ ] `CrawlRequest` defaults: depth=1, strategy="bfs", concurrency=1
- [ ] All tests pass: `pytest tests/handlers/test_scraping_models.py -v`
- [ ] Imports work: `from parrot.handlers.scraping.models import PlanCreateRequest, ScrapeRequest, CrawlRequest`

---

## Test Specification

```python
# tests/handlers/test_scraping_models.py
import pytest
from parrot.handlers.scraping.models import (
    PlanCreateRequest, ScrapeRequest, CrawlRequest,
    PlanSaveRequest, ActionInfo, DriverTypeInfo, StrategyInfo,
)


class TestPlanCreateRequest:
    def test_valid_minimal(self):
        req = PlanCreateRequest(url="https://example.com", objective="Extract data")
        assert req.url == "https://example.com"
        assert req.force_regenerate is False
        assert req.save is False

    def test_missing_url_raises(self):
        with pytest.raises(Exception):
            PlanCreateRequest(objective="Extract data")

    def test_all_fields(self):
        req = PlanCreateRequest(
            url="https://example.com",
            objective="Extract data",
            hints={"pagination": True},
            force_regenerate=True,
            save=True,
        )
        assert req.hints == {"pagination": True}


class TestScrapeRequest:
    def test_minimal(self):
        req = ScrapeRequest(url="https://example.com")
        assert req.plan_name is None
        assert req.save_plan is False

    def test_with_inline_steps(self):
        req = ScrapeRequest(
            url="https://example.com",
            steps=[{"action": "navigate", "url": "https://example.com"}],
            selectors=[{"name": "title", "selector": "h1"}],
        )
        assert len(req.steps) == 1


class TestCrawlRequest:
    def test_defaults(self):
        req = CrawlRequest(start_url="https://example.com")
        assert req.depth == 1
        assert req.strategy == "bfs"
        assert req.concurrency == 1

    def test_invalid_strategy(self):
        with pytest.raises(Exception):
            CrawlRequest(start_url="https://example.com", strategy="invalid")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scrapingtoolkit-handler.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-063-scraping-handler-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**: All 7 Pydantic v2 models created in `parrot/handlers/scraping/models.py`. 30 unit tests written and passing. Package init created with exports. Added `ge` constraints for depth (>=0), max_pages (>=1), and concurrency (>=1) for extra validation safety.

**Deviations from spec**: none
