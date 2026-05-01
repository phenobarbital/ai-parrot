"""Shared fixtures for parrot/models unit tests."""
import pytest


@pytest.fixture
def upstream_current_models() -> set:
    """Snapshot of https://developers.openai.com/api/docs/models/all
    as fetched on 2026-04-29. Update when upstream changes."""
    return {
        "gpt-5.5", "gpt-5.5-pro", "gpt-5.4", "gpt-5.4-pro",
        "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5", "gpt-5-mini",
        "gpt-5-nano", "gpt-5.3-chat-latest", "gpt-5.2-chat-latest",
        "gpt-5.3-codex", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
        "gpt-4o-mini", "gpt-4", "o3", "o3-pro",
        "gpt-realtime", "gpt-realtime-1.5",
        "gpt-audio", "gpt-audio-1.5",
        "gpt-image-2", "gpt-image-1.5", "gpt-image-1-mini",
    }
