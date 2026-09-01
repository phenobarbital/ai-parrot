"""Required checkpoint persistence — input metadata, errors, awaited writes
(TASK-2623).

Covers the data/persistence half of spec §3 Module 2:

* ``FlowCheckpointer.checkpoint()`` — an awaited, required write path that
  propagates encode/persist failures as ``CheckpointPersistenceError``,
  unlike the existing fire-and-forget ``make_listener()`` path (which stays
  best-effort and unchanged).
* ``CheckpointInputMetadata`` / ``FlowCheckpoint.input_metadata`` — immutable
  input-fingerprint metadata that round-trips through the serializer, with
  old (metadata-less) checkpoints still loading fine.
* ``AgentsFlow.resume(expected_input=...)`` — rejects resuming a checkpoint
  whose recorded input metadata does not match what the caller expects.
* ``AgentsFlow(checkpoint_definition=..., checkpoint_shared_data=...)`` — an
  externally-supplied declarative definition (so explicit-edge graphs never
  call ``to_definition()``) and an allowlisted shared-data projector (so the
  full live ``shared_data`` mapping is never persisted).
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.bots.flows.core.checkpoint import (
    CheckpointFingerprintMismatchError,
    CheckpointInputMetadata,
    CheckpointPersistenceError,
    FlowCheckpointer,
)
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.core.types import DependencyResults
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition
from parrot.bots.flows.flow.flow import AgentsFlow, register_node
from pydantic import Field

from .test_suspend_resume import (
    CountingAgent,
    FakeCheckpointStore,
    StubRegistry,
    _make_linear_definition,
)


@register_node("required-persistence.plain")
class _PlainNode(Node):
    """A trivial node — used only to exercise checkpoint_definition wiring."""

    dependencies: set[str] = Field(default_factory=set)
    successors: set[str] = Field(default_factory=set)

    @property
    def name(self) -> str:
        return self.node_id

    async def execute(self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any) -> dict:
        return {"ok": True}


@pytest.fixture
def fake_store() -> FakeCheckpointStore:
    return FakeCheckpointStore()


@pytest.fixture
def failing_checkpoint_store() -> FakeCheckpointStore:
    store = FakeCheckpointStore()
    store.put = AsyncMock(side_effect=ConnectionError("redis unavailable"))
    return store


@pytest.fixture
def agents():
    return {
        "agent1": CountingAgent("agent1"),
        "agent2": CountingAgent("agent2"),
        "agent3": CountingAgent("agent3"),
    }


@pytest.fixture
def registry(agents):
    return StubRegistry(agents)


def _definition() -> FlowDefinition:
    return _make_linear_definition()


# ---------------------------------------------------------------------------
# FlowCheckpointer.checkpoint() — awaited required write path
# ---------------------------------------------------------------------------


async def test_required_checkpoint_put_failure_raises(failing_checkpoint_store) -> None:
    checkpointer = FlowCheckpointer(
        flow_id="req-1",
        flow_name="req-flow",
        definition=_definition(),
        store=failing_checkpoint_store,
    )
    ctx = FlowContext(initial_task="t")
    ctx.mark_completed("n1", result={"ok": True})

    with pytest.raises(CheckpointPersistenceError):
        await checkpointer.checkpoint(ctx)


async def test_required_checkpoint_awaits_put_and_returns_checkpoint(fake_store) -> None:
    checkpointer = FlowCheckpointer(
        flow_id="req-2",
        flow_name="req-flow",
        definition=_definition(),
        store=fake_store,
    )
    ctx = FlowContext(initial_task="t")
    ctx.mark_completed("n1", result={"ok": True})

    checkpoint = await checkpointer.checkpoint(ctx)

    # No fire-and-forget task in flight — the write already landed by the
    # time checkpoint() returns.
    stored = await fake_store.latest("req-2")
    assert stored is not None
    assert stored.checkpoint_id == checkpoint.checkpoint_id
    assert "n1" in stored.context.completed_tasks


async def test_required_checkpoint_failure_does_not_advance_numbering(failing_checkpoint_store) -> None:
    """Spec §7: 'do not advance the in-memory parent ID until the write succeeds'."""
    checkpointer = FlowCheckpointer(
        flow_id="req-3",
        flow_name="req-flow",
        definition=_definition(),
        store=failing_checkpoint_store,
    )
    ctx = FlowContext(initial_task="t")
    ctx.mark_completed("n1", result={"ok": True})

    with pytest.raises(CheckpointPersistenceError):
        await checkpointer.checkpoint(ctx)

    assert checkpointer._last_checkpoint_id == 0
    assert checkpointer._parent_checkpoint_id is None


# ---------------------------------------------------------------------------
# CheckpointInputMetadata round-trip + backward compatibility
# ---------------------------------------------------------------------------


async def test_input_metadata_round_trips_through_checkpoint(fake_store) -> None:
    metadata = CheckpointInputMetadata(
        workflow="dev-loop",
        topology_version="v1",
        input_fingerprint="abc123",
    )
    checkpointer = FlowCheckpointer(
        flow_id="meta-1",
        flow_name="meta-flow",
        definition=_definition(),
        store=fake_store,
        input_metadata=metadata,
    )
    ctx = FlowContext(initial_task="t")
    ctx.mark_completed("n1", result={"ok": True})

    checkpoint = await checkpointer.checkpoint(ctx)
    assert checkpoint.input_metadata == metadata

    reloaded = await fake_store.latest("meta-1")
    assert reloaded.input_metadata == metadata


async def test_old_checkpoint_without_input_metadata_still_loads(fake_store) -> None:
    """Old checkpoints (written before this field existed) must still load."""
    checkpointer = FlowCheckpointer(
        flow_id="meta-2",
        flow_name="meta-flow",
        definition=_definition(),
        store=fake_store,
        # No input_metadata passed at all.
    )
    ctx = FlowContext(initial_task="t")
    ctx.mark_completed("n1", result={"ok": True})

    await checkpointer.checkpoint(ctx)

    reloaded = await fake_store.latest("meta-2")
    assert reloaded.input_metadata is None


# ---------------------------------------------------------------------------
# resume(expected_input=...) fingerprint mismatch
# ---------------------------------------------------------------------------


async def test_same_run_id_different_input_rejected(fake_store, registry) -> None:
    metadata = CheckpointInputMetadata(
        workflow="dev-loop",
        topology_version="v1",
        input_fingerprint="original-fingerprint",
    )
    flow = AgentsFlow.from_definition(
        _definition(),
        agent_registry=registry,
        checkpoint=True,
        checkpoint_store=fake_store,
        flow_id="mismatch-flow",
    )
    # from_definition() has no checkpoint_input passthrough (only
    # AgentsFlow.__init__ needs one per spec §2 — real dev-loop/dev-flow
    # callers build programmatically, not via from_definition(), see
    # TASK-2622); set the attribute _ensure_checkpointer() reads directly,
    # before the first checkpoint is built.
    flow._checkpoint_input_arg = metadata
    await flow.run_flow("go")

    other_metadata = CheckpointInputMetadata(
        workflow="dev-loop",
        topology_version="v1",
        input_fingerprint="a-different-fingerprint",
    )
    with pytest.raises(CheckpointFingerprintMismatchError):
        await AgentsFlow.resume(
            "mismatch-flow",
            agent_registry=registry,
            store=fake_store,
            expected_input=other_metadata,
        )


async def test_resume_matching_expected_input_succeeds(fake_store, registry) -> None:
    metadata = CheckpointInputMetadata(
        workflow="dev-loop",
        topology_version="v1",
        input_fingerprint="matching-fingerprint",
    )
    flow = AgentsFlow.from_definition(
        _definition(),
        agent_registry=registry,
        checkpoint=True,
        checkpoint_store=fake_store,
        flow_id="match-flow",
    )
    # from_definition() has no checkpoint_input passthrough (only
    # AgentsFlow.__init__ needs one per spec §2 — real dev-loop/dev-flow
    # callers build programmatically, not via from_definition(), see
    # TASK-2622); set the attribute _ensure_checkpointer() reads directly,
    # before the first checkpoint is built.
    flow._checkpoint_input_arg = metadata
    await flow.run_flow("go")

    resumed = await AgentsFlow.resume(
        "match-flow",
        agent_registry=registry,
        store=fake_store,
        expected_input=metadata,
    )
    assert resumed.flow_id == "match-flow"


async def test_resume_without_expected_input_skips_check(fake_store, registry) -> None:
    """expected_input=None (default) never raises, even with metadata-less checkpoints."""
    flow = AgentsFlow.from_definition(
        _definition(),
        agent_registry=registry,
        checkpoint=True,
        checkpoint_store=fake_store,
        flow_id="no-check-flow",
    )
    await flow.run_flow("go")

    resumed = await AgentsFlow.resume("no-check-flow", agent_registry=registry, store=fake_store)
    assert resumed.flow_id == "no-check-flow"


# ---------------------------------------------------------------------------
# checkpoint_definition / checkpoint_shared_data on AgentsFlow
# ---------------------------------------------------------------------------


async def test_explicit_graph_accepts_external_definition_without_to_definition(fake_store) -> None:
    """A graph with an unregistered node type would fail to_definition(); an
    external checkpoint_definition must let it checkpoint anyway."""
    flow = AgentsFlow(
        name="external-def-flow",
        flow_id="external-def-flow",
        checkpoint=True,
        checkpoint_store=fake_store,
        checkpoint_definition=FlowDefinition(
            flow="external-def-flow",
            nodes=[NodeDefinition(id="n1", type="agent", agent_ref="agent1")],
            edges=[],
        ),
    )

    flow.add_node(_PlainNode(node_id="n1"))
    # No add_edge() calls — legacy programmatic mode; nothing here calls
    # to_definition() because checkpoint_definition was supplied.
    result = await flow.run_flow("go")
    assert result.status.value == "completed"

    stored = await fake_store.latest("external-def-flow")
    assert stored is not None
    assert stored.definition.flow == "external-def-flow"


async def test_shared_data_projector_replaces_raw_shared_data(fake_store) -> None:
    checkpointer = FlowCheckpointer(
        flow_id="proj-1",
        flow_name="proj-flow",
        definition=_definition(),
        store=fake_store,
        shared_data_projector=lambda ctx: {"allowlisted": ctx.shared_data.get("safe_value")},
    )
    ctx = FlowContext(initial_task="t")
    ctx.shared_data["safe_value"] = "keep-me"
    ctx.shared_data["live_dependency"] = object()  # never reaches the projector's output
    ctx.mark_completed("n1", result={"ok": True})

    checkpoint = await checkpointer.checkpoint(ctx)

    assert checkpoint.context.shared_data == {"allowlisted": "keep-me"}


async def test_no_projector_keeps_raw_shared_data(fake_store) -> None:
    """Historical default: no projector means the full mapping is embedded."""
    checkpointer = FlowCheckpointer(
        flow_id="proj-2",
        flow_name="proj-flow",
        definition=_definition(),
        store=fake_store,
    )
    ctx = FlowContext(initial_task="t")
    ctx.shared_data["k"] = "v"
    ctx.mark_completed("n1", result={"ok": True})

    checkpoint = await checkpointer.checkpoint(ctx)

    assert checkpoint.context.shared_data == {"k": "v"}


# ---------------------------------------------------------------------------
# Backward compatibility: best-effort listener path unchanged
# ---------------------------------------------------------------------------


async def test_best_effort_checkpoint_behavior_unchanged(agents, registry, fake_store) -> None:
    """Default (non-required) flows still swallow/log listener write failures."""
    fake_store.put = AsyncMock(side_effect=ConnectionError("redis unavailable"))
    flow = AgentsFlow.from_definition(
        _definition(),
        agent_registry=registry,
        checkpoint=True,
        checkpoint_store=fake_store,
        flow_id="best-effort-flow",
    )

    # The listener path (make_listener()) must never propagate a write
    # failure into the flow — run_flow() completes normally regardless.
    result = await flow.run_flow("go")
    assert result.status.value == "completed"
    assert agents["agent1"].calls == 1
    assert agents["agent2"].calls == 1
    assert agents["agent3"].calls == 1
