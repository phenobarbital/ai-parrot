"""FEAT-877 Module 3 — own-class rule, resolution and AgentToolkit."""

from __future__ import annotations

import pytest

from parrot.bots.agent import Agent, BasicAgent
from parrot.mcp.agent_toolkit import AgentExposureError, exposed_methods, own_coroutine_methods
from parrot.registry.registry import MCPLocalExposure


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
