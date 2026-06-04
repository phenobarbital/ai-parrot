"""Unit tests for FEAT-225 Module 1 — filtering/contracts.py.

Tests cover:
- Valid model construction.
- op⇄kind validation (radius requires spatial; range requires numeric/temporal).
- Spatial kind restricts ops to radius only.
- Round-trip serialization via model_dump() / re-construction.
- FilterCondition and FilterResult basic validation.
"""
import pytest
from pydantic import ValidationError

from parrot.tools.dataset_manager.filtering import (
    FilterCondition,
    FilterDefinition,
    FilterResult,
    ValuesSource,
)


# ---------------------------------------------------------------------------
# FilterDefinition — valid cases
# ---------------------------------------------------------------------------


def test_categorical_definition_ok() -> None:
    """A categorical filter with equality ops is accepted."""
    d = FilterDefinition(
        name="region",
        columns=["region"],
        kind="categorical",
        ops=["eq", "ne", "in"],
    )
    assert d.required is False
    assert d.name == "region"
    assert d.kind == "categorical"
    assert set(d.ops) == {"eq", "ne", "in"}


def test_numeric_definition_with_range_ok() -> None:
    """A numeric filter can include the range operator."""
    d = FilterDefinition(
        name="price",
        columns=["price"],
        kind="numeric",
        ops=["range", "eq"],
    )
    assert "range" in d.ops


def test_temporal_definition_with_range_ok() -> None:
    """A temporal filter can include the range operator."""
    d = FilterDefinition(
        name="created_at",
        columns=["created_at"],
        kind="temporal",
        ops=["range"],
    )
    assert d.kind == "temporal"


def test_spatial_definition_with_radius_ok() -> None:
    """A spatial filter with radius op is accepted."""
    d = FilterDefinition(
        name="geo",
        columns=["lat", "lng"],
        kind="spatial",
        ops=["radius"],
    )
    assert d.kind == "spatial"
    assert d.ops == ["radius"]


def test_definition_with_values_source() -> None:
    """A filter definition can carry a ValuesSource."""
    vs = ValuesSource(column="region", dataset="stores")
    d = FilterDefinition(
        name="region",
        columns=["region"],
        kind="categorical",
        ops=["eq", "in"],
        values_source=vs,
    )
    assert d.values_source is not None
    assert d.values_source.column == "region"
    assert d.values_source.dataset == "stores"


def test_definition_required_flag() -> None:
    """required flag defaults to False; can be set to True."""
    d_default = FilterDefinition(
        name="x", columns=["x"], kind="categorical", ops=["eq"]
    )
    assert d_default.required is False

    d_required = FilterDefinition(
        name="x", columns=["x"], kind="categorical", ops=["eq"], required=True
    )
    assert d_required.required is True


def test_definition_optional_metadata() -> None:
    """label and description fields are stored correctly."""
    d = FilterDefinition(
        name="region",
        columns=["region"],
        kind="categorical",
        ops=["eq"],
        label="Region",
        description="Filter by geographic region.",
    )
    assert d.label == "Region"
    assert d.description == "Filter by geographic region."


# ---------------------------------------------------------------------------
# FilterDefinition — op⇄kind validation
# ---------------------------------------------------------------------------


def test_radius_requires_spatial_kind() -> None:
    """radius op is rejected when kind is not spatial."""
    with pytest.raises((ValueError, ValidationError)):
        FilterDefinition(
            name="geo",
            columns=["lat", "lng"],
            kind="categorical",
            ops=["radius"],
        )


def test_radius_requires_spatial_kind_numeric() -> None:
    """radius op is also rejected for numeric kind."""
    with pytest.raises((ValueError, ValidationError)):
        FilterDefinition(
            name="distance",
            columns=["distance"],
            kind="numeric",
            ops=["radius"],
        )


def test_range_requires_numeric_or_temporal() -> None:
    """range op is rejected for categorical kind."""
    with pytest.raises((ValueError, ValidationError)):
        FilterDefinition(
            name="r",
            columns=["region"],
            kind="categorical",
            ops=["range"],
        )


def test_range_rejected_for_text_kind() -> None:
    """range op is rejected for text kind."""
    with pytest.raises((ValueError, ValidationError)):
        FilterDefinition(
            name="notes",
            columns=["notes"],
            kind="text",
            ops=["range"],
        )


def test_range_rejected_for_spatial_kind() -> None:
    """range op is rejected for spatial kind (spatial uses radius only)."""
    with pytest.raises((ValueError, ValidationError)):
        FilterDefinition(
            name="geo",
            columns=["lat", "lng"],
            kind="spatial",
            ops=["range"],
        )


