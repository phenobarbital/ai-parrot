"""Unit tests for ScrapingHandler — plan CRUD + scrape/crawl execution."""
import json
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.handlers.scraping.handler import (
    ScrapingHandler,
    _TOOLKIT_KEY,
    _JOB_MANAGER_KEY,
)
from parrot.handlers.jobs.models import Job, JobStatus


# ---------------------------------------------------------------------------
# Mock Toolkit & Helpers
# ---------------------------------------------------------------------------

class MockPlanSummary:
    """Mock PlanSummary for plan_list responses."""
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
            "objective": "test",
            "steps": [],
        }


class MockSaveResult:
    """Mock PlanSaveResult."""
    def __init__(self, name: str = "test-plan"):
        self.success = True
        self.path = f"plans/{name}.json"
        self.name = name
        self.version = "1.0"
        self.registered = True
        self.message = "Saved"

    def model_dump(self, mode: str = "python") -> Dict[str, Any]:
        return {
            "success": self.success,
            "path": self.path,
            "name": self.name,
            "version": self.version,
            "registered": self.registered,
            "message": self.message,
        }


def _make_mock_toolkit():
    """Create a mock WebScrapingToolkit."""
    toolkit = AsyncMock()
    toolkit.plan_list = AsyncMock(return_value=[
        MockPlanSummary("plan-a"),
        MockPlanSummary("plan-b"),
    ])
    toolkit.plan_load = AsyncMock(return_value=MockPlan("test-plan"))
    toolkit.plan_create = AsyncMock(return_value=MockPlan("new-plan"))
    toolkit.plan_save = AsyncMock(return_value=MockSaveResult("test-plan"))
    toolkit.plan_delete = AsyncMock(return_value=True)
    toolkit.scrape = AsyncMock(return_value={"url": "https://example.com", "success": True})
    toolkit.crawl = AsyncMock(return_value={"start_url": "https://example.com", "pages": []})
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


def _make_app(toolkit=None, job_manager=None):
    """Create a mock aiohttp app dict with scraping resources."""
    app = {}
    if toolkit is not None:
        app[_TOOLKIT_KEY] = toolkit
    if job_manager is not None:
        app[_JOB_MANAGER_KEY] = job_manager
    return app


def _make_handler(
    method: str = "GET",
    path: str = "/api/v1/scraping/plans",
    match_info: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, str]] = None,
    toolkit=None,
    job_manager=None,
) -> ScrapingHandler:
    """Create a ScrapingHandler with a mocked request."""
    if toolkit is None:
        toolkit = _make_mock_toolkit()
    if job_manager is None:
        job_manager = _make_mock_job_manager()

    app = _make_app(toolkit, job_manager)

    # Build path with query string if provided
    full_path = path
    if query:
        qs = "&".join(f"{k}={v}" for k, v in query.items())
        full_path = f"{path}?{qs}"

    request = make_mocked_request(
        method,
        full_path,
        match_info=match_info or {},
        app=app,
    )

    # Patch json() method for POST/PUT/PATCH requests
    if json_body is not None:
        request.json = AsyncMock(return_value=json_body)

    handler = ScrapingHandler.__new__(ScrapingHandler)
    handler._request = request
    handler.request = request
    handler.logger = MagicMock()

    return handler


def _parse_body(resp: web.Response) -> dict:
    """Parse JSON from a web.Response body."""
    return json.loads(resp.body)


# ---------------------------------------------------------------------------
# GET Tests
# ---------------------------------------------------------------------------

class TestGetPlanList:
    """Tests for GET /plans — list plans."""

    @pytest.mark.asyncio
    async def test_list_plans_returns_200(self):
        """GET /plans returns 200 with plan list."""
        handler = _make_handler(method="GET", path="/api/v1/scraping/plans")
        resp = await handler.get()
        data = _parse_body(resp)
        assert resp.status == 200
        assert "plans" in data
        assert len(data["plans"]) == 2

    @pytest.mark.asyncio
    async def test_list_plans_with_domain_filter(self):
        """GET /plans?domain_filter=example passes filter to toolkit."""
        toolkit = _make_mock_toolkit()
        handler = _make_handler(
            method="GET",
            path="/api/v1/scraping/plans",
            query={"domain_filter": "example.com"},
            toolkit=toolkit,
        )
        await handler.get()
        toolkit.plan_list.assert_called_once_with(
            domain_filter="example.com",
            tag_filter=None,
        )


