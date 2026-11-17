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
        monkeypatch: pytest.MonkeyPatch,
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
        original_sql = inner.sql
        fetched: dict[str, str] = {}

        async def _capture(self, **params):  # noqa: ANN001, ANN003 - test double
            fetched["sql"] = self.sql
            return pd.DataFrame({"id": [1]})

        monkeypatch.setattr(SQLQuerySource, "fetch", _capture)
        source = AuthorizingDataSource(inner, mock_guard, lambda: pctx)
        await source.fetch()

        # The source actually fetched from carries the RLS wrapper (AC3) ...
        assert "_rls" in fetched["sql"]
        assert "WHERE" in fetched["sql"]
        # ... while the wrapped source is left untouched (AC1, issue:90cf04ce8edd).
        assert inner.sql == original_sql


class TestRequestScopedRls:
    """issue:90cf04ce8edd — RLS injection must never mutate the wrapped source."""

    @staticmethod
    def _predicate():
        """Build a single region predicate used by every test in this class."""
        from parrot.auth.rls_registry import RlsPredicate

        return RlsPredicate(
            table="sales.orders",
            sql_predicate="region IN (:p0)",
            bound_params={"p0": ["northeast"]},
        )

    @pytest.mark.asyncio
    async def test_repeated_fetch_does_not_accumulate_predicates(
        self,
        mock_guard: MagicMock,
        pctx: PermissionContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Two fetches send identical SQL — predicates must not pile up (AC2)."""
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource

        mock_guard.rls_predicates = AsyncMock(return_value=[self._predicate()])
        inner = SQLQuerySource(sql="SELECT * FROM sales.orders", driver="pg")
        seen: list[str] = []

        async def _capture(self, **params):  # noqa: ANN001, ANN003 - test double
            seen.append(self.sql)
            return pd.DataFrame({"id": [1]})

        monkeypatch.setattr(SQLQuerySource, "fetch", _capture)
        source = AuthorizingDataSource(inner, mock_guard, lambda: pctx)
        await source.fetch()
        await source.fetch()

        assert len(seen) == 2
        assert seen[0] == seen[1]

    @pytest.mark.asyncio
    async def test_fetch_does_not_mutate_table_source_permanent_filter(
        self,
        mock_guard: MagicMock,
        pctx: PermissionContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """TableSource._permanent_filter is isolated per request (AC1)."""
        from parrot.tools.dataset_manager.sources.table import TableSource

        mock_guard.rls_predicates = AsyncMock(return_value=[self._predicate()])
        inner = TableSource(table="sales.orders", driver="pg")
        original_filter = dict(inner._permanent_filter)
        original_id = id(inner._permanent_filter)
        fetched: dict[str, dict] = {}

        async def _capture(self, **params):  # noqa: ANN001, ANN003 - test double
            fetched["filter"] = dict(self._permanent_filter)
            return pd.DataFrame({"id": [1]})

        monkeypatch.setattr(TableSource, "fetch", _capture)
        source = AuthorizingDataSource(inner, mock_guard, lambda: pctx)
        await source.fetch()

        # The fetched copy carries the predicate ...
        assert fetched["filter"].get("region") == ["northeast"]
        # ... the original dict is neither replaced nor written through.
        assert inner._permanent_filter == original_filter
        assert id(inner._permanent_filter) == original_id

    @pytest.mark.asyncio
    async def test_fetch_does_not_mutate_query_slug_permanent_filter(
        self,
        mock_guard: MagicMock,
        pctx: PermissionContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """QuerySlugSource._permanent_filter is isolated per request (AC1)."""
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        mock_guard.rls_predicates = AsyncMock(return_value=[self._predicate()])
        inner = QuerySlugSource(slug="orders_by_region")
        original_filter = dict(inner._permanent_filter)
        fetched: dict[str, dict] = {}

        async def _capture(self, **params):  # noqa: ANN001, ANN003 - test double
            fetched["filter"] = dict(self._permanent_filter)
            return pd.DataFrame({"id": [1]})

        monkeypatch.setattr(QuerySlugSource, "fetch", _capture)
        source = AuthorizingDataSource(inner, mock_guard, lambda: pctx)
        await source.fetch()

        assert fetched["filter"].get("region") == ["northeast"]
        assert inner._permanent_filter == original_filter

    @pytest.mark.asyncio
    async def test_two_wrappers_sharing_one_source_do_not_cross_contaminate(
        self,
        mock_guard: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The cross-subject leak itself: one shared source, two subjects (AC1)."""
        from parrot.auth.rls_registry import RlsPredicate
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource

        def _pred(region: str) -> RlsPredicate:
            return RlsPredicate(
                table="sales.orders",
                sql_predicate="region IN (:p0)",
                bound_params={"p0": [region]},
            )

        def _ctx(user: str, region: str) -> PermissionContext:
            return PermissionContext(
                session=UserSession(
                    user_id=user,
                    tenant_id="corp",
                    roles=frozenset({"Sales"}),
                    metadata={"groups": [region], "programs": []},
                )
            )

        shared = SQLQuerySource(sql="SELECT * FROM sales.orders", driver="pg")
        seen: list[str] = []

        async def _capture(self, **params):  # noqa: ANN001, ANN003 - test double
            seen.append(self.sql)
            return pd.DataFrame({"id": [1]})

        monkeypatch.setattr(SQLQuerySource, "fetch", _capture)

        mock_guard.rls_predicates = AsyncMock(return_value=[_pred("northeast")])
        await AuthorizingDataSource(shared, mock_guard, lambda: _ctx("alice", "NE")).fetch()

        mock_guard.rls_predicates = AsyncMock(return_value=[_pred("southwest")])
        await AuthorizingDataSource(shared, mock_guard, lambda: _ctx("bob", "SW")).fetch()

        # Bob's query must not carry Alice's region.
        assert "northeast" in seen[0]
        assert "southwest" in seen[1]
        assert "northeast" not in seen[1]
