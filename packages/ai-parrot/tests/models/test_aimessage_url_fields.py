"""FEAT-601 M12 — URL media fields on AIMessage / AgentResponse (TASK-3715)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage, AgentResponse


def _msg(**kw) -> AIMessage:
    return AIMessage(input="q", output="a", model="gpt-4", provider="openai", usage=CompletionUsage(), **kw)


def test_aimessage_url_fields_validate() -> None:
    """https URLs accepted; filesystem paths and data: URIs rejected."""
    assert _msg(image_urls=["https://x/y.png"]).image_urls == ["https://x/y.png"]
    assert _msg(media_urls=["http://x/y.mp4"]).media_urls == ["http://x/y.mp4"]

    with pytest.raises(ValueError):
        _msg(image_urls=["/tmp/x.png"])

    with pytest.raises(ValueError):
        _msg(image_urls=["data:image/png;base64,AA"])

    with pytest.raises(ValueError):
        _msg(media_urls=["/tmp/x.mp4"])

    with pytest.raises(ValueError):
        _msg(media_urls=["data:image/png;base64,AA"])


def test_url_fields_default_empty_and_paths_untouched(tmp_path: Path) -> None:
    """Defaults are [] and `images` still holds Path objects."""
    msg = _msg(images=[tmp_path / "a.png"])
    assert isinstance(msg.images[0], Path)
    assert msg.image_urls == []
    assert msg.media_urls == []


def test_agent_response_syncs_urls_from_aimessage() -> None:
    """AgentResponse(response=AIMessage(image_urls=[u])) exposes u once (dedup)."""
    url = "https://cdn.example.com/figure.png"
    media_url = "https://cdn.example.com/clip.mp4"
    inner = _msg(image_urls=[url], media_urls=[media_url])

    resp = AgentResponse(response=inner, image_urls=[url])

    assert resp.image_urls == [url]
    assert resp.media_urls == [media_url]


def test_agent_response_rejects_non_http() -> None:
    with pytest.raises(ValueError):
        AgentResponse(image_urls=["file:///x"])
