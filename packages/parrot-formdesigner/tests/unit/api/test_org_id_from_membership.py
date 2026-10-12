"""NAV-9522 — ``/org/*`` resolves the caller's organization from membership.

``FormAPIHandler`` read the org id only from
``request.user.organizations[0].org_id``. navigator-auth never fills
``organizations``: the session user is built from the login's userinfo
dict, and that dict has no organization key (staging, 2026-10-12,
``GET /api/v1/user/session`` → 19 keys, the string "organization" 0
times). So every real request got ``400 org_id not found in session``,
and the Hierarchy screen could never load. The FEAT-302 handler tests
stayed green because they built the request as a ``MagicMock`` and set
``user.organizations`` by hand — a shape production cannot produce.

These tests build what production builds: a request from
``make_mocked_request``, the session as navigator-session's
``SessionData`` with the staging userinfo shape, and the user with
navigator-auth's own ``BasicUser`` class from that same dict. The
membership rows come from ``auth.organization_users``; the fake
connection refuses a column that table does not have.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import make_mocked_request
import uuid

from navigator_auth.backends.basic import BasicUser
from navigator_auth.models import User
from navigator_session import SessionData

from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.services.org_graph import OrgGraph, OrgGraphService, OrgNode
from parrot_formdesigner.services.registry import FormRegistry

from tests.unit.real_db_shapes import (
    FakeUndefinedColumnError,
    assert_real_column_refs,
    assert_real_columns,
)


USER_ID = 32771


def _staging_userinfo(**overrides: Any) -> dict[str, Any]:
    """The ``session["session"]`` dict navigator-auth stores at login.

    Key set copied from staging ``GET /api/v1/user/session`` (2026-10-12).
    It has no ``organizations`` key — that absence is the defect's cause.
    """
    info: dict[str, Any] = {
        "user_id": USER_ID,
        "username": "admin@example.com",
        "email": "admin@example.com",
        "first_name": "Ada",
        "last_name": "Admin",
        "enabled": True,
        "superuser": False,
        "programs": ["flexroc", "epson"],
        "groups": ["admin"],
        "group_id": [1],
        "domain": "example.com",
        "title": "Admin",
        "associate_id": "A1",
        "associate_oid": "OID1",
        "manager_id": None,
        "birthday": None,
        "start_date": None,
        "last_login": None,
        "user": "admin@example.com",
    }
    info.update(overrides)
    return info


def _request(query: str = "", *, model_user: bool = False, **overrides: Any):
    """A real aiohttp request with session and user as ``user_session`` sets them.

    ``model_user`` builds the user as navigator-auth's ``models.User``, the
    class the local 0.28 boot decodes from the session. It has no
    ``organizations`` field at all (measured 2026-10-12: AttributeError → 500).
    """
    userinfo = _staging_userinfo(**overrides)
    request = make_mocked_request("GET", f"/api/v1/org/graph{query}")
    request.session = SessionData(data={"session": userinfo})
    if model_user:
        request.user = User(
            user_id=USER_ID, userid=uuid.uuid4(), username=userinfo["username"]
        )
    else:
        request.user = BasicUser(data=userinfo)
    return request


class _MembershipConn:
    """Fake asyncpg connection that answers the membership query only.

    Refuses any column that ``auth.organization_users`` or
    ``auth.organizations`` does not have, as Postgres would.
    """

    def __init__(self, memberships: dict[int, list[int]], inactive: set[int] | None = None):
        self.memberships = memberships
        self.inactive = inactive or set()
        self.queries: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        assert_real_columns(sql)
        assert_real_column_refs(sql)
        self.queries.append((sql, args))
        if "auth.organization_users" not in sql:
            raise AssertionError(f"unexpected query: {sql}")
        (user_id,) = args
        # Inactive orgs drop out only when the SQL filters on is_active, so a
        # query that loses the filter makes the inactive-org test fail.
        filters_active = "is_active" in sql
        return [
            {"org_id": org_id}
            for org_id in sorted(self.memberships.get(user_id, []))
            if not (filters_active and org_id in self.inactive)
        ]


class _Pool:
    def __init__(self, conn: _MembershipConn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc: Any) -> bool:
                return False

        return _Ctx()


def _graph(org_id: int) -> OrgGraph:
    return OrgGraph(
        org_id=org_id,
        tenant="flexroc",
        root=OrgNode(node_type="company", node_id="company:flexroc"),
    )


def _handler(memberships: dict[int, list[int]], inactive: set[int] | None = None):
    """A handler whose org-graph service runs the REAL membership lookup.

    Only ``get_graph`` is replaced, so the test observes which org id the
    handler chose; ``get_user_org_ids`` runs its real SQL on the fake conn.
    """
    conn = _MembershipConn(memberships, inactive)
    service = OrgGraphService(_Pool(conn))
    service.get_graph = AsyncMock(side_effect=lambda org_id, tenant: _graph(org_id))
    registry = MagicMock(spec=FormRegistry)
    registry.default_tenant = "global"
    handler = FormAPIHandler(registry=registry, org_graph_service=service)
    return handler, service, conn


@pytest.mark.asyncio
async def test_session_from_real_login_has_no_organizations() -> None:
    """Precondition: the real user class builds NO organizations from the session."""
    request = _request()
    assert request.user.organizations == []


@pytest.mark.asyncio
async def test_org_graph_resolves_the_single_membership() -> None:
    handler, service, conn = _handler({USER_ID: [7]})

    response = await handler.get_org_graph(_request())

    assert response.status == 200, response.text
    service.get_graph.assert_awaited_once_with(7, tenant="flexroc")
    assert conn.queries and conn.queries[0][1] == (USER_ID,)


@pytest.mark.asyncio
async def test_org_graph_with_a_user_class_that_has_no_organizations_field() -> None:
    handler, service, _ = _handler({USER_ID: [7]})
    request = _request(model_user=True)
    assert not hasattr(request.user, "organizations")

    response = await handler.get_org_graph(request)

    assert response.status == 200, response.text
    service.get_graph.assert_awaited_once_with(7, tenant="flexroc")


@pytest.mark.asyncio
async def test_a_session_organization_is_not_trusted_over_the_database() -> None:
    """A stale session org (9) must not beat the DB membership (7)."""
    handler, service, _ = _handler({USER_ID: [7]})
    request = _request()
    request.user = BasicUser(
        data={**_staging_userinfo(), "organizations": [{"org_id": "9", "organization": "Old"}]}
    )
    assert request.user.organizations  # precondition: the session does carry one

    response = await handler.get_org_graph(request)

    assert response.status == 200, response.text
    service.get_graph.assert_awaited_once_with(7, tenant="flexroc")


@pytest.mark.asyncio
async def test_org_graph_403_when_user_belongs_to_no_organization() -> None:
    handler, service, _ = _handler({})

    response = await handler.get_org_graph(_request())

    assert response.status == 403, response.text
    service.get_graph.assert_not_awaited()


@pytest.mark.asyncio
async def test_inactive_organization_is_not_a_membership() -> None:
    handler, service, _ = _handler({USER_ID: [7]}, inactive={7})

    response = await handler.get_org_graph(_request())

    assert response.status == 403, response.text
    service.get_graph.assert_not_awaited()


@pytest.mark.asyncio
async def test_several_memberships_need_an_explicit_org_id() -> None:
    handler, service, _ = _handler({USER_ID: [7, 9]})

    response = await handler.get_org_graph(_request())

    assert response.status == 400, response.text
    assert "org_id" in response.text
    service.get_graph.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_org_id_is_honoured_when_the_user_is_a_member() -> None:
    handler, service, _ = _handler({USER_ID: [7, 9]})

    response = await handler.get_org_graph(_request("?org_id=9"))

    assert response.status == 200, response.text
    service.get_graph.assert_awaited_once_with(9, tenant="flexroc")


@pytest.mark.asyncio
async def test_explicit_org_id_of_another_organization_is_refused() -> None:
    handler, service, _ = _handler({USER_ID: [7]})

    response = await handler.get_org_graph(_request("?org_id=9"))

    assert response.status == 403, response.text
    service.get_graph.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["abc", "%C2%B2", "-7", "7.0", ""])
async def test_explicit_org_id_must_be_an_ascii_integer(value: str) -> None:
    # "%C2%B2" is "²": str.isdigit() accepts it and int() raises (was a 500).
    handler, service, _ = _handler({USER_ID: [7]})

    response = await handler.get_org_graph(_request(f"?org_id={value}"))

    assert response.status == 400, response.text
    service.get_graph.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_without_user_id_is_refused_without_a_query() -> None:
    handler, service, conn = _handler({USER_ID: [7]})

    response = await handler.get_org_graph(_request(user_id=None))

    assert response.status == 400, response.text
    assert conn.queries == []
    service.get_graph.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolver_is_the_shared_entry_point() -> None:
    """Every ``/org/*`` call site shares the resolver, not only the graph."""
    handler, _, _ = _handler({USER_ID: [7]})

    assert await handler._resolve_org_id(_request()) == (7, None)


@pytest.mark.asyncio
async def test_membership_query_reads_only_real_columns() -> None:
    """The lookup SQL must survive the real-column check (the 500 shape)."""
    conn = _MembershipConn({USER_ID: [7]})
    service = OrgGraphService(_Pool(conn))

    assert await service.get_user_org_ids(USER_ID) == [7]
    with pytest.raises(FakeUndefinedColumnError):
        assert_real_columns("SELECT org_id, name FROM auth.organization_users")


def _graph_sql_constants() -> dict[str, str]:
    from parrot_formdesigner.services import org_graph

    return {
        name: value
        for name, value in vars(org_graph).items()
        if name.startswith("_SQL_") and isinstance(value, str)
    }


def test_org_graph_queries_on_known_tables_reference_only_real_columns() -> None:
    """The production schema refuses a column a table lacks; so must we.

    Only tables with a recorded shape are checked (``real_db_shapes``); the
    depth >= 4 store query on ``networkninja.stores_geographies`` is a known
    open defect recorded in the FEAT-302 spec, not covered here.
    """
    constants = _graph_sql_constants()
    assert "_SQL_GET_REGIONS_FOR_CLIENT" in constants
    for name, sql in constants.items():
        try:
            assert_real_column_refs(sql)
        except FakeUndefinedColumnError as exc:  # pragma: no cover - failure path
            pytest.fail(f"{name}: {exc}")


@pytest.mark.parametrize(
    "sql",
    [
        # the pre-fix region/district queries: no client_id on those tables
        "SELECT region_id, region_name FROM networkninja.regions WHERE client_id = $1 AND orgid = $2",
        "SELECT district_id, district_name FROM networkninja.districts WHERE client_id = $1 AND orgid = $2",
        "SELECT r.region_id FROM networkninja.regions r WHERE r.client_id = $1",
        "SELECT ou.org_id FROM auth.organization_users ou WHERE ou.name = $1",
    ],
)
def test_column_reference_check_refuses_a_missing_column(sql: str) -> None:
    """Positive control: the checker fires on the shapes that broke production."""
    with pytest.raises(FakeUndefinedColumnError):
        assert_real_column_refs(sql)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method",
    ["get_org_graph", "create_project", "list_sites", "create_site",
     "list_locations", "create_location", "get_location"],
)
async def test_every_org_endpoint_goes_through_the_resolver(method: str) -> None:
    """AC3: each /org/* handler that needs an org asks ``_resolve_org_id``.

    The resolver is replaced by a spy that answers a sentinel refusal; a
    handler that bypassed it (e.g. back on ``_get_org_id``) would not return
    the sentinel.
    """
    from aiohttp import web

    registry = MagicMock(spec=FormRegistry)
    registry.default_tenant = "global"
    handler = FormAPIHandler(
        registry=registry,
        org_graph_service=MagicMock(),
        project_service=MagicMock(),
        venue_service=MagicMock(),
    )
    sentinel = web.json_response({"error": "sentinel"}, status=418)
    handler._resolve_org_id = AsyncMock(return_value=(None, sentinel))
    request = make_mocked_request(
        "POST", "/api/v1/org/x", match_info={"store_id": "1", "site_id": "1", "location_id": "1"}
    )
    request.session = SessionData(data={"session": _staging_userinfo()})
    request.user = BasicUser(data=_staging_userinfo())
    request.json = AsyncMock(
        return_value={"accounting_code": "A-1", "client_id": 3, "name": "N", "site_id": 1,
                      "store_id": "1", "location_type": "kiosk"}
    )

    response = await getattr(handler, method)(request)

    assert response is sentinel, (method, response.status)
    handler._resolve_org_id.assert_awaited()


@pytest.mark.asyncio
async def test_without_the_service_a_user_class_lacking_organizations_is_a_400_not_a_crash() -> None:
    """The legacy session read (no org-graph service) must survive ``models.User``."""
    registry = MagicMock(spec=FormRegistry)
    registry.default_tenant = "global"
    handler = FormAPIHandler(registry=registry)  # no org_graph_service
    request = _request(model_user=True)

    org_id, error = await handler._resolve_org_id(request)

    assert org_id is None
    assert error is not None and error.status == 400


@pytest.mark.asyncio
async def test_a_failed_membership_lookup_is_a_json_500_not_a_crash() -> None:
    handler, service, _ = _handler({USER_ID: [7]})
    service.get_user_org_ids = AsyncMock(side_effect=RuntimeError("pool down"))

    response = await handler.get_org_graph(_request())

    assert response.status == 500, response.text
    assert "Internal server error" in response.text
    service.get_graph.assert_not_awaited()


@pytest.mark.parametrize(
    "name, joins",
    [
        ("_SQL_GET_REGIONS_FOR_CLIENT", ["m.region_id = r.region_id", "m.orgid = r.orgid"]),
        ("_SQL_GET_DISTRICTS_FOR_CLIENT", ["m.district_id = d.district_id", "m.orgid = d.orgid"]),
    ],
)
def test_geography_is_joined_through_the_clients_markets(name: str, joins: list[str]) -> None:
    """The fakes do not execute SQL, so pin the join predicates themselves:
    a join on a wrong but existing column (m.region_id = d.district_id)
    would pass the column check. Proven on real Postgres in the NAV-9522 run."""
    sql = " ".join(_graph_sql_constants()[name].split())
    for predicate in joins:
        assert predicate in sql, (name, predicate)
    assert "WHERE m.client_id = $1 AND m.orgid = $2" in sql
