"""Regression contract: Join-grain safety, filtered and derived metrics (M5b)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from parrot.semantic.engines.native import NativeCompiler
from parrot.semantic.errors import SemanticValidationError
from parrot.semantic.loader import LoadedModel, SemanticModelLoader
from parrot.semantic.models import FilterGroup, FilterLeaf, OrderBy, SemanticQuery

_MODELS = """models:
  - name: customers
    table: dim.customers
    columns: {id: INTEGER, tenant: VARCHAR, segment: VARCHAR}
    primary_key: [id, tenant]
    dimensions:
      - {name: segment, kind: categorical, column: segment}
    metrics:
      - {name: customer_count, agg: count}
    relationships:
      - {from_model: customers, to_model: orders, cardinality: one_to_many, from_columns: [id, tenant], to_columns: [customer_id, tenant], join_type: inner}
  - name: orders
    table: sales.orders
    columns: {id: INTEGER, customer_id: INTEGER, tenant: VARCHAR, status: VARCHAR, region: VARCHAR, amount: DECIMAL}
    primary_key: [id]
    dimensions:
      - {name: region, kind: categorical, column: region}
      - {name: status, kind: categorical, column: status}
    metrics:
      - {name: revenue, agg: sum, column: amount}
      - {name: order_count, agg: count}
      - {name: paid_revenue, agg: sum, column: amount, filter: {op: and, items: [{member: status, op: equals, values: [paid]}]}}
      - {name: big_orders, agg: count, filter: {op: and, items: [{member: region, op: equals, values: [nowhere]}]}}
      - {name: avg_order, sql: "orders.revenue / orders.order_count"}
      - {name: big_ratio, sql: "orders.revenue / orders.big_orders"}
    relationships:
      - {from_model: orders, to_model: items, cardinality: one_to_many, from_columns: [id], to_columns: [order_id], join_type: left}
      - {from_model: orders, to_model: shipments, cardinality: one_to_many, from_columns: [id], to_columns: [order_id], join_type: left}
  - name: items
    table: sales.items
    columns: {id: INTEGER, order_id: INTEGER, sku: VARCHAR}
    primary_key: [id]
    dimensions:
      - {name: sku, kind: categorical, column: sku}
    metrics: []
    relationships: []
  - name: shipments
    table: sales.shipments
    columns: {id: INTEGER, order_id: INTEGER, carrier: VARCHAR}
    primary_key: [id]
    dimensions:
      - {name: carrier, kind: categorical, column: carrier}
    metrics: []
    relationships: []
