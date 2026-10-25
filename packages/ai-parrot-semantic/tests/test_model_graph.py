"""Regression contract: Frozen semantic graph and structural validation (M4a)."""

from pathlib import Path

import pytest

from parrot.semantic.errors import SemanticPolicyError
from parrot.semantic.model import Dimension, Metric, Relationship, SemanticModel, validate_model_graph
from parrot.semantic.models import FilterGroup, FilterLeaf


def _model(
    name: str,
    *,
    columns: dict[str, str] | None = None,
    primary_key: tuple[str, ...] = ("id",),
    dimensions: tuple[Dimension, ...] = (),
    metrics: tuple[Metric, ...] = (),
    relationships: tuple[Relationship, ...] = (),
) -> SemanticModel:
    """Build a compact model fixture."""
    return SemanticModel(
        name=name,
        table=f"analytics.{name}",
        columns=columns or {"id": "BIGINT"},
        primary_key=primary_key,
        dimensions=dimensions,
        metrics=metrics,
        relationships=relationships,
    )


def test_aggregate_inputs_and_derived_cycles(tmp_path: Path) -> None:
    """Verify aggregate inputs and derived cycles."""
    assert tmp_path.exists()
    region = Dimension(name="region", kind="categorical", column="region")
    filtered = FilterGroup(op="and", items=[FilterLeaf(member="region", op="equals", values=["eu"])])
    valid = _model(
        "orders",
        columns={"id": "BIGINT", "amount": "DECIMAL(12, 2)", "region": "TEXT"},
        dimensions=(region,),
        metrics=(
            Metric(name="orders", agg="count"),
            Metric(name="revenue", agg="sum", column="amount", filter=filtered),
            Metric(name="average_order", sql="orders.revenue / orders.orders"),
        ),
    )
    validate_model_graph({"orders": valid})

    with pytest.raises(SemanticPolicyError, match="requires a physical column"):
        Metric(name="broken", agg="sum")
    with pytest.raises(SemanticPolicyError, match="dimensions only"):
        validate_model_graph(
            {
                "orders": _model(
                    "orders",
                    metrics=(
                        Metric(name="orders", agg="count"),
                        Metric(
                            name="filtered",
                            agg="count",
                            filter=FilterGroup(op="and", items=[FilterLeaf(member="orders", op="gt", values=[0])]),
                        ),
                    ),
                )
            }
        )
    with pytest.raises(SemanticPolicyError, match="arithmetic only"):
        validate_model_graph({"orders": _model("orders", metrics=(Metric(name="bad", sql="sum(orders.x)"),))})

    cyclic = _model(
        "orders",
        metrics=(Metric(name="a", sql="orders.b + 1"), Metric(name="b", sql="orders.a / 2")),
    )
    with pytest.raises(SemanticPolicyError, match="cycle"):
        validate_model_graph({"orders": cyclic})


def test_composite_join_keys_and_physical_types(tmp_path: Path) -> None:
    """Verify composite join keys and physical types."""
    assert tmp_path.exists()
    relationship = Relationship(
        from_model="customers",
        to_model="orders",
        cardinality="one_to_many",
        from_columns=("tenant_id", "customer_id"),
        to_columns=("tenant_id", "customer_id"),
    )
    customers = _model(
        "customers",
        columns={"tenant_id": "BIGINT", "customer_id": "VARCHAR(36)", "segment": "TEXT"},
        primary_key=("tenant_id", "customer_id"),
        dimensions=(Dimension(name="segment", kind="categorical", column="segment"),),
        relationships=(relationship,),
    )
    orders = _model(
        "orders",
        columns={"id": "BIGINT", "tenant_id": "INTEGER", "customer_id": "TEXT"},
        metrics=(Metric(name="orders", agg="count"),),
    )
    validate_model_graph({"customers": customers, "orders": orders})

    incompatible = orders.model_copy(
        update={"columns": {"id": "BIGINT", "tenant_id": "INTEGER", "customer_id": "BOOLEAN"}}
    )
    with pytest.raises(SemanticPolicyError, match="incompatible physical types"):
        validate_model_graph({"customers": customers, "orders": incompatible})
    with pytest.raises(SemanticPolicyError, match="equally sized"):
        Relationship(
            from_model="customers",
            to_model="orders",
            cardinality="one_to_many",
            from_columns=("tenant_id", "customer_id"),
            to_columns=("customer_id",),
        )

    regions_to_customers = Relationship(
        from_model="regions",
        to_model="customers",
        cardinality="one_to_many",
        from_columns=("id",),
        to_columns=("region_id",),
    )
    regions_to_orders = Relationship(
        from_model="regions",
        to_model="orders",
        cardinality="one_to_many",
        from_columns=("id",),
        to_columns=("region_id",),
    )
    ambiguous_customers = customers.model_copy(
        update={
            "columns": {**customers.columns, "region_id": "BIGINT"},
            "relationships": (relationship, regions_to_customers),
        }
    )
    ambiguous_orders = orders.model_copy(update={"columns": {**orders.columns, "region_id": "BIGINT"}})
    regions = _model("regions", relationships=(regions_to_orders,))
    with pytest.raises(SemanticPolicyError, match="ambiguous join path"):
        validate_model_graph({"regions": regions, "customers": ambiguous_customers, "orders": ambiguous_orders})


def test_nested_snapshot_and_deterministic_digest(tmp_path: Path) -> None:
    """Verify nested snapshot and deterministic digest."""
    assert tmp_path.exists()
    columns = {"id": "BIGINT", "amount": "NUMERIC"}
    values: list[str | int | float | bool] = [10]
    filter_group = FilterGroup(op="and", items=[FilterLeaf(member="id", op="gt", values=values)])
    model = _model(
        "orders",
        columns=columns,
        dimensions=(Dimension(name="id", kind="numeric", column="id"),),
        metrics=(Metric(name="revenue", agg="sum", column="amount", filter=filter_group),),
    )
    digest = model.digest()

    columns["amount"] = "TEXT"
    values.append(20)
    filter_group.items.append(FilterLeaf(member="id", op="lt", values=[100]))
    assert model.columns["amount"] == "NUMERIC"
    assert len(model.metrics[0].filter.items) == 1
    assert model.digest() == digest
    assert model.digest() == model.model_validate(model.model_dump()).digest()
    assert len(digest) == 64

    with pytest.raises(TypeError, match="immutable"):
        model.columns["new"] = "TEXT"
    with pytest.raises(ValueError, match="frozen"):
        model.name = "changed"
    with pytest.raises(ValueError, match="frozen"):
        model.metrics[0].name = "changed"
