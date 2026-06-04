"""Unit tests for FEAT-225 Module 6 — get_filter_schema() + suggest_filters().

Tests cover:
- get_filter_schema() serializes the defined filter catalog.
- get_filter_schema() includes per-filter dataset applicability.
- Datasets without the column are excluded from schema 'datasets' list.
- suggest_filters() proposes from column introspection.
- suggest_filters() does NOT mutate _filter_defs (no side effects).
- Suggestion kinds: categorical, numeric, temporal, spatial.
"""
import pytest
import pandas as pd

from parrot.tools.dataset_manager.filtering import FilterDefinition
from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile
from parrot.tools.dataset_manager.spatial.registry import (
    SPATIAL_PROFILE_REGISTRY,
    register_spatial_profile,
)
from parrot.tools.dataset_manager.tool import DatasetEntry, DatasetManager


# ---------------------------------------------------------------------------
# Helpers + Fixtures
# ---------------------------------------------------------------------------


def _entry(df: pd.DataFrame) -> DatasetEntry:
    return DatasetEntry(name="test", df=df)


@pytest.fixture()
def clean_spatial_registry():
    SPATIAL_PROFILE_REGISTRY.clear()
    yield
    SPATIAL_PROFILE_REGISTRY.clear()


@pytest.fixture()
def manager_with_three_datasets():
    """stores+sites have region (Categorical dtype → 'categorical'); weather does not."""
    dm = DatasetManager()
    # Use pd.Categorical so categorize_columns returns 'categorical'
    dm._datasets["stores"] = _entry(pd.DataFrame({
        "region": pd.Categorical(["North"] * 8 + ["South"] * 5),
        "revenue": list(range(13)),
    }))
    dm._datasets["sites"] = _entry(pd.DataFrame({
        "region": pd.Categorical(["North"] * 6 + ["East"] * 4),
        "active": [True] * 10,
    }))
    dm._datasets["weather"] = _entry(pd.DataFrame({
        "temp": [float(i) for i in range(10)],
    }))
    return dm


# ---------------------------------------------------------------------------
# get_filter_schema()
# ---------------------------------------------------------------------------


def test_schema_lists_defined_filters(manager_with_three_datasets) -> None:
    """get_filter_schema returns one entry per defined filter."""
    dm = manager_with_three_datasets
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"], kind="categorical", ops=["in"]),
    ])
    schema = dm.get_filter_schema()
    assert len(schema) == 1
    assert schema[0]["name"] == "region"


def test_schema_lists_applicable_datasets(manager_with_three_datasets) -> None:
    """get_filter_schema includes datasets that have the column."""
    dm = manager_with_three_datasets
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"], kind="categorical", ops=["in"]),
    ])
    schema = dm.get_filter_schema()
    entry = next(e for e in schema if e["name"] == "region")
    assert "stores" in entry["datasets"]
    assert "sites" in entry["datasets"]


def test_schema_excludes_dataset_missing_column(manager_with_three_datasets) -> None:
    """get_filter_schema excludes datasets that lack the column."""
    dm = manager_with_three_datasets
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"], kind="categorical", ops=["in"]),
    ])
    schema = dm.get_filter_schema()
    entry = next(e for e in schema if e["name"] == "region")
    assert "weather" not in entry["datasets"]


def test_schema_multiple_filters(manager_with_three_datasets) -> None:
    """get_filter_schema returns entries for all defined filters."""
    dm = manager_with_three_datasets
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"], kind="categorical", ops=["eq"]),
        FilterDefinition(name="revenue", columns=["revenue"], kind="numeric", ops=["range"]),
    ])
    schema = dm.get_filter_schema()
    names = [e["name"] for e in schema]
    assert "region" in names
    assert "revenue" in names


def test_schema_contains_required_fields(manager_with_three_datasets) -> None:
    """Schema entries include name, kind, ops, label, required, datasets, columns."""
    dm = manager_with_three_datasets
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"], kind="categorical",
                         ops=["in"], required=True, label="Region Label"),
    ])
    schema = dm.get_filter_schema()
    entry = schema[0]
    assert "name" in entry
    assert "kind" in entry
    assert "ops" in entry
    assert "required" in entry
    assert "datasets" in entry
    assert "columns" in entry
    assert entry["required"] is True
    assert entry["label"] == "Region Label"


