"""HTTP handler for video reel generation with background job support."""

from __future__ import annotations

import json
import os
import re
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
from parrot.models.google import (
    AspectRatio,
    MusicGenre,
    MusicMood,
    VideoReelRequest,
    VideoReelScene,
)
from parrot.interfaces.file import FileManagerInterface
from parrot.tools.filemanager import FileManagerFactory
from .jobs import JobManager, JobStatus

# Matches an explicitly-indexed multipart image part name, e.g. "image_0", "image_12".
_IMAGE_INDEX_RE = re.compile(r"^image_(\d+)$")


class _RequestError(Exception):
    """Internal 4xx/413 signal raised while parsing/validating an incoming request.

    Carries the HTTP status the caller should see; always caught inside this
    module and converted to a real ``web.HTTPException`` — never leaks past
    ``post()``. ``max_size``/``actual_size`` are only meaningful for
    ``status=413`` (see ``VideoReelHandler._raise_request_error``).
    """

    def __init__(
        self,
        message: str,
        *,
        status: int = 400,
        max_size: Optional[int] = None,
        actual_size: Optional[int] = None,
    ) -> None:
        self.status = status
        self.max_size = max_size
        self.actual_size = actual_size
        super().__init__(message)


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
        _app = app.get_app() if hasattr(app, "get_app") else app
        _app.router.add_view(route, cls)
        _app.router.add_view(f"{route}/{{job_id}}", cls)

    # ------------------------------------------------------------------
    # Per-request job_manager access
    # ------------------------------------------------------------------

    @property
    def job_manager(self) -> JobManager:
        """Resolve JobManager lazily from the request's app."""
        app = self.request.app
        if "job_manager" in app:
            return app["job_manager"]
        raise RuntimeError("JobManager not configured. Call configure_job_manager(app) during startup.")

    # ------------------------------------------------------------------
    # Server-configurable upload bounds (read per-call so tests/ops can
    # override via environment without reloading this module).
    # ------------------------------------------------------------------

    @property
    def _max_scenes(self) -> int:
        """Maximum number of scenes/indexed image slots accepted per request."""
        return int(os.environ.get("VIDEO_REEL_MAX_SCENES", "20"))

    @property
    def _max_image_bytes(self) -> int:
        """Maximum size, in bytes, accepted for a single uploaded image part."""
        return int(os.environ.get("VIDEO_REEL_MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))

    @property
    def _max_total_upload_bytes(self) -> int:
        """Maximum combined size, in bytes, accepted across all uploaded image parts."""
        return int(os.environ.get("VIDEO_REEL_MAX_TOTAL_UPLOAD_BYTES", str(100 * 1024 * 1024)))

    # ------------------------------------------------------------------
    # Storage configuration
    # ------------------------------------------------------------------

    def _create_file_manager(self, output_directory: Optional[Path] = None) -> Optional[FileManagerInterface]:
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

    def _resolve_output_directory(self, output_directory: Optional[str]) -> Optional[Path]:
        """Validates a caller-supplied ``output_directory`` against storage escapes.

        Always rejects ``..`` path segments. When ``VIDEO_REEL_OUTPUT_ROOT`` is
        configured, additionally requires the resolved path to stay under that
        root — this is the only local-filesystem "ownership" boundary this
        contract supplies; no tenant/owner helper is invented here.

        Args:
            output_directory: The raw, caller-supplied path string, if any.

        Returns:
            A validated ``Path``, or ``None`` if no ``output_directory`` was given.

        Raises:
            _RequestError: If the path contains traversal segments or escapes
                the configured storage root.
        """
        if output_directory is None:
            return None
        candidate = Path(output_directory)
        if ".." in candidate.parts:
            raise _RequestError("output_directory must not contain '..' path segments.")
        root = os.environ.get("VIDEO_REEL_OUTPUT_ROOT")
        if root:
            root_path = Path(root).resolve()
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root_path):
                raise _RequestError("output_directory must be inside the configured storage root.")
            return resolved
        return candidate

    def _cleanup_tmp_dir(self, tmp_dir: Optional[Path]) -> None:
        """Removes the upload temp directory, if any, swallowing removal errors.

        Args:
            tmp_dir: The temp directory created by ``_parse_multipart`` for this
                request's uploaded images, or ``None`` if none was created.
        """
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def _raise_request_error(exc: _RequestError) -> None:
        """Converts a ``_RequestError`` into the correct real ``web.HTTPException``.

        ``BaseView.error()`` only maps a fixed status set (400/401/403/404/
        406/412/428) — any other status, including 413, silently falls
        through to ``HTTPBadRequest``. 413 therefore needs its own exception
        class raised directly; everything else goes through ``self.error()``.

        Args:
            exc: The internal error to convert.

        Raises:
            web.HTTPException: Always — this method never returns.
        """
        if exc.status == 413:
            raise web.HTTPRequestEntityTooLarge(
                max_size=exc.max_size or 0,
                actual_size=exc.actual_size or 0,
                text=str(exc),
            )
        raise web.HTTPBadRequest(text=str(exc))

    # ------------------------------------------------------------------
    # HTTP methods
    # ------------------------------------------------------------------

    async def _parse_multipart(self) -> tuple[dict, dict[int, Path]]:
        """Read multipart body: flat FormData fields + zero or more file parts.

        The frontend sends:
          - Scalar fields as individual FormData entries (string-coerced)
          - ``scenes``/``speech``/``storage_config`` as JSON strings
          - Reference images as either explicitly-indexed parts
            (``image_0``, ``image_1``, ...) or ordered parts
            (``reference_images``/``image``, one per part, index = arrival order)

        Backward compat: a single ``request`` JSON part is also accepted.

        Mixing indexed and ordered image addressing in the same request is
        rejected. Indexed slots preserve holes (an index with no uploaded
        image is simply absent from the returned mapping); ordered slots
        preserve holes from empty Blob placeholders the same way. Every saved
        file gets a unique on-disk name (index + random suffix + sanitized
        original name) so same-named uploads never collide.

        Per-image and total-upload byte bounds (`_max_image_bytes`,
        `_max_total_upload_bytes`) are enforced as each part is read, and the
        indexed/ordered slot count is bounded by `_max_scenes` — all before
        the full request has been consumed.

        Returns:
            Tuple of (parsed scalar-fields dict, ``{scene_index: image_path}``).

        Raises:
            _RequestError: On mixed addressing, duplicate/out-of-range
                indices, or a per-image/total upload size violation. Any
                temp directory created before the error is removed first.
        """
        reader = await self.request.multipart()
        data: dict = {}
        explicit_images: dict[int, Path] = {}
        ordered_images: list[Optional[Path]] = []
        tmp_dir: Optional[Path] = None
        total_bytes = 0

        def _ensure_tmp_dir() -> Path:
            nonlocal tmp_dir
            if tmp_dir is None:
                tmp_dir = Path(tempfile.mkdtemp(prefix="videoreel_upload_"))
            return tmp_dir

        try:
            async for part in reader:
                name = part.name or ""

                # Legacy: single JSON blob named "request"
                if name == "request":
                    raw = await part.read(decode=True)
                    data = json.loads(raw)
                    continue

                explicit_match = _IMAGE_INDEX_RE.match(name)
                is_ordered_image = name in ("reference_images", "image")

                if explicit_match or is_ordered_image:
                    if explicit_match and ordered_images:
                        raise _RequestError("Cannot mix indexed (image_<n>) and ordered image uploads in one request.")
                    if is_ordered_image and explicit_images:
                        raise _RequestError("Cannot mix indexed (image_<n>) and ordered image uploads in one request.")

                    raw_bytes = await part.read(decode=True)

                    # Skip empty Blob placeholders (0-byte, no real content), but
                    # still reserve their ordered slot so positions stay aligned.
                    if len(raw_bytes) == 0:
                        if is_ordered_image:
                            ordered_images.append(None)
                        continue

                    if len(raw_bytes) > self._max_image_bytes:
                        raise _RequestError(
                            f"Image part '{name}' exceeds the {self._max_image_bytes}-byte per-image limit.",
                            status=413,
                            max_size=self._max_image_bytes,
                            actual_size=len(raw_bytes),
                        )
                    total_bytes += len(raw_bytes)
                    if total_bytes > self._max_total_upload_bytes:
                        raise _RequestError(
                            f"Total upload size exceeds the {self._max_total_upload_bytes}-byte limit.",
                            status=413,
                            max_size=self._max_total_upload_bytes,
                            actual_size=total_bytes,
                        )

                    if explicit_match:
                        index = int(explicit_match.group(1))
                        if index < 0 or index >= self._max_scenes:
                            raise _RequestError(f"Image index {index} is out of range (0..{self._max_scenes - 1}).")
                        if index in explicit_images:
                            raise _RequestError(f"Duplicate image index {index}.")
                    else:
                        index = len(ordered_images)
                        if index >= self._max_scenes:
                            raise _RequestError(
                                f"Too many uploaded images (max {self._max_scenes}).",
                                status=413,
                                max_size=self._max_scenes,
                                actual_size=index + 1,
                            )

                    raw_name = part.filename or f"image_{index}.bin"
                    safe_name = Path(raw_name).name  # strip directory components
                    dest = _ensure_tmp_dir() / f"{index:04d}_{uuid.uuid4().hex[:8]}_{safe_name}"
                    dest.write_bytes(raw_bytes)

                    if explicit_match:
                        explicit_images[index] = dest
                    else:
                        ordered_images.append(dest)
                    continue

                # Scalar / JSON-encoded fields
                value = (await part.read(decode=True)).decode("utf-8")
                if name in ("scenes", "speech", "storage_config"):
                    try:
                        data[name] = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        data[name] = value
                else:
                    data[name] = value
        except Exception:
            self._cleanup_tmp_dir(tmp_dir)
            raise

        if explicit_images:
            images = dict(explicit_images)
        else:
            images = {i: p for i, p in enumerate(ordered_images) if p is not None}

        return data, images

    async def post(self) -> web.Response:
        """Submit a video reel generation job and return immediately."""
        content_type = self.request.content_type or ""
        images: dict[int, Path] = {}
        tmp_dir: Optional[Path] = None

        try:
            if "multipart" in content_type:
                data, images = await self._parse_multipart()
                if images:
                    tmp_dir = next(iter(images.values())).parent
            else:
                data = await self.request.json()
        except _RequestError as exc:
            self._raise_request_error(exc)
        except Exception as exc:
            self.logger.warning("Failed to parse request body: %s", exc)
            return self.error("Invalid request body.", status=400)

        if not isinstance(data, dict):
            self._cleanup_tmp_dir(tmp_dir)
            return self.error("Request body must be a JSON object.", status=400)

        # `reference_images` is populated exclusively by this handler from
        # uploaded images — a caller supplying it directly could point the
        # pipeline at an arbitrary local path (storage escape / LFI-style
        # abuse), so it is rejected outright rather than trusted.
        if "reference_images" in data:
            self._cleanup_tmp_dir(tmp_dir)
            return self.error(
                "`reference_images` is populated internally from uploaded images; "
                "do not supply it directly. Upload images via multipart/form-data instead.",
                status=400,
            )

        scenes_field = data.get("scenes")
        if isinstance(scenes_field, list) and len(scenes_field) > self._max_scenes:
            self._cleanup_tmp_dir(tmp_dir)
            self._raise_request_error(
                _RequestError(
                    f"At most {self._max_scenes} scenes are allowed.",
                    status=413,
                    max_size=self._max_scenes,
                    actual_size=len(scenes_field),
                )
            )

        # Extract control keys before Pydantic validation. `model` is
        # deliberately NOT popped here — it must reach VideoReelRequest so
        # the legacy-alias validator (conflict/blank/null checks) can run.
        output_directory: Optional[str] = data.pop("output_directory", None)
        user_id: Optional[str] = data.pop("user_id", None)
        session_id: Optional[str] = data.pop("session_id", None)

        if images:
            max_index = max(images)
            data["reference_images"] = [str(images[i]) if i in images else None for i in range(max_index + 1)]

        try:
            req = VideoReelRequest(**data)
        except ValidationError as exc:
            self._cleanup_tmp_dir(tmp_dir)
            return self.error(str(exc), status=400)

        try:
            output_path = self._resolve_output_directory(output_directory)
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
        except _RequestError as exc:
            self._cleanup_tmp_dir(tmp_dir)
            self._raise_request_error(exc)
        except Exception:
            self._cleanup_tmp_dir(tmp_dir)
            raise

        # Capture for closure.
        _tmp_dir = tmp_dir
        _file_manager = file_manager

        async def run_logic():
            try:
                # FEAT-523 (TASK-2846): lazy import — core must not import a
                # provider module at module scope (AC-3).
                from parrot.clients.google import GoogleGenAIClient

                client = GoogleGenAIClient(model=req.effective_director_model())
                async with client:
                    result = await client.generate_video_reel(
                        request=req,
                        output_directory=output_path,
                        file_manager=_file_manager,
                        user_id=user_id,
                        session_id=session_id,
                    )
                    # Serialize AIMessage to dict for JSON-safe storage.
                    if hasattr(result, "model_dump"):
                        return result.model_dump()
                    if hasattr(result, "to_dict"):
                        return result.to_dict()
                    return result
            finally:
                # Cleanup temp directory after job completes (success or failure).
                self._cleanup_tmp_dir(_tmp_dir)

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
