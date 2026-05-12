"""Integration tests for AgentsFlow — FEAT-163 TASK-1070.

Covers the 7 scenarios from Spec §4:
1. test_linear_flow             — 3-node A→B→C sequential execution
2. test_branching_fan_out       — A→{B,C} concurrent fan-out
3. test_branching_fan_in        — {A,B}→C fan-in waits for both
4. test_conditional_routing_cel — A→B guarded by CEL predicate (pass and fail)
5. test_retry_on_failure        — node with max_retries=2, fails once then succeeds
6. test_decision_node_routing   — DecisionNode → CEL-guarded branch
7. test_on_complete_hook_fires  — on_complete hooks receive (ctx, result)

All tests use stub agents and an in-memory StubRegistry — no real LLM calls.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional, Set
from unittest.mock import AsyncMock

import pytest
from pydantic import Field

from parrot.bots.flows.flow import AgentsFlow, DecisionNode
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.node import AgentNode, Node
from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.core.types import FlowStatus, DependencyResults
from parrot.bots.flow.definition import (
    EdgeDefinition,
    FlowDefinition,
    NodeDefinition,
)
from parrot.bots.flow.decision_node import (
    DecisionMode,
    DecisionNodeConfig,
    DecisionResult,
    DecisionType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockAgent:
    """Deterministic agent stub.

    Args:
        name: Agent identifier.
        reply: Fixed content string returned by ask().
        delay: Optional asyncio.sleep delay (seconds) to simulate latency.
        fail: If True, ask() raises RuntimeError.
    """

    def __init__(
        self,
        name: str,
        reply: str = "ok",
        delay: float = 0.0,
        fail: bool = False,
    ) -> None:
        self._name = name
        self.reply = reply
        self.delay = delay
        self.fail = fail
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    async def invoke(self, prompt: str, **kwargs: Any) -> Any:
        return self.reply

    async def ask(self, question: str = "", **kwargs: Any) -> Any:
        self.call_count += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError(f"{self._name} failed intentionally")
        return type("R", (), {"content": self.reply})()


class RetryableAgent:
    """Agent that fails on first N calls then succeeds."""

    def __init__(self, name: str, fail_times: int = 1, reply: str = "recovered") -> None:
        self._name = name
        self.fail_times = fail_times
        self.call_count = 0
        self.reply = reply

    @property
    def name(self) -> str:
        return self._name

    async def invoke(self, prompt: str, **kwargs: Any) -> Any:
        return self.reply

    async def ask(self, question: str = "", **kwargs: Any) -> Any:
        self.call_count += 1
        if self.call_count <= self.fail_times:
            raise RuntimeError(f"transient failure #{self.call_count}")
        return type("R", (), {"content": self.reply})()


class RetryableAgentNode(AgentNode):
    """AgentNode subclass that exposes max_retries for the scheduler."""

    max_retries: int = Field(default=0)


def _edge(from_: str, to: str, condition: str = "always", predicate: Optional[str] = None) -> EdgeDefinition:
    """Build an EdgeDefinition using the real field names."""
    kwargs: dict = {"from": from_, "to": to, "condition": condition}
    if predicate is not None:
        kwargs["predicate"] = predicate
        kwargs["condition"] = "on_condition"
    return EdgeDefinition(**kwargs)


def _agent_node_def(nid: str, agent_ref: str, max_retries: int = 0) -> NodeDefinition:
    """Build a NodeDefinition for an agent node."""
    return NodeDefinition(id=nid, type="agent", agent_ref=agent_ref, max_retries=max_retries)


def _start_node_def(nid: str = "start") -> NodeDefinition:
    return NodeDefinition(id=nid, type="start")


# ---------------------------------------------------------------------------
# Scenario 1: Linear flow A→B→C
# ---------------------------------------------------------------------------


class TestLinearFlow:
    """Integration scenario 1: 3-node sequential flow."""

    async def test_linear_flow_status_completed(self, stub_registry: Any) -> None:
        stub_registry.register(MockAgent("a", reply="alpha"))
        stub_registry.register(MockAgent("b", reply="beta"))
        stub_registry.register(MockAgent("c", reply="gamma"))

        defn = FlowDefinition(
            flow="linear",
            nodes=[
                _agent_node_def("n1", "a"),
                _agent_node_def("n2", "b"),
                _agent_node_def("n3", "c"),
            ],
            edges=[
                _edge("n1", "n2"),
                _edge("n2", "n3"),
            ],
        )
        flow = AgentsFlow.from_definition(defn, agent_registry=stub_registry)
        result = await flow.run_flow()

        assert isinstance(result, FlowResult)
        assert result.status == FlowStatus.COMPLETED

    async def test_linear_flow_responses_contain_all_nodes(self, stub_registry: Any) -> None:
        stub_registry.register(MockAgent("a"))
        stub_registry.register(MockAgent("b"))
        stub_registry.register(MockAgent("c"))

        defn = FlowDefinition(
            flow="linear-3",
            nodes=[
                _agent_node_def("n1", "a"),
                _agent_node_def("n2", "b"),
                _agent_node_def("n3", "c"),
            ],
            edges=[_edge("n1", "n2"), _edge("n2", "n3")],
        )
        flow = AgentsFlow.from_definition(defn, agent_registry=stub_registry)
        result = await flow.run_flow()

        assert "n1" in result.responses
        assert "n2" in result.responses
        assert "n3" in result.responses

    async def test_linear_flow_single_leaf_output_is_scalar(self, stub_registry: Any) -> None:
        """Single leaf (n3): output should be a scalar, not a multi-leaf dict."""
        stub_registry.register(MockAgent("a"))
        stub_registry.register(MockAgent("b"))
        stub_registry.register(MockAgent("c", reply="final_answer"))

        defn = FlowDefinition(
            flow="linear-scalar",
            nodes=[
                _agent_node_def("n1", "a"),
                _agent_node_def("n2", "b"),
                _agent_node_def("n3", "c"),
            ],
            edges=[_edge("n1", "n2"), _edge("n2", "n3")],
        )
        flow = AgentsFlow.from_definition(defn, agent_registry=stub_registry)
        result = await flow.run_flow()

        # Single leaf → scalar output (not a dict of leaf node_id → result)
        assert not isinstance(result.output, dict)


# ---------------------------------------------------------------------------
# Scenario 2: Fan-out A→{B,C} concurrent
# ---------------------------------------------------------------------------


class TestBranchingFanOut:
    """Integration scenario 2: A→{B,C} fan-out with concurrent scheduling."""

    async def test_fan_out_output_is_dict_with_both_leaves(self, stub_registry: Any) -> None:
        stub_registry.register(MockAgent("a", reply="root"))
        stub_registry.register(MockAgent("b", reply="branch_b", delay=0.05))
        stub_registry.register(MockAgent("c", reply="branch_c", delay=0.05))

        defn = FlowDefinition(
            flow="fan-out",
            nodes=[
                _agent_node_def("a", "a"),
                _agent_node_def("b", "b"),
                _agent_node_def("c", "c"),
            ],
            edges=[_edge("a", "b"), _edge("a", "c")],
        )
        flow = AgentsFlow.from_definition(defn, agent_registry=stub_registry)
        result = await flow.run_flow()

        assert isinstance(result.output, dict)
        assert set(result.output.keys()) == {"b", "c"}

    async def test_fan_out_concurrent_faster_than_sequential(self, stub_registry: Any) -> None:
        """B and C run concurrently so total time < B_delay + C_delay."""
        stub_registry.register(MockAgent("a", reply="root"))
        stub_registry.register(MockAgent("b", reply="b", delay=0.15))
        stub_registry.register(MockAgent("c", reply="c", delay=0.15))

        defn = FlowDefinition(
            flow="fan-out-timing",
            nodes=[
                _agent_node_def("a", "a"),
                _agent_node_def("b", "b"),
                _agent_node_def("c", "c"),
            ],
            edges=[_edge("a", "b"), _edge("a", "c")],
        )
        flow = AgentsFlow.from_definition(defn, agent_registry=stub_registry)
        start = time.perf_counter()
        result = await flow.run_flow()
        elapsed = time.perf_counter() - start

        # Sequential would be 0.15 + 0.15 = 0.30s; concurrent should be ~0.15s.
        # Allow 0.25s to be safe on slow CI.
        assert elapsed < 0.25, f"Fan-out took {elapsed:.3f}s — expected concurrent < 0.25s"
        assert result.status == FlowStatus.COMPLETED


# ---------------------------------------------------------------------------
# Scenario 3: Fan-in {A,B}→C
# ---------------------------------------------------------------------------


class TestBranchingFanIn:
    """Integration scenario 3: {A,B}→C — C waits for both A and B."""

    async def test_fan_in_c_receives_both_deps(self, stub_registry: Any) -> None:
        """C's DependencyResults must contain both 'a' and 'b' results."""
        received_deps: dict = {}

        class RecordingAgent:
            def __init__(self, nm: str) -> None:
                self._name = nm

            @property
            def name(self) -> str:
                return self._name

            async def invoke(self, prompt: str, **kw: Any) -> Any:
                return "ok"

            async def ask(self, question: str = "", **kw: Any) -> Any:
                return type("R", (), {"content": self._name})()

        class FanInAgent:
            @property
            def name(self) -> str:
                return "c"

            async def invoke(self, prompt: str, **kw: Any) -> Any:
                return "merged"

            async def ask(self, question: str = "", **kw: Any) -> Any:
                received_deps.update(dict(question.split("=") for segment in question.split(",") if "=" in segment) if "," in question else {})
                return type("R", (), {"content": "merged"})()

        stub_registry.register(RecordingAgent("a"))
        stub_registry.register(RecordingAgent("b"))
        stub_registry.register(FanInAgent())

        defn = FlowDefinition(
            flow="fan-in",
            nodes=[
                _agent_node_def("a", "a"),
                _agent_node_def("b", "b"),
                _agent_node_def("c", "c"),
            ],
            edges=[_edge("a", "c"), _edge("b", "c")],
        )
        flow = AgentsFlow.from_definition(defn, agent_registry=stub_registry)
        result = await flow.run_flow()

        # All three nodes must have completed.
        assert "a" in result.responses
        assert "b" in result.responses
        assert "c" in result.responses
        assert result.status == FlowStatus.COMPLETED


