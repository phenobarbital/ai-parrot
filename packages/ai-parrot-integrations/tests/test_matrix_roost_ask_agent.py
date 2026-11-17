"""Tests for AgentSwarmToolkit.ask_agent routed over Roost — FEAT-747 TASK-4728."""

import re
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
        (FailureCode.SCHEMA, "schema_error"),
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


# --- FEAT-786: fail-closed endpoint callers -----------------------------------------------------


@pytest.mark.asyncio
async def test_grant_denied_maps_to_refused():
    from parrot.roost.grant import GrantDenied

    ep = MagicMock()
    ep.query = AsyncMock(side_effect=GrantDenied("peer"))
    tk, _ = _toolkit(ep)
    out = await tk.ask_agent("peer", "q")
    assert out == {"status": "refused", "detail": "grant denied: peer"}


@pytest.mark.asyncio
async def test_pre_execute_context_is_bound_only_during_the_query():
    from parrot.auth.context import _pctx_var

    seen = []

    async def _query(*args, **kwargs):
        seen.append(_pctx_var.get())
        return "42"

    ep = MagicMock()
    ep.query = AsyncMock(side_effect=_query)
    tk, _ = _toolkit(ep)
    pctx = object()
    await tk._pre_execute("ask_agent", agent="peer", question="q", _permission_context=pctx)
    out = await tk.ask_agent("peer", "q")
    assert out["answer"] == "42"
    assert seen == [pctx]
    assert _pctx_var.get() is None


@pytest.mark.asyncio
async def test_concurrent_calls_keep_their_own_context():
    import asyncio

    from parrot.auth.context import _pctx_var

    seen = {}

    async def _query(question, **kwargs):
        await asyncio.sleep(0.01)
        seen[question] = _pctx_var.get()
        return question

    ep = MagicMock()
    ep.query = AsyncMock(side_effect=_query)
    tk, _ = _toolkit(ep)
    a, b = object(), object()

    async def _call(pctx, question):
        await tk._pre_execute("ask_agent", _permission_context=pctx)
        return await tk.ask_agent("peer", question)

    await asyncio.gather(asyncio.create_task(_call(a, "qa")), asyncio.create_task(_call(b, "qb")))
    assert seen == {"qa": a, "qb": b}


@pytest.mark.asyncio
async def test_toolkit_tool_path_binds_the_tool_manager_context():
    """Through the generated ToolkitTool: the ``_permission_context`` kwarg reaches the endpoint."""
    from parrot.auth.context import _pctx_var

    seen = []

    async def _query(*args, **kwargs):
        seen.append(_pctx_var.get())
        return "42"

    ep = MagicMock()
    ep.query = AsyncMock(side_effect=_query)
    tk, _ = _toolkit(ep)
    tool = next(t for t in tk.get_tools() if t.name.endswith("ask_agent"))
    pctx = MagicMock()
    await tool.execute(agent="peer", question="q", _permission_context=pctx)
    assert seen == [pctx]
    assert _pctx_var.get() is None


# --- FEAT-825: conversation id carriage, hop / expected_schema forwarding -----------------------


@pytest.mark.asyncio
async def test_success_metadata_carries_the_conversation_id():
    ep = MagicMock()
    ep.query = AsyncMock(return_value="42")
    tk, _ = _toolkit(ep)
    out = await tk.ask_agent("peer", "q")
    sent = ep.query.await_args.kwargs["conversation_id"]
    assert re.fullmatch(r"[0-9a-f]{32}", sent)
    assert out["metadata"] == {"via": "roost", "status": "ok", "conversation_id": sent}


@pytest.mark.asyncio
async def test_each_call_gets_its_own_conversation_id():
    ep = MagicMock()
    ep.query = AsyncMock(return_value="42")
    tk, _ = _toolkit(ep)
    first = await tk.ask_agent("peer", "q1")
    second = await tk.ask_agent("peer", "q2")
    assert first["metadata"]["conversation_id"] != second["metadata"]["conversation_id"]


