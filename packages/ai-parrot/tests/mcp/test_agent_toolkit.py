"""FEAT-877 Module 3 — own-class rule, resolution and AgentToolkit."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from parrot.bots.agent import Agent, BasicAgent
from parrot.mcp.agent_tools import mcp_tool
from parrot.mcp.agent_toolkit import (
    AgentExposureError,
    discover_agents,
    exposed_methods,
    list_exposable_agents,
    own_coroutine_methods,
    resolve_exposable_agent,
)
from parrot.registry.registry import AgentRegistry, MCPLocalExposure


class AuditMixin:
    """A user mixin: not an AbstractBot subclass → its names are reserved."""

    async def audit(self) -> str:
        return "audit"


class FinanceBase(Agent):
    """An author's intermediate base: an own class."""

    async def reconcile(self, account: str) -> dict:
        """Reconcile one account."""
        return {"account": account}


class FinanceAgent(AuditMixin, FinanceBase):
    async def forecast(self, months: int) -> dict:
        """Forecast cash for the next `months` months."""
        return {"months": months}

    async def configure(self, app=None) -> None:
        return None

    async def ask(self, question: str, **kwargs) -> None:
        return None

    def sync_helper(self) -> int:
        return 1

    async def _private(self) -> None:
        return None


def test_own_methods_exclude_framework() -> None:
    assert list(own_coroutine_methods(FinanceAgent)) == ["forecast", "reconcile"]


def test_own_override_of_framework_name_excluded() -> None:
    methods = own_coroutine_methods(FinanceAgent)
    assert "configure" not in methods
    assert "ask" not in methods


def test_mixin_methods_excluded() -> None:
    assert "audit" not in own_coroutine_methods(FinanceAgent)


def test_intermediate_user_base_included() -> None:
    assert own_coroutine_methods(FinanceAgent)["reconcile"] is FinanceBase.reconcile


def test_sync_and_private_excluded() -> None:
    class SyncForecastAgent(FinanceAgent):
        def forecast(self, months: int) -> dict:
            return {"months": months}

    methods = own_coroutine_methods(SyncForecastAgent)
    assert "sync_helper" not in methods
    assert "_private" not in methods
    assert "forecast" not in methods


def test_allow_narrows() -> None:
    methods = exposed_methods(FinanceAgent, MCPLocalExposure(allow=["reconcile"]))
    assert list(methods) == ["reconcile"]


def test_allow_unknown_entry_fails() -> None:
    with pytest.raises(AgentExposureError) as error:
        exposed_methods(FinanceAgent, MCPLocalExposure(allow=["forecast", "shutdown", "nope"]))

    assert "allow entries are not own-class public async methods" in str(error.value)
    assert "shutdown" in str(error.value)
    assert "nope" in str(error.value)


def test_ask_never_allowlistable() -> None:
    with pytest.raises(AgentExposureError, match=r"\(ask/ask_stream are never exposed\)"):
        exposed_methods(FinanceAgent, MCPLocalExposure(allow=["ask"]))


def test_generic_class_has_no_candidates() -> None:
    with pytest.raises(AgentExposureError, match="defines no exposable methods"):
        exposed_methods(BasicAgent, MCPLocalExposure(), agent_name="x")


@pytest.fixture
def isolated_registry(tmp_path: Path) -> AgentRegistry:
    """Create a registry rooted in temporary agent definitions."""
    return AgentRegistry(agents_dir=tmp_path / "agents")


def _yaml_agent(registry: AgentRegistry, name: str, agent: dict, mcp_local: object = True) -> None:
    """Write one standalone agent definition for discovery."""
    path = registry.agents_dir / "agents" / "general" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    body: dict = {"agent": {"name": name, **agent}}
    if mcp_local is not None:
        body["mcp_local"] = mcp_local
    path.write_text(yaml.safe_dump(body), encoding="utf-8")


