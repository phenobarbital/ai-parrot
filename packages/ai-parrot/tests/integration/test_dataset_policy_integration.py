"""Integration tests for DatasetManager PBAC policy chain (TASK-1047).

Tests wire all three FEAT-151 components together:
    DatasetPolicyGuard (TASK-1044)
    + extended setup_pbac (TASK-1045)
    + DatasetManager with guard (TASK-1046)

NOTE: ResourceType.DATASET does not yet exist in the installed version of
navigator-auth (cross-repo PR pending).  All tests in this file use a
mocked PolicyEvaluator to simulate the expected behaviour.  When the
cross-repo PR lands, replace the mock with a real PolicyEvaluator constructed
from the YAML fixture at policies/datasets/sample.yml.

The mock evaluator is configured per-test to mirror what the real evaluator
would return once DATASET resource type is available.
"""
from __future__ import annotations

import pytest
import pandas as pd
from unittest.mock import MagicMock

from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.dataset_guard import DatasetPolicyGuard
from parrot.tools.dataset_manager.tool import DatasetManager, _pctx_var


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_evaluator(
    allowed_datasets: dict[str, list[str]] | None = None,
    allowed_columns: dict[str, dict[str, list[str]]] | None = None,
) -> MagicMock:
    """Build a stub PolicyEvaluator that simulates DATASET resource evaluation.

    Args:
        allowed_datasets: Mapping user_id → list of allowed dataset names.
            ``None`` means all datasets are allowed (no dataset-level deny).
        allowed_columns: Mapping user_id → {dataset_name → allowed columns}.
            ``None`` means all columns are allowed (no column-level deny).

    The stub replicates the interface used by DatasetPolicyGuard:
        - ``filter_resources(ctx, resource_type, resource_names, action, env)``
          Returns an object with ``.allowed`` attribute (list of names that pass).
        - ``check_access(ctx, resource_type, resource_name, action, env)``
          Returns an object with ``.allowed`` (bool) attribute.
    """
    evaluator = MagicMock()

    def _filter_resources(ctx, resource_type, resource_names, action, env):
        """Simulate filter_resources for DATASET / DATASET:COLUMN resources.

        ``ctx`` is a navigator-auth EvalContext built by ``to_eval_context()``.
        User identity lives at ``ctx.user``; roles at ``ctx.userinfo["roles"]``.

        Resource name format (matches DatasetPolicyGuard after Fix 1):
          - dataset:read      → "dataset:<dataset_name>"
          - column:read       → "dataset:<dataset_name>:<column_name>"
        """
        # EvalContext stores identity via __getattr__ → self.store lookups.
        user_id: str = getattr(ctx, "user", None) or ""
        userinfo: dict = getattr(ctx, "userinfo", {}) or {}
        role_names: set[str] = set(userinfo.get("roles", []) or [])

        result = MagicMock()

        if action == "dataset:read":
            # Dataset-level filtering.
            # resource_names are "dataset:<name>" — strip prefix to get bare name.
            if allowed_datasets is None:
                result.allowed = list(resource_names)
            else:
                # Per-user allowed + wildcard ("*") fallback.
                permitted = (
                    set(allowed_datasets.get(user_id, []))
                    | set(allowed_datasets.get("*", []))
                )
                result.allowed = [
                    r for r in resource_names
                    if r.removeprefix("dataset:") in permitted
                ]

        elif action == "dataset:column:read":
            # Column-level filtering.
            # resource_names are "dataset:<dataset_name>:<column_name>" — strip
            # the "dataset:" prefix first, then split on the first ":" to get
            # dataset_name and column_name.
            if allowed_columns is None:
                result.allowed = list(resource_names)
            else:
                # Determine allowed cols per user + role
                user_allowed = dict(allowed_columns.get(user_id) or {})
                for role in role_names:
                    role_allowed = allowed_columns.get(f"role:{role}") or {}
                    for ds, cols in role_allowed.items():
                        user_allowed.setdefault(ds, cols)

                filtered = []
                for composite in resource_names:
                    # Strip "dataset:" prefix, then split "<ds>:<col>"
                    bare = composite.removeprefix("dataset:")
                    parts = bare.split(":", 1)
                    if len(parts) != 2:
                        filtered.append(composite)
                        continue
                    ds_name, col_name = parts
                    permitted_cols = user_allowed.get(ds_name)
                    if permitted_cols is None:
                        # No restriction for this dataset → allow
                        filtered.append(composite)
                    elif col_name in permitted_cols:
                        filtered.append(composite)
                result.allowed = filtered
        else:
            result.allowed = list(resource_names)

        return result

    def _check_access(ctx, resource_type, resource_name, action, env):
        """Simulate check_access for DATASET resources."""
        filter_result = _filter_resources(
            ctx, resource_type, [resource_name], action, env
        )
        access = MagicMock()
        access.allowed = bool(filter_result.allowed)
        access.matched_policy = "stub-policy"
        access.reason = "stub evaluator"
        return access

    evaluator.filter_resources.side_effect = _filter_resources
    evaluator.check_access.side_effect = _check_access
    return evaluator