class TestGetPlanLoad:
    """Tests for GET /plans/{name} — load a specific plan."""

    @pytest.mark.asyncio
    async def test_load_plan_returns_200(self):
        """GET /plans/{name} returns plan data."""
        handler = _make_handler(
            method="GET",
            path="/api/v1/scraping/plans/test-plan",
            match_info={"name": "test-plan"},
        )
        resp = await handler.get()
        data = _parse_body(resp)
        assert resp.status == 200
        assert data["name"] == "test-plan"

    @pytest.mark.asyncio
    async def test_load_plan_not_found_returns_404(self):
        """GET /plans/{name} returns 404 when plan doesn't exist."""
        toolkit = _make_mock_toolkit()
        toolkit.plan_load = AsyncMock(return_value=None)
        handler = _make_handler(
            method="GET",
            path="/api/v1/scraping/plans/missing",
            match_info={"name": "missing"},
            toolkit=toolkit,
        )
        resp = await handler.get()
        assert resp.status == 404


# ---------------------------------------------------------------------------
# POST Tests
# ---------------------------------------------------------------------------

class TestPostPlanCreate:
    """Tests for POST /plans — create a plan via LLM."""

    @pytest.mark.asyncio
    async def test_create_plan_returns_201(self):
        """POST /plans creates plan and returns 201."""
        handler = _make_handler(
            method="POST",
            path="/api/v1/scraping/plans",
            json_body={
                "url": "https://example.com",
                "objective": "Extract products",
            },
        )
        resp = await handler.post()
        data = _parse_body(resp)
        assert resp.status == 201
        assert data["name"] == "new-plan"

    @pytest.mark.asyncio
    async def test_create_plan_with_save(self):
        """POST /plans with save=True also saves the plan."""
        toolkit = _make_mock_toolkit()
        handler = _make_handler(
            method="POST",
            path="/api/v1/scraping/plans",
            json_body={
                "url": "https://example.com",
                "objective": "Extract products",
                "save": True,
            },
            toolkit=toolkit,
        )
        resp = await handler.post()
        data = _parse_body(resp)
        assert resp.status == 201
        assert "save_result" in data
        toolkit.plan_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_plan_validation_error(self):
        """POST /plans with missing fields returns 400."""
        handler = _make_handler(
            method="POST",
            path="/api/v1/scraping/plans",
            json_body={"url": "https://example.com"},  # missing objective
        )
        resp = await handler.post()
        assert resp.status == 400


class TestPostScrape:
    """Tests for POST /scrape — submit a scraping job."""

    @pytest.mark.asyncio
    async def test_scrape_returns_202_with_job_id(self):
        """POST /scrape submits job and returns 202 with job_id."""
        handler = _make_handler(
            method="POST",
            path="/api/v1/scraping/scrape",
            json_body={"url": "https://example.com"},
        )
        resp = await handler.post()
        data = _parse_body(resp)
        assert resp.status == 202
        assert "job_id" in data
        assert data["status"] == "queued"

    @pytest.mark.asyncio
    async def test_scrape_with_plan_name(self):
        """POST /scrape with plan_name loads the plan first."""
        toolkit = _make_mock_toolkit()
        handler = _make_handler(
            method="POST",
            path="/api/v1/scraping/scrape",
            json_body={
                "url": "https://example.com",
                "plan_name": "my-plan",
            },
            toolkit=toolkit,
        )
        resp = await handler.post()
        assert resp.status == 202
        toolkit.plan_load.assert_called_once_with("my-plan")

    @pytest.mark.asyncio
    async def test_scrape_plan_name_not_found(self):
        """POST /scrape with missing plan_name returns 404."""
        toolkit = _make_mock_toolkit()
        toolkit.plan_load = AsyncMock(return_value=None)
        handler = _make_handler(
            method="POST",
            path="/api/v1/scraping/scrape",
            json_body={
                "url": "https://example.com",
                "plan_name": "nonexistent",
            },
            toolkit=toolkit,
        )
        resp = await handler.post()
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_scrape_creates_job(self):
        """POST /scrape creates a job in the JobManager."""
        jm = _make_mock_job_manager()
        handler = _make_handler(
            method="POST",
            path="/api/v1/scraping/scrape",
            json_body={"url": "https://example.com"},
            job_manager=jm,
        )
        await handler.post()
        jm.create_job.assert_called_once()
        jm.execute_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_scrape_validation_error(self):
        """POST /scrape with missing url returns 400."""
        handler = _make_handler(
            method="POST",
            path="/api/v1/scraping/scrape",
            json_body={},  # missing url
        )
        resp = await handler.post()
        assert resp.status == 400


