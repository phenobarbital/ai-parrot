"""Unit tests for DatasetPolicyGuard.

Tests cover:
- Construction and attribute storage
- filter_datasets: allowed subset, empty input, fail-open/fail-closed
- filter_columns: order preservation, composite resource names, fail paths
- can_read_dataset: allow, deny+WARNING, fail-open/fail-closed
- Missing session / user_id → DENY (fail-closed)
"""
from __future__ import annotations

import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.dataset_guard import DatasetPolicyGuard


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def stub_evaluator():
    """Minimal mock PolicyEvaluator with configurable allow/deny."""
    evaluator = MagicMock()
    return evaluator


@pytest.fixture
def pctx_jleon():
    """PermissionContext for jleon@trocglobal.com, no roles."""
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
    """PermissionContext for admin user with admin role."""
    return PermissionContext(
        session=UserSession(
            user_id="admin@trocglobal.com",
            tenant_id="troc",
            roles=frozenset({"admin"}),
            metadata={},
        )
    )


@pytest.fixture
def guard(stub_evaluator):
    """DatasetPolicyGuard with the stub evaluator."""
    return DatasetPolicyGuard(evaluator=stub_evaluator)


def _make_filter_result(allowed: list[str]) -> MagicMock:
    """Build a mock filter_resources result with the given allowed list."""
    result = MagicMock()
    result.allowed = allowed
    return result


def _make_check_result(allowed: bool) -> MagicMock:
    """Build a mock check_access result."""
    result = MagicMock()
    result.allowed = allowed
    result.matched_policy = "test-policy" if not allowed else None
    result.reason = "denied" if not allowed else None
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestDatasetPolicyGuardInit:
    def test_init_with_evaluator(self, guard, stub_evaluator):
        """Constructor stores evaluator and default logger."""
        assert guard._evaluator is stub_evaluator
        assert guard.logger is not None

    def test_init_with_custom_logger(self, stub_evaluator):
        """Constructor stores the provided logger."""
        custom_logger = logging.getLogger("test.custom")
        g = DatasetPolicyGuard(evaluator=stub_evaluator, logger=custom_logger)
        assert g.logger is custom_logger

    def test_default_logger_name(self, stub_evaluator):
        """Default logger uses module name."""
        g = DatasetPolicyGuard(evaluator=stub_evaluator)
        assert g.logger.name == "parrot.auth.dataset_guard"


