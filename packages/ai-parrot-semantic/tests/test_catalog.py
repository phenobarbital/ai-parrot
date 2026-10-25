"""Regression contract: Authorized catalog and saved-query expansion (M7)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import shutil

import pytest

from parrot.semantic.catalog import RoleCatalog
from parrot.semantic.errors import SemanticAccessError, SemanticValidationError
from parrot.semantic.loader import SemanticModelLoader
from parrot.semantic.model import Metric
from parrot.semantic.models import FilterGroup, FilterLeaf, OrderBy, SemanticQuery, TimeDimension
from parrot.semantic.policy import RoleGrant, SavedQuery

_FIXTURES = Path(__file__).parent / "fixtures" / "models"


def _catalog(tmp_path: Path) -> RoleCatalog:
    models_dir = tmp_path / "models"
    shutil.copytree(_FIXTURES, models_dir)
    (models_dir / "customers.policy.yaml").write_text("governed: false\n", encoding="utf-8")
    return RoleCatalog(SemanticModelLoader(models_dir, driver="duckdb").load())


def test_catalog_denied_models_and_safe_suggestions(tmp_path: Path) -> None:
    """Verify catalog denied models and safe suggestions."""
    catalog = _catalog(tmp_path)
    analyst = frozenset({"analyst"})
    assert catalog.visible_members("orders", analyst, authorized=False) == []
    assert catalog.visible_members("orders", frozenset({"nobody"}), authorized=True) == []
    names = {m.name for m in catalog.visible_members("orders", analyst, authorized=True)}
    assert names == {"revenue", "order_count", "region", "order_date"}
    # Ungoverned models are visible; denied governed model filtered, not failing the listing.
    hits = catalog.search("count", frozenset({"nobody"}), authorized={"orders": True})
    assert [(h["model"], h["member"]) for h in hits] == [("customers", "customer_count")]
    # Restricted grant: suggestions never leak non-granted members.
    orders = catalog.models["orders"]
    policy = orders.policy.model_copy(update={"roles": {"viewer": RoleGrant(metrics=["order_count"])}})
    catalog.models["orders"] = orders.model_copy(update={"policy": policy})
    assert catalog.search("revenue", frozenset({"viewer"}), "orders", authorized={"orders": True}) == []
    with pytest.raises(SemanticAccessError) as exc:
        catalog.check_query_rights(SemanticQuery(model="orders", metrics=["revenue"]), frozenset({"viewer"}))
    assert exc.value.code == "member_not_granted"
    assert exc.value.details["suggestions"] == ["order_count"]
    with pytest.raises(SemanticAccessError):
        catalog.visible_members("missing", frozenset(), authorized=True)


def test_all_referenced_members_checked(tmp_path: Path) -> None:
    """Verify all referenced members checked."""
    catalog = _catalog(tmp_path)
    orders = catalog.models["orders"]
    policy = orders.policy.model_copy(
        update={"roles": {"r": RoleGrant(metrics=["revenue", "order_count"], dimensions=["region"])}}
    )
    catalog.models["orders"] = orders.model_copy(update={"policy": policy})
    roles = frozenset({"r"})
    catalog.check_query_rights(SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"]), roles)
    denied = [
        SemanticQuery(
            model="orders", metrics=["revenue"], time_dimensions=[TimeDimension(name="order_date", grain="day")]
        ),
        SemanticQuery(
            model="orders",
            metrics=["revenue"],
            filters=FilterGroup(
                op="and", items=[FilterGroup(op="or", items=[FilterLeaf(member="order_date", op="is_set")])]
            ),
        ),
        SemanticQuery(model="orders", metrics=["revenue"], order_by=[OrderBy(member="order_date", grain="day")]),
    ]
    for query in denied:
        with pytest.raises(SemanticAccessError) as exc:
            catalog.check_query_rights(query, roles)
        assert exc.value.details["member"] == "order_date"
    # Derived dependency: granted derived metric over a non-granted metric is denied.
    model = orders.model.model_copy(
        update={
            "metrics": (
                *orders.model.metrics,
                Metric(name="aov", sql="orders.secret / orders.order_count"),
                Metric(name="secret", agg="count"),
            )
        }
    )
    policy = policy.model_copy(update={"roles": {"r": RoleGrant(metrics=["aov", "order_count"])}})
    catalog.models["orders"] = orders.model_copy(update={"model": model, "policy": policy})
    with pytest.raises(SemanticAccessError) as exc:
        catalog.check_query_rights(SemanticQuery(model="orders", metrics=["aov"]), roles)
    assert exc.value.details["member"] == "secret"
    assert "secret" not in exc.value.details["suggestions"]


def test_saved_query_same_model_expansion(tmp_path: Path) -> None:
    """Verify saved query same model expansion."""
    catalog = _catalog(tmp_path)
    orders = catalog.models["orders"]
    saved = SavedQuery(
        name="rev_by_region",
        query=SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"], limit=50),
        verified_by="qa",
        verified_at=date(2026, 1, 1),
    )
    policy = orders.policy.model_copy(update={"saved_queries": [saved]})
    catalog.models["orders"] = orders.model_copy(update={"policy": policy})
    expanded = catalog.expand_saved_query(SemanticQuery(model="orders", saved_query="rev_by_region"))
    assert expanded.model == "orders" and expanded.metrics == ["revenue"] and expanded.limit == 50
    assert expanded.saved_query is None
    overridden = catalog.expand_saved_query(SemanticQuery(model="orders", saved_query="rev_by_region", limit=5))
    assert overridden.limit == 5
    catalog.check_query_rights(expanded, frozenset({"analyst"}))
    with pytest.raises(SemanticAccessError):
        catalog.check_query_rights(expanded, frozenset({"nobody"}))
    with pytest.raises(SemanticValidationError) as exc:
        catalog.expand_saved_query(SemanticQuery(model="orders", saved_query="nope"))
    assert exc.value.code == "unknown_saved_query"
    with pytest.raises(SemanticValidationError):
        catalog.expand_saved_query(SemanticQuery(model="customers", saved_query="rev_by_region"))
