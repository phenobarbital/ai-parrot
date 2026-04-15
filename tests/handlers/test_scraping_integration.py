"""Integration tests for scraping handler endpoints.

Tests the full HTTP request/response flow across all scraping handler modules.
Info endpoints use aiohttp TestClient (method-based routes work directly).
ScrapingHandler endpoints use direct handler invocation with mocked requests
(BaseView requires special initialization not compatible with TestClient).
"""
import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from parrot.handlers.scraping.handler import (
    ScrapingHandler,
    _TOOLKIT_KEY,
    _JOB_MANAGER_KEY,
)
from parrot.handlers.jobs.models import Job, JobStatus


# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------

class MockPlanSummary:
    """Mock plan summary returned by toolkit.plan_list."""
    def __init__(self, name: str, url: str = "https://example.com"):
        self.name = name
        self.url = url

    def model_dump(self, mode: str = "python") -> Dict[str, Any]:
        return {"name": self.name, "url": self.url}


class MockPlan:
    """Mock ScrapingPlan."""
    def __init__(self, name: str = "test-plan", url: str = "https://example.com"):
        self.name = name
        self.url = url

    def model_dump(self, mode: str = "python") -> Dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "objective": "test objective",
            "steps": [],
        }


class MockSaveResult:
    """Mock PlanSaveResult."""
    def __init__(self, name: str = "test-plan"):
        self.name = name

    def model_dump(self, mode: str = "python") -> Dict[str, Any]:
        return {
            "success": True,
            "path": f"plans/{self.name}.json",
            "name": self.name,
            "version": "1.0",
            "registered": True,
            "message": "Saved",
        }


def _make_mock_toolkit():
    """Create a mock WebScrapingToolkit with default return values."""
    toolkit = AsyncMock()
    toolkit.plan_list = AsyncMock(return_value=[
        MockPlanSummary("plan-a"),
        MockPlanSummary("plan-b"),
    ])
    toolkit.plan_load = AsyncMock(return_value=MockPlan("test-plan"))
    toolkit.plan_create = AsyncMock(return_value=MockPlan("new-plan"))
    toolkit.plan_save = AsyncMock(return_value=MockSaveResult("test-plan"))
    toolkit.plan_delete = AsyncMock(return_value=True)
    toolkit.scrape = AsyncMock(return_value={"url": "https://example.com", "data": []})
    toolkit.crawl = AsyncMock(return_value={"start_url": "https://example.com", "pages": []})
    toolkit.start = AsyncMock()
    toolkit.stop = AsyncMock()
    return toolkit


def _make_mock_job_manager():
    """Create a mock JobManager."""
    jm = MagicMock()
    jm.create_job = MagicMock(return_value=Job(
        job_id="test-job-id",
        obj_id="scrape",
        query={},
    ))
    jm.execute_job = AsyncMock()
    jm.get_job = MagicMock(return_value=None)
    jm.start = AsyncMock()
    jm.stop = AsyncMock()
    return jm


def _make_handler(
    method: str,
    path: str,
    toolkit=None,
    job_manager=None,
    match_info=None,
    json_body=None,
    query=None,
) -> ScrapingHandler:
    """Create a ScrapingHandler with mocked request and app context."""
    if toolkit is None:
        toolkit = _make_mock_toolkit()
    if job_manager is None:
        job_manager = _make_mock_job_manager()

    app = {
        _TOOLKIT_KEY: toolkit,
        _JOB_MANAGER_KEY: job_manager,
    }

    full_path = path
    if query:
        qs = "&".join(f"{k}={v}" for k, v in query.items())
        full_path = f"{path}?{qs}"

    request = make_mocked_request(
        method, full_path,
        match_info=match_info or {},
        app=app,
    )

    if json_body is not None:
        request.json = AsyncMock(return_value=json_body)

    handler = ScrapingHandler.__new__(ScrapingHandler)
    handler._request = request
    handler.request = request
    handler.logger = MagicMock()

    return handler


def _parse(resp: web.Response) -> dict:
    """Parse JSON body from response."""
    return json.loads(resp.body)


# ---------------------------------------------------------------------------
# Fixtures for info endpoint TestClient
# ---------------------------------------------------------------------------

