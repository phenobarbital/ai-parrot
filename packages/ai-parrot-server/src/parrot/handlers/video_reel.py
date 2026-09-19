"""HTTP handler for video reel generation with background job support."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING
from navconfig.logging import logging
import aiofiles
from aiohttp import web
from navigator.views import BaseView

if TYPE_CHECKING:
    from navigator.types import WebApp
    from .jobs.models import Job
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
        self.user_message = message
        self.status = status
        self.max_size = max_size
        self.actual_size = actual_size
        super().__init__(message)


class VideoReelHandler(BaseView):
    """REST handler for video reel generation using background jobs.

    Endpoints:
        POST /api/v1/google/generation/video_reel — Submit a video reel job (returns 202 + job_id).
        GET  /api/v1/google/generation/video_reel?job_id=<id> — Poll job status/result (owner-only).
        GET  /api/v1/google/generation/video_reel/{job_id}/artifacts/{artifact_id} — Deliver the
             final artifact (owner-only; streamed locally, redirected to a freshly-signed URL for
             cloud backends — never a raw local path in the HTTP result).
        GET  /api/v1/google/generation/video_reel — JSON Schema catalog (no job_id; unchanged, no
             ownership check applies — there is no job to own).

    Job ownership (§8 Q7) is resolved from the caller's SESSION via
    ``_resolve_session()``/``_get_session_user_id()`` — a body-supplied
    ``user_id`` is never trusted as an ownership claim (see ``post()``/
    ``_authorize_job()``). Deliberately NOT class-decorated
    ``@is_authenticated()``/``@user_session()`` (the pattern verified in
    ``CredentialsHandler``/``StudioBaseView`` during this task's evidence
    gate): ``@user_session()`` unconditionally calls
    ``navigator_session.get_session()`` with no test-friendly short
    circuit — unlike ``@is_authenticated()``'s documented
    ``request["authenticated"] = True`` bypass, it hard-requires real
    session-storage middleware to be configured, which this handler's
    existing test suites (``test_video_reel_handler.py``,
    ``test_video_reel_inputs.py``) do not set up. ``_resolve_session()``
    already implements the SAME "decorated or not" duality
    ``StudioBaseView`` documents (calling the plain, inherited
    ``BaseView.session()`` when nothing has overwritten it), and
    ``post()`` independently rejects an unresolvable session
    (``HTTPUnauthorized``) — so the class decorators add no additional
    security here, only a hard dependency on full session-storage setup
    this handler does not otherwise need.
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
        _app.router.add_view(f"{route}/{{job_id}}/artifacts/{{artifact_id}}", cls)

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

    def _create_file_manager(
        self, output_directory: Optional[Path] = None, *, backend: Optional[str] = None
    ) -> Optional[FileManagerInterface]:
        """Create a FileManagerInterface from server-side configuration.

        Reads storage settings from environment variables:
            VIDEO_REEL_STORAGE_BACKEND: "fs" | "temp" | "s3" | "gcs" (default: "fs")
            VIDEO_REEL_STORAGE_BUCKET: Bucket name for S3/GCS backends.
            VIDEO_REEL_STORAGE_PREFIX: Key prefix for S3/GCS backends.

        Args:
            output_directory: Local base path for the "fs" backend.
            backend: Explicit backend override — used when refreshing a
                signed URL for an already-completed job's recorded
                ``ReelArtifact.storage_backend`` (TASK-3333), which may
                differ from the CURRENT ``VIDEO_REEL_STORAGE_BACKEND`` env
                value if the deployment's default has since changed.
                Defaults to the env value when not given (unchanged
                behavior for the existing ``post()`` call site).

        Returns:
            A configured FileManagerInterface, or None to let the pipeline
            create one from ``VideoReelRequest.storage_backend``.
        """
        backend = backend or os.environ.get("VIDEO_REEL_STORAGE_BACKEND", "fs")
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
                text=exc.user_message,
            )
        raise web.HTTPBadRequest(text=exc.user_message)

    # ------------------------------------------------------------------
    # Session identity and job ownership (§8 Q7)
    #
    # Pattern verified against this deployment's existing conventions
    # before writing any of it (TASK-3333 evidence gate): CredentialsHandler
    # (credentials.py:57-59) and StudioBaseView (handlers/studio/_base.py)
    # both decorate `@is_authenticated() @user_session()` and resolve the
    # caller's identity from the session, never from the request body.
    # `BaseView.get_userid()` is defined directly on navigator's `BaseView`
    # (not an AbstractModel-only helper), so it applies here unchanged.
    # ------------------------------------------------------------------

    async def _resolve_session(self) -> Any:
        """Resolve the current session, decorated or not.

        ``@user_session()``'s wrapper overwrites ``self.session`` with the
        already-resolved session VALUE before the handler body runs; an
        undecorated/programmatic caller (a unit test instantiating the view
        directly) still sees the original callable ``BaseView.session``
        method — call it in that case. Mirrors ``StudioBaseView._resolve_session``.

        Returns:
            The resolved session (a dict/mapping), or a falsy value if none
            is available.
        """
        session_attr = self.session
        if callable(session_attr):
            return await session_attr()
        return session_attr

    async def _get_session_user_id(self) -> Optional[str]:
        """Resolve the authenticated caller's user id from the session.

        Never raises — a missing/unresolvable session or user id is
        reported as ``None``, letting callers decide what that means
        (``post()`` rejects it outright; ``_authorize_job()`` treats it as
        "cannot possibly own anything").

        Returns:
            The session's user id as a string, or ``None``.
        """
        try:
            session = await self._resolve_session()
        except Exception as exc:  # noqa: BLE001 - never let session resolution crash a request
            self.logger.debug("Session resolution failed: %s", exc)
            return None
        if not session:
            return None
        try:
            user_id = await self.get_userid(session)
        except web.HTTPException:
            return None
        return str(user_id) if user_id else None

    def _resolve_job_id(self) -> Optional[str]:
        """Resolve job_id from route ``match_info`` vs the ``?job_id=`` query string.

        Returns:
            The resolved job id, or ``None`` if neither source supplied one.

        Raises:
            web.HTTPBadRequest: Both sources supplied a job id and they disagree.
        """
        route_id = self.request.match_info.get("job_id")
        query_id = self.request.query.get("job_id")
        if route_id and query_id and route_id != query_id:
            raise web.HTTPBadRequest(text="Conflicting job_id between route and query string.")
        return route_id or query_id

    async def _authorize_job(self, job: "Job") -> None:
        """Requires the caller's session identity to own ``job``.

        Never trusts a body-supplied ``user_id`` as an ownership claim —
        only the session-resolved identity recorded on ``job.user_id`` at
        creation time (see ``post()``) counts. A job with no recorded
        owner (legacy/anonymous) is denied to everyone: fail-closed, not
        fail-open. Missing and unauthorized resources both raise the
        SAME non-disclosing 404 so a caller cannot distinguish "this job
        does not exist" from "this job exists but is not yours".

        Args:
            job: The job being accessed.

        Raises:
            web.HTTPNotFound: The caller does not own ``job``.
        """
        caller_id = await self._get_session_user_id()
        if not caller_id or not job.user_id or str(job.user_id) != str(caller_id):
            raise web.HTTPNotFound(text=f"Job '{job.job_id}' not found")

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
        #
        # `user_id` here is ONLY forwarded as AIMessage conversational
        # metadata (generate_video_reel's "reserved" user_id/session_id
        # params) — it is NEVER used as job ownership. Job ownership
        # (`job.user_id`, checked by `_authorize_job`) always comes from
        # the authenticated session below (§8 Q7: "Never trust body
        # user_id as ownership").
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

            # Job ownership comes from the authenticated session only —
            # never from the body's `user_id` (§8 Q7).
            owner_id = await self._get_session_user_id()
            if not owner_id:
                raise web.HTTPUnauthorized(reason="Authenticated session required to submit a video reel job.")

            # Create a background job.
            job_id = str(uuid.uuid4())
            job = self.job_manager.create_job(
                job_id=job_id,
                obj_id="video_reel",
                query=req.prompt,
                user_id=owner_id,
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
                    # Serialize AIMessage to a JSON-safe dict for storage
                    # (mode="json" so e.g. Path/datetime/enum fields come
                    # out as plain JSON-round-trippable values — TASK-3333).
                    if hasattr(result, "model_dump"):
                        return result.model_dump(mode="json")
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
        """Return job status/result, or a specific artifact, otherwise the schema catalog.

        ``job_id`` may come from the route or the ``?job_id=`` query string
        (``_resolve_job_id`` raises 400 if both are given and disagree).
        Schema-catalog behavior (no ``job_id`` at all) is unchanged and
        requires no ownership check — there is no job to own.
        """
        job_id = self._resolve_job_id()
        artifact_id = self.request.match_info.get("artifact_id")

        if job_id and artifact_id:
            return await self._get_artifact(job_id, artifact_id)

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
        Owner-checked (§8 Q7): missing and unauthorized jobs both surface
        the SAME non-disclosing 404 via ``_authorize_job``.

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

        await self._authorize_job(job)

        response_data: dict[str, Any] = {
            "job_id": job.job_id,
            "status": job.status.value,
            "created_at": job.created_at.isoformat(),
        }

        if job.status == JobStatus.COMPLETED:
            response_data["result"] = await self._refresh_result_urls(job.result)
            if job.completed_at:
                response_data["completed_at"] = job.completed_at.isoformat()
            if job.elapsed_time is not None:
                response_data["elapsed_time"] = job.elapsed_time

        elif job.status == JobStatus.FAILED:
            response_data["error"] = str(job.error)
            if job.completed_at:
                response_data["completed_at"] = job.completed_at.isoformat()

        elif job.status == JobStatus.CANCELLED:
            response_data["error"] = str(job.error) if job.error else "Job was cancelled"
            if job.completed_at:
                response_data["completed_at"] = job.completed_at.isoformat()

        elif job.status == JobStatus.RUNNING:
            if job.started_at:
                response_data["started_at"] = job.started_at.isoformat()
            if job.elapsed_time is not None:
                response_data["elapsed_time"] = job.elapsed_time

        return self.json_response(response_data)

    async def _refresh_result_urls(self, result: Any) -> Any:
        """Re-signs every cloud artifact's ``download_url`` from its stable ``storage_key``.

        Cloud (s3/gcs) signed URLs recorded at job-completion time can
        expire long before a caller polls or downloads them; the
        ``storage_key`` itself never changes, so a fresh URL is derived
        from it on every poll (spec: "Refresh cloud signed URLs from
        stable storage keys at polling/delivery"). Local ("fs"/"temp")
        artifacts are left untouched — their ``download_url`` is a
        non-expiring ``file://`` URI. The SAME refreshed URL is applied to
        both places the artifact is serialized (top-level ``artifacts[]``
        and ``metadata.video_reel.final_artifact``) so both stay
        consistent (AC10: byte-exact round trip). A refresh failure for
        one artifact is logged and that artifact's original URL is kept —
        it never fails the whole poll response.

        Args:
            result: The job's stored result (an ``AIMessage.model_dump()``
                dict), or anything else — passed through unchanged if it
                is not a dict with an ``artifacts`` list.

        Returns:
            ``result``, with any refreshable ``download_url`` fields updated.
        """
        if not isinstance(result, dict):
            return result
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, list):
            return result

        refreshed: dict[str, str] = {}
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            backend = artifact.get("storage_backend")
            storage_key = artifact.get("storage_key")
            artifact_id = artifact.get("artifact_id")
            if backend in ("fs", "temp") or not storage_key or not artifact_id:
                continue
            try:
                file_manager = self._create_file_manager(backend=backend)
                if file_manager is None:
                    continue
                refreshed[artifact_id] = await file_manager.get_file_url(storage_key)
            except Exception as exc:  # noqa: BLE001 - best-effort refresh, never fails the poll
                self.logger.warning("Failed to refresh signed URL for artifact %s: %s", artifact_id, exc)

        if not refreshed:
            return result

        for artifact in artifacts:
            if isinstance(artifact, dict) and artifact.get("artifact_id") in refreshed:
                artifact["download_url"] = refreshed[artifact["artifact_id"]]

        metadata = result.get("metadata")
        if isinstance(metadata, dict):
            video_reel = metadata.get("video_reel")
            if isinstance(video_reel, dict):
                final_artifact = video_reel.get("final_artifact")
                if isinstance(final_artifact, dict) and final_artifact.get("artifact_id") in refreshed:
                    final_artifact["download_url"] = refreshed[final_artifact["artifact_id"]]

        return result

    async def _get_artifact(self, job_id: str, artifact_id: str) -> web.StreamResponse:
        """Resolves ``ReelResult.final_artifact`` by id and delivers it.

        Owner-checked (§8 Q7) exactly like ``_get_job_status``. Local
        ("fs"/"temp") artifacts are streamed directly from disk — the raw
        local path never appears anywhere in the HTTP response, only the
        bytes. Cloud (s3/gcs) artifacts are delivered via a freshly-signed
        redirect (never the possibly-stale URL recorded at completion
        time).

        Args:
            job_id: The owning job's id.
            artifact_id: The artifact id to resolve (matched against
                ``job.result["artifacts"][*]["artifact_id"]`` — never a
                raw path or storage key supplied by the caller).

        Returns:
            A prepared ``web.StreamResponse`` (local delivery).

        Raises:
            web.HTTPNotFound: The job, its result, or the artifact are
                missing, the job is not owned by the caller, or the
                artifact's file/storage is no longer available.
            web.HTTPFound: Redirect to a freshly-signed cloud URL.
        """
        job = await self.job_manager.get_job_async(job_id)
        if not job:
            raise web.HTTPNotFound(text=f"Job '{job_id}' not found")

        await self._authorize_job(job)

        if job.status != JobStatus.COMPLETED or not isinstance(job.result, dict):
            raise web.HTTPNotFound(text=f"Artifact '{artifact_id}' not found for job '{job_id}'")

        artifacts = job.result.get("artifacts") or []
        artifact = next(
            (a for a in artifacts if isinstance(a, dict) and a.get("artifact_id") == artifact_id),
            None,
        )
        if artifact is None:
            raise web.HTTPNotFound(text=f"Artifact '{artifact_id}' not found for job '{job_id}'")

        storage_backend = artifact.get("storage_backend")
        mime_type = artifact.get("mime_type") or "application/octet-stream"

        if storage_backend in ("fs", "temp"):
            files = job.result.get("files") or []
            if not files:
                raise web.HTTPNotFound(text=f"Artifact '{artifact_id}' has no local file recorded.")
            local_path = Path(files[0])
            if not await asyncio.to_thread(local_path.exists):
                raise web.HTTPNotFound(text=f"Artifact '{artifact_id}' is no longer available.")
            return await self._stream_file(local_path, mime_type)

        storage_key = artifact.get("storage_key")
        if not storage_key:
            raise web.HTTPNotFound(text=f"Artifact '{artifact_id}' has no storage key recorded.")
        file_manager = self._create_file_manager(backend=storage_backend)
        if file_manager is None:
            raise web.HTTPNotFound(text="Cloud storage is not configured for artifact delivery.")
        fresh_url = await file_manager.get_file_url(storage_key)
        raise web.HTTPFound(location=fresh_url)

    async def _stream_file(
        self, file_path: Path, content_type: str, chunk_size: int = 256 * 1024
    ) -> web.StreamResponse:
        """Streams a local file chunk-by-chunk via ``aiofiles`` (never blocks the event loop).

        Args:
            file_path: The local file to stream.
            content_type: The MIME type to send.
            chunk_size: Bytes read per chunk.

        Returns:
            The prepared, fully-written ``web.StreamResponse``.
        """
        stream = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": content_type,
                "Content-Disposition": f'inline; filename="{file_path.name}"',
            },
        )
        await stream.prepare(self.request)
        async with aiofiles.open(file_path, "rb") as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                await stream.write(chunk)
        await stream.write_eof()
        return stream
