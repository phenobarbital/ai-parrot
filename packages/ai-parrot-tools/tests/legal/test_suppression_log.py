"""Unit tests for the append-only SuppressionLog (FEAT-449 TASK-2495)."""

from datetime import UTC, datetime

from parrot_tools.legal.librarian.models import SuppressionRecord
from parrot_tools.legal.librarian.suppression import SuppressionLog


def _record(execution_id="exec-1") -> SuppressionRecord:
    return SuppressionRecord(
        execution_id=execution_id,
        suppressed_text="Some sentence.",
        claimed_anchors=["a:0:0-3"],
        reason="quote_mismatch",
        user_id=None,
        created_at=datetime.now(UTC),
    )


async def test_suppression_log_append_only(fake_store, legal_tenant_ctx):
    log = SuppressionLog(fake_store, legal_tenant_ctx)
    public_methods = [m for m in dir(log) if not m.startswith("_") and callable(getattr(log, m))]
    assert public_methods == ["append"]


async def test_append_inserts_into_span_suppressions(fake_store, legal_tenant_ctx):
    log = SuppressionLog(fake_store, legal_tenant_ctx)
    await log.append(_record())

    assert len(fake_store.inserted_documents) == 1
    collection, doc = fake_store.inserted_documents[0]
    assert collection == "span_suppressions"
    assert doc["execution_id"] == "exec-1"
    assert doc["reason"] == "quote_mismatch"
    assert doc["suppression_id"] == "exec-1:1"
    assert doc["_key"] == "exec-1:1"


async def test_suppression_id_increments_per_instance(fake_store, legal_tenant_ctx):
    log = SuppressionLog(fake_store, legal_tenant_ctx)
    await log.append(_record())
    await log.append(_record())

    ids = [doc["suppression_id"] for _, doc in fake_store.inserted_documents]
    assert ids == ["exec-1:1", "exec-1:2"]
