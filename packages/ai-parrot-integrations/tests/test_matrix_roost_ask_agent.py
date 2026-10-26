"""Tests for AgentSwarmToolkit.ask_agent routed over Roost — FEAT-747 TASK-4728."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.matrix.crew.swarm_toolkit import AgentSwarmToolkit
from parrot.integrations.matrix.events import AgentAnswer
from parrot.roost.endpoint import RoostFailure
from parrot.roost.messages import FailureInfo
from parrot.roost.performatives import FailureCode


def _toolkit(endpoint):
    """Build a toolkit with mocked collaborators, like test_matrix_swarm_toolkit.py."""
    tunnels = AsyncMock()
    tunnel = AsyncMock()
    tunnel.ask.return_value = AgentAnswer(answer="tunnel", metadata={"status": "ok"})
    tunnels.get_or_create.return_value = tunnel
    tunnels.config = MagicMock(echo_summary_to_channel=False)
    registry = AsyncMock()
    registry.get.side_effect = lambda n: MagicMock(agent_name=n) if n in ("peer", "analyst") else None
    registry.all_agents.return_value = []
    kwargs = {"endpoint": endpoint} if endpoint is not None else {}
    tk = AgentSwarmToolkit("analyst", tunnels, registry, MagicMock(), AsyncMock(), **kwargs)
    return tk, tunnel


@pytest.mark.asyncio
async def test_routes_through_endpoint():
    ep = MagicMock()
    ep.query = AsyncMock(return_value="42")
    tk, tunnel = _toolkit(ep)
    out = await tk.ask_agent("peer", "q")
    assert out["answer"] == "42"
    assert out["metadata"]["via"] == "roost"
    ep.query.assert_awaited_once()
    assert ep.query.await_args.kwargs["receiver"].name == "peer"
    tunnel.ask.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,status",
    [
        (FailureCode.HOP_LIMIT, "hop_limit"),
        (FailureCode.TIMEOUT, "timeout"),
        (FailureCode.POLICY, "refused"),
        (FailureCode.INTERNAL, "error"),
    ],
)
async def test_failure_status_mapping(code, status):
    ep = MagicMock()
    ep.query = AsyncMock(side_effect=RoostFailure(FailureInfo(code=code)))
    tk, _ = _toolkit(ep)
    out = await tk.ask_agent("peer", "q")
    assert out["status"] == status


@pytest.mark.asyncio
async def test_prechecks_stay_authoritative():
    ep = MagicMock()
    ep.query = AsyncMock()
    tk, _ = _toolkit(ep)
    assert (await tk.ask_agent("ghost", "q"))["status"] == "unknown_agent"
    ep.query.assert_not_called()


@pytest.mark.asyncio
async def test_no_endpoint_uses_tunnel():
    tk, tunnel = _toolkit(None)
    out = await tk.ask_agent("peer", "q")
    assert out["answer"] == "tunnel"
    tunnel.ask.assert_awaited_once()