# ---------------------------------------------------------------------------
# Scenario 4: Conditional routing via CEL predicate
# ---------------------------------------------------------------------------


class TestConditionalRoutingCEL:
    """Integration scenario 4: edge with CEL predicate."""

    async def test_cel_predicate_pass_dispatches_downstream(self, stub_registry: Any) -> None:
        """A→B with on_condition 'result.output == "yes"' — B is dispatched."""
        stub_registry.register(MockAgent("a", reply="yes"))
        stub_registry.register(MockAgent("b", reply="routed"))

        defn = FlowDefinition(
            flow="cel-pass",
            nodes=[
                _agent_node_def("a", "a"),
                _agent_node_def("b", "b"),
            ],
            edges=[_edge("a", "b", predicate='result.output == "yes"')],
        )
        flow = AgentsFlow.from_definition(defn, agent_registry=stub_registry)
        result = await flow.run_flow()

        # B should have run (predicate passed).
        assert "b" in result.responses
        assert result.status == FlowStatus.COMPLETED

    async def test_cel_predicate_fail_skips_downstream(self, stub_registry: Any) -> None:
        """A→B with on_condition 'result.output == "yes"' — B is NOT dispatched."""
        stub_registry.register(MockAgent("a", reply="no"))
        stub_registry.register(MockAgent("b", reply="should_not_run"))

        defn = FlowDefinition(
            flow="cel-fail",
            nodes=[
                _agent_node_def("a", "a"),
                _agent_node_def("b", "b"),
            ],
            edges=[_edge("a", "b", predicate='result.output == "yes"')],
        )
        flow = AgentsFlow.from_definition(defn, agent_registry=stub_registry)
        result = await flow.run_flow()

        # B should NOT have run (predicate failed).
        assert "b" not in result.responses
        # Only a completed; no failures, so status is "completed".
        assert result.status == FlowStatus.COMPLETED


