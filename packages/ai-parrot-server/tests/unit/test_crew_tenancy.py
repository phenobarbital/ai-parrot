"""Unit tests for the session-derived tenant resolver (FEAT-446 TASK-2322)."""
from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from navigator_auth.conf import AUTH_SESSION_OBJECT
from parrot import conf
from parrot.handlers.crew._tenancy import resolve_session_tenant


def _make_request(userinfo=None):
    req = make_mocked_request("GET", "/api/v1/crew")
    req.session = {AUTH_SESSION_OBJECT: userinfo} if userinfo is not None else {}
    return req


@pytest.fixture(autouse=True)
def _reset_saas_mode(monkeypatch):
    # Default to legacy mode unless a test explicitly opts into SaaS mode.
    monkeypatch.setattr(conf, "PARROT_SAAS_MODE", False)
    yield


class TestResolveSessionTenant:
    async def test_claim_priority(self):
        request = _make_request(
            {"tenant_id": "acme", "programs": ["other-program"]}
        )

        tenant = await resolve_session_tenant(request)

        assert tenant == "acme"

    async def test_programs_fallback(self):
        request = _make_request({"programs": ["acme", "beta"]})

        tenant = await resolve_session_tenant(request)

        assert tenant == "acme"

    async def test_saas_mode_403(self, monkeypatch):
        monkeypatch.setattr(conf, "PARROT_SAAS_MODE", True)
        request = _make_request({})

        with pytest.raises(web.HTTPForbidden):
            await resolve_session_tenant(request)

    async def test_legacy_global(self):
        request = _make_request({})

        tenant = await resolve_session_tenant(request)

        assert tenant == "global"

    async def test_declared_mismatch_400(self):
        request = _make_request({"tenant_id": "acme"})

        with pytest.raises(web.HTTPBadRequest):
            await resolve_session_tenant(request, declared="other-tenant")

    async def test_declared_match_ok(self):
        request = _make_request({"tenant_id": "acme"})

        tenant = await resolve_session_tenant(request, declared="acme")

        assert tenant == "acme"

    async def test_declared_none_skips_check(self):
        request = _make_request({"tenant_id": "acme"})

        tenant = await resolve_session_tenant(request, declared=None)

        assert tenant == "acme"

    async def test_saas_mode_declared_mismatch_still_400(self, monkeypatch):
        """Declared-mismatch check applies regardless of SaaS mode."""
        monkeypatch.setattr(conf, "PARROT_SAAS_MODE", True)
        request = _make_request({"tenant_id": "acme"})

        with pytest.raises(web.HTTPBadRequest):
            await resolve_session_tenant(request, declared="other-tenant")

    async def test_no_session_falls_back_to_legacy_global(self, monkeypatch):
        request = make_mocked_request("GET", "/api/v1/crew")

        async def _fake_get_session(req):
            return None

        monkeypatch.setattr(
            "navigator_session.get_session", _fake_get_session
        )

        tenant = await resolve_session_tenant(request)

        assert tenant == "global"
