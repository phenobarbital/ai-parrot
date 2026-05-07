"""Unit tests for DatasetManager PBAC policy filtering (TASK-1046).

Tests verify that DatasetManager correctly integrates DatasetPolicyGuard to
enforce dataset-level and column-level access control at six enforcement
points: get_tools_filtered, list_datasets, get_active, get_metadata (both
loaded and unloaded paths), fetch_dataset, and _pre_execute.

Drop-silent semantics: denied datasets/columns are simply absent from the
response — no 'permission_denied' field, no warning, no marker.
"""
from __future__ import annotations

import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.dataset_guard import DatasetPolicyGuard
from parrot.auth.exceptions import AuthorizationRequired
from parrot.tools.dataset_manager.tool import DatasetManager, DatasetEntry, DatasetInfo


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_guard():
    """Mock DatasetPolicyGuard with configurable allow/deny.

    All guard methods default to fully-permissive (allow everything).
    Override per-test as needed.
    """
    guard = MagicMock(spec=DatasetPolicyGuard)
    # Default: allow all datasets
    guard.filter_datasets = AsyncMock(side_effect=lambda pctx, names: set(names))
    # Default: allow all columns (return input list unchanged)
    guard.filter_columns = AsyncMock(side_effect=lambda pctx, dataset, cols: list(cols))
    # Default: allow all reads
    guard.can_read_dataset = AsyncMock(return_value=True)
    return guard


@pytest.fixture
def pctx_jleon():
    """PermissionContext for jleon@trocglobal.com."""
    return PermissionContext(
        session=UserSession(
            user_id="jleon@trocglobal.com",
            tenant_id="troc",
            roles=frozenset(),
            metadata={},
        )
    )


@pytest.fixture
def sample_df():
    """Sample DataFrame with 4 columns for policy filtering tests."""
    return pd.DataFrame({
        "id": [1, 2, 3],
        "name": ["Alice", "Bob", "Charlie"],
        "salary": [100_000, 200_000, 150_000],
        "profit_margin": [0.25, 0.30, 0.22],
    })


@pytest.fixture
def dm_with_guard(mock_guard, sample_df):
    """DatasetManager pre-loaded with one dataset, with a policy guard."""
    dm = DatasetManager(policy_guard=mock_guard)
    dm.add_dataframe("financial_data", sample_df)
    return dm


@pytest.fixture
def dm_no_guard(sample_df):
    """DatasetManager pre-loaded with one dataset, WITHOUT a policy guard."""
    dm = DatasetManager()
    dm.add_dataframe("financial_data", sample_df)
    return dm


# ─────────────────────────────────────────────────────────────────────────────
# Test: no-guard baseline behaviour unchanged
# ─────────────────────────────────────────────────────────────────────────────


class TestDatasetManagerNoGuard:
    """When policy_guard=None, all existing behaviour is unchanged."""

    @pytest.mark.asyncio
    async def test_list_datasets_returns_all(self, dm_no_guard):
        """list_datasets returns all datasets when no guard is configured."""
        results = await dm_no_guard.list_datasets()
        names = [r["name"] for r in results]
        assert "financial_data" in names

    @pytest.mark.asyncio
    async def test_get_active_returns_all(self, dm_no_guard):
        """get_active returns all active datasets when no guard is configured."""
        active = await dm_no_guard.get_active()
        assert "financial_data" in active

    @pytest.mark.asyncio
    async def test_get_metadata_returns_all_columns(self, dm_no_guard):
        """get_metadata returns all columns when no guard is configured."""
        meta = await dm_no_guard.get_metadata("financial_data")
        assert "profit_margin" in meta["columns"]
        assert "salary" in meta["columns"]

    @pytest.mark.asyncio
    async def test_fetch_dataset_returns_all_columns(self, dm_no_guard):
        """fetch_dataset returns all columns when no guard is configured."""
        result = await dm_no_guard.fetch_dataset("financial_data")
        assert "profit_margin" in result["columns"]
        assert "salary" in result["columns"]

    @pytest.mark.asyncio
    async def test_guard_methods_never_called(self, sample_df):
        """When guard is None, guard methods are never invoked."""
        dm = DatasetManager(policy_guard=None)
        dm.add_dataframe("test", sample_df)
        # Just verify calls succeed without touching any guard
        await dm.list_datasets()
        await dm.get_active()
        await dm.get_metadata("test")


# ─────────────────────────────────────────────────────────────────────────────
# Test: dataset-level filtering (list_datasets, get_active, get_tools_filtered)
# ─────────────────────────────────────────────────────────────────────────────