class TestFilterDatasets:
    @pytest.mark.asyncio
    async def test_filter_datasets_empty_input_no_evaluator_call(
        self, guard, pctx_jleon
    ):
        """Empty input short-circuits; evaluator is never called."""
        result = await guard.filter_datasets(pctx_jleon, [])
        assert result == set()
        guard._evaluator.filter_resources.assert_not_called()

    @pytest.mark.asyncio
    async def test_filter_datasets_allows_subset(self, guard, pctx_jleon):
        """Stub evaluator returns allowed=['a','c']; guard returns {'a','c'}."""
        mock_rt = MagicMock()
        mock_rt.DATASET = "DATASET"
        guard._evaluator.filter_resources.return_value = _make_filter_result(["a", "c"])

        with patch.dict("sys.modules", {
            "navigator_auth.abac.policies.resources": MagicMock(ResourceType=mock_rt),
            "navigator_auth.abac.policies.environment": MagicMock(Environment=MagicMock),
        }):
            result = await guard.filter_datasets(pctx_jleon, ["a", "b", "c"])

        assert result == {"a", "c"}

    @pytest.mark.asyncio
    async def test_filter_datasets_returns_all_when_all_allowed(
        self, guard, pctx_jleon
    ):
        """All names allowed → returns full set."""
        mock_rt = MagicMock()
        guard._evaluator.filter_resources.return_value = _make_filter_result(
            ["sales", "finance"]
        )

        with patch.dict("sys.modules", {
            "navigator_auth.abac.policies.resources": MagicMock(ResourceType=mock_rt),
            "navigator_auth.abac.policies.environment": MagicMock(Environment=MagicMock),
        }):
            result = await guard.filter_datasets(pctx_jleon, ["sales", "finance"])

        assert result == {"sales", "finance"}

    @pytest.mark.asyncio
    async def test_filter_datasets_fail_open_on_importerror(
        self, guard, pctx_jleon
    ):
        """ImportError for navigator-auth → returns all names (fail-open)."""
        with patch.dict("sys.modules", {
            "navigator_auth.abac.policies.resources": None,
        }):
            with patch(
                "parrot.auth.dataset_guard.DatasetPolicyGuard.filter_datasets",
                wraps=guard.filter_datasets,
            ):
                pass

        # Patch the lazy import inside the method to raise ImportError
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        async def _run():
            import builtins
            original = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if "navigator_auth.abac.policies.resources" in name:
                    raise ImportError("navigator-auth not installed")
                return original(name, *args, **kwargs)

            builtins.__import__ = mock_import
            try:
                result = await guard.filter_datasets(pctx_jleon, ["a", "b", "c"])
            finally:
                builtins.__import__ = original
            return result

        result = await _run()
        assert result == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_filter_datasets_fail_closed_on_runtime_error(
        self, guard, pctx_jleon, caplog
    ):
        """RuntimeError from evaluator → returns empty set + WARNING log."""
        mock_rt = MagicMock()
        guard._evaluator.filter_resources.side_effect = RuntimeError("eval error")

        with caplog.at_level(logging.WARNING, logger="parrot.auth.dataset_guard"):
            with patch.dict("sys.modules", {
                "navigator_auth.abac.policies.resources": MagicMock(ResourceType=mock_rt),
                "navigator_auth.abac.policies.environment": MagicMock(Environment=MagicMock),
            }):
                result = await guard.filter_datasets(pctx_jleon, ["sales"])

        assert result == set()
        assert any("PBAC dataset deny" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_filter_datasets_fail_closed_on_missing_session(self, guard):
        """PermissionContext with session=None → DENY (empty set)."""
        ctx = PermissionContext.__new__(PermissionContext)
        ctx.session = None  # type: ignore[assignment]
        ctx.request_id = None
        ctx.channel = None
        ctx.extra = {}

        result = await guard.filter_datasets(ctx, ["sales", "finance"])
        assert result == set()

    @pytest.mark.asyncio
    async def test_filter_datasets_fail_closed_on_missing_user_id(self, guard):
        """session.user_id = None → DENY."""
        ctx = PermissionContext(
            session=UserSession(
                user_id="",  # empty string, still passes type check
                tenant_id="troc",
                roles=frozenset(),
                metadata={},
            )
        )
        # Patch _get_user_id to return None to simulate missing user_id
        original_get_user_id = guard._get_user_id
        guard._get_user_id = lambda c: None  # type: ignore[method-assign]
        try:
            result = await guard.filter_datasets(ctx, ["sales"])
        finally:
            guard._get_user_id = original_get_user_id  # type: ignore[method-assign]
        assert result == set()


class TestFilterColumns:
    @pytest.mark.asyncio
    async def test_filter_columns_empty_input(self, guard, pctx_jleon):
        """Empty columns list → returns empty list without evaluator call."""
        result = await guard.filter_columns(pctx_jleon, "sales", [])
        assert result == []
        guard._evaluator.filter_resources.assert_not_called()

    @pytest.mark.asyncio
    async def test_filter_columns_preserves_order(self, guard, pctx_jleon):
        """Allowed columns returned in original input order."""
        mock_rt = MagicMock()
        # Evaluator returns allowed in a different order
        guard._evaluator.filter_resources.return_value = _make_filter_result(
            ["sales:c3", "sales:c1"]
        )

        with patch.dict("sys.modules", {
            "navigator_auth.abac.policies.resources": MagicMock(ResourceType=mock_rt),
            "navigator_auth.abac.policies.environment": MagicMock(Environment=MagicMock),
        }):
            result = await guard.filter_columns(
                pctx_jleon, "sales", ["c1", "c2", "c3"]
            )

        # Must be in input order (c1, c3), not evaluator return order (c3, c1)
        assert result == ["c1", "c3"]

    @pytest.mark.asyncio
    async def test_filter_columns_composite_resource_names(
        self, guard, pctx_jleon
    ):
        """Evaluator is called with composite 'dataset:column' resource names."""
        mock_rt = MagicMock()
        guard._evaluator.filter_resources.return_value = _make_filter_result(
            ["sales:c1", "sales:c2"]
        )

        with patch.dict("sys.modules", {
            "navigator_auth.abac.policies.resources": MagicMock(ResourceType=mock_rt),
            "navigator_auth.abac.policies.environment": MagicMock(Environment=MagicMock),
        }):
            await guard.filter_columns(pctx_jleon, "sales", ["c1", "c2"])

        call_kwargs = guard._evaluator.filter_resources.call_args.kwargs
        assert call_kwargs["resource_names"] == ["sales:c1", "sales:c2"]
        assert call_kwargs["action"] == "dataset:column:read"

    @pytest.mark.asyncio
    async def test_filter_columns_fail_open_on_importerror(
        self, guard, pctx_jleon
    ):
        """ImportError for navigator-auth → returns all columns (fail-open)."""
        import builtins
        original = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "navigator_auth.abac.policies.resources" in name:
                raise ImportError("navigator-auth not installed")
            return original(name, *args, **kwargs)

        builtins.__import__ = mock_import
        try:
            result = await guard.filter_columns(
                pctx_jleon, "sales", ["c1", "c2", "c3"]
            )
        finally:
            builtins.__import__ = original

        assert result == ["c1", "c2", "c3"]

    @pytest.mark.asyncio
    async def test_filter_columns_fail_closed_on_evaluator_exception(
        self, guard, pctx_jleon, caplog
    ):
        """RuntimeError from evaluator → returns empty list + WARNING."""
        mock_rt = MagicMock()
        guard._evaluator.filter_resources.side_effect = RuntimeError("boom")

        with caplog.at_level(logging.WARNING, logger="parrot.auth.dataset_guard"):
            with patch.dict("sys.modules", {
                "navigator_auth.abac.policies.resources": MagicMock(ResourceType=mock_rt),
                "navigator_auth.abac.policies.environment": MagicMock(Environment=MagicMock),
            }):
                result = await guard.filter_columns(
                    pctx_jleon, "sales", ["c1", "c2"]
                )

        assert result == []
        assert any("PBAC column deny" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_filter_columns_fail_closed_on_missing_session(self, guard):
        """Missing session → DENY (empty list)."""
        ctx = PermissionContext.__new__(PermissionContext)
        ctx.session = None  # type: ignore[assignment]
        ctx.request_id = None
        ctx.channel = None
        ctx.extra = {}

        result = await guard.filter_columns(ctx, "sales", ["c1", "c2"])
        assert result == []


class TestCanReadDataset:
    @pytest.mark.asyncio
    async def test_can_read_dataset_allows(self, guard, pctx_jleon):
        """Evaluator allows access → guard returns True."""
        mock_rt = MagicMock()
        guard._evaluator.check_access.return_value = _make_check_result(allowed=True)

        with patch.dict("sys.modules", {
            "navigator_auth.abac.policies.resources": MagicMock(ResourceType=mock_rt),
            "navigator_auth.abac.policies.environment": MagicMock(Environment=MagicMock),
        }):
            result = await guard.can_read_dataset(pctx_jleon, "sales")

        assert result is True

    @pytest.mark.asyncio
    async def test_can_read_dataset_denies_with_warning(
        self, guard, pctx_jleon, caplog
    ):
        """Evaluator denies → guard returns False + WARNING with user and dataset."""
        mock_rt = MagicMock()
        guard._evaluator.check_access.return_value = _make_check_result(allowed=False)

        with caplog.at_level(logging.WARNING, logger="parrot.auth.dataset_guard"):
            with patch.dict("sys.modules", {
                "navigator_auth.abac.policies.resources": MagicMock(ResourceType=mock_rt),
                "navigator_auth.abac.policies.environment": MagicMock(Environment=MagicMock),
            }):
                result = await guard.can_read_dataset(pctx_jleon, "financial_data")

        assert result is False
        warning_msgs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any("financial_data" in msg for msg in warning_msgs), (
            f"Expected 'financial_data' in WARNING log. Got: {warning_msgs}"
        )
        assert any("jleon@trocglobal.com" in msg for msg in warning_msgs), (
            f"Expected user_id in WARNING log. Got: {warning_msgs}"
        )

    @pytest.mark.asyncio
    async def test_can_read_dataset_fail_open_on_importerror(
        self, guard, pctx_jleon
    ):
        """ImportError for navigator-auth → returns True (fail-open)."""
        import builtins
        original = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "navigator_auth.abac.policies.resources" in name:
                raise ImportError("navigator-auth not installed")
            return original(name, *args, **kwargs)

        builtins.__import__ = mock_import
        try:
            result = await guard.can_read_dataset(pctx_jleon, "sales")
        finally:
            builtins.__import__ = original

        assert result is True

    @pytest.mark.asyncio
    async def test_can_read_dataset_fail_closed_on_evaluator_exception(
        self, guard, pctx_jleon, caplog
    ):
        """RuntimeError from evaluator → returns False (fail-closed) + WARNING."""
        mock_rt = MagicMock()
        guard._evaluator.check_access.side_effect = RuntimeError("eval crash")

        with caplog.at_level(logging.WARNING, logger="parrot.auth.dataset_guard"):
            with patch.dict("sys.modules", {
                "navigator_auth.abac.policies.resources": MagicMock(ResourceType=mock_rt),
                "navigator_auth.abac.policies.environment": MagicMock(Environment=MagicMock),
            }):
                result = await guard.can_read_dataset(pctx_jleon, "financial_data")

        assert result is False
        assert any("PBAC dataset deny" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_can_read_dataset_fail_closed_on_missing_session(self, guard):
        """Missing session → returns False (fail-closed)."""
        ctx = PermissionContext.__new__(PermissionContext)
        ctx.session = None  # type: ignore[assignment]
        ctx.request_id = None
        ctx.channel = None
        ctx.extra = {}

        result = await guard.can_read_dataset(ctx, "financial_data")
        assert result is False


class TestImportExport:
    def test_importable_from_parrot_auth(self):
        """DatasetPolicyGuard is importable from parrot.auth."""
        from parrot.auth import DatasetPolicyGuard as DPG  # noqa: F401
        assert DPG is DatasetPolicyGuard
