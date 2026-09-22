"""Unit tests for the checkpoint-derived run resolver (TASK-3593, spec §3 Module 3).

Covers AC-1..AC-5: typed-ref round trip / fail-closed on an unregistered
type, ``project_run`` ordering/counters/pending-vs-blocked, the resolver's
repair-lineage consolidation, capability-scoped tier classification and
scope enforcement.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pytest

from parrot.bots.flows.core.checkpoint import ContextSnapshot, FlowCheckpoint
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition
from parrot.bots.flows.plan import ArtifactRef, ExecutionPlan, PlanNode, build_manifest
from parrot.tools.execution_plan.models import PLAN_RUN_SHARED_KEY, PlanRunError, PlanRunMetadata
from parrot.tools.execution_plan.runs import (
    PlanRunResolver,
    classify_miss,
    plan_fingerprint,
    process_identity,
    project_run,
    read_run_metadata,
    register_plan_checkpoint_types,
    select_latest,
)
from parrot.tools.working_memory.task_memory.models import TaskScope

from ._recovery_fakes import SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio


def _chain_plan(node_ids: tuple = ("a", "b", "c")) -> ExecutionPlan:
    """A linear chain plan a -> b -> c (or a prefix of it)."""
    nodes = []
    prev: Optional[str] = None
    for node_id in node_ids:
        nodes.append(
            PlanNode(
                id=node_id,
                tool=node_id,
                store_as=f"{node_id}_out",
                depends_on=[prev] if prev is not None else [],
            )
        )
        prev = node_id
    return ExecutionPlan(name="chain", objective="chain test", nodes=nodes)


def _metadata(plan: ExecutionPlan, **overrides: Any) -> PlanRunMetadata:
    run_id = overrides.get("run_id", "run-1")
    defaults: Dict[str, Any] = dict(
        run_id=run_id,
        root_run_id=overrides.get("root_run_id", run_id),
        parent_run_id=None,
        plan=plan,
        original_plan=plan,
        source="plan_name",
        started_at=datetime.now(timezone.utc),
        allowed_tools=sorted({node.tool for node in plan.nodes}),
        plan_fingerprint=plan_fingerprint(plan),
        artifact_mode="memory",
        process_id=process_identity(),
    )
    defaults.update(overrides)
    return PlanRunMetadata(**defaults)


def _checkpoint(
    *,
    status: str,
    results: Dict[str, ArtifactRef],
    errors: Dict[str, dict],
    metadata: PlanRunMetadata,
    checkpoint_id: int = 1,
    flow_id: Optional[str] = None,
) -> FlowCheckpoint:
    """Build a hand-constructed ``FlowCheckpoint`` carrying the ``plan_run`` envelope."""
    flow_id = flow_id or metadata.run_id
    definition = FlowDefinition(
        flow=flow_id,
        nodes=[NodeDefinition(id=node.id, type="agent", agent_ref="agent") for node in metadata.plan.nodes],
    )
    return FlowCheckpoint(
        flow_id=flow_id,
        flow_name="execution-plan",
        checkpoint_id=checkpoint_id,
        created_at=datetime.now(timezone.utc),
        status=status,
        definition=definition,
        context=ContextSnapshot(
            initial_task=metadata.plan.objective,
            results=dict(results),
            completed_tasks=list(results),
            completion_order=list(results),
            shared_data={PLAN_RUN_SHARED_KEY: metadata.model_dump(mode="json")},
            errors=dict(errors),
        ),
    )


# ── AC-1: typed-ref round trip, fail-closed on an unregistered type ────────


async def test_artifact_ref_checkpoint_roundtrip() -> None:
    register_plan_checkpoint_types()
    plan = _chain_plan(("a",))
    metadata = _metadata(plan, run_id="run-roundtrip", root_run_id="run-roundtrip")
    ref = ArtifactRef(node_id="a", status="ok", keys=["a_out"], bytes_stored=12)
    checkpoint = _checkpoint(
        status="completed", results={"a": ref}, errors={}, metadata=metadata, flow_id="run-roundtrip"
    )

    store = SerializingFakeCheckpointStore()
    await store.put(checkpoint)
    latest = await store.latest("run-roundtrip")

    assert latest is not None
    assert isinstance(latest.context.results["a"], ArtifactRef)
    assert latest.context.results["a"] == ref

    run = project_run(latest, metadata=metadata)
    assert run.refs == [ref]
    assert run.status == "completed"
    assert run.checkpoint_enabled is True


async def test_unregistered_type_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bytes encoded with a fresh (unregistered) serializer registry degrade to a lossy repr and fail closed."""
    import parrot.bots.flows.core.checkpoint.serializer as serializer_module

    # Fresh registry for BOTH encode and decode — unlike an already-tagged
    # envelope whose tag simply isn't recognized yet (recoverable once
    # something registers it), a type unregistered at ENCODE time degrades
    # irreversibly to `{"__type__": "lossy", "__repr__": ...}` (serializer.py
    # :205-221) and no later registration can undo that.
    monkeypatch.setattr(serializer_module, "_DEFAULT_TYPES", {})

    plan = _chain_plan(("a",))
    metadata = _metadata(plan, run_id="run-unreg", root_run_id="run-unreg")
    ref = ArtifactRef(node_id="a", status="ok")
    checkpoint = _checkpoint(status="completed", results={"a": ref}, errors={}, metadata=metadata, flow_id="run-unreg")

    store = SerializingFakeCheckpointStore()
    await store.put(checkpoint)
    latest = await store.latest("run-unreg")

    assert latest is not None
    assert not isinstance(latest.context.results["a"], ArtifactRef)
    assert latest.context.results["a"] == repr(ref)

    with pytest.raises(PlanRunError) as excinfo:
        project_run(latest, metadata=metadata)
    assert excinfo.value.code == "checkpoint_invalid"


