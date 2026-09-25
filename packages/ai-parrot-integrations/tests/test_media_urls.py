"""FEAT-601 M12 — parse_response carries URL media separately (TASK-3716)."""
from __future__ import annotations

from pathlib import Path

from parrot.integrations.parser import parse_response
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AgentResponse, AIMessage


def _ai_message(**overrides: object) -> AIMessage:
    """Build a minimal valid AIMessage for parser tests."""
    kwargs = {
        "input": "question",
        "output": "answer",
        "model": "test-model",
        "provider": "test-provider",
        "usage": CompletionUsage(),
    }
    kwargs.update(overrides)
    return AIMessage(**kwargs)


def test_parse_response_keeps_urls_and_paths(tmp_path: Path) -> None:
    """URLs survive; an existing Path is kept in images; a missing Path is still dropped."""
    real = tmp_path / "a.png"
    real.write_bytes(b"fake-png-bytes")
    missing = tmp_path / "missing.png"

    message = _ai_message(
        images=[real, missing],
        image_urls=["https://h/f.png"],
        media_urls=["https://h/v.mp4"],
    )

    parsed = parse_response(message)

    assert parsed.images == [real]
    assert parsed.image_urls == ["https://h/f.png"]
    assert parsed.media_urls == ["https://h/v.mp4"]


def test_parse_response_agent_response_roundtrip() -> None:
    """AgentResponse wrapping an AIMessage exposes the URLs once (sync_documents_and_paths + inner copy dedup)."""
    inner = _ai_message(
        image_urls=["https://h/inner.png"],
        media_urls=["https://h/inner.mp4"],
    )
    agent_response = AgentResponse(response=inner)

    # sync_documents_and_paths (model_validator) already merged the inner URLs
    # into the outer AgentResponse's own image_urls/media_urls.
    assert agent_response.image_urls == ["https://h/inner.png"]
    assert agent_response.media_urls == ["https://h/inner.mp4"]

    parsed = parse_response(agent_response)

    # Copying from both the outer AgentResponse and the inner AIMessage must
    # not duplicate entries.
    assert parsed.image_urls == ["https://h/inner.png"]
    assert parsed.media_urls == ["https://h/inner.mp4"]


def test_parse_response_plain_string_has_no_urls() -> None:
    assert parse_response("hi").image_urls == []
    assert parse_response("hi").media_urls == []
