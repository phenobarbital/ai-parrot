import pytest

from parrot.clients import detection


@pytest.fixture
def no_providers(monkeypatch):
    monkeypatch.setattr("parrot.clients.factory.LLMFactory.list_providers", lambda: {})


@pytest.fixture
def claude_code_only(monkeypatch):
    monkeypatch.setattr(
        "parrot.clients.factory.LLMFactory.list_providers",
        lambda: {"claude-code": "ai-parrot-client-anthropic"},
    )


@pytest.fixture
def codex_code_only(monkeypatch):
    monkeypatch.setattr(
        "parrot.clients.factory.LLMFactory.list_providers",
        lambda: {"codex-code": "ai-parrot-client-openai"},
    )


@pytest.fixture
def both_providers(monkeypatch):
    monkeypatch.setattr(
        "parrot.clients.factory.LLMFactory.list_providers",
        lambda: {
            "claude-code": "ai-parrot-client-anthropic",
            "codex-code": "ai-parrot-client-openai",
        },
    )


def test_returns_none_when_no_providers(no_providers, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _bin: None)
    assert detection.detect_coding_agent_llm() is None


def test_returns_claude_code_spec(claude_code_only, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/claude" if b == "claude" else None)
    assert detection.detect_coding_agent_llm() == "claude-code:claude-haiku-4-5-20251001"


def test_returns_codex_spec(codex_code_only, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/codex" if b == "codex" else None)
    assert detection.detect_coding_agent_llm() == "codex-code:gpt-5.1-codex"


def test_claude_wins_when_both_available(both_providers, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _bin: "/usr/bin/" + _bin)
    assert detection.detect_coding_agent_llm() == "claude-code:claude-haiku-4-5-20251001"


def test_registered_but_binary_missing(both_providers, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _bin: None)
    assert detection.detect_coding_agent_llm() is None
