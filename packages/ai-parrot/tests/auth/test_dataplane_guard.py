"""Tests for DataPlanePolicyGuard (FEAT-228 / TASK-1495)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.auth.dataplane_guard import DataPlanePolicyGuard
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.rls_registry import RlsRegistry
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources


@pytest.fixture
def mock_evaluator() -> MagicMock:
    """Mock PolicyEvaluator that allows everything by default."""
    ev = MagicMock()
    allow_result = MagicMock(allowed=True)
    deny_result = MagicMock(allowed=False)
    ev.check_access = MagicMock(return_value=allow_result)
    filter_result = MagicMock(allowed=["pg:sales.orders"])
    ev.filter_resources = MagicMock(return_value=filter_result)
    ev._allow_result = allow_result
    ev._deny_result = deny_result
    return ev


@pytest.fixture
def guard(mock_evaluator: MagicMock) -> DataPlanePolicyGuard:
    return DataPlanePolicyGuard(
        evaluator=mock_evaluator,
        rls_registry=RlsRegistry(),
        sensitive_drivers=frozenset({"bigquery_finance"}),
    )


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


class TestDataPlanePolicyGuard:
    """Verify the full guard interface."""

    @pytest.mark.asyncio
    async def test_can_connect_allowed(
        self, guard: DataPlanePolicyGuard, pctx: PermissionContext
    ) -> None:
        """can_connect_driver returns True when evaluator allows."""
        assert await guard.can_connect_driver(pctx, "pg") is True

    @pytest.mark.asyncio
    async def test_can_connect_denied(
        self,
        guard: DataPlanePolicyGuard,
        pctx: PermissionContext,
        mock_evaluator: MagicMock,
    ) -> None:
        """can_connect_driver returns False when evaluator denies."""
        mock_evaluator.check_access.return_value = MagicMock(allowed=False)
        assert await guard.can_connect_driver(pctx, "pg") is False

    @pytest.mark.asyncio
    async def test_can_connect_evaluator_error_fail_closed(
        self,
        guard: DataPlanePolicyGuard,
        pctx: PermissionContext,
        mock_evaluator: MagicMock,
    ) -> None:
        """Evaluator exception → fail-closed (returns False)."""
        mock_evaluator.check_access.side_effect = RuntimeError("eval error")
        result = await guard.can_connect_driver(pctx, "pg")
        assert result is False

    @pytest.mark.asyncio
    async def test_authorize_source_denied_driver_raises(
        self,
        guard: DataPlanePolicyGuard,
        pctx: PermissionContext,
        mock_evaluator: MagicMock,
    ) -> None:
        """authorize_source raises AuthorizationRequired when driver denied."""
        mock_evaluator.check_access.return_value = MagicMock(allowed=False)
        resources = PhysicalResources(driver="pg", tables={"pg:finance.salaries"})
        with pytest.raises(AuthorizationRequired):
            await guard.authorize_source(pctx, resources)

    @pytest.mark.asyncio
    async def test_authorize_source_denied_table_raises(
        self,
        guard: DataPlanePolicyGuard,
        pctx: PermissionContext,
        mock_evaluator: MagicMock,
    ) -> None:
        """authorize_source raises AuthorizationRequired when table denied."""
        # Driver allowed, but table denied
        def check_side_effect(eval_ctx, rtype, *args, **kwargs):
            if rtype == "driver":
                return MagicMock(allowed=True)
            return MagicMock(allowed=False)

        mock_evaluator.check_access.side_effect = check_side_effect
        mock_evaluator.filter_resources.return_value = MagicMock(allowed=[])
        resources = PhysicalResources(driver="pg", tables={"pg:finance.salaries"})
        with pytest.raises(AuthorizationRequired):
            await guard.authorize_source(pctx, resources)

    @pytest.mark.asyncio
    async def test_authorize_source_allowed(
        self,
        guard: DataPlanePolicyGuard,
        pctx: PermissionContext,
        mock_evaluator: MagicMock,
    ) -> None:
        """authorize_source succeeds (no exception) when all gates pass."""
        mock_evaluator.filter_resources.return_value = MagicMock(
            allowed=["pg:sales.orders"]
        )
        resources = PhysicalResources(driver="pg", tables={"pg:sales.orders"})
        # Should not raise
        await guard.authorize_source(pctx, resources)

    @pytest.mark.asyncio
    async def test_none_context_failopen(
        self, guard: DataPlanePolicyGuard
    ) -> None:
        """ctx=None → fail-open (no AuthorizationRequired)."""
        resources = PhysicalResources(driver="pg", tables={"pg:finance.salaries"})
        # Should not raise
        await guard.authorize_source(None, resources)

    def test_is_sensitive_driver_true(self, guard: DataPlanePolicyGuard) -> None:
        assert guard.is_sensitive_driver("bigquery_finance") is True

    def test_is_sensitive_driver_false(self, guard: DataPlanePolicyGuard) -> None:
        assert guard.is_sensitive_driver("pg") is False

    @pytest.mark.asyncio
    async def test_rls_predicates_empty_when_no_rules(
        self,
        guard: DataPlanePolicyGuard,
        pctx: PermissionContext,
    ) -> None:
        """rls_predicates returns [] when no rules match."""
        resources = PhysicalResources(driver="pg", tables={"pg:sales.orders"})
        predicates = await guard.rls_predicates(pctx, resources)
        assert predicates == []

    @pytest.mark.asyncio
    async def test_rls_predicates_with_rule(
        self,
        mock_evaluator: MagicMock,
        pctx: PermissionContext,
    ) -> None:
        """rls_predicates returns rendered predicates when rules match."""
        from parrot.auth.rls_registry import RlsRegistry, RlsRule

        registry = RlsRegistry()
        registry.register(
            RlsRule(
                driver="pg",
                table="sales.orders",
                predicate_template="region IN (:subject.programs)",
                subject_attribute="programs",
            )
        )
        # pctx has programs=[] → deny-all predicate rendered
        guard_with_rules = DataPlanePolicyGuard(
            evaluator=mock_evaluator,
            rls_registry=registry,
        )
        resources = PhysicalResources(driver="pg", tables={"pg:sales.orders"})
        predicates = await guard_with_rules.rls_predicates(pctx, resources)
        assert len(predicates) == 1
        # Empty programs → deny-all
        assert predicates[0].sql_predicate in ("1=0", "FALSE")


class TestDataPlanePolicyGuardExport:
    """Verify the guard is exported from parrot.auth."""

    def test_import_from_parrot_auth(self) -> None:
        from parrot.auth import DataPlanePolicyGuard as Guard

        assert Guard is DataPlanePolicyGuard
