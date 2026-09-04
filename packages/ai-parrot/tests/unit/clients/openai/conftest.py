"""Shared fixtures for parrot.clients.openai unit tests (FEAT-523, TASK-2842)."""

import pytest


@pytest.fixture
def upstream_current_models() -> set:
    """Snapshot of https://developers.openai.com/api/docs/models/all
    as fetched on 2026-08-20. Update when upstream changes."""
    return {
        "gpt-5.6",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.5",
        "gpt-5.5-pro",
        "gpt-5.4",
        "gpt-5.4-pro",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5.3-codex",
        "gpt-5.2",
        "gpt-5.2-pro",
        "gpt-5.1",
        "gpt-5",
        "gpt-5-pro",
        "gpt-5-mini",
        "gpt-5-nano",
        "chat-latest",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4o-mini",
        "o3",
        "o3-pro",
        "gpt-realtime-2.1",
        "gpt-realtime-2.1-mini",
        "gpt-realtime-2",
        "gpt-realtime-translate",
        "gpt-realtime-whisper",
        "gpt-realtime",
        "gpt-realtime-1.5",
        "gpt-audio",
        "gpt-audio-1.5",
        "gpt-transcribe",
        "gpt-live-transcribe",
        "gpt-image-2",
    }
