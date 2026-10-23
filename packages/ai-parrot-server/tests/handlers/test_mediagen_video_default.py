"""MediaGen video action must not hard-code a Veo default model (FEAT-719)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp.test_utils import make_mocked_request

from parrot.handlers.mediagen import MediaGen
from parrot.models import VideoGenerationPrompt


def _handler(payload: dict) -> MediaGen:
    request = make_mocked_request("POST", "/api/v1/google/media")
    request.json = AsyncMock(return_value=payload)
    return MediaGen(request)


def test_video_prompt_defaults_are_registry_driven() -> None:
    prompt = VideoGenerationPrompt(prompt="x")
    assert prompt.model is None
    assert prompt.resolution is None


@pytest.mark.asyncio
async def test_video_without_model_passes_none() -> None:
    fake_client = MagicMock()
    fake_client.generate_videos = AsyncMock(
        return_value=SimpleNamespace(model_dump=lambda mode="json": {}, files=[], media=[])
    )
    fake_client.close = AsyncMock()
    with patch("parrot.clients.google.GoogleGenAIClient", return_value=fake_client):
        await _handler({"action": "video", "prompt": "a lion"}).post()

    sent = fake_client.generate_videos.await_args.kwargs["prompt"]
    assert isinstance(sent, VideoGenerationPrompt)
    assert sent.model is None
