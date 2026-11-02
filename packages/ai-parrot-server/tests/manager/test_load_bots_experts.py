"""Tests for domain expert runtime wiring in BotManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import parrot.experts.bootstrap as bootstrap_module
import parrot.manager.manager as manager_module
from parrot.manager.manager import BotManager


def _manager_with_registry(monkeypatch: pytest.MonkeyPatch, registry: MagicMock, **kwargs: bool) -> BotManager:
    """Create a manager isolated from shared registry and Redis state."""
    monkeypatch.setattr(manager_module, "agent_registry", registry)
    monkeypatch.setattr(manager_module, "CrewRedis", MagicMock())
    return BotManager(enable_database_bots=False, enable_crews=False, **kwargs)


def _registry(tmp_path, calls: list[str]) -> MagicMock:
    """Create the minimal registry contract exercised by ``load_bots``."""
    registry = MagicMock()
    registry.agents_dir = tmp_path
    (tmp_path / "agents").mkdir()
    registry.setup.side_effect = lambda app: calls.append("setup")
    registry.load_modules = AsyncMock(side_effect=lambda: calls.append("modules"))
    registry.discover_config_agents.side_effect = lambda: calls.append("config") or 0
    registry.load_agent_definitions.side_effect = lambda path: calls.append("definitions") or 0
    registry.instantiate_startup_agents = AsyncMock(side_effect=lambda app: calls.append("startup") or {})
    return registry


@pytest.mark.asyncio
async def test_bot_manager_load_bots_wires_experts(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Expert loading runs between YAML definitions and startup agents."""
    calls: list[str] = []
    registry = _registry(tmp_path, calls)

    async def fake_load_experts(received_registry: MagicMock, *, enabled: bool) -> None:
        assert received_registry is registry
        assert enabled is True
        calls.append("experts")

    monkeypatch.setattr(bootstrap_module, "load_experts", fake_load_experts)
    manager = _manager_with_registry(monkeypatch, registry, enable_registry_bots=True)
    manager._process_startup_results = AsyncMock()

    await manager.load_bots(MagicMock())

    assert calls == ["setup", "modules", "config", "definitions", "experts", "startup"]


@pytest.mark.asyncio
async def test_enable_experts_false_skips(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """The expert flag reaches bootstrap and disables expert construction."""
    calls: list[str] = []
    registry = _registry(tmp_path, calls)
    load_experts = AsyncMock()
    monkeypatch.setattr(bootstrap_module, "load_experts", load_experts)
    manager = _manager_with_registry(monkeypatch, registry, enable_registry_bots=True, enable_experts=False)
    manager._process_startup_results = AsyncMock()

    await manager.load_bots(MagicMock())

    load_experts.assert_awaited_once_with(registry, enabled=False)


@pytest.mark.asyncio
async def test_expert_reachable_through_get_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    """A registry singleton remains reachable through the manager fallback."""
    expert = MagicMock(name="cve-analyst")
    expert.is_configured = True
    registry = MagicMock()
    registry.has.side_effect = lambda name: name == "cve-analyst"
    registry.get_instance = AsyncMock(return_value=expert)
    registry.evaluator = None
    manager = _manager_with_registry(monkeypatch, registry, enable_registry_bots=False)

    result = await manager.get_bot("cve-analyst")

    assert result is expert
    registry.get_instance.assert_awaited_once_with("cve-analyst")
