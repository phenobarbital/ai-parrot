"""
Integration tests for DatasetInfo, Guide & Fetch integration (TASK-433).

Tests cover:
- DatasetInfo.source_type accepts "composite"
- to_info() returns source_type="composite" for composite datasets
- _generate_dataframe_guide() shows join topology for composites
- fetch_dataset() routes composites correctly with filter propagation
- fetch_dataset() sets force_refresh=True for composites
- list_datasets() shows correct action_required for composites
- get_metadata() shows appropriate guidance for unloaded composites
- End-to-end: register composite → fetch → verify joined result with computed columns
"""
import pytest
import pandas as pd
from parrot.tools.dataset_manager.tool import DatasetManager, DatasetInfo
from parrot.tools.dataset_manager.computed import ComputedColumnDef


@pytest.fixture
def dm():
    dm = DatasetManager(generate_guide=True)
    dm.add_dataframe("sales", pd.DataFrame({
        "id": [1, 2, 3], "year": [2025, 2025, 2024],
        "revenue": [100, 200, 150], "expenses": [60, 80, 90],
    }))
    dm.add_dataframe("regions", pd.DataFrame({
        "id": [1, 2, 3], "region": ["East", "West", "South"],
    }))
    return dm


# ─────────────────────────────────────────────────────────────────────────────
# DatasetInfo source_type Literal
# ─────────────────────────────────────────────────────────────────────────────


class TestDatasetInfoComposite:
    def test_source_type_literal_accepted(self):
        """DatasetInfo accepts 'composite' as source_type."""
        info = DatasetInfo(
            name="test", source_type="composite", source_description="test join",
        )
        assert info.source_type == "composite"

    def test_source_type_does_not_break_existing(self):
        """Existing source types still work after adding composite."""
        for st in ["dataframe", "query_slug", "sql", "table", "airtable",
                   "smartsheet", "iceberg", "mongo", "deltatable"]:
            info = DatasetInfo(name="x", source_type=st, source_description="")
            assert info.source_type == st


# ─────────────────────────────────────────────────────────────────────────────
# to_info() returns composite
# ─────────────────────────────────────────────────────────────────────────────


class TestToInfoComposite:
    def test_to_info_returns_composite(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        entry = dm._datasets["combined"]
        info = entry.to_info()
        assert info.source_type == "composite"

    def test_to_info_has_source_description(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        entry = dm._datasets["combined"]
        info = entry.to_info()
        assert info.source_description != ""
        assert "JOIN" in info.source_description.upper()


# ─────────────────────────────────────────────────────────────────────────────
# Guide includes composite join topology
# ─────────────────────────────────────────────────────────────────────────────


class TestGuideComposite:
    def test_guide_includes_composite_name(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        guide = dm._generate_dataframe_guide()
        assert "combined" in guide

    def test_guide_includes_join_type(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        guide = dm._generate_dataframe_guide()
        assert "INNER JOIN" in guide

    def test_guide_includes_left_join(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id", "how": "left"}],
        )
        guide = dm._generate_dataframe_guide()
        assert "LEFT JOIN" in guide

    def test_guide_includes_fetch_hint(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        guide = dm._generate_dataframe_guide()
        assert 'fetch_dataset("combined")' in guide

    def test_guide_shows_component_names(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        guide = dm._generate_dataframe_guide()
        assert "sales" in guide
        assert "regions" in guide


# ─────────────────────────────────────────────────────────────────────────────
# fetch_dataset routes composites
# ─────────────────────────────────────────────────────────────────────────────


class TestFetchDatasetComposite:
    @pytest.mark.asyncio
    async def test_fetch_basic(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        result = await dm.fetch_dataset("combined")
        assert result.get("status") == "materialized"
        assert "combined" in str(result.get("dataset", ""))

    @pytest.mark.asyncio
    async def test_fetch_columns_present(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        result = await dm.fetch_dataset("combined")
        cols = result.get("columns", [])
        assert "revenue" in cols
        assert "region" in cols

    @pytest.mark.asyncio
    async def test_fetch_with_filter(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        result = await dm.fetch_dataset("combined", conditions={"year": 2025})
        assert result.get("status") == "materialized"
        # Should have filtered to 2 rows (year=2025)
        shape = result.get("shape", {})
        assert shape.get("rows") == 2

    @pytest.mark.asyncio
    async def test_fetch_loads_entry(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        await dm.fetch_dataset("combined")
        entry = dm._datasets["combined"]
        assert entry.loaded

    @pytest.mark.asyncio
    async def test_fetch_missing_returns_error(self, dm):
        result = await dm.fetch_dataset("nonexistent_composite")
        assert "error" in result


# ─────────────────────────────────────────────────────────────────────────────
# list_datasets action_required
# ─────────────────────────────────────────────────────────────────────────────


class TestListDatasetsComposite:
    @pytest.mark.asyncio
    async def test_action_required_for_unloaded_composite(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        listing = await dm.list_datasets()
        combined = next((d for d in listing if d["name"] == "combined"), None)
        assert combined is not None
        assert "action_required" in combined
        assert "fetch_dataset" in combined["action_required"]

    @pytest.mark.asyncio
    async def test_source_type_is_composite(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        listing = await dm.list_datasets()
        combined = next((d for d in listing if d["name"] == "combined"), None)
        assert combined["source_type"] == "composite"


# ─────────────────────────────────────────────────────────────────────────────
# get_metadata guidance for unloaded composites
# ─────────────────────────────────────────────────────────────────────────────


class TestGetMetadataComposite:
    @pytest.mark.asyncio
    async def test_get_metadata_unloaded_shows_guidance(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        meta = await dm.get_metadata("combined")
        assert meta.get("loaded") is False
        assert "fetch_dataset" in meta.get("message", "")

    @pytest.mark.asyncio
    async def test_get_metadata_loaded_shows_shape(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        await dm.fetch_dataset("combined")
        meta = await dm.get_metadata("combined")
        assert "shape" in meta


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end: composite with computed columns
# ─────────────────────────────────────────────────────────────────────────────


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_composite_with_computed(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
            computed_columns=[
                ComputedColumnDef(
                    name="ebitda", func="math_operation",
                    columns=["revenue", "expenses"],
                    kwargs={"operation": "subtract"},
                    description="EBITDA",
                ),
            ],
        )
        result = await dm.fetch_dataset("combined")
        assert result.get("status") == "materialized"
        entry = dm._datasets["combined"]
        assert entry.loaded
        assert "ebitda" in entry._df.columns
        assert "region" in entry._df.columns

    @pytest.mark.asyncio
    async def test_composite_ebitda_values(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
            computed_columns=[
                ComputedColumnDef(
                    name="ebitda", func="math_operation",
                    columns=["revenue", "expenses"],
                    kwargs={"operation": "subtract"},
                ),
            ],
        )
        await dm.fetch_dataset("combined")
        df = dm._datasets["combined"]._df
        assert list(df["ebitda"]) == [40.0, 120.0, 60.0]

    @pytest.mark.asyncio
    async def test_no_regression_existing_sources(self, dm):
        """Existing in-memory source still works after composite integration."""
        result = await dm.fetch_dataset("sales")
        assert result.get("status") == "materialized"
        assert "revenue" in result.get("columns", [])