# ── AC-2: project_run ordering, pending vs blocked, counters ───────────────


def test_manifest_projection_orders_and_counts() -> None:
    plan = _chain_plan(("a", "b", "c"))
    metadata = _metadata(plan, run_id="run-order", root_run_id="run-order")
    results = {
        "a": ArtifactRef(node_id="a", status="ok", bytes_stored=10),
        "c": ArtifactRef(node_id="c", status="partial", errors=["x"]),
        "b": ArtifactRef(node_id="b", status="skipped"),
    }
    checkpoint = _checkpoint(status="completed", results=results, errors={}, metadata=metadata, flow_id="run-order")

    run = project_run(checkpoint, metadata=metadata)

    assert [ref.node_id for ref in run.refs] == ["a", "b", "c"]
    assert run.status == "partial"
    manifest = build_manifest(plan, run.refs)
    assert run.nodes_done == manifest.nodes_ok + manifest.nodes_skipped + manifest.nodes_failed
    assert manifest.nodes_ok == 1
    assert manifest.nodes_skipped == 1
    assert manifest.nodes_failed == 1


def test_pending_vs_blocked() -> None:
    plan = _chain_plan(("a", "b"))
    metadata = _metadata(plan, run_id="run-pending", root_run_id="run-pending")
    ref_a = ArtifactRef(node_id="a", status="ok")

    running_checkpoint = _checkpoint(
        status="running", results={"a": ref_a}, errors={}, metadata=metadata, checkpoint_id=1, flow_id="run-pending"
    )
    run_running = project_run(running_checkpoint, metadata=metadata)
    assert [ref.node_id for ref in run_running.refs] == ["a"]
    assert run_running.status == "running"

    failed_checkpoint = _checkpoint(
        status="failed", results={"a": ref_a}, errors={}, metadata=metadata, checkpoint_id=2, flow_id="run-pending"
    )
    run_failed = project_run(failed_checkpoint, metadata=metadata)
    assert [ref.node_id for ref in run_failed.refs] == ["a", "b"]
    assert run_failed.refs[1].status == "error"
    assert "blocked" in run_failed.refs[1].errors[0]
    assert run_failed.status == "partial"


