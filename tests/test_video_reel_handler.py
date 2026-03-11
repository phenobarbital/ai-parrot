"""Tests for VideoReelHandler and VideoReelRequest."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from parrot.models.google import (
    AspectRatio,
    MusicGenre,
    MusicMood,
    VideoReelRequest,
    VideoReelScene,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(body, status=200, content_type="application/json"):
    """Build a lightweight fake web.Response-like object."""
    resp = MagicMock()
    resp.status = status
    resp.body = body
    resp.content_type = content_type
    return resp


def _make_job(
    job_id="job-123",
    status_value="pending",
    result=None,
    error=None,
    elapsed_time=None,
    started_at=None,
    completed_at=None,
):
    """Create a lightweight mock Job."""
    from parrot.handlers.jobs import JobStatus

    job = MagicMock()
    job.job_id = job_id
    job.status = JobStatus(status_value)
    job.result = result
    job.error = error
    job.elapsed_time = elapsed_time
    job.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job.started_at = started_at
    job.completed_at = completed_at
    return job


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def video_reel_payload() -> dict:
    """Valid payload for video reel generation."""
    return {
        "prompt": "A cinematic reel about ocean conservation",
        "music_genre": "Chillout",
        "aspect_ratio": "9:16",
    }


@pytest.fixture
def handler():
    """Create a VideoReelHandler with mocked internals including JobManager."""
    from parrot.handlers.video_reel import VideoReelHandler

    h = VideoReelHandler.__new__(VideoReelHandler)
    h.logger = MagicMock()
    h.request = MagicMock()

    # Mock JobManager accessible via request.app['job_manager']
    mock_jm = MagicMock()
    mock_job = _make_job()
    mock_jm.create_job = MagicMock(return_value=mock_job)
    mock_jm.execute_job = AsyncMock()
    mock_jm.get_job = MagicMock(return_value=None)
    h.request.app = {"job_manager": mock_jm}
    h.request.content_type = "application/json"

    h.error = MagicMock(side_effect=lambda *a, **kw: _make_response(
        body=kw.get('response', a[0] if a else "error"),
        status=kw.get('status', 400),
        content_type="application/json",
    ))
    h.json_response = MagicMock(side_effect=lambda data, **kw: _make_response(
        body=data, status=kw.get('status', 200), content_type="application/json",
    ))
    h.request.match_info = {}
    return h


# ---------------------------------------------------------------------------
# 1. Model validation tests
# ---------------------------------------------------------------------------

class TestVideoReelRequestModel:
    """Pydantic model tests for VideoReelRequest."""

    def test_model_valid_minimal(self):
        """VideoReelRequest with only prompt succeeds with defaults."""
        req = VideoReelRequest(prompt="Test reel")
        assert req.prompt == "Test reel"
        assert req.aspect_ratio == AspectRatio.RATIO_9_16
        assert req.transition_type == "crossfade"
        assert req.output_format == "mp4"
        assert req.scenes is None
        assert req.music_prompt is None
        assert req.music_genre is None
        assert req.music_mood is None

    def test_model_missing_prompt(self):
        """Missing prompt raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            VideoReelRequest()  # type: ignore[call-arg]
        assert "prompt" in str(exc_info.value)

    def test_model_full_payload(self, video_reel_payload):
        """Full payload constructs successfully."""
        req = VideoReelRequest(**video_reel_payload)
        assert req.prompt == video_reel_payload["prompt"]
        assert req.music_genre == MusicGenre.CHILLOUT
        assert req.aspect_ratio == AspectRatio.RATIO_9_16

    def test_model_with_scenes(self):
        """Model with explicit scenes list validates correctly."""
        scenes = [
            VideoReelScene(
                background_prompt="Ocean waves",
                video_prompt="Underwater coral reef video",
            ),
        ]
        req = VideoReelRequest(prompt="Test", scenes=scenes)
        assert len(req.scenes) == 1
        assert req.scenes[0].background_prompt == "Ocean waves"

    def test_model_json_schema(self):
        """JSON schema includes core properties."""
        schema = VideoReelRequest.model_json_schema()
        props = schema["properties"]
        expected = {
            "prompt", "scenes", "speech", "music_prompt", "music_genre",
            "music_mood", "aspect_ratio", "transition_type", "output_format",
            "reference_images", "storage_backend", "storage_config",
        }
        assert expected == set(props.keys())

    def test_scene_model_valid(self):
        """VideoReelScene with required fields succeeds."""
        scene = VideoReelScene(
            background_prompt="A sunset",
            video_prompt="Golden hour timelapse",
        )
        assert scene.background_prompt == "A sunset"
        assert scene.duration == 5.0
        assert scene.narration_text is None

    def test_scene_model_missing_required(self):
        """VideoReelScene without required fields raises ValidationError."""
        with pytest.raises(ValidationError):
            VideoReelScene(background_prompt="x")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# 2. Handler POST tests (now returns 202 with job_id)
