"""Unit tests for the crew Google-credential helpers (FEAT-575, TASK-3451)."""

import logging

import pytest

from parrot.bots.flows.crew.credentials import (
    GOOGLE_PROVIDER_KEYS,
    apply_google_api_key,
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


class _FakeAgent:
    """Minimal stand-in for a constructed, unconfigured AbstractBot."""

    _default_llm = "google"

    def __init__(self, llm=None, llm_kwargs=None):
        self._llm_raw = llm
        # Mirror abstract.py:516 — assignment BY REFERENCE, not a copy.
        self._llm_kwargs = llm_kwargs if llm_kwargs is not None else {}


def test_apply_injects_for_google_without_credential(crew_key):
    agent = _FakeAgent(llm="google:gemini-3.5-flash")
    assert apply_google_api_key(agent, crew_key) is True
    assert agent._llm_kwargs["api_key"] == crew_key


def test_apply_does_not_mutate_definition_dict(crew_key):
    # The dict an AgentDefinition would own, passed in by reference.
    definition_llm_kwargs = {"temperature": 0.1}
    agent = _FakeAgent(llm="google", llm_kwargs=definition_llm_kwargs)
    assert apply_google_api_key(agent, crew_key) is True
    # AC7: the credential must never reach the definition's dict. NOTE: this
    # asserts only the absence of api_key — AbstractBot itself writes
    # temperature/max_tokens into this same dict (abstract.py:517-518), so the
    # dict is NOT otherwise pristine and must not be compared for equality.
    assert "api_key" not in definition_llm_kwargs
    assert agent._llm_kwargs is not definition_llm_kwargs


@pytest.mark.parametrize(
    "llm_kwargs",
    [
        {"api_key": "own"},
        {"credentials_file": "/tmp/sa.json"},
        {"credentials": object()},
        {"vertexai": True},
    ],
)
def test_apply_respects_explicit_credential(crew_key, llm_kwargs):
    original = dict(llm_kwargs)
    agent = _FakeAgent(llm="google", llm_kwargs=llm_kwargs)
    assert apply_google_api_key(agent, crew_key) is False
    assert agent._llm_kwargs == original


def test_apply_skips_non_google_and_falsy_key(crew_key):
    non_google_agent = _FakeAgent(llm="openai:gpt-5")
    assert apply_google_api_key(non_google_agent, crew_key) is False

    google_agent = _FakeAgent(llm="google")
    assert apply_google_api_key(google_agent, None) is False


def test_apply_class_level_llm_declaration(crew_key):
    class _ClassLevelLlmAgent(_FakeAgent):
        llm = "google:gemini-3.5-flash"

        def __init__(self, llm=None, llm_kwargs=None):
            # Mirror abstract.py:448-452 — a class-level `llm` attribute is
            # honoured when no `llm` arg arrives.
            if llm is None:
                _cls_llm = getattr(type(self), "llm", None)
                if _cls_llm is not None and not isinstance(_cls_llm, property):
                    llm = _cls_llm
            super().__init__(llm=llm, llm_kwargs=llm_kwargs)

    agent = _ClassLevelLlmAgent()
    assert apply_google_api_key(agent, crew_key) is True
    assert agent._llm_kwargs["api_key"] == crew_key


def test_apply_ignores_non_abstractbot_agent(crew_key):
    class _NotAnAgent:
        pass

    assert apply_google_api_key(_NotAnAgent(), crew_key) is False
