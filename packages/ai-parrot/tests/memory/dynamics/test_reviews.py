"""Behavioral acceptance tests for verified grade selection."""

from datetime import datetime, timezone
from typing import Any

from parrot.memory.agent_memory.models import ChatStorageEvidenceRef, MemoryRequestScope
from parrot.memory.dynamics.grade import select_grade
from parrot.memory.dynamics.models import Grade, ReviewSignal


def _scope() -> MemoryRequestScope:
    """Build one trusted runtime-derived scope."""
    return MemoryRequestScope(
        tenant_id="tenant-a",
        agent_id="agent-a",
        user_id="user-a",
        session_id="session-a",
        turn_id="turn-a",
        identity_provenance="runtime_derived",
    )


def _signal(**overrides: Any) -> ReviewSignal:
    """Build a verified first-attempt success signal, overridden per case."""
    scope = _scope()
    data: dict[str, Any] = {
        "outcome_id": "outcome-a",
        "outcome_revision": 0,
        "observed_at": datetime(2026, 11, 14, tzinfo=timezone.utc),
        "scope": scope,
        "evidence_ref": ChatStorageEvidenceRef(
            tenant_id=scope.tenant_id,
            agent_name=scope.agent_id,
            user_id=scope.user_id or "",
            session_id=scope.session_id or "",
            turn_id=scope.turn_id,
        ).to_reference(),
        "source": "tool_runtime",
        "outcome": "success",
        "first_attempt": True,
        "correction_count": 0,
    }
    data.update(overrides)
    return ReviewSignal(**data)


def _failure(signature: str = "Timeout   contacting  Service") -> ReviewSignal:
    """Build a verified failure signal with a raw, un-normalized signature."""
    return _signal(outcome="failure", first_attempt=False, error_signature=signature)


def test_ordered_grade_precedence() -> None:
    """Apply AGAIN, EASY, HARD and GOOD in contract order, capping overlap recovery at GOOD."""
    again = select_grade(
        _failure(),
        attribution="cited",
        memory_error_signature="timeout contacting service",
        verified_recovery=False,
    )
    assert again is Grade.AGAIN

    recovered = _signal(first_attempt=False, correction_count=2, recovery_refs=("commit:abc123",))
    assert (
        select_grade(recovered, attribution="cited", memory_error_signature=None, verified_recovery=True) is Grade.EASY
    )
    assert (
        select_grade(recovered, attribution="overlap", memory_error_signature=None, verified_recovery=True)
        is Grade.GOOD
    )

    corrected = _signal(first_attempt=False, correction_count=1)
    assert (
        select_grade(corrected, attribution="cited", memory_error_signature=None, verified_recovery=False) is Grade.HARD
    )
    # A recovery claim without a structural reference falls through to the corrections rule.
    assert (
        select_grade(corrected, attribution="cited", memory_error_signature=None, verified_recovery=True) is Grade.HARD
    )

    first_try = _signal()
    for attribution in ("cited", "overlap"):
        assert (
            select_grade(first_try, attribution=attribution, memory_error_signature=None, verified_recovery=False)
            is Grade.GOOD
        )


def test_missing_or_unrelated_signal_no_review() -> None:
    """Produce no review without attribution, a relevant failure or a completed outcome."""
    assert select_grade(_signal(), attribution=None, memory_error_signature=None, verified_recovery=True) is None
    assert (
        select_grade(
            _failure(),
            attribution=None,
            memory_error_signature="timeout contacting service",
            verified_recovery=False,
        )
        is None
    )

    for outcome in ("cancelled", "incomplete"):
        signal = _signal(outcome=outcome, first_attempt=False)
        assert select_grade(signal, attribution="cited", memory_error_signature=None, verified_recovery=True) is None

    for memory_signature in ("permission denied", None, "", "   "):
        assert (
            select_grade(
                _failure(),
                attribution="cited",
                memory_error_signature=memory_signature,
                verified_recovery=False,
            )
            is None
        )

    retried_without_evidence = _signal(first_attempt=False)
    assert (
        select_grade(
            retried_without_evidence,
            attribution="cited",
            memory_error_signature=None,
            verified_recovery=False,
        )
        is None
    )