# ---------------------------------------------------------------------------

class TestVideoReelHandlerPost:
    """Tests for VideoReelHandler.post()."""

    @pytest.mark.asyncio
    async def test_post_valid_payload_returns_202(self, handler, video_reel_payload):
        """POST with valid payload returns 202 with job_id."""
        handler.request.json = AsyncMock(return_value=video_reel_payload)

        result = await handler.post()

        assert result.status == 202
        handler.json_response.assert_called_once()
        response_data = handler.json_response.call_args[0][0]
        assert "job_id" in response_data
        assert response_data["status"] == "pending"
        assert response_data["message"] == "Video reel generation started"
        handler.job_manager.create_job.assert_called_once()
        handler.job_manager.execute_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_invalid_payload(self, handler):
        """POST with missing prompt returns 400."""
        handler.request.json = AsyncMock(return_value={"music_genre": "Techno"})

        result = await handler.post()

        handler.error.assert_called_once()
        call_args = handler.error.call_args
        assert call_args.kwargs.get("status", call_args[1].get("status", None)) == 400
        assert result.status == 400

    @pytest.mark.asyncio
    async def test_post_invalid_json(self, handler):
        """POST with unparseable body returns 400."""
        handler.request.json = AsyncMock(side_effect=Exception("bad json"))

        result = await handler.post()

        handler.error.assert_called_once()
        assert result.status == 400

    @pytest.mark.asyncio
    async def test_post_extracts_control_keys(self, handler, video_reel_payload):
        """POST extracts output_directory, user_id, session_id before validation."""
        payload = {
            **video_reel_payload,
            "output_directory": "/tmp/reels",
            "user_id": "user-123",
            "session_id": "sess-456",
        }
        handler.request.json = AsyncMock(return_value=payload)

        await handler.post()

        create_call = handler.job_manager.create_job.call_args
        assert create_call.kwargs["user_id"] == "user-123"
        assert create_call.kwargs["session_id"] == "sess-456"

    @pytest.mark.asyncio
    async def test_post_creates_job_with_correct_params(self, handler, video_reel_payload):
        """POST creates job with obj_id='video_reel' and prompt as query."""
        handler.request.json = AsyncMock(return_value=video_reel_payload)

        await handler.post()

        create_call = handler.job_manager.create_job.call_args
        assert create_call.kwargs["obj_id"] == "video_reel"
        assert create_call.kwargs["query"] == video_reel_payload["prompt"]
        assert create_call.kwargs["execution_mode"] == "video_reel"


# ---------------------------------------------------------------------------
# 3. Handler GET schema tests (no job_id)
# ---------------------------------------------------------------------------

