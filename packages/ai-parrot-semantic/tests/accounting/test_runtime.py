"""FEAT-713 M6 — runtimes."""

from __future__ import annotations

import copy
import threading
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pytest
import yaml

from parrot.semantic.accounting.compiler import compile_metric
from parrot.semantic.accounting.errors import AccountingExecutionError
from parrot.semantic.accounting.loader import load_model
from parrot.semantic.accounting.models import AccountingModel, MetricRequest
from parrot.semantic.accounting.runtime import DatabaseRuntime, DuckDBRuntime
from parrot.semantic.accounting.runtime import duckdb as duckdb_runtime
from parrot.semantic.errors import SemanticExecutionError
from parrot.semantic.models import GovernedQuery

_CONNECTION = "acct"
_TABLE_SOURCE = {"table": "journal", "connection": _CONNECTION, "driver": "duckdb"}


def _request(**kwargs: Any) -> MetricRequest:
    return MetricRequest.model_validate(kwargs)


def _gross_margin_request() -> MetricRequest:
    return _request(
        metric="gross_margin_pct",
        grain="month",
        dimensions=("entity",),
        period={"from": "2025-01-01", "to": "2025-12-31"},
    )


def _table_model(troc_pnl_yaml, chart_snapshot) -> AccountingModel:
    data = copy.deepcopy(yaml.safe_load(troc_pnl_yaml.read_text(encoding="utf-8")))
    data["chart_of_accounts"]["source"] = dict(_TABLE_SOURCE)
    return load_model(data, chart_snapshot)


class _FakeExecutor:
    """Captures GovernedQuery objects; returns canned rows."""

    def __init__(self, rows: list[dict] | None = None, *, truncated: bool = False, error: Exception | None = None):
        self.rows = rows or []
        self.truncated = truncated
        self.error = error
        self.calls: list[tuple[GovernedQuery, str]] = []
        self.toolkit = SimpleNamespace(get_source=lambda driver: SimpleNamespace(sqlglot_dialect="duckdb"))
        self.resolver = SimpleNamespace(resolve=lambda connection, driver: {"database": ":memory:"})

    async def run_with_columns(self, governed: GovernedQuery, *, connection: str):
        self.calls.append((governed, connection))
        if self.error is not None:
            raise self.error
        columns = list(self.rows[0]) if self.rows else []
        return list(self.rows), len(self.rows), self.truncated, 1, columns


class _FakeEngine:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, sql: str, *, frames=None, parameters=None) -> pa.Table:  # pragma: no cover - unused
        self.calls.append(sql)
        raise AssertionError("the engine must not run when frame validation fails")


async def test_duckdb_runtime_uses_frame_provider(troc_pnl_yaml, chart_snapshot, journal_frame, monkeypatch) -> None:
    pytest.importorskip("duckdb")
    from parrot.interfaces.duckdb_engine import DuckDBEngine

    model = load_model(troc_pnl_yaml, chart_snapshot)
    compiled = compile_metric(model, _gross_margin_request(), "duckdb")
    requested: list[str] = []

    async def provider(name: str) -> pa.Table:
        requested.append(name)
        return journal_frame

    loop_thread = threading.get_ident()
    conversion_threads: list[int] = []
    real_to_arrow = duckdb_runtime.to_arrow

    def spy(frame, **kwargs):
        conversion_threads.append(threading.get_ident())
        return real_to_arrow(frame, **kwargs)

    monkeypatch.setattr(duckdb_runtime, "to_arrow", spy)
    engine = DuckDBEngine(threads=2)
    try:
        result = await DuckDBRuntime(engine, provider).execute(compiled, model)
    finally:
        await engine.close()

    assert requested == ["journal"]
    assert conversion_threads and all(ident != loop_thread for ident in conversion_threads)
    assert result.target == "duckdb"
    assert result.columns == ("bucket", "entity", "m_gross_margin_pct")
    assert result.rows
    for row in result.rows:
        assert tuple(row) == result.columns
        assert isinstance(row["bucket"], date)
        assert row["m_gross_margin_pct"] is None or isinstance(row["m_gross_margin_pct"], Decimal)
    assert any(isinstance(row["m_gross_margin_pct"], Decimal) for row in result.rows)
    # August 2025 has no postings, so no bucket is produced for it.
    assert date(2025, 8, 1) not in {row["bucket"] for row in result.rows}


