"""Field/validator tests for the plan-run data models (TASK-3590, spec §2).

Covers ``PlanRecoveryConfig`` (D1 range enforcement), ``PlanDelta``,
``PlanRunMetadata`` (round-trip + schema-version pinning), ``PlanRunManifest``/
``PlanRunSummary`` (additive top-level keys) and ``PlanRunError.to_tool_result``.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from parrot.bots.flows.plan import ExecutionPlan, PlanNode
from parrot.tools.execution_plan.models import (
    PlanDelta,
    PlanRecoveryConfig,
    PlanRecoveryEnvelope,
    PlanRunError,
    PlanRunManifest,
    PlanRunMetadata,
    PlanRunSummary,
)

def _make_plan() -> ExecutionPlan:
    return ExecutionPlan(
        name="demo_plan",
        objective="Demonstrate the plan-run models.",
        nodes=[PlanNode(id="n1", tool="demo_tool", args={}, store_as="n1_out")],
    )


def _make_metadata(**overrides) -> PlanRunMetadata:
    plan = _make_plan()
    fields = dict(
        run_id="run-1",
        root_run_id="run-1",
        parent_run_id=None,
        plan=plan,
        original_plan=plan,
        source="objective",
        started_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        allowed_tools=["demo_tool"],
        plan_fingerprint="a" * 64,
        artifact_mode="memory",
    )
    fields.update(overrides)
    return PlanRunMetadata(**fields)


def test_recovery_config_defaults_and_ranges() -> None:
    config = PlanRecoveryConfig()
    assert config.max_repair_rounds == 2
    assert config.max_restore_bytes == 67_108_864
    assert config.checkpoint_probe_timeout == 2.0


@pytest.mark.parametrize("value", [3, -1])
def test_max_repair_rounds_out_of_range(value: int) -> None:
    with pytest.raises(ValidationError):
        PlanRecoveryConfig(max_repair_rounds=value)


@pytest.mark.parametrize("value", [math.inf, math.nan, 0.0])
def test_probe_timeout_must_be_finite_positive(value: float) -> None:
    with pytest.raises(ValidationError):
        PlanRecoveryConfig(checkpoint_probe_timeout=value)


def test_delta_requires_unique_nonempty_nodes() -> None:
    with pytest.raises(ValidationError):
        PlanDelta(nodes=[])

    dup_node = PlanNode(id="n1", tool="demo_tool", args={}, store_as="n1_out")
    with pytest.raises(ValidationError):
        PlanDelta(nodes=[dup_node, dup_node.model_copy()])

    # A single valid node is accepted, and PlanDelta has no plan-level fields.
    delta = PlanDelta(nodes=[dup_node])
    assert delta.nodes[0].id == "n1"
    with pytest.raises(ValidationError):
        PlanDelta(nodes=[dup_node], name="not-allowed")  # type: ignore[call-arg]


def test_metadata_roundtrip_and_schema_version() -> None:
    metadata = _make_metadata()
    dumped = metadata.model_dump(mode="json")
    restored = PlanRunMetadata.model_validate(dumped)
    assert restored == metadata

    dumped["schema_version"] = 2
    with pytest.raises(ValidationError):
        PlanRunMetadata.model_validate(dumped)


def test_manifest_keeps_frozen_keys_top_level() -> None:
    manifest = PlanRunManifest(
        plan_name="demo_plan",
        objective="Demonstrate the plan-run models.",
        session_id="sess-1",
        artifacts=[],
        nodes_total=1,
        nodes_ok=1,
        nodes_skipped=0,
        nodes_failed=0,
        duration_seconds=1.5,
        total_bytes_stored=0,
        status="completed",
        run_id="run-1",
        root_run_id="run-1",
        checkpoint_enabled=True,
        artifact_mode="memory",
        resume_level="process",
        resumable=False,
    )
    dumped = manifest.model_dump(mode="json")
    # ExecutionManifest top-level keys.
    assert dumped["plan_name"] == "demo_plan"
    assert dumped["nodes_total"] == 1
    # PlanRecoveryEnvelope top-level keys.
    assert dumped["run_id"] == "run-1"
    assert dumped["resume_level"] == "process"
    assert dumped["status"] == "completed"

    summary = PlanRunSummary(
        plan_name="demo_plan",
        nodes_total=1,
        nodes_done=0,
        run_id="run-1",
        root_run_id="run-1",
        checkpoint_enabled=True,
        artifact_mode="memory",
        resume_level="process",
        resumable=False,
    )
    dumped_summary = summary.model_dump(mode="json")
    assert dumped_summary["plan_name"] == "demo_plan"
    assert dumped_summary["status"] == "running"
    assert dumped_summary["run_id"] == "run-1"
    assert dumped_summary["uncheckpointed_progress"] is False


def test_error_to_tool_result_is_bounded() -> None:
    error = PlanRunError("unknown_run", "x" * 600)
    result = error.to_tool_result()
    assert result.status == "error"
    assert result.success is False
    assert result.result["code"] == "unknown_run"
    assert len(result.error) <= 500
    assert "manifest" not in result.result


def test_error_to_tool_result_merges_envelope() -> None:
    envelope = PlanRecoveryEnvelope(
        run_id="run-1",
        root_run_id="run-1",
        checkpoint_enabled=True,
        artifact_mode="memory",
        resume_level="process",
        resumable=False,
        recovery_reason="lease held by another process",
    )
    error = PlanRunError("run_lease_conflict", "cannot resume", envelope=envelope)
    result = error.to_tool_result()
    assert result.result["code"] == "run_lease_conflict"
    assert result.result["manifest"]["run_id"] == "run-1"
    assert result.result["manifest"]["recovery_reason"] == "lease held by another process"
