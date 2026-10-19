"""Tests for sidemantic compilation and async dispatch."""

from __future__ import annotations

import asyncio

import pytest
import sqlglot

from parrot.semantic.engines import compile
from parrot.semantic.engines.sidemantic_engine import filter_tree_to_sidemantic
from parrot.semantic.models import FilterGroup, FilterLeaf, SemanticQuery

from ._models import loaded_models, models_dir


@pytest.mark.parametrize("dialect", ["postgres", "bigquery", "duckdb"])
async def test_sidemantic_compile_pg_bq_duckdb(loaded_models, dialect: str) -> None:
    """One semantic query compiles without a connection for every supported dialect."""
    query = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])
    compiled = await compile(query, loaded_models["orders"], dialect)

    assert compiled.dialect == dialect
    assert compiled.tables == ("sales.orders",)
    assert "sales" in compiled.sql


async def test_compile_concurrent_to_thread(loaded_models) -> None:
    """Concurrent dispatch is deterministic for one shared sidemantic layer."""
    query = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])
    serial = await compile(query, loaded_models["orders"], "duckdb")
    results = await asyncio.gather(*[compile(query, loaded_models["orders"], "duckdb") for _ in range(32)])

    assert {result.sql for result in results} == {serial.sql}


@pytest.mark.parametrize("dialect", ["postgres", "bigquery"])
async def test_dialect_sql_snapshots(loaded_models, dialect: str) -> None:
    """Normalized PostgreSQL and BigQuery ASTs retain the expected physical query shape."""
    query = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])
    compiled = await compile(query, loaded_models["orders"], dialect)
    normalized = sqlglot.parse_one(compiled.sql, read=dialect).sql(dialect=dialect, pretty=False)

    assert "sales.orders" in normalized
    assert "SUM" in normalized
    assert "GROUP BY 1" in normalized


def test_filter_tree_uses_typed_literals(loaded_models) -> None:
    """Filter values are quoted by sqlglot and nested boolean structure is preserved."""
    members = {member.name: member for member in loaded_models["orders"].members}
    filters = FilterGroup(
        op="or",
        items=[
            FilterLeaf(member="region", op="equals", values=["EU' OR 1=1 --"]),
            FilterLeaf(member="revenue", op="gte", values=[10]),
        ],
    )

    rendered = filter_tree_to_sidemantic(filters, members)

    assert rendered == ["region = 'EU'' OR 1=1 --' OR revenue >= 10"]
