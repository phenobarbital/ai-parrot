"""Unit tests for ``SurfaceScope``/``SurfaceScopeResolver`` (FEAT-535, Module 2).

No live Postgres and no real session-storage middleware required —
``SessionSurfaceScopeResolver`` is exercised with ``make_mocked_request``
plus a real ``SessionData`` object installed the way navigator_session
stores it (``request[SESSION_OBJECT]``), never a ``Mock`` with attributes
(spec §3 Module 2 rationale: a ``Mock`` answers ``.get()`` with a truthy
``Mock``, defeating a type check).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import make_mocked_request
from navigator_session.data import SessionData
from parrot.handlers.models.ui_surfaces import SurfaceVisibility, UISurfaceKind, UISurfaceRecord
from parrot.handlers.ui_surfaces_scope import (
    EMPTY_SCOPE,
    SessionSurfaceScopeResolver,
    SurfaceScope,
    get_scope_resolver,
    scope_grants,
)

# NOTE: no module-level `pytestmark = pytest.mark.asyncio` — this suite mixes
# async resolver tests with sync `scope_grants` tests; `asyncio_mode = "auto"`
# (pyproject.toml) already runs the async ones without a marker.


def _make_record(**overrides) -> UISurfaceRecord:
    now = datetime.now(UTC)
    defaults = {
        "surface_id": "surface-1",
        "kind": UISurfaceKind.dashboard,
        "title": "Q3 Revenue",
        "envelope": {},
        "catalog_id": None,
        "agent_id": "agent-1",
        "user_id": "owner-1",
        "session_id": None,
        "recipe_name": None,
        "recipe_owner": None,
        "recipe_params": {},
        "tenant": "epson",
        "visibility": SurfaceVisibility.private,
        "allowed_groups": [],
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return UISurfaceRecord(**defaults)


# ---------------------------------------------------------------------------
# SessionSurfaceScopeResolver
# ---------------------------------------------------------------------------


async def test_default_resolver_empty_request():
    req = make_mocked_request("GET", "/api/v1/ui/surfaces")
    scope = await SessionSurfaceScopeResolver().resolve(req)
    assert scope == EMPTY_SCOPE


async def test_default_resolver_attribute_only_double_is_empty():
    """An object exposing only a ``.session`` attribute (no dict-like
    ``request[SESSION_OBJECT]``/``.get()`` behaviour) must fail closed."""
    double = SimpleNamespace(session=object())
    scope = await SessionSurfaceScopeResolver().resolve(double)
    assert scope == EMPTY_SCOPE


async def test_default_resolver_reads_session_dict():
    req = make_mocked_request("GET", "/api/v1/ui/surfaces")
    req["NAV_SESSION"] = SessionData(
        data={
            "session": {
                "user_id": 36522,
                "programs": ["epson"],
                "groups": ["epson_fieldsync_admin"],
                "superuser": False,
            }
        }
    )

    scope = await SessionSurfaceScopeResolver().resolve(req)

    assert scope == SurfaceScope(
        user_id="36522", tenant="epson", groups=frozenset({"epson_fieldsync_admin"}), is_superuser=False
    )


async def test_default_resolver_multi_program_tenant_is_none():
    req = make_mocked_request("GET", "/api/v1/ui/surfaces")
    req["NAV_SESSION"] = SessionData(
        data={"session": {"user_id": 1, "programs": ["epson", "acme"], "groups": [], "superuser": True}}
    )

    scope = await SessionSurfaceScopeResolver().resolve(req)

    assert scope.tenant is None
    assert scope.is_superuser is True


async def test_default_resolver_type_checks_every_value():
    req = make_mocked_request("GET", "/api/v1/ui/surfaces")
    req["NAV_SESSION"] = SessionData(
        data={
            "session": {
                "user_id": 1,
                "programs": "epson",  # str, NOT list/tuple — must be ignored entirely
                "groups": [1, "g"],  # non-str items filtered out
                "superuser": "yes",  # non-bool — must be False
            }
        }
    )

    scope = await SessionSurfaceScopeResolver().resolve(req)

    assert scope.tenant is None
    assert scope.groups == frozenset({"g"})
    assert scope.is_superuser is False


async def test_default_resolver_userinfo_not_a_dict_is_empty_scope():
    req = make_mocked_request("GET", "/api/v1/ui/surfaces")
    req["NAV_SESSION"] = SessionData(data={"session": "not-a-dict"})

    scope = await SessionSurfaceScopeResolver().resolve(req)

    assert scope.tenant is None
    assert scope.groups == frozenset()
    assert scope.is_superuser is False


# ---------------------------------------------------------------------------
# get_scope_resolver
# ---------------------------------------------------------------------------


async def test_get_scope_resolver_default_when_unset_dict_app():
    app: dict = {}
    resolver = get_scope_resolver(app)
    assert isinstance(resolver, SessionSurfaceScopeResolver)


async def test_get_scope_resolver_honours_installed_resolver_dict_app():
    class _StubResolver:
        async def resolve(self, request):
            return SurfaceScope(user_id="stub", tenant="t", groups=frozenset(), is_superuser=False)

    stub = _StubResolver()
    app = {"ui_surfaces_scope_resolver": stub}
    resolver = get_scope_resolver(app)
    assert resolver is stub


async def test_get_scope_resolver_honours_installed_resolver_web_application():
    from aiohttp import web

    class _StubResolver:
        async def resolve(self, request):
            return EMPTY_SCOPE

    stub = _StubResolver()
    app = web.Application()
    app["ui_surfaces_scope_resolver"] = stub
    resolver = get_scope_resolver(app)
    assert resolver is stub


# ---------------------------------------------------------------------------
# scope_grants truth table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "visibility,same_tenant,groups,superuser,expected",
    [
        (SurfaceVisibility.private, True, frozenset(), False, False),
        (SurfaceVisibility.tenant, True, frozenset(), False, True),
        (SurfaceVisibility.tenant, False, frozenset(), False, False),
        (SurfaceVisibility.groups, True, frozenset({"g1"}), False, True),
        (SurfaceVisibility.groups, True, frozenset({"g2"}), False, False),
        (SurfaceVisibility.private, True, frozenset(), True, True),
        (SurfaceVisibility.tenant, False, frozenset(), True, False),
    ],
)
def test_scope_grants_truth_table(visibility, same_tenant, groups, superuser, expected):
    record = _make_record(tenant="epson", visibility=visibility, allowed_groups=["g1"])
    scope = SurfaceScope(
        user_id="caller",
        tenant="epson" if same_tenant else "other-tenant",
        groups=groups,
        is_superuser=superuser,
    )
    assert scope_grants(record, scope) is expected


def test_scope_grants_no_tenant_on_scope_never_matches():
    record = _make_record(tenant="epson", visibility=SurfaceVisibility.tenant)
    scope = SurfaceScope(user_id="caller", tenant=None, groups=frozenset(), is_superuser=True)
    assert scope_grants(record, scope) is False


def test_scope_grants_no_tenant_on_record_never_matches():
    record = _make_record(tenant=None, visibility=SurfaceVisibility.tenant)
    scope = SurfaceScope(user_id="caller", tenant="epson", groups=frozenset(), is_superuser=True)
    assert scope_grants(record, scope) is False
