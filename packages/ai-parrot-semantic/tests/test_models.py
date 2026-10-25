"""Regression contract: query/result contracts and trusted identity model (M2)."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.auth import PermissionContext, UserSession
from parrot.semantic.context import SemanticRequestIdentity
from parrot.semantic.errors import SemanticValidationError
from parrot.semantic.models import (
    CompiledQuery,
    FilterGroup,
    FilterLeaf,
    GovernedQuery,
    Limits,
    SemanticQuery,
    TimeDimension,
)


def test_dimensions_only_and_saved_query_exclusivity(tmp_path: Path) -> None:
    """Allow dimension lookups and reject explicit saved-query clauses."""
    del tmp_path
    query = SemanticQuery(model="sales", dimensions=["region"])
    assert query.canonical_json() == '{"dimensions":["region"],"filters":null,"limit":null,"metrics":[],"model":"sales","offset":0,"order_by":[],"saved_query":null,"time_dimensions":[],"timezone":null}'
    with pytest.raises(ValidationError, match="saved_query is exclusive"):
        SemanticQuery(model="sales", saved_query="regional_sales", dimensions=["region"])
    with pytest.raises(ValidationError, match="requires at least one"):
        SemanticQuery(model="sales")


def test_invalid_grains_limits_and_mixed_filters(tmp_path: Path) -> None:
    """Reject malformed limits, grains, filter values, and WHERE/HAVING mixes."""
    del tmp_path
    with pytest.raises(ValidationError, match="time dimensions require a grain"):
        TimeDimension(name="ordered_at")
    with pytest.raises(ValidationError, match="requires exactly 2 values"):
        FilterLeaf(member="region", op="between", values=["a"])
    with pytest.raises(ValidationError, match="1 <= default <= max"):
        Limits(default=0, max=10)
    with pytest.raises(ValidationError, match="offset requires order_by"):
        SemanticQuery(model="sales", dimensions=["region"], offset=1)

    query = SemanticQuery(
        model="sales",
        metrics=["revenue"],
        filters=FilterGroup(
            op="and",
            items=[
                FilterLeaf(member="revenue", op="gt", values=[0]),
                FilterLeaf(member="region", op="equals", values=["EU"]),
            ],
        ),
    )
    with pytest.raises(SemanticValidationError, match="WHERE and HAVING"):
        query.validate_against({"revenue": "metric", "region": "dimension"}, set())


def test_identity_snapshot_and_provenance_fields(tmp_path: Path) -> None:
    """Snapshot trusted context and retain governed provenance fields."""
    del tmp_path
    context = PermissionContext(
        session=UserSession("user-1", "tenant-1", frozenset({"analyst"}), {"region": "EU"}),
        extra={"request_source": "test"},
    )
    identity = SemanticRequestIdentity(ctx=context, channel="agent", agent_id="agent-1", session_id="session-1")
    context.extra["request_source"] = "mutated"
    context.session.metadata["region"] = "US"
    assert identity.ctx.extra["request_source"] == "test"
    assert identity.ctx.session.metadata["region"] == "EU"
    with pytest.raises(ValidationError, match="must not be blank"):
        SemanticRequestIdentity(ctx=context, channel="http", agent_id=" ", session_id="session-1")

    compiled = CompiledQuery(sql="SELECT 1", dialect="postgres", members=("revenue",), tables=("public.sales",), cache_key="k")
    governed = GovernedQuery(
        sql="SELECT 1",
        dialect="postgres",
        driver="pg",
        tables=("public.sales",),
        rls_applied=("tenant rule",),
        masked_columns=(),
        limit=100,
        subject_digest="digest",
        members=("revenue",),
        physical_columns=("public.sales.amount",),
    )
    assert "subject_digest" not in compiled.model_dump()
    assert governed.members == ("revenue",)
    assert governed.physical_columns == ("public.sales.amount",)
