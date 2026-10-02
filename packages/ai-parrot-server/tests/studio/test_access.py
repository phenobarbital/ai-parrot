"""FEAT-605 M2 — StudioAccess rule and _studio_partition override."""
from __future__ import annotations

import json as _json

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


# ---- request-level: _access / _check_record_access (real session + real default resolver) ----
def _mw(userinfo: dict, user_id=7):
    @web.middleware
    async def mw(request, handler):
        request["NAV_SESSION"] = SessionData(data={"session": {**userinfo, **({"user_id": user_id} if user_id else {})}})
        request["authenticated"] = True
        return await handler(request)

    return mw


class _CheckView(StudioBaseView):
    """GET /check?present=1&tenant=&owner=&vis=&manage=1 -> body of the helper (or 'ok')."""

    async def get(self):
        from parrot.handlers.studio.access import StudioVisibilityRecord

        q = self.request.query
        access = await self._access()
        rec = None
        if q.get("present"):
            rec = StudioVisibilityRecord("agent", "k", "bot", q.get("owner") or None, q.get("tenant") or None,
                                         q.get("vis", "private"), (), "store")
        resp = await self._check_record_access(access, rec, "agent", "bot", manage=bool(q.get("manage")))
        return resp if resp is not None else self.json_response({"ok": True, "opted_in": access.opted_in,
                                                                   "user_id": access.scope.user_id,
                                                                   "groups": sorted(access.scope.groups),
                                                                   "superuser": access.scope.is_superuser})


async def _call(aiohttp_client, userinfo, query, *, opted_in=True):
    from parrot.handlers.scope import SessionScopeResolver

    app = web.Application(middlewares=[_mw(userinfo)])
    if opted_in:
        app["scope_resolver"] = SessionScopeResolver()  # the REAL default resolver, real session
    app.router.add_view("/check", _CheckView)
    resp = await (await aiohttp_client(app)).get("/check", params=query)
    return resp.status, await resp.read()


_INFO = {"programs": ["acme"], "groups": ["g1"], "superuser": False}


async def test_check_record_access_matrix(aiohttp_client):
    absent = await _call(aiohttp_client, _INFO, {})
    other_tenant = await _call(aiohttp_client, _INFO, {"present": "1", "tenant": "beta", "owner": "7"})
    assert absent[0] == 404 and absent == other_tenant  # byte-identical
    peer = {"present": "1", "tenant": "acme", "owner": "1", "vis": "tenant"}
    status, body = await _call(aiohttp_client, _INFO, {**peer, "manage": "1"})
    assert status == 403 and b"forbidden" in body
    assert (await _call(aiohttp_client, _INFO, peer))[0] == 200  # visible, no manage requested
    own = {"present": "1", "tenant": "acme", "owner": "7", "manage": "1"}
    status, body = await _call(aiohttp_client, _INFO, own)
    assert status == 200 and _json.loads(body)["ok"] is True  # helper returned None


async def test_access_not_opted_in_goes_through_get_user(aiohttp_client):
    info = {"groups": ["g9", "superuser"]}  # superuser via group: only _get_user derives it
    status, body = await _call(aiohttp_client, info, {"present": "1"}, opted_in=False)
    data = _json.loads(body)
    assert status == 200 and data["opted_in"] is False
    assert data["user_id"] == "7" and data["groups"] == ["g9", "superuser"] and data["superuser"] is True


async def test_access_not_opted_in_without_user_is_401(aiohttp_client):
    app = web.Application(middlewares=[_mw({}, user_id=None)])
    app.router.add_view("/check", _CheckView)
    resp = await (await aiohttp_client(app)).get("/check")
    assert resp.status in (401, 403)


def test_stamp_requires_user_id():
    with pytest.raises(ValueError):
        _acc(_scope(user_id=None)).stamp(visibility="tenant", allowed_groups=[])
    with pytest.raises(ValueError):
        _acc(_scope(user_id="")).stamp(visibility="tenant", allowed_groups=[])


class _BrokenDb:
    async def acquire(self):
        raise RuntimeError("db down")


async def test_legacy_lookup_db_error_is_503_not_404():
    acc = StudioAccess(_scope(user_id="7"), opted_in=False, app={"database": _BrokenDb()})
    for call in (acc.agent("bot"), acc.draft("bot"), acc.skill("x")):
        with pytest.raises(web.HTTPServiceUnavailable):
            await call
    no_db = StudioAccess(_scope(user_id="7"), opted_in=False, app={})
    assert await no_db.draft("bot") is None


async def test_skill_lookup_store_row_and_tenant_isolation():
    repos = InMemoryStudioRepositories()
    mine = await repos.skills.insert(None, StudioPartition("acme"), owner="1", name="s1", description="d",
                                     body="b", visibility="groups", allowed_groups=["g1"])
    theirs = await repos.skills.insert(None, StudioPartition("beta"), owner="7", name="s2", description="d", body="b")
    app = {"studio_storage": type("S", (), {"repos": repos})()}
    acc = StudioAccess(_scope(), opted_in=True, app=app)
    rec = await acc.skill(str(mine.skill_id))
    assert rec is not None and rec.kind == "skill" and rec.source == "store"
    assert (rec.key, rec.name, rec.owner, rec.tenant) == (str(mine.skill_id), "s1", "1", "acme")
    assert rec.visibility == "groups" and rec.allowed_groups == ("g1",)
    assert acc.can_see(rec) and not acc.can_manage(rec)
    assert await acc.skill(str(theirs.skill_id)) is None  # other tenant's row is never returned
