"""Tests for AuthorizingDataSource (FEAT-228 / TASK-1496)."""
from __future__ import annotations

import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock

from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.exceptions import AuthorizationRequired


@pytest.fixture
def pctx() -> PermissionContext:
    return PermissionContext(
        session=UserSession(
            user_id="test_user",
            tenant_id="corp",
            roles=frozenset({"Finance"}),
            metadata={"groups": ["Finance"], "programs": []},
        )
    )


@pytest.fixture
def mock_guard() -> MagicMock:
    guard = MagicMock()
    guard.is_sensitive_driver.return_value = False
    guard.authorize_source = AsyncMock()
    guard.rls_predicates = AsyncMock(return_value=[])
    return guard


@pytest.fixture
def mock_inner() -> MagicMock:
    """Mock DataSource-like inner object."""
    inner = MagicMock()
    inner.driver = "pg"
    inner.routing_meta = None
    inner.fetch = AsyncMock(return_value=pd.DataFrame({"a": [1, 2]}))
    inner.describe.return_value = "test source"
    inner.has_builtin_cache = False
    inner.cache_key = "test-key"
    return inner


class TestAuthorizingDataSource:
    """Core enforcement chain tests."""

    @pytest.mark.asyncio
    async def test_allowed_delegates_to_inner(
        self,
        mock_inner: MagicMock,
        mock_guard: MagicMock,
        pctx: PermissionContext,
    ) -> None:
        """When guard allows, inner.fetch() is called and result returned."""
        source = AuthorizingDataSource(mock_inner, mock_guard, lambda: pctx)
        result = await source.fetch()
        mock_inner.fetch.assert_called_once()
        assert list(result.columns) == ["a"]

    @pytest.mark.asyncio
    async def test_denied_raises_no_fetch(
        self,
        mock_inner: MagicMock,
        mock_guard: MagicMock,
        pctx: PermissionContext,
    ) -> None:
        """When guard denies, AuthorizationRequired raised, inner.fetch never called."""
        mock_guard.authorize_source = AsyncMock(
            side_effect=AuthorizationRequired(
                tool_name="t", message="denied"
            )
        )
        source = AuthorizingDataSource(mock_inner, mock_guard, lambda: pctx)
        with pytest.raises(AuthorizationRequired):
            await source.fetch()
        mock_inner.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_context_failopen(
        self,
        mock_inner: MagicMock,
        mock_guard: MagicMock,
    ) -> None:
        """No PermissionContext → fail-open, guard not consulted."""
        source = AuthorizingDataSource(mock_inner, mock_guard, lambda: None)
        result = await source.fetch()
        mock_inner.fetch.assert_called_once()
        mock_guard.authorize_source.assert_not_called()

    @pytest.mark.asyncio
    async def test_sensitive_driver_non_slug_denied(
        self,
        mock_inner: MagicMock,
        mock_guard: MagicMock,
        pctx: PermissionContext,
    ) -> None:
        """Sensitive driver + non-slug source → denied before parsing."""
        mock_guard.is_sensitive_driver.return_value = True
        mock_inner.driver = "bigquery_finance"
        source = AuthorizingDataSource(mock_inner, mock_guard, lambda: pctx)
        with pytest.raises(AuthorizationRequired):
            await source.fetch()
        # Guard's authorize_source should not have been called
        mock_guard.authorize_source.assert_not_called()

    @pytest.mark.asyncio
    async def test_sensitive_driver_slug_allowed(
        self,
        mock_guard: MagicMock,
        pctx: PermissionContext,
    ) -> None:
        """Sensitive driver + QuerySlugSource → passes pre-check, proceeds normally."""
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        mock_guard.is_sensitive_driver.return_value = True
        inner = QuerySlugSource(slug="my_slug")
        # Patch fetch to return a DataFrame
        inner.fetch = AsyncMock(return_value=pd.DataFrame({"x": [1]}))
        source = AuthorizingDataSource(inner, mock_guard, lambda: pctx)
        result = await source.fetch()
        assert len(result) == 1

    def test_describe_delegates(
        self, mock_inner: MagicMock, mock_guard: MagicMock
    ) -> None:
        """describe() is delegated to inner source."""
        source = AuthorizingDataSource(mock_inner, mock_guard, lambda: None)
        assert source.describe() == "test source"

    def test_cache_key_delegates(
        self, mock_inner: MagicMock, mock_guard: MagicMock
    ) -> None:
        source = AuthorizingDataSource(mock_inner, mock_guard, lambda: None)
        assert source.cache_key == "test-key"

    def test_has_builtin_cache_delegates(
        self, mock_inner: MagicMock, mock_guard: MagicMock
    ) -> None:
        source = AuthorizingDataSource(mock_inner, mock_guard, lambda: None)
        assert source.has_builtin_cache is False

    @pytest.mark.asyncio
    async def test_rls_injected_before_fetch(
        self,
        mock_guard: MagicMock,
        pctx: PermissionContext,
    ) -> None:
        """When guard returns RLS predicates, they are injected before fetch."""
        from parrot.auth.rls_registry import RlsPredicate
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource

        pred = RlsPredicate(
            table="sales.orders",
            sql_predicate="region IN (:p0)",
            bound_params={"p0": ["northeast"]},
        )
        mock_guard.rls_predicates = AsyncMock(return_value=[pred])

        inner = SQLQuerySource(sql="SELECT * FROM sales.orders", driver="pg")
        inner.fetch = AsyncMock(return_value=pd.DataFrame({"id": [1]}))
        source = AuthorizingDataSource(inner, mock_guard, lambda: pctx)
        await source.fetch()
        # The inner SQL should now be rewritten with the RLS wrapper
        assert "_rls" in inner.sql
        assert "WHERE" in inner.sql
