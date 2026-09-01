"""Unit tests for principal resolution + tenant binding (FEAT-477, TASK-2604)."""

import pytest
from aiohttp import web
from parrot.auth.context import _pctx_var
from parrot.auth.permission import PermissionContext
from parrot.mcp.principal_guard import (
    published_principal,
    resolve_principal,
    resolve_tenant,
    runtime_key,
)


class _Cfg:
    def __init__(self, default_tenant_id=None):
        self.default_tenant_id = default_tenant_id


@pytest.fixture
def cfg_with_default():
    return _Cfg(default_tenant_id="mount-default")


@pytest.fixture
def cfg_without_default():
    return _Cfg(default_tenant_id=None)


@pytest.fixture
def oauth_req():
    """A request populated the way `_authenticate_oauth_external` leaves it."""
    return {
        "mcp_user": {
            "user_id": "user-oauth-1",
            "scopes": ["read", "write"],
            "token_info": {"sub": "user-oauth-1", "client_id": "claude-uid"},
        }
    }


@pytest.fixture
def apikey_req():
    """A request populated the way `_authenticate_api_key` leaves it (no token_info)."""
    return {"mcp_user": {"user_id": "user-apikey-1", "scopes": ["read"]}}


class _AuditSpy:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, payload: dict) -> None:
        self.calls.append(payload)

    @property
    def last(self) -> dict:
        return self.calls[-1]


@pytest.fixture
def audit_spy():
    return _AuditSpy()


class TestPrincipalResolution:
    async def test_principal_from_oauth_and_api_key(self, oauth_req, apikey_req, cfg_with_default):
        a = await resolve_principal(oauth_req, cfg_with_default)
        b = await resolve_principal(apikey_req, cfg_with_default)
        assert isinstance(a, PermissionContext) and isinstance(b, PermissionContext)
        assert a.session.user_id == "user-oauth-1"
        assert b.session.user_id == "user-apikey-1"
        assert type(a) is type(b)
        assert a.channel == b.channel == "mcp"

    @pytest.mark.parametrize(
        "info,expected",
        [
            ({"tenant_id": "t1"}, "t1"),
            ({"org_id": "t2"}, "t2"),
            ({"tenant_id": "t1", "org_id": "t2"}, "t1"),
            ({}, "mount-default"),
        ],
    )
    def test_tenant_precedence(self, info, expected, cfg_with_default):
        assert resolve_tenant(info, cfg_with_default) == expected

    async def test_fail_closed_when_no_tenant(self, oauth_req, cfg_without_default, audit_spy):
        resp = await resolve_principal(oauth_req, cfg_without_default, audit_hook=audit_spy)
        assert isinstance(resp, web.Response)
        assert resp.status == 401
        assert audit_spy.last["decision"] == "principal_unresolved"

    async def test_fail_closed_when_no_mcp_user(self, cfg_with_default, audit_spy):
        resp = await resolve_principal({}, cfg_with_default, audit_hook=audit_spy)
        assert resp.status == 401
        assert audit_spy.last["decision"] == "principal_unresolved"

    def test_client_id_never_becomes_tenant(self, cfg_without_default):
        assert resolve_tenant({"client_id": "claude-uid"}, cfg_without_default) is None

    async def test_pctx_var_published_and_reset(self, oauth_req, cfg_with_default):
        pctx = await resolve_principal(oauth_req, cfg_with_default)
        assert _pctx_var.get() is None
        seen = {}
        async with published_principal(pctx):
            seen["v"] = _pctx_var.get()
        assert seen["v"] is pctx
        assert _pctx_var.get() is None

    async def test_pctx_var_reset_even_on_exception(self, oauth_req, cfg_with_default):
        pctx = await resolve_principal(oauth_req, cfg_with_default)
        with pytest.raises(RuntimeError):
            async with published_principal(pctx):
                raise RuntimeError("boom")
        assert _pctx_var.get() is None

    async def test_runtime_key_is_tenant_and_principal(self, oauth_req, cfg_with_default):
        pctx = await resolve_principal(oauth_req, cfg_with_default)
        assert runtime_key(pctx) == ("mount-default", "user-oauth-1")
