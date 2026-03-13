"""HTTP handler for video reel generation with background job support."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING
from navconfig.logging import logging
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
from parrot.tools.file import FileManagerInterface
from parrot.tools.file.tool import FileManagerFactory
from .jobs import JobManager, JobStatus


class VideoReelHandler(BaseView):
    """REST handler for video reel generation using background jobs.

    Endpoints:
        POST /api/v1/google/generation/video_reel — Submit a video reel job (returns 202 + job_id).
        GET  /api/v1/google/generation/video_reel?job_id=<id> — Poll job status/result.
        GET  /api/v1/google/generation/video_reel — JSON Schema catalog (no job_id).
    """

    _logger_name = "Parrot.VideoReelHandler"
    _app: WebApp

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
    # Storage configuration
    # ------------------------------------------------------------------

    def _create_file_manager(
        self, output_directory: Optional[Path] = None
    ) -> Optional[FileManagerInterface]:
        """Create a FileManagerInterface from server-side configuration.

        Reads storage settings from environment variables:
            VIDEO_REEL_STORAGE_BACKEND: "fs" | "temp" | "s3" | "gcs" (default: "fs")
            VIDEO_REEL_STORAGE_BUCKET: Bucket name for S3/GCS backends.
            VIDEO_REEL_STORAGE_PREFIX: Key prefix for S3/GCS backends.

        Returns:
            A configured FileManagerInterface, or None to let the pipeline
            create one from ``VideoReelRequest.storage_backend``.
        """
        backend = os.environ.get("VIDEO_REEL_STORAGE_BACKEND", "fs")
        bucket = os.environ.get("VIDEO_REEL_STORAGE_BUCKET")
        prefix = os.environ.get("VIDEO_REEL_STORAGE_PREFIX", "")

        if backend == "fs":
            env_dir = os.environ.get("VIDEO_REEL_OUTPUT_DIR")
            base_path = output_directory or (Path(env_dir) if env_dir else None)
            if base_path is None:
                # Let the pipeline use its own default path.
                return None
            return FileManagerFactory.create("fs", base_path=base_path)

        if backend == "temp":
            return FileManagerFactory.create("temp")

        # Cloud backends (s3 / gcs)
        if not bucket:
            self.logger.warning(
                "VIDEO_REEL_STORAGE_BACKEND=%s but no VIDEO_REEL_STORAGE_BUCKET set. "
                "Falling back to local filesystem.",
                backend,
            )
            return None

        kwargs: dict[str, Any] = {"bucket_name": bucket}
        if prefix:
            kwargs["prefix"] = prefix
        return FileManagerFactory.create(backend, **kwargs)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # HTTP methods
    # ------------------------------------------------------------------

    async def _parse_multipart(self) -> tuple[dict, list[Path]]:
        """Read multipart body: flat FormData fields + zero or more file parts.

        The frontend sends:
          - Scalar fields as individual FormData entries (string-coerced)
          - ``scenes`` as a JSON string
          - ``speech`` as a JSON string
          - ``reference_images`` as File/Blob parts (one per image, in order)

        Backward compat: a single ``request`` JSON part is also accepted.

        Returns:
            Tuple of (parsed data dict, list of saved image Paths in order).
        """
        reader = await self.request.multipart()
        data: dict = {}
        image_parts: list[tuple[str, Path]] = []  # (part_name_or_index, path)
        tmp_dir = Path(tempfile.mkdtemp(prefix="videoreel_upload_"))
        img_counter = 0

        async for part in reader:
            name = part.name or ""

            # Legacy: single JSON blob named "request"
            if name == "request":
                raw = await part.read(decode=True)
                data = json.loads(raw)
                continue

            # File parts: reference_images or image_*
            if name == "reference_images" or name.startswith("image"):
                raw_bytes = await part.read(decode=True)
                # Skip empty Blob placeholders (0-byte, no filename)
                if len(raw_bytes) == 0:
                    img_counter += 1
                    continue
                raw_name = part.filename or f"image_{img_counter}.bin"
                filename = Path(raw_name).name  # strip directory components
                dest = tmp_dir / filename
                dest.write_bytes(raw_bytes)
                image_parts.append((f"img_{img_counter:04d}", dest))
                img_counter += 1
                continue

            # Scalar / JSON-encoded fields
            value = (await part.read(decode=True)).decode("utf-8")

            if name in ("scenes", "speech"):
                try:
                    data[name] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    data[name] = value
            else:
                data[name] = value

        # Sort image parts by index to preserve order
        image_parts.sort(key=lambda x: x[0])
        image_paths = [p for _, p in image_parts]
        return data, image_paths

    async def post(self) -> web.Response:
        """Submit a video reel generation job and return immediately."""
        content_type = self.request.content_type or ""
        image_paths: list[Path] = []
        tmp_dir: Optional[Path] = None

        try:
            if "multipart" in content_type:
                data, image_paths = await self._parse_multipart()
                if image_paths:
                    tmp_dir = image_paths[0].parent
            else:
                data = await self.request.json()
        except Exception as exc:
            self.logger.warning("Failed to parse request body: %s", exc)
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            return self.error("Invalid request body.", status=400)

        # Extract control keys before Pydantic validation.
        model = data.pop("model", GoogleModel.GEMINI_3_FLASH_PREVIEW.value)
        output_directory: Optional[str] = data.pop("output_directory", None)
        user_id: Optional[str] = data.pop("user_id", None)
        session_id: Optional[str] = data.pop("session_id", None)

        try:
            req = VideoReelRequest(**data)
        except ValidationError as exc:
            return self.error(str(exc), status=400)

        if image_paths:
            req.reference_images = [str(p) for p in image_paths]

        output_path = Path(output_directory) if output_directory else None

        # Resolve storage backend from server-side config.
        file_manager = self._create_file_manager(output_directory=output_path)

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

        # Capture for closure.
        _tmp_dir = tmp_dir
        _file_manager = file_manager

        async def run_logic():
            try:
                client = GoogleGenAIClient(model=model)
                async with client:
                    result = await client.generate_video_reel(
                        request=req,
                        output_directory=output_path,
                        file_manager=_file_manager,
                        user_id=user_id,
                        session_id=session_id,
                    )
                    # Serialize AIMessage to dict for JSON-safe storage.
                    if hasattr(result, 'model_dump'):
                        return result.model_dump()
                    if hasattr(result, 'to_dict'):
                        return result.to_dict()
                    return result
            finally:
                # Cleanup temp directory after job completes (success or failure).
                if _tmp_dir and _tmp_dir.exists():
                    shutil.rmtree(_tmp_dir, ignore_errors=True)

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
            return await self._get_job_status(job_id)

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

    async def _get_job_status(self, job_id: str) -> web.Response:
        """Build a response for the given job_id.

        Uses ``get_job_async()`` so that jobs persisted in Redis (but no
        longer in the in-memory dict after a restart) can still be retrieved.

        Args:
            job_id: The job identifier to look up.

        Returns:
            JSON response with job state details.
        """
        job = await self.job_manager.get_job_async(job_id)
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