"""Tests for semantic-layer request and result contracts."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.semantic.errors import SemanticValidationError
from parrot.semantic.models import (
    CompiledQuery,
    FilterGroup,
    FilterLeaf,
    GovernedQuery,
    SemanticQuery,
    TimeDimension,
)


def test_semantic_query_validators() -> None:
    """Validate query shape plus member-dependent mixed filters and missing grains."""
    with pytest.raises(ValidationError):
        SemanticQuery(model="orders", metrics=["revenue"], saved_query="monthly")
    with pytest.raises(ValidationError):
        SemanticQuery(model="orders", metrics=["revenue"], offset=10)
    with pytest.raises(ValidationError):
        SemanticQuery(model="orders", metrics=["revenue"], limit=0)
    with pytest.raises(ValidationError):
        SemanticQuery(model="orders", metrics=["revenue"], password="p")

    query = SemanticQuery(
        model="orders",
        metrics=["revenue"],
        filters=FilterGroup(
            op="and",
            items=[
                FilterLeaf(member="revenue", op="gt", values=[1]),
                FilterLeaf(member="region", op="equals", values=["n"]),
            ],
        ),
    )
    with pytest.raises(SemanticValidationError, match="mixed_filter_group"):
        query.validate_against({"revenue": "metric", "region": "dimension"}, set())

    query = SemanticQuery(
        model="orders",
        metrics=["revenue"],
        time_dimensions=[TimeDimension(name="order_date")],
    )
    with pytest.raises(SemanticValidationError, match="grain_required"):
        query.validate_against({"revenue": "metric", "order_date": "time_dimension"}, {"order_date"})


def test_canonical_json_stable() -> None:
    """Canonical JSON is insensitive to constructor keyword ordering."""
    first = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])
    second = SemanticQuery(dimensions=["region"], metrics=["revenue"], model="orders")
    assert first.canonical_json() == second.canonical_json()


def test_compiled_and_governed_queries_are_frozen() -> None:
    """Immutable compiler and governance contracts reject field assignment."""
    compiled = CompiledQuery(
        sql="SELECT 1",
        dialect="duckdb",
        engine="native",
        members=("revenue",),
        tables=("sales.orders",),
        cache_key="cache-key",
    )
    governed = GovernedQuery(
        sql="SELECT 1 LIMIT 1",
        dialect="duckdb",
        driver="duckdb",
        tables=("sales.orders",),
        rls_applied=(),
        masked_columns=(),
        limit=1,
        subject_digest="subject",
    )

    with pytest.raises(ValidationError):
        compiled.sql = "SELECT 2"
    with pytest.raises(ValidationError):
        governed.limit = 2