@pytest.fixture
async def info_client():
    """Create an aiohttp test client for info endpoints only."""
    from parrot.handlers.scraping.info import ScrapingInfoHandler

    app = web.Application()
    info_handler = ScrapingInfoHandler()
    info_handler.setup(app)

    async with TestClient(TestServer(app)) as tc:
        yield tc


# ---------------------------------------------------------------------------
# Integration: Info endpoints (via real HTTP)
# ---------------------------------------------------------------------------

class TestInfoEndpoints:
    """Integration tests for GET /api/v1/scraping/info/* via HTTP test client."""

    @pytest.mark.asyncio
    async def test_actions_endpoint(self, info_client):
        """GET /info/actions returns action catalog with expected structure."""
        resp = await info_client.get("/api/v1/scraping/info/actions")
        assert resp.status == 200
        data = await resp.json()
        assert "actions" in data
        assert len(data["actions"]) > 0
        action = data["actions"][0]
        assert "name" in action
        assert "description" in action
        assert "fields" in action
        assert "required" in action

    @pytest.mark.asyncio
    async def test_drivers_endpoint(self, info_client):
        """GET /info/drivers returns selenium and playwright."""
        resp = await info_client.get("/api/v1/scraping/info/drivers")
        assert resp.status == 200
        data = await resp.json()
        assert "drivers" in data
        names = [d["name"] for d in data["drivers"]]
        assert "selenium" in names
        assert "playwright" in names

    @pytest.mark.asyncio
    async def test_config_endpoint(self, info_client):
        """GET /info/config returns DriverConfig JSON schema."""
        resp = await info_client.get("/api/v1/scraping/info/config")
        assert resp.status == 200
        data = await resp.json()
        assert "schema" in data
        assert "properties" in data["schema"]
        assert "driver_type" in data["schema"]["properties"]

    @pytest.mark.asyncio
    async def test_strategies_endpoint(self, info_client):
        """GET /info/strategies returns bfs and dfs strategies."""
        resp = await info_client.get("/api/v1/scraping/info/strategies")
        assert resp.status == 200
        data = await resp.json()
        assert "strategies" in data
        names = [s["name"] for s in data["strategies"]]
        assert "bfs" in names
        assert "dfs" in names


# ---------------------------------------------------------------------------
# Integration: Full plan CRUD lifecycle
# ---------------------------------------------------------------------------

