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


# ---------------------------------------------------------------------------
# FEAT-447 / TASK-2328 — faithful _aggregate_result
# ---------------------------------------------------------------------------


def _envelope(output: object, prompt: str = "q") -> dict:
    """The shape AgentNode.execute() returns (core/node.py)."""
    return {
        "response": None,
        "output": output,
        "execution_time": 0.01,
        "prompt": prompt,
    }


class TestAggregateResultFidelity:
    """`_aggregate_result` must not discard what the scheduler measured."""

    async def test_aggregate_result_total_time(self) -> None:
        """total_time > 0 and approximates now - run_started_at."""
        flow = _make_linear_flow()
        loop = asyncio.get_running_loop()
        run_started_at = loop.time() - 0.25

        result = flow._aggregate_result(
            flow._nodes,
            {"a": _envelope("out_a"), "b": _envelope("out_b")},
            {},
            {"a", "b"},
            set(),
            durations={"a": 0.1, "b": 0.1},
            run_started_at=run_started_at,
        )
        assert result.total_time > 0
        assert result.total_time == pytest.approx(
            loop.time() - run_started_at, abs=0.5
        )
        # The alias and __repr__ follow it (spec AC4).
        assert result.total_execution_time == result.total_time
        assert "time=0.00s" not in repr(result)

    async def test_aggregate_result_execution_log(self) -> None:
        """One entry per completed+failed node, with the five documented keys."""
        flow = _make_partial_flow()
        result = flow._aggregate_result(
            flow._nodes,
            {"a": _envelope("out_a")},
            {"b": RuntimeError("b exploded")},
            {"a"},
            {"b"},
            durations={"a": 0.4, "b": 0.2},
        )
        assert len(result.execution_log) == 2
        for entry in result.execution_log:
            assert set(entry) == {
                "node_id", "node_name", "status", "execution_time", "error",
            }
        by_id = {e["node_id"]: e for e in result.execution_log}
        assert by_id["a"]["status"] == "completed"
        assert by_id["a"]["error"] is None
        assert by_id["a"]["execution_time"] == 0.4
        assert by_id["b"]["status"] == "failed"
        assert "b exploded" in by_id["b"]["error"]
        # Same order as result.nodes.
        assert [e["node_id"] for e in result.execution_log] == [
            n.node_id for n in result.nodes
        ]

    async def test_aggregate_result_metadata_keys(self) -> None:
        """All six metadata keys present and correctly valued."""
        flow = _make_fan_out_flow()
        result = flow._aggregate_result(
            flow._nodes,
            {"a": _envelope("root"), "b": _envelope("branch_b")},
            {"c": RuntimeError("c failed")},
            {"a", "b"},
            {"c"},
            durations={"a": 0.1, "b": 0.1, "c": 0.1},
            skipped={"z", "y"},
        )
        meta = result.metadata
        assert set(meta) == {
            "mode", "node_count", "completed_count", "failed_count",
            "skipped", "leaves",
        }
        # Programmatic flow, no definition and no explicit edges → "legacy".
        assert meta["mode"] == "legacy"
        assert meta["node_count"] == 3
        assert meta["completed_count"] == 2
        assert meta["failed_count"] == 1
        assert meta["skipped"] == ["y", "z"]     # sorted for determinism
        assert meta["leaves"] == ["b"]           # only executed leaf
        # AC12: summary stays empty for AgentsFlow.
        assert result.summary == ""

    async def test_aggregate_result_node_order(self) -> None:
        """[n.node_id for n in result.nodes] == ctx.completion_order."""
        flow = _make_fan_out_flow()
        ctx = FlowContext(initial_task="t")
        # Deliberately NOT alphabetical, and not the set-iteration order.
        for nid in ("c", "a", "b"):
            ctx.mark_completed(nid, result=_envelope(f"out_{nid}"))
        assert ctx.completion_order == ["c", "a", "b"]

        result = flow._aggregate_result(
            flow._nodes,
            {nid: _envelope(f"out_{nid}") for nid in ("a", "b", "c")},
            {},
            {"a", "b", "c"},
            set(),
            ctx=ctx,
        )
        assert [n.node_id for n in result.nodes] == ctx.completion_order

    async def test_aggregate_result_node_order_is_deterministic(self) -> None:
        """Ordering never depends on set-iteration order, with or without ctx."""
        flow = _make_fan_out_flow()
        results = {nid: _envelope(f"out_{nid}") for nid in ("a", "b", "c")}

        # Without ctx: sorted, not hash-ordered.
        no_ctx = flow._aggregate_result(
            flow._nodes, results, {}, {"a", "b", "c"}, set(),
        )
        assert [n.node_id for n in no_ctx.nodes] == ["a", "b", "c"]

        # Repeated aggregation is stable (the union is rebuilt each time).
        for _ in range(5):
            again = flow._aggregate_result(
                flow._nodes, results, {}, {"c", "b", "a"}, set(),
            )
            assert [n.node_id for n in again.nodes] == ["a", "b", "c"]

    async def test_aggregate_result_failed_node_included(self) -> None:
        """A node failed via mark_failed (absent from completion_order) still appears."""
        flow = _make_partial_flow()
        ctx = FlowContext(initial_task="t")
        ctx.mark_completed("a", result=_envelope("out_a"))
        ctx.mark_failed("b", RuntimeError("b exploded"))
        # mark_failed must NOT append to completion_order — that is why the
        # residue has to be appended explicitly.
        assert ctx.completion_order == ["a"]

        result = flow._aggregate_result(
            flow._nodes,
            {"a": _envelope("out_a")},
            {"b": RuntimeError("b exploded")},
            {"a"},
            {"b"},
            ctx=ctx,
        )
        assert [n.node_id for n in result.nodes] == ["a", "b"]
        assert result.failed == ["b"]

    async def test_aggregate_result_backward_compatible_call(self) -> None:
        """Calling without ctx/run_started_at/skipped returns a valid FlowResult."""
        flow = _make_linear_flow()
        # Exactly the pre-FEAT-447 argument list, positional edges/durations.
        result = flow._aggregate_result(
            flow._nodes,
            {"a": _envelope("out_a"), "b": _envelope("out_b")},
            {},
            {"a", "b"},
            set(),
            None,
            {"a": 0.1, "b": 0.2},
        )
        assert isinstance(result, FlowResult)
        assert result.output == "out_b"
        assert result.total_time == 0.0          # no run_started_at supplied
        assert result.metadata["skipped"] == []
        assert len(result.nodes) == 2
        assert len(result.execution_log) == 2


class TestOutputShapeContract:
    """Contract lock for FlowResult.output's scalar-vs-dict polymorphism."""

    async def test_output_single_leaf_is_scalar(self) -> None:
        """Single executed leaf -> scalar output."""
        flow = _make_linear_flow()
        result = await flow.run_flow()
        assert not isinstance(result.output, dict)
        assert result.output == "result_b"
        assert result.metadata["leaves"] == ["b"]

    async def test_output_multi_leaf_is_dict(self) -> None:
        """Fan-out -> dict[node_id, scalar]."""
        flow = _make_fan_out_flow()
        result = await flow.run_flow()
        assert isinstance(result.output, dict)
        assert set(result.output) == {"b", "c"}
        assert result.output == {"b": "branch_b", "c": "branch_c"}
        # Every value is a scalar, never a nested envelope.
        assert not any(
            isinstance(v, dict) and "response" in v for v in result.output.values()
        )
        assert sorted(result.metadata["leaves"]) == ["b", "c"]