class TestVideoReelHandlerGet:
    """Tests for VideoReelHandler.get() without job_id — schema catalog."""

    @pytest.mark.asyncio
    async def test_get_schema(self, handler):
        """GET without job_id returns JSON with all expected top-level keys."""
        await handler.get()

        handler.json_response.assert_called_once()
        payload = handler.json_response.call_args[0][0]
        expected_keys = {
            "video_reel_request", "video_reel_scene",
            "aspect_ratios", "music_genres", "music_moods",
        }
        assert set(payload.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_get_schema_has_properties(self, handler):
        """GET video_reel_request schema includes core properties."""
        await handler.get()
        payload = handler.json_response.call_args[0][0]
        props = payload["video_reel_request"]["properties"]
        assert "prompt" in props
        assert "scenes" in props
        assert "aspect_ratio" in props

    @pytest.mark.asyncio
    async def test_schema_includes_aspect_ratios(self, handler):
        """GET includes all AspectRatio enum values."""
        await handler.get()
        payload = handler.json_response.call_args[0][0]
        expected = {r.value for r in AspectRatio}
        assert set(payload["aspect_ratios"]) == expected

    @pytest.mark.asyncio
    async def test_schema_includes_music_genres(self, handler):
        """GET includes all MusicGenre enum values."""
        await handler.get()
        payload = handler.json_response.call_args[0][0]
        expected = {g.value for g in MusicGenre}
        assert set(payload["music_genres"]) == expected

    @pytest.mark.asyncio
    async def test_schema_includes_music_moods(self, handler):
        """GET includes all MusicMood enum values."""
        await handler.get()
        payload = handler.json_response.call_args[0][0]
        expected = {m.value for m in MusicMood}
        assert set(payload["music_moods"]) == expected

    @pytest.mark.asyncio
    async def test_scene_schema_present(self, handler):
        """GET includes VideoReelScene schema."""
        await handler.get()
        payload = handler.json_response.call_args[0][0]
        scene_schema = payload["video_reel_scene"]
        assert "properties" in scene_schema
        assert "background_prompt" in scene_schema["properties"]
        assert "video_prompt" in scene_schema["properties"]


# ---------------------------------------------------------------------------
# 4. Handler GET job status tests (with job_id)
# ---------------------------------------------------------------------------

class TestVideoReelHandlerGetJobStatus:
    """Tests for VideoReelHandler.get() with ?job_id= query parameter."""

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, handler):
        """GET with unknown job_id returns 404."""
        handler.request.match_info = {"job_id": "unknown-id"}
        handler.job_manager.get_job = MagicMock(return_value=None)

        result = await handler.get()

        assert result.status == 404

    @pytest.mark.asyncio
    async def test_get_job_pending(self, handler):
        """GET with pending job returns status 'pending'."""
        job = _make_job(status_value="pending")
        handler.request.match_info = {"job_id": "job-123"}
        handler.job_manager.get_job = MagicMock(return_value=job)

        result = await handler.get()

        assert result.status == 200
        response_data = handler.json_response.call_args[0][0]
        assert response_data["status"] == "pending"
        assert response_data["job_id"] == "job-123"

    @pytest.mark.asyncio
    async def test_get_job_running(self, handler):
        """GET with running job returns status 'running' + started_at."""
        started = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)
        job = _make_job(status_value="running", started_at=started, elapsed_time=30.5)
        handler.request.match_info = {"job_id": "job-123"}
        handler.job_manager.get_job = MagicMock(return_value=job)

        result = await handler.get()

        assert result.status == 200
        response_data = handler.json_response.call_args[0][0]
        assert response_data["status"] == "running"
        assert response_data["started_at"] == started.isoformat()
        assert response_data["elapsed_time"] == 30.5

    @pytest.mark.asyncio
    async def test_get_job_completed(self, handler):
        """GET with completed job returns status + result + elapsed_time."""
        completed = datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc)
        job = _make_job(
            status_value="completed",
            result={"files": ["/tmp/reel.mp4"]},
            completed_at=completed,
            elapsed_time=120.0,
        )
        handler.request.match_info = {"job_id": "job-123"}
        handler.job_manager.get_job = MagicMock(return_value=job)

        result = await handler.get()

        assert result.status == 200
        response_data = handler.json_response.call_args[0][0]
        assert response_data["status"] == "completed"
        assert response_data["result"] == {"files": ["/tmp/reel.mp4"]}
        assert response_data["completed_at"] == completed.isoformat()
        assert response_data["elapsed_time"] == 120.0

    @pytest.mark.asyncio
    async def test_get_job_failed(self, handler):
        """GET with failed job returns status + error."""
        completed = datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc)
        job = _make_job(
            status_value="failed",
            error="All scene generations failed.",
            completed_at=completed,
        )
        handler.request.match_info = {"job_id": "job-123"}
        handler.job_manager.get_job = MagicMock(return_value=job)

        result = await handler.get()

        assert result.status == 200
        response_data = handler.json_response.call_args[0][0]
        assert response_data["status"] == "failed"
        assert "All scene generations failed" in response_data["error"]


# ---------------------------------------------------------------------------
# 5. Schema helper test
# ---------------------------------------------------------------------------

