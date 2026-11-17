"""FEAT-734 M2 -- tenant precedence and bearer resolution."""

from types import SimpleNamespace

import pytest

from parrot.integrations.msteams.formdesigner_identity import TenantUnresolved, resolve_bearer, resolve_form_tenant

GUID_A = "11111111-2222-3333-4444-555555555555"
GUID_B = "99999999-8888-7777-6666-555555555555"


def _session(**kw: object) -> SimpleNamespace:
    base = dict(authenticated=True, nav_session_token="nav-tok", nav_user_id="u1", tenant_id=GUID_A)
    return SimpleNamespace(**{**base, **kw})


def test_tenant_precedence_aad_map_wins() -> None:
    result = resolve_form_tenant(
        asserted_tenant_id=GUID_A,
        session_tenant_id=GUID_B,
        tenant_map={GUID_A: "acme", GUID_B: "other"},
        config_tenant="configured",
    )

    assert result.tenant == "acme"
    assert result.source == "aad_map"


def test_tenant_precedence_session_guid_when_activity_absent() -> None:
    result = resolve_form_tenant(
        asserted_tenant_id=None,
        session_tenant_id=GUID_B,
        tenant_map={GUID_B: "other"},
        config_tenant="configured",
    )

    assert result.tenant == "other"
    assert result.source == "session_aad_map"


def test_tenant_precedence_unmapped_guid_never_leaks() -> None:
    result = resolve_form_tenant(
        asserted_tenant_id=GUID_A,
        session_tenant_id=GUID_B,
        tenant_map={},
        config_tenant="configured",
    )

    assert result.tenant == "configured"
    assert result.tenant not in {GUID_A, GUID_B}


def test_tenant_precedence_config_last() -> None:
    result = resolve_form_tenant(
        asserted_tenant_id=None,
        session_tenant_id=None,
        tenant_map=None,
        config_tenant="configured",
    )

    assert result.tenant == "configured"
    assert result.source == "config"


def test_tenant_unresolved_raises() -> None:
    with pytest.raises(TenantUnresolved):
        resolve_form_tenant(
            asserted_tenant_id=GUID_A,
            session_tenant_id=None,
            tenant_map={},
            config_tenant=None,
        )


def test_resolve_bearer_requires_authenticated() -> None:
    assert resolve_bearer(_session(authenticated=False)) is None
    assert resolve_bearer(_session(nav_session_token=None)) is None


def test_resolve_bearer_rejects_expired() -> None:
    assert resolve_bearer(_session(), expired=True) is None
