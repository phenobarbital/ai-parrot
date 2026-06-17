"""Unit tests for the per-tenant opt-in gating module (TASK-008).

Verifies ``is_avatar_enabled`` under various env configurations:
- Wildcard allows any tenant.
- Named tenant in allowlist → allowed.
- Unknown tenant → denied (default-deny).
- Empty tenant_id → denied.
- LIVEAVATAR_ENABLED_AGENTS further restricts by agent name.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from parrot.integrations.liveavatar.optin import is_avatar_enabled


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env(**kwargs: str):
    """Patch.dict helper that also ensures absent vars are cleared."""
    base = {
        "LIVEAVATAR_ENABLED_TENANTS": "",
        "LIVEAVATAR_ENABLED_AGENTS": "",
    }
    base.update(kwargs)
    return patch.dict(os.environ, base)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_optin_enabled_tenant() -> None:
    """Tenant present in LIVEAVATAR_ENABLED_TENANTS → True."""
    with _env(LIVEAVATAR_ENABLED_TENANTS="t1,t2"):
        assert is_avatar_enabled(tenant_id="t1") is True


def test_optin_default_deny_unknown_tenant() -> None:
    """Unknown tenant → False."""
    with _env(LIVEAVATAR_ENABLED_TENANTS="t1,t2"):
        assert is_avatar_enabled(tenant_id="unknown") is False


def test_optin_default_deny_env_not_set() -> None:
    """LIVEAVATAR_ENABLED_TENANTS absent → False for any tenant."""
    with _env(LIVEAVATAR_ENABLED_TENANTS=""):
        assert is_avatar_enabled(tenant_id="t1") is False


def test_optin_default_deny_empty_tenant_id() -> None:
    """None or empty tenant_id → False regardless of allowlist."""
    with _env(LIVEAVATAR_ENABLED_TENANTS="t1"):
        assert is_avatar_enabled(tenant_id=None) is False
    with _env(LIVEAVATAR_ENABLED_TENANTS="t1"):
        assert is_avatar_enabled(tenant_id="") is False


def test_optin_wildcard_allows_all_tenants() -> None:
    """LIVEAVATAR_ENABLED_TENANTS=* allows any tenant."""
    with _env(LIVEAVATAR_ENABLED_TENANTS="*"):
        assert is_avatar_enabled(tenant_id="any-tenant") is True
        assert is_avatar_enabled(tenant_id="another") is True


def test_optin_agent_gate_allows_known_agent() -> None:
    """Tenant allowed + agent in LIVEAVATAR_ENABLED_AGENTS → True."""
    with _env(LIVEAVATAR_ENABLED_TENANTS="t1", LIVEAVATAR_ENABLED_AGENTS="bot-a,bot-b"):
        assert is_avatar_enabled(tenant_id="t1", agent_name="bot-a") is True


def test_optin_agent_gate_denies_unknown_agent() -> None:
    """Tenant allowed but agent NOT in LIVEAVATAR_ENABLED_AGENTS → False."""
    with _env(LIVEAVATAR_ENABLED_TENANTS="t1", LIVEAVATAR_ENABLED_AGENTS="bot-a"):
        assert is_avatar_enabled(tenant_id="t1", agent_name="bot-unknown") is False


def test_optin_no_agent_gate_when_env_absent() -> None:
    """When LIVEAVATAR_ENABLED_AGENTS is absent, any agent_name is accepted."""
    with _env(LIVEAVATAR_ENABLED_TENANTS="t1", LIVEAVATAR_ENABLED_AGENTS=""):
        assert is_avatar_enabled(tenant_id="t1", agent_name="any-agent") is True
        assert is_avatar_enabled(tenant_id="t1", agent_name=None) is True


def test_optin_multiple_tenants_in_allowlist() -> None:
    """Multiple tenants — both included and excluded."""
    with _env(LIVEAVATAR_ENABLED_TENANTS="acme,demo,internal-qa"):
        assert is_avatar_enabled(tenant_id="acme") is True
        assert is_avatar_enabled(tenant_id="demo") is True
        assert is_avatar_enabled(tenant_id="internal-qa") is True
        assert is_avatar_enabled(tenant_id="external") is False
