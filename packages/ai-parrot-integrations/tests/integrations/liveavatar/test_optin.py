"""Unit tests for the per-tenant opt-in gating module (TASK-008 + TASK-1597).

Verifies ``is_avatar_enabled`` under various env configurations:
- Wildcard allows any tenant.
- Named tenant in allowlist → allowed.
- Unknown tenant → denied (default-deny).
- Empty tenant_id → denied.
- LIVEAVATAR_ENABLED_AGENTS further restricts by agent name.

Also verifies ``is_fullmode_enabled`` (TASK-1597):
- Superset gate: base avatar gate must pass before fullmode gate.
- LIVEAVATAR_FULLMODE_ENABLED_TENANTS controls fullmode allowlist.
- Wildcard, per-tenant, and empty configurations.
"""
from __future__ import annotations

import os
from unittest.mock import patch


from parrot.integrations.liveavatar.optin import is_avatar_enabled, is_fullmode_enabled


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


def _env_fullmode(**kwargs: str):
    """Patch.dict helper for fullmode tests — clears all relevant env vars."""
    base = {
        "LIVEAVATAR_ENABLED_TENANTS": "",
        "LIVEAVATAR_ENABLED_AGENTS": "",
        "LIVEAVATAR_FULLMODE_ENABLED_TENANTS": "",
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


# ---------------------------------------------------------------------------
# is_fullmode_enabled tests (TASK-1597)
# ---------------------------------------------------------------------------


class TestIsFullmodeEnabled:
    """Tests for ``is_fullmode_enabled`` — superset of base avatar gate."""

    def test_disabled_when_avatar_disabled(self) -> None:
        """Base avatar gate must pass first — if avatar disabled, fullmode denied."""
        with _env_fullmode(
            LIVEAVATAR_ENABLED_TENANTS="",
            LIVEAVATAR_FULLMODE_ENABLED_TENANTS="*",
        ):
            assert is_fullmode_enabled(tenant_id="acme") is False

    def test_disabled_when_fullmode_env_not_set(self) -> None:
        """Avatar enabled but LIVEAVATAR_FULLMODE_ENABLED_TENANTS absent → False."""
        with _env_fullmode(
            LIVEAVATAR_ENABLED_TENANTS="*",
            LIVEAVATAR_FULLMODE_ENABLED_TENANTS="",
        ):
            assert is_fullmode_enabled(tenant_id="acme") is False

    def test_wildcard_enables_all(self) -> None:
        """Both wildcard env vars → fullmode allowed for any tenant."""
        with _env_fullmode(
            LIVEAVATAR_ENABLED_TENANTS="*",
            LIVEAVATAR_FULLMODE_ENABLED_TENANTS="*",
        ):
            assert is_fullmode_enabled(tenant_id="acme") is True
            assert is_fullmode_enabled(tenant_id="any-other") is True

    def test_specific_tenant_match(self) -> None:
        """Avatar wildcard + specific fullmode tenants — only listed tenants allowed."""
        with _env_fullmode(
            LIVEAVATAR_ENABLED_TENANTS="*",
            LIVEAVATAR_FULLMODE_ENABLED_TENANTS="acme,beta",
        ):
            assert is_fullmode_enabled(tenant_id="acme") is True
            assert is_fullmode_enabled(tenant_id="beta") is True
            assert is_fullmode_enabled(tenant_id="other") is False

    def test_tenant_in_avatar_but_not_fullmode(self) -> None:
        """Tenant in avatar allowlist but NOT fullmode allowlist → False."""
        with _env_fullmode(
            LIVEAVATAR_ENABLED_TENANTS="acme,demo",
            LIVEAVATAR_FULLMODE_ENABLED_TENANTS="demo",
        ):
            assert is_fullmode_enabled(tenant_id="acme") is False
            assert is_fullmode_enabled(tenant_id="demo") is True

    def test_none_tenant_id_denied(self) -> None:
        """None tenant_id → always denied (default-deny via base gate)."""
        with _env_fullmode(
            LIVEAVATAR_ENABLED_TENANTS="*",
            LIVEAVATAR_FULLMODE_ENABLED_TENANTS="*",
        ):
            assert is_fullmode_enabled(tenant_id=None) is False

    def test_empty_tenant_id_denied(self) -> None:
        """Empty string tenant_id → always denied."""
        with _env_fullmode(
            LIVEAVATAR_ENABLED_TENANTS="*",
            LIVEAVATAR_FULLMODE_ENABLED_TENANTS="*",
        ):
            assert is_fullmode_enabled(tenant_id="") is False

    def test_agent_name_gate_propagated(self) -> None:
        """agent_name gate from is_avatar_enabled propagates to fullmode gate."""
        with _env_fullmode(
            LIVEAVATAR_ENABLED_TENANTS="acme",
            LIVEAVATAR_ENABLED_AGENTS="allowed-bot",
            LIVEAVATAR_FULLMODE_ENABLED_TENANTS="*",
        ):
            assert is_fullmode_enabled(tenant_id="acme", agent_name="allowed-bot") is True
            assert is_fullmode_enabled(tenant_id="acme", agent_name="blocked-bot") is False

    def test_fullmode_whitespace_tenant_ignored(self) -> None:
        """Whitespace-only entries in the tenant list are ignored."""
        with _env_fullmode(
            LIVEAVATAR_ENABLED_TENANTS="*",
            LIVEAVATAR_FULLMODE_ENABLED_TENANTS="  ,acme,  ",
        ):
            assert is_fullmode_enabled(tenant_id="acme") is True
            assert is_fullmode_enabled(tenant_id="other") is False
