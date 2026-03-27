"""Unit tests for UnderstandingHandler with mocked GoogleGenAIClient."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from parrot.handlers.understanding import UnderstandingHandler


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

HANDLER_PATH = "parrot.handlers.understanding.GoogleGenAIClient"


def _make_ai_message(content: str = "Analysis result") -> MagicMock:
    """Build a minimal AIMessage-like mock."""
    msg = MagicMock()
    msg.content = content
    msg.structured_output = None
    msg.model = "gemini-2.5-flash"
    msg.provider = "google_genai"
    msg.usage = None
    return msg


def _patch_client(mock_msg: MagicMock):
    """Return a context-manager patch that makes GoogleGenAIClient return *mock_msg*.

    The handler uses ``async with client:`` but then calls ``client.image_understanding``
    directly on the client object (not the __aenter__ return value), so we mock
    on ``return_value`` directly.
    """
    patcher = patch(HANDLER_PATH)

    class _Ctx:
        def __enter__(self):
            self.mock_cls = patcher.start()
            # The handler creates the client as GoogleGenAIClient(**kwargs) → mock_cls.return_value
            # It then calls client.image_understanding / client.video_understanding directly.
            client_instance = self.mock_cls.return_value
            client_instance.image_understanding = AsyncMock(return_value=mock_msg)
            client_instance.video_understanding = AsyncMock(return_value=mock_msg)
            # Support async with client:
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            self.instance = client_instance
            return self

        def __exit__(self, *args):
            patcher.stop()

    return _Ctx()


# ---------------------------------------------------------------------------
# Basic import / setup
# ---------------------------------------------------------------------------


class TestUnderstandingHandlerImport:
    def test_importable(self) -> None:
        """UnderstandingHandler can be imported."""
        assert UnderstandingHandler is not None

    def test_has_post(self) -> None:
        """Handler exposes a post method."""
        assert callable(UnderstandingHandler.post)

    def test_has_get(self) -> None:
        """Handler exposes a get method."""
        assert callable(UnderstandingHandler.get)

    def test_has_setup(self) -> None:
        """Handler exposes a setup classmethod."""
        assert callable(UnderstandingHandler.setup)

    def test_setup_registers_route(self) -> None:
        """setup() adds the route to the aiohttp app router."""
        app = web.Application()
        UnderstandingHandler.setup(app, route="/test/understanding")
        routes = [r.resource.canonical for r in app.router.routes()]
        assert "/test/understanding" in routes


# ---------------------------------------------------------------------------
# GET endpoint — catalog
# ---------------------------------------------------------------------------


class TestUnderstandingHandlerGet:
    @pytest.mark.asyncio
    async def test_get_returns_200_with_schema(self, aiohttp_client) -> None:
        """GET returns 200 with schema and supported types."""
        app = web.Application()
        UnderstandingHandler.setup(app, route="/api/v1/google/understanding")
        client = await aiohttp_client(app)

        resp = await client.get("/api/v1/google/understanding")
        assert resp.status == 200

        body = await resp.json()
        assert "schema" in body
        assert "supported_media_types" in body
        assert "image" in body["supported_media_types"]
        assert "video" in body["supported_media_types"]

    @pytest.mark.asyncio
    async def test_get_returns_extensions(self, aiohttp_client) -> None:
        """GET response includes image and video extension lists."""
        app = web.Application()
        UnderstandingHandler.setup(app, route="/api/v1/google/understanding")
        client = await aiohttp_client(app)

        resp = await client.get("/api/v1/google/understanding")
        body = await resp.json()
        assert ".png" in body["image_extensions"]
        assert ".mp4" in body["video_extensions"]


# ---------------------------------------------------------------------------
# POST endpoint — JSON mode
# ---------------------------------------------------------------------------


class TestUnderstandingHandlerPostJSON:
    @pytest.mark.asyncio
    async def test_missing_prompt_returns_400(self, aiohttp_client) -> None:
        """POST without 'prompt' returns 400."""
        app = web.Application()
        UnderstandingHandler.setup(app, route="/api/v1/google/understanding")
        client = await aiohttp_client(app)

        resp = await client.post(
            "/api/v1/google/understanding",
            json={"media_url": "https://example.com/img.png"},
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_missing_media_returns_400(self, aiohttp_client) -> None:
        """POST with a prompt but no media returns 400."""
        app = web.Application()
        UnderstandingHandler.setup(app, route="/api/v1/google/understanding")
        client = await aiohttp_client(app)

        resp = await client.post(
            "/api/v1/google/understanding",
            json={"prompt": "describe this"},
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_json_image_dispatches_to_image_understanding(
        self, aiohttp_client
    ) -> None:
        """JSON POST with image URL calls image_understanding."""
        app = web.Application()
        UnderstandingHandler.setup(app, route="/api/v1/google/understanding")
        http = await aiohttp_client(app)

        msg = _make_ai_message("Image analysis result")

        with _patch_client(msg) as ctx:
            resp = await http.post(
                "/api/v1/google/understanding",
                json={
                    "prompt": "Describe this image",
                    "media_url": "https://example.com/photo.png",
                    "media_type": "image",
                },
            )

        assert resp.status == 200
        body = await resp.json()
        assert body["content"] == "Image analysis result"
        ctx.instance.image_understanding.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_json_video_dispatches_to_video_understanding(
        self, aiohttp_client
    ) -> None:
        """JSON POST with video URL calls video_understanding."""
        app = web.Application()
        UnderstandingHandler.setup(app, route="/api/v1/google/understanding")
        http = await aiohttp_client(app)

        msg = _make_ai_message("Video analysis result")

        with _patch_client(msg) as ctx:
            resp = await http.post(
                "/api/v1/google/understanding",
                json={
                    "prompt": "Summarise this video",
                    "media_url": "https://example.com/clip.mp4",
                    "media_type": "video",
                },
            )

        assert resp.status == 200
        body = await resp.json()
        assert body["content"] == "Video analysis result"
        ctx.instance.video_understanding.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_image_auto_detected_from_url_extension(
        self, aiohttp_client
    ) -> None:
        """Image type auto-detected from .jpg URL extension (no media_type field)."""
        app = web.Application()
        UnderstandingHandler.setup(app, route="/api/v1/google/understanding")
        http = await aiohttp_client(app)

        msg = _make_ai_message("Auto-detected image")

        with _patch_client(msg) as ctx:
            resp = await http.post(
                "/api/v1/google/understanding",
                json={
                    "prompt": "What is in this image?",
                    "media_url": "https://example.com/photo.jpg",
                },
            )

        assert resp.status == 200
        ctx.instance.image_understanding.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_video_auto_detected_from_url_extension(
        self, aiohttp_client
    ) -> None:
        """Video type auto-detected from .mp4 URL extension (no media_type field)."""
        app = web.Application()
        UnderstandingHandler.setup(app, route="/api/v1/google/understanding")
        http = await aiohttp_client(app)

        msg = _make_ai_message("Auto-detected video")

        with _patch_client(msg) as ctx:
            resp = await http.post(
                "/api/v1/google/understanding",
                json={
                    "prompt": "Summarise",
                    "media_url": "https://example.com/clip.mp4",
                },
            )

        assert resp.status == 200
        ctx.instance.video_understanding.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self, aiohttp_client) -> None:
        """Sending non-JSON body with JSON content-type returns 400."""
        app = web.Application()
        UnderstandingHandler.setup(app, route="/api/v1/google/understanding")
        http = await aiohttp_client(app)

        resp = await http.post(
            "/api/v1/google/understanding",
            data=b"not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400


# ---------------------------------------------------------------------------
# POST endpoint — multipart mode
# ---------------------------------------------------------------------------


class TestUnderstandingHandlerPostMultipart:
    @pytest.mark.asyncio
    async def test_multipart_image_calls_image_understanding(
        self, aiohttp_client
    ) -> None:
        """Multipart upload of a PNG file calls image_understanding."""
        from aiohttp import FormData

        app = web.Application()
        UnderstandingHandler.setup(app, route="/api/v1/google/understanding")
        http = await aiohttp_client(app)

        msg = _make_ai_message("Multipart image result")

        data = FormData()
        data.add_field("prompt", "Describe this image")
        data.add_field(
            "file",
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,  # minimal fake PNG bytes
            filename="test.png",
            content_type="image/png",
        )

        with _patch_client(msg) as ctx:
            resp = await http.post(
                "/api/v1/google/understanding", data=data
            )

        assert resp.status == 200
        body = await resp.json()
        assert body["content"] == "Multipart image result"
        ctx.instance.image_understanding.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multipart_video_calls_video_understanding(
        self, aiohttp_client
    ) -> None:
        """Multipart upload of a .mp4 file calls video_understanding."""
        from aiohttp import FormData

        app = web.Application()
        UnderstandingHandler.setup(app, route="/api/v1/google/understanding")
        http = await aiohttp_client(app)

        msg = _make_ai_message("Multipart video result")

        data = FormData()
        data.add_field("prompt", "Summarise this video")
        data.add_field(
            "file",
            b"\x00" * 200,  # fake video bytes
            filename="clip.mp4",
            content_type="video/mp4",
        )

        with _patch_client(msg) as ctx:
            resp = await http.post(
                "/api/v1/google/understanding", data=data
            )

        assert resp.status == 200
        body = await resp.json()
        assert body["content"] == "Multipart video result"
        ctx.instance.video_understanding.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multipart_missing_prompt_returns_400(
        self, aiohttp_client
    ) -> None:
        """Multipart upload without a prompt field returns 400."""
        from aiohttp import FormData

        app = web.Application()
        UnderstandingHandler.setup(app, route="/api/v1/google/understanding")
        http = await aiohttp_client(app)

        data = FormData()
        data.add_field(
            "file",
            b"\x00" * 50,
            filename="test.png",
            content_type="image/png",
        )

        resp = await http.post("/api/v1/google/understanding", data=data)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_multipart_missing_file_returns_400(
        self, aiohttp_client
    ) -> None:
        """Multipart request with only a prompt and no file returns 400."""
        from aiohttp import FormData

        app = web.Application()
        UnderstandingHandler.setup(app, route="/api/v1/google/understanding")
        http = await aiohttp_client(app)

        data = FormData()
        data.add_field("prompt", "What is this?")

        # With no 'file' part the source will be None → 400.
        resp = await http.post("/api/v1/google/understanding", data=data)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_explicit_media_type_overrides_content_type(
        self, aiohttp_client
    ) -> None:
        """Explicit 'media_type' form field overrides the file's Content-Type."""
        from aiohttp import FormData

        app = web.Application()
        UnderstandingHandler.setup(app, route="/api/v1/google/understanding")
        http = await aiohttp_client(app)

        msg = _make_ai_message("Override result")

        data = FormData()
        data.add_field("prompt", "Describe")
        # File has 'image/png' Content-Type but we override to 'image' explicitly
        data.add_field(
            "file",
            b"\x89PNG\r\n" + b"\x00" * 50,
            filename="test.png",
            content_type="image/png",
        )
        data.add_field("media_type", "image")

        with _patch_client(msg) as ctx:
            resp = await http.post(
                "/api/v1/google/understanding", data=data
            )

        assert resp.status == 200
        ctx.instance.image_understanding.assert_awaited_once()
