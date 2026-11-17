"""Tests for MatrixCrewAgentWrapper.handle_roost_wake — FEAT-827 TASK-5247."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.matrix.crew import context as ctx
from parrot.integrations.matrix.crew.config import MatrixCrewAgentEntry
from parrot.integrations.matrix.crew.crew_wrapper import MatrixCrewAgentWrapper
from parrot.integrations.matrix.crew.swarm_toolkit import AgentSwarmToolkit
from parrot.roost.carriers.inprocess import InProcessCarrier
from parrot.roost.directory import InterAgentGrant, RoostAgentConfig
from parrot.roost.endpoint import RoostEndpoint
from parrot.roost.gating import GatingDispatcher, HandlerRegistry
from parrot.roost.grant import GrantPolicy
from parrot.roost.messages import AgentAddress, LocalEnvelope, RoostMessage
from parrot.roost.performatives import CarrierKind, FailureCode, InteractionProtocol, Performative
from parrot.roost.protocols import ProtocolEngine

pytestmark = pytest.mark.asyncio


def _wrapper(name="writer"):
    registry = AsyncMock()
    wrapper = MatrixCrewAgentWrapper(
        name,
        MatrixCrewAgentEntry(chatbot_id=name, display_name=name.title(), mxid_localpart=f"parrot-{name}"),
        AsyncMock(),
        registry,
        MagicMock(),
        "parrot.local",
        streaming=False,
    )
    return wrapper, registry


def _query(*, hops=0, content="ping", envelope=None, **kw):
    base = dict(
        performative=Performative.QUERY,
        protocol=InteractionProtocol.QUERY,
        conversation_id="c1",
        sender=AgentAddress(name="analyst"),
        receivers=[AgentAddress(name="writer")],
        content=content,
        envelope=envelope,
        hops=hops,
    )
    base.update(kw)
    return RoostMessage(**base)


def _bot(**kw):
    bot = MagicMock()
    bot.ask = AsyncMock(**kw)
    return bot


async def _wake(wrapper, msg, bot):
    with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=bot)):
        return await wrapper.handle_roost_wake(msg, MagicMock())


async def test_inbound_hop_depth_is_the_turn_depth_and_is_restored():
    wrapper, _ = _wrapper()
    seen = []

    async def _ask(prompt):
        seen.append(ctx.current_hops.get())
        return "pong"

    outer = ctx.current_hops.set(1)
    try:
        reply = await _wake(wrapper, _query(hops=4), _bot(side_effect=_ask))
        assert seen == [4]
        assert ctx.current_hops.get() == 1
    finally:
        ctx.current_hops.reset(outer)
    assert reply.performative is Performative.INFORM


async def test_hop_depth_is_restored_after_a_failed_turn():
    wrapper, _ = _wrapper()
    await _wake(wrapper, _query(hops=4), _bot(side_effect=RuntimeError("boom")))
    assert ctx.current_hops.get() == 0


async def test_inform_reply_carries_text_and_tokens():
    wrapper, registry = _wrapper()
    msg = _query()
    response = SimpleNamespace(to_text="pong", usage=SimpleNamespace(total_tokens=42))
    bot = _bot(return_value=response)
    reply = await _wake(wrapper, msg, bot)
    assert reply.performative is Performative.INFORM
    assert reply.content == "pong" and reply.tokens == 42
    assert reply.conversation_id == "c1" and reply.in_reply_to == msg.message_id
    assert reply.sender.name == "writer" and [r.name for r in reply.receivers] == ["analyst"]
    prompt = bot.ask.await_args.args[0]
    assert "analyst" in prompt and "ping" in prompt
    assert [call.args[1] for call in registry.update_status.await_args_list] == ["busy", "ready"]


async def test_plain_string_response_reports_no_tokens():
    wrapper, _ = _wrapper()
    reply = await _wake(wrapper, _query(), _bot(return_value="pong"))
    assert reply.content == "pong" and reply.tokens == 0


async def test_structured_question_is_serialized_into_the_prompt():
    wrapper, _ = _wrapper()
    bot = _bot(return_value="ok")
    await _wake(wrapper, _query(content={"metric": "q2"}), bot)
    assert '{"metric": "q2"}' in bot.ask.await_args.args[0]


async def test_bot_error_becomes_an_internal_failure_without_leaking_the_message():
    wrapper, registry = _wrapper()
    reply = await _wake(wrapper, _query(), _bot(side_effect=RuntimeError("secret dsn")))
    assert reply.performative is Performative.FAILURE
    assert reply.failure.code is FailureCode.INTERNAL and reply.failure.detail == "RuntimeError"
    assert registry.update_status.await_args_list[-1].args[1] == "ready"


async def test_missing_bot_becomes_an_internal_failure():
    wrapper, _ = _wrapper()
    reply = await _wake(wrapper, _query(), None)
    assert reply.performative is Performative.FAILURE and reply.failure.code is FailureCode.INTERNAL


async def test_envelope_budget_bounds_the_turn():
    wrapper, _ = _wrapper()

    async def _slow(prompt):
        await asyncio.sleep(5)

    envelope = LocalEnvelope(correlation_id="c1", caller="analyst", budget_ms=20)
    reply = await _wake(wrapper, _query(envelope=envelope), _bot(side_effect=_slow))
    assert reply.performative is Performative.FAILURE and reply.failure.code is FailureCode.TIMEOUT


async def test_messages_that_are_not_addressed_queries_are_not_served():
    wrapper, registry = _wrapper()
    inform = _query(performative=Performative.INFORM, protocol=InteractionProtocol.INFORM)
    broadcast = _query(receivers=[], capability_filter="s.x")
    get_bot = AsyncMock()
    with patch("parrot.manager.BotManager.get_bot", get_bot):
        assert await wrapper.handle_roost_wake(inform, MagicMock()) is None
        assert await wrapper.handle_roost_wake(broadcast, MagicMock()) is None
    get_bot.assert_not_awaited()
    registry.update_status.assert_not_awaited()


async def test_a_registry_failure_after_the_turn_does_not_lose_the_reply():
    wrapper, registry = _wrapper()
    registry.update_status.side_effect = [None, RuntimeError("board down")]
    reply = await _wake(wrapper, _query(), _bot(return_value="pong"))
    assert reply.performative is Performative.INFORM and reply.content == "pong"


# --- chain depth: real endpoints for one hop, the toolkit seam for the onward hop ---------------
#
# A full A -> B -> A chain over real endpoints cannot be exercised yet: an agent woken by a query
# cannot receive the reply to its own onward query (issue:a409d14b8130 — the in-process carrier
# serves one message at a time and the wake runs inline), so the onward call always times out.
# The two halves of the chain are therefore pinned separately.

HOP_LIMIT = 4


def _endpoint(name, carrier, wake=None):
    config = RoostAgentConfig(capabilities=[f"{name}.answer"], grant=InterAgentGrant(scopes=["*"]))
    engine = ProtocolEngine(default_hop_limit=HOP_LIMIT)
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


def _toolkit(name, endpoint):
    tunnels = AsyncMock()
    tunnels.config = MagicMock(echo_summary_to_channel=False)
    crew_registry = AsyncMock()
    crew_registry.get.side_effect = lambda n: MagicMock(agent_name=n) if n in ("analyst", "writer") else None
    return AgentSwarmToolkit(name, tunnels, crew_registry, MagicMock(), AsyncMock(), endpoint=endpoint)


async def test_a_served_turn_asks_onward_at_the_inbound_depth():
    """The served agent's own ``ask_agent`` continues the chain: inbound depth 3 → onward ``hops=3``."""
    wrapper, _ = _wrapper("writer")
    onward = MagicMock()
    onward.query = AsyncMock(return_value="fine")
    toolkit = _toolkit("writer", onward)

    async def _ask(prompt):
        out = await toolkit.ask_agent("analyst", "and you?")
        return out["answer"]

    reply = await _wake(wrapper, _query(hops=3), _bot(side_effect=_ask))

    assert reply.performative is Performative.INFORM and reply.content == "fine"
    assert onward.query.await_args.kwargs["hops"] == 3


