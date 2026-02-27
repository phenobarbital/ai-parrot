"""HTTP handler for video reel generation with background job support."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING
import logging
from aiohttp import web
from navigator.views import BaseView

if TYPE_CHECKING:
    from navigator.types import WebApp
from pydantic import ValidationError
from parrot.clients.google import GoogleGenAIClient
from parrot.models.google import (
    AspectRatio,
    MusicGenre,
    MusicMood,
    VideoReelRequest,
    VideoReelScene,
    GoogleModel,
)
from .jobs import JobManager, JobStatus


class VideoReelHandler(BaseView):
    """REST handler for video reel generation using background jobs.

    Endpoints:
        POST /api/v1/google/generation/video_reel — Submit a video reel job (returns 202 + job_id).
        GET  /api/v1/google/generation/video_reel?job_id=<id> — Poll job status/result.
        GET  /api/v1/google/generation/video_reel — JSON Schema catalog (no job_id).
    """

    _logger_name = "Parrot.VideoReelHandler"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self._logger_name)

    # ------------------------------------------------------------------
    # App-level setup (called during aiohttp configure, NOT per-request)
    # ------------------------------------------------------------------

    @classmethod
    def setup(cls, app: WebApp, route: str = "/api/v1/google/generation/video_reel"):
        """Register routes and ensure JobManager is available."""
        _app = app.get_app() if hasattr(app, 'get_app') else app
        _app.router.add_view(route, cls)
        _app.router.add_view(f"{route}/{{job_id}}", cls)

    # ------------------------------------------------------------------
    # Per-request job_manager access
    # ------------------------------------------------------------------

    @property
    def job_manager(self) -> JobManager:
        """Resolve JobManager lazily from the request's app."""
        app = self.request.app
        if 'job_manager' in app:
            return app['job_manager']
        raise RuntimeError(
            "JobManager not configured. Call configure_job_manager(app) during startup."
        )

    # ------------------------------------------------------------------
    # HTTP methods
    # ------------------------------------------------------------------

    async def post(self) -> web.Response:
        """Submit a video reel generation job and return immediately."""
        try:
            data: dict[str, Any] = await self.request.json()
        except Exception:
            return self.error("Invalid JSON body.", status=400)

        # Extract control keys before Pydantic validation.
        model = data.pop("model", GoogleModel.GEMINI_3_FLASH_PREVIEW.value)
        output_directory: Optional[str] = data.pop("output_directory", None)
        user_id: Optional[str] = data.pop("user_id", None)
        session_id: Optional[str] = data.pop("session_id", None)

        try:
            req = VideoReelRequest(**data)
        except ValidationError as exc:
            return self.error(str(exc), status=400)

        output_path = Path(output_directory) if output_directory else None

        # Create a background job.
        job_id = str(uuid.uuid4())
        job = self.job_manager.create_job(
            job_id=job_id,
            obj_id="video_reel",
            query=req.prompt,
            user_id=user_id,
            session_id=session_id,
            execution_mode="video_reel",
        )

        # Capture validated request data for the background closure.
        async def run_logic():
            client = GoogleGenAIClient(model=model)
            async with client:
                result = await client.generate_video_reel(
                    request=req,
                    output_directory=output_path,
                    user_id=user_id,
                    session_id=session_id,
                )
                # Serialize AIMessage to dict for JSON-safe storage.
                if hasattr(result, 'model_dump'):
                    return result.model_dump()
                if hasattr(result, 'to_dict'):
                    return result.to_dict()
                return result

        # Fire background task — returns immediately.
        await self.job_manager.execute_job(job.job_id, run_logic)

        return self.json_response(
            {
                "job_id": job.job_id,
                "status": job.status.value,
                "message": "Video reel generation started",
                "created_at": job.created_at.isoformat(),
            },
            status=202,
        )

    async def get(self) -> web.Response:
        """Return job status/result when job_id is provided, otherwise the schema catalog."""
        job_id = self.request.match_info.get("job_id")

        if job_id:
            return self._get_job_status(job_id)

        # No job_id — return schema catalog (original behaviour).
        payload: dict[str, Any] = {
            "video_reel_request": VideoReelRequest.model_json_schema(),
            "video_reel_scene": VideoReelScene.model_json_schema(),
            "aspect_ratios": [r.value for r in AspectRatio],
            "music_genres": [g.value for g in MusicGenre],
            "music_moods": [m.value for m in MusicMood],
        }
        return self.json_response(payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_job_status(self, job_id: str) -> web.Response:
        """Build a response for the given job_id."""
        job = self.job_manager.get_job(job_id)
        if not job:
            return self.error(
                response={"message": f"Job '{job_id}' not found"},
                status=404,
            )

        response_data: dict[str, Any] = {
            "job_id": job.job_id,
            "status": job.status.value,
            "created_at": job.created_at.isoformat(),
        }

        if job.status == JobStatus.COMPLETED:
            response_data["result"] = job.result
            if job.completed_at:
                response_data["completed_at"] = job.completed_at.isoformat()
            if job.elapsed_time is not None:
                response_data["elapsed_time"] = job.elapsed_time

        elif job.status == JobStatus.FAILED:
            response_data["error"] = str(job.error)
            if job.completed_at:
                response_data["completed_at"] = job.completed_at.isoformat()

        elif job.status == JobStatus.RUNNING:
            if job.started_at:
                response_data["started_at"] = job.started_at.isoformat()
            if job.elapsed_time is not None:
                response_data["elapsed_time"] = job.elapsed_time

        return self.json_response(response_data)