"""Unit tests for DatabaseQueryTool FEAT-228 data-plane authorization (TASK-1498).

Validates:
- AC3: guarded driver+query denied for unauthorized user.
- AC3: guarded driver+query allowed for authorized user (RLS-aware).
- test_connection gated on driver:connect.
- No guard configured → existing behavior unchanged.
- AC12: DML in query → ReadOnlyViolation propagates.
- No PermissionContext → fail-open.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_guard() -> MagicMock:
    """Mock DataPlanePolicyGuard that allows everything by default."""
    guard = MagicMock()
    guard.is_sensitive_driver.return_value = False
    guard.authorize_source = AsyncMock()
    guard.rls_predicates = AsyncMock(return_value=[])
    guard.can_connect_driver = AsyncMock(return_value=True)
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
    guard.can_connect_driver = AsyncMock(return_value=False)
    return guard


@pytest.fixture
def pctx():
    from parrot.auth.permission import PermissionContext, UserSession
    return PermissionContext(
        session=UserSession(user_id="test_user", tenant_id="corp", roles=frozenset())
    )


# ── Constructor ───────────────────────────────────────────────────────────────


class TestDatabaseQueryToolInit:
    def test_no_guard_by_default(self) -> None:
        """No dataplane_guard configured → _dataplane_guard is None."""
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool()
        assert tool._dataplane_guard is None

    def test_guard_stored_on_init(self, mock_guard: MagicMock) -> None:
        """dataplane_guard kwarg stored as _dataplane_guard."""
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool(dataplane_guard=mock_guard)
        assert tool._dataplane_guard is mock_guard


# ── _execute authorization gate ───────────────────────────────────────────────


class TestExecuteAuthzGate:
    @pytest.mark.asyncio
    async def test_no_guard_no_enforcement(self) -> None:
        """AC8: no guard → _execute runs without authorization check."""
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        import pandas as pd

        tool = DatabaseQueryTool()
        # Mock the actual DB execution layer
        with patch.object(
            tool,
            "_execute_database_query",
            new=AsyncMock(return_value=pd.DataFrame({"x": [1]})),
        ):
            result = await tool._execute(driver="pg", query="SELECT 1")
        assert result is not None

    @pytest.mark.asyncio
    async def test_guard_no_context_failopen(self, mock_guard: MagicMock) -> None:
        """No PermissionContext in ContextVar → fail-open, guard not consulted."""
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        import pandas as pd

        tool = DatabaseQueryTool(dataplane_guard=mock_guard)
        with patch.object(
            tool,
            "_execute_database_query",
            new=AsyncMock(return_value=pd.DataFrame({"x": [1]})),
        ):
            result = await tool._execute(driver="pg", query="SELECT 1")

        mock_guard.authorize_source.assert_not_called()
        assert result is not None

    @pytest.mark.asyncio
    async def test_guard_denies_raises(
        self, denying_guard: MagicMock, pctx
    ) -> None:
        """AC3: guard denies → AuthorizationRequired raised."""
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        from parrot.auth.exceptions import AuthorizationRequired
        from parrot.tools.dataset_manager.tool import _pctx_var

        tool = DatabaseQueryTool(dataplane_guard=denying_guard)

        token = _pctx_var.set(pctx)
        try:
            with pytest.raises(AuthorizationRequired):
                await tool._execute(
                    driver="pg",
                    query="SELECT * FROM finance.salaries",
                )
        finally:
            _pctx_var.reset(token)

    @pytest.mark.asyncio
    async def test_guard_allows_proceeds(
        self, mock_guard: MagicMock, pctx
    ) -> None:
        """AC3: guard allows → query proceeds to execution."""
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        from parrot.tools.dataset_manager.tool import _pctx_var
        import pandas as pd

        tool = DatabaseQueryTool(dataplane_guard=mock_guard)
        _db_mock = AsyncMock(return_value=pd.DataFrame({"id": [1, 2]}))

        token = _pctx_var.set(pctx)
        try:
            with patch.object(tool, "_execute_database_query", new=_db_mock):
                result = await tool._execute(
                    driver="pg",
                    query="SELECT * FROM orders",
                )
        finally:
            _pctx_var.reset(token)

        mock_guard.authorize_source.assert_called_once()
        # _execute returns a response dict with result key
        assert result["status"] == "success"
        assert len(result["result"]) == 2

    @pytest.mark.asyncio
    async def test_readonly_violation_propagates(
        self, mock_guard: MagicMock, pctx
    ) -> None:
        """AC12: DML query → ReadOnlyViolation propagates from resolver."""
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        from parrot.tools.dataset_manager.sources.resolver import ReadOnlyViolation
        from parrot.tools.dataset_manager.tool import _pctx_var

        tool = DatabaseQueryTool(dataplane_guard=mock_guard)

        token = _pctx_var.set(pctx)
        try:
            with pytest.raises(ReadOnlyViolation):
                await tool._execute(
                    driver="pg",
                    query="DROP TABLE finance.salaries",
                )
        finally:
            _pctx_var.reset(token)


# ── test_connection gate ──────────────────────────────────────────────────────


class TestTestConnectionGate:
    @pytest.mark.asyncio
    async def test_connection_no_guard(self) -> None:
        """No guard → test_connection runs without driver:connect check."""
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        import pandas as pd

        tool = DatabaseQueryTool()
        with patch.object(
            tool,
            "_execute_database_query",
            new=AsyncMock(return_value=pd.DataFrame({"test_column": [1]})),
        ):
            result = await tool.test_connection(driver="pg")
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_connection_denied_raises(
        self, denying_guard: MagicMock, pctx
    ) -> None:
        """test_connection gated on driver:connect — denied raises AuthorizationRequired."""
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        from parrot.auth.exceptions import AuthorizationRequired
        from parrot.tools.dataset_manager.tool import _pctx_var

        tool = DatabaseQueryTool(dataplane_guard=denying_guard)

        token = _pctx_var.set(pctx)
        try:
            with pytest.raises(AuthorizationRequired):
                await tool.test_connection(driver="bigquery_finance")
        finally:
            _pctx_var.reset(token)

    @pytest.mark.asyncio
    async def test_connection_allowed_proceeds(
        self, mock_guard: MagicMock, pctx
    ) -> None:
        """test_connection allowed when driver:connect passes."""
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        from parrot.tools.dataset_manager.tool import _pctx_var
        import pandas as pd

        tool = DatabaseQueryTool(dataplane_guard=mock_guard)

        token = _pctx_var.set(pctx)
        try:
            with patch.object(
                tool,
                "_execute_database_query",
                new=AsyncMock(return_value=pd.DataFrame({"test_column": [1]})),
            ):
                result = await tool.test_connection(driver="pg")
        finally:
            _pctx_var.reset(token)

        mock_guard.can_connect_driver.assert_called_once()
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_connection_no_context_failopen(
        self, mock_guard: MagicMock
    ) -> None:
        """No PermissionContext → test_connection proceeds without guard check."""
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        import pandas as pd

        tool = DatabaseQueryTool(dataplane_guard=mock_guard)
        # No pctx in ContextVar → fail-open
        with patch.object(
            tool,
            "_execute_database_query",
            new=AsyncMock(return_value=pd.DataFrame({"test_column": [1]})),
        ):
            result = await tool.test_connection(driver="pg")

        mock_guard.can_connect_driver.assert_not_called()
        assert result["status"] == "success"
