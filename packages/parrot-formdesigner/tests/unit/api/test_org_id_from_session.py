"""Organization context comes from navigator-auth's normalized session user."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from navigator_auth.backends.basic import BasicUser
from navigator_auth.identities import Organization
from navigator_session import SessionData

from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.services.org_graph import OrgGraph, OrgGraphService, OrgNode
from parrot_formdesigner.services.registry import FormRegistry


def _request(org_ids: tuple[int, ...] = (7,), query: str = "") -> web.Request:
    """Build a request using the normalized AuthUser contract, without a user ID."""
    user = BasicUser(
        data={
            "username": "review@example.invalid",
            "organizations": [Organization(org_id=str(org_id), organization=f"Org {org_id}") for org_id in org_ids],
        }
    )
    session = SessionData(data={"session": {"programs": ["example"]}})
    session["user"] = session.encode(user)
    request = make_mocked_request("GET", f"/api/v1/org/graph{query}")
    request.user = session.decode("user")
    request.session = session
    return request


def _handler(*, graph_service: bool = False) -> FormAPIHandler:
    """Provide only the application services requested by the test."""
    registry = MagicMock(spec=FormRegistry)
    registry.default_tenant = "global"
    service = MagicMock(spec=OrgGraphService) if graph_service else None
    if service is not None:
        service.get_graph = AsyncMock(
            return_value=OrgGraph(org_id=7, tenant="example", root=OrgNode(node_type="company", node_id="example"))
        )
    return FormAPIHandler(registry=registry, org_graph_service=service)


@pytest.mark.parametrize("org_ids", [(), (7,), (9, 7), (7, 7, 9)])
def test_reads_all_session_organizations(org_ids: tuple[int, ...]) -> None:
    """The singular accessor retains the first organization; the plural deduplicates."""
    handler = _handler()
    request = _request(org_ids)

    assert handler._get_org_ids(request) == list(dict.fromkeys(org_ids))
    assert handler._get_org_id(request) == (org_ids[0] if org_ids else None)


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize(
    "org_ids, query, selected, status",
    [
        ((7,), "", 7, None),
        ((7,), "?org_id=7", 7, None),
        ((7, 9), "?org_id=9", 9, None),
        ((7, 9), "", None, 400),
        ((7,), "?org_id=9", None, 403),
        ((), "", None, 403),
        ((), "?org_id=7", None, 403),
    ],
)
def test_selection_is_independent_of_graph_service(
    configured: bool, org_ids: tuple[int, ...], query: str, selected: int | None, status: int | None
) -> None:
    """Only session organizations authorize a selection, with no service calls."""
    handler = _handler(graph_service=configured)

    org_id, error = handler._resolve_org_id(_request(org_ids, query))

    assert org_id == selected
    assert (error.status if error is not None else None) == status
    if configured:
        assert handler._org_graph_service.mock_calls == []


@pytest.mark.parametrize("value", ["abc", "%C2%B2", "-7", "7.0", "", "7" * 5000])
def test_invalid_selection_returns_400(value: str) -> None:
    """Invalid integers, including values beyond Python's conversion limit, are rejected."""
    org_id, error = _handler()._resolve_org_id(_request(query=f"?org_id={value}"))

    assert org_id is None
    assert error is not None and error.status == 400


@pytest.mark.parametrize("user", [None, SimpleNamespace(), SimpleNamespace(organizations=None)])
def test_missing_organization_context_is_refused(user: object) -> None:
    """Old or incomplete sessions fail closed without a database fallback."""
    request = _request()
    request.user = user

    org_id, error = _handler()._resolve_org_id(request)

    assert org_id is None
    assert error is not None and error.status == 403


def test_invalid_session_organization_is_refused() -> None:
    """An invalid ID cannot produce a partially authorized organization list."""
    request = _request()
    request.user.organizations.append(Organization(org_id="invalid", organization="Invalid"))

    org_id, error = _handler()._resolve_org_id(request)

    assert org_id is None
    assert error is not None and error.status == 403


@pytest.mark.asyncio
async def test_graph_uses_session_organization_without_membership_query() -> None:
    """A decoded BasicUser suffices even when login userinfo contains no user_id."""
    handler = _handler(graph_service=True)

    response = await handler.get_org_graph(_request())

    assert response.status == 200
    handler._org_graph_service.get_graph.assert_awaited_once_with(7, tenant="example")
    assert len(handler._org_graph_service.mock_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method",
    [
        "get_org_graph",
        "create_project",
        "list_sites",
        "create_site",
        "list_locations",
        "create_location",
        "get_location",
    ],
)
async def test_org_endpoints_refuse_an_organization_outside_the_session(method: str) -> None:
    """Exercise selection in every handler that consumes organization context."""
    handler = _handler(graph_service=True)
    handler._project_service = MagicMock()
    handler._venue_service = MagicMock()
    request = _request(query="?org_id=99")
    request.match_info.update({"store_id": "1", "site_id": "1", "location_id": "1"})
    request.json = AsyncMock(
        return_value={
            "accounting_code": "A-1",
            "client_id": 3,
            "name": "N",
            "site_id": 1,
            "store_id": "1",
            "location_type": "kiosk",
        }
    )

    response = await getattr(handler, method)(request)

    assert response.status == 403, (method, response.text)
    assert handler._org_graph_service.mock_calls == []
    assert handler._project_service.mock_calls == []
    assert handler._venue_service.mock_calls == []
