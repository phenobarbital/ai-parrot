"""Unit tests for AgentsFlow event-driven scheduler — FEAT-163 TASK-1067.

Tests verify:
- run_flow works end-to-end for a linear A→B flow with mocked agents.
- No asyncio.gather in the flow module source.
- Concurrent run_flow() calls on the same instance do not share FSM state.
- on_complete hooks fire and receive (ctx, result).
- A hook that raises does NOT change FlowResult.status.
- Single-leaf flow: output is scalar.
- Multi-leaf flow (fan-out): output is a dict.
- FlowResult has status "completed" when all nodes succeed.
- FlowResult has status "failed" when all nodes fail.
- FlowResult has status "partial" when some succeed, some fail.
"""
import asyncio
import inspect

import pytest
from unittest.mock import AsyncMock

from parrot.bots.flows.flow import AgentsFlow, NODE_REGISTRY, register_node
from parrot.bots.flows.core.node import AgentNode, Node
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.result import FlowResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeAgent:
    """Minimal AgentLike stub for scheduler tests."""

    def __init__(self, name: str, response: str = "ok", fail: bool = False) -> None:
        self._name = name
        self._response = response
        self._fail = fail

    @property
    def name(self) -> str:
        return self._name

    async def invoke(self, prompt: str, **kwargs: object) -> object:
        return self._response

    async def ask(self, question: str = "", **kwargs: object) -> object:
        if self._fail:
            raise RuntimeError(f"{self._name} failed intentionally")
        return type("R", (), {"content": self._response})()


def _make_linear_flow(agent_a_response: str = "result_a", agent_b_response: str = "result_b") -> AgentsFlow:
    """Build a simple linear A → B AgentsFlow using programmatic add_node."""
    agent_a = FakeAgent("agent_a", response=agent_a_response)
    agent_b = FakeAgent("agent_b", response=agent_b_response)

    node_a = AgentNode(agent=agent_a, node_id="a", dependencies=set(), successors={"b"})
    node_b = AgentNode(agent=agent_b, node_id="b", dependencies={"a"}, successors=set())

    flow = AgentsFlow("linear-test")
    flow.add_node(node_a)
    flow.add_node(node_b)
    return flow


def _make_fan_out_flow() -> AgentsFlow:
    """Build a fan-out flow: A → B, A → C (two leaves)."""
    agent_a = FakeAgent("agent_a", response="root")
    agent_b = FakeAgent("agent_b", response="branch_b")
    agent_c = FakeAgent("agent_c", response="branch_c")

    node_a = AgentNode(agent=agent_a, node_id="a", dependencies=set(), successors={"b", "c"})
    node_b = AgentNode(agent=agent_b, node_id="b", dependencies={"a"}, successors=set())
    node_c = AgentNode(agent=agent_c, node_id="c", dependencies={"a"}, successors=set())

    flow = AgentsFlow("fan-out-test")
    flow.add_node(node_a)
    flow.add_node(node_b)
    flow.add_node(node_c)
    return flow


def _make_failing_flow() -> AgentsFlow:
    """Build a single-node flow where the node always fails."""
    agent = FakeAgent("bad_agent", fail=True)
    node = AgentNode(agent=agent, node_id="a", dependencies=set(), successors=set())
    flow = AgentsFlow("failing-test")
    flow.add_node(node)
    return flow


def _make_partial_flow() -> AgentsFlow:
    """A → B where B always fails (A succeeds, B fails → partial)."""
    node_a = AgentNode(agent=FakeAgent("a"), node_id="a", dependencies=set(), successors={"b"})
    node_b = AgentNode(agent=FakeAgent("b", fail=True), node_id="b", dependencies={"a"}, successors=set())
    flow = AgentsFlow("partial-test")
    flow.add_node(node_a)
    flow.add_node(node_b)
    return flow


# ---------------------------------------------------------------------------
# Source-level checks
# ---------------------------------------------------------------------------


class TestSchedulerSourceConstraints:
    def test_no_asyncio_gather_in_flow_module(self) -> None:
        """run_flow must never call asyncio.gather — verified in source."""
        import parrot.bots.flows.flow as flow_module

        src = inspect.getsource(flow_module)
        assert "asyncio.gather" not in src, (
            "asyncio.gather found in flow.py — forbidden by scheduler design."
        )


