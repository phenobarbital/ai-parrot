"""Integration tests for UnderstandingHandler — full request lifecycle with mocked client."""
from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import FormData, web
from PIL import Image

from parrot.handlers.understanding import UnderstandingHandler

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROUTE = "/api/v1/google/understanding"
HANDLER_PATH = "parrot.handlers.understanding.GoogleGenAIClient"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> web.Application:
    """Create an aiohttp Application with UnderstandingHandler mounted."""
    _app = web.Application()
    UnderstandingHandler.setup(_app, route=ROUTE)
    return _app


@pytest.fixture
def mock_image_ai_message() -> MagicMock:
    """AIMessage-like mock returned by image_understanding."""
    msg = MagicMock()
    msg.content = "A red rectangle on a white background."
    msg.structured_output = MagicMock()
    msg.structured_output.model_dump.return_value = {
        "detections": [
            {"label": "rectangle", "score": 0.99, "box": [0.1, 0.1, 0.7, 0.7]}
        ]
    }
    msg.model = "gemini-2.5-flash"
    msg.provider = "google_genai"
    msg.usage = None
    return msg


@pytest.fixture
def mock_video_ai_message() -> MagicMock:
    """AIMessage-like mock returned by video_understanding."""
    msg = MagicMock()
    msg.content = "A short video clip with no notable content."
    msg.structured_output = None
    msg.model = "gemini-2.5-flash"
    msg.provider = "google_genai"
    msg.usage = None
    return msg


