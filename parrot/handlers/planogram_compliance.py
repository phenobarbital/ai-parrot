"""HTTP handler for planogram compliance analysis with async job support."""
from __future__ import annotations

import asyncio
import base64
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING
import logging

from aiohttp import web
from navigator.views import BaseView

if TYPE_CHECKING:
    from navigator.types import WebApp

from parrot.clients.google import GoogleGenAIClient
from parrot.pipelines.models import PlanogramConfig, EndcapGeometry
from parrot.pipelines.planogram.plan import PlanogramCompliance
from .jobs import JobManager, JobStatus

# Maximum allowed upload size: 20 MB
MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB in bytes

# SSE polling interval in seconds
_SSE_POLL_INTERVAL = 1.0


class PlanogramComplianceHandler(BaseView):
    """REST handler for planogram compliance analysis with async job support.

    Endpoints:
        POST /api/v1/planogram/compliance
            Accept multipart form-data (image + config_name), resolve planogram
            configuration from Postgres, launch async compliance pipeline job,
            and return 202 with job_id.

        GET /api/v1/planogram/compliance/<job_id>
            Poll job status. On completion returns compliance results including
            a base64-encoded rendered overlay image.

        GET /api/v1/planogram/compliance/<job_id>/sse
            Server-Sent Events stream of job status updates until terminal state.
    """

    _logger_name = "Parrot.PlanogramComplianceHandler"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self._logger_name)

    # ------------------------------------------------------------------
    # App-level setup (called during aiohttp configure, NOT per-request)
    # ------------------------------------------------------------------

    @classmethod
    def setup(cls, app: "WebApp", route: str = "/api/v1/planogram/compliance") -> None:
        """Register routes and ensure JobManager is available.

        Args:
            app: The aiohttp web application (or navigator WebApp wrapper).
            route: Base URL path for the handler (default: /api/v1/planogram/compliance).
        """
        _app = app.get_app() if hasattr(app, "get_app") else app
        _app.router.add_view(route, cls)
        _app.router.add_view(f"{route}/{{job_id}}", cls)
        _app.router.add_view(f"{route}/{{job_id}}/sse", cls)

    # ------------------------------------------------------------------
    # Per-request job_manager access
    # ------------------------------------------------------------------

    @property
    def job_manager(self) -> JobManager:
        """Resolve JobManager lazily from the request's app.

        Returns:
            The application-level JobManager instance.

        Raises:
            RuntimeError: If JobManager has not been configured on the app.
        """
        app = self.request.app
        if "job_manager" in app:
            return app["job_manager"]
        raise RuntimeError(
            "JobManager not configured. Call configure_job_manager(app) during startup."
        )

    # ------------------------------------------------------------------
    # HTTP methods
    # ------------------------------------------------------------------

    async def post(self) -> web.Response:
        """Accept image + config_name, launch async compliance job, return 202.

        Parses multipart form-data with:
            - ``image``: JPEG/PNG file (max 20 MB)
            - ``config_name``: string name of the planogram configuration

        Queries ``troc.planograms_configurations`` for the named config, builds
        ``PlanogramConfig``, creates a background job, and fires the pipeline
        asynchronously.

        Returns:
            202 response with ``{ "job_id": "...", "status": "pending" }``.
            400 if image or config_name is missing/invalid.
            404 if config_name is not found in the database.
        """
        try:
            config_name, image_path, tmp_dir = await self._parse_multipart()
        except ValueError as exc:
            return self.error(str(exc), status=400)
        except Exception:
            self.logger.exception("Failed to parse multipart request")
            return self.error("Invalid multipart request body.", status=400)

        if not config_name:
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            return self.error("config_name is required.", status=400)

        if image_path is None:
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            return self.error("image file is required.", status=400)

        # Query planogram configuration from Postgres
        try:
            row = await self._fetch_planogram_config(config_name)
        except Exception:
            self.logger.exception("Database error fetching planogram config")
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            return self.error("Database error fetching planogram configuration.", status=500)

        if row is None:
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            return self.error(
                f"Planogram configuration '{config_name}' not found or inactive.",
                status=404,
            )

        # Hydrate PlanogramConfig
        try:
            config = self._build_planogram_config(row)
        except Exception:
            self.logger.exception("Failed to build PlanogramConfig from DB row")
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            return self.error("Failed to build planogram configuration.", status=500)

        # Create the background job
        job_id = str(uuid.uuid4())
        job = self.job_manager.create_job(
            job_id=job_id,
            obj_id="planogram_compliance",
            query=config_name,
            execution_mode="planogram_compliance",
        )

        # Capture variables for closure
        _tmp_dir = tmp_dir
        _image_path = image_path
        _config = config

        async def run_compliance() -> dict[str, Any]:
            """Execute the planogram compliance pipeline as a background task."""
            try:
                llm = GoogleGenAIClient(model="gemini-3-flash-preview")
                pipeline = PlanogramCompliance(planogram_config=_config, llm=llm)
                result = await pipeline.run(
                    image=_image_path,
                    output_dir=str(_tmp_dir),
                )

                # Base64-encode the rendered overlay image if available
                rendered_image_base64: Optional[str] = None
                content_type = "image/png"
                overlay_path = result.get("overlay_path")
                if overlay_path and Path(overlay_path).exists():
                    with open(overlay_path, "rb") as f:
                        rendered_image_base64 = base64.b64encode(f.read()).decode("utf-8")

                # Build serialisable result dict (avoid non-JSON objects)
                serialisable: dict[str, Any] = {
                    "overall_compliant": result.get("overall_compliant"),
                    "overall_compliance_score": result.get("overall_compliance_score"),
                    "rendered_image_base64": rendered_image_base64,
                    "content_type": content_type,
                }

                # Serialize shelf_results / compliance_results
                compliance_results = result.get("compliance_results", [])
                shelf_results = []
                for cr in compliance_results:
                    if hasattr(cr, "model_dump"):
                        shelf_results.append(cr.model_dump())
                    elif hasattr(cr, "to_dict"):
                        shelf_results.append(cr.to_dict())
                    elif isinstance(cr, dict):
                        shelf_results.append(cr)
                    else:
                        shelf_results.append(str(cr))
                serialisable["shelf_results"] = shelf_results

                return serialisable
            finally:
                # Always clean up temp directory
                if _tmp_dir and _tmp_dir.exists():
                    shutil.rmtree(_tmp_dir, ignore_errors=True)

        # Fire background task — returns immediately
        await self.job_manager.execute_job(job.job_id, run_compliance)

        return self.json_response(
            {
                "job_id": job.job_id,
                "status": job.status.value,
            },
            status=202,
        )

    async def get(self) -> web.Response:
        """Return job status/result or stream SSE events.

        The path ``/api/v1/planogram/compliance/<job_id>`` returns JSON with
        current job status and, on completion, the full compliance results.

        The path ``/api/v1/planogram/compliance/<job_id>/sse`` streams
        Server-Sent Events until the job reaches a terminal state.

        Returns:
            JSON response or SSE stream depending on the URL path.
        """
        job_id = self.request.match_info.get("job_id")
        if not job_id:
            return self.error("job_id is required.", status=400)

        # Check if this is an SSE request (path ends with /sse)
        path = self.request.path
        if path.endswith("/sse"):
            return await self._sse_stream(job_id)

        return self._get_job_status(job_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_job_status(self, job_id: str) -> web.Response:
        """Build a JSON response for the given job_id.

        Args:
            job_id: The job identifier to look up.

        Returns:
            JSON response with job status and optional result/error details.
        """
        job = self.job_manager.get_job(job_id)
        if not job:
            return self.error(
                response={"message": f"Job '{job_id}' not found."},
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

    async def _sse_stream(self, job_id: str) -> web.StreamResponse:
        """Stream Server-Sent Events for job status until terminal state.

        Polls the JobManager at regular intervals and emits SSE events with
        current job status until the job completes or fails.

        Args:
            job_id: The job identifier to watch.

        Returns:
            An aiohttp StreamResponse with ``text/event-stream`` content type.
        """
        response = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            }
        )
        await response.prepare(self.request)

        terminal_states = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

        try:
            while True:
                job = self.job_manager.get_job(job_id)
                if not job:
                    await response.write(
                        f"event: error\ndata: Job '{job_id}' not found.\n\n".encode()
                    )
                    break

                event_data = f'{{"job_id": "{job.job_id}", "status": "{job.status.value}"}}'
                await response.write(f"event: status\ndata: {event_data}\n\n".encode())

                if job.status in terminal_states:
                    break

                await asyncio.sleep(_SSE_POLL_INTERVAL)

        except asyncio.CancelledError:
            pass
        except Exception:
            self.logger.exception("SSE stream error for job %s", job_id)
        finally:
            await response.write_eof()

        return response

    async def _fetch_planogram_config(self, config_name: str) -> Optional[dict]:
        """Query troc.planograms_configurations for the given config_name.

        Args:
            config_name: The planogram configuration name to look up.

        Returns:
            A dict representing the DB row, or None if not found / inactive.
        """
        db = self.request.app["database"]
        async with await db.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT * FROM troc.planograms_configurations "
                "WHERE config_name = $1 AND is_active = TRUE LIMIT 1",
                config_name,
            )
        if result is None:
            return None
        return dict(result)

    def _build_planogram_config(self, row: dict) -> PlanogramConfig:
        """Hydrate a PlanogramConfig from a database row dict.

        Maps flat DB columns to ``PlanogramConfig`` and constructs nested
        ``EndcapGeometry`` from the geometry-related columns.

        Args:
            row: A dict representing a row from troc.planograms_configurations.

        Returns:
            A fully populated PlanogramConfig instance.
        """
        # Resolve reference image paths to Path objects
        reference_images_raw: dict = row.get("reference_images") or {}
        reference_images: dict[str, Path] = {
            name: Path(path_str)
            for name, path_str in reference_images_raw.items()
        }

        endcap_geometry = EndcapGeometry(
            aspect_ratio=row.get("aspect_ratio", 1.35),
            left_margin_ratio=row.get("left_margin_ratio", 0.01),
            right_margin_ratio=row.get("right_margin_ratio", 0.03),
            top_margin_ratio=row.get("top_margin_ratio", 0.02),
            bottom_margin_ratio=row.get("bottom_margin_ratio", 0.05),
            inter_shelf_padding=row.get("inter_shelf_padding", 0.02),
            width_margin_percent=row.get("width_margin_percent", 0.25),
            height_margin_percent=row.get("height_margin_percent", 0.30),
            top_margin_percent=row.get("top_margin_percent", 0.05),
            side_margin_percent=row.get("side_margin_percent", 0.05),
        )

        return PlanogramConfig(
            planogram_id=row.get("planogram_id"),
            config_name=row.get("config_name", ""),
            planogram_config=row.get("planogram_config") or {},
            roi_detection_prompt=row.get("roi_detection_prompt", ""),
            object_identification_prompt=row.get("object_identification_prompt", ""),
            reference_images=reference_images,
            confidence_threshold=row.get("confidence_threshold", 0.25),
            detection_model=row.get("detection_model", "yolo11l.pt"),
            endcap_geometry=endcap_geometry,
        )

    async def _parse_multipart(self) -> tuple[str, Optional[Path], Optional[Path]]:
        """Parse multipart form-data and extract config_name and image file.

        Reads the multipart body looking for:
            - ``config_name``: scalar text field
            - ``image``: binary file part (saved to a temp directory)

        Returns:
            A tuple of ``(config_name, image_path, tmp_dir)`` where
            ``image_path`` and ``tmp_dir`` may be None if no image was uploaded.

        Raises:
            ValueError: If the image exceeds the 20 MB maximum upload size.
        """
        reader = await self.request.multipart()
        config_name: str = ""
        image_path: Optional[Path] = None
        tmp_dir: Optional[Path] = None

        async for part in reader:
            name = part.name or ""

            if name == "config_name":
                value = (await part.read(decode=True)).decode("utf-8")
                config_name = value.strip()
                continue

            if name == "image":
                raw_bytes = await part.read(decode=True)
                if len(raw_bytes) > MAX_UPLOAD_SIZE:
                    raise ValueError(
                        f"Image exceeds maximum upload size of {MAX_UPLOAD_SIZE // (1024 * 1024)} MB."
                    )
                if len(raw_bytes) == 0:
                    continue
                filename = part.filename or "image.jpg"
                tmp_dir = Path(tempfile.mkdtemp(prefix="planogram_upload_"))
                image_path = tmp_dir / filename
                image_path.write_bytes(raw_bytes)
                continue

        return config_name, image_path, tmp_dir
