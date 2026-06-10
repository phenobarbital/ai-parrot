"""Tests for AgentsFlow explicit-edge mode (add_edge): conditional routing,
OR-join, skip-propagation, callable predicates, and on_node_event hooks.

These cover the engine extension added for the dev-loop migration
(FEAT-129): programmatic flows can now declare conditional / on_error
edges directly instead of relying on node.successors, and joins follow
OR semantics — a node dispatches once all incoming edges are resolved
(source completed, failed, or skipped) and at least one fired; when none
fired the node is skipped and the skip cascades downstream.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional, Set

import pytest
from pydantic import Field

from parrot.bots.flows import AgentsFlow, FlowEdge
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node


class StubNode(Node):
    """Minimal concrete Node for scheduler tests.

    Returns ``result`` from execute(); raises RuntimeError when ``fail`` is
    True. Appends its node_id to ``ctx.shared_data['order']`` so tests can
    assert execution order/membership.
    """

    node_id: str
    result: Any = None
    fail: bool = False
    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        if self.fsm is None:
            object.__setattr__(
                self, "fsm", AgentTaskMachine(agent_name=self.node_id)
            )

    @property
    def name(self) -> str:
        return self.node_id

    async def execute(self, ctx: FlowContext, deps: Any, **kwargs: Any) -> Any:
        ctx.shared_data.setdefault("order", []).append(self.node_id)
        if self.fail:
            raise RuntimeError(f"{self.node_id} failed intentionally")
        return self.result if self.result is not None else self.node_id


def _flow(name: str = "explicit-test", **kwargs: Any) -> AgentsFlow:
    return AgentsFlow(name, **kwargs)


def _ran(ctx: FlowContext) -> list[str]:
    return ctx.shared_data.get("order", [])


# ---------------------------------------------------------------------------
# add_edge validation
# ---------------------------------------------------------------------------


class TestAddEdgeValidation:
    def test_unknown_condition_raises(self) -> None:
        flow = _flow()
        with pytest.raises(ValueError, match="Unknown edge condition"):
            flow.add_edge("a", "b", condition="sometimes")

    def test_on_condition_without_predicate_raises(self) -> None:
        flow = _flow()
        with pytest.raises(ValueError, match="requires a predicate"):
            flow.add_edge("a", "b", condition="on_condition")

    def test_predicate_promotes_condition(self) -> None:
        flow = _flow()
        edge = flow.add_edge("a", "b", predicate=lambda r: True)
        assert isinstance(edge, FlowEdge)
        assert edge.condition == "on_condition"

    @pytest.mark.asyncio
    async def test_edge_to_unknown_node_raises_at_run(self) -> None:
        flow = _flow()
        flow.add_node(StubNode(node_id="a"))
        flow.add_edge("a", "ghost")
        with pytest.raises(ValueError, match="references a node"):
            await flow.run_flow(FlowContext(initial_task=""))


# ---------------------------------------------------------------------------
# Conditional branching + OR-join merge
# ---------------------------------------------------------------------------


def _branch_merge_flow(root_result: str) -> AgentsFlow:
    """root →(=='left') left | →(=='right') right; both → merge."""
    flow = _flow()
    flow.add_node(StubNode(node_id="root", result=root_result))
    flow.add_node(StubNode(node_id="left"))
    flow.add_node(StubNode(node_id="right"))
    flow.add_node(StubNode(node_id="merge"))
    flow.add_edge("root", "left", predicate=lambda r: r == "left")
    flow.add_edge("root", "right", predicate=lambda r: r == "right")
    flow.add_edge("left", "merge")
    flow.add_edge("right", "merge")
    return flow


class TestBranchAndMerge:
    @pytest.mark.asyncio
    async def test_only_taken_branch_runs_and_merge_fires(self) -> None:
        flow = _branch_merge_flow("left")
        ctx = FlowContext(initial_task="")
        result = await flow.run_flow(ctx)
        assert "left" in _ran(ctx)
        assert "right" not in _ran(ctx)
        assert "merge" in _ran(ctx)
        assert result.status.value == "completed"

    @pytest.mark.asyncio
    async def test_other_branch(self) -> None:
        flow = _branch_merge_flow("right")
        ctx = FlowContext(initial_task="")
        await flow.run_flow(ctx)
        assert "right" in _ran(ctx)
        assert "left" not in _ran(ctx)
        assert "merge" in _ran(ctx)

    @pytest.mark.asyncio
    async def test_skip_propagates_when_no_branch_taken(self) -> None:
        flow = _branch_merge_flow("neither")
        ctx = FlowContext(initial_task="")
        result = await flow.run_flow(ctx)
        assert _ran(ctx) == ["root"]
        # Only the root completed; downstream nodes were skipped, not failed.
        assert result.errors == {}


# ---------------------------------------------------------------------------
# on_error fan-in (failure-handler pattern)
# ---------------------------------------------------------------------------


def _pipeline_with_handler(fail_at: Optional[str]) -> AgentsFlow:
    """a → b → c with on_error edges from each into 'handler'."""
    flow = _flow()
    for nid in ("a", "b", "c"):
        flow.add_node(StubNode(node_id=nid, fail=(nid == fail_at)))
    flow.add_node(StubNode(node_id="handler"))
    flow.add_edge("a", "b")
    flow.add_edge("b", "c")
    for nid in ("a", "b", "c"):
        flow.add_edge(nid, "handler", condition="on_error")
    return flow


class TestErrorFanIn:
    @pytest.mark.asyncio
    async def test_handler_runs_when_middle_node_fails(self) -> None:
        flow = _pipeline_with_handler(fail_at="b")
        ctx = FlowContext(initial_task="")
        result = await flow.run_flow(ctx)
        # b failed → c skipped → handler's fan-in resolves with one fired edge.
        assert "handler" in _ran(ctx)
        assert "c" not in _ran(ctx)
        assert "b" in result.errors
        # The scheduler records the failure on the context too.
        assert "b" in ctx.errors

    @pytest.mark.asyncio
    async def test_handler_skipped_on_happy_path(self) -> None:
        flow = _pipeline_with_handler(fail_at=None)
        ctx = FlowContext(initial_task="")
        result = await flow.run_flow(ctx)
        assert _ran(ctx) == ["a", "b", "c"]
        assert "handler" not in _ran(ctx)
        assert result.status.value == "completed"


# ---------------------------------------------------------------------------
# Derived dependencies (no node.dependencies/successors required)
# ---------------------------------------------------------------------------


class TestDerivedDependencies:
    @pytest.mark.asyncio
    async def test_deps_payload_comes_from_edges(self) -> None:
        captured: dict[str, Any] = {}

        class CapturingNode(StubNode):
            async def execute(self, ctx: FlowContext, deps: Any, **kwargs: Any) -> Any:
                captured[self.node_id] = dict(deps)
                return await super().execute(ctx, deps, **kwargs)

        flow = _flow()
        flow.add_node(CapturingNode(node_id="a", result="A-result"))
        flow.add_node(CapturingNode(node_id="b"))
        flow.add_edge("a", "b")
        await flow.run_flow(FlowContext(initial_task=""))
        assert captured["a"] == {}
        assert captured["b"] == {"a": "A-result"}


# ---------------------------------------------------------------------------
# on_node_event hook
# ---------------------------------------------------------------------------


class TestNodeEventHook:
    @pytest.mark.asyncio
    async def test_sync_callback_receives_lifecycle_events(self) -> None:
        events: list[tuple[str, str]] = []

        def on_event(event: str, node_id: str, info: dict) -> None:
            events.append((event, node_id))

        flow = _branch_merge_flow("left")
        flow._on_node_event = on_event
        await flow.run_flow(FlowContext(initial_task=""))

        assert ("node_started", "root") in events
        assert ("node_completed", "root") in events
        assert ("node_skipped", "right") in events
        assert ("node_completed", "merge") in events

    @pytest.mark.asyncio
    async def test_async_callback_and_failure_event(self) -> None:
        events: list[tuple[str, str, dict]] = []

        async def on_event(event: str, node_id: str, info: dict) -> None:
            events.append((event, node_id, info))

        flow = _pipeline_with_handler(fail_at="b")
        flow._on_node_event = on_event
        await flow.run_flow(FlowContext(initial_task=""))
        # Give fire-and-forget tasks a tick to drain.
        await asyncio.sleep(0)

        failed = [e for e in events if e[0] == "node_failed"]
        assert len(failed) == 1
        assert failed[0][1] == "b"
        assert "failed intentionally" in failed[0][2]["error"]

    @pytest.mark.asyncio
    async def test_constructor_accepts_callback(self) -> None:
        events: list[str] = []
        flow = AgentsFlow(
            "ctor-event-test",
            on_node_event=lambda ev, nid, info: events.append(f"{ev}:{nid}"),
        )
        flow.add_node(StubNode(node_id="solo"))
        flow.add_node(StubNode(node_id="solo2"))
        flow.add_edge("solo", "solo2")
        await flow.run_flow(FlowContext(initial_task=""))
        assert "node_started:solo" in events
        assert "node_completed:solo2" in events

    @pytest.mark.asyncio
    async def test_raising_callback_does_not_break_run(self) -> None:
        def bad_callback(event: str, node_id: str, info: dict) -> None:
            raise RuntimeError("telemetry exploded")

        flow = _branch_merge_flow("left")
        flow._on_node_event = bad_callback
        result = await flow.run_flow(FlowContext(initial_task=""))
        assert result.status.value == "completed"


# ---------------------------------------------------------------------------
# Structural validation + FSM lifecycle
# ---------------------------------------------------------------------------


class TestCycleValidation:
    @pytest.mark.asyncio
    async def test_full_cycle_raises(self) -> None:
        flow = _flow()
        flow.add_node(StubNode(node_id="x"))
        flow.add_node(StubNode(node_id="y"))
        flow.add_edge("x", "y")
        flow.add_edge("y", "x")
        with pytest.raises(ValueError, match="contains a cycle"):
            await flow.run_flow(FlowContext(initial_task=""))

    @pytest.mark.asyncio
    async def test_downstream_cycle_raises(self) -> None:
        """An entry node exists, but a downstream subgraph cycles."""
        flow = _flow()
        for nid in ("a", "b", "c"):
            flow.add_node(StubNode(node_id=nid))
        flow.add_edge("a", "b")
        flow.add_edge("b", "c")
        flow.add_edge("c", "b")
        with pytest.raises(ValueError, match="contains a cycle"):
            await flow.run_flow(FlowContext(initial_task=""))

    @pytest.mark.asyncio
    async def test_parallel_edges_same_pair_are_not_a_cycle(self) -> None:
        """Two edges between the same pair (cond + on_error) must validate."""
        flow = _flow()
        flow.add_node(StubNode(node_id="a", result="go"))
        flow.add_node(StubNode(node_id="b"))
        flow.add_edge("a", "b", predicate=lambda r: r == "go")
        flow.add_edge("a", "b", condition="on_error")
        ctx = FlowContext(initial_task="")
        result = await flow.run_flow(ctx)
        assert _ran(ctx) == ["a", "b"]
        assert result.status.value == "completed"


class TestFsmLifecycle:
    @staticmethod
    def _capture_materialized(flow: AgentsFlow) -> dict:
        captured: dict = {}
        original = flow._materialize_nodes

        def wrapper():
            fresh = original()
            captured.update(fresh)
            return fresh

        flow._materialize_nodes = wrapper  # type: ignore[method-assign]
        return captured

    @pytest.mark.asyncio
    async def test_fsm_states_reflect_run_outcome(self) -> None:
        """Executed → completed, failed → failed, skipped → blocked."""
        flow = _pipeline_with_handler(fail_at="b")
        captured = self._capture_materialized(flow)
        await flow.run_flow(FlowContext(initial_task=""))

        states = {nid: n.fsm.current_state.id for nid, n in captured.items()}
        assert states["a"] == "completed"
        assert states["b"] == "failed"
        assert states["c"] == "blocked"        # skipped (upstream failed)
        assert states["handler"] == "completed"

    @pytest.mark.asyncio
    async def test_original_nodes_keep_pristine_fsm(self) -> None:
        """B-lite contract: run_flow never mutates the registered nodes."""
        flow = _branch_merge_flow("left")
        await flow.run_flow(FlowContext(initial_task=""))
        for node in flow._nodes.values():
            assert node.fsm.current_state.id == "idle"


# ---------------------------------------------------------------------------
# Backward compatibility — legacy successors mode untouched
# ---------------------------------------------------------------------------


class TestLegacyModeUnchanged:
    @pytest.mark.asyncio
    async def test_successor_based_flow_still_runs(self) -> None:
        flow = _flow()
        flow.add_node(StubNode(node_id="a", successors={"b"}))
        flow.add_node(StubNode(node_id="b", dependencies={"a"}))
        ctx = FlowContext(initial_task="")
        result = await flow.run_flow(ctx)
        assert _ran(ctx) == ["a", "b"]
        assert result.status.value == "completed"