async def test_duckdb_runtime_rejects_table_source(troc_pnl_yaml, chart_snapshot) -> None:
    model = _table_model(troc_pnl_yaml, chart_snapshot)
    compiled = compile_metric(model, _gross_margin_request(), "duckdb")

    async def provider(name: str) -> pa.Table:  # pragma: no cover - never called
        raise AssertionError(name)

    with pytest.raises(AccountingExecutionError):
        await DuckDBRuntime(_FakeEngine(), provider).execute(compiled, model)


async def test_database_runtime_builds_governed_query(troc_pnl_yaml, chart_snapshot) -> None:
    model = _table_model(troc_pnl_yaml, chart_snapshot)
    compiled = compile_metric(model, _gross_margin_request(), "duckdb")
    rows = [
        {
            "bucket": date(2025, 1, 1),
            "entity": "TROC",
            "set_product_sales": Decimal("200.000000"),
            "set_returns": Decimal("0.000000"),
            "set_cost_of_sales": Decimal("50.000000"),
        }
    ]
    executor = _FakeExecutor(rows)
    runtime = DatabaseRuntime(executor, result_limit=500)

    assert runtime.dialect_for(model) == "duckdb"
    result = await runtime.execute(compiled, model, subject_digest="digest-1")

    assert len(executor.calls) == 1
    governed, connection = executor.calls[0]
    assert connection == _CONNECTION
    assert governed.sql == compiled.sql
    assert "LIMIT" not in governed.sql.upper()
    assert governed.dialect == "duckdb"
    assert governed.driver == "duckdb"
    assert governed.tables == ("journal",)
    assert governed.rls_applied == ()
    assert governed.masked_columns == ()
    assert governed.limit == 500
    assert governed.subject_digest == "digest-1"
    assert governed.members == ("gross_margin_pct",)
    assert governed.physical_columns == (
        "account_id",
        "posting_date",
        "amount",
        "entity",
        "product_line",
        "cost_center",
    )
    assert result.target == "database"
    assert result.columns == ("bucket", "entity", "m_gross_margin_pct")
    assert result.rows == ({"bucket": date(2025, 1, 1), "entity": "TROC", "m_gross_margin_pct": Decimal("0.750000")},)


async def test_database_runtime_fetch_helpers(troc_pnl_yaml, chart_snapshot) -> None:
    executor = _FakeExecutor([{"account_id": "4000", "nature": "credit"}])
    runtime = DatabaseRuntime(executor)
    rows = await runtime.fetch_chart_rows(
        connection=_CONNECTION, driver="duckdb", table="erp.accounts", columns=["account_id", "nature"]
    )
    assert rows == [{"account_id": "4000", "nature": "credit"}]
    governed, connection = executor.calls[0]
    assert connection == _CONNECTION
    assert governed.sql == 'SELECT DISTINCT "account_id", "nature" FROM "erp"."accounts"'
    assert governed.tables == ("erp.accounts",)
    with pytest.raises(AccountingExecutionError):
        await runtime.fetch_chart_rows(connection=_CONNECTION, driver="duckdb", table="a.b.c.d", columns=["x"])


async def test_database_runtime_truncation_raises(troc_pnl_yaml, chart_snapshot) -> None:
    model = _table_model(troc_pnl_yaml, chart_snapshot)
    compiled = compile_metric(model, _gross_margin_request(), "duckdb")

    truncated = DatabaseRuntime(_FakeExecutor([], truncated=True), result_limit=10)
    with pytest.raises(AccountingExecutionError, match="exceeds 10"):
        await truncated.execute(compiled, model, subject_digest="d")

    original = SemanticExecutionError("execution_failed", "query execution failed")
    failing = DatabaseRuntime(_FakeExecutor(error=original))
    with pytest.raises(AccountingExecutionError) as caught:
        await failing.execute(compiled, model, subject_digest="d")
    assert caught.value.__cause__ is original

    # A float aggregate is rejected, never repaired.
    floats = DatabaseRuntime(_FakeExecutor([{"set_product_sales": 1.5, "set_returns": 0, "set_cost_of_sales": 0}]))
    with pytest.raises(AccountingExecutionError):
        await floats.execute(compiled, model, subject_digest="d")


