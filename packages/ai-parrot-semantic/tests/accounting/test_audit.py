"""FEAT-713 M7 — accounting audit on the shared ledger."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from parrot.security import LocalHMACSigner
from parrot.semantic.accounting.audit import (
    AccountingAuditEntry,
    append_entry,
    audit_mode_from_env,
    build_entry,
    rebuild_lineage,
    subject_digest,
)
from parrot.semantic.accounting.compiler import compile_assertion, compile_metric
from parrot.semantic.accounting.errors import AccountingAuditError, AccountingError
from parrot.semantic.accounting.loader import load_model
from parrot.semantic.accounting.models import AssertionRequest, MetricRequest
from parrot.semantic.audit import SemanticAuditEntry, SemanticAuditLedger

_PERIOD = {"from": "2025-01-01", "to": "2025-03-31"}


def _entry(troc_pnl_yaml, chart_snapshot, context=None) -> tuple:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    request = MetricRequest.model_validate({"metric": "gross_margin", "grain": "month", "period": _PERIOD})
    compiled = compile_metric(model, request, "duckdb")
    entry = build_entry(
        context=context,
        tenant="troc",
        model=model,
        compiled=compiled,
        target="duckdb",
        tool="accounting_metric",
        outcome="ok",
        assertion_status="none",
        row_count=3,
        duration_ms=5,
    )
    return model, entry


def test_entry_records_queried_tenant_not_caller_tenant(troc_pnl_yaml, chart_snapshot, permission_context) -> None:
    """A caller of tenant A querying tenant B's model is audited against tenant B (caller kept in digest/user)."""
    caller_tenant = str(permission_context.tenant_id)
    queried = "not-" + caller_tenant
    model = load_model(troc_pnl_yaml, chart_snapshot)
    request = MetricRequest.model_validate({"metric": "gross_margin", "grain": "month", "period": _PERIOD})
    entry = build_entry(
        context=permission_context,
        tenant=queried,
        model=model,
        compiled=compile_metric(model, request, "duckdb"),
        target="duckdb",
        tool="accounting_metric",
        outcome="ok",
        assertion_status="none",
        row_count=1,
        duration_ms=1,
    )
    assert entry.tenant_id == queried
    assert entry.user_id == str(permission_context.user_id)
    assert entry.subject_digest != subject_digest(None)


async def test_ledger_accepts_both_entry_types(recording_storage, troc_pnl_yaml, chart_snapshot) -> None:
    storage, payloads = recording_storage
    ledger = SemanticAuditLedger(signer=LocalHMACSigner(), storage=storage)
    semantic = SemanticAuditEntry(
        entry_id="s1",
        created_at=datetime.now(timezone.utc),
        user_id="u1",
        tenant_id="troc",
        channel="test",
        agent_id=None,
        subject_digest="d",
        roles=[],
        static_subject=False,
        model="m",
        model_digest="x",
        policy_digest="y",
        tool="t",
        structured_query=None,
        raw_sql=False,
        compiled_sql=None,
        governed_sql=None,
        dialect="duckdb",
        driver="duckdb",
        rls_applied=[],
        masked_columns=[],
        pbac="not_governed",
        outcome="ok",
        error_code=None,
        row_count=None,
        duration_ms=None,
    )
    _, accounting = _entry(troc_pnl_yaml, chart_snapshot)
    signed_acc = await ledger.append(accounting)
    signed_sem = await ledger.append(semantic)
    assert await ledger.verify(signed_acc)
    assert await ledger.verify(signed_sem)
    assert len(payloads) == 2


async def test_audit_entry_signed_and_verifiable(troc_pnl_yaml, chart_snapshot) -> None:
    ledger = SemanticAuditLedger(signer=LocalHMACSigner())
    _, entry = _entry(troc_pnl_yaml, chart_snapshot)
    signed = await append_entry(ledger, entry, mode="best_effort")
    assert signed.signature
    assert await ledger.verify(signed) is True
    signed.row_count = 999
    assert await ledger.verify(signed) is False


async def test_audit_required_fails_closed(troc_pnl_yaml, chart_snapshot) -> None:
    async def failing(payload: str) -> None:
        raise RuntimeError("down")

    _, entry = _entry(troc_pnl_yaml, chart_snapshot)
    with pytest.raises(AccountingAuditError):
        await append_entry(SemanticAuditLedger(storage=failing), entry, mode="required")
    _, entry2 = _entry(troc_pnl_yaml, chart_snapshot)
    assert (await append_entry(SemanticAuditLedger(storage=failing), entry2, mode="best_effort")) is entry2
    _, entry3 = _entry(troc_pnl_yaml, chart_snapshot)
    with pytest.raises(AccountingAuditError):
        await append_entry(SemanticAuditLedger(), entry3, mode="required")


def test_audit_entry_fits_postgres_sink_keys(troc_pnl_yaml, chart_snapshot, permission_context) -> None:
    _, entry = _entry(troc_pnl_yaml, chart_snapshot, permission_context)
    payload = json.loads(entry.model_dump_json())
    for key in ("entry_id", "created_at", "user_id", "tenant_id", "model", "outcome", "signature"):
        assert key in payload
    assert payload["user_id"] == "u1"
    assert entry.subject_digest == subject_digest(permission_context)
    assert subject_digest(None) != entry.subject_digest


def test_audit_mode_from_env() -> None:
    assert audit_mode_from_env({}) == "required"
    assert audit_mode_from_env({"FINANCE_AUDIT_MODE": "best_effort"}) == "best_effort"
    with pytest.raises(ValueError):
        audit_mode_from_env({"FINANCE_AUDIT_MODE": "nope"})


def test_assertion_audit_replay(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    request = AssertionRequest(assertion_index=0, period=_PERIOD)
    compiled = compile_assertion(model, request, "duckdb")
    entry = build_entry(
        context=None,
        tenant="troc",
        model=model,
        compiled=compiled,
        target="duckdb",
        tool="accounting_assert",
        outcome="ok",
        assertion_status="passed",
        row_count=1,
        duration_ms=1,
    )
    assert rebuild_lineage(entry, model) == compiled.lineage
    # metric entry replays too
    metric_model, metric_entry = _entry(troc_pnl_yaml, chart_snapshot)
    assert rebuild_lineage(metric_entry, metric_model).metric == "gross_margin"
    bad_index = entry.model_copy(
        update={"request_canonical": entry.request_canonical.replace('"assertion_index":0', '"assertion_index":7')}
    )
    with pytest.raises(AccountingError):
        rebuild_lineage(bad_index, model)
    with pytest.raises(AccountingError):
        rebuild_lineage(metric_entry, model.model_copy(update={"model_hash": "0" * 64}))


def test_replay_rejects_tampered_plan_hash(troc_pnl_yaml, chart_snapshot) -> None:
    model, entry = _entry(troc_pnl_yaml, chart_snapshot)
    tampered = entry.model_copy(update={"plan_hash": "f" * 64})
    assert isinstance(tampered, AccountingAuditEntry)
    with pytest.raises(AccountingError):
        rebuild_lineage(tampered, model)
