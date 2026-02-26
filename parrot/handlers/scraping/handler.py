"""ScrapingHandler — Class-based HTTP view for plan CRUD and scrape/crawl execution.

Exposes the WebScrapingToolkit API over HTTP at /api/v1/scraping/.
Manages its own WebScrapingToolkit instance, JobManager for async execution,
and integrates with a BasicAgent for LLM-powered plan generation.
"""
import uuid
from typing import Any, Dict

from aiohttp import web
from datamodel.parsers.json import json_encoder  # pylint: disable=E0611
from navconfig.logging import logging
from navigator.views import BaseView
from pydantic import ValidationError

from parrot.handlers.jobs.job import JobManager
from parrot.tools.scraping import WebScrapingToolkit

from .models import (
    CrawlRequest,
    PlanCreateRequest,
    PlanSaveRequest,
    ScrapeRequest,
)


def _json_response(data: Any, status: int = 200) -> web.Response:
    """Create a JSON response using the project's json_encoder."""
    return web.json_response(data, status=status, dumps=json_encoder)


def _error_response(data: Any, status: int = 400) -> web.Response:
    """Create a JSON error response."""
    return web.json_response(data, status=status, dumps=json_encoder)


# App context keys
_TOOLKIT_KEY = "scraping_toolkit"
_JOB_MANAGER_KEY = "scraping_job_manager"


