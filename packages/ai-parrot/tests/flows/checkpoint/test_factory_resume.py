"""``AgentsFlow.resume(flow_factory=..., seed_context=...)`` (TASK-2622).

``resume()`` used to rebuild every flow through ``from_definition()``. That is
correct for a flow that *was* built from a definition and wrong, in two
compounding ways, for one built programmatically with ``add_node`` /
``add_edge`` (like the dev-loop/dev-flow graphs this feature targets):

1. **Custom node types come back empty rather than failing.** The generic
   fallback is ``cls(node_id=…, dependencies=…, successors=…)``, so a node
   whose fields all have defaults reconstructs happily with every live
   dependency — agents, dispatchers, toolkits — set to ``None``.
2. **The explicit-edge scheduler is lost.** ``run_flow()`` selects it with
   ``self._definition is None and bool(self._edges)``, and a rebuilt flow has
   a definition bound. OR-join, back-edge detection and predicate evaluation
   all switch off, whatever the original graph relied on.

``flow_factory`` fixes both by handing the caller's own builder back instead.
``seed_context`` additionally lets the caller supply a live ``FlowContext``
(bound to a fresh process's ``SessionHost``/dispatchers) that resume seeds
in place, instead of building a brand-new internal context — so a fresh
process's live objects are never overwritten by checkpoint data.

Also covers ``register_checkpoint_type()`` — the process-wide type registry
that lets an arbitrary Pydantic result type round-trip through every
``FlowStateSerializer`` instance, not just one built after registration.
"""
from typing import Any

import pytest
from parrot.bots.flows.core import FlowContext
from parrot.bots.flows.core.checkpoint import (
    FlowStateSerializer,
    register_checkpoint_type,
)
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.core.types import DependencyResults
from parrot.bots.flows.flow.flow import AgentsFlow, register_node
from pydantic import BaseModel, Field

from .test_suspend_resume import FakeCheckpointStore, StubRegistry


@register_node("factory-resume.step")
class _StepNode(Node):
    """A node holding a live dependency, like every custom node in practice."""

    dependencies: set[str] = Field(default_factory=set)
    successors: set[str] = Field(default_factory=set)
    fsm: Any = None
    # The field that matters: it has a default, so the generic fallback
    # constructs this class without complaint and simply drops what was here.
    sink: Any = None
    label: str = ""

    def model_post_init(self, _context: Any) -> None:
        if self.fsm is None:
            from parrot.bots.flows.core.fsm import AgentTaskMachine

            object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.node_id))

    @property
    def name(self) -> str:
        return self.node_id

    async def execute(self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any) -> dict:
        if self.sink is not None:
            self.sink.append(self.node_id)
        ctx.shared_data.setdefault("ran", []).append(self.node_id)
        return {"status": self.label or "ok"}


def _build(sink: list, *, flow_id: str = "run-1", store=None) -> AgentsFlow:
    """Build the graph the way a real caller does: explicit edges, live deps."""
    flow = AgentsFlow(
        name="factory-resume",
        flow_id=flow_id,
        checkpoint=store is not None,
        checkpoint_store=store,
    )
    for node_id, label in (("a", "left"), ("b", "ok"), ("c", "ok"), ("d", "ok")):
        flow.add_node(_StepNode(node_id=node_id, sink=sink, label=label))
    flow.add_edge("a", "b", condition="on_condition", predicate='result.status == "left"')
    flow.add_edge("a", "c", condition="on_condition", predicate='result.status == "right"')
    flow.add_edge("b", "d", condition="on_success")
    flow.add_edge("c", "d", condition="on_success")
    return flow


@pytest.fixture
def store() -> FakeCheckpointStore:
    """A fresh in-memory checkpoint store."""
    return FakeCheckpointStore()


@pytest.fixture
def registry() -> StubRegistry:
    """This graph has no agent-typed nodes; the registry is a formality."""
    return StubRegistry({})


async def _checkpointed_run(store: FakeCheckpointStore, flow_id: str = "run-1") -> list:
    """Run the graph once with checkpointing on, returning the execution order."""
    sink: list = []
    flow = _build(sink, flow_id=flow_id, store=store)
    await flow.run_flow(FlowContext(initial_task="t"))
    await store.release_lease(flow_id, "")
    store._leases.pop(flow_id, None)
    return sink


# ---------------------------------------------------------------------------
# flow_factory preserves explicit routing (spec test names)
# ---------------------------------------------------------------------------


async def test_resume_flow_factory_preserves_explicit_graph(store, registry) -> None:
    """Callable predicates / OR joins / back-edges survive factory resume."""
    await _checkpointed_run(store)
    sink: list = []

    resumed = await AgentsFlow.resume(
        "run-1",
        agent_registry=registry,
        store=store,
        flow_factory=lambda _definition: _build(sink),
    )

    assert resumed._definition is None
    assert (resumed._definition is None and bool(resumed._edges)) is True

    nodes = resumed._materialize_nodes()
    assert nodes["d"].sink is sink


async def test_resume_factory_rejects_missing_completed_node(store, registry) -> None:
    """A factory that returns the wrong graph must not resume silently."""
    await _checkpointed_run(store)

    def _wrong(_definition) -> AgentsFlow:
        other = AgentsFlow(name="factory-resume-wrong")
        other.add_node(_StepNode(node_id="z"))
        return other

    with pytest.raises(ValueError, match="missing node"):
        await AgentsFlow.resume("run-1", agent_registry=registry, store=store, flow_factory=_wrong)