class TestPostCrawl:
    """Tests for POST /crawl — submit a crawl job."""

    @pytest.mark.asyncio
    async def test_crawl_returns_202_with_job_id(self):
        """POST /crawl submits job and returns 202 with job_id."""
        handler = _make_handler(
            method="POST",
            path="/api/v1/scraping/crawl",
            json_body={"start_url": "https://example.com"},
        )
        resp = await handler.post()
        data = _parse_body(resp)
        assert resp.status == 202
        assert "job_id" in data
        assert data["status"] == "queued"

    @pytest.mark.asyncio
    async def test_crawl_creates_job(self):
        """POST /crawl creates a job in the JobManager."""
        jm = _make_mock_job_manager()
        handler = _make_handler(
            method="POST",
            path="/api/v1/scraping/crawl",
            json_body={"start_url": "https://example.com"},
            job_manager=jm,
        )
        await handler.post()
        jm.create_job.assert_called_once()
        jm.execute_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_crawl_validation_error(self):
        """POST /crawl with missing start_url returns 400."""
        handler = _make_handler(
            method="POST",
            path="/api/v1/scraping/crawl",
            json_body={},  # missing start_url
        )
        resp = await handler.post()
        assert resp.status == 400


# ---------------------------------------------------------------------------
# PUT Tests
# ---------------------------------------------------------------------------

class TestPutPlanSave:
    """Tests for PUT /plans/{name} — save a plan."""

    @pytest.mark.asyncio
    async def test_save_plan_returns_200(self):
        """PUT /plans/{name} saves plan and returns result."""
        handler = _make_handler(
            method="PUT",
            path="/api/v1/scraping/plans/test-plan",
            match_info={"name": "test-plan"},
            json_body={
                "plan": {
                    "url": "https://example.com",
                    "objective": "Extract data",
                    "steps": [],
                },
            },
        )
        resp = await handler.put()
        data = _parse_body(resp)
        assert resp.status == 200
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_save_plan_missing_name_returns_400(self):
        """PUT /plans without name returns 400."""
        handler = _make_handler(
            method="PUT",
            path="/api/v1/scraping/plans",
            match_info={},
            json_body={"plan": {"steps": []}},
        )
        resp = await handler.put()
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_save_plan_validation_error(self):
        """PUT /plans/{name} with missing plan returns 400."""
        handler = _make_handler(
            method="PUT",
            path="/api/v1/scraping/plans/test",
            match_info={"name": "test"},
            json_body={},  # missing plan
        )
        resp = await handler.put()
        assert resp.status == 400


# ---------------------------------------------------------------------------
# PATCH Tests (job status)
# ---------------------------------------------------------------------------

