"""Tests for host-independent domain expert bootstrap wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import parrot.cli.loaders as loaders_module
import parrot.experts.bootstrap as bootstrap_module
from parrot.cli.loaders import StandaloneAgentLoader
from parrot.experts.bootstrap import load_experts


@pytest.mark.asyncio
async def test_load_experts_disabled_returns_none() -> None:
    """Disabled discovery does not construct an expert registry."""
    registry = MagicMock()

    result = await load_experts(registry, enabled=False)

    assert result is None
    assert registry.mock_calls == []


@pytest.mark.asyncio
async def test_load_experts_is_fail_open(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """A registry loading error is logged and does not escape to the host."""
    expert_registry = MagicMock()
    expert_registry.load = AsyncMock(side_effect=RuntimeError("expert failure"))
    expert_registry.report.return_value = {"skipped": [], "seeded": {}, "shadowing": {}}
    monkeypatch.setattr(bootstrap_module, "ExpertRegistry", MagicMock(return_value=expert_registry))

    result = await load_experts(MagicMock(), wiki_toolkit=MagicMock())

    assert result is None
    assert "experts: loading failed" in caplog.text


@pytest.mark.asyncio
async def test_standalone_loader_discovers_experts(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """REPL discovery invokes expert loading after YAML definition discovery."""
    calls: list[str] = []
    registry = MagicMock()
    registry.load_modules = AsyncMock(return_value=0)
    registry.discover_config_agents.side_effect = lambda: calls.append("config") or 0
    registry.agents_dir = tmp_path
    (tmp_path / "agents").mkdir()
    registry.load_agent_definitions.side_effect = lambda path: calls.append("definitions") or 0

    async def fake_load_experts(received_registry: MagicMock) -> None:
        assert received_registry is registry
        calls.append("experts")

    monkeypatch.setattr(loaders_module, "agent_registry", registry)
    monkeypatch.setattr(bootstrap_module, "load_experts", fake_load_experts)

    await StandaloneAgentLoader()._ensure_discovered()

    assert calls == ["config", "definitions", "experts"]
