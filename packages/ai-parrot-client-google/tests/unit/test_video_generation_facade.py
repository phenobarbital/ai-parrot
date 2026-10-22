"""FEAT-719 TASK-4583 — registry-routed video façade tests."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from parrot.clients.google import GoogleGenAIClient
from parrot.clients.google.reel.errors import ReelErrorCode, ReelValidationError


def _clip(tmp_path: Path, index: int = 0):
    """Build the adapter result needed by the façade return path."""
    path = tmp_path / f"clip-{index}.mp4"
    return SimpleNamespace(local_path=path)


@pytest.fixture
def client():
    """Create a developer-API client without making a provider call."""
    return GoogleGenAIClient(api_key="k", vertexai=False)


async def test_video_generation_default_routes_omni(client, tmp_path):
    """The developer default resolves to Omni and returns its media paths."""
    clips = [_clip(tmp_path)]
    with patch(
        "parrot.clients.google.reel.omni.OmniClipAdapter.generate_many",
        new=AsyncMock(return_value=clips),
    ) as generate_many, patch("parrot.clients.google.reel.veo.VeoClipAdapter.generate", new=AsyncMock()) as veo:
        message = await client.video_generation("a lion", output_directory=tmp_path)

    generate_many.assert_awaited_once()
    veo.assert_not_awaited()
    assert message.files == [clips[0].local_path]
    assert message.model == "gemini-omni-1.1-flash"


async def test_video_generation_rejects_before_paid_call(client, tmp_path):
    """Unsupported Omni options fail before either adapter is called."""
    with patch(
        "parrot.clients.google.reel.omni.OmniClipAdapter.generate_many",
        new=AsyncMock(),
    ) as generate_many:
        with pytest.raises(ReelValidationError) as exc_info:
            await client.video_generation("a lion", resolution="1080p", output_directory=tmp_path)

    generate_many.assert_not_awaited()
    assert exc_info.value.code is ReelErrorCode.UNSUPPORTED_OPTION


async def test_video_generation_omni_uses_one_multi_output_call(client, tmp_path):
    """Multiple requested outputs are delegated as one Omni request."""
    clips = [_clip(tmp_path, 0), _clip(tmp_path, 1)]
    with patch(
        "parrot.clients.google.reel.omni.OmniClipAdapter.generate_many",
        new=AsyncMock(return_value=clips),
    ) as generate_many:
        await client.video_generation("a lion", number_of_videos=2, output_directory=tmp_path)

    generate_many.assert_awaited_once()
    assert generate_many.await_args.kwargs["number_of_videos"] == 2


async def test_vertex_without_model_is_model_disabled(tmp_path):
    """A Vertex client does not bypass disabled registry defaults."""
    vertex_client = GoogleGenAIClient(api_key="k", vertexai=True)
    with pytest.raises(ReelValidationError) as exc_info:
        await vertex_client.video_generation("a lion", output_directory=tmp_path)

    assert exc_info.value.code is ReelErrorCode.MODEL_DISABLED


def test_facade_signatures_keep_optional_models():
    """Both public façades accept an omitted model for registry resolution."""
    import inspect

    assert inspect.signature(GoogleGenAIClient.video_generation).parameters["model"].default is None
    assert inspect.signature(GoogleGenAIClient.generate_videos).parameters["model"].default is None
