"""FEAT-713 M8 — AccountingToolkit core."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from parrot.auth.context import _pctx_var
from parrot.auth.dataset_guard import DatasetPolicyGuard
from parrot.auth.exceptions import AuthorizationRequired
from parrot.semantic.accounting.errors import AccountingExecutionError, ModelValidationError, RequestValidationError
from parrot.semantic.accounting.models import ChartSnapshot
from parrot.semantic.accounting.toolkit import AccountingToolkit

METRICS = ("cogs", "ebitda", "gross_margin", "gross_margin_pct", "opex", "revenue")


@pytest.fixture(autouse=True)
def _reset_pctx():
    """Isolate the module-level permission ContextVar between tests."""
    token = _pctx_var.set(None)
    yield
    _pctx_var.reset(token)


class _FakeGuard:
    """Guard allowing a fixed set of bare resource names; records every call."""

    def __init__(self, allowed: set[str]) -> None:
        self.allowed = allowed
        self.filtered: list[list[str]] = []
        self.checked: list[str] = []

    async def filter_datasets(self, context: Any, dataset_names: list[str]) -> set[str]:
        self.filtered.append(list(dataset_names))
        return {name for name in dataset_names if name in self.allowed}

    async def can_read_dataset(self, context: Any, dataset_name: str) -> bool:
        self.checked.append(dataset_name)
        return dataset_name in self.allowed


class _RecordingEvaluator:
    """PolicyEvaluator stand-in recording resource names, types and actions; allows one metric."""

    def __init__(self, allowed: set[str]) -> None:
        self.allowed = allowed
        self.calls: list[dict] = []

    def filter_resources(self, *, ctx, resource_type, resource_names, action, env):  # noqa: ANN001, ANN201
        self.calls.append({"type": resource_type, "names": list(resource_names), "action": action})
        return SimpleNamespace(allowed=[name for name in resource_names if name in self.allowed])

    def check_access(self, *, ctx, resource_type, resource_name, action, env):  # noqa: ANN001, ANN201
        self.calls.append({"type": resource_type, "names": [resource_name], "action": action})
        return SimpleNamespace(allowed=resource_name in self.allowed, matched_policy=None, reason="test")


def _provider(snapshot: ChartSnapshot, calls: list | None = None):  # noqa: ANN202
    async def provider(tenant: str, model: str, spec: Any) -> ChartSnapshot:
        if calls is not None:
            calls.append((tenant, model, spec))
        return snapshot

    return provider


def _toolkit(models_dir: Path, snapshot: ChartSnapshot, **kwargs: Any) -> AccountingToolkit:
    return AccountingToolkit(models_dir=models_dir, snapshot_provider=_provider(snapshot), **kwargs)


def _write_manifest(path: Path, snapshot: ChartSnapshot) -> None:
    accounts = [{"account_id": a.account_id, "nature": a.nature, "tags": ",".join(a.tags)} for a in snapshot.accounts]
    path.write_text(yaml.safe_dump({"taken_at": "2026-10-01", "accounts": accounts}), encoding="utf-8")


async def test_toolkit_list_and_explain(troc_pnl_yaml, chart_snapshot) -> None:
    calls: list = []
    toolkit = AccountingToolkit(
        models_dir=troc_pnl_yaml.parent.parent, snapshot_provider=_provider(chart_snapshot, calls)
    )

    listed = await toolkit.list_metrics("troc")
    assert sorted(row["metric"] for row in listed) == list(METRICS)
    revenue = next(row for row in listed if row["metric"] == "revenue")
    assert revenue == {
        "model": "troc_pnl",
        "metric": "revenue",
        "description": "Net revenue",
        "unit": "currency",
        "dimensions": ["entity", "product_line", "cost_center"],
    }
    assert calls == []  # listing never touches a snapshot

    text = await toolkit.explain_metric("gross_margin", tenant="troc")
    assert len(calls) == 1
    assert "Formula: revenue - cogs" in text
    assert "Inlined formula: (sum(product_sales) - sum(returns)) - (sum(cost_of_sales))" in text
    for set_name in ("product_sales", "returns", "cost_of_sales"):
        assert f"  - {set_name}" in text
    assert "operating_expenses" not in text
    assert "4000, 4010" in text and "5900" not in text.split("cost_of_sales")[1].split("\n")[0]
    assert "gross_margin == revenue - cogs" in text

    # Second explain reuses the loaded model.
    opex = await toolkit.explain_metric("opex", model="troc_pnl", tenant="troc")
    assert len(calls) == 1
    assert "operating_expenses" in opex and "(none)" in opex

    with pytest.raises(RequestValidationError):
        await toolkit.explain_metric("nope", tenant="troc")
    with pytest.raises(RequestValidationError):
        await toolkit.list_metrics()  # no tenant from argument, context or default


async def test_toolkit_resolves_tenant_and_ambiguous_model(troc_pnl_yaml, chart_snapshot, permission_context) -> None:
    second = troc_pnl_yaml.parent / "troc_alt.yaml"
    second.write_text(troc_pnl_yaml.read_text(encoding="utf-8").replace("model: troc_pnl\n", "model: troc_alt\n"))
    toolkit = _toolkit(troc_pnl_yaml.parent.parent, chart_snapshot, default_tenant="troc")
    assert len(await toolkit.list_metrics()) == 2 * len(METRICS)  # default tenant
    with pytest.raises(RequestValidationError, match="troc_alt, troc_pnl"):
        await toolkit.explain_metric("revenue")
    await toolkit._pre_execute("finance_list_metrics", _permission_context=permission_context)
    assert toolkit._resolve_tenant(None) == "troc"
    assert toolkit._resolve_tenant("other") == "other"


async def test_toolkit_pbac_filtering(troc_pnl_yaml, chart_snapshot, permission_context) -> None:
    guard = _FakeGuard({"accounting:troc:troc_pnl:revenue"})
    calls: list = []
    toolkit = AccountingToolkit(
        models_dir=troc_pnl_yaml.parent.parent, snapshot_provider=_provider(chart_snapshot, calls), policy_guard=guard
    )
    await toolkit._pre_execute("finance_list_metrics", _permission_context=permission_context)

    listed = await toolkit.list_metrics()  # tenant from the permission context
    assert [row["metric"] for row in listed] == ["revenue"]

    assert "Net revenue" in await toolkit.explain_metric("revenue")
    with pytest.raises(AuthorizationRequired):
        await toolkit.explain_metric("cogs")
    assert len(calls) == 1  # the denied explain never fetched a snapshot


async def test_toolkit_allows_without_guard_or_context(troc_pnl_yaml, chart_snapshot, permission_context) -> None:
    models_dir = troc_pnl_yaml.parent.parent

    no_guard = _toolkit(models_dir, chart_snapshot)
    await no_guard._pre_execute("finance_list_metrics", _permission_context=permission_context)
    assert len(await no_guard.list_metrics()) == len(METRICS)
    assert "Formula" in await no_guard.explain_metric("cogs")

    guard = _FakeGuard(set())
    no_context = _toolkit(models_dir, chart_snapshot, policy_guard=guard)
    await no_context._pre_execute("finance_list_metrics", _permission_context=None)
    assert len(await no_context.list_metrics("troc")) == len(METRICS)
    assert "Formula" in await no_context.explain_metric("cogs", tenant="troc")
    assert guard.filtered == [] and guard.checked == []


async def test_policy_resource_names(troc_pnl_yaml, chart_snapshot, permission_context) -> None:
    from navigator_auth.abac.policies.resources import ResourceType

    evaluator = _RecordingEvaluator({"dataset:accounting:troc:troc_pnl:opex"})
    toolkit = _toolkit(troc_pnl_yaml.parent.parent, chart_snapshot, policy_guard=DatasetPolicyGuard(evaluator))
    await toolkit._pre_execute("finance_list_metrics", _permission_context=permission_context)

    listed = await toolkit.list_metrics()
    assert [row["metric"] for row in listed] == ["opex"]
    assert "operating_expenses" in await toolkit.explain_metric("opex")
    with pytest.raises(AuthorizationRequired):
        await toolkit.explain_metric("revenue")

    batch, single_ok, single_denied = evaluator.calls
    assert batch["names"] == [f"dataset:accounting:troc:troc_pnl:{m}" for m in METRICS]
    assert single_ok["names"] == ["dataset:accounting:troc:troc_pnl:opex"]
    assert single_denied["names"] == ["dataset:accounting:troc:troc_pnl:revenue"]
    for call in evaluator.calls:
        assert call["type"] == ResourceType.DATASET
        assert call["action"] == "dataset:read"


async def test_snapshot_acquisition(troc_pnl_yaml, chart_snapshot, tmp_path) -> None:
    models_dir = troc_pnl_yaml.parent.parent
    with pytest.raises(ValueError):
        AccountingToolkit(models_dir=models_dir)
    with pytest.raises(ValueError):
        AccountingToolkit(
            models_dir=models_dir,
            snapshot_provider=_provider(chart_snapshot),
            snapshot_manifests={"troc": {"troc_pnl": tmp_path / "chart.yaml"}},
        )

    # Provider receives (tenant, model, spec).
    calls: list = []
    toolkit = AccountingToolkit(models_dir=models_dir, snapshot_provider=_provider(chart_snapshot, calls))
    await toolkit._ensure_loaded("troc", "troc_pnl")
    ((tenant, model, spec),) = calls
    assert (tenant, model, spec.model, spec.tenant) == ("troc", "troc_pnl", "troc_pnl", "troc")

    # Manifest adapter re-reads the file on every call.
    manifest = tmp_path / "chart.yaml"
    _write_manifest(manifest, chart_snapshot)
    manifest_kit = AccountingToolkit(models_dir=models_dir, snapshot_manifests={"troc": {"troc_pnl": manifest}})
    first = await manifest_kit._snapshot_provider("troc", "troc_pnl", spec)
    assert [(a.account_id, a.nature) for a in first.accounts] == [
        (a.account_id, a.nature) for a in chart_snapshot.accounts
    ]
    _write_manifest(manifest, chart_snapshot.model_copy(update={"accounts": chart_snapshot.accounts[:-1]}))
    second = await manifest_kit._snapshot_provider("troc", "troc_pnl", spec)
    assert len(second.accounts) == len(chart_snapshot.accounts) - 1
    _write_manifest(manifest, chart_snapshot)
    assert (await manifest_kit._ensure_loaded("troc", "troc_pnl")).spec.model == "troc_pnl"

    # Missing manifest key fails closed and loads nothing.
    missing = AccountingToolkit(models_dir=models_dir, snapshot_manifests={"troc": {"other": manifest}})
    with pytest.raises(AccountingExecutionError):
        await missing.explain_metric("revenue", tenant="troc")
    assert not missing._catalog.is_loaded("troc", "troc_pnl")

    # Provider failure fails closed and loads nothing.
    async def failing(tenant: str, model: str, spec: Any) -> ChartSnapshot:
        raise OSError("account master down")

    broken = AccountingToolkit(models_dir=models_dir, snapshot_provider=failing)
    with pytest.raises(AccountingExecutionError):
        await broken.explain_metric("revenue", tenant="troc")
    assert not broken._catalog.is_loaded("troc", "troc_pnl")


async def test_table_source_fetches_journal_columns(troc_pnl_yaml, chart_snapshot, tmp_path) -> None:
    models_dir = tmp_path / "models"
    (models_dir / "troc").mkdir(parents=True)
    table_yaml = troc_pnl_yaml.read_text(encoding="utf-8").replace(
        "source: { dataframe: journal }", 'source: { table: "fin.journal", connection: "erp", driver: "pg" }'
    )
    (models_dir / "troc" / "troc_pnl.yaml").write_text(table_yaml, encoding="utf-8")
    toolkit = _toolkit(models_dir, chart_snapshot)
    seen: list[dict] = []
    columns = {
        "account_id": "varchar",
        "posting_date": "date",
        "amount": "numeric(18,2)",
        "entity": "varchar",
        "product_line": "varchar",
        "cost_center": "varchar",
    }

    async def fetch_columns(**kwargs: Any) -> dict[str, str]:
        seen.append(kwargs)
        return dict(columns)

    toolkit._database.fetch_columns = fetch_columns  # type: ignore[method-assign]
    await toolkit._ensure_loaded("troc", "troc_pnl")
    assert seen == [{"connection": "erp", "driver": "pg", "table": "fin.journal"}]

    bad = _toolkit(models_dir, chart_snapshot)

    async def float_columns(**kwargs: Any) -> dict[str, str]:
        return {**columns, "amount": "double precision"}

    bad._database.fetch_columns = float_columns  # type: ignore[method-assign]
    with pytest.raises(ModelValidationError):
        await bad._ensure_loaded("troc", "troc_pnl")
    assert not bad._catalog.is_loaded("troc", "troc_pnl")


# --- TASK-5537: query_metric / validate_model ---------------------------------------------------------------------


def _frames(frame: Any, requested: list | None = None):  # noqa: ANN202
    async def frame_provider(name: str) -> Any:
        if requested is not None:
            requested.append(name)
        return frame

    return frame_provider


async def _close(toolkit: AccountingToolkit) -> None:
    if toolkit._engine is not None:
        await toolkit._engine.close()


async def test_toolkit_tools_and_prefix(troc_pnl_yaml, chart_snapshot) -> None:
    toolkit = _toolkit(troc_pnl_yaml.parent.parent, chart_snapshot)
    names = sorted(tool.name for tool in toolkit.get_tools())
    assert names == [
        "finance_explain_metric",
        "finance_list_metrics",
        "finance_query_metric",
        "finance_validate_model",
    ]


async def test_query_metric_duckdb(troc_pnl_yaml, chart_snapshot, journal_frame, monkeypatch) -> None:
    import threading

    from parrot.semantic.accounting import toolkit as toolkit_module

    compile_threads: list[int] = []
    real_compile = toolkit_module.compile_metric

    def spy(*args: Any, **kwargs: Any) -> Any:
        compile_threads.append(threading.get_ident())
        return real_compile(*args, **kwargs)

    monkeypatch.setattr(toolkit_module, "compile_metric", spy)
    requested: list[str] = []
    toolkit = _toolkit(
        troc_pnl_yaml.parent.parent,
        chart_snapshot,
        frame_provider=_frames(journal_frame, requested),
        audit_mode="best_effort",
        duckdb_threads=2,
    )
    try:
        result = await toolkit.query_metric(
            "gross_margin", "2025-01-01", "2025-03-31", grain="month", dimensions=["entity"], tenant="troc"
        )
        again = await toolkit.query_metric(
            "gross_margin", "2025-01-01", "2025-03-31", grain="month", dimensions=["entity"], tenant="troc"
        )
    finally:
        await _close(toolkit)

    assert requested == ["journal", "journal"]
    assert len(compile_threads) == 1  # the second query hit the compile cache
    assert compile_threads[0] != threading.get_ident()  # compiled off the event loop
    assert result["columns"] == ["bucket", "entity", "m_gross_margin"]
    assert result["row_count"] == len(result["rows"]) == 9
    for row in result["rows"]:
        assert isinstance(row["m_gross_margin"], str)
        Decimal(row["m_gross_margin"])  # exact decimal text
        assert row["bucket"] in ("2025-01-01", "2025-02-01", "2025-03-01")
    assert len(result["sql_hash"]) == 64 and len(result["plan_hash"]) == 64
    assert result["lineage"]["metric"] == "gross_margin"
    assert result["chart_drift"] is False and result["assertion_failed"] is False
    assert result["audit_id"] and result["audit_id"] != again["audit_id"]
    assert again["rows"] == result["rows"] and again["sql_hash"] == result["sql_hash"]

    with pytest.raises(RequestValidationError):
        await toolkit.query_metric("revenue", "2025-03-31", "2025-01-01", tenant="troc")
    with pytest.raises(RequestValidationError):
        await toolkit.query_metric("revenue", "2025-01-01", "2025-03-31", grain="week", cumulative="ytd", tenant="troc")


async def test_query_metric_audits(troc_pnl_yaml, chart_snapshot, journal_frame, recording_storage) -> None:
    from parrot.semantic.accounting.audit import AccountingAuditEntry
    from parrot.semantic.accounting.errors import AccountingAuditError

    storage, payloads = recording_storage
    models_dir = troc_pnl_yaml.parent.parent
    toolkit = _toolkit(
        models_dir, chart_snapshot, frame_provider=_frames(journal_frame), audit_storage=storage, audit_mode="required"
    )
    try:
        result = await toolkit.query_metric("revenue", "2025-01-01", "2025-01-31", tenant="troc")
    finally:
        await _close(toolkit)
    assert len(payloads) == 1
    entry = AccountingAuditEntry.model_validate_json(payloads[0])
    assert entry.entry_id == result["audit_id"]
    assert entry.outcome == "ok" and entry.target == "duckdb" and entry.tool == "finance_query_metric"
    assert entry.sql_hash == result["sql_hash"] and entry.row_count == result["row_count"] == 1
    assert entry.signature and await toolkit._ledger.verify(entry)

    async def failing_sink(payload: str) -> None:
        raise OSError("audit sink down")

    strict = _toolkit(
        models_dir, chart_snapshot, frame_provider=_frames(journal_frame), audit_storage=failing_sink, audit_mode="required"
    )
    outcome: dict | None = None
    try:
        with pytest.raises(AccountingAuditError):
            outcome = await strict.query_metric("revenue", "2025-01-01", "2025-01-31", tenant="troc")
    finally:
        await _close(strict)
    assert outcome is None

    # A runtime failure is audited as execution_error (best effort) and re-raised with the audit id.
    payloads.clear()

    async def broken_frames(name: str) -> Any:
        raise OSError("lake unreachable")

    broken = _toolkit(
        models_dir, chart_snapshot, frame_provider=broken_frames, audit_storage=storage, audit_mode="required"
    )
    try:
        with pytest.raises(AccountingExecutionError) as excinfo:
            await broken.query_metric("revenue", "2025-01-01", "2025-01-31", tenant="troc")
    finally:
        await _close(broken)
    assert len(payloads) == 1
    failed = AccountingAuditEntry.model_validate_json(payloads[0])
    assert failed.outcome == "execution_error" and excinfo.value.audit_id == failed.entry_id
    assert "lake unreachable" not in str(excinfo.value)


async def test_validate_model_authorization(troc_pnl_yaml, chart_snapshot, journal_frame, permission_context) -> None:
    second = troc_pnl_yaml.parent / "troc_alt.yaml"
    second.write_text(troc_pnl_yaml.read_text(encoding="utf-8").replace("model: troc_pnl\n", "model: troc_alt\n"))
    models_dir = troc_pnl_yaml.parent.parent
    metric_names = {f"accounting:troc:troc_pnl:{m}" for m in METRICS}
    validate_name = "accounting:troc:troc_pnl:__validate__"

    for allowed in (metric_names, (metric_names - {"accounting:troc:troc_pnl:opex"}) | {validate_name}):
        calls: list = []
        guard = _FakeGuard(allowed)
        toolkit = AccountingToolkit(
            models_dir=models_dir,
            snapshot_provider=_provider(chart_snapshot, calls),
            frame_provider=_frames(journal_frame),
            policy_guard=guard,
            audit_mode="best_effort",
        )
        await toolkit._pre_execute("finance_validate_model", _permission_context=permission_context)
        for live in (False, True):
            with pytest.raises(AuthorizationRequired):
                await toolkit.validate_model("troc_pnl", live=live)
        assert calls == []  # denied before any snapshot refresh
        assert not toolkit._catalog.is_loaded("troc", "troc_pnl")
        assert toolkit._catalog.flags("troc", "troc_pnl") is None
        assert len(toolkit._ledger.entries) == 0  # nothing compiled, executed or audited

    calls = []
    toolkit = AccountingToolkit(
        models_dir=models_dir,
        snapshot_provider=_provider(chart_snapshot, calls),
        frame_provider=_frames(journal_frame),
        policy_guard=_FakeGuard(metric_names | {validate_name}),
        audit_mode="best_effort",
    )
    await toolkit._pre_execute("finance_validate_model", _permission_context=permission_context)
    try:
        structural = await toolkit.validate_model("troc_pnl")
        assert structural == {"tenant": "troc", "model": "troc_pnl", "problems": []}
        live = await toolkit.validate_model("troc_pnl", live=True)
    finally:
        await _close(toolkit)
    assert (live["tenant"], live["model"], live["error"]) == ("troc", "troc_pnl", None)
    assert [item["status"] for item in live["assertion_results"]] == ["passed"]
    assert {(tenant, model) for tenant, model, _ in calls} == {("troc", "troc_pnl")}
    assert toolkit._catalog.flags("troc", "troc_alt") is None
    assert not toolkit._catalog.is_loaded("troc", "troc_alt")
    with pytest.raises(AuthorizationRequired):
        await toolkit.validate_model("troc_alt")  # its own privilege is not granted


async def test_snapshot_refresh_failure(troc_pnl_yaml, chart_snapshot, journal_frame) -> None:
    from parrot.semantic.accounting.models import ChartAccount

    state = {"mode": "ok"}
    drifted = chart_snapshot.model_copy(
        update={"accounts": (*chart_snapshot.accounts, ChartAccount(account_id="7000", nature="debit"))}
    )

    async def provider(tenant: str, model: str, spec: Any) -> ChartSnapshot:
        if state["mode"] == "fail":
            raise OSError("account master down")
        return drifted if state["mode"] == "drift" else chart_snapshot

    toolkit = AccountingToolkit(
        models_dir=troc_pnl_yaml.parent.parent,
        snapshot_provider=provider,
        frame_provider=_frames(journal_frame),
        audit_mode="best_effort",
    )
    try:
        first = await toolkit.validate_model("troc_pnl", tenant="troc", live=True)
        assert first["error"] is None and first["drift_accounts"] == []
        flags = toolkit._catalog.flags("troc", "troc_pnl")
        model_hash = toolkit._catalog.get("troc", "troc_pnl").model_hash

        state["mode"] = "fail"
        failed = await toolkit.validate_model("troc_pnl", tenant="troc", live=True)
        assert failed["error"] and "OSError" in failed["error"]
        assert failed["assertion_results"] == []
        assert toolkit._catalog.flags("troc", "troc_pnl") is flags  # previous flags preserved
        assert toolkit._catalog.get("troc", "troc_pnl").model_hash == model_hash

        state["mode"] = "drift"
        drift = await toolkit.validate_model("troc_pnl", tenant="troc", live=True)
        assert drift["error"] is None and drift["drift_accounts"] == ["7000"]
        assert toolkit._catalog.get("troc", "troc_pnl").model_hash == model_hash  # no silent reload
        result = await toolkit.query_metric("revenue", "2025-01-01", "2025-01-31", tenant="troc")
        assert result["chart_drift"] is True
    finally:
        await _close(toolkit)
