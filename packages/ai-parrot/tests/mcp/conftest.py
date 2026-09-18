"""Shared fixtures for `packages/ai-parrot/tests/mcp/` (FEAT-570, TASK-3381)."""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def repo_with_hosts(tmp_path, monkeypatch):
    """A temp repo wired for all three MCP hosts, with Google redirected.

    Google's primary config is USER-GLOBAL (~/.gemini/config/mcp_config.json,
    verified: google/assets.py:59). Redirecting it here — rather than in each test —
    makes it impossible for a case to write into the developer's real home.
    """
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"wikitoolkit": {"command": "/bin/true", "args": ["mcp"], "env": {}}}}),
        encoding="utf-8",
    )
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text("", encoding="utf-8")
    gemini = tmp_path / "gemini_home" / "mcp_config.json"
    gemini.parent.mkdir(parents=True)
    gemini.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setattr("parrot.knowledge.wiki.google.assets.default_mcp_config_path", lambda: gemini)
    monkeypatch.chdir(tmp_path)
    return tmp_path
