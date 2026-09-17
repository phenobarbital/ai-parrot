"""TASK-3332: real HTTP input boundary tests for ``VideoReelHandler``.

Multipart bodies are built with a real ``aiohttp.MultipartWriter`` and fed
through ``aiohttp.test_utils.make_mocked_request`` + ``request.multipart()``
— the same pattern as ``test_infographic_render_models.py`` /
``test_infographic_render_route.py`` — so these tests exercise the actual
aiohttp wire format, not a hand-mocked reader.

Covers: JSON-body-is-object validation, the legacy `model` alias reaching
`VideoReelRequest` (not popped early), server-configurable scene/upload
bounds, indexed vs. ordered image addressing (sparse holes, reordering,
duplicate filenames, mixed-address rejection), the `reference_images`
storage-escape rejection, and upload-ownership cleanup across parse/
validation/setup failures.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import MultipartWriter, web
from aiohttp.base_protocol import BaseProtocol
from aiohttp.streams import StreamReader
from aiohttp.test_utils import make_mocked_request

from parrot.handlers.video_reel import VideoReelHandler

# NOTE: this package's pytest.ini_options sets `asyncio_mode = "auto"`.


# ---------------------------------------------------------------------------
# Request construction helpers
# ---------------------------------------------------------------------------


async def _multipart_request(parts: List[Tuple[str, bytes, Optional[str]]], *, app: web.Application):
    """Build a real aiohttp multipart request from ``(name, data, content_type)`` parts."""
    writer = MultipartWriter("form-data")
    for name, data, content_type in parts:
        headers = {"Content-Type": content_type} if content_type else None
        payload = writer.append(data, headers)
        payload.set_content_disposition("form-data", name=name)
    body = await writer.as_bytes()

    loop = asyncio.get_event_loop()
    protocol = BaseProtocol(loop=loop)
    stream = StreamReader(protocol, limit=2**20, loop=loop)
    stream.feed_data(body)
    stream.feed_eof()
    return make_mocked_request(
        "POST",
        "/api/v1/google/generation/video_reel",
        headers={"Content-Type": writer.content_type},
        payload=stream,
        app=app,
    )


async def _json_request(body: Any, *, app: web.Application, raw: Optional[bytes] = None):
    """Build a real aiohttp request with a plain JSON (or malformed) body."""
    data = raw if raw is not None else json.dumps(body).encode("utf-8")
    loop = asyncio.get_event_loop()
    protocol = BaseProtocol(loop=loop)
    stream = StreamReader(protocol, limit=2**20, loop=loop)
    stream.feed_data(data)
    stream.feed_eof()
    return make_mocked_request(
        "POST",
        "/api/v1/google/generation/video_reel",
        headers={"Content-Type": "application/json"},
        payload=stream,
        app=app,
    )


class _FakeJob:
    def __init__(self, job_id: str):
        from datetime import datetime, timezone

        self.job_id = job_id
        self.status = MagicMock(value="pending")
        self.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeJobManager:
    """Records `create_job`/`execute_job` calls without running anything."""

    def __init__(self):
        self.created: List[dict] = []
        self.executed: List[Tuple[str, Any]] = []
        self.create_job_side_effect = None

    def create_job(self, **kwargs):
        if self.create_job_side_effect is not None:
            raise self.create_job_side_effect
        self.created.append(kwargs)
        return _FakeJob(kwargs["job_id"])

    async def execute_job(self, job_id, coro_fn):
        self.executed.append((job_id, coro_fn))


@pytest.fixture
def job_manager() -> _FakeJobManager:
    return _FakeJobManager()


@pytest.fixture
def app(job_manager) -> web.Application:
    application = web.Application()
    application["job_manager"] = job_manager
    return application


def _handler(request) -> VideoReelHandler:
    h = VideoReelHandler.__new__(VideoReelHandler)
    h.logger = logging.getLogger("test.video_reel_inputs")
    h._request = request
    # TASK-3333: post() now requires a session-resolved identity for job
    # ownership (§8 Q7) — bypass real navigator-auth session machinery
    # (there is none configured on the bare `web.Application()` these
    # tests build) with a fixed test identity. This suite tests request
    # body/upload parsing, not authorization — that's
    # test_video_reel_artifacts.py's job.
    h._get_session_user_id = AsyncMock(return_value="test-user-id")
    return h


async def _post(handler: VideoReelHandler) -> web.StreamResponse:
    """Calls ``handler.post()``, normalizing the real ``BaseView.error()``'s
    raise-based signaling (it raises ``web.HTTPException``, it does not
    return) into a returned response — mirroring how aiohttp's own
    request-handling machinery treats a raised ``HTTPException`` as the
    response (``HTTPException`` IS a ``Response`` subclass, with ``.status``).
    Any other exception (e.g. a genuine setup failure) still propagates.
    """
    try:
        return await handler.post()
    except web.HTTPException as exc:
        return exc


def _image_part(name: str, content: bytes = b"\xff\xd8\xff\xe0", filename: str = "photo.jpg"):
    return (name, content, "image/jpeg")


# ---------------------------------------------------------------------------
# JSON body validation
# ---------------------------------------------------------------------------


class TestJsonBodyValidation:
    async def test_json_array_body_is_rejected(self, app):
        """A JSON array (not an object) must return 400, not a TypeError."""
        request = await _json_request([1, 2, 3], app=app)
        handler = _handler(request)

        result = await _post(handler)

        assert result.status == 400

    async def test_malformed_json_returns_400(self, app):
        request = await _json_request(None, app=app, raw=b"{not json")
        handler = _handler(request)

        result = await _post(handler)

        assert result.status == 400

    async def test_model_alias_reaches_validation_and_conflict_is_rejected(self, app):
        """`model` must NOT be popped before VideoReelRequest validation — a
        conflicting legacy alias must surface as a 400 validation error."""
        body = {"prompt": "test reel", "model": "gemini-2.5-flash", "director_model": "gemini-3.5-flash"}
        request = await _json_request(body, app=app)
        handler = _handler(request)

        result = await _post(handler)

        assert result.status == 400

    async def test_model_alias_identical_values_succeed(self, app, job_manager):
        """Identical `model`/`director_model` values are accepted (deprecation warning only)."""
        body = {"prompt": "test reel", "model": "gemini-2.5-flash", "director_model": "gemini-2.5-flash"}
        request = await _json_request(body, app=app)
        handler = _handler(request)

        result = await _post(handler)

        assert result.status == 202
        assert len(job_manager.created) == 1

    async def test_reference_images_supplied_directly_is_rejected(self, app):
        """`reference_images` is handler-populated only; a caller-supplied value
        (e.g. an arbitrary local path) must be rejected, not trusted."""
        body = {"prompt": "test reel", "reference_images": ["/etc/passwd"]}
        request = await _json_request(body, app=app)
        handler = _handler(request)

        result = await _post(handler)

        assert result.status == 400


# ---------------------------------------------------------------------------
# Server-configurable bounds
# ---------------------------------------------------------------------------


class TestBounds:
    async def test_too_many_scenes_returns_413(self, app, monkeypatch):
        monkeypatch.setenv("VIDEO_REEL_MAX_SCENES", "2")
        scene = {"background_prompt": "bg", "video_prompt": "vid"}
        body = {"prompt": "test reel", "scenes": [scene, scene, scene]}
        request = await _json_request(body, app=app)
        handler = _handler(request)

        result = await _post(handler)

        assert result.status == 413

    async def test_scenes_at_limit_is_accepted(self, app, job_manager, monkeypatch):
        monkeypatch.setenv("VIDEO_REEL_MAX_SCENES", "2")
        scene = {"background_prompt": "bg", "video_prompt": "vid"}
        body = {"prompt": "test reel", "scenes": [scene, scene]}
        request = await _json_request(body, app=app)
        handler = _handler(request)

        result = await _post(handler)

        assert result.status == 202

    async def test_oversized_image_returns_413(self, app, monkeypatch):
        monkeypatch.setenv("VIDEO_REEL_MAX_IMAGE_BYTES", "4")
        parts = [("prompt", b"test reel", "text/plain"), _image_part("image_0", content=b"\xff\xd8\xff\xe0\xff")]
        request = await _multipart_request(parts, app=app)
        handler = _handler(request)

        result = await _post(handler)

        assert result.status == 413

    async def test_total_upload_size_exceeded_returns_413(self, app, monkeypatch):
        monkeypatch.setenv("VIDEO_REEL_MAX_IMAGE_BYTES", "1000")
        monkeypatch.setenv("VIDEO_REEL_MAX_TOTAL_UPLOAD_BYTES", "5")
        parts = [
            ("prompt", b"test reel", "text/plain"),
            _image_part("image_0", content=b"\xff\xd8\xff"),
            _image_part("image_1", content=b"\xff\xd8\xff"),
        ]
        request = await _multipart_request(parts, app=app)
        handler = _handler(request)

        result = await _post(handler)

        assert result.status == 413

    async def test_out_of_range_index_is_rejected(self, app, monkeypatch):
        monkeypatch.setenv("VIDEO_REEL_MAX_SCENES", "2")
        parts = [("prompt", b"test reel", "text/plain"), _image_part("image_5")]
        request = await _multipart_request(parts, app=app)
        handler = _handler(request)

        result = await _post(handler)

        assert result.status == 400


# ---------------------------------------------------------------------------
# Indexed vs. ordered image addressing (direct _parse_multipart tests)
# ---------------------------------------------------------------------------


class TestMultipartImageAddressing:
    async def test_sparse_indexed_slots_preserve_holes(self, app):
        """image_0 and image_3 uploaded, 1 and 2 absent -> holes preserved."""
        parts = [
            ("prompt", b"test reel", "text/plain"),
            _image_part("image_0", content=b"AAA0"),
            _image_part("image_3", content=b"AAA3"),
        ]
        request = await _multipart_request(parts, app=app)
        handler = _handler(request)

        data, images = await handler._parse_multipart()

        assert set(images.keys()) == {0, 3}
        assert images[0].read_bytes() == b"AAA0"
        assert images[3].read_bytes() == b"AAA3"
        assert data["prompt"] == "test reel"

    async def test_ordered_slots_assign_sequential_indices(self, app):
        """reference_images parts (no explicit index) get 0, 1, 2... in arrival order."""
        parts = [
            ("prompt", b"test reel", "text/plain"),
            ("reference_images", b"AAA0", "image/jpeg"),
            ("reference_images", b"AAA1", "image/jpeg"),
        ]
        request = await _multipart_request(parts, app=app)
        handler = _handler(request)

        data, images = await handler._parse_multipart()

        assert set(images.keys()) == {0, 1}
        assert images[0].read_bytes() == b"AAA0"
        assert images[1].read_bytes() == b"AAA1"

    async def test_duplicate_index_is_rejected(self, app):
        parts = [
            ("prompt", b"test reel", "text/plain"),
            _image_part("image_0", content=b"AAA0"),
            _image_part("image_0", content=b"BBB0"),
        ]
        request = await _multipart_request(parts, app=app)
        handler = _handler(request)

        with pytest.raises(Exception):
            await handler._parse_multipart()

    async def test_mixed_addressing_is_rejected(self, app):
        """Indexed image_<n> and ordered reference_images in the same request must fail."""
        parts = [
            ("prompt", b"test reel", "text/plain"),
            _image_part("image_0", content=b"AAA0"),
            ("reference_images", b"BBB0", "image/jpeg"),
        ]
        request = await _multipart_request(parts, app=app)
        handler = _handler(request)

        with pytest.raises(Exception):
            await handler._parse_multipart()

    async def test_duplicate_filenames_get_unique_destinations(self, app):
        """Two different uploads sharing the same original filename must not collide."""
        parts = [
            ("prompt", b"test reel", "text/plain"),
            ("image_0", b"CONTENT-A", "image/jpeg"),
            ("image_1", b"CONTENT-B", "image/jpeg"),
        ]
        # Force identical original filenames via explicit headers.
        writer = MultipartWriter("form-data")
        headers0 = {"Content-Type": "image/jpeg"}
        p0 = writer.append(b"CONTENT-A", headers0)
        p0.set_content_disposition("form-data", name="image_0", filename="same.jpg")
        headers1 = {"Content-Type": "image/jpeg"}
        p1 = writer.append(b"CONTENT-B", headers1)
        p1.set_content_disposition("form-data", name="image_1", filename="same.jpg")
        body = await writer.as_bytes()

        loop = asyncio.get_event_loop()
        protocol = BaseProtocol(loop=loop)
        stream = StreamReader(protocol, limit=2**20, loop=loop)
        stream.feed_data(body)
        stream.feed_eof()
        request = make_mocked_request(
            "POST",
            "/api/v1/google/generation/video_reel",
            headers={"Content-Type": writer.content_type},
            payload=stream,
            app=app,
        )
        handler = _handler(request)

        data, images = await handler._parse_multipart()

        assert images[0] != images[1]
        assert images[0].name != images[1].name
        assert images[0].read_bytes() == b"CONTENT-A"
        assert images[1].read_bytes() == b"CONTENT-B"


# ---------------------------------------------------------------------------
# Upload ownership / cleanup across failure paths
# ---------------------------------------------------------------------------


def _mkdtemp_spy():
    """Wraps `tempfile.mkdtemp` to record every path it returns, so a test
    can assert on the EXACT directory the handler created — a global glob
    over the system temp root is unsafe here since other tests in the same
    session legitimately leave their own `videoreel_upload_*` dirs behind.
    """
    import tempfile as _tempfile

    created: List[str] = []
    original = _tempfile.mkdtemp

    def _spy(*args, **kwargs):
        path = original(*args, **kwargs)
        created.append(path)
        return path

    return created, _spy


class TestUploadOwnershipCleanup:
    async def test_validation_failure_after_image_upload_cleans_tmp_dir(self, app):
        """A Pydantic validation error occurring AFTER images were saved must
        still remove the temp directory (no leak on the validation-failure path)."""
        # Missing required `prompt` -> ValidationError, but images are supplied.
        parts = [_image_part("image_0", content=b"AAA0")]
        request = await _multipart_request(parts, app=app)
        handler = _handler(request)
        created, spy = _mkdtemp_spy()

        with patch("parrot.handlers.video_reel.tempfile.mkdtemp", side_effect=spy):
            result = await _post(handler)

        assert result.status == 400
        assert len(created) == 1
        from pathlib import Path

        assert not Path(created[0]).exists()

    async def test_duplicate_index_failure_cleans_tmp_dir(self, app):
        """A _parse_multipart-internal rejection (duplicate index) must clean
        up its own tmp_dir before re-raising."""
        parts = [
            _image_part("image_0", content=b"AAA0"),
            _image_part("image_0", content=b"BBB0"),
        ]
        request = await _multipart_request(parts, app=app)
        handler = _handler(request)
        created, spy = _mkdtemp_spy()

        with patch("parrot.handlers.video_reel.tempfile.mkdtemp", side_effect=spy):
            with pytest.raises(Exception):
                await handler._parse_multipart()

        assert len(created) == 1
        from pathlib import Path

        assert not Path(created[0]).exists()

    async def test_job_creation_failure_cleans_tmp_dir(self, app, job_manager):
        """A failure in job_manager.create_job (setup, after validation) must
        still clean up any uploaded images before propagating."""
        job_manager.create_job_side_effect = RuntimeError("job store unavailable")
        parts = [
            ("prompt", b"test reel", "text/plain"),
            _image_part("image_0", content=b"AAA0"),
        ]
        request = await _multipart_request(parts, app=app)
        handler = _handler(request)
        created, spy = _mkdtemp_spy()

        with patch("parrot.handlers.video_reel.tempfile.mkdtemp", side_effect=spy):
            with pytest.raises(RuntimeError):
                await handler.post()

        assert len(created) == 1
        from pathlib import Path

        assert not Path(created[0]).exists()


# ---------------------------------------------------------------------------
# POST forwards the full validated request to the provider call
# ---------------------------------------------------------------------------


class TestPostForwardsFullRequest:
    async def test_run_logic_passes_full_request_and_effective_director_model(self, app, job_manager):
        """The background job callback must call generate_video_reel(request=<full
        VideoReelRequest>), using effective_director_model() to build the client —
        never a stripped dict or the pre-TASK-3321 hardcoded default."""
        body = {"prompt": "test reel", "director_model": "gemini-3.1-flash"}
        request = await _json_request(body, app=app)
        handler = _handler(request)

        result = await _post(handler)
        assert result.status == 202
        assert len(job_manager.executed) == 1
        _, run_logic = job_manager.executed[0]

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_result = MagicMock()
        fake_result.model_dump.return_value = {"ok": True}
        fake_client.generate_video_reel = AsyncMock(return_value=fake_result)
        fake_client_cls = MagicMock(return_value=fake_client)

        with patch("parrot.clients.google.GoogleGenAIClient", fake_client_cls):
            output = await run_logic()

        assert output == {"ok": True}
        fake_client_cls.assert_called_once_with(model="gemini-3.1-flash")
        call_kwargs = fake_client.generate_video_reel.call_args.kwargs
        assert call_kwargs["request"].prompt == "test reel"
        assert call_kwargs["request"].effective_director_model() == "gemini-3.1-flash"