# ── AC-3: resolver lineage consolidation, cycle/missing-ancestor/schema ────


async def test_resolver_follows_active_child_and_consolidates() -> None:
    plan = _chain_plan(("a", "b"))
    root_metadata = _metadata(
        plan,
        run_id="root-1",
        root_run_id="root-1",
        active_child_run_id="child-1",
        repair_children=["child-1"],
    )
    ref_a = ArtifactRef(node_id="a", status="ok")
    root_checkpoint = _checkpoint(
        status="failed",
        results={"a": ref_a},
        errors={"b": {"type": "RuntimeError", "message": "boom", "repr": "RuntimeError('boom')"}},
        metadata=root_metadata,
        flow_id="root-1",
    )

    child_metadata = _metadata(plan, run_id="child-1", root_run_id="root-1", parent_run_id="root-1")
    ref_b = ArtifactRef(node_id="b", status="ok")
    child_checkpoint = _checkpoint(
        status="completed", results={"b": ref_b}, errors={}, metadata=child_metadata, flow_id="child-1"
    )

    store = SerializingFakeCheckpointStore()
    await store.put(root_checkpoint)
    await store.put(child_checkpoint)

    resolver = PlanRunResolver(store=store, durable_store=None, scope=None, cache={})
    run = await resolver.resolve("root-1")

    assert [ref.node_id for ref in run.refs] == ["a", "b"]
    assert run.refs[0].status == "ok"
    assert run.refs[1].status == "ok"
    assert run.status == "completed"
    assert run.nodes_done == 2
    assert run.metadata.run_id == "child-1"


async def test_resolver_rejects_cycle_missing_ancestor_schema() -> None:
    plan = _chain_plan(("a",))
    store = SerializingFakeCheckpointStore()
    resolver = PlanRunResolver(store=store, durable_store=None, scope=None, cache={})

    # Cycle: active_child_run_id points back at the run itself.
    cycle_metadata = _metadata(plan, run_id="root-cycle", root_run_id="root-cycle", active_child_run_id="root-cycle")
    cycle_checkpoint = _checkpoint(
        status="failed", results={}, errors={}, metadata=cycle_metadata, flow_id="root-cycle"
    )
    await store.put(cycle_checkpoint)
    with pytest.raises(PlanRunError) as cycle_exc:
        await resolver.resolve("root-cycle")
    assert cycle_exc.value.code == "checkpoint_invalid"

    # Missing ancestor: active_child_run_id names a checkpoint that was never written.
    missing_metadata = _metadata(
        plan,
        run_id="root-missing",
        root_run_id="root-missing",
        active_child_run_id="ghost-child",
        repair_children=["ghost-child"],
    )
    missing_checkpoint = _checkpoint(
        status="failed", results={}, errors={}, metadata=missing_metadata, flow_id="root-missing"
    )
    await store.put(missing_checkpoint)
    with pytest.raises(PlanRunError) as missing_exc:
        await resolver.resolve("root-missing")
    assert missing_exc.value.code == "checkpoint_invalid"

    # schema_version mismatch: fails closed at read_run_metadata (consulted by resolve()).
    schema_metadata = _metadata(plan, run_id="root-schema", root_run_id="root-schema")
    schema_checkpoint = _checkpoint(
        status="running", results={}, errors={}, metadata=schema_metadata, flow_id="root-schema"
    )
    bad_envelope = dict(schema_metadata.model_dump(mode="json"))
    bad_envelope["schema_version"] = 2
    schema_checkpoint.context.shared_data["plan_run"] = bad_envelope
    with pytest.raises(PlanRunError) as schema_exc:
        read_run_metadata(schema_checkpoint)
    assert schema_exc.value.code == "checkpoint_invalid"