class TestPatchJobStatus:
    """Tests for PATCH /{job_id} — check job status."""

    @pytest.mark.asyncio
    async def test_patch_job_found(self):
        """PATCH /{job_id} returns job status when found."""
        job = Job(
            job_id="abc-123",
            obj_id="scrape",
            query={"url": "https://example.com"},
            status=JobStatus.COMPLETED,
            result={"success": True},
        )
        jm = _make_mock_job_manager()
        jm.get_job = MagicMock(return_value=job)

        handler = _make_handler(
            method="PATCH",
            path="/api/v1/scraping/jobs/abc-123",
            match_info={"name": "abc-123"},
            job_manager=jm,
        )
        resp = await handler.patch()
        data = _parse_body(resp)
        assert resp.status == 200
        assert data["job_id"] == "abc-123"
        assert data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_patch_job_not_found(self):
        """PATCH /{job_id} returns 404 when job doesn't exist."""
        handler = _make_handler(
            method="PATCH",
            path="/api/v1/scraping/jobs/nonexistent",
            match_info={"name": "nonexistent"},
        )
        resp = await handler.patch()
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_patch_missing_name_returns_400(self):
        """PATCH without identifier returns 400."""
        handler = _make_handler(
            method="PATCH",
            path="/api/v1/scraping/jobs",
            match_info={},
        )
        resp = await handler.patch()
        assert resp.status == 400


# ---------------------------------------------------------------------------
# DELETE Tests
# ---------------------------------------------------------------------------

class TestDeletePlan:
    """Tests for DELETE /plans/{name} — delete a plan."""

    @pytest.mark.asyncio
    async def test_delete_plan_returns_200(self):
        """DELETE /plans/{name} deletes plan."""
        handler = _make_handler(
            method="DELETE",
            path="/api/v1/scraping/plans/test-plan",
            match_info={"name": "test-plan"},
        )
        resp = await handler.delete()
        data = _parse_body(resp)
        assert resp.status == 200
        assert "deleted" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_plan_not_found(self):
        """DELETE /plans/{name} returns 404 when plan doesn't exist."""
        toolkit = _make_mock_toolkit()
        toolkit.plan_delete = AsyncMock(return_value=False)
        handler = _make_handler(
            method="DELETE",
            path="/api/v1/scraping/plans/missing",
            match_info={"name": "missing"},
            toolkit=toolkit,
        )
        resp = await handler.delete()
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_delete_plan_missing_name_returns_400(self):
        """DELETE /plans without name returns 400."""
        handler = _make_handler(
            method="DELETE",
            path="/api/v1/scraping/plans",
            match_info={},
        )
        resp = await handler.delete()
        assert resp.status == 400


# ---------------------------------------------------------------------------
# Setup / Lifecycle Tests
# ---------------------------------------------------------------------------

class TestSetup:
    """Tests for ScrapingHandler.setup() and lifecycle signals."""

    def test_setup_registers_routes(self):
        """setup() registers all expected routes."""
        app = web.Application()
        ScrapingHandler.setup(app)

        paths = set()
        for resource in app.router.resources():
            info = resource.get_info()
            path = info.get("formatter") or info.get("path", "")
            if path:
                paths.add(path)

        assert "/api/v1/scraping/plans" in paths
        assert "/api/v1/scraping/plans/{name}" in paths
        assert "/api/v1/scraping/scrape" in paths
        assert "/api/v1/scraping/crawl" in paths
        assert "/api/v1/scraping/jobs/{name}" in paths

    def test_setup_registers_signals(self):
        """setup() registers on_startup and on_cleanup signals."""
        app = web.Application()
        initial_startup = len(app.on_startup)
        initial_cleanup = len(app.on_cleanup)
        ScrapingHandler.setup(app)
        assert len(app.on_startup) == initial_startup + 1
        assert len(app.on_cleanup) == initial_cleanup + 1


class TestImports:
    """Tests for module imports."""

    def test_import_handler(self):
        """ScrapingHandler can be imported."""
        from parrot.handlers.scraping.handler import ScrapingHandler
        assert ScrapingHandler is not None

    def test_handler_extends_baseview(self):
        """ScrapingHandler extends BaseView."""
        from navigator.views import BaseView
        assert issubclass(ScrapingHandler, BaseView)