@pytest.fixture
def sample_image_bytes(tmp_path: Path) -> tuple[bytes, str]:
    """Generate a minimal red-rectangle PNG as bytes."""
    img = Image.new("RGB", (200, 200), "white")
    from PIL import ImageDraw

    ImageDraw.Draw(img).rectangle([50, 50, 150, 150], fill="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), "test.png"


@pytest.fixture
def sample_video_bytes(tmp_path: Path) -> tuple[bytes, str]:
    """Create a minimal fake .mp4 file (content doesn't matter; client is mocked)."""
    # 100 null bytes — just enough to have a non-empty file
    return b"\x00" * 100, "test.mp4"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_client_patch(mock_msg: MagicMock, *, is_image: bool):
    """Patch GoogleGenAIClient so it returns *mock_msg* for the appropriate method."""
    patcher = patch(HANDLER_PATH)

    class _Ctx:
        def __enter__(self):
            self.mock_cls = patcher.start()
            client_instance = self.mock_cls.return_value
            client_instance.image_understanding = AsyncMock(return_value=mock_msg)
            client_instance.video_understanding = AsyncMock(return_value=mock_msg)
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            self.instance = client_instance
            return self

        def __exit__(self, *args: Any) -> None:
            patcher.stop()

    return _Ctx()


# ---------------------------------------------------------------------------
# GET endpoint
# ---------------------------------------------------------------------------


class TestGetCatalog:
    """Integration tests for the GET /api/v1/google/understanding endpoint."""

    @pytest.mark.asyncio
    async def test_get_returns_200(self, aiohttp_client: Any, app: web.Application) -> None:
        """GET returns HTTP 200."""
        client = await aiohttp_client(app)
        resp = await client.get(ROUTE)
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_get_returns_json_schema(
        self, aiohttp_client: Any, app: web.Application
    ) -> None:
        """GET response body contains a JSON schema with the expected fields."""
        client = await aiohttp_client(app)
        resp = await client.get(ROUTE)
        body = await resp.json()

        assert "schema" in body
        assert "properties" in body["schema"]
        assert "prompt" in body["schema"]["properties"]

    @pytest.mark.asyncio
    async def test_get_returns_supported_media_types(
        self, aiohttp_client: Any, app: web.Application
    ) -> None:
        """GET response includes supported media types."""
        client = await aiohttp_client(app)
        resp = await client.get(ROUTE)
        body = await resp.json()

        assert "image" in body["supported_media_types"]
        assert "video" in body["supported_media_types"]

    @pytest.mark.asyncio
    async def test_get_returns_file_extensions(
        self, aiohttp_client: Any, app: web.Application
    ) -> None:
        """GET response includes image and video extension lists."""
        client = await aiohttp_client(app)
        resp = await client.get(ROUTE)
        body = await resp.json()

        assert ".png" in body["image_extensions"]
        assert ".jpg" in body["image_extensions"]
        assert ".mp4" in body["video_extensions"]
        assert ".mov" in body["video_extensions"]


# ---------------------------------------------------------------------------
# POST multipart — image
# ---------------------------------------------------------------------------


class TestPostImageMultipart:
    """Integration tests for image uploads via multipart/form-data."""

    @pytest.mark.asyncio
    async def test_post_image_returns_200(
        self,
        aiohttp_client: Any,
        app: web.Application,
        sample_image_bytes: tuple[bytes, str],
        mock_image_ai_message: MagicMock,
    ) -> None:
        """POST with a PNG file returns HTTP 200."""
        client = await aiohttp_client(app)
        raw_bytes, filename = sample_image_bytes

        data = FormData()
        data.add_field("prompt", "Describe this image")
        data.add_field(
            "file",
            raw_bytes,
            filename=filename,
            content_type="image/png",
        )

        with _make_client_patch(mock_image_ai_message, is_image=True):
            resp = await client.post(ROUTE, data=data)

        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_post_image_returns_content(
        self,
        aiohttp_client: Any,
        app: web.Application,
        sample_image_bytes: tuple[bytes, str],
        mock_image_ai_message: MagicMock,
    ) -> None:
        """POST image response body contains 'content' and 'provider' fields."""
        client = await aiohttp_client(app)
        raw_bytes, filename = sample_image_bytes

        data = FormData()
        data.add_field("prompt", "Describe this image")
        data.add_field(
            "file",
            raw_bytes,
            filename=filename,
            content_type="image/png",
        )

        with _make_client_patch(mock_image_ai_message, is_image=True):
            resp = await client.post(ROUTE, data=data)
            body = await resp.json()

        assert "content" in body
        assert body["content"] == "A red rectangle on a white background."
        assert body["provider"] == "google_genai"

    @pytest.mark.asyncio
    async def test_post_image_structured_output_present(
        self,
        aiohttp_client: Any,
        app: web.Application,
        sample_image_bytes: tuple[bytes, str],
        mock_image_ai_message: MagicMock,
    ) -> None:
        """POST image response includes structured_output with detections."""
        client = await aiohttp_client(app)
        raw_bytes, filename = sample_image_bytes

        data = FormData()
        data.add_field("prompt", "Detect objects")
        data.add_field(
            "file",
            raw_bytes,
            filename=filename,
            content_type="image/png",
        )

        with _make_client_patch(mock_image_ai_message, is_image=True):
            resp = await client.post(ROUTE, data=data)
            body = await resp.json()

        assert "structured_output" in body
        assert body["structured_output"] is not None
        assert "detections" in body["structured_output"]

    @pytest.mark.asyncio
    async def test_post_image_calls_image_understanding(
        self,
        aiohttp_client: Any,
        app: web.Application,
        sample_image_bytes: tuple[bytes, str],
        mock_image_ai_message: MagicMock,
    ) -> None:
        """POST image → image_understanding is called (not video_understanding)."""
        client = await aiohttp_client(app)
        raw_bytes, filename = sample_image_bytes

        data = FormData()
        data.add_field("prompt", "What is in this image?")
        data.add_field(
            "file",
            raw_bytes,
            filename=filename,
            content_type="image/png",
        )

        with _make_client_patch(mock_image_ai_message, is_image=True) as ctx:
            await client.post(ROUTE, data=data)

        ctx.instance.image_understanding.assert_awaited_once()
        ctx.instance.video_understanding.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST multipart — video
# ---------------------------------------------------------------------------


class TestPostVideoMultipart:
    """Integration tests for video uploads via multipart/form-data."""

    @pytest.mark.asyncio
    async def test_post_video_returns_200(
        self,
        aiohttp_client: Any,
        app: web.Application,
        sample_video_bytes: tuple[bytes, str],
        mock_video_ai_message: MagicMock,
    ) -> None:
        """POST with a .mp4 file returns HTTP 200."""
        client = await aiohttp_client(app)
        raw_bytes, filename = sample_video_bytes

        data = FormData()
        data.add_field("prompt", "Summarise this video")
        data.add_field(
            "file",
            raw_bytes,
            filename=filename,
            content_type="video/mp4",
        )

        with _make_client_patch(mock_video_ai_message, is_image=False):
            resp = await client.post(ROUTE, data=data)

        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_post_video_returns_content(
        self,
        aiohttp_client: Any,
        app: web.Application,
        sample_video_bytes: tuple[bytes, str],
        mock_video_ai_message: MagicMock,
    ) -> None:
        """POST video response body contains 'content' field."""
        client = await aiohttp_client(app)
        raw_bytes, filename = sample_video_bytes

        data = FormData()
        data.add_field("prompt", "What is happening?")
        data.add_field(
            "file",
            raw_bytes,
            filename=filename,
            content_type="video/mp4",
        )

        with _make_client_patch(mock_video_ai_message, is_image=False):
            resp = await client.post(ROUTE, data=data)
            body = await resp.json()

        assert body["content"] == "A short video clip with no notable content."

    @pytest.mark.asyncio
    async def test_post_video_calls_video_understanding(
        self,
        aiohttp_client: Any,
        app: web.Application,
        sample_video_bytes: tuple[bytes, str],
        mock_video_ai_message: MagicMock,
    ) -> None:
        """POST video → video_understanding is called (not image_understanding)."""
        client = await aiohttp_client(app)
        raw_bytes, filename = sample_video_bytes

        data = FormData()
        data.add_field("prompt", "Summarise")
        data.add_field(
            "file",
            raw_bytes,
            filename=filename,
            content_type="video/mp4",
        )

        with _make_client_patch(mock_video_ai_message, is_image=False) as ctx:
            await client.post(ROUTE, data=data)

        ctx.instance.video_understanding.assert_awaited_once()
        ctx.instance.image_understanding.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_post_video_called_with_stateless_true(
        self,
        aiohttp_client: Any,
        app: web.Application,
        sample_video_bytes: tuple[bytes, str],
        mock_video_ai_message: MagicMock,
    ) -> None:
        """video_understanding is always called with stateless=True."""
        client = await aiohttp_client(app)
        raw_bytes, filename = sample_video_bytes

        data = FormData()
        data.add_field("prompt", "Summarise")
        data.add_field(
            "file",
            raw_bytes,
            filename=filename,
            content_type="video/mp4",
        )

        with _make_client_patch(mock_video_ai_message, is_image=False) as ctx:
            await client.post(ROUTE, data=data)

        _, call_kwargs = ctx.instance.video_understanding.call_args
        assert call_kwargs.get("stateless") is True


# ---------------------------------------------------------------------------
# POST JSON mode
# ---------------------------------------------------------------------------


class TestPostJSONMode:
    """Integration tests for JSON body + media_url mode."""

    @pytest.mark.asyncio
    async def test_json_image_url_returns_200(
        self,
        aiohttp_client: Any,
        app: web.Application,
        mock_image_ai_message: MagicMock,
    ) -> None:
        """JSON POST with image URL returns 200."""
        client = await aiohttp_client(app)

        with _make_client_patch(mock_image_ai_message, is_image=True):
            resp = await client.post(
                ROUTE,
                json={
                    "prompt": "What is in this picture?",
                    "media_url": "https://example.com/photo.png",
                    "media_type": "image",
                },
            )

        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_json_video_url_returns_200(
        self,
        aiohttp_client: Any,
        app: web.Application,
        mock_video_ai_message: MagicMock,
    ) -> None:
        """JSON POST with video URL returns 200."""
        client = await aiohttp_client(app)

        with _make_client_patch(mock_video_ai_message, is_image=False):
            resp = await client.post(
                ROUTE,
                json={
                    "prompt": "Summarise this video",
                    "media_url": "https://example.com/clip.mp4",
                    "media_type": "video",
                },
            )

        assert resp.status == 200


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestPostErrorCases:
    """Integration tests for 400 error scenarios."""

    @pytest.mark.asyncio
    async def test_missing_prompt_returns_400(
        self, aiohttp_client: Any, app: web.Application
    ) -> None:
        """POST without 'prompt' returns 400."""
        client = await aiohttp_client(app)
        resp = await client.post(
            ROUTE,
            json={"media_url": "https://example.com/photo.png", "media_type": "image"},
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_missing_media_returns_400(
        self, aiohttp_client: Any, app: web.Application
    ) -> None:
        """POST with only a prompt and no media returns 400."""
        client = await aiohttp_client(app)
        resp = await client.post(ROUTE, json={"prompt": "Describe"})
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_missing_prompt_multipart_returns_400(
        self, aiohttp_client: Any, app: web.Application
    ) -> None:
        """Multipart POST without a prompt field returns 400."""
        client = await aiohttp_client(app)
        data = FormData()
        data.add_field(
            "file",
            b"\x89PNG\r\n" + b"\x00" * 50,
            filename="test.png",
            content_type="image/png",
        )
        resp = await client.post(ROUTE, data=data)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_missing_file_multipart_returns_400(
        self, aiohttp_client: Any, app: web.Application
    ) -> None:
        """Multipart POST with only a prompt and no file returns 400."""
        client = await aiohttp_client(app)
        data = FormData()
        data.add_field("prompt", "Describe")
        resp = await client.post(ROUTE, data=data)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_invalid_json_body_returns_400(
        self, aiohttp_client: Any, app: web.Application
    ) -> None:
        """Sending non-JSON data with JSON content-type returns 400."""
        client = await aiohttp_client(app)
        resp = await client.post(
            ROUTE,
            data=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_invalid_media_type_value_returns_400(
        self, aiohttp_client: Any, app: web.Application
    ) -> None:
        """media_type value other than 'image' or 'video' returns 400."""
        client = await aiohttp_client(app)
        resp = await client.post(
            ROUTE,
            json={
                "prompt": "Analyse this",
                "media_url": "https://example.com/file.mp3",
                "media_type": "audio",
            },
        )
        assert resp.status == 400