def test_undeclared_agent_refused(isolated_registry: AgentRegistry) -> None:
    """Undeclared and disabled decorator registrations are refused."""
    isolated_registry.register_bot_decorator(name="finance")(FinanceAgent)
    isolated_registry.register_bot_decorator(name="disabled", mcp_local={"enabled": False})(FinanceAgent)

    with pytest.raises(AgentExposureError, match="is not declared for local MCP exposure"):
        resolve_exposable_agent("finance", isolated_registry)
    with pytest.raises(AgentExposureError, match="is not declared for local MCP exposure"):
        resolve_exposable_agent("disabled", isolated_registry)


def test_unknown_agent_suggests(isolated_registry: AgentRegistry) -> None:
    """Unknown names include close registered matches."""
    isolated_registry.register_bot_decorator(name="finance", mcp_local=True)(FinanceAgent)

    with pytest.raises(AgentExposureError, match=r"Unknown agent 'financ'.*finance"):
        resolve_exposable_agent("financ", isolated_registry)


def test_remote_agent_refused(isolated_registry: AgentRegistry) -> None:
    """Remote agent definitions cannot be served over stdio."""
    _yaml_agent(isolated_registry, "remote", {"kind": "a2a", "endpoint": "http://127.0.0.1:1"})

    with pytest.raises(AgentExposureError, match="is a a2a agent"):
        resolve_exposable_agent("remote", isolated_registry)


def test_yaml_basic_agent_nothing_to_expose(isolated_registry: AgentRegistry) -> None:
    """A generic YAML BasicAgent has no own methods to expose."""
    _yaml_agent(isolated_registry, "plain", {"class_name": "BasicAgent", "module": "parrot.bots.agent"})

    with pytest.raises(AgentExposureError, match="defines no exposable methods"):
        resolve_exposable_agent("plain", isolated_registry)


def test_yaml_custom_class_resolves(isolated_registry: AgentRegistry) -> None:
    """YAML classes are imported without instantiation and narrowed by allow."""
    _yaml_agent(
        isolated_registry,
        "fin",
        {"class_name": "FinanceAgent", "module": FinanceAgent.__module__},
        mcp_local={"allow": ["forecast"]},
    )

    resolved = resolve_exposable_agent("fin", isolated_registry)

    assert resolved.methods == {"forecast": FinanceAgent.forecast}


def test_duplicate_tool_names_fail(isolated_registry: AgentRegistry) -> None:
    """Two methods may not map to the same MCP tool name."""

    class ForecastArgs(BaseModel):
        months: int

    class ForecastResult(BaseModel):
        total: int

    class DuplicateToolAgent(Agent):
        async def forecast(self, months: int) -> dict:
            return {"total": months}

        @mcp_tool(
            name="forecast",
            description="Forecast a total.",
            args_schema=ForecastArgs,
            returns=ForecastResult,
            scope="agent:x",
        )
        async def predict(self, months: int) -> dict:
            return {"total": months}

    isolated_registry.register_bot_decorator(name="duplicate", mcp_local=True)(DuplicateToolAgent)

    with pytest.raises(AgentExposureError, match="methods forecast and predict both map to tool name 'forecast'"):
        resolve_exposable_agent("duplicate", isolated_registry)


def test_list_exposable_agents_skips_broken(isolated_registry: AgentRegistry, caplog: pytest.LogCaptureFixture) -> None:
    """Broken declared agents do not hide healthy local agents from listing."""
    isolated_registry.register_bot_decorator(name="good agent", mcp_local={"allow": ["forecast"]})(FinanceAgent)
    isolated_registry.register_bot_decorator(name="undeclared")(FinanceAgent)
    _yaml_agent(isolated_registry, "broken", {"class_name": "BasicAgent", "module": "parrot.bots.agent"})

    agents = list_exposable_agents(isolated_registry)

    assert [(agent.name, agent.section_name, agent.tools) for agent in agents] == [
        ("good agent", "agent-good-agent", ["forecast"])
    ]
    assert "agent broken not exposable" in caplog.text
    assert "undeclared" not in [agent.name for agent in agents]


def test_discovery_runs_once(isolated_registry: AgentRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    """Discovery is memoized per registry object."""
    calls = 0
    original = isolated_registry.load_modules_sync

    def counted_load_modules() -> int:
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(isolated_registry, "load_modules_sync", counted_load_modules)

    discover_agents(isolated_registry)
    discover_agents(isolated_registry)

    assert calls == 1
