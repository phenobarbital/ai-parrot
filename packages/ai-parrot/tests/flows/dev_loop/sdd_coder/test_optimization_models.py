"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop.sdd_coder.optimization_models import (
    BackgroundRegistration,
    BackgroundStatus,
    CompactionReceipt,
    EvidenceRef,
    ReviewCheckpoint,
    TaskCompletionEvidence,
    WorkflowEvent,
)

_EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
_FULL_SHA_A = "a" * 40
_FULL_SHA_B = "b" * 40


def _evidence_ref(artifact_id: str = "artifact-1", content: bytes = b"{}") -> EvidenceRef:
    """Build a valid EvidenceRef whose sha256 actually matches `content`."""
    digest = hashlib.sha256(content).hexdigest()
    return EvidenceRef(
        artifact_id=artifact_id,
        sha256=digest,
        relative_path=f"artifacts/{digest}.json",
        size_bytes=len(content),
        media_type="application/json",
    )


def _checkpoint_kwargs(**overrides: object) -> dict[str, object]:
    """Every ReviewCheckpoint field except `checkpoint_id`, with sane defaults."""
    base: dict[str, object] = dict(
        schema_version=1,
        feature="sdd-execution-optimization",
        execution_id=_EXECUTION_ID,
        worktree="/tmp/worktree",
        branch="feat-FEAT-584-sdd-execution-optimization",
        base_sha=_FULL_SHA_A,
        implementation_head=_FULL_SHA_B,
        spec_hash="c" * 64,
        index_hash="d" * 64,
        convention_hashes={"CLAUDE.md": "e" * 64},
        task_refs=[_evidence_ref("task-ref")],
        criteria_refs=[_evidence_ref("criteria-ref")],
        commits=[_FULL_SHA_A],
        validation_refs=[_evidence_ref("validation-ref")],
        evidence_refs=[_evidence_ref("evidence-ref")],
        user_constraints=["never touch clients/base.py"],
        pending_actions=["awaiting semantic review"],
        settlement_ref=_evidence_ref("settlement"),
        neutral_brief="Implement TASK-3558 optimization models.",
        context_id=None,
    )
    base.update(overrides)
    return base


def _build_checkpoint(**overrides: object) -> ReviewCheckpoint:
    """Construct a ReviewCheckpoint with a correctly-computed checkpoint_id."""
    kwargs = _checkpoint_kwargs(**overrides)
    checkpoint_id = ReviewCheckpoint.compute_checkpoint_id(**kwargs)
    return ReviewCheckpoint(checkpoint_id=checkpoint_id, **kwargs)