# ---------------------------------------------------------------------------
# Basic scheduling
# ---------------------------------------------------------------------------


class TestSchedulerBasics:
    async def test_empty_flow_returns_flow_result(self) -> None:
        flow = AgentsFlow("empty")
        result = await flow.run_flow()
        assert isinstance(result, FlowResult)

    async def test_linear_flow_returns_completed_status(self) -> None:
        flow = _make_linear_flow()
        result = await flow.run_flow()
        assert str(result.status) in ("completed", "FlowStatus.COMPLETED")

    async def test_linear_flow_has_two_responses(self) -> None:
        flow = _make_linear_flow()
        result = await flow.run_flow()
        assert "a" in result.responses
        assert "b" in result.responses

    async def test_single_leaf_output_is_scalar(self) -> None:
        """Linear A→B: leaf is B, output should be B's result (not a dict)."""
        flow = _make_linear_flow(agent_b_response="final_answer")
        result = await flow.run_flow()
        # output is scalar (not dict) for a single-leaf flow
        assert not isinstance(result.output, dict)

    async def test_fan_out_output_is_dict(self) -> None:
        """Fan-out A→B, A→C: two leaves, output is a dict."""
        flow = _make_fan_out_flow()
        result = await flow.run_flow()
        assert isinstance(result.output, dict)
        assert len(result.output) == 2


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


class TestSchedulerFailures:
    async def test_failing_node_status_is_failed(self) -> None:
        flow = _make_failing_flow()
        result = await flow.run_flow()
        assert str(result.status) in ("failed", "FlowStatus.FAILED")

    async def test_partial_flow_status_is_partial(self) -> None:
        flow = _make_partial_flow()
        result = await flow.run_flow()
        assert str(result.status) in ("partial", "FlowStatus.PARTIAL")

    async def test_failing_node_id_in_errors(self) -> None:
        flow = _make_failing_flow()
        result = await flow.run_flow()
        assert "a" in result.errors


# ---------------------------------------------------------------------------
# Concurrent run safety
# ---------------------------------------------------------------------------


class TestSchedulerConcurrency:
    async def test_concurrent_runs_do_not_share_fsm_state(self) -> None:
        """Two concurrent run_flow() calls must NOT corrupt each other's FSM."""
        flow = _make_linear_flow()
        r1, r2 = await asyncio.gather(
            flow.run_flow(),
            flow.run_flow(),
        )
        assert r1.status.value == "completed"
        assert r2.status.value == "completed"


# ---------------------------------------------------------------------------
# on_complete hooks
# ---------------------------------------------------------------------------


class TestOnCompleteHooks:
    async def test_hook_fires_with_ctx_and_result(self) -> None:
        flow = _make_linear_flow()
        received: list = []

        async def hook(ctx: object, result: FlowResult) -> None:
            received.append((ctx, result))

        await flow.run_flow(on_complete=(hook,))
        assert len(received) == 1
        assert isinstance(received[0][1], FlowResult)

    async def test_multiple_hooks_fire_in_order(self) -> None:
        flow = _make_linear_flow()
        order: list = []

        async def hook1(ctx: object, result: FlowResult) -> None:
            order.append(1)

        async def hook2(ctx: object, result: FlowResult) -> None:
            order.append(2)

        await flow.run_flow(on_complete=(hook1, hook2))
        assert order == [1, 2]

    async def test_hook_exception_does_not_change_status(self) -> None:
        flow = _make_linear_flow()

        async def broken_hook(ctx: object, result: FlowResult) -> None:
            raise RuntimeError("hook boom")

        result = await flow.run_flow(on_complete=(broken_hook,))
        # Status should still be completed despite hook failure
        assert str(result.status) in ("completed", "FlowStatus.COMPLETED")

    async def test_ctx_passed_to_hook(self) -> None:
        flow = _make_linear_flow()
        received_ctx: list = []

        async def hook(ctx: object, result: FlowResult) -> None:
            received_ctx.append(ctx)

        ctx = FlowContext(initial_task="hello")
        await flow.run_flow(ctx=ctx, on_complete=(hook,))
        assert received_ctx[0] is ctx
