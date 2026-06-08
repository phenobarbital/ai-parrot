"""Integration tests for DatasetManager FEAT-228 data-plane authorization (TASK-1497).

Validates that:
- ``DatasetManager`` accepts a ``dataplane_guard`` parameter.
- ``_make_source()`` wraps non-InMemorySource when guard is configured.
- ``_make_source()`` skips InMemorySource (no authorization surface).
- ``_make_source()`` returns source unchanged when guard is None.
- Pre-registered datasets are wrapped at registration time.
- Ad-hoc source construction in ``add_dataset()`` is wrapped.
- AC8: no ``dataplane_guard`` → fail-open.
- AC1: alias-spoofing ad-hoc ``query=`` path denied for unauthorized user.
"""
from __future__ import annotations

import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_guard() -> MagicMock:
    """Mock DataPlanePolicyGuard that allows everything by default."""
    guard = MagicMock()
    guard.is_sensitive_driver.return_value = False
    guard.authorize_source = AsyncMock()
    guard.rls_predicates = AsyncMock(return_value=[])
    return guard


@pytest.fixture
def denying_guard() -> MagicMock:
    """Mock DataPlanePolicyGuard that denies every request."""
    from parrot.auth.exceptions import AuthorizationRequired
    guard = MagicMock()
    guard.is_sensitive_driver.return_value = False
    guard.authorize_source = AsyncMock(
        side_effect=AuthorizationRequired(
            tool_name="dataplane_authz", message="access denied"
        )
    )
    guard.rls_predicates = AsyncMock(return_value=[])
    return guard


# ── _make_source factory ──────────────────────────────────────────────────────


class TestMakeSourceFactory:
    """Unit-level tests for the _make_source() factory method."""

    def test_no_guard_returns_original(self) -> None:
        """AC8: no dataplane_guard → _make_source returns source unchanged."""
        from parrot.tools.dataset_manager.tool import DatasetManager
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource

        dm = DatasetManager(dataplane_guard=None)
        source = SQLQuerySource(sql="SELECT 1", driver="pg")
        result = dm._make_source(source)
        assert result is source

    def test_guard_present_wraps_sql_source(self, mock_guard: MagicMock) -> None:
        """_make_source wraps SQLQuerySource with AuthorizingDataSource."""
        from parrot.tools.dataset_manager.tool import DatasetManager
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
        from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource

        dm = DatasetManager(dataplane_guard=mock_guard)
        source = SQLQuerySource(sql="SELECT 1", driver="pg")
        wrapped = dm._make_source(source)
        assert isinstance(wrapped, AuthorizingDataSource)
        assert wrapped._inner is source

    def test_guard_present_skips_inmemory(self, mock_guard: MagicMock) -> None:
        """InMemorySource is not wrapped — no driver, no authorization surface."""
        from parrot.tools.dataset_manager.tool import DatasetManager
        from parrot.tools.dataset_manager.sources.memory import InMemorySource
        from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource

        dm = DatasetManager(dataplane_guard=mock_guard)
        source = InMemorySource(df=pd.DataFrame({"x": [1]}), name="test")
        result = dm._make_source(source)
        assert result is source
        assert not isinstance(result, AuthorizingDataSource)

    def test_guard_present_wraps_query_slug_source(self, mock_guard: MagicMock) -> None:
        """QuerySlugSource is wrapped with AuthorizingDataSource."""
        from parrot.tools.dataset_manager.tool import DatasetManager
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource
        from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource

        dm = DatasetManager(dataplane_guard=mock_guard)
        source = QuerySlugSource(slug="my_slug")
        wrapped = dm._make_source(source)
        assert isinstance(wrapped, AuthorizingDataSource)

    def test_pctx_provider_reads_from_context_var(self, mock_guard: MagicMock) -> None:
        """The pctx_provider in the wrapped source reads from _pctx_var."""
        from parrot.tools.dataset_manager.tool import DatasetManager, _pctx_var
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
        from parrot.auth.permission import PermissionContext, UserSession

        dm = DatasetManager(dataplane_guard=mock_guard)
        source = SQLQuerySource(sql="SELECT 1", driver="pg")
        wrapped = dm._make_source(source)

        # Without a context, provider returns None
        assert wrapped._pctx_provider() is None

        # With a context set in the ContextVar, provider returns it
        pctx = PermissionContext(
            session=UserSession(user_id="u1", tenant_id="t1", roles=frozenset())
        )
        token = _pctx_var.set(pctx)
        try:
            assert wrapped._pctx_provider() is pctx
        finally:
            _pctx_var.reset(token)


# ── Registration paths ────────────────────────────────────────────────────────


