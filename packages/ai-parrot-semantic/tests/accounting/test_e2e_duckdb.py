"""FEAT-713 integration tests over the 10k-row fixture journal.

Expected values are computed here from ``journal_frame`` with plain ``Decimal`` arithmetic and plain Python
predicates over account ids - never copied from engine output and never through floats.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Callable
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

pytest.importorskip("duckdb")

from parrot.semantic.accounting.audit import AccountingAuditEntry, rebuild_lineage
from parrot.semantic.accounting.errors import RequestValidationError
from parrot.semantic.accounting.loader import load_model
from parrot.semantic.accounting.toolkit import AccountingToolkit

_SCALE = Decimal("0.000001")

# Independent re-statement of the troc_pnl sets as plain predicates over the account id.
_PREDICATES: dict[str, Callable[[str], bool]] = {
    "product_sales": lambda a: a.startswith("40"),
    "returns": lambda a: a == "4900",
    "cost_of_sales": lambda a: a.startswith("5") and a != "5900",
    "other_cost": lambda a: a == "5900",
    "operating_expenses": lambda a: "6000" <= a <= "6799",
}
_CREDIT_PREFIX = "40"  # every 4xxx account except 4900 is credit-natured in the fixture chart


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _normalised(account_id: str, amount: Decimal) -> Decimal:
    """debit_positive journal: credit-natured accounts post negative, so their normalised value is -amount."""
    return -amount if account_id.startswith(_CREDIT_PREFIX) else amount


def _set_totals(frame: pa.Table, lower: date, upper: date) -> dict[date, dict[str, Decimal]]:
    """{month: {set_name: Decimal}} for postings in [lower, upper]; a month appears when it has any posting."""
    totals: dict[date, dict[str, Decimal]] = defaultdict(lambda: {name: Decimal(0) for name in _PREDICATES})
    for row in frame.to_pylist():
        posted = row["posting_date"]
        if not lower <= posted <= upper:
            continue
        bucket = totals[_month_start(posted)]
        for name, predicate in _PREDICATES.items():
            if predicate(row["account_id"]):
                bucket[name] += _normalised(row["account_id"], row["amount"])
    return dict(totals)


def _metrics(sets: dict[str, Decimal]) -> dict[str, Decimal | None]:
    revenue = sets["product_sales"] - sets["returns"]
    cogs = sets["cost_of_sales"]
    gross_margin = revenue - cogs
    opex = sets["operating_expenses"]
    ebitda = gross_margin - sets["other_cost"] - opex
    pct: Decimal | None = None
    if revenue != 0:
        with localcontext() as context:
            context.prec = 60
            pct = (gross_margin / revenue).quantize(_SCALE, rounding=ROUND_HALF_EVEN)
    return {
        "revenue": revenue,
        "cogs": cogs,
        "gross_margin": gross_margin,
        "opex": opex,
        "ebitda": ebitda,
        "gross_margin_pct": pct,
    }


def _expected_by_month(frame: pa.Table, lower: date, upper: date, metric: str) -> dict[str, Decimal | None]:
    return {
        month.isoformat(): _metrics(sets)[metric] for month, sets in sorted(_set_totals(frame, lower, upper).items())
    }


def _as_decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _by_bucket(result: dict, metric: str) -> dict[str, Decimal | None]:
    column = f"m_{metric}"
    assert result["columns"][0] == "bucket"
    assert column in result["columns"]
    assert result["row_count"] == len(result["rows"])
    return {str(row["bucket"]): _as_decimal(row[column]) for row in result["rows"]}


def _toolkit(troc_pnl_yaml: Path, chart_snapshot: Any, journal_frame: pa.Table, **kwargs: Any) -> AccountingToolkit:
    async def frame_provider(name: str) -> pa.Table:
        assert name == "journal"
        return journal_frame

    async def snapshot_provider(tenant: str, model: str, spec: Any) -> Any:
        assert (tenant, model) == ("troc", "troc_pnl")
        return chart_snapshot

    kwargs.setdefault("audit_mode", "best_effort")
    return AccountingToolkit(
        models_dir=troc_pnl_yaml.parent.parent,
        snapshot_provider=snapshot_provider,
        frame_provider=frame_provider,
        **kwargs,
    )


async def _close(toolkit: AccountingToolkit) -> None:
    if toolkit._engine is not None:
        await toolkit._engine.close()


async def test_e2e_duckdb_pnl(troc_pnl_yaml, chart_snapshot, journal_frame) -> None:
    """Every P&L metric by month equals the hand-computed Decimal; the empty month has no row (AC8/AC9)."""
    toolkit = _toolkit(troc_pnl_yaml, chart_snapshot, journal_frame)
    try:
        lower, upper = date(2025, 1, 1), date(2026, 9, 30)
        for metric in ("revenue", "cogs", "gross_margin", "opex", "ebitda", "gross_margin_pct"):
            result = await toolkit.query_metric(
                metric=metric, period_from=lower.isoformat(), period_to=upper.isoformat(), grain="month", tenant="troc"
            )
            expected = _expected_by_month(journal_frame, lower, upper, metric)
            actual = _by_bucket(result, metric)
            assert actual == expected, metric
            assert "2025-08-01" not in actual  # the fixture's empty month
            assert len(actual) == 20
        # Exactness: the totals are not float-representable round numbers, so equality above is a real check.
        revenue = _by_bucket(
            await toolkit.query_metric(
                metric="revenue", period_from="2025-01-01", period_to="2026-09-30", grain="month", tenant="troc"
            ),
            "revenue",
        )
        assert all(value is not None and value > 0 for value in revenue.values())
    finally:
        await _close(toolkit)


async def test_e2e_duckdb_cumulative(troc_pnl_yaml, chart_snapshot, journal_frame) -> None:
    """mtd / qtd / ytd results equal running sums of the hand-computed monthly values (AC8)."""
    toolkit = _toolkit(troc_pnl_yaml, chart_snapshot, journal_frame)
    try:
        monthly = _set_totals(journal_frame, date(2025, 1, 1), date(2025, 12, 31))

        # ytd, month grain: running sum from January (August is empty, so it has no row but still carries no value).
        result = await toolkit.query_metric(
            metric="ebitda",
            period_from="2025-01-01",
            period_to="2025-12-31",
            grain="month",
            cumulative="ytd",
            tenant="troc",
        )
        running = {name: Decimal(0) for name in _PREDICATES}
        expected: dict[str, Decimal | None] = {}
        for month, sets in sorted(monthly.items()):
            for name in running:
                running[name] += sets[name]
            expected[month.isoformat()] = _metrics(running)["ebitda"]
        assert _by_bucket(result, "ebitda") == expected

        # ytd, year grain: one bucket holding the whole-year ratio.
        year_sets = {name: sum((s[name] for s in monthly.values()), Decimal(0)) for name in _PREDICATES}
        result = await toolkit.query_metric(
            metric="gross_margin_pct",
            period_from="2025-01-01",
            period_to="2025-12-31",
            grain="year",
            cumulative="ytd",
            tenant="troc",
        )
        assert _by_bucket(result, "gross_margin_pct") == {"2025-01-01": _metrics(year_sets)["gross_margin_pct"]}

        # mtd at month grain equals the plain monthly value; qtd accumulates within each quarter.
        plain = _expected_by_month(journal_frame, date(2025, 1, 1), date(2025, 3, 31), "gross_margin")
        mtd = await toolkit.query_metric(
            metric="gross_margin",
            period_from="2025-01-01",
            period_to="2025-03-31",
            grain="month",
            cumulative="mtd",
            tenant="troc",
        )
        assert _by_bucket(mtd, "gross_margin") == plain
        qtd = await toolkit.query_metric(
            metric="gross_margin",
            period_from="2025-01-01",
            period_to="2025-03-31",
            grain="month",
            cumulative="qtd",
            tenant="troc",
        )
        total = Decimal(0)
        running_gm: dict[str, Decimal | None] = {}
        for bucket, value in plain.items():
            total += value  # type: ignore[operator]
            running_gm[bucket] = total
        assert _by_bucket(qtd, "gross_margin") == running_gm
    finally:
        await _close(toolkit)


async def test_weekly_cumulative_rejected(troc_pnl_yaml, chart_snapshot, journal_frame) -> None:
    """A cumulative mode with a week (or no) grain is refused before any data is read; plain weekly works."""
    requested: list[str] = []

    async def frame_provider(name: str) -> pa.Table:
        requested.append(name)
        return journal_frame

    async def snapshot_provider(tenant: str, model: str, spec: Any) -> Any:
        return chart_snapshot

    toolkit = AccountingToolkit(
        models_dir=troc_pnl_yaml.parent.parent,
        snapshot_provider=snapshot_provider,
        frame_provider=frame_provider,
        audit_mode="best_effort",
    )
    try:
        for grain in ("week", None):
            with pytest.raises(RequestValidationError):
                await toolkit.query_metric(
                    metric="gross_margin",
                    period_from="2025-01-01",
                    period_to="2025-12-31",
                    grain=grain,
                    cumulative="ytd",
                    tenant="troc",
                )
        assert requested == []  # no journal was fetched for the refused requests

        result = await toolkit.query_metric(
            metric="gross_margin", period_from="2025-12-22", period_to="2026-01-11", grain="week", tenant="troc"
        )
        buckets = list(_by_bucket(result, "gross_margin"))
        # ISO weeks start on Monday: 2025-12-22, 2025-12-29 (spans the year boundary), 2026-01-05.
        assert buckets == sorted(buckets)
        assert all(date.fromisoformat(bucket).weekday() == 0 for bucket in buckets)
        assert set(buckets) <= {"2025-12-22", "2025-12-29", "2026-01-05"}
        assert "2025-12-29" in buckets
    finally:
        await _close(toolkit)


async def test_e2e_duckdb_file_through_executor(
    troc_pnl_yaml, chart_snapshot, journal_frame, journal_duckdb_file, tmp_path, monkeypatch
) -> None:
    """The table-source variant over the DuckDB file (database runtime + Executor) equals the dataframe result."""
    monkeypatch.setenv("PARROT_SEMANTIC_CONN_ACCT_DATABASE", str(journal_duckdb_file))
    models_dir = tmp_path / "table_models"
    (models_dir / "troc").mkdir(parents=True)
    table_yaml = troc_pnl_yaml.read_text(encoding="utf-8").replace(
        "source: { dataframe: journal }", 'source: { table: "journal", connection: "acct", driver: "duckdb" }'
    )
    assert "table:" in table_yaml
    (models_dir / "troc" / "troc_pnl.yaml").write_text(table_yaml, encoding="utf-8")

    async def snapshot_provider(tenant: str, model: str, spec: Any) -> Any:
        return chart_snapshot

    toolkit = AccountingToolkit(
        models_dir=models_dir, snapshot_provider=snapshot_provider, audit_mode="best_effort"
    )  # no frame_provider: the data can only come through the database runtime
    try:
        model = await toolkit._ensure_loaded("troc", "troc_pnl")
        source = model.spec.chart_of_accounts.source
        assert (source.table, source.connection, source.driver) == ("journal", "acct", "duckdb")
        assert source.dataframe is None

        lower, upper = date(2025, 1, 1), date(2026, 9, 30)
        for metric in ("revenue", "ebitda", "gross_margin_pct"):
            result = await toolkit.query_metric(
                metric=metric,
                period_from=lower.isoformat(),
                period_to=upper.isoformat(),
                grain="month",
                tenant="troc",
            )
            assert _by_bucket(result, metric) == _expected_by_month(journal_frame, lower, upper, metric), metric
    finally:
        await _close(toolkit)


@pytest.mark.skipif(not os.environ.get("PARROT_TEST_PG_DSN"), reason="PARROT_TEST_PG_DSN not set")
async def test_e2e_postgres_parity(troc_pnl_yaml, chart_snapshot, journal_frame) -> None:
    """Postgres rows equal the hand-computed values (and therefore the DuckDB rows). Needs a reachable server."""
    pytest.importorskip("psycopg")
    import psycopg

    dsn = os.environ["PARROT_TEST_PG_DSN"]
    table = "feat713_journal_parity"
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        await conn.execute(f"DROP TABLE IF EXISTS {table}")
        await conn.execute(
            f"CREATE TABLE {table} (account_id text, posting_date date, amount numeric(18,2), entity text, "
            "product_line text, cost_center text)"
        )
        try:
            async with conn.cursor() as cur:
                await cur.executemany(
                    f"INSERT INTO {table} VALUES (%s, %s, %s, %s, %s, %s)",
                    [
                        (
                            r["account_id"],
                            r["posting_date"],
                            r["amount"],
                            r["entity"],
                            r["product_line"],
                            r["cost_center"],
                        )
                        for r in journal_frame.to_pylist()
                    ],
                )
            parity = load_model(troc_pnl_yaml, chart_snapshot)
            assert parity.spec.chart_of_accounts.source.dataframe == "journal"
            # The table-source model reads PARROT_SEMANTIC_CONN_ACCT_* from the environment; the operator that sets
            # PARROT_TEST_PG_DSN is expected to expose the same server under that connection name.
            models = Path(os.environ.get("PARROT_TEST_PG_MODELS_DIR", ""))
            if not models.is_dir():
                pytest.skip("PARROT_TEST_PG_MODELS_DIR (table-source model dir for connection 'acct') not set")

            async def snapshot_provider(tenant: str, model: str, spec: Any) -> Any:
                return chart_snapshot

            toolkit = AccountingToolkit(
                models_dir=models, snapshot_provider=snapshot_provider, audit_mode="best_effort"
            )
            result = await toolkit.query_metric(
                metric="revenue", period_from="2025-01-01", period_to="2026-09-30", grain="month", tenant="troc"
            )
            assert _by_bucket(result, "revenue") == _expected_by_month(
                journal_frame, date(2025, 1, 1), date(2026, 9, 30), "revenue"
            )
        finally:
            await conn.execute(f"DROP TABLE IF EXISTS {table}")


async def test_e2e_audit_trail(troc_pnl_yaml, chart_snapshot, journal_frame, recording_storage) -> None:
    """N queries -> N signed payloads; each entry's lineage rebuilds to the lineage the query returned (AC11)."""
    storage, payloads = recording_storage
    toolkit = _toolkit(troc_pnl_yaml, chart_snapshot, journal_frame, audit_storage=storage)
    try:
        results = [
            await toolkit.query_metric(
                metric=metric, period_from="2025-01-01", period_to="2025-12-31", grain="month", tenant="troc"
            )
            for metric in ("revenue", "gross_margin", "ebitda")
        ]
        assert len(payloads) == 3
        model = load_model(troc_pnl_yaml, chart_snapshot)
        for payload, result in zip(payloads, results, strict=True):
            entry = AccountingAuditEntry.model_validate(json.loads(payload))
            assert entry.entry_id == result["audit_id"]
            assert entry.sql_hash == result["sql_hash"]
            assert rebuild_lineage(entry, model).model_dump(mode="json") == result["lineage"]
        assert len({result["audit_id"] for result in results}) == 3
    finally:
        await _close(toolkit)