class TestDatasetLevelFiltering:
    """Tests for dataset-level deny (full dataset hidden)."""

    @pytest.mark.asyncio
    async def test_list_datasets_drops_denied(
        self, mock_guard, pctx_jleon, sample_df
    ):
        """Mock guard denies 'financial_data'; list_datasets excludes it."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)
        dm.add_dataframe("public_data", pd.DataFrame({"x": [1, 2]}))

        # financial_data is denied; only public_data is allowed
        mock_guard.filter_datasets.side_effect = (
            lambda pctx, names: {"public_data"} if "public_data" in names else set()
        )
        dm._current_pctx = pctx_jleon

        results = await dm.list_datasets()
        names = [r["name"] for r in results]

        assert "financial_data" not in names
        assert "public_data" in names

    @pytest.mark.asyncio
    async def test_list_available_delegates_to_list_datasets(
        self, mock_guard, pctx_jleon, sample_df
    ):
        """list_available delegates to list_datasets (verify PBAC filtering)."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)
        mock_guard.filter_datasets.side_effect = (
            lambda pctx, names: set()  # deny all
        )
        dm._current_pctx = pctx_jleon

        via_list_datasets = await dm.list_datasets()
        via_list_available = await dm.list_available()

        assert via_list_datasets == via_list_available

    @pytest.mark.asyncio
    async def test_get_active_drops_denied(
        self, mock_guard, pctx_jleon, sample_df
    ):
        """Mock guard denies 'financial_data'; get_active excludes it."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)
        dm.add_dataframe("public_data", pd.DataFrame({"x": [1, 2]}))

        mock_guard.filter_datasets.side_effect = (
            lambda pctx, names: {"public_data"} if "public_data" in names else set()
        )
        dm._current_pctx = pctx_jleon

        active = await dm.get_active()

        assert "financial_data" not in active
        assert "public_data" in active

    @pytest.mark.asyncio
    async def test_get_tools_filtered_calls_guard(
        self, mock_guard, pctx_jleon, sample_df
    ):
        """get_tools_filtered invokes filter_datasets when guard is configured."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)

        mock_resolver = MagicMock()
        mock_resolver.filter_tools = AsyncMock(side_effect=lambda pctx, tools: tools)

        await dm.get_tools_filtered(pctx_jleon, mock_resolver)

        mock_guard.filter_datasets.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_tools_filtered_no_guard_skips(
        self, pctx_jleon, sample_df
    ):
        """When guard is None, filter_datasets is never called."""
        dm = DatasetManager(policy_guard=None)
        dm.add_dataframe("financial_data", sample_df)

        mock_resolver = MagicMock()
        mock_resolver.filter_tools = AsyncMock(side_effect=lambda pctx, tools: tools)

        # Should not raise, should not call any guard
        tools = await dm.get_tools_filtered(pctx_jleon, mock_resolver)
        assert isinstance(tools, list)

    @pytest.mark.asyncio
    async def test_list_datasets_no_pctx_allows_all(
        self, mock_guard, sample_df
    ):
        """When _current_pctx is None (no context), no filtering is applied."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)
        dm._current_pctx = None  # explicitly no context

        results = await dm.list_datasets()
        names = [r["name"] for r in results]

        assert "financial_data" in names
        # Guard should NOT be called when pctx is None
        mock_guard.filter_datasets.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Test: column-level filtering — get_metadata (loaded path)
# ─────────────────────────────────────────────────────────────────────────────


class TestColumnFilteringGetMetadata:
    """Tests for column-level filtering in get_metadata."""

    @pytest.mark.asyncio
    async def test_get_metadata_drops_denied_columns(
        self, mock_guard, pctx_jleon, sample_df
    ):
        """Mock guard denies 'profit_margin'; get_metadata excludes it."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)

        allowed = ["id", "name", "salary"]
        mock_guard.filter_columns.side_effect = (
            lambda pctx, dataset, cols: [c for c in cols if c in allowed]
        )
        dm._current_pctx = pctx_jleon

        meta = await dm.get_metadata("financial_data")

        assert "profit_margin" not in meta["columns"]
        assert "salary" in meta["columns"]
        assert "id" in meta["columns"]

    @pytest.mark.asyncio
    async def test_column_types_trimmed_in_lockstep(
        self, mock_guard, pctx_jleon, sample_df
    ):
        """columns and column_types are filtered together (lockstep)."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)

        allowed = ["id", "name"]
        mock_guard.filter_columns.side_effect = (
            lambda pctx, dataset, cols: [c for c in cols if c in allowed]
        )
        dm._current_pctx = pctx_jleon

        meta = await dm.get_metadata("financial_data")

        # Both columns and column_types must be consistent
        col_keys = set(meta["columns"].keys()) if isinstance(meta["columns"], dict) else set(meta["columns"])
        ct_keys = set(meta.get("column_types", {}).keys()) if meta.get("column_types") else set()

        # All keys in column_types must exist in columns
        assert ct_keys <= col_keys, f"column_types keys {ct_keys} exceed columns {col_keys}"
        # Denied columns must be absent from both
        assert "profit_margin" not in col_keys
        assert "profit_margin" not in ct_keys

    @pytest.mark.asyncio
    async def test_sample_rows_filtered_with_columns(
        self, mock_guard, pctx_jleon, sample_df
    ):
        """sample_rows in get_metadata also have denied columns stripped."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)

        allowed = ["id", "name"]
        mock_guard.filter_columns.side_effect = (
            lambda pctx, dataset, cols: [c for c in cols if c in allowed]
        )
        dm._current_pctx = pctx_jleon

        meta = await dm.get_metadata(
            "financial_data", include_samples=True
        )

        if "sample_rows" in meta:
            for row in meta["sample_rows"]:
                assert "profit_margin" not in row, (
                    f"sample_rows contain denied column 'profit_margin': {row}"
                )

    @pytest.mark.asyncio
    async def test_shape_updated_after_filtering(
        self, mock_guard, pctx_jleon, sample_df
    ):
        """shape['columns'] reflects filtered count, not original count."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)

        allowed = ["id", "name"]  # only 2 of 4 columns allowed
        mock_guard.filter_columns.side_effect = (
            lambda pctx, dataset, cols: [c for c in cols if c in allowed]
        )
        dm._current_pctx = pctx_jleon

        meta = await dm.get_metadata("financial_data")

        if "shape" in meta:
            assert meta["shape"]["columns"] == 2, (
                f"Expected shape.columns=2 after filtering; got {meta['shape']['columns']}"
            )

    @pytest.mark.asyncio
    async def test_drop_silent_no_error_signal(
        self, mock_guard, pctx_jleon, sample_df
    ):
        """No 'permission_denied' field or any redaction marker in output."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)

        mock_guard.filter_columns.side_effect = (
            lambda pctx, dataset, cols: [c for c in cols if c != "profit_margin"]
        )
        dm._current_pctx = pctx_jleon

        meta = await dm.get_metadata("financial_data")

        assert "permission_denied" not in meta
        assert "redacted" not in str(meta).lower()
        assert "hidden" not in str(meta).lower()

    @pytest.mark.asyncio
    async def test_no_pctx_returns_all_columns(
        self, mock_guard, sample_df
    ):
        """When _current_pctx is None, no column filtering is applied."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)
        dm._current_pctx = None

        meta = await dm.get_metadata("financial_data")

        # All columns should be present (no filtering without context)
        col_keys = set(meta["columns"].keys()) if isinstance(meta["columns"], dict) else set(meta["columns"])
        assert "profit_margin" in col_keys
        mock_guard.filter_columns.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Test: column-level filtering — fetch_dataset
# ─────────────────────────────────────────────────────────────────────────────


class TestColumnFilteringFetchDataset:
    """Tests for column-level filtering in fetch_dataset."""

    @pytest.mark.asyncio
    async def test_fetch_dataset_drops_denied_columns(
        self, mock_guard, pctx_jleon, sample_df
    ):
        """Mock guard denies 'profit_margin'; fetch_dataset omits it from result."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)

        allowed = ["id", "name", "salary"]
        mock_guard.filter_columns.side_effect = (
            lambda pctx, dataset, cols: [c for c in cols if c in allowed]
        )
        dm._current_pctx = pctx_jleon

        result = await dm.fetch_dataset("financial_data")

        assert "profit_margin" not in result["columns"], (
            f"Expected 'profit_margin' absent from columns: {result['columns']}"
        )
        assert "salary" in result["columns"]

    @pytest.mark.asyncio
    async def test_fetch_dataset_data_lacks_denied_columns(
        self, mock_guard, pctx_jleon, sample_df
    ):
        """The inline data/sample_rows in fetch_dataset response also lacks denied columns."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)

        allowed = ["id", "name"]
        mock_guard.filter_columns.side_effect = (
            lambda pctx, dataset, cols: [c for c in cols if c in allowed]
        )
        dm._current_pctx = pctx_jleon

        result = await dm.fetch_dataset("financial_data")

        # Whether returned as 'data' (small) or 'sample_rows' (large)
        rows = result.get("data") or result.get("sample_rows", [])
        for row in rows:
            assert "profit_margin" not in row, (
                f"Denied column 'profit_margin' found in row: {row}"
            )
            assert "salary" not in row, (
                f"Denied column 'salary' found in row: {row}"
            )

    @pytest.mark.asyncio
    async def test_fetch_dataset_no_guard_returns_all(
        self, pctx_jleon, sample_df
    ):
        """Without a guard, fetch_dataset returns all columns."""
        dm = DatasetManager(policy_guard=None)
        dm.add_dataframe("financial_data", sample_df)

        result = await dm.fetch_dataset("financial_data")

        assert "profit_margin" in result["columns"]
        assert "salary" in result["columns"]

    @pytest.mark.asyncio
    async def test_fetch_dataset_no_pctx_returns_all(
        self, mock_guard, sample_df
    ):
        """When _current_pctx is None, no column filtering on fetch_dataset."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)
        dm._current_pctx = None

        result = await dm.fetch_dataset("financial_data")

        assert "profit_margin" in result["columns"]
        mock_guard.filter_columns.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Test: _pre_execute Layer-2 enforcement
