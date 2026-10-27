"""Regression contract: Signed audit ledger and optional Postgres sink (M8)."""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from parrot.security import LocalHMACSigner
from parrot.semantic.audit import SemanticAuditEntry, SemanticAuditLedger, postgres_audit_storage
from parrot.semantic.errors import SemanticExecutionError

ENTRY_ID = "6f1c1a52-5d0e-4c43-9a3f-1a2b3c4d5e6f"


def _entry(outcome: str = "ok", **kw: Any) -> SemanticAuditEntry:
    base: dict[str, Any] = dict(
        entry_id=ENTRY_ID,
        created_at=datetime(2026, 10, 26, tzinfo=timezone.utc),
        user_id="u1",
        tenant_id="t1",
        channel="api",
        agent_id=None,
        subject_digest="sd",
        roles=["analyst"],
        static_subject=False,
        model="sales",
        model_digest="md",
        policy_digest="pd",
        tool="semantic_query",
        structured_query={"measures": ["revenue"]},
        raw_sql=False,
        compiled_sql="SELECT 1",
        governed_sql="SELECT 1",
        dialect="postgres",
        driver="pg",
        rls_applied=[],
        masked_columns=[],
        pbac="allow",
        outcome=outcome,
        error_code=None,
        row_count=1,
        duration_ms=5,
    )
    base.update(kw)
    return SemanticAuditEntry(**base)


class _YieldingSigner(LocalHMACSigner):
    async def sign(self, data: bytes) -> str:
        await asyncio.sleep(0)
        return await super().sign(data)

    async def verify(self, data: bytes, signature: str) -> bool:
        await asyncio.sleep(0)
        return await super().verify(data, signature)


@pytest.mark.asyncio
async def test_signed_roundtrip_and_tampering(tmp_path: Path) -> None:
    """Verify signed roundtrip and tampering."""
    ledger = SemanticAuditLedger(signer=_YieldingSigner(b"k"), max_entries=2)
    entry = await ledger.append(_entry())
    assert entry.signature and entry.engine == "native"
    assert b"signature" not in entry.canonical_bytes()
    assert await ledger.verify(entry) is True
    tampered = entry.model_copy(update={"row_count": 999})
    assert await ledger.verify(tampered) is False
    assert await SemanticAuditLedger(signer=LocalHMACSigner(b"other")).verify(entry) is False
    for outcome, pbac in (("denied", "deny"), ("validation_error", "not_governed"), ("execution_error", "unavailable")):
        await ledger.append(_entry(outcome, pbac=pbac, error_code="x"))
    assert len(ledger.entries) == 2
    with pytest.raises(ValueError):
        _entry(engine="sidemantic")


@pytest.mark.asyncio
async def test_durable_required_and_optional_failures(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Verify durable required and optional failures."""
    assert SemanticAuditLedger().durable is False
    with pytest.raises(SemanticExecutionError) as missing:
        await SemanticAuditLedger().append(_entry(), required=True)
    assert missing.value.details == {"audit_id": ENTRY_ID}

    stored: list[str] = []

    async def ok_sink(payload: str) -> None:
        stored.append(payload)

    ledger = SemanticAuditLedger(storage=ok_sink)
    assert ledger.durable
    await ledger.append(_entry(), required=True)
    assert len(stored) == 1 and ENTRY_ID in stored[0]

    async def bad_sink(payload: str) -> None:
        raise RuntimeError("boom")

    failing = SemanticAuditLedger(storage=bad_sink)
    with pytest.raises(SemanticExecutionError) as err:
        await failing.append(_entry(), required=True)
    assert err.value.code == "audit_unavailable"
    assert "SELECT" not in str(err.value)
    entry = await failing.append(_entry(), required=False)
    assert entry.signature
    assert "Semantic audit sink failed" in caplog.text


class _FakeConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    async def execute(self, sql: str, *args: Any) -> None:
        self.calls.append((sql, args))

    async def close(self) -> None:
        self.closed = True


class _FakePool:
    def __init__(self) -> None:
        self.conn = _FakeConn()
        self.closed = False

    def acquire(self) -> Any:
        pool = self

        class _Ctx:
            async def __aenter__(self) -> _FakeConn:
                return pool.conn

            async def __aexit__(self, *exc: Any) -> None:
                return None

        return _Ctx()

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_postgres_storage_bound_values_and_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify postgres storage bound values and cleanup."""
    for bad in ("x; DROP TABLE y", 'a"b', "a.b.c", ""):
        with pytest.raises(ValueError):
            postgres_audit_storage("dsn", table=bad)

    pool = _FakePool()
    ledger = SemanticAuditLedger(storage=postgres_audit_storage(pool, table="audit.events"))
    entry = await ledger.append(_entry(user_id="o'brien"), required=True)
    sql, args = pool.conn.calls[0]
    assert 'INSERT INTO "audit"."events"' in sql and "o'brien" not in sql
    assert args[0] == ENTRY_ID and args[2] == "o'brien" and args[7] == entry.signature
    assert not pool.closed

    conns: list[_FakeConn] = []

    class _FailConn(_FakeConn):
        async def execute(self, sql: str, *args: Any) -> None:
            raise RuntimeError("db down")

    async def connect(dsn: str) -> _FakeConn:
        conn = _FailConn() if conns else _FakeConn()
        conns.append(conn)
        return conn

    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(connect=connect))
    storage = postgres_audit_storage("postgres://x")
    await storage(entry.model_dump_json())
    with pytest.raises(RuntimeError):
        await storage(entry.model_dump_json())
    assert all(c.closed for c in conns) and len(conns) == 2
