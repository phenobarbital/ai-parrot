"""Tests for the signed, fail-closed Squawk served ledger."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from types import TracebackType
from typing import Any

import pytest

from parrot.interagent import CallCost, CallerIdentity, ServedLedgerEntry
from parrot.security.audit_ledger import LocalHMACSigner
from parrot.squawk.server import LedgerUnavailable, ServedLedger, postgres_ledger_sink


def _entry(entry_id: str = "entry-1") -> ServedLedgerEntry:
    """Build a deterministic served-ledger entry."""
    return ServedLedgerEntry(
        entry_id=entry_id,
        created_at=datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc),
        caller=CallerIdentity(agent_id="hr-agent", network="internal"),
        cap_id="hr.reports.manager_of",
        category="hr.reports",
        contract_hash="sha256:" + "a" * 64,
        args_digest="sha256:" + "b" * 64,
        result_kind="inline",
        result_digest="sha256:" + "c" * 64,
        cost=CallCost(duration_ms=12, rows=1),
        backing="deterministic",
        status="OK",
        trace_id="trace-1",
        correlation_id="correlation-1",
    )


@pytest.mark.asyncio
async def test_signature_round_trip_and_tamper_detection() -> None:
    """Verify a signed entry and reject a modified signed entry."""
    ledger = ServedLedger(LocalHMACSigner(b"test-secret"))

    signed = await ledger.append(_entry())

    assert signed.signature
    assert await ledger.verify(signed) is True
    assert await ledger.verify(signed.model_copy(update={"args_digest": "sha256:" + "d" * 64})) is False


@pytest.mark.asyncio
async def test_required_sink_failure_does_not_retain_entry() -> None:
    """Raise and avoid retaining an entry when its required sink fails."""

    async def bad_sink(payload: str) -> None:
        """Simulate an unavailable durable sink."""
        raise RuntimeError(f"database unavailable for {len(payload)} bytes")

    ledger = ServedLedger(LocalHMACSigner(b"test-secret"), bad_sink)

    with pytest.raises(LedgerUnavailable, match="database unavailable"):
        await ledger.append(_entry())

    assert ledger.recent() == []


@pytest.mark.asyncio
async def test_optional_sink_failure_logs_and_retains_entry(caplog: pytest.LogCaptureFixture) -> None:
    """Log an optional sink failure while retaining the signed entry."""

    async def bad_sink(payload: str) -> None:
        """Simulate an unavailable optional sink."""
        raise RuntimeError(f"database unavailable for {len(payload)} bytes")

    ledger = ServedLedger(LocalHMACSigner(b"test-secret"), bad_sink)

    with caplog.at_level(logging.ERROR, logger="parrot.squawk.server.ledger"):
        signed = await ledger.append(_entry(), required=False)

    assert ledger.recent() == [signed]
    assert "sink failed (not required): database unavailable" in caplog.text


@pytest.mark.asyncio
async def test_durable_flag_and_recent_entries_are_bounded() -> None:
    """Reflect sink presence and retain only the configured newest entries."""
    payloads: list[str] = []

    async def ok_sink(payload: str) -> None:
        """Record a successful durable commit."""
        payloads.append(payload)

    transient = ServedLedger(LocalHMACSigner(b"test-secret"), max_entries=2)
    durable = ServedLedger(LocalHMACSigner(b"test-secret"), ok_sink, max_entries=2)

    assert transient.durable is False
    assert durable.durable is True
    for number in range(3):
        await durable.append(_entry(f"entry-{number}"))

    assert [entry.entry_id for entry in durable.recent()] == ["entry-1", "entry-2"]
    assert [entry.entry_id for entry in durable.recent(limit=1)] == ["entry-2"]
    assert durable.recent(limit=0) == []
    assert len(payloads) == 3


class _FakeAcquire:
    """Async context manager returned by a fake asyncpg pool."""

    def __init__(self, connection: "_FakePool") -> None:
        self._connection = connection

    async def __aenter__(self) -> "_FakePool":
        """Return the fake connection."""
        return self._connection

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release the fake connection without suppressing errors."""
        return None


class _FakePool:
    """Capture asyncpg acquire and execute calls without a live database."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def acquire(self) -> _FakeAcquire:
        """Return an async context manager for this fake connection."""
        return _FakeAcquire(self)

    async def execute(self, query: str, *args: Any) -> str:
        """Record an INSERT and report asyncpg's success shape."""
        self.calls.append((query, args))
        return "INSERT 0 1"


@pytest.mark.asyncio
async def test_postgres_sink_inserts_all_ddl_columns_with_fake_pool() -> None:
    """Insert a signed JSON payload through an asyncpg-compatible fake pool."""
    pool = _FakePool()
    signed = await ServedLedger(LocalHMACSigner(b"test-secret")).append(_entry())

    await postgres_ledger_sink(pool)(signed.model_dump_json())

    assert len(pool.calls) == 1
    query, args = pool.calls[0]
    assert "INSERT INTO squawk_served_ledger" in query
    assert "ON CONFLICT (entry_id) DO NOTHING" in query
    assert len(args) == 16
    assert args[0] == signed.entry_id
    assert json.loads(args[2]) == signed.caller.model_dump(mode="json")
    assert json.loads(args[10]) == signed.cost.model_dump(mode="json")
    assert args[14] == signed.signature
    assert json.loads(args[15])["entry_id"] == signed.entry_id