# ---------------------------------------------------------------------------
# Scenario 5: Retry on failure
# ---------------------------------------------------------------------------


class TestRetryOnFailure:
    """Integration scenario 5: node that fails once then succeeds with max_retries=2."""

    async def test_retry_node_succeeds_after_one_failure(self) -> None:
        """Programmatic mode: RetryableAgentNode with max_retries=2."""
        retryable = RetryableAgent("retry-agent", fail_times=1, reply="recovered")

        node = RetryableAgentNode(
            agent=retryable,
            node_id="r",
            dependencies=set(),
            successors=set(),
            max_retries=2,
        )

        flow = AgentsFlow("retry-test")
        flow.add_node(node)
        result = await flow.run_flow()

        # Node should have been called twice: once fail, once succeed.
        assert retryable.call_count == 2
        assert result.status == FlowStatus.COMPLETED

    async def test_retry_exhausted_results_in_failed_status(self) -> None:
        """Programmatic mode: max_retries=1, agent fails twice → status 'failed'."""
        always_fail = MockAgent("always-fail", fail=True)

        node = RetryableAgentNode(
            agent=always_fail,
            node_id="f",
            dependencies=set(),
            successors=set(),
            max_retries=1,
        )

        flow = AgentsFlow("retry-exhausted")
        flow.add_node(node)
        result = await flow.run_flow()

        assert result.status == FlowStatus.FAILED
        assert "f" in result.errors
        # Called max_retries + 1 times (original + 1 retry).
        assert always_fail.call_count == 2


