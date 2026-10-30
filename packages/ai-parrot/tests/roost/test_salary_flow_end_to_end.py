"""Driving flow — the salary question end to end with a stubbed LLM (FEAT-747 M13)."""

from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from parrot.bots.abstract import AbstractBot
from parrot.registry import AgentRegistry
from parrot.roost import (
    CarrierKind,
    GatingDispatcher,
    GrantPolicy,
    HandlerRegistry,
    InProcessCarrier,
    InterAgentGrant,
    ProtocolEngine,
    RoostAgentConfig,
    RoostEndpoint,
)


CALLER_CTX = object()  # opaque stand-in for a PermissionContext (FEAT-747 / issue:59d1cb0c9814)


class _DummyBot(AbstractBot):
    """Minimal bot class used only for registration."""


class SalaryRecord(BaseModel):
    """Structured salary answer returned by the deterministic HR tool."""

    employee_id: str
    amount: int
    currency: str


def _endpoint(
    name: str,
    carrier: InProcessCarrier,
    cfg: Optional[RoostAgentConfig],
    *,
    tool_result: object = None,
    registry: Optional[AgentRegistry] = None,
    permission_context: object = CALLER_CTX,
) -> RoostEndpoint:
    """Build one endpoint with a stubbed tool manager and a stubbed (never-LLM) wake callback."""
    eng = ProtocolEngine()
    disp = GatingDispatcher(self_name=name, config=cfg, engine=eng, handlers=HandlerRegistry(), grant=GrantPolicy())
    tm = MagicMock()
    tm.execute_tool = AsyncMock(return_value=tool_result)
    return RoostEndpoint(
        agent_name=name,
        config=cfg,
        engine=eng,
        dispatcher=disp,
        carriers={CarrierKind.IN_PROCESS: carrier},
        tool_manager=tm,
        wake=AsyncMock(return_value=None),
        registry=registry,
        permission_context=permission_context,
    )


@pytest.mark.asyncio
async def test_salary_question_end_to_end(tmp_path: Path) -> None:
    """A granted caller resolves HR through the directory and gets the native struct, without waking."""
    hr_cfg = RoostAgentConfig(
        capabilities=["hr.people.salary"],
        categories=["hr.people"],
        keywords=["salary"],
        backing="deterministic",
    )
    caller_cfg = RoostAgentConfig(grant=InterAgentGrant(scopes=["hr.*"]))
    registry = AgentRegistry(agents_dir=tmp_path / "agents")
    registry.register("hr", _DummyBot, roost=hr_cfg)
    registry.register("caller", _DummyBot, roost=caller_cfg)

    record = SalaryRecord(employee_id="E-17", amount=100_000, currency="EUR")
    carrier = InProcessCarrier()
    hr = _endpoint("hr", carrier, hr_cfg, tool_result=record)
    caller = _endpoint("caller", carrier, caller_cfg, registry=registry)
    await hr.start()
    await caller.start()
    try:
        result = await caller.request("hr.people.salary", {"employee_id": "E-17"}, timeout=1)

        assert result is record
        assert caller.metrics["wakes"] == 0
        caller.wake.assert_not_awaited()
        assert hr.metrics["wakes"] == 0
        hr.tool_manager.execute_tool.assert_awaited_once()
        assert hr.tool_manager.execute_tool.await_args.args[0] == "hr_people_salary"
    finally:
        await caller.stop()
        await hr.stop()
        await carrier.close()