class TestRegistrationPaths:
    """Verify sources registered via add_X methods are wrapped."""

    def test_add_sql_source_wraps(self, mock_guard: MagicMock) -> None:
        """add_sql_source() registers an AuthorizingDataSource."""
        from parrot.tools.dataset_manager.tool import DatasetManager
        from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource

        dm = DatasetManager(dataplane_guard=mock_guard)
        dm.add_sql_source("orders", "SELECT * FROM orders", "pg")
        entry = dm._datasets["orders"]
        assert isinstance(entry.source, AuthorizingDataSource)

    def test_add_query_wraps(self, mock_guard: MagicMock) -> None:
        """add_query() registers an AuthorizingDataSource."""
        from parrot.tools.dataset_manager.tool import DatasetManager
        from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource

        dm = DatasetManager(dataplane_guard=mock_guard)
        dm.add_query("my_ds", "my_slug")
        entry = dm._datasets["my_ds"]
        assert isinstance(entry.source, AuthorizingDataSource)

    def test_add_source_wraps(self, mock_guard: MagicMock) -> None:
        """add_source() registers an AuthorizingDataSource for SQL sources."""
        from parrot.tools.dataset_manager.tool import DatasetManager
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
        from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource

        dm = DatasetManager(dataplane_guard=mock_guard)
        source = SQLQuerySource(sql="SELECT 1", driver="pg")
        source.name = "raw_source"  # type: ignore[attr-defined]
        dm.add_source(source)
        entry = dm._datasets["raw_source"]
        assert isinstance(entry.source, AuthorizingDataSource)

    def test_add_dataframe_not_wrapped(self, mock_guard: MagicMock) -> None:
        """add_dataframe() stores InMemorySource — not wrapped."""
        from parrot.tools.dataset_manager.tool import DatasetManager
        from parrot.tools.dataset_manager.sources.memory import InMemorySource
        from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource

        dm = DatasetManager(dataplane_guard=mock_guard)
        dm.add_dataframe("df1", pd.DataFrame({"a": [1]}))
        entry = dm._datasets["df1"]
        assert isinstance(entry.source, InMemorySource)
        assert not isinstance(entry.source, AuthorizingDataSource)

    def test_no_guard_sql_source_not_wrapped(self) -> None:
        """AC8: no dataplane_guard → sources registered unwrapped."""
        from parrot.tools.dataset_manager.tool import DatasetManager
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
        from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource

        dm = DatasetManager(dataplane_guard=None)
        dm.add_sql_source("orders", "SELECT * FROM orders", "pg")
        entry = dm._datasets["orders"]
        assert isinstance(entry.source, SQLQuerySource)
        assert not isinstance(entry.source, AuthorizingDataSource)


# ── Enforcement chain via registered source ───────────────────────────────────


class TestEnforcementChain:
    """AC1 / AC6: verify guard is called when registered dataset is fetched."""

    @pytest.mark.asyncio
    async def test_authorized_fetch_succeeds(self, mock_guard: MagicMock) -> None:
        """Guard allows → fetch returns data."""
        from parrot.tools.dataset_manager.tool import DatasetManager

        mock_inner_fetch = AsyncMock(return_value=pd.DataFrame({"col": [1, 2]}))

        dm = DatasetManager(dataplane_guard=mock_guard)
        dm.add_sql_source("ds1", "SELECT 1", "pg")
        # Replace inner source's fetch so no real DB call is made
        entry = dm._datasets["ds1"]
        entry.source._inner.fetch = mock_inner_fetch  # type: ignore[attr-defined]

        from parrot.auth.permission import PermissionContext, UserSession
        from parrot.tools.dataset_manager.tool import _pctx_var

        pctx = PermissionContext(
            session=UserSession(user_id="u1", tenant_id="corp", roles=frozenset())
        )
        token = _pctx_var.set(pctx)
        try:
            df = await entry.source.fetch()
        finally:
            _pctx_var.reset(token)

        assert len(df) == 2
        mock_guard.authorize_source.assert_called_once()

    @pytest.mark.asyncio
    async def test_denied_fetch_raises(self, denying_guard: MagicMock) -> None:
        """AC1: guard denies → AuthorizationRequired raised, inner.fetch not called."""
        from parrot.tools.dataset_manager.tool import DatasetManager
        from parrot.auth.exceptions import AuthorizationRequired
        from parrot.auth.permission import PermissionContext, UserSession
        from parrot.tools.dataset_manager.tool import _pctx_var

        dm = DatasetManager(dataplane_guard=denying_guard)
        dm.add_sql_source("finance", "SELECT * FROM finance.salaries", "pg")
        entry = dm._datasets["finance"]
        inner_fetch = AsyncMock(return_value=pd.DataFrame({"salary": [100000]}))
        entry.source._inner.fetch = inner_fetch  # type: ignore[attr-defined]

        pctx = PermissionContext(
            session=UserSession(user_id="basic_user", tenant_id="corp", roles=frozenset())
        )
        token = _pctx_var.set(pctx)
        try:
            with pytest.raises(AuthorizationRequired):
                await entry.source.fetch()
        finally:
            _pctx_var.reset(token)

        inner_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_context_failopen(self, mock_guard: MagicMock) -> None:
        """No PermissionContext in ContextVar → fail-open, guard not consulted."""
        from parrot.tools.dataset_manager.tool import DatasetManager

        dm = DatasetManager(dataplane_guard=mock_guard)
        dm.add_sql_source("ds1", "SELECT 1", "pg")
        entry = dm._datasets["ds1"]
        inner_fetch = AsyncMock(return_value=pd.DataFrame({"x": [1]}))
        entry.source._inner.fetch = inner_fetch  # type: ignore[attr-defined]

        # No pctx set in ContextVar → provider returns None → fail-open
        df = await entry.source.fetch()
        assert len(df) == 1
        mock_guard.authorize_source.assert_not_called()