class TestPlanLifecycle:
    """Integration tests for plan CRUD via ScrapingHandler."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """Create → list → load → delete lifecycle with shared toolkit."""
        toolkit = _make_mock_toolkit()
        jm = _make_mock_job_manager()

        # 1. Create plan
        h = _make_handler(
            "POST", "/api/v1/scraping/plans",
            toolkit=toolkit, job_manager=jm,
            json_body={"url": "https://example.com", "objective": "Extract data"},
        )
        resp = await h.post()
        assert resp.status == 201
        data = _parse(resp)
        assert data["name"] == "new-plan"
        toolkit.plan_create.assert_called_once()

        # 2. List plans
        h = _make_handler(
            "GET", "/api/v1/scraping/plans",
            toolkit=toolkit, job_manager=jm,
        )
        resp = await h.get()
        assert resp.status == 200
        data = _parse(resp)
        assert len(data["plans"]) == 2
        toolkit.plan_list.assert_called_once()

        # 3. Load specific plan
        h = _make_handler(
            "GET", "/api/v1/scraping/plans/test-plan",
            toolkit=toolkit, job_manager=jm,
            match_info={"name": "test-plan"},
        )
        resp = await h.get()
        assert resp.status == 200
        data = _parse(resp)
        assert data["name"] == "test-plan"

        # 4. Delete plan
        h = _make_handler(
            "DELETE", "/api/v1/scraping/plans/test-plan",
            toolkit=toolkit, job_manager=jm,
            match_info={"name": "test-plan"},
        )
        resp = await h.delete()
        assert resp.status == 200
        toolkit.plan_delete.assert_called_once_with("test-plan")

    @pytest.mark.asyncio
    async def test_create_plan_with_auto_save(self):
        """Create plan with save=True triggers both create and save."""
        toolkit = _make_mock_toolkit()
        h = _make_handler(
            "POST", "/api/v1/scraping/plans",
            toolkit=toolkit,
            json_body={
                "url": "https://example.com",
                "objective": "Extract products",
                "save": True,
            },
        )
        resp = await h.post()
        assert resp.status == 201
        data = _parse(resp)
        assert "save_result" in data
        assert data["save_result"]["success"] is True
        toolkit.plan_create.assert_called_once()
        toolkit.plan_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_plan_not_found(self):
        """Load missing plan returns 404."""
        toolkit = _make_mock_toolkit()
        toolkit.plan_load = AsyncMock(return_value=None)
        h = _make_handler(
            "GET", "/api/v1/scraping/plans/missing",
            toolkit=toolkit,
            match_info={"name": "missing"},
        )
        resp = await h.get()
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_list_plans_with_filters(self):
        """List plans passes query filters to toolkit."""
        toolkit = _make_mock_toolkit()
        h = _make_handler(
            "GET", "/api/v1/scraping/plans",
            toolkit=toolkit,
            query={"domain_filter": "example.com", "tag_filter": "ecommerce"},
        )
        resp = await h.get()
        assert resp.status == 200
        toolkit.plan_list.assert_called_once_with(
            domain_filter="example.com",
            tag_filter="ecommerce",
        )

    @pytest.mark.asyncio
    async def test_delete_missing_plan_returns_404(self):
        """Delete nonexistent plan returns 404."""
        toolkit = _make_mock_toolkit()
        toolkit.plan_delete = AsyncMock(return_value=False)
        h = _make_handler(
            "DELETE", "/api/v1/scraping/plans/missing",
            toolkit=toolkit,
            match_info={"name": "missing"},
        )
        resp = await h.delete()
        assert resp.status == 404


# ---------------------------------------------------------------------------
# Integration: Scrape execution flow
# ---------------------------------------------------------------------------

class TestScrapeExecution:
    """Integration tests for POST /scrape endpoint."""

    @pytest.mark.asyncio
    async def test_scrape_submits_job(self):
        """POST /scrape creates a job and returns 202 with job_id."""
        jm = _make_mock_job_manager()
        h = _make_handler(
            "POST", "/api/v1/scraping/scrape",
            job_manager=jm,
            json_body={"url": "https://example.com"},
        )
        resp = await h.post()
        assert resp.status == 202
        data = _parse(resp)
        assert "job_id" in data
        assert data["status"] == "queued"
        jm.create_job.assert_called_once()
        jm.execute_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_scrape_with_plan_name_resolution(self):
        """POST /scrape with plan_name loads and uses the plan."""
        toolkit = _make_mock_toolkit()
        jm = _make_mock_job_manager()
        h = _make_handler(
            "POST", "/api/v1/scraping/scrape",
            toolkit=toolkit, job_manager=jm,
            json_body={
                "url": "https://example.com",
                "plan_name": "my-plan",
            },
        )
        resp = await h.post()
        assert resp.status == 202
        toolkit.plan_load.assert_called_once_with("my-plan")

    @pytest.mark.asyncio
    async def test_scrape_missing_plan_returns_404(self):
        """POST /scrape with nonexistent plan_name returns 404."""
        toolkit = _make_mock_toolkit()
        toolkit.plan_load = AsyncMock(return_value=None)
        h = _make_handler(
            "POST", "/api/v1/scraping/scrape",
            toolkit=toolkit,
            json_body={
                "url": "https://example.com",
                "plan_name": "nonexistent",
            },
        )
        resp = await h.post()
        assert resp.status == 404


# ---------------------------------------------------------------------------
# Integration: Crawl execution flow
# ---------------------------------------------------------------------------

class TestCrawlExecution:
    """Integration tests for POST /crawl endpoint."""

    @pytest.mark.asyncio
    async def test_crawl_submits_job(self):
        """POST /crawl creates a job and returns 202 with job_id."""
        jm = _make_mock_job_manager()
        h = _make_handler(
            "POST", "/api/v1/scraping/crawl",
            job_manager=jm,
            json_body={"start_url": "https://example.com"},
        )
        resp = await h.post()
        assert resp.status == 202
        data = _parse(resp)
        assert "job_id" in data
        assert data["status"] == "queued"
        jm.create_job.assert_called_once()
        jm.execute_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_crawl_with_options(self):
        """POST /crawl with depth and max_pages passes them through."""
        jm = _make_mock_job_manager()
        h = _make_handler(
            "POST", "/api/v1/scraping/crawl",
            job_manager=jm,
            json_body={
                "start_url": "https://example.com",
                "depth": 3,
                "max_pages": 50,
            },
        )
        resp = await h.post()
        assert resp.status == 202


# ---------------------------------------------------------------------------
# Integration: Job status flow
# ---------------------------------------------------------------------------

class TestJobStatusFlow:
    """Integration tests for submit → check job status flow."""

    @pytest.mark.asyncio
    async def test_submit_then_check_status(self):
        """Submit a scrape job, then check its status via PATCH."""
        toolkit = _make_mock_toolkit()
        jm = _make_mock_job_manager()

        # Step 1: Submit scrape job
        h = _make_handler(
            "POST", "/api/v1/scraping/scrape",
            toolkit=toolkit, job_manager=jm,
            json_body={"url": "https://example.com"},
        )
        resp = await h.post()
        assert resp.status == 202
        submitted_job_id = _parse(resp)["job_id"]

        # Step 2: Mock the job as completed
        completed_job = Job(
            job_id=submitted_job_id,
            obj_id="scrape",
            query={"url": "https://example.com"},
            status=JobStatus.COMPLETED,
            result={"success": True, "data": [{"title": "Example"}]},
        )
        jm.get_job = MagicMock(return_value=completed_job)

        # Step 3: Check status
        h = _make_handler(
            "PATCH", f"/api/v1/scraping/jobs/{submitted_job_id}",
            toolkit=toolkit, job_manager=jm,
            match_info={"name": submitted_job_id},
        )
        resp = await h.patch()
        assert resp.status == 200
        data = _parse(resp)
        assert data["job_id"] == submitted_job_id
        assert data["status"] == "completed"
        assert data["result"]["success"] is True

    @pytest.mark.asyncio
    async def test_check_nonexistent_job(self):
        """PATCH for nonexistent job returns 404."""
        h = _make_handler(
            "PATCH", "/api/v1/scraping/jobs/nonexistent",
            match_info={"name": "nonexistent"},
        )
        resp = await h.patch()
        assert resp.status == 404


# ---------------------------------------------------------------------------
# Integration: Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Integration tests for error cases across all endpoints."""

    @pytest.mark.asyncio
    async def test_create_plan_missing_objective(self):
        """POST /plans with missing objective returns 400."""
        h = _make_handler(
            "POST", "/api/v1/scraping/plans",
            json_body={"url": "https://example.com"},
        )
        resp = await h.post()
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_scrape_missing_url(self):
        """POST /scrape with missing url returns 400."""
        h = _make_handler(
            "POST", "/api/v1/scraping/scrape",
            json_body={},
        )
        resp = await h.post()
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_crawl_missing_start_url(self):
        """POST /crawl with missing start_url returns 400."""
        h = _make_handler(
            "POST", "/api/v1/scraping/crawl",
            json_body={},
        )
        resp = await h.post()
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_put_without_name_returns_400(self):
        """PUT /plans without name returns 400."""
        h = _make_handler(
            "PUT", "/api/v1/scraping/plans",
            match_info={},
            json_body={"plan": {"steps": []}},
        )
        resp = await h.put()
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_put_missing_plan_body_returns_400(self):
        """PUT /plans/{name} with missing plan body returns 400."""
        h = _make_handler(
            "PUT", "/api/v1/scraping/plans/test",
            match_info={"name": "test"},
            json_body={},
        )
        resp = await h.put()
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_delete_without_name_returns_400(self):
        """DELETE /plans without name returns 400."""
        h = _make_handler(
            "DELETE", "/api/v1/scraping/plans",
            match_info={},
        )
        resp = await h.delete()
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_patch_without_name_returns_400(self):
        """PATCH /jobs without job_id returns 400."""
        h = _make_handler(
            "PATCH", "/api/v1/scraping/jobs",
            match_info={},
        )
        resp = await h.patch()
        assert resp.status == 400
