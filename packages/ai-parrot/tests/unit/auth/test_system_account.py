"""Unit tests for the system-account principal + fail-closed guard (FEAT-326)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from parrot.auth.permission import PermissionContext
from parrot.auth.system_account import (
    SystemAccount,
    SystemAccountNotProvisioned,
    resolve_system_account_context,
    run_scheduled_refresh,
)

_ENV = ("PARROT_SYSTEM_ACCOUNT_ID", "PARROT_SYSTEM_ACCOUNT_TENANT",
        "PARROT_SYSTEM_ACCOUNT_ROLES")


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for key in _ENV:
        monkeypatch.delenv(key, raising=False)


class TestSystemAccount:
    def test_from_env_none_when_unset(self):
        assert SystemAccount.from_env() is None

    def test_from_env_parses_roles(self, monkeypatch):
        monkeypatch.setenv("PARROT_SYSTEM_ACCOUNT_ID", "svc-reports")
        monkeypatch.setenv("PARROT_SYSTEM_ACCOUNT_ROLES", "reports.read, reports.run")
        acct = SystemAccount.from_env()
        assert acct is not None
        assert acct.account_id == "svc-reports"
        assert acct.roles == frozenset({"reports.read", "reports.run"})

    def test_resolves_permission_context(self):
        acct = SystemAccount(account_id="svc-reports", roles=frozenset({"reports.run"}))
        ctx = resolve_system_account_context(account=acct)
        assert isinstance(ctx, PermissionContext)
        assert ctx  # truthy — never a fail-open falsy pctx
        assert ctx.session.user_id == "svc-reports"
        assert ctx.channel == "scheduler"

    def test_resolves_from_env(self, monkeypatch):
        monkeypatch.setenv("PARROT_SYSTEM_ACCOUNT_ID", "svc-x")
        ctx = resolve_system_account_context(channel="rest")
        assert ctx.session.user_id == "svc-x"
        assert ctx.channel == "rest"

    def test_missing_provisioning_fails_closed(self):
        with pytest.raises(SystemAccountNotProvisioned):
            resolve_system_account_context()


class TestScheduledRefreshGuard:
    async def test_guard_passes_real_pctx(self):
        runner = type("R", (), {})()
        runner.run = AsyncMock(return_value="artifact")
        acct = SystemAccount(account_id="svc-reports")
        result = await run_scheduled_refresh(runner, "daily", account=acct)
        assert result == "artifact"
        # pctx forwarded and is NOT None.
        _, kwargs = runner.run.call_args
        assert kwargs["pctx"] is not None
        assert isinstance(kwargs["pctx"], PermissionContext)

    async def test_guard_refuses_when_unprovisioned(self):
        runner = type("R", (), {})()
        runner.run = AsyncMock(return_value="artifact")
        with pytest.raises(SystemAccountNotProvisioned):
            await run_scheduled_refresh(runner, "daily")
        runner.run.assert_not_called()
