"""Tests for canonical served-ledger entry serialization."""

from datetime import datetime, timezone

from parrot.interagent import CallCost, CallerIdentity, ServedLedgerEntry


def _entry(*, signature: str = "signature-a") -> ServedLedgerEntry:
    """Build a deterministic ledger entry for canonicalization tests."""
    return ServedLedgerEntry(
        entry_id="entry-1",
        created_at=datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc),
        caller=CallerIdentity(agent_id="hr", network="internal"),
        cap_id="hr.reports.manager_of",
        category="hr.reports",
        contract_hash="sha256:" + "a" * 64,
        args_digest="sha256:" + "b" * 64,
        result_kind="inline",
        cost=CallCost(duration_ms=1),
        backing="deterministic",
        status="OK",
        trace_id="trace-1",
        signature=signature,
    )


def test_canonical_bytes_excludes_signature_and_is_stable() -> None:
    """Signature changes do not affect the byte representation to be signed."""
    first = _entry(signature="first")
    second = _entry(signature="second")

    assert first.canonical_bytes() == second.canonical_bytes()
    assert b'"signature"' not in first.canonical_bytes()