# ── AC-4: capability-scoped tier classification ─────────────────────────────


async def test_tier_classification() -> None:
    durable_resolver = PlanRunResolver(
        store=SerializingFakeCheckpointStore(),
        durable_store=SerializingFakeCheckpointStore(durable=True),
        scope=None,
        cache={},
    )
    with pytest.raises(PlanRunError) as durable_exc:
        await durable_resolver.resolve("missing-run")
    assert durable_exc.value.code == "unknown_run"
    assert classify_miss(durable_resolver._store, durable_resolver._durable) == "unknown_run"

    ephemeral_resolver = PlanRunResolver(
        store=SerializingFakeCheckpointStore(), durable_store=None, scope=None, cache={}
    )
    with pytest.raises(PlanRunError) as ephemeral_exc:
        await ephemeral_resolver.resolve("missing-run")
    assert ephemeral_exc.value.code == "missing_or_expired"

    unconfigured_resolver = PlanRunResolver(store=None, durable_store=None, scope=None, cache={})
    with pytest.raises(PlanRunError) as unconfigured_exc:
        await unconfigured_resolver.resolve("missing-run")
    assert unconfigured_exc.value.code == "checkpoint_unavailable"


# ── AC-5: scope enforcement ─────────────────────────────────────────────────


async def test_scope_mismatch() -> None:
    plan = _chain_plan(("a",))
    trusted_scope = TaskScope(chatbot_id="execution-plan", user_id="host-user", session_id="host-session")
    other_scope = TaskScope(chatbot_id="execution-plan", user_id="other-user", session_id="other-session")
    metadata = _metadata(plan, run_id="run-scope", root_run_id="run-scope", scope_key=other_scope.cache_key())
    checkpoint = _checkpoint(
        status="completed",
        results={"a": ArtifactRef(node_id="a", status="ok")},
        errors={},
        metadata=metadata,
        flow_id="run-scope",
    )
    store = SerializingFakeCheckpointStore()
    await store.put(checkpoint)

    resolver = PlanRunResolver(store=store, durable_store=None, scope=trusted_scope, cache={})
    with pytest.raises(PlanRunError) as excinfo:
        await resolver.resolve("run-scope")
    assert excinfo.value.code == "scope_mismatch"


# ── select_latest: greatest id across tiers, corruption on disagreement ────


async def test_select_latest_prefers_greatest_id_and_detects_corruption() -> None:
    plan = _chain_plan(("a",))
    metadata = _metadata(plan, run_id="run-sel", root_run_id="run-sel")
    ref = ArtifactRef(node_id="a", status="ok")
    older = _checkpoint(status="running", results={}, errors={}, metadata=metadata, checkpoint_id=1, flow_id="run-sel")
    newer = _checkpoint(
        status="completed", results={"a": ref}, errors={}, metadata=metadata, checkpoint_id=2, flow_id="run-sel"
    )

    store = SerializingFakeCheckpointStore()
    durable = SerializingFakeCheckpointStore(durable=True)
    await store.put(older)
    await durable.put(newer)

    latest = await select_latest(store, durable, "run-sel")
    assert latest is not None
    assert latest.checkpoint_id == 2
    assert latest.status == "completed"

    conflicting_store = SerializingFakeCheckpointStore()
    conflicting_durable = SerializingFakeCheckpointStore(durable=True)
    diverged = _checkpoint(
        status="failed", results={}, errors={}, metadata=metadata, checkpoint_id=2, flow_id="run-sel"
    )
    await conflicting_store.put(newer)
    await conflicting_durable.put(diverged)

    with pytest.raises(PlanRunError) as excinfo:
        await select_latest(conflicting_store, conflicting_durable, "run-sel")
    assert excinfo.value.code == "checkpoint_invalid"