async def test_resume_without_factory_is_unchanged(store, registry) -> None:
    """``flow_factory=None`` must behave exactly as it always did."""
    await _checkpointed_run(store)

    resumed = await AgentsFlow.resume("run-1", agent_registry=registry, store=store)

    assert resumed.flow_id == "run-1"
    assert resumed._checkpoint_enabled is True
    assert resumed._resume_seed_context is not None
    assert set(resumed._resume_seed_context.completed_tasks) == {"a", "b", "d"}


async def test_resumed_run_does_not_re_execute_completed_nodes(store, registry) -> None:
    """The whole point of resuming rather than re-running."""
    first = await _checkpointed_run(store)
    assert first == ["a", "b", "d"]

    sink: list = []
    resumed = await AgentsFlow.resume(
        "run-1",
        agent_registry=registry,
        store=store,
        flow_factory=lambda _definition: _build(sink),
    )
    await resumed.run_flow()

    assert sink == []


# ---------------------------------------------------------------------------
# seed_context: caller-supplied live context (TASK-2622 addition)
# ---------------------------------------------------------------------------


async def test_seed_context_receives_completed_ids_and_results(store, registry) -> None:
    """A caller-supplied context is seeded in place, not replaced."""
    await _checkpointed_run(store)

    live_marker = object()
    caller_ctx = FlowContext(initial_task="fresh-process-task", agent_registry=registry)
    caller_ctx.shared_data["live_dependency"] = live_marker

    resumed = await AgentsFlow.resume(
        "run-1",
        agent_registry=registry,
        store=store,
        flow_factory=lambda _definition: _build([]),
        seed_context=caller_ctx,
    )

    assert resumed._resume_seed_context is caller_ctx
    assert set(caller_ctx.completed_tasks) == {"a", "b", "d"}
    assert caller_ctx.results["a"]["status"] == "left"


async def test_seed_context_live_objects_are_not_overwritten(store, registry) -> None:
    """Checkpoint data must never clobber the caller's live objects."""
    await _checkpointed_run(store)

    live_marker = object()
    caller_ctx = FlowContext(initial_task="fresh-process-task", agent_registry=registry)
    caller_ctx.shared_data["live_dependency"] = live_marker

    await AgentsFlow.resume(
        "run-1",
        agent_registry=registry,
        store=store,
        flow_factory=lambda _definition: _build([]),
        seed_context=caller_ctx,
    )

    # shared_data/agent_registry are the caller's live objects: resume must
    # not touch shared_data (mark_completed() never writes to it) so the
    # live dependency set before resume() survives untouched.
    assert caller_ctx.shared_data["live_dependency"] is live_marker
    assert caller_ctx.agent_registry is registry


async def test_seed_context_continues_from_the_frontier(store, registry) -> None:
    """The realistic case: a run that stopped part-way carries on."""
    sink: list = []
    flow = _build(sink, store=store)
    ctx = FlowContext(initial_task="t")

    class _Boom(_StepNode):
        async def execute(self, ctx, deps, **kwargs):
            raise RuntimeError("b exploded")

    flow._nodes["b"] = _Boom(node_id="b", sink=sink)
    await flow.run_flow(ctx)
    store._leases.pop("run-1", None)
    assert "d" not in sink

    replay: list = []
    caller_ctx = FlowContext(initial_task="fresh-process-task", agent_registry=registry)
    resumed = await AgentsFlow.resume(
        "run-1",
        agent_registry=registry,
        store=store,
        flow_factory=lambda _definition: _build(replay),
        seed_context=caller_ctx,
    )
    await resumed.run_flow()

    assert "a" not in replay
    assert replay == ["b", "d"]


# ---------------------------------------------------------------------------
# register_checkpoint_type: process-wide type registry
# ---------------------------------------------------------------------------


def test_register_checkpoint_type_round_trip() -> None:
    class _MyRegisteredResult(BaseModel):
        value: int = 1
        note: str = "ok"

    register_checkpoint_type(_MyRegisteredResult)

    serializer = FlowStateSerializer()
    data, lossy = serializer.encode_with_meta(_MyRegisteredResult(value=7, note="round-tripped"))
    assert not lossy

    restored = serializer.decode(data)
    assert isinstance(restored, _MyRegisteredResult)
    assert restored.value == 7
    assert restored.note == "round-tripped"


def test_register_checkpoint_type_visible_to_serializers_built_before_registration() -> None:
    """Order independence: a serializer built first must still see a later registration."""

    class _LateRegisteredResult(BaseModel):
        marker: str = "late"

    serializer = FlowStateSerializer()  # built BEFORE registration

    register_checkpoint_type(_LateRegisteredResult)

    data, lossy = serializer.encode_with_meta(_LateRegisteredResult())
    assert not lossy
    assert isinstance(serializer.decode(data), _LateRegisteredResult)


def test_register_checkpoint_type_conflicting_tag_raises() -> None:
    class _ModelOne(BaseModel):
        x: int = 1

    class _ModelTwo(BaseModel):
        y: int = 2

    tag = register_checkpoint_type(_ModelOne, tag="factory-resume.conflict-tag")

    with pytest.raises(ValueError, match="already registered"):
        register_checkpoint_type(_ModelTwo, tag=tag)

    # Idempotent re-registration of the same class/tag is a no-op, not an error.
    register_checkpoint_type(_ModelOne, tag=tag)
