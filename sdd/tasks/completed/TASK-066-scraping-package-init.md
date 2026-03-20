# TASK-066: Package Init & Route Registration for Scraping Handlers

**Feature**: ScrapingToolkit HTTP Handler (FEAT-016)
**Spec**: `sdd/specs/scrapingtoolkit-handler.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-064, TASK-065
**Assigned-to**: claude-session

---

## Context

With both handlers implemented, we need a clean package init that exports public symbols
and provides a `setup_scraping_routes(app)` convenience function. This function is the
single entry point for registering all scraping-related routes on an aiohttp application,
used in the app factory (e.g., `app.py`).

This implements **Module 4** from the spec.

---

## Scope

- Update `parrot/handlers/scraping/__init__.py`:
  - Export `ScrapingHandler`, `ScrapingInfoHandler`, and all request/response models
  - Implement `setup_scraping_routes(app)` that:
    1. Registers `ScrapingHandler` class-based view routes for `/api/v1/scraping/plans` and `/api/v1/scraping/plans/{name}`
    2. Registers POST routes for `/api/v1/scraping/scrape` and `/api/v1/scraping/crawl`
    3. Creates a `ScrapingInfoHandler` instance and calls its `setup(app)` to register info routes
    4. Registers aiohttp on_startup / on_cleanup signals for toolkit + job manager lifecycle
- Write a simple test verifying route registration

**NOT in scope**: Handler implementation (already done in TASK-064, TASK-065).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/scraping/__init__.py` | MODIFY | Add exports + setup_scraping_routes() |
| `tests/handlers/test_scraping_routes.py` | CREATE | Test route registration |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/handlers/scraping/__init__.py
from .handler import ScrapingHandler
from .info import ScrapingInfoHandler
from .models import (
    PlanCreateRequest, ScrapeRequest, CrawlRequest,
    PlanSaveRequest, ActionInfo, DriverTypeInfo, StrategyInfo,
)

__all__ = (
    "ScrapingHandler",
    "ScrapingInfoHandler",
    "PlanCreateRequest",
    "ScrapeRequest",
    "CrawlRequest",
    "PlanSaveRequest",
    "ActionInfo",
    "DriverTypeInfo",
    "StrategyInfo",
    "setup_scraping_routes",
)


def setup_scraping_routes(app) -> None:
    """Register all scraping handler routes on the aiohttp application."""
    # Class-based view routes
    app.router.add_view('/api/v1/scraping/plans', ScrapingHandler)
    app.router.add_view('/api/v1/scraping/plans/{name}', ScrapingHandler)
    # Execution routes (POST-only)
    # ...
    # Info handler routes
    info_handler = ScrapingInfoHandler()
    info_handler.setup(app)
```

### Key Constraints
- Follow existing handler package patterns in `parrot/handlers/`
- `setup_scraping_routes` is the single entry point for app integration
- Startup/cleanup signals should be registered for toolkit and JobManager lifecycle

### References in Codebase
- `parrot/handlers/agents/abstract.py` — AgentHandler.setup() pattern for route registration
- `parrot/handlers/chat.py` — How ChatHandler routes are registered

---

## Acceptance Criteria

- [ ] `setup_scraping_routes(app)` registers all routes (plans CRUD, scrape, crawl, info)
- [ ] All public symbols exported from `parrot.handlers.scraping`
- [ ] Route registration test passes
- [ ] All tests pass: `pytest tests/handlers/test_scraping_routes.py -v`
- [ ] Import works: `from parrot.handlers.scraping import setup_scraping_routes`

---

## Test Specification

```python
# tests/handlers/test_scraping_routes.py
import pytest
from aiohttp import web
from parrot.handlers.scraping import setup_scraping_routes


class TestRouteRegistration:
    def test_setup_registers_plan_routes(self):
        """setup_scraping_routes registers plan CRUD routes."""
        app = web.Application()
        setup_scraping_routes(app)
        routes = [r.resource.canonical for r in app.router.routes() if hasattr(r, 'resource')]
        assert '/api/v1/scraping/plans' in routes
        assert '/api/v1/scraping/plans/{name}' in routes

    def test_setup_registers_info_routes(self):
        """setup_scraping_routes registers info GET routes."""
        app = web.Application()
        setup_scraping_routes(app)
        routes = [r.resource.canonical for r in app.router.routes() if hasattr(r, 'resource')]
        assert '/api/v1/scraping/info/actions' in routes
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scrapingtoolkit-handler.spec.md` for full context
2. **Check dependencies** — TASK-064 and TASK-065 must be completed first
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-066-scraping-package-init.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**: Updated `__init__.py` to export both handler classes + all models + `setup_scraping_routes()`. The setup function delegates to `ScrapingHandler.setup(app)` for view routes + lifecycle signals, and creates a `ScrapingInfoHandler` instance calling its `setup(app)` for info routes. 10 tests passing covering route registration, lifecycle signals, imports, and `__all__` exports.

**Deviations from spec**: none
