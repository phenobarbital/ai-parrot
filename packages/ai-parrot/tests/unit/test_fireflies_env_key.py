"""Unit tests for create_fireflies_mcp_server env-var key fallback (FEAT-237).

Tests the three key behaviours:
  1. An explicit api_key argument wins over the env var.
  2. When api_key is omitted, FIREFLIES_API_KEY is resolved via navconfig.config.
  3. When neither is provided, ValueError is raised mentioning FIREFLIES_API_KEY.
"""
from __future__ import annotations

import pytest

from parrot.mcp import integration
from parrot.mcp.integration import create_fireflies_mcp_server


def _auth_header(cfg) -> str:
    """Return the last element of cfg.args, which holds the Authorization header value."""
    # args = ["mcp-remote", api_base, "--header", "Authorization: Bearer <key>"]
    return cfg.args[-1]


def test_create_fireflies_uses_explicit_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit api_key wins over any env-var value."""
    monkeypatch.setattr(integration.config, "get", lambda *a, **k: "env-key")
    cfg = create_fireflies_mcp_server(api_key="explicit-key")
    assert "Bearer explicit-key" in _auth_header(cfg)


def test_create_fireflies_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no api_key argument, FIREFLIES_API_KEY is resolved via navconfig.config."""
    monkeypatch.setattr(
        integration.config,
        "get",
        lambda key, *a, **k: "env-key-123" if key == "FIREFLIES_API_KEY" else None,
    )
    cfg = create_fireflies_mcp_server()
    assert "Bearer env-key-123" in _auth_header(cfg)


def test_create_fireflies_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """No explicit api_key and no env var → ValueError mentioning FIREFLIES_API_KEY."""
    monkeypatch.setattr(integration.config, "get", lambda *a, **k: None)
    with pytest.raises(ValueError, match="FIREFLIES_API_KEY"):
        create_fireflies_mcp_server()


def test_create_fireflies_bearer_header_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolved key is embedded as 'Authorization: Bearer <key>' in args."""
    monkeypatch.setattr(integration.config, "get", lambda *a, **k: None)
    cfg = create_fireflies_mcp_server(api_key="my-secret-key")
    assert _auth_header(cfg) == "Authorization: Bearer my-secret-key"


def test_create_fireflies_stdio_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """Transport remains stdio regardless of key source."""
    monkeypatch.setattr(integration.config, "get", lambda *a, **k: None)
    cfg = create_fireflies_mcp_server(api_key="any-key")
    assert cfg.transport == "stdio"
    assert cfg.command == "npx"


def test_create_fireflies_default_api_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default api_base is the canonical Fireflies MCP endpoint."""
    monkeypatch.setattr(integration.config, "get", lambda *a, **k: None)
    cfg = create_fireflies_mcp_server(api_key="k")
    assert "https://api.fireflies.ai/mcp" in cfg.args


def test_create_fireflies_explicit_key_none_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """Passing api_key=None explicitly triggers env-var fallback (not a ValueError)."""
    monkeypatch.setattr(
        integration.config,
        "get",
        lambda key, *a, **k: "fallback-key" if key == "FIREFLIES_API_KEY" else None,
    )
    cfg = create_fireflies_mcp_server(api_key=None)
    assert "Bearer fallback-key" in _auth_header(cfg)
