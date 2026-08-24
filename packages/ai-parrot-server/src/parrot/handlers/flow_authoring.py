"""HTTP handler for natural-language workflow authoring.

Endpoints::

    POST /api/v1/flows/authoring            → 202 + {job_id}
    GET  /api/v1/flows/authoring/{job_id}   → status, progress, result
    GET  /api/v1/flows/authoring            → the request JSON Schema

Authoring is one LLM call per node plus a skeleton, a transition pass and
possibly a repair round, so a ten-node workflow is a dozen sequential model
calls — far past what an HTTP request should hold open. It therefore runs on
the ``JobManager``, following the ``video_reel.py`` template: the POST
returns immediately with a job id and the client polls.

Progress is reported through ``JobManager.report_progress`` at every stage,
so a poll answers "authoring node 4/7" rather than an opaque "running" —
which matters precisely because the run is long and made of many small
steps. That call mirrors the change to the job store, so the counter is
visible to a poll served by any worker, not only the one running the job.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional, TYPE_CHECKING

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from pydantic import ValidationError

from parrot.bots.flows.authoring import (
    AuthoringProgress,
    FlowAuthoringOrchestrator,
    FlowAuthoringRequest,
    FlowAuthoringResult,
    build_catalog,
)

from .jobs import JobManager, JobStatus

if TYPE_CHECKING:  # pragma: no cover
    from navigator.types import WebApp


@is_authenticated()
@user_session()
class FlowAuthoringHandler(BaseView):
    """REST handler that authors a workflow from a natural-language request.

    Endpoints:
        POST /api/v1/flows/authoring — submit a request (202 + job_id).
        GET  /api/v1/flows/authoring/{job_id} — poll status/progress/result.
        GET  /api/v1/flows/authoring — request schema + the component catalog.

    FEAT-446: every HTTP method requires an authenticated session
    (mirrors ``tool_catalog.py:231`` / ``special_nodes.py:74``). No tenant
    resolution here — this handler has no tenant parameter today (spec
    §3 Module 4 scopes the auth requirement only; PBAC policy for
    ``flows:author`` is deferred to S5).
    """

    _logger_name = "Parrot.FlowAuthoringHandler"

    #: Model used when the request does not name one. Read from config at
    #: request time rather than import time so deployments can change it
    #: without a restart-order dependency.
    _DEFAULT_PLANNER_SETTING = "FLOW_AUTHORING_PLANNER_LLM"
    _DEFAULT_PLANNER = "openai:gpt-4o"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self._logger_name)

    # ------------------------------------------------------------------
    # App-level setup
    # ------------------------------------------------------------------

    @classmethod
    def setup(cls, app: "WebApp", route: str = "/api/v1/flows/authoring") -> None:
        """Register both the collection and the per-job routes.

        Args:
            app: The aiohttp application (or a navigator wrapper).
            route: Base route to mount on.
        """
        _app = app.get_app() if hasattr(app, "get_app") else app
        _app.router.add_view(route, cls)
        _app.router.add_view(f"{route}/{{job_id}}", cls)

    @property
    def job_manager(self) -> JobManager:
        """Resolve the JobManager from the request's app.

        Returns:
            The configured :class:`JobManager`.

        Raises:
            RuntimeError: If ``configure_job_manager(app)`` was never called.
        """
        app = self.request.app
        if "job_manager" in app:
            return app["job_manager"]
        raise RuntimeError(
            "JobManager not configured. Call configure_job_manager(app) during startup."
        )

    # ------------------------------------------------------------------
    # POST — submit
    # ------------------------------------------------------------------

    async def post(self) -> web.Response:
        """Submit an authoring request and return its job id.

        Returns:
            ``202`` with the job id, or ``400`` when the body is unusable.
        """
        try:
            data: Dict[str, Any] = await self.request.json()
        except Exception as exc:
            self.logger.warning("Failed to parse request body: %s", exc)
            return self.error("Invalid JSON request body.", status=400)

        # Control keys that are not part of the authoring contract.
        planner_llm = data.pop("planner_llm", None) or self._configured_planner()
        user_id: Optional[str] = data.pop("user_id", None)
        session_id: Optional[str] = data.pop("session_id", None)

        try:
            request = FlowAuthoringRequest(**data)
        except ValidationError as exc:
            return self.error(str(exc), status=400)

        job = self.job_manager.create_job(
            job_id=str(uuid.uuid4()),
            obj_id="flow_authoring",
            query=request.description,
            user_id=user_id,
            session_id=session_id,
            execution_mode=request.engine,
        )
        job.metadata["progress"] = AuthoringProgress(
            stage="skeleton", message="Queued"
        ).model_dump(mode="json")

        tool_manager = self.request.app.get("tool_manager")
        job_manager = self.job_manager

        async def run_logic() -> Dict[str, Any]:
            """Author the workflow, recording progress as it goes."""
            orchestrator = FlowAuthoringOrchestrator(
                planner_llm, tool_manager=tool_manager
            )

            async def _on_progress(progress: AuthoringProgress) -> None:
                # Through the manager, not by mutating job.metadata directly:
                # only this path mirrors the change to the store, which is
                # what makes "authoring node 4/7" visible to a poll served by
                # another worker.
                await job_manager.report_progress(job.job_id, progress)

            result = await orchestrator.build(request, on_progress=_on_progress)

            if request.persist and (
                result.crew_definition or result.flow_definition
            ):
                result = await self._persist(result)

            # Dumped to JSON so the Redis-backed job record stays
            # round-trippable, as video_reel.py does for its AIMessage.
            return result.model_dump(mode="json")

        await self.job_manager.execute_job(job.job_id, run_logic)

        return self.json_response(
            {
                "job_id": job.job_id,
                "status": job.status.value,
                "message": "Workflow authoring started",
                "created_at": job.created_at.isoformat(),
            },
            status=202,
        )

    # ------------------------------------------------------------------
    # GET — poll, or describe
    # ------------------------------------------------------------------

    async def get(self) -> web.Response:
        """Return job state when ``job_id`` is present, else the schema."""
        job_id = self.request.match_info.get("job_id")
        if job_id:
            return await self._get_job_status(job_id)

        # Same tool_manager the POST path uses, so the catalog this endpoint
        # advertises is the one an authoring run would actually see.
        catalog = build_catalog(tool_manager=self.request.app.get("tool_manager"))
        return self.json_response(
            {
                "request_schema": FlowAuthoringRequest.model_json_schema(),
                "result_schema": FlowAuthoringResult.model_json_schema(),
                "engines": {
                    "crew": catalog.kinds_for("crew"),
                    "flow": catalog.kinds_for("flow"),
                },
                "counts": {
                    "node_types": len(catalog.node_types),
                    "agents": len(catalog.agents),
                    "tools": len(catalog.tools),
                },
            }
        )

    async def _get_job_status(self, job_id: str) -> web.Response:
        """Build the response for one job.

        Uses ``get_job_async`` so a job persisted to Redis is still
        retrievable after a restart has emptied the in-memory map.

        Args:
            job_id: The job to look up.

        Returns:
            The job's state, or ``404``.
        """
        job = await self.job_manager.get_job_async(job_id)
        if not job:
            return self.error(
                response={"message": f"Job '{job_id}' not found"}, status=404
            )

        payload: Dict[str, Any] = {
            "job_id": job.job_id,
            "status": job.status.value,
            "created_at": job.created_at.isoformat(),
        }
        progress = (job.metadata or {}).get("progress")
        if progress:
            payload["progress"] = progress

        if job.status == JobStatus.COMPLETED:
            payload["result"] = job.result
            if job.completed_at:
                payload["completed_at"] = job.completed_at.isoformat()
            if job.elapsed_time is not None:
                payload["elapsed_time"] = job.elapsed_time
        elif job.status == JobStatus.FAILED:
            payload["error"] = str(job.error)
            if job.completed_at:
                payload["completed_at"] = job.completed_at.isoformat()
        elif job.status == JobStatus.RUNNING:
            if job.started_at:
                payload["started_at"] = job.started_at.isoformat()
            if job.elapsed_time is not None:
                payload["elapsed_time"] = job.elapsed_time

        return self.json_response(payload)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _configured_planner(self) -> str:
        """Return the configured planner model, or the built-in default."""
        try:
            from parrot.conf import config  # noqa: PLC0415

            return config.get(
                self._DEFAULT_PLANNER_SETTING, fallback=self._DEFAULT_PLANNER
            )
        except Exception:  # pragma: no cover - config is optional
            return self._DEFAULT_PLANNER

    async def _persist(self, result: FlowAuthoringResult) -> FlowAuthoringResult:
        """Store the compiled definition, when the caller asked for it.

        Persisting is opt-in and best-effort: the authored definition is the
        deliverable, and failing the whole run because a store was
        unreachable would throw away work that took a dozen model calls. A
        storage failure is reported through ``persisted_as`` staying unset.

        Args:
            result: The successful authoring result.

        Returns:
            ``result``, with ``persisted_as`` set on success.
        """
        redis = self.request.app.get("redis")
        if redis is None:
            self.logger.warning("persist=True but no redis is configured on the app")
            return result

        try:
            if result.flow_definition is not None:
                from parrot.bots.flows.flow.definition import (  # noqa: PLC0415
                    FlowDefinition,
                )
                from parrot.bots.flows.flow.loader import FlowLoader  # noqa: PLC0415

                definition = FlowDefinition.model_validate(result.flow_definition)
                await FlowLoader.save_to_redis(redis, definition)
                return result.model_copy(
                    update={"persisted_as": f"parrot:flow:{definition.flow}"}
                )

            if result.crew_definition is not None:
                key = f"parrot:crew:{result.crew_definition['crew_id']}"
                import json  # noqa: PLC0415

                await redis.set(key, json.dumps(result.crew_definition))
                return result.model_copy(update={"persisted_as": key})
        except Exception:
            self.logger.exception("Failed to persist the authored workflow")

        return result
