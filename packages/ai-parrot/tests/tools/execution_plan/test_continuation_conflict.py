"""FEAT-585 M4 root-lease continuation contention and delegation coverage."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from parrot.bots.flows.core.checkpoint import CheckpointPersistenceError, ContextSnapshot, FlowCheckpoint
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition
from parrot.bots.flows.plan import ExecutionPlan, PlanNode
from parrot.tools.execution_plan.checkpoint import LeaseDelegatingStore, PlanContinuation, degraded_lock
from parrot.tools.execution_plan.models import PLAN_RUN_SHARED_KEY, PlanRun, PlanRunError, PlanRunMetadata
from parrot.tools.execution_plan.runs import plan_fingerprint, process_identity

from ._recovery_fakes import SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio


def _metadata(run_id: str = "root") -> PlanRunMetadata:
    """Build a minimal root plan envelope for a checkpointed continuation."""
    plan = ExecutionPlan(
        name="continuation", objective="continue", nodes=[PlanNode(id="step", tool="tool", store_as="step_out")]
    )
    return PlanRunMetadata(
        run_id=run_id,
        root_run_id=run_id,
        plan=plan,
        original_plan=plan,
        source="plan_name",
        started_at=datetime.now(timezone.utc),
        allowed_tools=["tool"],
        plan_fingerprint=plan_fingerprint(plan),
        artifact_mode="memory",
        process_id=process_identity(),
    )


def _checkpoint(metadata: PlanRunMetadata, checkpoint_id: int) -> FlowCheckpoint:
    """Build a checkpoint whose revision can be compared by the continuation."""
    return FlowCheckpoint(
        flow_id=metadata.root_run_id,
        flow_name="continuation",
        checkpoint_id=checkpoint_id,
        created_at=datetime.now(timezone.utc),
        status="suspended",
        definition=FlowDefinition(
            flow=metadata.root_run_id,
            nodes=[NodeDefinition(id="step", type="agent", agent_ref="agent")],
        ),
        context=ContextSnapshot(
            initial_task=metadata.plan.objective,
            shared_data={PLAN_RUN_SHARED_KEY: metadata.model_dump(mode="json")},
        ),
    )


def _run(metadata: PlanRunMetadata, checkpoint_id: int = 1) -> PlanRun:
    """Build the resolved run view consumed by ``PlanContinuation``."""
    return PlanRun(
        metadata=metadata,
        checkpoint_id=checkpoint_id,
        status="running",
        checkpoint_enabled=True,
        resume_level="process",
        resumable=True,
    )


async def test_second_continuation_gets_run_busy_without_side_effects() -> None:
    """A competing continuation fails before its caller can dispatch work."""
    metadata = _metadata()
    store = SerializingFakeCheckpointStore()
    await store.put(_checkpoint(metadata, 1))
    first = PlanContinuation(_run(metadata), store=store)
    second = PlanContinuation(_run(metadata), store=store)

    async with first:
        with pytest.raises(PlanRunError, match="leased") as error:
            await second.__aenter__()
        assert error.value.code == "run_busy"

    async with second:
        assert store._leases == {metadata.root_run_id: second._holder}


async def test_delegating_store_hands_off_root_lease_without_inner_acquire() -> None:
    """A resumed root flow aliases its generated holder to the held lease holder."""
    store = SerializingFakeCheckpointStore()
    store._leases["root"] = "continuation-holder"
    adapter = LeaseDelegatingStore(
        store,
        root_flow_id="root",
        holder="continuation-holder",
        leased_flow_ids={"root"},
    )

    assert await adapter.acquire_lease("root", "flow-holder") is True
    assert store._leases == {"root": "continuation-holder"}
    assert await adapter.renew_lease("root", "flow-holder") is True
    await adapter.release_lease("root", "flow-holder")

    assert store._leases == {"root": "continuation-holder"}


async def test_delegating_store_refuses_older_write_allows_equal() -> None:
    """Covered flow writes retain equal-id final rewrites but reject older snapshots."""
    metadata = _metadata()
    store = SerializingFakeCheckpointStore()
    await store.put(_checkpoint(metadata, 2))
    adapter = LeaseDelegatingStore(store, root_flow_id="root", holder="holder", leased_flow_ids={"root"})

    with pytest.raises(CheckpointPersistenceError, match="stale write"):
        await adapter.put(_checkpoint(metadata, 1))
    await adapter.put(_checkpoint(metadata, 2))
    await adapter.put(_checkpoint(metadata, 3))
    assert (await store.latest("root")).checkpoint_id == 3  # type: ignore[union-attr]


async def test_child_flow_id_acquires_normally() -> None:
    """An uncovered child flow uses the inner store's ordinary lease lifecycle."""
    store = SerializingFakeCheckpointStore()
    adapter = LeaseDelegatingStore(store, root_flow_id="root", holder="holder", leased_flow_ids={"root"})

    assert await adapter.acquire_lease("child", "child-holder") is True
    assert await adapter.renew_lease("child", "child-holder") is True
    await adapter.release_lease("child", "child-holder")
    assert store._leases == {}


async def test_heartbeat_loss_sets_flag_and_raise_if_lease_lost() -> None:
    """A failed renewal marks the continuation busy before later dispatch work."""
    metadata = _metadata()
    store = SerializingFakeCheckpointStore()
    await store.put(_checkpoint(metadata, 1))
    continuation = PlanContinuation(_run(metadata), store=store, ttl=0.01)

    async with continuation:
        store._leases.clear()
        while not continuation.lease_lost:
            await asyncio.sleep(0)
        with pytest.raises(PlanRunError, match="lost") as error:
            continuation.raise_if_lease_lost()
        assert error.value.code == "run_busy"


async def test_stale_snapshot_is_rejected_and_lease_released() -> None:
    """A changed checkpoint revision releases the acquired lease before raising."""
    metadata = _metadata()
    store = SerializingFakeCheckpointStore()
    await store.put(_checkpoint(metadata, 2))

    with pytest.raises(PlanRunError, match="stale snapshot") as error:
        await PlanContinuation(_run(metadata, 1), store=store).__aenter__()

    assert error.value.code == "run_busy"
    assert store._leases == {}


async def test_release_on_exception_and_cancellation() -> None:
    """The root lease releases after both an ordinary exception and cancellation."""
    metadata = _metadata()
    store = SerializingFakeCheckpointStore()
    await store.put(_checkpoint(metadata, 1))

    with pytest.raises(RuntimeError):
        async with PlanContinuation(_run(metadata), store=store):
            raise RuntimeError("boom")
    assert store._leases == {}

    entered = asyncio.Event()

    async def hold_continuation() -> None:
        """Enter a continuation and wait until this task is cancelled."""
        async with PlanContinuation(_run(metadata), store=store):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(hold_continuation())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store._leases == {}


async def test_degraded_lock_serializes_same_run_id() -> None:
    """Uncheckpointed callers share one process-wide lock for the same run id."""
    lock = degraded_lock("uncheckpointed-root")
    assert lock is degraded_lock("uncheckpointed-root")
    acquired = asyncio.Event()

    async def wait_for_lock() -> None:
        """Record only after the already-held lock becomes available."""
        async with degraded_lock("uncheckpointed-root"):
            acquired.set()

    async with lock:
        task = asyncio.create_task(wait_for_lock())
        await asyncio.sleep(0)
        assert not acquired.is_set()
    await task
    assert acquired.is_set()
