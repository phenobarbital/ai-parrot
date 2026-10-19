"""Tests for the signed semantic audit ledger (TASK-4474)."""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import sqlglot

from parrot.security import LocalHMACSigner
from parrot.semantic.audit import SemanticAuditEntry, SemanticAuditLedger, postgres_audit_storage
from parrot.semantic.errors import SemanticExecutionError


def _entry() -> SemanticAuditEntry:
    return SemanticAuditEntry(
        entry_id=str(uuid.uuid4()), created_at=datetime.now(timezone.utc), user_id="u1", tenant_id="t1",
        channel="api", agent_id=None, subject_digest="d", roles=["analyst"], static_subject=False,
        model="sales", model_digest="m", policy_digest="p", engine="sidemantic", tool="semantic_query",
        structured_query={"metrics": ["revenue"]}, raw_sql=False, compiled_sql="SELECT 1", governed_sql="SELECT 1",
        dialect="postgres", driver="pg", rls_applied=[], masked_columns=[], pbac="allow", outcome="ok",
        error_code=None, row_count=1, duration_ms=3,
    )


async def test_audit_entry_signature(caplog):
    sink = AsyncMock()
    ledger = SemanticAuditLedger(signer=LocalHMACSigner(b"k" * 32), storage=sink)
    assert ledger.durable
    entry = await ledger.append(_entry())
    assert entry.signature
    assert await ledger.verify(entry)
    tampered = entry.model_copy(update={"row_count": 999})
    assert not await ledger.verify(tampered)
    sent = sink.await_args.args[0]
    assert SemanticAuditEntry.model_validate_json(sent).entry_id == entry.entry_id

    failing = SemanticAuditLedger(storage=AsyncMock(side_effect=OSError("down")))
    with caplog.at_level(logging.ERROR):
        await failing.append(_entry(), required=False)
    assert "storage failed" in caplog.text
    with pytest.raises(SemanticExecutionError) as exc:
        await failing.append(_entry(), required=True)
    assert exc.value.code == "audit_unavailable"
    assert not await SemanticAuditLedger().verify(entry)


async def test_postgres_audit_storage_insert():
    ddl = (Path(__import__("parrot.semantic").semantic.__file__).parent / "sql/semantic_audit_events.sql").read_text()
    assert sqlglot.parse(ddl, read="postgres")
    pool = AsyncMock()
    storage = postgres_audit_storage(pool)
    entry = _entry()
    await storage(entry.model_dump_json())
    sql, *params = pool.execute.await_args.args
    assert sql.startswith("INSERT INTO semantic_audit_events")
    assert params[0] == uuid.UUID(entry.entry_id)
    assert params[2:6] == ["u1", "t1", "sales", "ok"]
    with pytest.raises(ValueError):
        postgres_audit_storage(pool, table="x; DROP TABLE y")
