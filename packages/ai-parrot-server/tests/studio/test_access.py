"""FEAT-605 M2 — StudioAccess rule and _studio_partition override."""
from __future__ import annotations

import pytest
from aiohttp import web
from navigator_session.data import SessionData
from parrot.handlers.scope import RequestScope
from parrot.handlers.studio._base import StudioBaseView
from parrot.handlers.studio.access import (
    StudioAccess,
    StudioTenantRequired,
    StudioVisibilityRecord,
    build_tool_scope,
)
from parrot.handlers.studio.storage.models import StudioPartition
from parrot.handlers.studio.storage.testing import InMemoryStudioRepositories


def _scope(**kw) -> RequestScope:
    base = dict(user_id="7", tenant="acme", groups=frozenset({"g1"}))
    base.update(kw)
    return RequestScope(**base)


def _rec(**kw) -> StudioVisibilityRecord:
    base = dict(kind="agent", key="k", name="bot", owner="7", tenant="acme", visibility="private",
                allowed_groups=(), source="store")
    base.update(kw)
    return StudioVisibilityRecord(**base)


def _acc(scope: RequestScope | None = None, opted_in: bool = True) -> StudioAccess:
    return StudioAccess(scope or _scope(), opted_in=opted_in)


def test_owner_in_other_tenant_invisible():
    acc = _acc(_scope(tenant="beta"))
    rec = _rec(tenant="acme", owner="7")
    assert not acc.can_see(rec) and not acc.can_manage(rec)
    assert _acc().can_see(rec)


def test_admin_bounded_to_tenant():
    for flag in ({"may_administer": True}, {"is_superuser": True}):
        acc = _acc(_scope(user_id="9", **flag))
        assert acc.can_see(_rec()) and acc.can_manage(_rec()) and acc.access_tag(_rec()) == "admin"
        other = _rec(tenant="beta")
        assert not acc.can_see(other) and not acc.can_manage(other)


def test_null_tenant_row_never_in_tenant():
    rec = _rec(tenant=None, owner="7", visibility="tenant")
    acc = _acc()
    assert not acc.can_see(rec) and not acc.can_manage(rec)
    assert not _acc(_scope(tenant=None)).can_see(rec)
    assert not _acc(_scope(tenant=None, is_superuser=True)).can_see(rec)


def test_groups_intersection():
    rec = _rec(owner="1", visibility="groups", allowed_groups=("g1",))
    assert _acc().can_see(rec) and _acc().access_tag(rec) == "groups"
    assert not _acc(_scope(groups=frozenset({"x"}))).can_see(rec)
    assert not _acc().can_manage(rec)
    tenant_rec = _rec(owner="1", visibility="tenant")
    assert _acc().can_see(tenant_rec) and _acc().access_tag(tenant_rec) == "tenant"
    assert not _acc().can_see(_rec(owner="1"))


def test_no_resolver_is_global():
    acc = _acc(_scope(tenant=None, user_id="7"), opted_in=False)
    rec = _rec(tenant=None, owner="8", source="legacy")
    assert acc.can_see(rec) and acc.access_tag(rec) == "global"
    assert not acc.can_manage(rec)
    assert acc.can_manage(_rec(tenant=None, owner="7"))
    assert _acc(_scope(tenant=None, is_superuser=True), opted_in=False).can_manage(rec)


def test_reserved_keys_rejected():
    assert StudioAccess.reject_reserved_keys({"a": 1}) is None
    assert StudioAccess.reject_reserved_keys({"a": 1, "tenant": "x"}) == "tenant"
    for key in ("owner", "created_by", "visibility", "allowed_groups"):
        assert StudioAccess.reject_reserved_keys({key: 1}) == key
    assert StudioAccess.reject_reserved_keys([]) is None
    stamped = _acc().stamp(visibility="bogus", allowed_groups=["g1"])
    assert stamped == {"owner": "7", "tenant": "acme", "visibility": "private", "allowed_groups": ["g1"]}


def test_visibility_validation():
    acc = _acc()
    assert acc.validate_visibility(visibility="private", allowed_groups=[]) is None
    assert acc.validate_visibility(visibility="tenant", allowed_groups=[]) is None
    assert acc.validate_visibility(visibility="groups", allowed_groups=["g1"]) is None
    assert acc.validate_visibility(visibility="groups", allowed_groups=[]) == "groups_required"
    assert acc.validate_visibility(visibility="groups", allowed_groups=["zz"]) == "groups_not_allowed"
    no_tenant = _acc(_scope(tenant=None))
    assert no_tenant.validate_visibility(visibility="tenant", allowed_groups=[]) == "tenant_required"
    assert no_tenant.validate_visibility(visibility="private", allowed_groups=[]) is None
    admin = _acc(_scope(may_administer=True))
    assert admin.validate_visibility(visibility="groups", allowed_groups=["zz"]) is None


def test_build_tool_scope_shape():
    acc = _acc()
    ref = acc.agent_ref(_rec(key="abc"))
    assert ref.agent_id == "abc" and ref.name == "bot" and ref.tenant == "acme"
    assert acc.agent_ref(_rec(source="legacy")).agent_id is None
    ts = build_tool_scope(acc.scope, ref)
    assert ts.caller is acc.scope and ts.agent is ref
    assert build_tool_scope(acc.scope).agent is None


class _Resolver:
    def __init__(self, scope):
        self.scope = scope

    async def resolve(self, request):
        return self.scope


@web.middleware
async def _session_mw(request, handler):
    request["NAV_SESSION"] = SessionData(data={"session": {"user_id": 7, "programs": ["acme"]}})
    request["authenticated"] = True
    return await handler(request)


class _PartView(StudioBaseView):
    async def get(self):
        try:
            part = await self._studio_partition()
        except StudioTenantRequired:
            return self._tenant_required()
        return self.json_response({"tenant": part.tenant, "global": part == StudioPartition.GLOBAL})


async def _get(aiohttp_client, scope):
    app = web.Application(middlewares=[_session_mw])
    if scope is not None:
        app["scope_resolver"] = _Resolver(scope)
    app.router.add_view("/part", _PartView)
    resp = await (await aiohttp_client(app)).get("/part")
    return resp.status, await resp.json()


async def test_partition_from_scope(aiohttp_client):
    assert await _get(aiohttp_client, None) == (200, {"tenant": None, "global": True})
    assert await _get(aiohttp_client, _scope()) == (200, {"tenant": "acme", "global": False})
    status, body = await _get(aiohttp_client, _scope(tenant=None))
    assert status == 422 and body["code"] == "tenant_required"


async def test_store_lookup_uses_tenant_partition():
    from parrot.handlers.studio.storage.models import StudioPartition as P

    repos = InMemoryStudioRepositories()
    app = {"studio_storage": type("S", (), {"repos": repos})()}
    acc = StudioAccess(_scope(), opted_in=True, app=app)
    assert await acc.agent("nope") is None
    assert await acc.draft("nope") is None
    assert await acc.skill("not-a-uuid") is None
    with pytest.raises(StudioTenantRequired):
        await StudioAccess(_scope(tenant=None), opted_in=True, app=app).agent("x")
    assert P.from_scope(acc.scope).tenant == "acme"
