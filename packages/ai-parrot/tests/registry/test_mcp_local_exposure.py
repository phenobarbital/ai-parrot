"""FEAT-877 Module 1 — `mcp_local` exposure declaration in the registry."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from parrot.bots.agent import Agent
from parrot.registry import registry as registry_module
from parrot.registry.registry import AgentRegistry, BotConfig, MCPLocalExposure


@pytest.fixture
def isolated_registry(tmp_path: Path) -> AgentRegistry:
    """Return an AgentRegistry rooted in tmp_path, never the global registry."""
    return AgentRegistry(agents_dir=tmp_path / "agents")


@pytest.fixture
def definition_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect definition writes from the module-level AGENTS_DIR into tmp_path."""
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path)
    return tmp_path


def _write_definition(registry: AgentRegistry, body: dict) -> Path:
    path = registry.agents_dir / "agents" / "general" / f"{body['agent']['name']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path


def _agent(name: str = "finance") -> dict:
    return {"name": name, "class_name": "BasicAgent", "module": "parrot.bots.agent"}


def test_yaml_mcp_local_true_coerces(isolated_registry: AgentRegistry) -> None:
    """A YAML true declaration enables unrestricted local MCP exposure."""
    path = _write_definition(isolated_registry, {"agent": _agent(), "mcp_local": True})

    assert isolated_registry.load_agent_definition_file(path)
    assert isolated_registry.get_metadata("finance").bot_config.mcp_local == MCPLocalExposure()


def test_yaml_mcp_local_allow(isolated_registry: AgentRegistry) -> None:
    """A YAML allowlist becomes the exposure model allowlist."""
    path = _write_definition(isolated_registry, {"agent": _agent(), "mcp_local": {"allow": ["forecast"]}})

    assert isolated_registry.load_agent_definition_file(path)
    assert isolated_registry.get_metadata("finance").bot_config.mcp_local == MCPLocalExposure(allow=["forecast"])


@pytest.mark.parametrize("value", [None, False])
def test_yaml_mcp_local_absent_or_false(isolated_registry: AgentRegistry, value: object) -> None:
    """Absent and false YAML declarations leave local MCP exposure undeclared."""
    definition = {"agent": _agent()}
    if value is not None:
        definition["mcp_local"] = value
    path = _write_definition(isolated_registry, definition)

    assert isolated_registry.load_agent_definition_file(path)
    assert isolated_registry.get_metadata("finance").bot_config.mcp_local is None


def test_yaml_mcp_local_unknown_key_rejected(isolated_registry: AgentRegistry) -> None:
    """Unknown mcp_local keys are rejected by the strict Pydantic model."""
    path = _write_definition(
        isolated_registry,
        {"agent": _agent(), "mcp_local": {"allow": ["forecast"], "expose": True}},
    )

    with pytest.raises(ValueError):
        isolated_registry.load_agent_definition_file(path)


def test_decorator_mcp_local_kwarg(isolated_registry: AgentRegistry) -> None:
    """Decorator declarations use the same coercion as YAML declarations."""

    @isolated_registry.register_bot_decorator(name="finance", mcp_local={"allow": ["forecast"]})
    class FinanceAgent(Agent):
        async def forecast(self, months: int) -> dict:
            """Forecast."""
            return {"months": months}

    @isolated_registry.register_bot_decorator(name="all-tools", mcp_local=True)
    class AllToolsAgent(Agent):
        pass

    @isolated_registry.register_bot_decorator(name="undeclared")
    class UndeclaredAgent(Agent):
        pass

    assert isolated_registry.get_metadata("finance").bot_config.mcp_local == MCPLocalExposure(allow=["forecast"])
    assert isolated_registry.get_metadata("all-tools").bot_config.mcp_local == MCPLocalExposure()
    assert isolated_registry.get_metadata("undeclared").bot_config.mcp_local is None


def test_definition_roundtrip_keeps_mcp_local(isolated_registry: AgentRegistry, definition_root: Path) -> None:
    """Definition writes preserve an exposure declaration and omit absent ones."""
    config = BotConfig(
        name="finance",
        class_name="BasicAgent",
        module="parrot.bots.agent",
        mcp_local={"allow": ["forecast"]},
    )
    path = isolated_registry.create_agent_definition(config)

    assert yaml.safe_load(path.read_text(encoding="utf-8"))["mcp_local"] == {"enabled": True, "allow": ["forecast"]}
    assert isolated_registry.load_agent_definition_file(path)
    assert isolated_registry.get_metadata("finance").bot_config.mcp_local == config.mcp_local

    no_exposure = BotConfig(name="none", class_name="BasicAgent", module="parrot.bots.agent")
    no_exposure_path = isolated_registry.create_agent_definition(no_exposure)
    assert "mcp_local" not in yaml.safe_load(no_exposure_path.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_load_modules_sync_matches_async(isolated_registry: AgentRegistry) -> None:
    """The sync discovery entry point retains the asynchronous method's count."""
    (isolated_registry.agents_dir / "simple.py").write_text("VALUE = 1\n", encoding="utf-8")

    assert isolated_registry.load_modules_sync() == 1
    assert await isolated_registry.load_modules() == 1