async def test_runtimes_agree(troc_pnl_yaml, chart_snapshot, journal_frame, journal_duckdb_file) -> None:
    pytest.importorskip("duckdb")
    from parrot.interfaces.duckdb_engine import DuckDBEngine
    from parrot.semantic.execution import ConnectionResolver, Executor
    from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit

    frame_model = load_model(troc_pnl_yaml, chart_snapshot)
    table_model = _table_model(troc_pnl_yaml, chart_snapshot)
    env = {f"PARROT_SEMANTIC_CONN_{_CONNECTION.upper()}_DATABASE": str(journal_duckdb_file)}
    database = DatabaseRuntime(Executor(DatabaseQueryToolkit(), ConnectionResolver(env)))
    assert database.dialect_for(table_model) == "duckdb"

    async def provider(name: str) -> pa.Table:
        return journal_frame

    requests = [
        _gross_margin_request(),
        _request(metric="ebitda", grain="quarter", period={"from": "2025-01-01", "to": "2026-09-30"}),
        _request(
            metric="revenue",
            grain="month",
            dimensions=("product_line",),
            filters={"entity": "TROC"},
            period={"from": "2026-01-01", "to": "2026-06-30", "cumulative": "ytd"},
        ),
    ]
    engine = DuckDBEngine(threads=2)
    try:
        for request in requests:
            frame_compiled = compile_metric(frame_model, request, "duckdb")
            table_compiled = compile_metric(table_model, request, "duckdb")
            assert frame_compiled.sql == table_compiled.sql
            on_engine = await DuckDBRuntime(engine, provider).execute(frame_compiled, frame_model)
            on_database = await database.execute(table_compiled, table_model, subject_digest="d")
            assert on_engine.rows
            assert on_engine.columns == on_database.columns
            assert on_engine.rows == on_database.rows
            for row in on_database.rows:
                value = row[f"m_{request.metric}"]
                assert value is None or isinstance(value, Decimal)
    finally:
        await engine.close()

    columns = await database.fetch_columns(connection=_CONNECTION, driver="duckdb", table="journal")
    assert set(columns) == {"account_id", "posting_date", "amount", "entity", "product_line", "cost_center"}
    assert columns["amount"].upper().startswith("DECIMAL")
    with pytest.raises(AccountingExecutionError):
        await database.fetch_columns(connection=_CONNECTION, driver="duckdb", table="missing_table")


@pytest.mark.parametrize(
    ("arrow_type", "value"),
    [
        (pa.decimal128(38, 7), Decimal("1.2345678")),  # seven fractional digits
        (pa.decimal128(38, 0), Decimal(10) ** 33),  # beyond 32 integer digits
    ],
)
async def test_exact_numeric_types(troc_pnl_yaml, chart_snapshot, monkeypatch, arrow_type, value) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    compiled = compile_metric(model, _gross_margin_request(), "duckdb")
    frame = pa.table(
        {
            "account_id": ["4000", "4010"],
            "posting_date": [date(2025, 1, 2), date(2025, 1, 3)],
            "amount": pa.array([Decimal(1), value], type=arrow_type),
            "entity": ["TROC", "TROC"],
            "product_line": ["magic", "magic"],
            "cost_center": ["CC100", "CC100"],
        }
    )

    async def provider(name: str) -> pa.Table:
        return frame

    def must_not_convert(*args, **kwargs):  # pragma: no cover - reaching it is the failure
        raise AssertionError("out-of-range values must be rejected before conversion")

    monkeypatch.setattr(duckdb_runtime, "to_arrow", must_not_convert)
    engine = _FakeEngine()
    with pytest.raises(AccountingExecutionError):
        await DuckDBRuntime(engine, provider).execute(compiled, model)
    assert engine.calls == []
