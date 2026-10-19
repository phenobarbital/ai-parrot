"""Tests for AuthorizingDataSource (FEAT-228 / TASK-1496)."""
from __future__ import annotations

import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock

from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource
from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.exceptions import AuthorizationRequired


class _RecordingSQL(SQLQuerySource):
    """SQL source that records the statement executed by each scoped copy."""

    seen: list[str] = []

    async def fetch(self, **params: object) -> pd.DataFrame:
        """Record the scoped SQL and return a deterministic row."""
        type(self).seen.append(self.sql)
        return pd.DataFrame({"id": [1]})


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

    @pytest.mark.asyncio
    async def test_denied_slug_raises_no_fetch(
        self,
        mock_guard: MagicMock,
        pctx: PermissionContext,
    ) -> None:
        """A denied QuerySlugSource fails closed on the fetch path (issue:176ec55ba7c3).

        Only the ai-parrot guard is involved — no in-process QuerySource PBAC —
        which is exactly the degraded mode the guard must cover (FEAT-598 AC14/AC18).
        """
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        mock_guard.authorize_source = AsyncMock(
            side_effect=AuthorizationRequired(tool_name="dataplane_authz", message="denied")
        )
        inner = QuerySlugSource(slug="s", tenant="t")
        inner.fetch = AsyncMock(return_value=pd.DataFrame({"x": [1]}))
        source = AuthorizingDataSource(inner, mock_guard, lambda: pctx)
        with pytest.raises(AuthorizationRequired):
            await source.fetch()
        inner.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_allowed_slug_fetches(
        self,
        mock_guard: MagicMock,
        pctx: PermissionContext,
    ) -> None:
        """An allowed QuerySlugSource fetches, and the guard saw the slug identity."""
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        inner = QuerySlugSource(slug="s", tenant="t")
        inner.fetch = AsyncMock(return_value=pd.DataFrame({"x": [1]}))
        source = AuthorizingDataSource(inner, mock_guard, lambda: pctx)
        result = await source.fetch()
        inner.fetch.assert_called_once()
        assert len(result) == 1
        mock_guard.authorize_source.assert_called_once()
        resources = mock_guard.authorize_source.call_args.args[1]
        assert resources.source_type == "query_slug"
        assert resources.source_id == "t:s"

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
        pred = RlsPredicate(
            table="sales.orders",
            sql_predicate="region IN (:p0)",
            bound_params={"p0": ["northeast"]},
        )
        mock_guard.rls_predicates = AsyncMock(return_value=[pred])

        _RecordingSQL.seen.clear()
        original_sql = "SELECT * FROM sales.orders"
        inner = _RecordingSQL(sql=original_sql, driver="pg")
        source = AuthorizingDataSource(inner, mock_guard, lambda: pctx)
        await source.fetch()
        assert "_rls" in _RecordingSQL.seen[-1]
        assert "WHERE" in _RecordingSQL.seen[-1]
        assert inner.sql == original_sql

    @pytest.mark.asyncio
    async def test_rls_not_persisted_across_fetches(
        self,
        mock_guard: MagicMock,
        pctx: PermissionContext,
    ) -> None:
        """Each fetch gets one RLS wrapper while the shared inner SQL stays pristine."""
        from parrot.auth.rls_registry import RlsPredicate

        pred = RlsPredicate(
            table="sales.orders",
            sql_predicate="region IN (:p0)",
            bound_params={"p0": ["northeast"]},
        )
        mock_guard.rls_predicates = AsyncMock(return_value=[pred])
        _RecordingSQL.seen.clear()
        original_sql = "SELECT * FROM sales.orders"
        inner = _RecordingSQL(sql=original_sql, driver="pg")
        source = AuthorizingDataSource(inner, mock_guard, lambda: pctx)

        await source.fetch()
        await source.fetch()

        assert len(_RecordingSQL.seen) == 2
        assert all(sql.count("_rls") == 1 for sql in _RecordingSQL.seen)
        assert inner.sql == original_sql

    @pytest.mark.asyncio
    async def test_rls_two_subjects_isolated(
        self,
        mock_guard: MagicMock,
        pctx: PermissionContext,
    ) -> None:
        """Subjects and filter-based sources never share request-scoped RLS state."""
        from parrot.auth.rls_registry import RlsPredicate
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource
        from parrot.tools.dataset_manager.sources.table import TableSource

        pctx_b = PermissionContext(
            session=UserSession(
                user_id="other_user",
                tenant_id="corp",
                roles=frozenset({"Finance"}),
                metadata={"groups": ["Finance"], "programs": []},
            )
        )
        current = {"context": pctx}

        async def predicates_for_context(
            ctx: PermissionContext,
            resources: object,
        ) -> list[RlsPredicate]:
            value = "northeast" if ctx.user_id == pctx.user_id else "southwest"
            return [
                RlsPredicate(
                    table="sales.orders",
                    sql_predicate="region IN (:p0)",
                    bound_params={"p0": [value]},
                )
            ]

        mock_guard.rls_predicates = AsyncMock(side_effect=predicates_for_context)
        _RecordingSQL.seen.clear()
        original_sql = "SELECT * FROM sales.orders"
        inner = _RecordingSQL(sql=original_sql, driver="pg")
        source = AuthorizingDataSource(inner, mock_guard, lambda: current["context"])

        await source.fetch()
        current["context"] = pctx_b
        await source.fetch()

        first_sql, second_sql = _RecordingSQL.seen
        assert "northeast" in first_sql and "southwest" not in first_sql
        assert "southwest" in second_sql and "northeast" not in second_sql
        assert inner.sql == original_sql

        predicate = await predicates_for_context(pctx, object())
        table = TableSource(table="sales.orders", driver="pg", permanent_filter={"active": True})
        scoped_table = AuthorizingDataSource(table, mock_guard, lambda: pctx)._apply_rls(predicate, MagicMock())
        assert table._permanent_filter == {"active": True}
        assert scoped_table._permanent_filter == {"active": True, "region": ["northeast"]}

        slug = QuerySlugSource(slug="orders", permanent_filter={"active": True})
        scoped_slug = AuthorizingDataSource(slug, mock_guard, lambda: pctx)._apply_rls(predicate, MagicMock())
        assert slug._permanent_filter == {"active": True}
        assert scoped_slug._permanent_filter == {"active": True, "region": ["northeast"]}
