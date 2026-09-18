"""Unit tests for the crew Google-credential helpers (FEAT-575, TASK-3451)."""
import logging

import pytest

from parrot.bots.flows.crew.credentials import (
    GOOGLE_PROVIDER_KEYS,
    get_crew_google_api_key,
    is_google_llm,
)


@pytest.fixture
def crew_key(monkeypatch):
    """Set CREW_AI_KEY and reset the warn-once latch for one test."""
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", "crew-test-key", raising=False)
    monkeypatch.setattr("parrot.bots.flows.crew.credentials._warned_unset", False, raising=False)
    return "crew-test-key"


@pytest.fixture
def no_crew_key(monkeypatch):
    """Unset CREW_AI_KEY and reset the warn-once latch for one test."""
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", None, raising=False)
    monkeypatch.setattr("parrot.bots.flows.crew.credentials._warned_unset", False, raising=False)


def test_google_provider_keys_are_the_three_entry_points():
    assert GOOGLE_PROVIDER_KEYS == frozenset({"google", "gemini-live", "google-compat"})


@pytest.mark.parametrize(
    "value,expected",
    [
        ("google", True),
        ("google:gemini-3.5-flash", True),
        ("GOOGLE", True),
        ("gemini-live", True),
        ("google-compat:x", True),
        ("openai:gpt-5", False),
        ("anthropic", False),
    ],
)
def test_is_google_llm_strings(value, expected):
    assert is_google_llm(value) is expected


def test_is_google_llm_none_uses_default_provider():
    assert is_google_llm(None, default_provider="google") is True
    assert is_google_llm(None, default_provider="openai") is False


def test_is_google_llm_instance_is_false():
    # A trivial object stands in for a live AbstractClient instance: it is
    # neither None, a str, nor a type, so is_google_llm must return False
    # unconditionally regardless of what class the instance belongs to
    # (AC2 — a live instance already carries its own credentials).
    class _FakeClientInstance:
        pass

    assert is_google_llm(_FakeClientInstance()) is False


def test_is_google_llm_class():
    pytest.importorskip("parrot.clients.google")
    from parrot.clients.google import GoogleGenAIClient

    assert is_google_llm(GoogleGenAIClient) is True

    class _NonGoogleClient:
        pass

    assert is_google_llm(_NonGoogleClient) is False


def test_get_key_returns_configured_value(crew_key):
    assert get_crew_google_api_key() == crew_key


def test_get_key_warns_once_when_unset(no_crew_key, caplog):
    with caplog.at_level(logging.WARNING, logger="parrot.bots.flows.crew.credentials"):
        first = get_crew_google_api_key()
        second = get_crew_google_api_key()

    assert first is None
    assert second is None

    warning_records = [record for record in caplog.records if "CREW_AI_KEY" in record.getMessage()]
    assert len(warning_records) == 1

    for record in caplog.records:
        assert "crew-test-key" not in record.getMessage()
