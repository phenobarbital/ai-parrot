"""Session-auth preference of ClaudeAgentClient over ANTHROPIC_API_KEY."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.clients.anthropic import claude_agent as mod
from parrot.clients.anthropic.claude_agent import ClaudeAgentClient

_ALL = (*mod._CLAUDE_CODE_SESSION_MARKERS, *mod._SESSION_AUTH_ENV, mod.PREFER_SESSION_ENV, "ANTHROPIC_API_KEY")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    """Strip every relevant variable and point the config dir at an empty tmp dir."""
    for name in _ALL:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(mod.sys, "platform", "linux")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    return monkeypatch


def _client(**kwargs: object) -> ClaudeAgentClient:
    return ClaudeAgentClient(**kwargs)


def test_no_session_keeps_api_key(clean_env: pytest.MonkeyPatch) -> None:
    assert mod.detect_claude_code_session() is False
    assert _client()._auth_env(None) == {}


def test_session_with_credentials_file_blanks_key(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clean_env.setenv("CLAUDECODE", "1")
    (tmp_path / ".credentials.json").write_text("{}")
    assert _client()._auth_env({"FOO": "1"}) == {"FOO": "1", "ANTHROPIC_API_KEY": ""}


def test_session_with_vertex_blanks_key(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CLAUDE_CODE_SESSION_ID", "abc")
    clean_env.setenv("CLAUDE_CODE_USE_VERTEX", "1")
    assert _client()._auth_env(None) == {"ANTHROPIC_API_KEY": ""}


def test_session_without_credentials_keeps_key(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CLAUDECODE", "1")
    assert _client()._auth_env(None) == {}


def test_explicit_key_in_run_env_wins(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CLAUDECODE", "1")
    clean_env.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    assert _client()._auth_env({"ANTHROPIC_API_KEY": "sk-x"}) == {"ANTHROPIC_API_KEY": "sk-x"}


@pytest.mark.parametrize("via_env", [True, False])
def test_opt_out(clean_env: pytest.MonkeyPatch, via_env: bool) -> None:
    clean_env.setenv("CLAUDECODE", "1")
    clean_env.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    if via_env:
        clean_env.setenv(mod.PREFER_SESSION_ENV, "0")
        client = _client()
    else:
        client = _client(prefer_session_auth=False)
    assert client._auth_env(None) == {}


def test_build_options_carries_blank_key(clean_env: pytest.MonkeyPatch) -> None:
    pytest.importorskip("claude_agent_sdk")
    clean_env.setenv("CLAUDECODE", "1")
    clean_env.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    options = _client()._build_options(prompt="hi")
    assert options.env["ANTHROPIC_API_KEY"] == ""
