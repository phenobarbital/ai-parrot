"""``AgentsFlow.resume(flow_factory=...)`` — resuming a graph the caller built.

``resume()`` used to rebuild every flow through ``from_definition()``. That is
correct for a flow that *was* built from a definition and wrong, in two
compounding ways, for one built programmatically with ``add_node`` /
``add_edge``:

1. **Custom node types come back empty rather than failing.** The generic
   fallback is ``cls(node_id=…, dependencies=…, successors=…)``, so a node
   whose fields all have defaults reconstructs happily with every live
   dependency — agents, repositories, clients — set to ``None``.
2. **The explicit-edge scheduler is lost.** ``run_flow()`` selects it with
   ``self._definition is None and bool(self._edges)``, and a rebuilt flow has
   a definition bound. OR-join, back-edge detection and predicate evaluation
   all switch off, whatever the original graph relied on.

Each of those is asserted directly below, on the old path, so the fix cannot
quietly stop being needed.
"""
from typing import Any

import pytest
from parrot.bots.flows.core import FlowContext
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.core.types import DependencyResults
from parrot.bots.flows.flow.flow import AgentsFlow, register_node

from .test_suspend_resume import FakeCheckpointStore, StubRegistry


@register_node("rft.step")
class _StepNode(Node):
    """A node holding a live dependency, like every custom node in practice."""

    dependencies: set[str] = set()
    successors: set[str] = set()
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

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> dict:
        if self.sink is not None:
            self.sink.append(self.node_id)
        ctx.shared_data.setdefault("ran", []).append(self.node_id)
        return {"status": self.label or "ok"}


def _build(sink: list, *, flow_id: str = "run-1", store=None) -> AgentsFlow:
    """Build the graph the way a real caller does: explicit edges, live deps.

    ``a`` fans out to ``b`` and ``c`` under CEL predicates, and both join on
    ``d`` — an OR-join, so ``d`` fires as soon as either arrives. Under the
    AND-join the old resume path falls back to, ``d`` never fires at all.
    """
    flow = AgentsFlow(
        name="rft",
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
# The two findings, asserted on the old path
# ---------------------------------------------------------------------------


async def test_without_a_factory_live_dependencies_are_silently_dropped(
    store, registry
) -> None:
    """A failure would be better: this looks like a successful resume."""
    await _checkpointed_run(store)

    resumed = await AgentsFlow.resume(
        "run-1", agent_registry=registry, store=store
    )
    nodes = resumed._materialize_nodes()

    assert nodes["d"].sink is None


async def test_without_a_factory_the_explicit_edge_scheduler_is_lost(
    store, registry
) -> None:
    """OR-join, back-edges and predicates all switch off together."""
    await _checkpointed_run(store)

    resumed = await AgentsFlow.resume(
        "run-1", agent_registry=registry, store=store
    )

    assert resumed._definition is not None
    # This expression is what run_flow() uses to pick the scheduler.
    assert (resumed._definition is None and bool(resumed._edges)) is False


# ---------------------------------------------------------------------------
# The factory
# ---------------------------------------------------------------------------


async def test_a_factory_keeps_the_live_dependencies(store, registry) -> None:
    """The caller's own builder produces the graph it always produced."""
    await _checkpointed_run(store)
    sink: list = []

    resumed = await AgentsFlow.resume(
        "run-1",
        agent_registry=registry,
        store=store,
        flow_factory=lambda _definition: _build(sink),
    )
    nodes = resumed._materialize_nodes()

    assert nodes["d"].sink is sink


async def test_a_factory_keeps_the_explicit_edge_scheduler(store, registry) -> None:
    """Which is what makes the OR-join and the predicates work on a resume."""
    sink: list = []
    await _checkpointed_run(store)

    resumed = await AgentsFlow.resume(
        "run-1",
        agent_registry=registry,
        store=store,
        flow_factory=lambda _definition: _build(sink),
    )

    assert resumed._definition is None
    assert (resumed._definition is None and bool(resumed._edges)) is True


async def test_a_resumed_run_does_not_re_execute_completed_nodes(
    store, registry
) -> None:
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

    # Everything had finished, so a resume re-executes nothing at all.
    assert sink == []


async def test_a_resumed_run_continues_from_the_frontier(store, registry) -> None:
    """The realistic case: a run that stopped part-way carries on."""
    sink: list = []
    flow = _build(sink, store=store)
    ctx = FlowContext(initial_task="t")

    # Fail 'b' on the first pass so the run stops before 'd'.
    class _Boom(_StepNode):
        async def execute(self, ctx, deps, **kwargs):
            raise RuntimeError("b exploded")

    flow._nodes["b"] = _Boom(node_id="b", sink=sink)
    await flow.run_flow(ctx)
    store._leases.pop("run-1", None)
    assert "d" not in sink

    replay: list = []
    resumed = await AgentsFlow.resume(
        "run-1",
        agent_registry=registry,
        store=store,
        flow_factory=lambda _definition: _build(replay),
    )
    await resumed.run_flow()

    # 'a' finished and is not re-run; 'b' failed, so it and 'd' do run.
    assert "a" not in replay
    assert replay == ["b", "d"]


# ---------------------------------------------------------------------------
# Guard rails and backward compatibility
# ---------------------------------------------------------------------------


async def test_a_factory_returning_the_wrong_graph_is_refused(
    store, registry
) -> None:
    """Otherwise the run restarts from the wrong frontier without a word."""
    await _checkpointed_run(store)

    def _wrong(_definition) -> AgentsFlow:
        other = AgentsFlow(name="rft")
        other.add_node(_StepNode(node_id="z"))
        return other

    with pytest.raises(ValueError, match="missing node"):
        await AgentsFlow.resume(
            "run-1", agent_registry=registry, store=store, flow_factory=_wrong
        )


async def test_the_default_path_is_unchanged(store, registry) -> None:
    """``flow_factory=None`` must behave exactly as it always did."""
    await _checkpointed_run(store)

    resumed = await AgentsFlow.resume(
        "run-1", agent_registry=registry, store=store
    )

    assert resumed.flow_id == "run-1"
    assert resumed._checkpoint_enabled is True
    assert resumed._resume_seed_context is not None
    assert set(resumed._resume_seed_context.completed_tasks) == {"a", "b", "d"}


async def test_the_seeded_context_survives_a_factory_rebuild(
    store, registry
) -> None:
    """Seeding happens after the rebuild, so a factory must not lose it."""
    await _checkpointed_run(store)

    resumed = await AgentsFlow.resume(
        "run-1",
        agent_registry=registry,
        store=store,
        flow_factory=lambda _definition: _build([]),
    )

    seeded = resumed._resume_seed_context
    assert seeded is not None
    assert set(seeded.completed_tasks) == {"a", "b", "d"}
    assert seeded.results["a"]["status"] == "left"