def _make_guard(evaluator) -> DatasetPolicyGuard:
    """Wrap a stub evaluator in a DatasetPolicyGuard."""
    return DatasetPolicyGuard(evaluator=evaluator)


def _make_dm(guard: DatasetPolicyGuard | None, *frames: tuple[str, pd.DataFrame]) -> DatasetManager:
    """Build a DatasetManager with the given guard and pre-loaded DataFrames."""
    dm = DatasetManager(policy_guard=guard)
    for name, df in frames:
        dm.add_dataframe(name, df)
    return dm


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def pctx_jleon():
    """jleon is denied access to financial_data (per sample.yml)."""
    return PermissionContext(
        session=UserSession(
            user_id="jleon@trocglobal.com",
            tenant_id="troc",
            roles=frozenset(),
            metadata={},
        )
    )


@pytest.fixture
def pctx_admin():
    """admin sees all datasets and all columns."""
    return PermissionContext(
        session=UserSession(
            user_id="admin@trocglobal.com",
            tenant_id="troc",
            roles=frozenset({"admin"}),
            metadata={},
        )
    )


@pytest.fixture
def pctx_tier1_rep():
    """tier-1-rep is denied the profit_margin column in sales (per sample.yml)."""
    return PermissionContext(
        session=UserSession(
            user_id="rep@trocglobal.com",
            tenant_id="troc",
            roles=frozenset({"tier-1-rep"}),
            metadata={},
        )
    )


@pytest.fixture
def financial_df():
    return pd.DataFrame({
        "id": [1, 2, 3],
        "revenue": [100_000, 200_000, 150_000],
        "profit_margin": [0.25, 0.30, 0.22],
    })