def test_reject_invalid_identity_and_time(tmp_path: Path) -> None:
    """Cross-field identity, reversed timestamps and extra fields are rejected."""
    now = datetime.now(timezone.utc)

    # extra fields are rejected (extra="forbid")
    with pytest.raises(ValidationError):
        EvidenceRef(
            artifact_id="a1",
            sha256="a" * 64,
            relative_path="artifacts/a.json",
            size_bytes=2,
            media_type="application/json",
            unexpected="nope",
        )

    # a non-UUID execution_id is rejected
    with pytest.raises(ValidationError):
        WorkflowEvent(
            event_id="evt-1",
            kind="task.accepted",
            execution_id="not-a-uuid",
            task_id="TASK-1",
            timestamp=now,
            source="engine",
        )

    # per-kind identity: attempt.dispatched requires task_id + attempt_uid
    with pytest.raises(ValidationError):
        WorkflowEvent(
            event_id="evt-2",
            kind="attempt.dispatched",
            execution_id=_EXECUTION_ID,
            timestamp=now,
            source="engine",
        )

    # a reversed started_at/ended_at window inside the payload is rejected
    with pytest.raises(ValidationError):
        WorkflowEvent(
            event_id="evt-3",
            kind="attempt.finished",
            execution_id=_EXECUTION_ID,
            task_id="TASK-1",
            attempt_uid="attempt-1",
            timestamp=now,
            source="engine",
            payload={
                "started_at": now.isoformat(),
                "ended_at": (now - timedelta(seconds=5)).isoformat(),
            },
        )

    # a naive timestamp (no tzinfo) is rejected
    with pytest.raises(ValidationError):
        WorkflowEvent(
            event_id="evt-4",
            kind="task.accepted",
            execution_id=_EXECUTION_ID,
            task_id="TASK-1",
            timestamp=datetime(2026, 9, 21, 12, 0, 0),
            source="engine",
        )

    # a forbidden key in the payload is rejected, wherever it is nested
    with pytest.raises(ValidationError):
        WorkflowEvent(
            event_id="evt-5",
            kind="task.accepted",
            execution_id=_EXECUTION_ID,
            task_id="TASK-1",
            timestamp=now,
            source="engine",
            payload={"nested": {"secret": "shh"}},
        )

    # a malformed task_id is rejected
    with pytest.raises(ValidationError):
        WorkflowEvent(
            event_id="evt-6",
            kind="task.accepted",
            execution_id=_EXECUTION_ID,
            task_id="not-a-task-id",
            timestamp=now,
            source="engine",
        )

    # implementation_sha must be a full (non-abbreviated) SHA
    with pytest.raises(ValidationError):
        TaskCompletionEvidence(
            feature_slug="sdd-execution-optimization",
            task_id="TASK-3558",
            implementation_sha="abc123",
            validation_refs=[_evidence_ref("validation")],
            review_evidence=_evidence_ref("review"),
            completion_facts={"tests_green": True},
        )

    # a fully valid evidence record is accepted
    evidence = TaskCompletionEvidence(
        feature_slug="sdd-execution-optimization",
        task_id="TASK-3558",
        implementation_sha=_FULL_SHA_A,
        validation_refs=[_evidence_ref("validation")],
        review_evidence=_evidence_ref("review"),
        fix_commits=[_FULL_SHA_B],
        completion_facts={"tests_green": True},
    )
    assert evidence.fix_commits == [_FULL_SHA_B]