class ScrapingHandler(BaseView):
    """Class-based HTTP view for /api/v1/scraping/.

    Handles plan CRUD (create via LLM, list, load, save, delete) and
    scrape/crawl execution via JobManager for async processing.

    Routes:
        GET    /plans           — list saved plans
        GET    /plans/{name}    — load a specific plan
        POST   /plans           — create a plan via LLM
        PUT    /plans/{name}    — save/update a plan
        PATCH  /plans/{name}    — partial update (reserved)
        PATCH  /jobs/{job_id}   — check job status
        DELETE /plans/{name}    — delete a plan
        POST   /scrape          — submit a scraping job
        POST   /crawl           — submit a crawl job
    """

    def post_init(self, *args, **kwargs):
        """Post-initialization hook called by BaseView."""
        self.logger = logging.getLogger("Parrot.ScrapingHandler")

    # ------------------------------------------------------------------
    # Helpers to access app-level resources
    # ------------------------------------------------------------------

    def _get_toolkit(self) -> WebScrapingToolkit:
        """Retrieve the WebScrapingToolkit from app context."""
        toolkit = self.request.app.get(_TOOLKIT_KEY)
        if toolkit is None:
            raise web.HTTPServiceUnavailable(
                reason="ScrapingToolkit not initialized. Call setup() first."
            )
        return toolkit

    def _get_job_manager(self) -> JobManager:
        """Retrieve the JobManager from app context."""
        jm = self.request.app.get(_JOB_MANAGER_KEY)
        if jm is None:
            raise web.HTTPServiceUnavailable(
                reason="JobManager not initialized. Call setup() first."
            )
        return jm

    async def _parse_json(self) -> Dict[str, Any]:
        """Parse JSON body from request, raising 400 on failure."""
        try:
            return await self.request.json()
        except Exception as err:
            raise web.HTTPBadRequest(
                reason=f"Invalid JSON body: {err}"
            ) from err

    # ------------------------------------------------------------------
    # GET — list plans or load a specific plan
    # ------------------------------------------------------------------

    async def get(self) -> web.Response:
        """Handle GET requests.

        GET /plans           — list all plans (optional: ?domain_filter=&tag_filter=)
        GET /plans/{name}    — load a specific plan by name
        """
        try:
            toolkit = self._get_toolkit()
            name = self.request.match_info.get("name")

            if name:
                return await self._handle_plan_load(toolkit, name)
            return await self._handle_plan_list(toolkit)
        except web.HTTPException:
            raise
        except Exception as err:
            self.logger.error(f"GET error: {err}", exc_info=True)
            return _error_response({"error": str(err)}, status=500)

    async def _handle_plan_list(self, toolkit: WebScrapingToolkit) -> web.Response:
        """List all saved plans with optional filters."""
        params = dict(self.request.query)
        plans = await toolkit.plan_list(
            domain_filter=params.get("domain_filter"),
            tag_filter=params.get("tag_filter"),
        )
        return _json_response(
            {"plans": [p.model_dump(mode="json") for p in plans]},
        )

    async def _handle_plan_load(
        self, toolkit: WebScrapingToolkit, name: str
    ) -> web.Response:
        """Load a specific plan by name."""
        plan = await toolkit.plan_load(name)
        if plan is None:
            return _error_response(
                {"error": f"Plan '{name}' not found"}, status=404
            )
        return _json_response(plan.model_dump(mode="json"))

    # ------------------------------------------------------------------
    # POST — create plan, scrape, or crawl (dispatched by path)
    # ------------------------------------------------------------------

    async def post(self) -> web.Response:
        """Handle POST requests.

        POST /plans   — create a plan via LLM
        POST /scrape  — submit a scraping job
        POST /crawl   — submit a crawl job
        """
        try:
            path = self.request.path
            data = await self._parse_json()

            if path.endswith("/scrape"):
                return await self._handle_scrape(data)
            elif path.endswith("/crawl"):
                return await self._handle_crawl(data)
            else:
                return await self._handle_plan_create(data)
        except web.HTTPException:
            raise
        except ValidationError as err:
            return _error_response(
                {"error": "Validation error", "details": err.errors()},
                status=400,
            )
        except Exception as err:
            self.logger.error(f"POST error: {err}", exc_info=True)
            return _error_response({"error": str(err)}, status=500)

    async def _handle_plan_create(self, data: Dict[str, Any]) -> web.Response:
        """Create a new plan via LLM."""
        req = PlanCreateRequest.model_validate(data)
        toolkit = self._get_toolkit()

        plan = await toolkit.plan_create(
            url=req.url,
            objective=req.objective,
            hints=req.hints,
            force_regenerate=req.force_regenerate,
        )

        result = plan.model_dump(mode="json")

        # Optionally save immediately
        if req.save:
            save_result = await toolkit.plan_save(plan)
            result["save_result"] = save_result.model_dump(mode="json")

        return _json_response(result, status=201)

    async def _handle_scrape(self, data: Dict[str, Any]) -> web.Response:
        """Submit a scraping job for async execution."""
        req = ScrapeRequest.model_validate(data)
        toolkit = self._get_toolkit()
        jm = self._get_job_manager()

        job_id = str(uuid.uuid4())

        # Resolve plan by name if provided
        plan = req.plan
        if req.plan_name and plan is None:
            loaded = await toolkit.plan_load(req.plan_name)
            if loaded is None:
                return _error_response(
                    {"error": f"Plan '{req.plan_name}' not found"}, status=404
                )
            plan = loaded.model_dump(mode="json")

        async def _execute_scrape():
            return await toolkit.scrape(
                url=req.url,
                plan=plan,
                objective=req.objective,
                steps=req.steps,
                selectors=req.selectors,
                save_plan=req.save_plan,
                browser_config_override=req.browser_config_override,
            )

        jm.create_job(
            job_id=job_id,
            obj_id="scrape",
            query={"url": req.url, "objective": req.objective},
        )
        await jm.execute_job(job_id, _execute_scrape)

        return _json_response(
            {"job_id": job_id, "status": "queued"},
            status=202,
        )

    async def _handle_crawl(self, data: Dict[str, Any]) -> web.Response:
        """Submit a crawl job for async execution."""
        req = CrawlRequest.model_validate(data)
        toolkit = self._get_toolkit()
        jm = self._get_job_manager()

        job_id = str(uuid.uuid4())

        # Resolve plan by name if provided
        plan = req.plan
        if req.plan_name and plan is None:
            loaded = await toolkit.plan_load(req.plan_name)
            if loaded is None:
                return _error_response(
                    {"error": f"Plan '{req.plan_name}' not found"}, status=404
                )
            plan = loaded.model_dump(mode="json")

        async def _execute_crawl():
            return await toolkit.crawl(
                start_url=req.start_url,
                depth=req.depth,
                max_pages=req.max_pages,
                follow_selector=req.follow_selector,
                follow_pattern=req.follow_pattern,
                plan=plan,
                objective=req.objective,
                save_plan=req.save_plan,
                concurrency=req.concurrency,
            )

        jm.create_job(
            job_id=job_id,
            obj_id="crawl",
            query={"start_url": req.start_url, "depth": req.depth},
        )
        await jm.execute_job(job_id, _execute_crawl)

        return _json_response(
            {"job_id": job_id, "status": "queued"},
            status=202,
        )

    # ------------------------------------------------------------------
    # PUT — save/update a plan
    # ------------------------------------------------------------------

    async def put(self) -> web.Response:
        """PUT /plans/{name} — save or update a plan."""
        try:
            name = self.request.match_info.get("name")
            if not name:
                return _error_response(
                    {"error": "Plan name required in URL path"}, status=400
                )

            data = await self._parse_json()
            req = PlanSaveRequest.model_validate(data)
            toolkit = self._get_toolkit()

            # Import ScrapingPlan for validation
            from parrot.tools.scraping.plan import ScrapingPlan

            plan_data = req.plan.copy()
            if "name" not in plan_data or not plan_data["name"]:
                plan_data["name"] = name

            plan = ScrapingPlan.model_validate(plan_data)
            save_result = await toolkit.plan_save(plan, overwrite=req.overwrite)

            return _json_response(save_result.model_dump(mode="json"))

        except web.HTTPException:
            raise
        except ValidationError as err:
            return _error_response(
                {"error": "Validation error", "details": err.errors()},
                status=400,
            )
        except Exception as err:
            self.logger.error(f"PUT error: {err}", exc_info=True)
            return _error_response({"error": str(err)}, status=500)

    # ------------------------------------------------------------------
    # PATCH — check job status or partial plan update
    # ------------------------------------------------------------------

    async def patch(self) -> web.Response:
        """PATCH /{job_id} — check job status and retrieve results.
        PATCH /plans/{name} — partial plan update (reserved).
        """
        try:
            name = self.request.match_info.get("name")
            if not name:
                return _error_response(
                    {"error": "Identifier required in URL path"}, status=400
                )

            # Check if this is a job status request
            jm = self._get_job_manager()
            job = jm.get_job(name)
            if job is not None:
                return _json_response(job.to_dict())

            # Could also be a plan — return 404 if neither
            return _error_response(
                {"error": f"Job or plan '{name}' not found"}, status=404
            )

        except web.HTTPException:
            raise
        except Exception as err:
            self.logger.error(f"PATCH error: {err}", exc_info=True)
            return _error_response({"error": str(err)}, status=500)

    # ------------------------------------------------------------------
    # DELETE — delete a plan
    # ------------------------------------------------------------------

    async def delete(self) -> web.Response:
        """DELETE /plans/{name} — delete a plan by name."""
        try:
            name = self.request.match_info.get("name")
            if not name:
                return _error_response(
                    {"error": "Plan name required in URL path"}, status=400
                )

            toolkit = self._get_toolkit()
            deleted = await toolkit.plan_delete(name)

            if not deleted:
                return _error_response(
                    {"error": f"Plan '{name}' not found"}, status=404
                )

            return _json_response(
                {"message": f"Plan '{name}' deleted successfully"},
            )

        except web.HTTPException:
            raise
        except Exception as err:
            self.logger.error(f"DELETE error: {err}", exc_info=True)
            return _error_response({"error": str(err)}, status=500)

    # ------------------------------------------------------------------
    # Lifecycle: setup, startup, cleanup
    # ------------------------------------------------------------------

    @classmethod
    def setup(cls, app: web.Application) -> None:
        """Register routes and lifecycle signals on the aiohttp application.

        Args:
            app: The aiohttp web application.
        """
        # Class-based view routes for plan CRUD
        app.router.add_view("/api/v1/scraping/plans", cls)
        app.router.add_view("/api/v1/scraping/plans/{name}", cls)

        # POST-only execution routes (reuse the same view class)
        app.router.add_view("/api/v1/scraping/scrape", cls)
        app.router.add_view("/api/v1/scraping/crawl", cls)

        # Job status route
        app.router.add_view("/api/v1/scraping/jobs/{name}", cls)

        # Register startup/cleanup signals
        app.on_startup.append(cls._on_startup)
        app.on_cleanup.append(cls._on_cleanup)

    @staticmethod
    async def _on_startup(app: web.Application) -> None:
        """Initialize toolkit and job manager on app startup."""
        logger = logging.getLogger("Parrot.ScrapingHandler")

        # Create and start WebScrapingToolkit (session_based=False for safety)
        toolkit = WebScrapingToolkit(session_based=False)
        await toolkit.start()
        app[_TOOLKIT_KEY] = toolkit
        logger.info("WebScrapingToolkit started")

        # Create and start JobManager
        job_manager = JobManager(id="scraping")
        await job_manager.start()
        app[_JOB_MANAGER_KEY] = job_manager
        logger.info("Scraping JobManager started")

    @staticmethod
    async def _on_cleanup(app: web.Application) -> None:
        """Stop toolkit and job manager on app cleanup."""
        logger = logging.getLogger("Parrot.ScrapingHandler")

        if toolkit := app.get(_TOOLKIT_KEY):
            await toolkit.stop()
            logger.info("WebScrapingToolkit stopped")

        if jm := app.get(_JOB_MANAGER_KEY):
            await jm.stop()
            logger.info("Scraping JobManager stopped")
