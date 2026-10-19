"""Tests for the role-filtered semantic catalog (spec §3 Module 7, AC19)."""

from __future__ import annotations

import pytest

from parrot.semantic.catalog import RoleCatalog
from parrot.semantic.errors import SemanticAccessError, SemanticValidationError
from parrot.semantic.models import SemanticQuery
from parrot.semantic.policy import SavedQuery

from ._models import loaded_models, models_dir  # noqa: F401

ANALYST = frozenset({"analyst"})


def test_catalog_role_filtering_and_suggestions(loaded_models):  # noqa: F811
    cat = RoleCatalog(loaded_models)
    assert cat.visible_members("orders", ANALYST, authorized=False) == []
    assert cat.search("revenue", ANALYST, authorized={"orders": False}) == []
    names = {member.name for member in cat.visible_members("orders", ANALYST, authorized=True)}
    assert names <= {"revenue", "orders", "region", "order_date"}
    assert "revenue" in names and "tenant_id" not in names and "email" not in names

    with pytest.raises(SemanticAccessError) as info:
        cat.check_query_rights(SemanticQuery(model="orders", metrics=["revenu"]), ANALYST)
    suggestions = info.value.details["suggestions"]
    assert info.value.code == "member_not_granted"
    assert suggestions[0] == "revenue" and len(suggestions) <= 3
    assert set(suggestions) <= names

    with pytest.raises(SemanticAccessError) as info:
        cat.check_query_rights(
            SemanticQuery(
                model="orders",
                metrics=["revenue"],
                filters={
                    "op": "and",
                    "items": [{"op": "or", "items": [{"member": "tenant_id", "op": "equals", "values": ["x"]}]}],
                },
            ),
            ANALYST,
        )
    assert info.value.details["member"] == "tenant_id"
    cat.check_query_rights(SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"]), ANALYST)

    hits = cat.search("rev", ANALYST, authorized={"orders": True})
    assert hits and hits[0]["name"] == "revenue"


def test_saved_query_expansion(loaded_models):  # noqa: F811
    stored = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"], limit=50)
    loaded_models["orders"].policy.saved_queries.append(
        SavedQuery(name="monthly_revenue", query=stored, verified_by="qa", verified_at="2026-10-01")
    )
    cat = RoleCatalog(loaded_models)
    expanded = cat.expand_saved_query(SemanticQuery(model="orders", saved_query="monthly_revenue", limit=5))
    assert expanded.metrics == ["revenue"] and expanded.limit == 5 and expanded.saved_query is None
    cat.check_query_rights(expanded, ANALYST)
    with pytest.raises(SemanticValidationError):
        cat.expand_saved_query(SemanticQuery(model="orders", saved_query="nope"))
