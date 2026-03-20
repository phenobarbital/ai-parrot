# TASK-067: Integration Tests for Scraping Handler Endpoints

**Feature**: ScrapingToolkit HTTP Handler (FEAT-016)
**Spec**: `sdd/specs/scrapingtoolkit-handler.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-065, TASK-066
**Assigned-to**: claude-session

---

## Context

With all handler modules implemented and route registration in place, this task adds
integration tests that verify the full HTTP request/response flow. Tests use `aiohttp`
test client to make actual HTTP requests against the registered routes with a mocked
`WebScrapingToolkit`.

This implements **Module 5** (integration test portion) from the spec.

---

## Scope

- Create integration tests that:
  - Stand up an aiohttp app with `setup_scraping_routes(app)`
  - Mock `WebScrapingToolkit` to avoid real browser/LLM calls
  - Test full plan lifecycle: create → list → load → update → delete
  - Test scrape execution endpoint with inline plan
  - Test crawl execution endpoint
  - Test all info endpoints return valid JSON
  - Test error cases: invalid JSON, missing plans, validation errors
  - Test job status flow: submit → check pending → check completed

**NOT in scope**: Real browser tests, LLM integration tests, frontend tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/handlers/test_scraping_integration.py` | CREATE | Integration tests with aiohttp test client |

---

## Implementation Notes

### Pattern to Follow
```python
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase
from unittest.mock import AsyncMock, patch, MagicMock

from parrot.handlers.scraping import setup_scraping_routes


@pytest.fixture
def app():
    """Create aiohttp app with scraping routes and mocked toolkit."""
    application = web.Application()
    setup_scraping_routes(application)
    # Mock the toolkit that gets created on startup
    return application


@pytest.fixture
def client(aiohttp_client, app):
    return aiohttp_client(app)


class TestPlanLifecycle:
    async def test_full_plan_lifecycle(self, client):
        """Create → List → Load → Update → Delete flow."""
        # 1. Create plan
        resp = await client.post('/api/v1/scraping/plans', json={
            "url": "https://example.com",
            "objective": "Extract products",
        })
        assert resp.status == 200
        data = await resp.json()
        plan_name = data["name"]

        # 2. List plans
        resp = await client.get('/api/v1/scraping/plans')
        assert resp.status == 200
        plans = (await resp.json())["plans"]
        assert any(p["name"] == plan_name for p in plans)

        # 3. Load plan
        resp = await client.get(f'/api/v1/scraping/plans/{plan_name}')
        assert resp.status == 200

        # 4. Delete plan
        resp = await client.delete(f'/api/v1/scraping/plans/{plan_name}')
        assert resp.status == 200
```

### Key Constraints
- Use `pytest-aiohttp` for async test client
- Mock `WebScrapingToolkit` methods — do not start real browsers
- Mock `JobManager` or use real in-memory JobManager
- Each test should be independent (no shared state between tests)
- Test both happy paths and error paths

### References in Codebase
- `tests/` — Existing test patterns
- `parrot/handlers/jobs/job.py` — JobManager can be used in-memory without external deps

---

## Acceptance Criteria

- [ ] Full plan lifecycle test (create → list → load → delete) passes
- [ ] Scrape endpoint returns job_id
- [ ] Crawl endpoint returns job_id
- [ ] All 4 info endpoints return valid JSON with expected keys
- [ ] Error cases tested: 400 (invalid body), 404 (missing plan)
- [ ] All tests pass: `pytest tests/handlers/test_scraping_integration.py -v`

---

## Test Specification

```python
# tests/handlers/test_scraping_integration.py

class TestPlanLifecycle:
    async def test_full_plan_lifecycle(self, client): ...

class TestScrapeExecution:
    async def test_scrape_with_inline_plan(self, client): ...
    async def test_scrape_returns_job_id(self, client): ...

class TestCrawlExecution:
    async def test_crawl_returns_job_id(self, client): ...

class TestInfoEndpoints:
    async def test_actions_endpoint(self, client): ...
    async def test_drivers_endpoint(self, client): ...
    async def test_config_endpoint(self, client): ...
    async def test_strategies_endpoint(self, client): ...

class TestErrorHandling:
    async def test_invalid_json_returns_400(self, client): ...
    async def test_missing_plan_returns_404(self, client): ...
    async def test_missing_required_field_returns_400(self, client): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scrapingtoolkit-handler.spec.md` for full context
2. **Check dependencies** — TASK-065 and TASK-066 must be completed first
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-067-scraping-handler-integration-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**: 23 integration tests covering: info endpoints via real HTTP TestClient (4 tests), full plan CRUD lifecycle (5 tests), scrape execution with job submission (3 tests), crawl execution (2 tests), job status submit-then-check flow (2 tests), and error handling across all endpoints (7 tests). Total test suite across all FEAT-016 files: 121 tests passing.

**Deviations from spec**: Info endpoints tested via aiohttp TestClient (real HTTP), but ScrapingHandler endpoints use direct handler invocation (BaseView from navigator requires special initialization not compatible with aiohttp TestClient). This still validates the full cross-module integration flow.
