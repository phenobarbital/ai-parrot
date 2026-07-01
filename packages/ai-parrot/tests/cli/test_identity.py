"""Unit tests for the CLI identity bootstrap's tenant_id resolution (FEAT-267).

Covers the fix for `build_cli_permission_context()` hardcoding
`tenant_id=CLI_CHANNEL` ("cli") — see `sdd/specs/o365-devicecode-followups.spec.md`.
"""
from __future__ import annotations

import pytest

from parrot.cli.identity import (
    CLI_CHANNEL,
    O365_PRINCIPAL_ENV_VAR,
    O365_TENANT_ID_ENV_VAR,
    UNSET_CLI_TENANT,
    build_cli_permission_context,
)


@pytest.fixture(autouse=True)
def _set_principal(monkeypatch):
    """Ensure O365_PRINCIPAL is always set so tenant_id resolution is under test."""
    monkeypatch.setenv(O365_PRINCIPAL_ENV_VAR, "user@contoso.com")


def test_tenant_id_from_env(monkeypatch):
    """With O365_TENANT_ID set, PermissionContext.session.tenant_id matches it exactly."""
    monkeypatch.setenv(O365_TENANT_ID_ENV_VAR, "contoso-tenant")
    ctx = build_cli_permission_context(user_id="user@contoso.com")
    assert ctx.session.tenant_id == "contoso-tenant"


def test_tenant_id_sentinel_when_unset(monkeypatch):
    """With O365_TENANT_ID unset, tenant_id falls back to the sentinel, never CLI_CHANNEL."""
    monkeypatch.delenv(O365_TENANT_ID_ENV_VAR, raising=False)
    ctx = build_cli_permission_context(user_id="user@contoso.com")
    assert ctx.session.tenant_id == UNSET_CLI_TENANT
    assert ctx.session.tenant_id != "cli"
    assert ctx.session.tenant_id != CLI_CHANNEL


def test_tenant_id_blank_env_falls_back_to_sentinel(monkeypatch):
    """A blank (whitespace-only) O365_TENANT_ID is treated as unset."""
    monkeypatch.setenv(O365_TENANT_ID_ENV_VAR, "   ")
    ctx = build_cli_permission_context(user_id="user@contoso.com")
    assert ctx.session.tenant_id == UNSET_CLI_TENANT


def test_roles_remain_empty_frozenset(monkeypatch):
    """roles=frozenset() remains the documented, currently-inert placeholder."""
    monkeypatch.delenv(O365_TENANT_ID_ENV_VAR, raising=False)
    ctx = build_cli_permission_context(user_id="user@contoso.com")
    assert ctx.session.roles == frozenset()