def test_spatial_kind_disallows_equality_ops() -> None:
    """spatial kind only allows radius; eq/in/etc. are rejected."""
    with pytest.raises((ValueError, ValidationError)):
        FilterDefinition(
            name="geo",
            columns=["lat", "lng"],
            kind="spatial",
            ops=["eq"],
        )


def test_spatial_kind_disallows_mixed_ops() -> None:
    """spatial kind rejects a mix of radius and equality operators."""
    with pytest.raises((ValueError, ValidationError)):
        FilterDefinition(
            name="geo",
            columns=["lat", "lng"],
            kind="spatial",
            ops=["radius", "eq"],
        )


# ---------------------------------------------------------------------------
# FilterDefinition — Pydantic validation errors
# ---------------------------------------------------------------------------


def test_empty_columns_rejected() -> None:
    """columns list must have at least one entry."""
    with pytest.raises((ValueError, ValidationError)):
        FilterDefinition(
            name="x",
            columns=[],
            kind="categorical",
            ops=["eq"],
        )


def test_empty_ops_rejected() -> None:
    """ops list must have at least one entry."""
    with pytest.raises((ValueError, ValidationError)):
        FilterDefinition(
            name="x",
            columns=["x"],
            kind="categorical",
            ops=[],
        )


# ---------------------------------------------------------------------------
# Round-trip serialization
# ---------------------------------------------------------------------------


def test_roundtrip_categorical() -> None:
    """Categorical FilterDefinition survives model_dump() + re-construction."""
    d = FilterDefinition(
        name="region",
        columns=["region"],
        kind="categorical",
        ops=["eq", "ne", "in", "not_in"],
        required=True,
        label="Region",
    )
    assert FilterDefinition(**d.model_dump()) == d


def test_roundtrip_spatial() -> None:
    """Spatial FilterDefinition with radius survives round-trip."""
    d = FilterDefinition(
        name="geo",
        columns=["lat", "lng"],
        kind="spatial",
        ops=["radius"],
    )
    assert FilterDefinition(**d.model_dump()) == d


def test_roundtrip_with_values_source() -> None:
    """FilterDefinition with ValuesSource survives round-trip."""
    d = FilterDefinition(
        name="region",
        columns=["region"],
        kind="categorical",
        ops=["in"],
        values_source=ValuesSource(column="region", dataset="stores"),
    )
    reconstructed = FilterDefinition(**d.model_dump())
    assert reconstructed == d
    assert reconstructed.values_source is not None
    assert reconstructed.values_source.column == "region"


# ---------------------------------------------------------------------------
# FilterCondition
# ---------------------------------------------------------------------------


def test_filter_condition_eq() -> None:
    """FilterCondition with eq op and scalar value is valid."""
    c = FilterCondition(op="eq", value="North")
    assert c.op == "eq"
    assert c.value == "North"


def test_filter_condition_range() -> None:
    """FilterCondition with range op and dict value is valid."""
    c = FilterCondition(op="range", value={"min": 10, "max": 50})
    assert c.op == "range"
    assert c.value["min"] == 10


def test_filter_condition_in_list() -> None:
    """FilterCondition with in op and list value is valid."""
    c = FilterCondition(op="in", value=["North", "South"])
    assert c.value == ["North", "South"]


def test_filter_condition_no_value() -> None:
    """FilterCondition with no value defaults to None."""
    c = FilterCondition(op="eq")
    assert c.value is None


# ---------------------------------------------------------------------------
# FilterResult
# ---------------------------------------------------------------------------


def test_filter_result_defaults() -> None:
    """FilterResult has empty lists by default."""
    r = FilterResult()
    assert r.applied == []
    assert r.skipped == []


def test_filter_result_with_data() -> None:
    """FilterResult stores applied and skipped dataset names."""
    r = FilterResult(applied=["stores", "sites"], skipped=["weather"])
    assert "stores" in r.applied
    assert "weather" in r.skipped


def test_filter_result_roundtrip() -> None:
    """FilterResult survives model_dump() + re-construction."""
    r = FilterResult(applied=["a", "b"], skipped=["c"])
    assert FilterResult(**r.model_dump()) == r


# ---------------------------------------------------------------------------
# ValuesSource
# ---------------------------------------------------------------------------


def test_values_source_all_optional() -> None:
    """ValuesSource can be constructed with no arguments."""
    vs = ValuesSource()
    assert vs.query_slug is None
    assert vs.column is None
    assert vs.dataset is None


def test_values_source_query_slug() -> None:
    """ValuesSource accepts a query_slug."""
    vs = ValuesSource(query_slug="regions_query")
    assert vs.query_slug == "regions_query"
