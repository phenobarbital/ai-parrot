"""Unit tests for MediaGen handler with mocked GoogleGenAIClient."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import MultipartReader, web
from parrot.handlers.mediagen import MediaGen
from parrot.models.responses import AIMessage
from parrot.models.basic import CompletionUsage


def _make_mock_message(prompt: str, images: list[Path] = None, files: list[Path] = None) -> AIMessage:
    """Build an AIMessage for image/video generation mocks."""
    return AIMessage(
        input=prompt,
        output="Result payload",
        response="Generation succeeded",
        model="gemini-3.1-flash-image",
        provider="google",
        usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        images=images or [],
        files=files or []
    )


@pytest.fixture
def mock_client_methods():
    """Context manager to patch GoogleGenAIClient methods."""
    class PatchCtx:
        def __init__(self):
            self.patcher = patch("parrot.handlers.mediagen.GoogleGenAIClient")
            self.mock_class = None
            self.client_instance = None

        def __enter__(self):
            self.mock_class = self.patcher.start()
            self.client_instance = self.mock_class.return_value
            
            # Setup async with support
            self.client_instance.__aenter__ = AsyncMock(return_value=self.client_instance)
            self.client_instance.__aexit__ = AsyncMock(return_value=False)
            self.client_instance.close = AsyncMock()
            
            # Setup generation mocks
            self.client_instance.generate_images = AsyncMock()
            self.client_instance.generate_image = AsyncMock()
            self.client_instance.generate_image_batch = AsyncMock()
            self.client_instance.generate_videos = AsyncMock()
            self.client_instance.generate_video_batch = AsyncMock()
            return self

        def __exit__(self, *args):
            self.patcher.stop()

    return PatchCtx()


class TestMediaGenHandler:
    """Tests for MediaGen REST handler."""

    def test_setup_registers_route(self):
        """Verify MediaGen.setup registers route on the app router."""
        app = web.Application()
        MediaGen.setup(app, route="/test/google/media")
        
        # Verify the route was registered
        routes = [r.resource.canonical for r in app.router.routes()]
        assert "/test/google/media" in routes

    async def test_post_image_single(self, aiohttp_client, mock_client_methods, tmp_path):
        """Verify single image generation returns direct file streaming."""
        app = web.Application()
        MediaGen.setup(app, route="/api/v1/google/media")
        client = await aiohttp_client(app)

        # Create a dummy image file that will be "generated"
        dummy_img = tmp_path / "gen_image_123.png"
        dummy_img.write_text("fake image contents")

        with mock_client_methods as ctx:
            ctx.client_instance.generate_image.return_value = _make_mock_message(
                prompt="a cute parrot",
                images=[dummy_img]
            )

            payload = {
                "action": "image",
                "batch": False,
                "prompt": "a cute parrot",
                "download_mode": "StreamResponse"
            }

            resp = await client.post("/api/v1/google/media", json=payload)
            assert resp.status == 200
            assert resp.headers["Content-Type"] == "image/png"
            body = await resp.read()
            assert body == b"fake image contents"
            
            ctx.client_instance.generate_image.assert_called_once()

    async def test_post_image_batch(self, aiohttp_client, mock_client_methods, tmp_path):
        """Verify batch image generation processes concurrently and returns zip archive."""
        app = web.Application()
        MediaGen.setup(app, route="/api/v1/google/media")
        client = await aiohttp_client(app)

        # Create two dummy images
        img1 = tmp_path / "img1.png"
        img1.write_text("img1 data")
        img2 = tmp_path / "img2.png"
        img2.write_text("img2 data")

        with mock_client_methods as ctx:
            ctx.client_instance.generate_image_batch.return_value = [
                _make_mock_message(prompt="parrot 1", images=[img1]),
                _make_mock_message(prompt="parrot 2", images=[img2])
            ]

            payload = {
                "action": "image",
                "batch": True,
                "prompts": ["parrot 1", "parrot 2"],
                "download_mode": "FileResponse"
            }

            resp = await client.post("/api/v1/google/media", json=payload)
            assert resp.status == 200
            assert resp.headers["Content-Type"] == "application/zip"
            assert "attachment" in resp.headers["Content-Disposition"]
            
            # Verify zip headers and correct methods were invoked
            ctx.client_instance.generate_image_batch.assert_called_once_with(
                [{"prompt": "parrot 1"}, {"prompt": "parrot 2"}],
                use_flex=True,
                persist_results=True
            )

    async def test_post_video_single(self, aiohttp_client, mock_client_methods, tmp_path):
        """Verify single video generation returns direct file download via FileResponse."""
        app = web.Application()
        MediaGen.setup(app, route="/api/v1/google/media")
        client = await aiohttp_client(app)

        # Create a dummy video file
        dummy_vid = tmp_path / "gen_video_123.mp4"
        dummy_vid.write_text("fake video contents")

        with mock_client_methods as ctx:
            ctx.client_instance.generate_videos.return_value = _make_mock_message(
                prompt="flying parrot",
                files=[dummy_vid]
            )

            payload = {
                "action": "video",
                "batch": False,
                "prompt": "flying parrot",
                "download_mode": "FileResponse"
            }

            resp = await client.post("/api/v1/google/media", json=payload)
            assert resp.status == 200
            assert resp.headers["Content-Type"] == "video/mp4"
            assert "attachment" in resp.headers["Content-Disposition"]
            body = await resp.read()
            assert body == b"fake video contents"
            
            ctx.client_instance.generate_videos.assert_called_once()

    async def test_post_video_batch(self, aiohttp_client, mock_client_methods, tmp_path):
        """Verify batch video generation processes concurrently and returns zip archive."""
        app = web.Application()
        MediaGen.setup(app, route="/api/v1/google/media")
        client = await aiohttp_client(app)

        # Create two dummy videos
        vid1 = tmp_path / "vid1.mp4"
        vid1.write_text("vid1 data")
        vid2 = tmp_path / "vid2.mp4"
        vid2.write_text("vid2 data")

        with mock_client_methods as ctx:
            ctx.client_instance.generate_video_batch.return_value = [
                _make_mock_message(prompt="video 1", files=[vid1]),
                _make_mock_message(prompt="video 2", files=[vid2])
            ]

            payload = {
                "action": "video",
                "batch": True,
                "prompts": ["video 1", "video 2"],
                "download_mode": "StreamResponse"
            }

            resp = await client.post("/api/v1/google/media", json=payload)
            assert resp.status == 200
            assert resp.headers["Content-Type"] == "application/zip"
            
            # Verify zip headers and correct methods were invoked
            ctx.client_instance.generate_video_batch.assert_called_once_with(
                [{"prompt": "video 1"}, {"prompt": "video 2"}],
                persist_results=True
            )

    async def test_post_video_batch_multipart_preserves_metadata(
        self, aiohttp_client, mock_client_methods, tmp_path
    ):
        """Verify Multipart mode returns metadata (incl. failed items) + file parts."""
        app = web.Application()
        MediaGen.setup(app, route="/api/v1/google/media")
        client = await aiohttp_client(app)

        vid1 = tmp_path / "vid1.mp4"
        vid1.write_text("vid1 data")
        vid2 = tmp_path / "vid2.mp4"
        vid2.write_text("vid2 data")

        with mock_client_methods as ctx:
            # 2 successes + 1 failure: the failure must survive in the metadata part.
            ctx.client_instance.generate_video_batch.return_value = [
                _make_mock_message(prompt="video 1", files=[vid1]),
                RuntimeError("Video generation failed for item 2"),
                _make_mock_message(prompt="video 3", files=[vid2]),
            ]

            payload = {
                "action": "video",
                "batch": True,
                "prompts": ["video 1", "video 2", "video 3"],
                "download_mode": "Multipart",
            }

            resp = await client.post("/api/v1/google/media", json=payload)
            assert resp.status == 200
            assert resp.headers["Content-Type"].startswith("multipart/mixed")

            metadata = None
            file_bodies = []
            reader = MultipartReader.from_response(resp)
            while True:
                part = await reader.next()
                if part is None:
                    break
                if part.headers.get("Content-Type") == "application/json":
                    metadata = await part.json()
                else:
                    file_bodies.append(await part.read(decode=False))

            # Metadata part is present and carries one entry per batch item,
            # including the failed item's error message.
            assert metadata is not None
            assert len(metadata["metadata"]) == 3
            errors = [m for m in metadata["metadata"] if "error" in m]
            assert len(errors) == 1
            assert "item 2" in errors[0]["error"]

            # Both successful videos are delivered as separate binary parts.
            assert file_bodies == [b"vid1 data", b"vid2 data"]

    async def test_post_video_error_comprehensive(self, aiohttp_client, mock_client_methods):
        """Verify that MediaGen dynamically parses embedded error dictionaries on failure."""
        app = web.Application()
        MediaGen.setup(app, route="/api/v1/google/media")
        client = await aiohttp_client(app)

        with mock_client_methods as ctx:
            # Simulate a Google/Veo 3.1 RuntimeError with a dictionary in the string representation
            err_msg = "Video generation failed: {'code': 13, 'message': 'Video generation failed due to an internal server issue.'}"
            ctx.client_instance.generate_videos.side_effect = RuntimeError(err_msg)

            payload = {
                "action": "video",
                "batch": False,
                "prompt": "flying parrot"
            }

            resp = await client.post("/api/v1/google/media", json=payload)
            assert resp.status == 500
            
            data = await resp.json()
            assert "error" in data
            assert data["error"]["code"] == 13
            assert "internal server issue" in data["error"]["message"]
            assert err_msg in data["error"]["details"]
