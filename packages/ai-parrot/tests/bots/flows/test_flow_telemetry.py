"""Tests for FEAT-176 Phase 1.5 — flow/node lifecycle telemetry.

Covers:
- the new flow/node LifecycleEvent dataclasses (construction + strict
  JSON serialization via to_dict);
- the engine's listener multiplexing (ctor sequence +
  add_node_event_listener) and the run-level bracket events
  (flow_started / flow_completed) with durations;
- FlowLifecycleAdapter: typed events on an isolated EventRegistry, trace
  stitching (one trace per run, one child span per node), run_id
  extraction from shared_data, and TraceContext pinning on FlowContext.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, List, Optional, Set

import pytest
from pydantic import Field

from parrot.bots.flows import AgentsFlow, FlowLifecycleAdapter
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node
from navigator_eventbus.lifecycle.base import LifecycleEvent
from parrot.core.events.lifecycle.events.flow import (
    FlowCompletedEvent,
    FlowStartedEvent,
    NodeCompletedEvent,
    NodeFailedEvent,
    NodeSkippedEvent,
    NodeStartedEvent,
)
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.trace import TraceContext


class StubNode(Node):
    """Minimal node: returns ``result`` (or node_id), raises when ``fail``."""

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
        if self.fail:
            raise RuntimeError(f"{self.node_id} failed intentionally")
        return self.result if self.result is not None else self.node_id


def _branch_merge_flow(root_result: str = "left") -> AgentsFlow:
    """root →(=='left') left | →(=='right') right; both → merge."""
    flow = AgentsFlow("telemetry-test")
    flow.add_node(StubNode(node_id="root", result=root_result))
    for nid in ("left", "right", "merge"):
        flow.add_node(StubNode(node_id=nid))
    flow.add_edge("root", "left", predicate=lambda r: r == "left")
    flow.add_edge("root", "right", predicate=lambda r: r == "right")
    flow.add_edge("left", "merge")
    flow.add_edge("right", "merge")
    return flow


async def _drain_lifecycle_tasks() -> None:
    """Await the fire-and-forget tasks scheduled by emit_nowait."""
    for _ in range(5):
        pending = [
            t for t in asyncio.all_tasks()
            if t.get_name().startswith("lifecycle.") and t is not asyncio.current_task()
        ]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


# ---------------------------------------------------------------------------
# Event dataclasses
# ---------------------------------------------------------------------------


class TestFlowEventDataclasses:
    @pytest.mark.parametrize(
        "cls",
        [
            FlowStartedEvent,
            FlowCompletedEvent,
            NodeStartedEvent,
            NodeCompletedEvent,
            NodeFailedEvent,
            NodeSkippedEvent,
        ],
    )
    def test_constructible_and_json_serializable(self, cls) -> None:
        event = cls(trace_context=TraceContext.new_root())
        payload = event.to_dict()
        json.dumps(payload)  # must not raise (strict-serialization contract)
        assert payload["event_class"] == cls.__name__

    def test_frozen(self) -> None:
        event = NodeStartedEvent(
            trace_context=TraceContext.new_root(), node_id="a"
        )
        with pytest.raises(Exception):
            event.node_id = "b"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Engine: listener multiplexing + flow bracket
# ---------------------------------------------------------------------------


class TestListenerMultiplexing:
    @pytest.mark.asyncio
    async def test_multiple_listeners_all_receive(self) -> None:
        seen_a: List[str] = []
        seen_b: List[str] = []
        flow = _branch_merge_flow()
        flow.add_node_event_listener(lambda e, n, i: seen_a.append(f"{e}:{n}"))
        flow.add_node_event_listener(lambda e, n, i: seen_b.append(f"{e}:{n}"))
        await flow.run_flow(FlowContext(initial_task=""))
        assert seen_a == seen_b
        assert "node_completed:merge" in seen_a

    @pytest.mark.asyncio
    async def test_constructor_accepts_sequence(self) -> None:
        seen: List[str] = []
        flow = AgentsFlow(
            "seq-listeners",
            on_node_event=[
                lambda e, n, i: seen.append(f"1:{e}"),
                lambda e, n, i: seen.append(f"2:{e}"),
            ],
        )
        flow.add_node(StubNode(node_id="solo"))
        flow.add_node(StubNode(node_id="solo2"))
        flow.add_edge("solo", "solo2")
        await flow.run_flow(FlowContext(initial_task=""))
        assert "1:flow_started" in seen and "2:flow_started" in seen


class TestFlowBracketEvents:
    @pytest.mark.asyncio
    async def test_bracket_order_and_payload(self) -> None:
        events: List[tuple] = []
        flow = _branch_merge_flow()
        flow.add_node_event_listener(
            lambda e, n, i: events.append((e, n, dict(i)))
        )
        await flow.run_flow(FlowContext(initial_task=""))

        names = [e for e, _, _ in events]
        assert names[0] == "flow_started"
        assert names[-1] == "flow_completed"

        started_info = events[0][2]
        assert started_info["node_count"] == 4

        completed_info = events[-1][2]
        assert completed_info["status"] == "completed"
        assert completed_info["duration_ms"] >= 0.0
        assert completed_info["completed_count"] == 3
        assert completed_info["skipped_count"] == 1
        assert completed_info["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_node_durations_in_info(self) -> None:
        infos: dict = {}

        def listener(e: str, n: str, i: dict) -> None:
            if e in ("node_completed", "node_failed"):
                infos[(e, n)] = i

        flow = AgentsFlow("durations")
        flow.add_node(StubNode(node_id="ok"))
        flow.add_node(StubNode(node_id="bad", fail=True))
        flow.add_edge("ok", "bad")
        flow.add_node_event_listener(listener)
        result = await flow.run_flow(FlowContext(initial_task=""))

        assert infos[("node_completed", "ok")]["duration_ms"] >= 0.0
        failed = infos[("node_failed", "bad")]
        assert failed["error_type"] == "RuntimeError"
        assert "failed intentionally" in failed["error"]
        # Durations also land on the FlowResult's node metadata.
        ok_info = next(n for n in result.nodes if n.node_id == "ok")
        assert ok_info.execution_time >= 0.0


# ---------------------------------------------------------------------------
# FlowLifecycleAdapter
# ---------------------------------------------------------------------------


@pytest.fixture
def collector():
    """Isolated registry + ordered event collector."""
    registry = EventRegistry(forward_to_global=False)
    events: List[LifecycleEvent] = []

    async def _collect(event: LifecycleEvent) -> None:
        events.append(event)

    registry.subscribe(LifecycleEvent, _collect)
    return registry, events


class TestFlowLifecycleAdapter:
    @pytest.mark.asyncio
    async def test_typed_events_for_full_run(self, collector) -> None:
        registry, events = collector
        flow = _branch_merge_flow()
        flow.add_node_event_listener(FlowLifecycleAdapter(registry=registry))

        ctx = FlowContext(
            initial_task="", shared_data={"run_id": "run-telemetry"}
        )
        await flow.run_flow(ctx)
        await _drain_lifecycle_tasks()

        by_type = {}
        for ev in events:
            by_type.setdefault(type(ev).__name__, []).append(ev)

        assert len(by_type["FlowStartedEvent"]) == 1
        assert len(by_type["FlowCompletedEvent"]) == 1
        assert {e.node_id for e in by_type["NodeStartedEvent"]} == {
            "root", "left", "merge",
        }
        assert {e.node_id for e in by_type["NodeCompletedEvent"]} == {
            "root", "left", "merge",
        }
        assert {e.node_id for e in by_type["NodeSkippedEvent"]} == {"right"}
        assert "NodeFailedEvent" not in by_type

        # Every event carries the run_id and the flow name.
        assert all(e.run_id == "run-telemetry" for e in events)
        assert all(e.flow_name == "telemetry-test" for e in events)

        flow_done = by_type["FlowCompletedEvent"][0]
        assert flow_done.status == "completed"
        assert flow_done.completed_count == 3
        assert flow_done.skipped_count == 1

    @pytest.mark.asyncio
    async def test_trace_stitching(self, collector) -> None:
        registry, events = collector
        flow = _branch_merge_flow()
        flow.add_node_event_listener(FlowLifecycleAdapter(registry=registry))

        ctx = FlowContext(initial_task="")
        await flow.run_flow(ctx)
        await _drain_lifecycle_tasks()

        # The run's root TraceContext is pinned on the FlowContext.
        assert ctx.trace_context is not None
        root = ctx.trace_context

        # One trace for the whole run.
        assert {e.trace_context.trace_id for e in events} == {root.trace_id}

        # Flow events carry the root span itself.
        flow_events = [
            e for e in events
            if isinstance(e, (FlowStartedEvent, FlowCompletedEvent))
        ]
        assert all(e.trace_context.span_id == root.span_id for e in flow_events)

        # A node's started/completed share ONE child span parented to root.
        started = {
            e.node_id: e.trace_context for e in events
            if isinstance(e, NodeStartedEvent)
        }
        completed = {
            e.node_id: e.trace_context for e in events
            if isinstance(e, NodeCompletedEvent)
        }
        for nid, span in started.items():
            assert span.span_id == completed[nid].span_id
            assert span.parent_span_id == root.span_id
        # Distinct nodes get distinct spans.
        assert len({s.span_id for s in started.values()}) == len(started)

    @pytest.mark.asyncio
    async def test_failed_node_event(self, collector) -> None:
        registry, events = collector
        flow = AgentsFlow("failing-telemetry")
        flow.add_node(StubNode(node_id="a"))
        flow.add_node(StubNode(node_id="bad", fail=True))
        flow.add_edge("a", "bad")
        flow.add_node_event_listener(FlowLifecycleAdapter(registry=registry))

        await flow.run_flow(FlowContext(initial_task=""))
        await _drain_lifecycle_tasks()

        failed = [e for e in events if isinstance(e, NodeFailedEvent)]
        assert len(failed) == 1
        assert failed[0].node_id == "bad"
        assert failed[0].error_type == "RuntimeError"
        assert "failed intentionally" in failed[0].error_message

        flow_done = next(
            e for e in events if isinstance(e, FlowCompletedEvent)
        )
        assert flow_done.status == "partial"
        assert flow_done.failed_count == 1

    @pytest.mark.asyncio
    async def test_seeded_trace_context_is_respected(self, collector) -> None:
        registry, events = collector
        flow = _branch_merge_flow()
        flow.add_node_event_listener(FlowLifecycleAdapter(registry=registry))

        seeded = TraceContext.new_root()
        ctx = FlowContext(initial_task="", trace_context=seeded)
        await flow.run_flow(ctx)
        await _drain_lifecycle_tasks()

        assert ctx.trace_context is seeded
        assert {e.trace_context.trace_id for e in events} == {seeded.trace_id}

    @pytest.mark.asyncio
    async def test_adapter_span_pool_is_cleaned_up(self, collector) -> None:
        registry, _events = collector
        adapter = FlowLifecycleAdapter(registry=registry)
        flow = _branch_merge_flow()
        flow.add_node_event_listener(adapter)
        await flow.run_flow(FlowContext(initial_task=""))
        await _drain_lifecycle_tasks()
        assert adapter._node_spans == {}
