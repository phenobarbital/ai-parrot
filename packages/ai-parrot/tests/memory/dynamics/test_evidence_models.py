"""Behavioral acceptance tests for exposure, review evidence and durable backend contracts."""

from datetime import datetime, timezone

import pytest

from parrot.memory.agent_memory.models import ChatStorageEvidenceRef, MemoryRequestScope
from parrot.memory.dynamics.models import (
    CheckedPattern,
    MemoryRef,
    ReviewCommand,
    ReviewReceipt,
    ReviewSignal,
)
from parrot.memory.episodic.models import MemoryNamespace


def _scope() -> MemoryRequestScope:
    """Build one trusted scope with all dimensions needed by ChatStorage evidence."""
    return MemoryRequestScope(
        tenant_id="tenant-a",
        agent_id="agent-a",
        user_id="user-a",
        session_id="session-a",
        turn_id="turn-a",
        identity_provenance="runtime_derived",
    )


def _ref(scope: MemoryRequestScope) -> MemoryRef:
    """Build one delivered episode reference inside the trusted scope."""
    return MemoryRef(
        namespace=MemoryNamespace(
            tenant_id=scope.tenant_id,
            agent_id=scope.agent_id,
            user_id=scope.user_id,
            session_id=scope.session_id,
        ),
        kind="episode",
        memory_id="episode-a",
        content_version="v1",
    )


def _signal(scope: MemoryRequestScope) -> ReviewSignal:
    """Build one valid runtime-derived success signal."""
    evidence_ref = ChatStorageEvidenceRef(
        tenant_id=scope.tenant_id,
        agent_name=scope.agent_id,
        user_id=scope.user_id or "",
        session_id=scope.session_id or "",
        turn_id=scope.turn_id,
    ).to_reference()
    return ReviewSignal(
        outcome_id="outcome-a",
        outcome_revision=0,
        observed_at=datetime(2026, 11, 14, tzinfo=timezone.utc),
        scope=scope,
        evidence_ref=evidence_ref,
        source="tool_runtime",
        outcome="success",
        first_attempt=True,
        correction_count=0,
    )


def test_synthetic_and_forged_scope_rejected() -> None:
    """Reject synthetic source claims and evidence or refs from another request scope."""
    scope = _scope()
    signal_data = _signal(scope).model_dump()

    with pytest.raises(ValueError):
        ReviewSignal(**{**signal_data, "source": "synthetic"})
    with pytest.raises(ValueError):
        ReviewSignal(**{**signal_data, "verified": True})
    forged_evidence = ChatStorageEvidenceRef(
        tenant_id=scope.tenant_id,
        agent_name=scope.agent_id,
        user_id="another-user",
        session_id=scope.session_id or "",
        turn_id=scope.turn_id,
    ).to_reference()
    with pytest.raises(ValueError, match="match the request scope"):
        ReviewSignal(**{**signal_data, "evidence_ref": forged_evidence})
    mismatched_ref = MemoryRef(
        namespace=MemoryNamespace(
            tenant_id=scope.tenant_id,
            agent_id=scope.agent_id,
            user_id="another-user",
            session_id=scope.session_id,
        ),
        kind="episode",
        memory_id="episode-a",
        content_version="v1",
    )
    with pytest.raises(ValueError, match="namespace must match"):
        ReviewCommand(ref=mismatched_ref, signal=_signal(scope), exposure_id="exposure-a", expected_revision=0)


def test_receipt_requires_durable_identity() -> None:
    """Require receipt identities and status-specific durable acknowledgement invariants."""
    scope = _scope()
    command = ReviewCommand(ref=_ref(scope), signal=_signal(scope), exposure_id="exposure-a", expected_revision=2)
    receipt = ReviewReceipt(
        status="applied",
        dedupe_key=command.dedupe_key,
        outcome_id=command.signal.outcome_id,
        ref_key=command.ref.canonical_key,
        apply_revision=2,
    )

    assert receipt.apply_revision == command.expected_revision
    assert len(command.payload_digest) == 64
    with pytest.raises(ValueError, match="require apply_revision"):
        ReviewReceipt(
            status="duplicate",
            dedupe_key=command.dedupe_key,
            outcome_id=command.signal.outcome_id,
            ref_key=command.ref.canonical_key,
        )
    with pytest.raises(ValueError, match="durable replay_ref"):
        ReviewReceipt(
            status="pending",
            dedupe_key=command.dedupe_key,
            outcome_id=command.signal.outcome_id,
            ref_key=command.ref.canonical_key,
        )
    with pytest.raises(ValueError, match="cannot carry apply_revision"):
        ReviewReceipt(
            status="conflict",
            dedupe_key=command.dedupe_key,
            outcome_id=command.signal.outcome_id,
            ref_key=command.ref.canonical_key,
            apply_revision=2,
        )


def test_checked_pattern_is_not_proof() -> None:
    """Keep checked patterns as untrusted claims without caller-supplied grades or proof."""
    scope = _scope()
    pattern = CheckedPattern(pattern="avoid stale context", ref=_ref(scope), exposure_id="exposure-a")

    assert pattern.evidence_refs == ()
    assert "grade" not in pattern.model_dump()
    with pytest.raises(ValueError):
        CheckedPattern(
            pattern="avoid stale context",
            ref=_ref(scope),
            exposure_id="exposure-a",
            grade="easy",
        )