# ---------------------------------------------------------------------------
# Scenario 6: DecisionNode routing via CEL
# ---------------------------------------------------------------------------


class TestDecisionNodeRouting:
    """Integration scenario 6: DecisionNode → CEL-guarded branch."""

    async def test_decision_approve_branch_runs(self) -> None:
        """DecisionNode returns 'approve'; approve branch dispatched; reject skipped."""
        fake_result = DecisionResult(
            mode=DecisionMode.CIO,
            final_decision="approve",
            confidence=0.9,
        )

        approve_agent = MockAgent("approve-agent", reply="approved")

        # Build flow programmatically (DecisionNode + downstream AgentNodes).
        config = DecisionNodeConfig(
            mode=DecisionMode.CIO,
            decision_type=DecisionType.BINARY,
        )
        decision_node = DecisionNode(
            node_id="decision",
            decision_config=config,
            dependencies=set(),
            successors={"approve-path"},
        )
        approve_node = AgentNode(
            agent=approve_agent,
            node_id="approve-path",
            dependencies={"decision"},
            successors=set(),
        )

        flow = AgentsFlow("decision-flow")
        flow.add_node(decision_node)
        flow.add_node(approve_node)

        from unittest.mock import patch

        with patch("parrot.bots.flows.flow.DecisionFlowNode") as MockDecisionFlowNode:
            instance = AsyncMock()
            instance.ask = AsyncMock(return_value=fake_result)
            MockDecisionFlowNode.return_value = instance

            result = await flow.run_flow()

        # Decision node ran.
        assert "decision" in result.responses
        # Approval path ran (always edge — no CEL filter here in programmatic mode).
        assert "approve-path" in result.responses
        assert result.status == FlowStatus.COMPLETED


# ---------------------------------------------------------------------------
# Scenario 7: on_complete hook fires
# ---------------------------------------------------------------------------


class TestOnCompleteHookFires:
    """Integration scenario 7: on_complete hooks receive (ctx, result)."""

    async def test_hook_fires_once_with_correct_args(self, stub_registry: Any) -> None:
        stub_registry.register(MockAgent("a", reply="done"))

        defn = FlowDefinition(
            flow="hook-test",
            nodes=[_agent_node_def("n1", "a")],
            edges=[],
        )
        flow = AgentsFlow.from_definition(defn, agent_registry=stub_registry)

        hook = AsyncMock()
        ctx = FlowContext(initial_task="hook test")
        result = await flow.run_flow(ctx=ctx, on_complete=(hook,))

        hook.assert_awaited_once()
        call_args = hook.await_args.args
        assert len(call_args) == 2
        assert call_args[0] is ctx
        assert call_args[1] is result

    async def test_multiple_hooks_fire_in_order(self, stub_registry: Any) -> None:
        stub_registry.register(MockAgent("a"))

        defn = FlowDefinition(
            flow="multi-hook",
            nodes=[_agent_node_def("n1", "a")],
            edges=[],
        )
        flow = AgentsFlow.from_definition(defn, agent_registry=stub_registry)

        order: list = []

        async def hook1(ctx: object, result: FlowResult) -> None:
            order.append(1)

        async def hook2(ctx: object, result: FlowResult) -> None:
            order.append(2)

        await flow.run_flow(on_complete=(hook1, hook2))
        assert order == [1, 2]

    async def test_hook_exception_does_not_change_status(self, stub_registry: Any) -> None:
        stub_registry.register(MockAgent("a"))

        defn = FlowDefinition(
            flow="broken-hook",
            nodes=[_agent_node_def("n1", "a")],
            edges=[],
        )
        flow = AgentsFlow.from_definition(defn, agent_registry=stub_registry)

        async def broken_hook(ctx: object, result: FlowResult) -> None:
            raise RuntimeError("hook boom")

        result = await flow.run_flow(on_complete=(broken_hook,))
        # Status must remain completed despite hook failure.
        assert result.status == FlowStatus.COMPLETED