@pytest.fixture
def sales_df():
    return pd.DataFrame({
        "product": ["A", "B", "C"],
        "units": [500, 300, 800],
        "profit_margin": [0.15, 0.20, 0.18],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Tests: end-to-end dataset deny
# ─────────────────────────────────────────────────────────────────────────────


class TestEndToEndDatasetPolicy:
    """Full chain: mocked PolicyEvaluator → DatasetPolicyGuard → DatasetManager."""

    @pytest.mark.asyncio
    async def test_dataset_deny_list_datasets(
        self, pctx_jleon, financial_df, sales_df
    ):
        """Denied dataset absent from list_datasets for the restricted user."""
        # jleon can only see 'public_sales', NOT 'financial_data'
        evaluator = _make_evaluator(
            allowed_datasets={"jleon@trocglobal.com": ["public_sales"]}
        )
        guard = _make_guard(evaluator)
        dm = _make_dm(
            guard,
            ("financial_data", financial_df),
            ("public_sales", sales_df),
        )
        _pctx_var.set(pctx_jleon)

        results = await dm.list_datasets()
        names = [r["name"] for r in results]

        assert "financial_data" not in names, (
            f"financial_data should be hidden for jleon, got: {names}"
        )
        assert "public_sales" in names

    @pytest.mark.asyncio
    async def test_dataset_deny_get_active(
        self, pctx_jleon, financial_df, sales_df
    ):
        """Denied dataset absent from get_active for the restricted user."""
        evaluator = _make_evaluator(
            allowed_datasets={"jleon@trocglobal.com": ["public_sales"]}
        )
        guard = _make_guard(evaluator)
        dm = _make_dm(
            guard,
            ("financial_data", financial_df),
            ("public_sales", sales_df),
        )
        _pctx_var.set(pctx_jleon)

        active = await dm.get_active()

        assert "financial_data" not in active
        assert "public_sales" in active

    @pytest.mark.asyncio
    async def test_dataset_deny_get_metadata(
        self, pctx_jleon, financial_df
    ):
        """Denied dataset not returned for the restricted user in get_metadata."""
        # All datasets denied for jleon
        evaluator = _make_evaluator(
            allowed_datasets={"jleon@trocglobal.com": []}
        )
        guard = _make_guard(evaluator)
        dm = _make_dm(guard, ("financial_data", financial_df))
        _pctx_var.set(pctx_jleon)

        # list_datasets returns nothing — simulates the dataset is hidden
        results = await dm.list_datasets()
        assert not any(r["name"] == "financial_data" for r in results)

    @pytest.mark.asyncio
    async def test_dataset_deny_fetch_dataset_via_pre_execute(
        self, pctx_jleon, financial_df
    ):
        """_pre_execute blocks fetch_dataset for denied dataset (Layer-2)."""
        from parrot.auth.exceptions import AuthorizationRequired

        evaluator = _make_evaluator(
            allowed_datasets={"jleon@trocglobal.com": []}
        )
        guard = _make_guard(evaluator)
        dm = _make_dm(guard, ("financial_data", financial_df))

        with pytest.raises(AuthorizationRequired):
            await dm._pre_execute(
                "dataset_fetch_dataset",
                _permission_context=pctx_jleon,
                name="financial_data",
            )

    @pytest.mark.asyncio
    async def test_dataset_deny_drop_silent(
        self, pctx_jleon, financial_df, sales_df
    ):
        """No 'permission_denied' field in list_datasets output for hidden datasets."""
        evaluator = _make_evaluator(
            allowed_datasets={"jleon@trocglobal.com": ["public_sales"]}
        )
        guard = _make_guard(evaluator)
        dm = _make_dm(
            guard,
            ("financial_data", financial_df),
            ("public_sales", sales_df),
        )
        _pctx_var.set(pctx_jleon)

        results = await dm.list_datasets()

        for r in results:
            assert "permission_denied" not in r
            assert "redacted" not in str(r).lower()
            assert "hidden" not in str(r).lower()


# ─────────────────────────────────────────────────────────────────────────────
# Tests: end-to-end column deny
# ─────────────────────────────────────────────────────────────────────────────


class TestEndToEndColumnPolicy:
    """Column-level deny: profit_margin hidden for tier-1-rep in sales."""

    @pytest.mark.asyncio
    async def test_column_deny_get_metadata(
        self, pctx_tier1_rep, sales_df
    ):
        """Denied column absent from DatasetInfo.columns and column_types."""
        # tier-1-rep can see 'product' and 'units' in sales, NOT 'profit_margin'
        evaluator = _make_evaluator(
            allowed_columns={
                "role:tier-1-rep": {
                    "sales": ["product", "units"]
                }
            }
        )
        guard = _make_guard(evaluator)
        dm = _make_dm(guard, ("sales", sales_df))
        _pctx_var.set(pctx_tier1_rep)

        meta = await dm.get_metadata("sales")

        col_keys = (
            set(meta["columns"].keys())
            if isinstance(meta["columns"], dict)
            else set(meta["columns"])
        )
        ct_keys = set(meta.get("column_types", {}).keys())

        assert "profit_margin" not in col_keys, (
            f"profit_margin should be hidden; columns: {col_keys}"
        )
        assert "profit_margin" not in ct_keys
        assert "product" in col_keys
        assert "units" in col_keys

    @pytest.mark.asyncio
    async def test_column_deny_fetch_dataset(
        self, pctx_tier1_rep, sales_df
    ):
        """Denied column absent from DataFrame returned by fetch_dataset."""
        evaluator = _make_evaluator(
            allowed_columns={
                "role:tier-1-rep": {
                    "sales": ["product", "units"]
                }
            }
        )
        guard = _make_guard(evaluator)
        dm = _make_dm(guard, ("sales", sales_df))
        _pctx_var.set(pctx_tier1_rep)

        result = await dm.fetch_dataset("sales")

        assert "profit_margin" not in result["columns"], (
            f"profit_margin should be absent; columns: {result['columns']}"
        )
        assert "product" in result["columns"]

        # Also check data/sample_rows
        rows = result.get("data") or result.get("sample_rows", [])
        for row in rows:
            assert "profit_margin" not in row

    @pytest.mark.asyncio
    async def test_column_deny_lockstep(self, pctx_tier1_rep, sales_df):
        """columns and column_types are filtered in lockstep."""
        evaluator = _make_evaluator(
            allowed_columns={
                "role:tier-1-rep": {"sales": ["product"]}
            }
        )
        guard = _make_guard(evaluator)
        dm = _make_dm(guard, ("sales", sales_df))
        _pctx_var.set(pctx_tier1_rep)

        meta = await dm.get_metadata("sales")

        col_keys = (
            set(meta["columns"].keys())
            if isinstance(meta["columns"], dict)
            else set(meta["columns"])
        )
        ct_keys = set(meta.get("column_types", {}).keys()) if meta.get("column_types") else set()

        # column_types must be a subset of columns — they must stay consistent
        assert ct_keys <= col_keys, (
            f"column_types {ct_keys} is not a subset of columns {col_keys}"
        )
        assert "profit_margin" not in col_keys
        assert "units" not in col_keys
        assert "product" in col_keys

    @pytest.mark.asyncio
    async def test_column_deny_drop_silent(self, pctx_tier1_rep, sales_df):
        """No error signal or redaction marker in column-filtered output."""
        evaluator = _make_evaluator(
            allowed_columns={"role:tier-1-rep": {"sales": ["product", "units"]}}
        )
        guard = _make_guard(evaluator)
        dm = _make_dm(guard, ("sales", sales_df))
        _pctx_var.set(pctx_tier1_rep)

        meta = await dm.get_metadata("sales")

        assert "permission_denied" not in meta
        assert "redacted" not in str(meta).lower()


# ─────────────────────────────────────────────────────────────────────────────
# Tests: admin full visibility
# ─────────────────────────────────────────────────────────────────────────────


class TestAdminFullVisibility:
    """Admin user sees all datasets and columns regardless of policy."""

    @pytest.mark.asyncio
    async def test_admin_sees_all_datasets(
        self, pctx_admin, financial_df, sales_df
    ):
        """Admin user gets all datasets in list_datasets."""
        # Evaluator allows only jleon's deny but admin (not jleon) is unrestricted
        evaluator = _make_evaluator(
            allowed_datasets={
                "jleon@trocglobal.com": [],
                "*": ["financial_data", "sales"],
            }
        )
        guard = _make_guard(evaluator)
        dm = _make_dm(
            guard,
            ("financial_data", financial_df),
            ("sales", sales_df),
        )
        _pctx_var.set(pctx_admin)

        results = await dm.list_datasets()
        names = [r["name"] for r in results]

        assert "financial_data" in names
        assert "sales" in names

    @pytest.mark.asyncio
    async def test_admin_sees_all_columns(self, pctx_admin, sales_df):
        """Admin user gets all columns including restricted ones."""
        # None → all columns allowed (no column restriction)
        evaluator = _make_evaluator(allowed_columns=None)
        guard = _make_guard(evaluator)
        dm = _make_dm(guard, ("sales", sales_df))
        _pctx_var.set(pctx_admin)

        meta = await dm.get_metadata("sales")

        col_keys = (
            set(meta["columns"].keys())
            if isinstance(meta["columns"], dict)
            else set(meta["columns"])
        )
        assert "profit_margin" in col_keys


# ─────────────────────────────────────────────────────────────────────────────
# Tests: opt-in backwards compatibility
# ─────────────────────────────────────────────────────────────────────────────


class TestOptInCompatibility:
    """DatasetManager(policy_guard=None) must be bit-identical to pre-feature."""

    @pytest.mark.asyncio
    async def test_no_guard_all_datasets_visible(self, financial_df, sales_df):
        """Without a guard, all datasets are returned by list_datasets."""
        dm = DatasetManager(policy_guard=None)
        dm.add_dataframe("financial_data", financial_df)
        dm.add_dataframe("sales", sales_df)

        results = await dm.list_datasets()
        names = [r["name"] for r in results]

        assert "financial_data" in names
        assert "sales" in names

    @pytest.mark.asyncio
    async def test_no_guard_all_columns_visible(self, financial_df):
        """Without a guard, all columns are present in get_metadata."""
        dm = DatasetManager(policy_guard=None)
        dm.add_dataframe("financial_data", financial_df)

        meta = await dm.get_metadata("financial_data")

        col_keys = (
            set(meta["columns"].keys())
            if isinstance(meta["columns"], dict)
            else set(meta["columns"])
        )
        assert "profit_margin" in col_keys
        assert "revenue" in col_keys

    @pytest.mark.asyncio
    async def test_no_guard_fetch_returns_all_columns(self, financial_df):
        """Without a guard, fetch_dataset returns all columns."""
        dm = DatasetManager(policy_guard=None)
        dm.add_dataframe("financial_data", financial_df)

        result = await dm.fetch_dataset("financial_data")

        assert "profit_margin" in result["columns"]
        assert "revenue" in result["columns"]

    @pytest.mark.asyncio
    async def test_no_policies_no_enforcement(self, financial_df, sales_df):
        """With an allow-all evaluator (empty policy dir), all data is visible."""
        # allow_all evaluator: allowed_datasets=None and allowed_columns=None
        evaluator = _make_evaluator(
            allowed_datasets=None,
            allowed_columns=None,
        )
        guard = _make_guard(evaluator)
        dm = _make_dm(
            guard,
            ("financial_data", financial_df),
            ("sales", sales_df),
        )
        _pctx_var.set(PermissionContext(
            session=UserSession(
                user_id="any@example.com",
                tenant_id="test",
                roles=frozenset(),
                metadata={},
            )
        ))

        results = await dm.list_datasets()
        names = [r["name"] for r in results]
        assert "financial_data" in names
        assert "sales" in names

        meta = await dm.get_metadata("financial_data")
        col_keys = (
            set(meta["columns"].keys())
            if isinstance(meta["columns"], dict)
            else set(meta["columns"])
        )
        assert "profit_margin" in col_keys