"""


def _load(tmp_path: Path) -> dict[str, LoadedModel]:
    """Load the join fixture with an ungoverned policy for every model."""
    models = tmp_path / "models"
    models.mkdir()
    (models / "all.yml").write_text(_MODELS, encoding="utf-8")
    for name in ("customers", "orders", "items", "shipments"):
        (models / f"{name}.policy.yaml").write_text("governed: false\nconnection: warehouse\n", encoding="utf-8")
    return SemanticModelLoader(models, driver="duckdb").load()


def _query(**kwargs: object) -> SemanticQuery:
    """Build an orders-rooted query."""
    return SemanticQuery(model="orders", **kwargs)  # type: ignore[arg-type]


def test_many_to_one_and_fanout_rejection(tmp_path: Path) -> None:
    """Allow many-to-one composite joins; reject fan-out, sibling and mixed-grain plans."""
    duckdb = pytest.importorskip("duckdb")
    loaded = _load(tmp_path)
    orders = NativeCompiler(loaded["orders"])
    query = _query(
        metrics=["revenue"],
        dimensions=["customers.segment"],
        order_by=[OrderBy(member="customers.segment")],
    )
    sql = orders.compile(query, "duckdb").sql
    assert "INNER JOIN dim.customers AS customers ON customers.id = orders.customer_id AND" in sql
    assert "customers.tenant = orders.tenant" in sql
    compiled = orders.compile(query, "duckdb")
    assert compiled.tables == ("sales.orders", "dim.customers")

    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE SCHEMA sales")
        connection.execute("CREATE SCHEMA dim")
        connection.execute("CREATE TABLE dim.customers (id INTEGER, tenant VARCHAR, segment VARCHAR)")
        connection.execute(
            "CREATE TABLE sales.orders (id INTEGER, customer_id INTEGER, tenant VARCHAR, status VARCHAR, "
            "region VARCHAR, amount DECIMAL)"
        )
        connection.execute("INSERT INTO dim.customers VALUES (1, 't', 'smb'), (2, 't', 'ent'), (1, 'u', 'ent')")
        connection.execute(
            "INSERT INTO sales.orders VALUES (1, 1, 't', 'paid', 'eu', 10), (2, 1, 't', 'open', 'eu', 5), "
            "(3, 2, 't', 'paid', 'us', 7), (4, 1, 'u', 'paid', 'us', 3)"
        )
        rows = connection.execute(sql).fetchall()
    finally:
        connection.close()
    assert [(float(r[0]), r[1]) for r in rows] == [(10.0, "ent"), (15.0, "smb")]

    for bad in (
        SemanticQuery(model="customers", metrics=["customer_count"], dimensions=["orders.region"]),
        _query(metrics=["revenue"], dimensions=["items.sku"]),
        _query(metrics=["revenue"], dimensions=["items.sku", "shipments.carrier"]),
        _query(metrics=["revenue", "customers.customer_count"]),
    ):
        compiler = NativeCompiler(loaded[bad.model])
        with pytest.raises(SemanticValidationError) as raised:
            compiler.compile(bad, "duckdb")
        assert raised.value.code == "join_fanout"
    # Inputs stay immutable and compilation stateless.
    assert orders.compile(query, "duckdb") == compiled


def test_filtered_derived_metrics_and_zero_denominator(tmp_path: Path) -> None:
    """Lower filtered measures per dialect and derived division with CASE-guarded NULL."""
    duckdb = pytest.importorskip("duckdb")
    loaded = _load(tmp_path)
    compiler = NativeCompiler(loaded["orders"])
    query = _query(metrics=["paid_revenue", "avg_order", "big_ratio", "big_orders"], dimensions=["region"])
    duck = compiler.compile(query, "duckdb").sql
    postgres = compiler.compile(query, "postgres").sql
    bigquery = compiler.compile(query, "bigquery").sql
    assert "SUM(orders.amount) FILTER(WHERE orders.status = 'paid')" in duck
    assert "FILTER(WHERE" in postgres
    assert "FILTER" not in bigquery
    assert "SUM(CASE WHEN orders.status = 'paid' THEN orders.amount END)" in bigquery
    assert "COUNT(CASE WHEN orders.region = 'nowhere' THEN 1 END)" in bigquery
    for sql in (duck, postgres, bigquery):
        assert "CASE WHEN" in sql and "= 0 THEN NULL" in sql
    assert compiler.dependencies("avg_order") == ("orders.order_count", "orders.revenue", "orders.avg_order")

    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE SCHEMA sales")
        connection.execute(
            "CREATE TABLE sales.orders (id INTEGER, customer_id INTEGER, tenant VARCHAR, status VARCHAR, "
            "region VARCHAR, amount DECIMAL)"
        )
        connection.execute(
            "INSERT INTO sales.orders VALUES (1, 1, 't', 'paid', 'eu', 10), (2, 1, 't', 'open', 'eu', 5), "
            "(3, 2, 't', 'paid', 'us', 7)"
        )
        rows = connection.execute(duck.replace("LIMIT 1000", "ORDER BY region LIMIT 1000")).fetchall()
    finally:
        connection.close()
    by_region = {row[4]: row for row in rows}
    assert float(by_region["eu"][0]) == 10.0 and float(by_region["eu"][1]) == 7.5
    assert by_region["eu"][2] is None and by_region["us"][2] is None
    assert by_region["eu"][3] == 0


def test_cross_process_hash_and_golden_sql(tmp_path: Path) -> None:
    """SQL is byte-identical across processes with different PYTHONHASHSEED values."""
    loaded = _load(tmp_path)
    compiler = NativeCompiler(loaded["orders"])
    query = _query(
        metrics=["revenue", "paid_revenue"],
        dimensions=["customers.segment", "region"],
        filters=FilterGroup(op="and", items=[FilterLeaf(member="customers.segment", op="equals", values=["ent"])]),
        limit=5,
    )
    golden = {
        "duckdb": (
            "SELECT SUM(orders.amount) AS revenue, SUM(orders.amount) FILTER(WHERE orders.status = 'paid') AS "
            'paid_revenue, customers.segment AS "customers.segment", orders.region AS region FROM sales.orders AS '
            "orders INNER JOIN dim.customers AS customers ON customers.id = orders.customer_id AND customers.tenant "
            "= orders.tenant WHERE customers.segment = 'ent' GROUP BY customers.segment, orders.region LIMIT 5"
        ),
    }
    rendered = {dialect: compiler.compile(query, dialect).sql for dialect in ("duckdb", "postgres", "bigquery")}
    assert rendered["duckdb"] == golden["duckdb"]
    assert "FILTER(WHERE" in rendered["postgres"] and "FILTER" not in rendered["bigquery"]
    assert "CASE WHEN orders.status = 'paid' THEN orders.amount END" in rendered["bigquery"]
    assert all(" INNER JOIN " in sql and "LIMIT 5" in sql for sql in rendered.values())
    expected = hashlib.sha256("\n".join(rendered[d] for d in sorted(rendered)).encode()).hexdigest()

    script = (
        "import hashlib, sys\n"
        "from pathlib import Path\n"
        "from parrot.semantic.engines.native import NativeCompiler\n"
        "from parrot.semantic.loader import SemanticModelLoader\n"
        "from parrot.semantic.models import FilterGroup, FilterLeaf, SemanticQuery\n"
        "model = SemanticModelLoader(Path(sys.argv[1]), driver='duckdb').load()['orders']\n"
        "q = SemanticQuery(model='orders', metrics=['revenue', 'paid_revenue'], dimensions=['customers.segment', 'region'],"
        " filters=FilterGroup(op='and', items=[FilterLeaf(member='customers.segment', op='equals', values=['ent'])]), limit=5)\n"
        "c = NativeCompiler(model)\n"
        "print(hashlib.sha256('\\n'.join(c.compile(q, d).sql for d in sorted(['duckdb','postgres','bigquery'])).encode()).hexdigest())\n"
    )
    for seed in ("0", "1", "4242"):
        src = str(Path(__file__).resolve().parents[1] / "src")
        env = {
            **os.environ,
            "PYTHONHASHSEED": seed,
            "PYTHONPATH": os.pathsep.join([src, os.environ.get("PYTHONPATH", "")]),
        }
        out = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path / "models")],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        assert out.stdout.strip() == expected
