"""
Unit tests for CompositeDataSource (TASK-431).

Tests cover:
- JoinSpec model validation
- CompositeDataSource single JOIN
- Chained JOINs (A → B → C)
- Filter propagation (applied only to components with matching column)
- Missing component raises ValueError
- Missing join column raises ValueError
- has_builtin_cache returns True
- describe() returns human-readable join description
"""
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock

from parrot.tools.dataset_manager.sources.composite import JoinSpec, CompositeDataSource


@pytest.fixture
def mock_dm():
    """Mock DatasetManager with two datasets."""
    dm = MagicMock()

    df_history = pd.DataFrame({
        "kiosk_id": [1, 2, 3],
        "year": [2025, 2025, 2024],
        "revenue": [100.0, 200.0, 150.0],
    })
    df_locations = pd.DataFrame({
        "kiosk_id": [1, 2, 3],
        "city": ["Miami", "NYC", "LA"],
    })

    async def mock_materialize(name, **kw):
        dfs = {
            "history": df_history.copy(),
            "locations": df_locations.copy(),
        }
        if name not in dfs:
            raise ValueError(f"Dataset '{name}' not found")
        return dfs[name]

    dm.materialize = mock_materialize

    # Mock _apply_filter
    def apply_filter(df, filters):
        for k, v in filters.items():
            if isinstance(v, (list, tuple, set)):
                df = df[df[k].isin(v)]
            else:
                df = df[df[k] == v]
        return df.reset_index(drop=True)

    dm._apply_filter = apply_filter

    # Mock _datasets for column introspection
    entry_history = MagicMock()
    entry_history.columns = ["kiosk_id", "year", "revenue"]
    entry_history._computed_columns = []
    entry_locations = MagicMock()
    entry_locations.columns = ["kiosk_id", "city"]
    entry_locations._computed_columns = []
    dm._datasets = {
        "history": entry_history,
        "locations": entry_locations,
    }
    return dm


@pytest.fixture
def composite_source(mock_dm):
    joins = [JoinSpec(left="history", right="locations", on="kiosk_id", how="inner")]
    return CompositeDataSource(
        name="combined",
        joins=joins,
        dataset_manager=mock_dm,
        description="Test composite",
    )


# ─────────────────────────────────────────────────────────────────────────────
# JoinSpec model
# ─────────────────────────────────────────────────────────────────────────────


class TestJoinSpec:
    def test_basic_creation(self):
        j = JoinSpec(left="a", right="b", on="id")
        assert j.how == "inner"
        assert j.suffixes == ("", "_right")
        assert j.on == "id"

    def test_list_on(self):
        j = JoinSpec(left="a", right="b", on=["id1", "id2"])
        assert j.on == ["id1", "id2"]

    def test_left_join(self):
        j = JoinSpec(left="a", right="b", on="id", how="left")
        assert j.how == "left"

    def test_custom_suffixes(self):
        j = JoinSpec(left="a", right="b", on="id", suffixes=("_l", "_r"))
        assert j.suffixes == ("_l", "_r")


# ─────────────────────────────────────────────────────────────────────────────
# CompositeDataSource
# ─────────────────────────────────────────────────────────────────────────────


class TestCompositeDataSource:
    def test_component_names(self, composite_source):
        assert composite_source.component_names == {"history", "locations"}

    def test_has_builtin_cache(self, composite_source):
        assert composite_source.has_builtin_cache is True

    def test_cache_key(self, composite_source):
        assert composite_source.cache_key == "composite:combined"

    def test_describe(self, composite_source):
        desc = composite_source.describe()
        assert "INNER JOIN" in desc
        assert "history" in desc
        assert "locations" in desc

    def test_describe_shows_on_column(self, composite_source):
        desc = composite_source.describe()
        assert "kiosk_id" in desc

    @pytest.mark.asyncio
    async def test_single_join(self, composite_source):
        result = await composite_source.fetch()
        assert "kiosk_id" in result.columns
        assert "revenue" in result.columns
        assert "city" in result.columns
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_filter_propagation_by_year(self, composite_source):
        """Filter on 'year' applies only to history (which has year column)."""
        result = await composite_source.fetch(filter={"year": 2025})
        # Only 2 rows have year=2025
        assert len(result) == 2
        assert all(result["year"] == 2025)

    @pytest.mark.asyncio
    async def test_filter_propagation_by_city(self, composite_source):
        """Filter on 'city' applies only to locations (which has city column)."""
        result = await composite_source.fetch(filter={"city": "Miami"})
        assert len(result) == 1
        assert result["city"].iloc[0] == "Miami"

    @pytest.mark.asyncio
    async def test_filter_no_error_for_missing_column(self, composite_source):
        """Filter on column that doesn't exist in any component is silently skipped."""
        # The filter is just not applied to either component
        result = await composite_source.fetch(filter={"nonexistent_col": "value"})
        # Result is unfiltered join
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_missing_component_raises(self, mock_dm):
        """Missing component dataset raises ValueError."""
        joins = [JoinSpec(left="history", right="missing_dataset", on="kiosk_id")]
        source = CompositeDataSource(
            name="bad", joins=joins, dataset_manager=mock_dm,
        )
        # Remove 'missing_dataset' from _datasets (it doesn't exist)
        with pytest.raises(ValueError, match="not found"):
            await source.fetch()

    @pytest.mark.asyncio
    async def test_missing_join_column_raises(self, mock_dm):
        """Missing join column raises ValueError."""
        joins = [JoinSpec(left="history", right="locations", on="nonexistent_col")]
        source = CompositeDataSource(
            name="bad", joins=joins, dataset_manager=mock_dm,
        )
        with pytest.raises(ValueError, match="not found"):
            await source.fetch()

    @pytest.mark.asyncio
    async def test_describe_default(self, mock_dm):
        """describe() works without explicit description."""
        joins = [JoinSpec(left="history", right="locations", on="kiosk_id")]
        source = CompositeDataSource(
            name="test", joins=joins, dataset_manager=mock_dm,
        )
        desc = source.describe()
        assert "test" in desc or "history" in desc

    @pytest.mark.asyncio
    async def test_chained_joins(self):
        """Three datasets joined in sequence: A → B → C."""
        dm = MagicMock()

        df_a = pd.DataFrame({"id": [1, 2], "val_a": ["x", "y"]})
        df_b = pd.DataFrame({"id": [1, 2], "val_b": ["p", "q"]})
        df_c = pd.DataFrame({"id": [1, 2], "val_c": [10, 20]})

        async def mock_mat(name, **kw):
            return {"a": df_a.copy(), "b": df_b.copy(), "c": df_c.copy()}[name]

        dm.materialize = mock_mat

        entry_a = MagicMock()
        entry_a.columns = ["id", "val_a"]
        entry_b = MagicMock()
        entry_b.columns = ["id", "val_b"]
        entry_c = MagicMock()
        entry_c.columns = ["id", "val_c"]
        dm._datasets = {"a": entry_a, "b": entry_b, "c": entry_c}
        dm._apply_filter = lambda df, f: df

        joins = [
            JoinSpec(left="a", right="b", on="id"),
            JoinSpec(left="b", right="c", on="id"),
        ]
        source = CompositeDataSource(name="chain", joins=joins, dataset_manager=dm)
        result = await source.fetch()

        assert "val_a" in result.columns
        assert "val_b" in result.columns
        assert "val_c" in result.columns
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_exported_from_init(self):
        """CompositeDataSource is exported from sources/__init__.py."""
        from parrot.tools.dataset_manager.sources import CompositeDataSource as CDS, JoinSpec as JS
        assert CDS is CompositeDataSource
        assert JS is JoinSpec