def test_nullable_authority_and_outcome(tmp_path: Path) -> None:
    """Unknown/native/logical jobs do not invent POSIX exit codes or tokens."""
    now = datetime.now(timezone.utc)

    # a lost-authority status is unknown with no stale exit_code
    status = BackgroundStatus(
        state="unknown",
        outcome=None,
        exit_code=None,
        source="supervisor-registry",
        authority="engine",
        verified_at=None,
        stale=True,
        revision=3,
        changed=True,
        elapsed_ms=10,
        next_poll_after_ms=5000,
    )
    assert status.exit_code is None
    assert status.stale is True

    # unknown carrying an exit_code is rejected
    with pytest.raises(ValidationError):
        BackgroundStatus(
            state="unknown",
            outcome=None,
            exit_code=1,
            source="supervisor-registry",
            authority="engine",
            verified_at=None,
            stale=True,
            revision=3,
            changed=True,
            elapsed_ms=10,
            next_poll_after_ms=5000,
        )

    # native-agent (host_observation) never yields a POSIX exit_code
    with pytest.raises(ValidationError):
        BackgroundStatus(
            state="finished",
            outcome="completed",
            exit_code=0,
            source="native-handback",
            authority="host_observation",
            verified_at=now,
            stale=False,
            revision=1,
            changed=True,
            elapsed_ms=10,
            next_poll_after_ms=5000,
        )

    # a pending/running state never carries an outcome yet
    with pytest.raises(ValidationError):
        BackgroundStatus(
            state="running",
            outcome="completed",
            exit_code=None,
            source="supervisor",
            authority="supervisor",
            verified_at=now,
            stale=False,
            revision=1,
            changed=True,
            elapsed_ms=10,
            next_poll_after_ms=5000,
        )

    # finished always carries a known outcome
    with pytest.raises(ValidationError):
        BackgroundStatus(
            state="finished",
            outcome=None,
            exit_code=None,
            source="supervisor",
            authority="supervisor",
            verified_at=now,
            stale=False,
            revision=1,
            changed=True,
            elapsed_ms=10,
            next_poll_after_ms=5000,
        )

    # exit_code preserves a negative signal-carrying code
    signaled = BackgroundStatus(
        state="finished",
        outcome="failed",
        exit_code=-9,
        source="supervisor",
        authority="supervisor",
        verified_at=now,
        stale=False,
        revision=2,
        changed=True,
        elapsed_ms=10,
        next_poll_after_ms=5000,
    )
    assert signaled.exit_code == -9

    # exit_code 124 alone is preserved verbatim, never auto-labeled timed_out
    exit_124 = BackgroundStatus(
        state="finished",
        outcome="failed",
        exit_code=124,
        source="supervisor",
        authority="supervisor",
        verified_at=now,
        stale=False,
        revision=2,
        changed=True,
        elapsed_ms=10,
        next_poll_after_ms=5000,
    )
    assert exit_124.exit_code == 124
    assert exit_124.outcome == "failed"

    # a logical MCP job legitimately has no POSIX exit code AND no host tokens
    receipt = CompactionReceipt(
        checkpoint_id="f" * 64,
        context_id="ctx-1",
        status="skipped",
        reason="no adapter available for this context",
        backend="unknown",
        before_bytes=1000,
        after_bytes=None,
        before_tokens=None,
        after_tokens=None,
        elapsed_ms=0,
    )
    assert receipt.before_tokens is None
    assert receipt.after_tokens is None

    # a native agent handle never claims a rooted (non-absolute) worktree
    with pytest.raises(ValidationError):
        BackgroundRegistration(
            handle="handle-1",
            execution_id=_EXECUTION_ID,
            task_id="TASK-3558",
            attempt_uid="attempt-1",
            launch_id="launch-1",
            owner_instance_id="owner-1",
            kind="native_agent",
            authority="host_observation",
            worktree="relative/worktree",
            backend="claude",
        )

    # a well-formed registration is accepted, with a UTC started_at
    registration = BackgroundRegistration(
        handle="handle-2",
        execution_id=_EXECUTION_ID,
        task_id="TASK-3558",
        attempt_uid="attempt-1",
        launch_id="launch-2",
        owner_instance_id="owner-1",
        kind="native_agent",
        authority="host_observation",
        worktree="/tmp/worktree",
        backend="claude",
        started_at=now,
    )
    assert registration.worktree == "/tmp/worktree"


def test_canonical_json_roundtrip(tmp_path: Path) -> None:
    """Versioned contracts serialize deterministically and preserve pending actions."""
    checkpoint = _build_checkpoint(pending_actions=["fix lint", "rerun tests"])

    # deterministic: recomputing from the same fields yields the same id
    kwargs = _checkpoint_kwargs(pending_actions=["fix lint", "rerun tests"])
    assert ReviewCheckpoint.compute_checkpoint_id(**kwargs) == checkpoint.checkpoint_id

    # persisted to disk and reloaded, still validates and keeps pending_actions
    out_file = tmp_path / "checkpoint.json"
    out_file.write_text(checkpoint.model_dump_json(), encoding="utf-8")
    reloaded = ReviewCheckpoint.model_validate_json(out_file.read_text(encoding="utf-8"))
    assert reloaded == checkpoint
    assert reloaded.pending_actions == ["fix lint", "rerun tests"]
    assert reloaded.schema_version == 1

    # a stale checkpoint_id (content mutated without recomputing) is rejected
    stale_kwargs = _checkpoint_kwargs(pending_actions=["different actions entirely"])
    with pytest.raises(ValidationError):
        ReviewCheckpoint(checkpoint_id=checkpoint.checkpoint_id, **stale_kwargs)

    # WorkflowEvent round-trips too, preserving schema_version and payload
    event = WorkflowEvent(
        event_id="evt-roundtrip",
        kind="review.checkpoint",
        execution_id=_EXECUTION_ID,
        timestamp=datetime.now(timezone.utc),
        source="engine",
        payload={"checkpoint_id": checkpoint.checkpoint_id},
    )
    reloaded_event = WorkflowEvent.model_validate_json(event.model_dump_json())
    assert reloaded_event == event
    assert reloaded_event.schema_version == 1