# ─────────────────────────────────────────────────────────────────────────────


class TestPreExecute:
    """Tests for the _pre_execute PBAC Layer-2 enforcement hook."""

    @pytest.mark.asyncio
    async def test_pre_execute_stores_pctx(self, mock_guard, pctx_jleon):
        """_pre_execute stores the permission context on self._current_pctx."""
        dm = DatasetManager(policy_guard=mock_guard)
        assert dm._current_pctx is None

        await dm._pre_execute(
            "dataset_list_datasets",
            _permission_context=pctx_jleon,
        )
        assert dm._current_pctx is pctx_jleon

    @pytest.mark.asyncio
    async def test_pre_execute_allows_when_permitted(
        self, mock_guard, pctx_jleon, sample_df
    ):
        """_pre_execute does not raise when can_read_dataset returns True."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)
        mock_guard.can_read_dataset.return_value = True

        # Should not raise
        await dm._pre_execute(
            "dataset_fetch_dataset",
            _permission_context=pctx_jleon,
            name="financial_data",
        )

    @pytest.mark.asyncio
    async def test_pre_execute_denies_forbidden(
        self, mock_guard, pctx_jleon, sample_df
    ):
        """_pre_execute raises AuthorizationRequired when can_read_dataset returns False."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)
        mock_guard.can_read_dataset.return_value = False

        with pytest.raises(AuthorizationRequired) as exc_info:
            await dm._pre_execute(
                "dataset_fetch_dataset",
                _permission_context=pctx_jleon,
                name="financial_data",
            )

        assert exc_info.value.tool_name == "dataset_fetch_dataset"

    @pytest.mark.asyncio
    async def test_pre_execute_no_guard_never_denies(
        self, pctx_jleon, sample_df
    ):
        """Without a guard, _pre_execute never raises regardless of name."""
        dm = DatasetManager(policy_guard=None)
        dm.add_dataframe("financial_data", sample_df)

        # Should not raise
        await dm._pre_execute(
            "dataset_fetch_dataset",
            _permission_context=pctx_jleon,
            name="financial_data",
        )

    @pytest.mark.asyncio
    async def test_pre_execute_no_name_skips_check(
        self, mock_guard, pctx_jleon
    ):
        """_pre_execute skips can_read_dataset for tools without a 'name' kwarg."""
        dm = DatasetManager(policy_guard=mock_guard)

        # list_datasets, get_active, etc. do not pass a 'name'
        await dm._pre_execute(
            "dataset_list_datasets",
            _permission_context=pctx_jleon,
        )
        mock_guard.can_read_dataset.assert_not_called()

    @pytest.mark.asyncio
    async def test_pre_execute_no_pctx_skips_check(self, mock_guard, sample_df):
        """Without a permission context, _pre_execute skips guard checks."""
        dm = DatasetManager(policy_guard=mock_guard)
        dm.add_dataframe("financial_data", sample_df)

        await dm._pre_execute(
            "dataset_fetch_dataset",
            # no _permission_context kwarg
            name="financial_data",
        )
        mock_guard.can_read_dataset.assert_not_called()
        # _current_pctx should be None
        assert dm._current_pctx is None
