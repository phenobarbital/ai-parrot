"""Regression contract: Native single-table compiler and async compile entry (M5a)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.semantic.cache import CompileCache
from parrot.semantic.engines import compile
from parrot.semantic.engines.native import NativeCompiler
from parrot.semantic.models import FilterGroup, FilterLeaf, OrderBy, SemanticQuery, TimeDimension


def test_single_table_dialect_sql_and_rows(tmp_path: Path) -> None:
    """Compile one aggregate query for all supported dialect renderers and execute DuckDB SQL."""
    duckdb = pytest.importorskip("duckdb")
    from parrot.semantic.loader import SemanticModelLoader

    models = tmp_path / "models"
    models.mkdir()
    (models / "orders.yml").write_text(
        """models:
  - name: orders
    table: sales.orders
    columns: {region: VARCHAR, order_date: TIMESTAMP, amount: DECIMAL}
    primary_key: [region]
    dimensions:
      - {name: region, kind: categorical, column: region}
      - {name: order_date, kind: time, column: order_date, grain: month}
    metrics:
      - {name: revenue, agg: sum, column: amount}
    relationships: []
""",
        encoding="utf-8",
    )
    (models / "orders.policy.yaml").write_text(
        "governed: false\nconnection: warehouse\nlimits: {default: 50, max: 100}\n",
        encoding="utf-8",
    )
    model = SemanticModelLoader(models, driver="duckdb").load()["orders"]
    query = SemanticQuery(
        model="orders",
        metrics=["revenue"],
        dimensions=["region"],
        time_dimensions=[TimeDimension(name="order_date", grain="month")],
        filters=FilterGroup(op="and", items=[FilterLeaf(member="region", op="equals", values=["eu"])]),
        order_by=[OrderBy(member="region")],
        limit=10,
    )
    compiler = NativeCompiler(model)
    rendered = {dialect: compiler.compile(query, dialect).sql for dialect in ("duckdb", "postgres", "bigquery")}
    assert all("SUM" in sql and "GROUP BY" in sql and "LIMIT 10" in sql for sql in rendered.values())
    distinct_sql = compiler.compile(
        SemanticQuery(model="orders", dimensions=["region"], order_by=[OrderBy(member="region")], offset=1),
        "duckdb",
    ).sql
    having_sql = compiler.compile(
        SemanticQuery(
            model="orders",
            metrics=["revenue"],
            filters=FilterGroup(op="and", items=[FilterLeaf(member="revenue", op="gt", values=[10])]),
        ),
        "duckdb",
    ).sql
    assert "SELECT DISTINCT" in distinct_sql and "OFFSET 1" in distinct_sql
    assert "HAVING SUM" in having_sql

    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE SCHEMA sales")
        connection.execute("CREATE TABLE sales.orders (region VARCHAR, order_date TIMESTAMP, amount DECIMAL)")
        connection.execute("INSERT INTO sales.orders VALUES ('eu', '2026-01-01', 12), ('eu', '2026-01-10', 8), ('us', '2026-01-02', 5)")
        rows = connection.execute(rendered["duckdb"]).fetchall()
    finally:
        connection.close()
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(20)
    assert rows[0][1] == "eu"
    assert rows[0][2].isoformat() == "2026-01-01T00:00:00"


def test_literal_like_wildcards(tmp_path: Path) -> None:
    """Render literal wildcard matching with an explicit SQL LIKE escape clause."""
    from parrot.semantic.loader import SemanticModelLoader

    models = tmp_path / "models"
    models.mkdir()
    (models / "events.yml").write_text(
        """models:
  - name: events
    table: events
    columns: {label: VARCHAR}
    primary_key: [label]
    dimensions:
      - {name: label, kind: categorical, column: label}
    metrics: []
    relationships: []
""",
        encoding="utf-8",
    )
    (models / "events.policy.yaml").write_text("governed: false\nconnection: warehouse\n", encoding="utf-8")
    model = SemanticModelLoader(models, driver="duckdb").load()["events"]
    query = SemanticQuery(
        model="events",
        dimensions=["label"],
        filters=FilterGroup(op="and", items=[FilterLeaf(member="label", op="contains", values=[r"a%_\b"])]),
    )
    sql = NativeCompiler(model).compile(query, "duckdb").sql
    assert "ESCAPE" in sql and r"a\%\_\\b" in sql


@pytest.mark.asyncio
async def test_cache_key_and_no_database_at_compile(tmp_path: Path) -> None:
    """Use canonical cache keys and avoid recompiling on a pre-governance cache hit."""
    from parrot.semantic.loader import SemanticModelLoader

    models = tmp_path / "models"
    models.mkdir()
    (models / "events.yml").write_text(
        """models:
  - name: events
    table: events
    columns: {label: VARCHAR}
    primary_key: [label]
    dimensions:
      - {name: label, kind: categorical, column: label}
    metrics: []
    relationships: []
""",
        encoding="utf-8",
    )
    (models / "events.policy.yaml").write_text("governed: false\nconnection: warehouse\n", encoding="utf-8")
    model = SemanticModelLoader(models, driver="duckdb").load()["events"]
    query = SemanticQuery(model="events", dimensions=["label"])
    cache = CompileCache()
    first = await compile(query, model, "duckdb", cache=cache)
    second = await compile(query, model, "duckdb", cache=cache)
    assert second is first
    assert json.loads(first.cache_key) == [
        model.model_digest,
        model.policy_digest,
        query.canonical_json(),
        "duckdb",
        model.compiler_version,
        "warehouse",
    ]