@pytest.mark.asyncio
async def test_failure_carries_the_conversation_id():
    ep = MagicMock()
    ep.query = AsyncMock(side_effect=RoostFailure(FailureInfo(code=FailureCode.TIMEOUT, detail="query timed out")))
    tk, _ = _toolkit(ep)
    out = await tk.ask_agent("peer", "q")
    sent = ep.query.await_args.kwargs["conversation_id"]
    assert out == {"status": "timeout", "detail": "query timed out", "conversation_id": sent}


@pytest.mark.asyncio
async def test_forwards_hops_and_expected_schema():
    from parrot.integrations.matrix.crew import context as ctx

    ep = MagicMock()
    ep.query = AsyncMock(return_value={"n": 1})
    tk, _ = _toolkit(ep)
    schema = {"type": "object", "required": ["n"]}
    token = ctx.current_hops.set(3)
    try:
        await tk.ask_agent("peer", "q", expected_schema=schema, timeout=7)
    finally:
        ctx.current_hops.reset(token)
    kwargs = ep.query.await_args.kwargs
    assert kwargs["hops"] == 3
    assert kwargs["expected_schema"] is schema
    assert kwargs["timeout"] == 7


def _real_endpoint(name, carrier, *, config, wake=None):
    """A real ``RoostEndpoint`` over the in-process carrier (same wiring as the core Roost tests)."""
    from parrot.roost.endpoint import RoostEndpoint
    from parrot.roost.gating import GatingDispatcher, HandlerRegistry
    from parrot.roost.grant import GrantPolicy
    from parrot.roost.performatives import CarrierKind
    from parrot.roost.protocols import ProtocolEngine

    engine = ProtocolEngine()
    dispatcher = GatingDispatcher(
        self_name=name, config=config, engine=engine, handlers=HandlerRegistry(), grant=GrantPolicy()
    )
    tool_manager = MagicMock()
    tool_manager.execute_tool = AsyncMock()
    return RoostEndpoint(
        agent_name=name,
        config=config,
        engine=engine,
        dispatcher=dispatcher,
        carriers={CarrierKind.IN_PROCESS: carrier},
        tool_manager=tool_manager,
        wake=wake,
        permission_context=object(),
        sweep_interval=0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("hops,expected_status", [(0, "ok"), (8, "hop_limit")])
async def test_hop_budget_is_enforced_over_real_endpoints(hops, expected_status):
    """``ctx.current_hops`` reaches the wire: at the engine's hop limit (8) the ask fails with ``hop_limit``."""
    from parrot.integrations.matrix.crew import context as ctx
    from parrot.roost.carriers.inprocess import InProcessCarrier
    from parrot.roost.directory import InterAgentGrant, RoostAgentConfig
    from parrot.roost.performatives import Performative

    carrier = InProcessCarrier()
    served = []

    async def wake(msg, dispatch):
        served.append(msg)
        return msg.reply(Performative.INFORM, content="pong")

    peer = _real_endpoint("peer", carrier, config=RoostAgentConfig(capabilities=["s.x"]), wake=wake)
    analyst = _real_endpoint("analyst", carrier, config=RoostAgentConfig(grant=InterAgentGrant(scopes=["*"])))
    await peer.start()
    await analyst.start()
    tk, tunnel = _toolkit(analyst)
    token = ctx.current_hops.set(hops)
    try:
        out = await tk.ask_agent("peer", "ping", timeout=2)
    finally:
        ctx.current_hops.reset(token)
        await analyst.stop()
        await peer.stop()

    tunnel.ask.assert_not_called()
    if expected_status == "ok":
        assert out["answer"] == "pong"
        assert out["metadata"]["status"] == "ok"
        assert [msg.conversation_id for msg in served] == [out["metadata"]["conversation_id"]]
        assert [msg.hops for msg in served] == [1]
    else:
        assert out["status"] == "hop_limit"
        assert served == []
        assert analyst.engine.state(out["conversation_id"]) is not None
