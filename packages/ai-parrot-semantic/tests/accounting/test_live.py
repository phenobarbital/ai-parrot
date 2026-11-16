"""FEAT-713 M9 — live validation."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from parrot.auth.context import _pctx_var
from parrot.semantic.accounting.audit import AccountingAuditEntry, rebuild_lineage
from parrot.semantic.accounting.errors import AccountingExecutionError
from parrot.semantic.accounting.live import LiveValidationReport, last_closed_month, run_live_validation
from parrot.semantic.accounting.models import ChartSnapshot
from parrot.semantic.accounting.toolkit import AccountingToolkit

_FIXTURE_ASSERTION = '  - { expr: "gross_margin == revenue - cogs" }\n'


@pytest.fixture(autouse=True)
def _reset_pctx():
    """Isolate the module-level permission ContextVar between tests."""
    token = _pctx_var.set(None)
    yield
    _pctx_var.reset(token)


def _toolkit(models_dir: Path, snapshot: ChartSnapshot, frame: Any, **kwargs: Any) -> AccountingToolkit:
    async def provider(tenant: str, model: str, spec: Any) -> ChartSnapshot:
        return snapshot

    async def frames(name: str) -> Any:
        return frame

    kwargs.setdefault("audit_mode", "best_effort")
    return AccountingToolkit(models_dir=models_dir, snapshot_provider=provider, frame_provider=frames, **kwargs)


def _write_model(troc_pnl_yaml: Path, name: str, assertions: str) -> None:
    text = troc_pnl_yaml.read_text(encoding="utf-8")
    assert _FIXTURE_ASSERTION in text
    text = text.replace("model: troc_pnl\n", f"model: {name}\n").replace(_FIXTURE_ASSERTION, assertions)
    (troc_pnl_yaml.parent / f"{name}.yaml").write_text(text, encoding="utf-8")


async def _close(toolkit: AccountingToolkit) -> None:
    if toolkit._engine is not None:
        await toolkit._engine.close()


def test_last_closed_month() -> None:
    period = last_closed_month(date(2026, 3, 15))
    assert (period.from_, period.to, period.cumulative) == (date(2026, 2, 1), date(2026, 2, 28), None)
    january = last_closed_month(date(2026, 1, 1))
    assert (january.from_, january.to) == (date(2025, 12, 1), date(2025, 12, 31))
    leap = last_closed_month(date(2024, 3, 31))
    assert (leap.from_, leap.to) == (date(2024, 2, 1), date(2024, 2, 29))


async def test_live_validation_flags(troc_pnl_yaml, chart_snapshot, journal_frame) -> None:
    _write_model(
        troc_pnl_yaml,
        "troc_flag",
        '  - { expr: "gross_margin == revenue - cogs" }\n'
        '  - { expr: "revenue == cogs", on_failure: flag }\n'
        '  - { expr: "gross_margin_pct == gross_margin_pct" }\n',
    )
    _write_model(troc_pnl_yaml, "troc_block", '  - { expr: "revenue == cogs", on_failure: block }\n')
    toolkit = _toolkit(troc_pnl_yaml.parent.parent, chart_snapshot, journal_frame)
    try:
        before = await toolkit.query_metric("revenue", "2025-02-01", "2025-02-28", model="troc_flag", tenant="troc")
        assert before["assertion_failed"] is False

        # 2025-09-10 => August 2025, the empty month: revenue is 0 so the ratio side is NULL (skipped).
        august = await run_live_validation(toolkit, today=date(2025, 9, 10))
        assert isinstance(august, LiveValidationReport)
        by_model = {status.model: status for status in august.models}
        assert [s.status for s in by_model["troc_flag"].assertion_results] == ["passed", "passed", "skipped"]

        report = await run_live_validation(toolkit, today=date(2025, 3, 15))
        assert [(s.tenant, s.model) for s in report.models] == [
            ("troc", "troc_block"),
            ("troc", "troc_flag"),
            ("troc", "troc_pnl"),
        ]
        by_model = {status.model: status for status in report.models}
        flag = by_model["troc_flag"]
        assert [s.status for s in flag.assertion_results] == ["passed", "failed", "passed"]
        failed = flag.assertion_results[1]
        assert failed.lhs != failed.rhs and failed.period.from_ == date(2025, 2, 1)
        assert flag.blocked is False and len(flag.audit_ids) == 3
        assert by_model["troc_pnl"].blocked is False
        assert by_model["troc_block"].blocked is True

        after = await toolkit.query_metric("revenue", "2025-02-01", "2025-02-28", model="troc_flag", tenant="troc")
        assert after["assertion_failed"] is True and after["chart_drift"] is False
        clean = await toolkit.query_metric("revenue", "2025-02-01", "2025-02-28", model="troc_pnl", tenant="troc")
        assert clean["assertion_failed"] is False
        with pytest.raises(AccountingExecutionError, match="blocked"):
            await toolkit.query_metric("revenue", "2025-02-01", "2025-02-28", model="troc_block", tenant="troc")
    finally:
        await _close(toolkit)


async def test_live_errors_do_not_leak_exception_text(troc_pnl_yaml, chart_snapshot, journal_frame) -> None:
    """A failing assertion run reports only the exception type, never driver/SQL text from the message."""
    secret = "password=hunter2 SELECT secret FROM vault"
    toolkit = _toolkit(troc_pnl_yaml.parent.parent, chart_snapshot, journal_frame)
    try:

        async def boom(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise AccountingExecutionError(secret)

        toolkit._run_assertions = boom  # type: ignore[method-assign]
        report = await run_live_validation(toolkit, today=date(2025, 3, 15))
    finally:
        await _close(toolkit)
    errors = [status.error for status in report.models]
    assert errors and all(error for error in errors)
    assert all("hunter2" not in error and "SELECT" not in error for error in errors)
    assert any("AccountingExecutionError" in error for error in errors)


async def test_assertion_entries_replayable(troc_pnl_yaml, chart_snapshot, journal_frame, recording_storage) -> None:
    storage, payloads = recording_storage
    _write_model(
        troc_pnl_yaml,
        "troc_two",
        '  - { expr: "gross_margin == revenue - cogs" }\n'
        '  - { expr: "ebitda == gross_margin - sum(other_cost) - opex" }\n',
    )
    toolkit = _toolkit(
        troc_pnl_yaml.parent.parent, chart_snapshot, journal_frame, audit_storage=storage, audit_mode="required"
    )
    try:
        report = await run_live_validation(toolkit, today=date(2026, 4, 2))
    finally:
        await _close(toolkit)
    audit_ids = [audit_id for status in report.models for audit_id in status.audit_ids]
    assert all(status.error is None for status in report.models)
    assert len(payloads) == len(audit_ids) == 3

    entries = [AccountingAuditEntry.model_validate_json(payload) for payload in payloads]
    assert [entry.entry_id for entry in entries] == audit_ids
    for entry in entries:
        request = json.loads(entry.request_canonical)
        assert request["kind"] == "assertion"
        assert request["period"] == {"from": "2026-03-01", "to": "2026-03-31", "cumulative": None}
        assert entry.assertion_status == "passed" and entry.tool == "finance_validate_model"
        assert await toolkit._ledger.verify(entry)
        loaded = toolkit._catalog.get("troc", entry.model)
        lineage = rebuild_lineage(entry, loaded)
        assert lineage.metric is None and lineage.assertion_index == request["assertion_index"]
        assert lineage.formula == loaded.spec.assertions[request["assertion_index"]].expr