def test_schema_empty_when_no_filters_defined() -> None:
    """get_filter_schema returns empty list when no filters are defined."""
    dm = DatasetManager()
    assert dm.get_filter_schema() == []


# ---------------------------------------------------------------------------
# suggest_filters()
# ---------------------------------------------------------------------------


def test_suggest_filters_no_side_effects(manager_with_three_datasets) -> None:
    """suggest_filters does not mutate _filter_defs."""
    dm = manager_with_three_datasets
    before = dict(dm._filter_defs)
    proposals = dm.suggest_filters()
    assert dm._filter_defs == before
    assert isinstance(proposals, list)


def test_suggest_filters_proposes_categorical(manager_with_three_datasets) -> None:
    """suggest_filters proposes categorical kind for region column."""
    dm = manager_with_three_datasets
    proposals = dm.suggest_filters()
    region_props = [p for p in proposals if "region" in p.columns]
    assert len(region_props) > 0
    assert region_props[0].kind == "categorical"


def test_suggest_filters_proposes_numeric(manager_with_three_datasets) -> None:
    """suggest_filters proposes numeric kind for revenue column."""
    dm = manager_with_three_datasets
    proposals = dm.suggest_filters()
    revenue_props = [p for p in proposals if "revenue" in p.columns]
    assert len(revenue_props) > 0
    assert revenue_props[0].kind == "numeric"


def test_suggest_filters_no_proposals_for_unloaded() -> None:
    """suggest_filters returns empty list when no datasets are loaded."""
    dm = DatasetManager()
    assert dm.suggest_filters() == []


def test_suggest_filters_categorical_ops(manager_with_three_datasets) -> None:
    """Categorical suggestions include eq/ne/in/not_in operators."""
    dm = manager_with_three_datasets
    proposals = dm.suggest_filters()
    region_props = [p for p in proposals if "region" in p.columns]
    assert len(region_props) > 0
    ops_set = set(region_props[0].ops)
    assert "eq" in ops_set
    assert "in" in ops_set


def test_suggest_filters_numeric_ops(manager_with_three_datasets) -> None:
    """Numeric suggestions include range operator."""
    dm = manager_with_three_datasets
    proposals = dm.suggest_filters()
    revenue_props = [p for p in proposals if "revenue" in p.columns]
    assert len(revenue_props) > 0
    assert "range" in revenue_props[0].ops


def test_suggest_filters_spatial(clean_spatial_registry) -> None:
    """suggest_filters proposes spatial kind for datasets with spatial profiles."""
    dm = DatasetManager()
    df = pd.DataFrame({"lat": [1.0, 2.0], "lng": [3.0, 4.0]})
    dm._datasets["geo"] = _entry(df)
    register_spatial_profile(DatasetSpatialProfile(
        dataset="geo", lat_col="lat", lng_col="lng", layer="geo", property_cols=[]
    ))
    proposals = dm.suggest_filters()
    spatial_props = [p for p in proposals if p.kind == "spatial"]
    assert len(spatial_props) > 0
    assert "radius" in spatial_props[0].ops


def test_suggest_filters_min_datasets_threshold() -> None:
    """min_datasets=2 only suggests columns present in at least 2 datasets."""
    dm = DatasetManager()
    # Use pd.Categorical so categorize_columns returns 'categorical'
    dm._datasets["ds1"] = _entry(pd.DataFrame(
        {"region": pd.Categorical(["A"] * 8 + ["B"] * 7)}
    ))
    dm._datasets["ds2"] = _entry(pd.DataFrame(
        {"region": pd.Categorical(["B"] * 6 + ["C"] * 4),
         "unique_col": list(range(10))}
    ))
    proposals = dm.suggest_filters(min_datasets=2)
    proposal_cols = [col for p in proposals for col in p.columns]
    assert "region" in proposal_cols
    # unique_col is only in 1 dataset; revenue is integer but only in 1 dataset
    assert "unique_col" not in proposal_cols