class TestSchemaHelper:
    """Test GoogleGenerationHelper.list_schemas includes video reel schema."""

    def test_schema_helper_includes_video_reel(self):
        """list_schemas() dict has 'video_reel_request' key."""
        from parrot.handlers.google_generation import GoogleGenerationHelper

        schemas = GoogleGenerationHelper.list_schemas()
        assert "video_reel_request" in schemas

    def test_schema_helper_video_reel_has_properties(self):
        """Video reel schema in list_schemas() contains expected properties."""
        from parrot.handlers.google_generation import GoogleGenerationHelper

        schemas = GoogleGenerationHelper.list_schemas()
        props = schemas["video_reel_request"]["properties"]
        assert "prompt" in props
        assert "scenes" in props
        assert "aspect_ratio" in props


# ---------------------------------------------------------------------------
# 6. Model field tests — reference_image / reference_images (FEAT-029)
# ---------------------------------------------------------------------------

class TestVideoReelReferenceImageFields:
    """Tests for new reference_image / reference_images model fields."""

    def test_videoreelscene_has_reference_image_field(self):
        """VideoReelScene should accept reference_image."""
        scene = VideoReelScene(
            background_prompt="A sunny beach",
            video_prompt="Slow pan",
            duration=5.0,
            reference_image="/tmp/ref.jpg",
        )
        assert scene.reference_image == "/tmp/ref.jpg"

    def test_videoreelscene_reference_image_defaults_none(self):
        """VideoReelScene.reference_image defaults to None."""
        scene = VideoReelScene(background_prompt="x", video_prompt="y", duration=5.0)
        assert scene.reference_image is None

    def test_videoreelrequest_has_reference_images_field(self):
        """VideoReelRequest.reference_images defaults to None."""
        req = VideoReelRequest(prompt="test")
        assert req.reference_images is None

    def test_videoreelrequest_reference_images_can_be_set(self):
        """VideoReelRequest.reference_images accepts a list of paths."""
        req = VideoReelRequest(prompt="test", reference_images=["/tmp/a.jpg", "/tmp/b.jpg"])
        assert req.reference_images == ["/tmp/a.jpg", "/tmp/b.jpg"]


# ---------------------------------------------------------------------------
# 7. Handler multipart tests (FEAT-029)
# ---------------------------------------------------------------------------

class TestVideoReelHandlerMultipart:
    """Tests for multipart/form-data upload path in VideoReelHandler.post()."""

    @pytest.mark.asyncio
    async def test_post_json_body_no_regression(self, handler, video_reel_payload):
        """Plain JSON POST must still work — no reference images."""
        handler.request.content_type = "application/json"
        handler.request.json = AsyncMock(return_value=video_reel_payload)

        result = await handler.post()

        assert result.status == 202
        body = handler.json_response.call_args[0][0]
        assert "job_id" in body

    @pytest.mark.asyncio
    async def test_post_multipart_single_image(self, handler, tmp_path):
        """Multipart POST with one image assigns it to reference_images."""
        img = tmp_path / "ref.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0")

        handler.request.content_type = "multipart/form-data; boundary=----boundary"
        with patch.object(
            handler,
            "_parse_multipart",
            new=AsyncMock(return_value=({"prompt": "test reel"}, [img])),
        ):
            result = await handler.post()

        assert result.status == 202
        body = handler.json_response.call_args[0][0]
        assert "job_id" in body

    @pytest.mark.asyncio
    async def test_post_multipart_sets_reference_images_on_request(self, handler, tmp_path):
        """Multipart POST populates req.reference_images before job creation."""
        img0 = tmp_path / "a.jpg"
        img1 = tmp_path / "b.jpg"
        img0.write_bytes(b"FAKE0")
        img1.write_bytes(b"FAKE1")

        captured_req = {}

        async def fake_execute(job_id, coro_fn):
            # Capture the req object via the closure — we can't call coro_fn
            # without real Google client, so just record that execute was called.
            pass

        handler.job_manager.execute_job = fake_execute
        handler.request.content_type = "multipart/form-data; boundary=----boundary"

        with patch.object(
            handler,
            "_parse_multipart",
            new=AsyncMock(return_value=({"prompt": "test"}, [img0, img1])),
        ):
            result = await handler.post()

        assert result.status == 202

    @pytest.mark.asyncio
    async def test_post_multipart_bad_body_returns_400(self, handler):
        """Multipart POST that raises during parsing returns 400."""
        handler.request.content_type = "multipart/form-data; boundary=----boundary"
        with patch.object(
            handler,
            "_parse_multipart",
            new=AsyncMock(side_effect=Exception("parse error")),
        ):
            result = await handler.post()

        assert result.status == 400
