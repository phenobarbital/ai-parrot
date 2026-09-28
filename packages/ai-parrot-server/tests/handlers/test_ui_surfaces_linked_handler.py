"""FEAT-598 M8 — UISurfacesHandler linked save/refresh (spec §4)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.auth.exceptions import AuthorizationRequired
from parrot.handlers.models.ui_surfaces import UISurfaceKind, UISurfaceRecord
from parrot.handlers.ui_surfaces import UISurfacesHandler
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.linked.service import LinkedSurfaceService, RefreshOutcome, SnapshotError

pytestmark = pytest.mark.asyncio


class _FakeRequest:
    def __init__(self, app, match_info=None, path="", json_body=None, user_id="user-1", query=None, headers=None):
        self.app = app
        self.match_info = match_info or {}
        self.path = path
        self._json_body = json_body
        self.user = SimpleNamespace(user_id=user_id) if user_id else None
        self.query = query or {}
        self.headers = headers or {}

    async def json(self):
        if self._json_body is None:
            raise ValueError("no body")
        return self._json_body


def _handler(app, **kwargs):
    handler = UISurfacesHandler.__new__(UISurfacesHandler)
    handler.logger = logging.getLogger("test.ui_surfaces_linked_handler")
    handler._request = _FakeRequest(app, **kwargs)
    return handler


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _post(handler):
    return await _unwrap(UISurfacesHandler.post)(handler)


async def _get(handler):
    return await _unwrap(UISurfacesHandler.get)(handler)


async def _decode(response) -> dict:
    return json.loads(response.body)


def _linked_envelope(snapshot_at: str | None = None) -> dict:
    return {
        "surfaceId": "linked-chart",
        "catalogId": "https://parrot.dev/catalogs/v1",
        "components": [
            {
                "component": "Chart",
                "id": "root",
                "type": "bar",
                "data": {"path": "/activity/rows"},
                "x": "day",
                "y": ["visits"],
            }
        ],
        "dataModel": {"activity": {"rows": []}},
        "metadata": {
            "extensions": {
                "parrot_data_sources": {
                    "activity": {
                        "kind": "query_slug",
                        "slug": "activity",
                        "tenant": None,
                        "is_multiquery": False,
                        "multi_output": None,
                        "conditions": {},
                        "request": {"fields": [], "filter": {}, "grouping": [], "ordering": []},
                        "target": "/activity/rows",
                        "params": {},
                        "locked": [],
                        "transform": None,
                        "snapshot_at": snapshot_at,
                        "snapshot_truncated": False,
                        "refresh": {"policy": "on_mount", "interval_seconds": None},
                    }
                }
            }
        },
    }


def _baked_envelope() -> dict:
    return {"surfaceId": "baked", "components": [], "dataModel": {"activity": {"rows": []}}}


def _make_record(**overrides) -> UISurfaceRecord:
    now = datetime.now(UTC)
    defaults = {
        "surface_id": "surface-1",
        "kind": UISurfaceKind.dashboard,
        "title": "Linked dashboard",
        "envelope": _linked_envelope(),
        "catalog_id": "https://parrot.dev/catalogs/v1",
        "agent_id": "agent-1",
        "user_id": "user-1",
        "session_id": "session-1",
        "recipe_name": None,
        "recipe_owner": None,
        "recipe_params": {"window": "7d"},
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return UISurfaceRecord(**defaults)


def _store(record=None):
    store = MagicMock()
    store.save = AsyncMock(return_value="surface-1")
    store.get = AsyncMock(return_value=record)
    store.resolve_share = AsyncMock(return_value=None)
    store.claim_share = AsyncMock(return_value=None)
    store.update_envelope = AsyncMock(return_value=True)
    return store


def _linked_service() -> MagicMock:
    service = MagicMock()
    service.validate_for_persistence = AsyncMock()
    service.ensure_snapshot = AsyncMock()
    service.refresh = AsyncMock()
    return service


def _app(store, service=None, runner=None):
    app = {"ui_surfaces_store": store}
    if service is not None:
        app["linked_surface_service"] = service
    if runner is not None:
        app["recipe_runner"] = runner
    return app


async def test_save_without_snapshot_executes_once():
    store = _store()
    service = _linked_service()
    snapshot = _linked_envelope("2026-09-26T12:00:00Z")
    service.ensure_snapshot.return_value = snapshot
    body = {"kind": "dashboard", "title": "Linked", "envelope": _linked_envelope()}

    response = await _post(_handler(_app(store, service), path="/api/v1/ui/surfaces", json_body=body))

    assert response.status == 201
    service.validate_for_persistence.assert_awaited_once()
    service.ensure_snapshot.assert_awaited_once()
    assert service.ensure_snapshot.call_args.kwargs["owner_pctx"].user_id == "user-1"
    assert store.save.call_args.args[0].envelope == snapshot


@pytest.mark.parametrize("error", [SnapshotError(404, "not_found"), SnapshotError(503, "unavailable")])
async def test_save_failure_persists_nothing(error):
    store = _store()
    service = _linked_service()
    service.ensure_snapshot.side_effect = error
    body = {"kind": "dashboard", "title": "Linked", "envelope": _linked_envelope()}

    response = await _post(_handler(_app(store, service), path="/api/v1/ui/surfaces", json_body=body))

    assert response.status == error.status
    store.save.assert_not_awaited()


async def test_save_guard_missing_403():
    store = _store()
    body = {"kind": "dashboard", "title": "Linked", "envelope": _linked_envelope()}

    response = await _post(_handler(_app(store), path="/api/v1/ui/surfaces", json_body=body))

    assert response.status == 403
    store.save.assert_not_awaited()


async def test_save_owner_denied_403():
    store = _store()
    service = _linked_service()
    service.validate_for_persistence.side_effect = AuthorizationRequired("query_slug", "not permitted")
    body = {"kind": "dashboard", "title": "Linked", "envelope": _linked_envelope()}

    response = await _post(_handler(_app(store, service), path="/api/v1/ui/surfaces", json_body=body))

    assert response.status == 403
    store.save.assert_not_awaited()


async def test_save_invalid_linked_envelope_422():
    store = _store()
    service = _linked_service()
    service.validate_for_persistence.side_effect = CatalogValidationError(
        "bad descriptor", issues=[{"code": "bad", "message": "bad descriptor", "path": "/metadata"}]
    )
    body = {"kind": "dashboard", "title": "Linked", "envelope": _linked_envelope()}

    response = await _post(_handler(_app(store, service), path="/api/v1/ui/surfaces", json_body=body))

    assert response.status == 422
    assert (await _decode(response))["errors"][0]["code"] == "bad"
    store.save.assert_not_awaited()


async def test_save_baked_envelope_skips_service():
    store = _store()
    service = _linked_service()
    body = {"kind": "dashboard", "title": "Baked", "envelope": _baked_envelope()}

    response = await _post(_handler(_app(store, service), path="/api/v1/ui/surfaces", json_body=body))

    assert response.status == 201
    service.validate_for_persistence.assert_not_awaited()
    service.ensure_snapshot.assert_not_awaited()


async def test_refresh_descriptor_path():
    record = _make_record()
    store = _store(record)
    service = _linked_service()
    refreshed = _linked_envelope("2026-09-26T12:00:00Z")
    service.refresh.return_value = RefreshOutcome(envelope=refreshed)

    response = await _post(
        _handler(
            _app(store, service),
            match_info={"surface_id": "surface-1"},
            path="/api/v1/ui/surfaces/surface-1/refresh",
            json_body={"params": {"window": "30d"}},
        )
    )

    assert response.status == 200
    assert service.refresh.call_args.kwargs["owner_pctx"].user_id == "user-1"
    store.update_envelope.assert_awaited_once_with(
        "surface-1", refreshed, {"window": "7d"}, expected_updated_at=record.updated_at
    )


async def test_refresh_recipe_precedence():
    record = _make_record(recipe_name="daily-budget")
    store = _store(record)
    service = _linked_service()
    runner = MagicMock()
    runner.run = AsyncMock(return_value=SimpleNamespace(metadata={"source_envelope": _baked_envelope()}))

    response = await _post(
        _handler(
            _app(store, service, runner),
            match_info={"surface_id": "surface-1"},
            path="/api/v1/ui/surfaces/surface-1/refresh",
            json_body={},
        )
    )

    assert response.status == 200
    runner.run.assert_awaited_once()
    service.refresh.assert_not_awaited()


async def test_refresh_conflict_409():
    record = _make_record()
    newer = _make_record(envelope=_linked_envelope("2026-09-27T12:00:00Z"))
    store = _store(record)
    store.update_envelope.return_value = False
    store.get.side_effect = [record, newer]
    service = _linked_service()
    service.refresh.return_value = RefreshOutcome(envelope=_linked_envelope("2026-09-26T12:00:00Z"))

    response = await _post(
        _handler(
            _app(store, service),
            match_info={"surface_id": "surface-1"},
            path="/api/v1/ui/surfaces/surface-1/refresh",
            json_body={},
        )
    )

    assert response.status == 409
    assert (await _decode(response))["snapshot_at"] == "2026-09-27T12:00:00Z"


async def test_refresh_all_sources_failed_status():
    record = _make_record()
    store = _store(record)
    service = _linked_service()
    service.refresh.return_value = RefreshOutcome(envelope=record.envelope, error_status=503, error_code="unavailable")

    response = await _post(
        _handler(
            _app(store, service),
            match_info={"surface_id": "surface-1"},
            path="/api/v1/ui/surfaces/surface-1/refresh",
            json_body={},
        )
    )

    assert response.status == 503
    store.update_envelope.assert_not_awaited()


async def test_refresh_linked_needs_no_runner():
    record = _make_record()
    store = _store(record)
    service = _linked_service()
    service.refresh.return_value = RefreshOutcome(envelope=record.envelope)

    response = await _post(
        _handler(
            _app(store, service),
            match_info={"surface_id": "surface-1"},
            path="/api/v1/ui/surfaces/surface-1/refresh",
            json_body={},
        )
    )

    assert response.status == 200
    service.refresh.assert_awaited_once()


@pytest.mark.parametrize("query", [{}, {"format": "html"}])
async def test_get_never_executes(query):
    record = _make_record()
    store = _store(record)
    service = _linked_service()

    response = await _get(
        _handler(
            _app(store, service),
            match_info={"surface_id": "surface-1"},
            path="/api/v1/ui/surfaces/surface-1",
            query=query,
        )
    )

    assert response.status == 200
    service.validate_for_persistence.assert_not_awaited()
    service.ensure_snapshot.assert_not_awaited()
    service.refresh.assert_not_awaited()
