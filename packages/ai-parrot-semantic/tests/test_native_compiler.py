"""Tests for the sqlglot-native semantic compiler subset."""

from __future__ import annotations

import pytest

from parrot.semantic.engines import compile
from parrot.semantic.engines.native import NativeCompiler
from parrot.semantic.errors import SemanticValidationError
from parrot.semantic.models import SemanticQuery, TimeDimension

from ._models import duckdb_warehouse, loaded_models, models_dir


def test_native_compiler_subset(loaded_models) -> None:
    """The native subset supports grains and safe many-to-one dimension joins."""
    query = SemanticQuery(
        model="orders",
        metrics=["revenue"],
        dimensions=["email"],
        time_dimensions=[TimeDimension(name="order_date", grain="month")],
    )

    compiled = NativeCompiler(loaded_models["orders"]).compile(query, "duckdb")

    assert "DATE_TRUNC('MONTH'" in compiled.sql.upper()
    assert "LEFT JOIN dim.customers AS customers" in compiled.sql
    assert "GROUP BY" in compiled.sql.upper()


def test_native_rejects_fan_out(loaded_models) -> None:
    """A one-to-many path from the aggregate root fails closed as fan-out."""
    orders = loaded_models["orders"]
    customers = orders.layer.graph.models["customers"]
    customers.metrics.append(type(orders.layer.graph.models["orders"].metrics[0])(
        name="customer_revenue", agg="sum", sql="salary"
    ))
    customer_model = orders.model_copy(
        update={
            "name": "customers",
            "members": [*orders.members, type(orders.members[0])(name="customer_revenue", kind="metric")],
        }
    )

    with pytest.raises(SemanticValidationError, match="fan_out"):
        NativeCompiler(customer_model).compile(
            SemanticQuery(model="customers", metrics=["customer_revenue"], dimensions=["region"]), "duckdb"
        )


async def test_native_vs_sidemantic_parity(loaded_models, duckdb_warehouse: str) -> None:
    """Native and sidemantic subset queries return identical DuckDB rows."""
    query = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])
    native = NativeCompiler(loaded_models["orders"]).compile(query, "duckdb")
    sidemantic = await compile(query, loaded_models["orders"], "duckdb")
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(duckdb_warehouse, read_only=True)
    try:
        native_rows = sorted(connection.execute(native.sql).fetchall())
        sidemantic_rows = sorted(connection.execute(sidemantic.sql).fetchall())
    finally:
        connection.close()

    assert native_rows == sidemantic_rows


@pytest.mark.parametrize("dialect", ["postgres", "bigquery"])
def test_native_dialect_snapshots(loaded_models, dialect: str) -> None:
    """Postgres and BigQuery SQL retain the native aggregate and grouping shape."""
    compiled = NativeCompiler(loaded_models["orders"]).compile(
        SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"]), dialect
    )

    assert (
        compiled.sql
        == "SELECT orders.region AS region, SUM(orders.amount) AS revenue "
        "FROM sales.orders AS orders GROUP BY orders.region"
    )