@pytest.mark.parametrize("caller_depth,expected", [(2, "ok"), (HOP_LIMIT, "hop_limit")])
async def test_one_hop_over_real_endpoints_seeds_the_served_depth(caller_depth, expected):
    """analyst → writer over two real endpoints, writer served by ``handle_roost_wake``."""
    carrier = InProcessCarrier()
    wrapper, _ = _wrapper("writer")
    writer = _endpoint("writer", carrier, wrapper.handle_roost_wake)
    analyst = _endpoint("analyst", carrier)
    toolkit = _toolkit("analyst", analyst)
    depths = []

    async def _ask(prompt):
        depths.append(ctx.current_hops.get())
        return SimpleNamespace(to_text="pong", usage=SimpleNamespace(total_tokens=7))

    await writer.start()
    await analyst.start()
    token = ctx.current_hops.set(caller_depth)
    try:
        with patch("parrot.manager.BotManager.get_bot", AsyncMock(return_value=_bot(side_effect=_ask))):
            out = await toolkit.ask_agent("writer", "ping", timeout=5)
    finally:
        ctx.current_hops.reset(token)
        await analyst.stop()
        await writer.stop()

    if expected == "ok":
        assert out["answer"] == "pong" and out["metadata"]["status"] == "ok"
        assert depths == [caller_depth + 1]
    else:
        assert out["status"] == "hop_limit"
        assert depths == []
