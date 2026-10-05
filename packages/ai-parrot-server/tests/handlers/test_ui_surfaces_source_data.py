"""FEAT-636 TASK-4108 — POST source-data endpoint identity and error matrix."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot.auth.exceptions import AuthorizationRequired
from parrot.handlers.models.ui_surfaces import SurfaceVisibility
from parrot.handlers.ui_surfaces_scope import SurfaceScope
from parrot.outputs.a2ui.linked.service import LinkedGuardRequired, SourceFetchOutcome

from .test_ui_surfaces_linked_handler import _app, _decode, _handler, _linked_service, _make_record, _post, _store

pytestmark = pytest.mark.asyncio

PATH = "/api/v1/ui/surfaces/surface-1/sources/activity/data"


class _StubResolver:
    """Resolve a fixed scope for endpoint identity tests."""

    def __init__(self, scope: SurfaceScope):
        self._scope = scope

    async def resolve(self, request):
        """Return the scope configured for this test request."""
        return self._scope


def _service(outcome: SourceFetchOutcome | None = None):
    """Build the linked-service fake with a configurable fetch result."""
    service = _linked_service()
    service.fetch_source = AsyncMock(return_value=outcome or SourceFetchOutcome(key="activity", rows=[{"a": 1}]))
    return service


def _request(record=None, service=None, *, user_id="user-1", query=None, body=None, scope=None):
    """Build a source-data handler using the shared linked-handler fixtures."""
    app = _app(_store(record or _make_record()), service or _service())
    if scope is not None:
        app["ui_surfaces_scope_resolver"] = _StubResolver(scope)
    return _handler(
        app,
        match_info={"surface_id": "surface-1", "key": "activity"},
        path=PATH,
        json_body=body,
        user_id=user_id,
        query=query,
    )


async def test_owner_gets_rows_with_own_pctx():
    """The owner fetches the requested source with their own principal."""
    service = _service()
    response = await _post(_request(service=service, body={"params": {"window": "30d"}}))

    assert response.status == 200
    assert (await _decode(response))["rows"] == [{"a": 1}]
    kwargs = service.fetch_source.call_args.kwargs
    assert kwargs["params"] == {"window": "30d"}
    assert kwargs["pctx"].user_id == "user-1"


async def test_share_only_viewer_uses_owner_pctx():
    """A share-token-only viewer runs the guarded fetch as the surface owner."""
    record = _make_record(user_id="owner-1")
    store = _store(record)
    store.resolve_share.return_value = SimpleNamespace(surface_id="surface-1")
    service = _service()
    app = _app(store, service)
    response = await _post(
        _handler(
            app,
            match_info={"surface_id": "surface-1", "key": "activity"},
            path=PATH,
            json_body={},
            user_id="viewer-9",
            query={"share": "tok"},
        )
    )

    assert response.status == 200
    assert service.fetch_source.call_args.kwargs["pctx"].user_id == "owner-1"


async def test_scope_granted_viewer_uses_own_pctx_even_with_share_token():
    """Scope access wins over a supplied share token for principal selection."""
    record = _make_record(user_id="owner-1", tenant="epson", visibility=SurfaceVisibility.tenant)
    service = _service()
    scope = SurfaceScope(user_id="viewer-9", tenant="epson", groups=frozenset(), is_superuser=False)
    response = await _post(_request(record, service, user_id="viewer-9", query={"share": "tok"}, body={}, scope=scope))

    assert response.status == 200
    assert service.fetch_source.call_args.kwargs["pctx"].user_id == "viewer-9"


@pytest.mark.parametrize(
    ("query", "expected_status"),
    [({}, 404), ({"share": "bad-token"}, 410)],
)
async def test_missing_access_and_bad_token_return_non_oracle_errors(query, expected_status):
    """Absent access is hidden while an explicitly supplied invalid token expires."""
    response = await _post(_request(_make_record(user_id="owner-1"), user_id="viewer-9", query=query, body={}))

    assert response.status == expected_status


@pytest.mark.parametrize("error", [LinkedGuardRequired(), AuthorizationRequired("query_slug", "not permitted")])
async def test_guard_and_authorization_denials_return_403(error):
    """Guard and PBAC failures have the same safe public status."""
    service = _service()
    service.fetch_source.side_effect = error
    response = await _post(_request(service=service, body={}))

    assert response.status == 403


@pytest.mark.parametrize(
    ("outcome", "expected_status", "expected_code"),
    [
        (SourceFetchOutcome(key="activity", error_status=404, error_code="source_not_found"), 404, "source_not_found"),
        (SourceFetchOutcome(key="activity", error_status=422, error_code="transform_failed"), 422, "transform_failed"),
    ],
)
async def test_source_errors_preserve_status_and_code(outcome, expected_status, expected_code):
    """Unavailable source outcomes preserve their service-specific HTTP status."""
    response = await _post(_request(service=_service(outcome), body={}))

    decoded = await _decode(response)
    assert response.status == expected_status
    assert decoded["message"] == "Data source unavailable"
    assert decoded["code"] == expected_code


async def test_recipe_surface_is_not_a_data_source_endpoint():
    """Recipe-backed surfaces never dispatch through the linked fetch service."""
    service = _service()
    response = await _post(_request(_make_record(recipe_name="daily-budget"), service, body={}))

    assert response.status == 404
    service.fetch_source.assert_not_awaited()


async def test_conditions_in_body_are_ignored():
    """Only params are forwarded; client-supplied conditions cannot alter descriptors."""
    service = _service()
    response = await _post(
        _request(service=service, body={"params": {"window": "30d"}, "conditions": {"tenant": "attacker"}})
    )

    assert response.status == 200
    assert service.fetch_source.call_args.kwargs["params"] == {"window": "30d"}
