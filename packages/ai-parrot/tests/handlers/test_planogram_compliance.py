"""Tests for PlanogramComplianceHandler — planogram compliance REST endpoint."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.handlers.planogram_compliance import PlanogramComplianceHandler
from parrot.handlers.jobs.models import Job, JobStatus
from parrot.handlers.jobs.job import JobManager
from parrot.pipelines.models import PlanogramConfig, EndcapGeometry

# ---------------------------------------------------------------------------
# Helpers — minimal JPEG bytes (valid 1×1 JPEG)
# ---------------------------------------------------------------------------

def _make_jpeg_bytes() -> bytes:
    """Return minimal valid JPEG image bytes (1x1 white pixel)."""
    try:
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (1, 1), color=(255, 255, 255)).save(buf, format="JPEG")
        return buf.getvalue()
    except ImportError:
        # Raw 1×1 JPEG bytes (RFC-compliant minimal JPEG)
        return (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
            b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
            b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
            b"C  C\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4"
            b"\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4"
            b"\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00"
            b"\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07\"q\x142"
            b"\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18"
            b"\x19\x1a%&'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85"
            b"\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3"
            b"\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba"
            b"\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8"
            b"\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4"
            b"\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb"
            b"\xd2P\x00\x00\x00\x1f\xff\xd9"
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def planogram_db_row() -> dict:
    """Sample DB row matching troc.planograms_configurations schema."""
    return {
        "planogram_id": 1,
        "config_name": "BOSE S1 Pro+ Planogram",
        "planogram_config": {"brand": "Bose", "category": "Speakers", "shelves": []},
        "roi_detection_prompt": "Analyze the Bose display...",
        "object_identification_prompt": "Identify the speaker...",
        "reference_images": {"S1 Pro+": "/tmp/test_ref.jpg"},
        "confidence_threshold": 0.25,
        "detection_model": "yolo11l.pt",
        "aspect_ratio": 1.35,
        "left_margin_ratio": 0.01,
        "right_margin_ratio": 0.03,
        "top_margin_ratio": 0.02,
        "bottom_margin_ratio": 0.05,
        "inter_shelf_padding": 0.02,
        "width_margin_percent": 0.25,
        "height_margin_percent": 0.30,
        "top_margin_percent": 0.05,
        "side_margin_percent": 0.05,
        "is_active": True,
    }


@pytest.fixture
def job_manager() -> JobManager:
    """Real in-memory JobManager instance."""
    return JobManager(id="test")


def _make_handler(
    job_manager: JobManager,
    db_row: Optional[dict] = None,
    match_info: Optional[dict] = None,
) -> PlanogramComplianceHandler:
    """Build a PlanogramComplianceHandler with mocked request and app."""
    handler = object.__new__(PlanogramComplianceHandler)
    handler.logger = MagicMock()

    # Build mock app
    mock_app: dict[str, Any] = {"job_manager": job_manager}

    # Build mock DB connection
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=db_row)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_db = MagicMock()
    mock_db.acquire = AsyncMock(return_value=mock_conn)
    mock_app["database"] = mock_db

    # Build mock request
    mock_request = MagicMock()
    mock_request.app = mock_app
    mock_request.match_info = match_info or {}
    mock_request.path = "/api/v1/planogram/compliance"

    handler.request = mock_request

    # Wire json_response and error helpers (mirror aiohttp BaseView pattern)
    def _json_response(data: dict, status: int = 200) -> MagicMock:
        resp = MagicMock()
        resp.status = status
        resp._body = json.dumps(data)
        resp.data = data
        return resp

    def _error(response=None, status: int = 400, **kwargs) -> MagicMock:
        if isinstance(response, str):
            body = {"message": response}
        elif isinstance(response, dict):
            body = response
        else:
            body = {}
        resp = MagicMock()
        resp.status = status
        resp._body = json.dumps(body)
        resp.data = body
        return resp

    handler.json_response = _json_response
    handler.error = _error

    return handler


# ---------------------------------------------------------------------------
# Multipart reader mocks
# ---------------------------------------------------------------------------


class _MockPart:
    """Simulates an aiohttp multipart part."""

    def __init__(self, name: str, data: bytes, filename: Optional[str] = None):
        self.name = name
        self._data = data
        self.filename = filename

    async def read(self, decode: bool = True) -> bytes:
        return self._data


class _MockMultipartReader:
    """Simulates an async multipart reader."""

    def __init__(self, parts: list[_MockPart]):
        self._parts = parts
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self) -> _MockPart:
        if self._idx >= len(self._parts):
            raise StopAsyncIteration
        part = self._parts[self._idx]
        self._idx += 1
        return part


# ---------------------------------------------------------------------------
# Unit Tests — POST
# ---------------------------------------------------------------------------


class TestPostEndpoint:
    """Tests for POST /api/v1/planogram/compliance."""

    @pytest.mark.asyncio
    async def test_post_valid_request(self, planogram_db_row, job_manager):
        """POST with valid image + config_name returns 202 with job_id."""
        handler = _make_handler(job_manager, db_row=planogram_db_row)
        jpeg = _make_jpeg_bytes()

        parts = [
            _MockPart("config_name", b"BOSE S1 Pro+ Planogram"),
            _MockPart("image", jpeg, filename="store.jpg"),
        ]
        handler.request.multipart = AsyncMock(
            return_value=_MockMultipartReader(parts)
        )

        with (
            patch(
                "parrot.handlers.planogram_compliance.GoogleGenAIClient",
                MagicMock(),
            ),
            patch(
                "parrot.handlers.planogram_compliance.PlanogramCompliance",
                MagicMock(),
            ),
        ):
            response = await handler.post()

        assert response.status == 202
        data = response.data
        assert "job_id" in data
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_post_missing_image(self, planogram_db_row, job_manager):
        """POST without image returns 400."""
        handler = _make_handler(job_manager, db_row=planogram_db_row)

        parts = [
            _MockPart("config_name", b"BOSE S1 Pro+ Planogram"),
            # No image part
        ]
        handler.request.multipart = AsyncMock(
            return_value=_MockMultipartReader(parts)
        )

        response = await handler.post()
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_post_missing_config_name(self, planogram_db_row, job_manager):
        """POST without config_name returns 400."""
        handler = _make_handler(job_manager, db_row=planogram_db_row)
        jpeg = _make_jpeg_bytes()

        parts = [
            # No config_name part
            _MockPart("image", jpeg, filename="store.jpg"),
        ]
        handler.request.multipart = AsyncMock(
            return_value=_MockMultipartReader(parts)
        )

        response = await handler.post()
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_post_unknown_config(self, job_manager):
        """POST with non-existent config_name returns 404."""
        handler = _make_handler(job_manager, db_row=None)  # DB returns None
        jpeg = _make_jpeg_bytes()

        parts = [
            _MockPart("config_name", b"NonExistentConfig"),
            _MockPart("image", jpeg, filename="store.jpg"),
        ]
        handler.request.multipart = AsyncMock(
            return_value=_MockMultipartReader(parts)
        )

        response = await handler.post()
        assert response.status == 404

    @pytest.mark.asyncio
    async def test_post_inactive_config(self, job_manager):
        """POST with inactive planogram config returns 404 (filtered by query)."""
        # The DB query filters is_active=TRUE, so inactive configs return None
        handler = _make_handler(job_manager, db_row=None)
        jpeg = _make_jpeg_bytes()

        parts = [
            _MockPart("config_name", b"InactiveConfig"),
            _MockPart("image", jpeg, filename="store.jpg"),
        ]
        handler.request.multipart = AsyncMock(
            return_value=_MockMultipartReader(parts)
        )

        response = await handler.post()
        assert response.status == 404


# ---------------------------------------------------------------------------
# Unit Tests — GET
# ---------------------------------------------------------------------------


class TestGetEndpoint:
    """Tests for GET /api/v1/planogram/compliance/<job_id>."""

    @pytest.mark.asyncio
    async def test_get_pending_job(self, job_manager):
        """GET with valid job_id in PENDING state returns status."""
        job_id = str(uuid.uuid4())
        job_manager.create_job(
            job_id=job_id,
            obj_id="planogram_compliance",
            query="BOSE S1 Pro+ Planogram",
        )

        handler = _make_handler(job_manager, match_info={"job_id": job_id})
        handler.request.path = f"/api/v1/planogram/compliance/{job_id}"

        response = await handler.get()
        assert response.status == 200
        assert response.data["job_id"] == job_id
        assert response.data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_completed_job(self, job_manager):
        """GET completed job returns results with base64 image."""
        job_id = str(uuid.uuid4())
        job = job_manager.create_job(
            job_id=job_id,
            obj_id="planogram_compliance",
            query="BOSE S1 Pro+ Planogram",
        )

        # Simulate completed state
        job.status = JobStatus.COMPLETED
        job.result = {
            "overall_compliant": True,
            "overall_compliance_score": 0.95,
            "shelf_results": [],
            "rendered_image_base64": base64.b64encode(b"fake_png").decode(),
            "content_type": "image/png",
        }

        handler = _make_handler(job_manager, match_info={"job_id": job_id})
        handler.request.path = f"/api/v1/planogram/compliance/{job_id}"

        response = await handler.get()
        assert response.status == 200
        data = response.data
        assert data["status"] == "completed"
        assert "result" in data
        assert data["result"]["overall_compliant"] is True
        assert data["result"]["rendered_image_base64"] is not None

    @pytest.mark.asyncio
    async def test_get_failed_job(self, job_manager):
        """GET failed job returns error message."""
        job_id = str(uuid.uuid4())
        job = job_manager.create_job(
            job_id=job_id,
            obj_id="planogram_compliance",
            query="BOSE S1 Pro+ Planogram",
        )
        job.status = JobStatus.FAILED
        job.error = "Pipeline execution failed: YOLO model not found"

        handler = _make_handler(job_manager, match_info={"job_id": job_id})
        handler.request.path = f"/api/v1/planogram/compliance/{job_id}"

        response = await handler.get()
        assert response.status == 200
        data = response.data
        assert data["status"] == "failed"
        assert "error" in data
        assert "YOLO" in data["error"]

    @pytest.mark.asyncio
    async def test_get_unknown_job(self, job_manager):
        """GET with non-existent job_id returns 404."""
        unknown_id = str(uuid.uuid4())
        handler = _make_handler(job_manager, match_info={"job_id": unknown_id})
        handler.request.path = f"/api/v1/planogram/compliance/{unknown_id}"

        response = await handler.get()
        assert response.status == 404


# ---------------------------------------------------------------------------
# Unit Tests — _build_planogram_config
# ---------------------------------------------------------------------------


class TestBuildPlanogramConfig:
    """Tests for _build_planogram_config helper."""

    def test_build_planogram_config(self, planogram_db_row, job_manager):
        """DB row correctly hydrated into PlanogramConfig with EndcapGeometry."""
        handler = _make_handler(job_manager)
        config = handler._build_planogram_config(planogram_db_row)

        assert isinstance(config, PlanogramConfig)
        assert config.config_name == "BOSE S1 Pro+ Planogram"
        assert config.confidence_threshold == 0.25
        assert config.detection_model == "yolo11l.pt"
        assert config.roi_detection_prompt == "Analyze the Bose display..."
        assert config.object_identification_prompt == "Identify the speaker..."

        # Reference images resolved to Path objects
        assert isinstance(config.reference_images["S1 Pro+"], Path)
        assert str(config.reference_images["S1 Pro+"]) == "/tmp/test_ref.jpg"

        # EndcapGeometry hydrated from flat columns
        geom = config.endcap_geometry
        assert isinstance(geom, EndcapGeometry)
        assert geom.aspect_ratio == 1.35
        assert geom.left_margin_ratio == 0.01
        assert geom.right_margin_ratio == 0.03
        assert geom.top_margin_ratio == 0.02
        assert geom.bottom_margin_ratio == 0.05
        assert geom.inter_shelf_padding == 0.02
        assert geom.width_margin_percent == 0.25
        assert geom.height_margin_percent == 0.30
        assert geom.top_margin_percent == 0.05
        assert geom.side_margin_percent == 0.05

    def test_build_planogram_config_defaults(self, job_manager):
        """Missing optional columns use safe defaults."""
        minimal_row = {
            "config_name": "Minimal Config",
            "planogram_config": {},
            "roi_detection_prompt": "Find ROI",
            "object_identification_prompt": "Identify objects",
        }
        handler = _make_handler(job_manager)
        config = handler._build_planogram_config(minimal_row)

        assert config.confidence_threshold == 0.25
        assert config.detection_model == "yolo11l.pt"
        assert config.reference_images == {}
        assert config.endcap_geometry.aspect_ratio == 1.35


# ---------------------------------------------------------------------------
# Integration Test — end-to-end with mocked pipeline + DB
# ---------------------------------------------------------------------------


class TestEndToEndCompliance:
    """Integration test: POST → poll GET → completed result."""

    @pytest.mark.asyncio
    async def test_end_to_end_compliance(self, planogram_db_row, job_manager):
        """POST image → poll GET → receive completed result (mocked pipeline + DB)."""
        handler = _make_handler(job_manager, db_row=planogram_db_row)
        jpeg = _make_jpeg_bytes()

        parts = [
            _MockPart("config_name", b"BOSE S1 Pro+ Planogram"),
            _MockPart("image", jpeg, filename="store.jpg"),
        ]
        handler.request.multipart = AsyncMock(
            return_value=_MockMultipartReader(parts)
        )

        # Create a small PNG for the overlay
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as overlay_f:
            overlay_path = overlay_f.name
            overlay_f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

        fake_result = {
            "overall_compliant": True,
            "overall_compliance_score": 0.88,
            "compliance_results": [],
            "shelf_regions": [],
            "overlay_path": overlay_path,
            "rendered_image": None,
        }

        mock_pipeline_instance = AsyncMock()
        mock_pipeline_instance.run = AsyncMock(return_value=fake_result)
        mock_pipeline_class = MagicMock(return_value=mock_pipeline_instance)

        mock_llm_instance = MagicMock()
        mock_llm_class = MagicMock(return_value=mock_llm_instance)

        # Use patch.start/stop so mocks persist for the background asyncio task
        p1 = patch(
            "parrot.handlers.planogram_compliance.GoogleGenAIClient",
            mock_llm_class,
        )
        p2 = patch(
            "parrot.handlers.planogram_compliance.PlanogramCompliance",
            mock_pipeline_class,
        )
        p1.start()
        p2.start()
        try:
            post_response = await handler.post()

            assert post_response.status == 202
            job_id = post_response.data["job_id"]

            # Wait for background job to complete (short poll)
            for _ in range(20):
                job = job_manager.get_job(job_id)
                if job and job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                    break
                await asyncio.sleep(0.1)
        finally:
            p1.stop()
            p2.stop()

        assert job is not None
        assert job.status == JobStatus.COMPLETED, f"Job failed: {job.error}"

        # Now GET the job
        handler2 = _make_handler(job_manager, match_info={"job_id": job_id})
        handler2.request.path = f"/api/v1/planogram/compliance/{job_id}"

        get_response = handler2._get_job_status(job_id)
        assert get_response.status == 200
        result_data = get_response.data
        assert result_data["status"] == "completed"
        assert result_data["result"]["overall_compliant"] is True
        assert result_data["result"]["overall_compliance_score"] == pytest.approx(0.88)
        # Base64 image present
        assert result_data["result"]["rendered_image_base64"] is not None
        # Verify base64 decodes successfully
        decoded = base64.b64decode(result_data["result"]["rendered_image_base64"])
        assert len(decoded) > 0

        # Cleanup overlay
        Path(overlay_path).unlink(missing_ok=True)
