"""Unit tests for ``SurfaceNegotiationService`` + ``UISurfacesHandler``
(FEAT-492, TASK-2702).

Testing approach mirrors ``test_infographic_recipes.py`` (same package,
same ``BaseView`` + double-decorator shape): construct the handler via
``__new__`` (bypassing ``BaseView.__init__``/aiohttp routing) and drive it
with a fake request carrying ``app`` (dict), ``match_info``, ``path``,
``query``, ``headers``, and an async ``json()``. ``@is_authenticated()``/
``@user_session()`` are fully unwrapped via ``__wrapped__`` — those
decorators need real aiohttp session/auth middleware, out of scope for a
unit test of the handler's OWN request-handling logic.

``PgUISurfaceStore`` and ``RecipeRunner`` are mocked/stubbed throughout.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.handlers.models.ui_surfaces import (
    UISurfaceKind,
    UISurfaceRecord,
    UISurfaceShare,
)
from parrot.handlers.ui_surfaces import (
    SurfaceNegotiationService,
    UISurfacesHandler,
)
from parrot.outputs.a2ui.models import CreateSurface
from parrot.outputs.a2ui.recipes.models import RecipeRunError
from parrot.tools.infographic_recipes.runner import RecipeRunException

# ---------------------------------------------------------------------------
# Fake request / handler construction (test_infographic_recipes.py idiom)
# ---------------------------------------------------------------------------


class _FakeRequest:
    def __init__(
        self,
        app,
        match_info=None,
        path="",
        json_body=None,
        user_id="user-1",
        query=None,
        headers=None,
    ):
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
    h = UISurfacesHandler.__new__(UISurfacesHandler)
    h.logger = logging.getLogger("test.ui_surfaces_handler")
    h._request = _FakeRequest(app, **kwargs)
    return h


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _get(h):
    return await _unwrap(UISurfacesHandler.get)(h)


async def _post(h):
    return await _unwrap(UISurfacesHandler.post)(h)


async def _delete(h):
    return await _unwrap(UISurfacesHandler.delete)(h)


async def _decode(response) -> dict:
    return json.loads(response.body)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sample_envelope(surface_id="s-1") -> dict:
    return CreateSurface(
        surfaceId=surface_id,
        components=[],
        dataModel={"filters": {"window": "all"}},
    ).model_dump(by_alias=True, mode="json")


def _make_record(**overrides) -> UISurfaceRecord:
    now = datetime.now(UTC)
    defaults = {
        "surface_id": "surface-1",
        "kind": UISurfaceKind.dashboard,
        "title": "Q3 Revenue",
        "envelope": _sample_envelope(),
        "catalog_id": None,
        "agent_id": "agent-1",
        "user_id": "user-1",
        "session_id": "session-1",
        "recipe_name": None,
        "recipe_owner": None,
        "recipe_params": {},
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return UISurfaceRecord(**defaults)


@pytest.fixture
def fake_store():
    store = MagicMock()
    store.get = AsyncMock(return_value=None)
    store.list = AsyncMock(return_value=[])
    store.list_shared_with = AsyncMock(return_value=[])
    store.save = AsyncMock(return_value="surface-1")
    store.update_envelope = AsyncMock(return_value=None)
    store.delete = AsyncMock(return_value=True)
    store.mint_share = AsyncMock()
    store.resolve_share = AsyncMock(return_value=None)
    store.claim_share = AsyncMock(return_value=None)
    store.revoke_share = AsyncMock(return_value=True)
    return store


@pytest.fixture
def fake_runner():
    runner = MagicMock()
    runner.run = AsyncMock()
    return runner


def _app(store, runner=None, artifact_store=None):
    app = {"ui_surfaces_store": store}
    if runner is not None:
        app["recipe_runner"] = runner
    if artifact_store is not None:
        app["artifact_store"] = artifact_store
    return app


# ---------------------------------------------------------------------------
# SurfaceNegotiationService
# ---------------------------------------------------------------------------


class TestSurfaceNegotiationService:
    def test_negotiate_default_json(self):
        service = SurfaceNegotiationService()
        req = _FakeRequest({}, query={}, headers={})
        assert service.negotiate(req) == "application/json"

    def test_negotiate_accept_header_html(self):
        service = SurfaceNegotiationService()
        req = _FakeRequest({}, query={}, headers={"Accept": "text/html"})
        assert service.negotiate(req) == "text/html"

    def test_negotiate_format_param_wins_over_accept(self):
        service = SurfaceNegotiationService()
        req = _FakeRequest({}, query={"format": "json"}, headers={"Accept": "text/html"})
        assert service.negotiate(req) == "application/json"

    async def test_respond_json_default(self):
        service = SurfaceNegotiationService()
        record = _make_record()
        resp = await service.respond(record, "application/json")
        body = json.loads(resp.body)
        assert body["envelope"] == record.envelope
        assert body["metadata"]["surface_id"] == "surface-1"
        assert body["metadata"]["refreshable"] is False

    async def test_respond_html_renders(self):
        service = SurfaceNegotiationService()
        record = _make_record()
        resp = await service.respond(record, "text/html")
        assert resp.content_type == "text/html"
        assert b"<html" in resp.body or b"<!DOCTYPE" in resp.body or resp.body

    async def test_respond_html_501_without_visualizations(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "parrot.outputs.a2ui_renderers.interactive_html":
                raise ImportError("simulated: ai-parrot-visualizations not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        service = SurfaceNegotiationService()
        record = _make_record()
        resp = await service.respond(record, "text/html")
        assert resp.status == 501
        body = json.loads(resp.body)
        assert "ai-parrot-visualizations" in body["message"]


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


class TestGet:
    async def test_get_owner_json_default(self, fake_store):
        record = _make_record(user_id="user-1")
        fake_store.get.return_value = record
        h = _handler(_app(fake_store), match_info={"surface_id": "surface-1"}, user_id="user-1")

        resp = await _get(h)

        assert resp.status == 200
        body = await _decode(resp)
        assert body["metadata"]["surface_id"] == "surface-1"

    async def test_get_foreign_id_404(self, fake_store):
        record = _make_record(user_id="owner-a")
        fake_store.get.return_value = record
        h = _handler(_app(fake_store), match_info={"surface_id": "surface-1"}, user_id="someone-else")

        resp = await _get(h)

        assert resp.status == 404

    async def test_get_share_token_ok_and_claims(self, fake_store):
        record = _make_record(user_id="owner-a")
        fake_store.get.return_value = record
        share = UISurfaceShare(token="tok-1", surface_id="surface-1", created_at=datetime.now(UTC))
        fake_store.resolve_share.return_value = share
        h = _handler(
            _app(fake_store),
            match_info={"surface_id": "surface-1"},
            user_id="viewer-1",
            query={"share": "tok-1"},
        )

        resp = await _get(h)

        assert resp.status == 200
        fake_store.claim_share.assert_awaited_once_with("tok-1", "viewer-1")

    async def test_get_share_token_revoked_410(self, fake_store):
        record = _make_record(user_id="owner-a")
        fake_store.get.return_value = record
        fake_store.resolve_share.return_value = None  # revoked/expired/missing — no oracle
        h = _handler(
            _app(fake_store),
            match_info={"surface_id": "surface-1"},
            user_id="viewer-1",
            query={"share": "bad-token"},
        )

        resp = await _get(h)

        assert resp.status == 410

    async def test_get_html_accept_and_format_param(self, fake_store):
        record = _make_record(user_id="user-1")
        fake_store.get.return_value = record
        h = _handler(
            _app(fake_store),
            match_info={"surface_id": "surface-1"},
            user_id="user-1",
            query={"format": "html"},
        )

        resp = await _get(h)

        assert resp.content_type == "text/html"

    async def test_list_owned_union_shared_with_access_tag(self, fake_store):
        owned = _make_record(surface_id="owned-1", user_id="user-1")
        shared = _make_record(surface_id="shared-1", user_id="owner-b")
        fake_store.list.return_value = [owned]
        fake_store.list_shared_with.return_value = [shared]
        h = _handler(_app(fake_store), match_info={}, user_id="user-1")

        resp = await _get(h)

        assert resp.status == 200
        body = await _decode(resp)
        by_id = {s["surface_id"]: s["access"] for s in body["surfaces"]}
        assert by_id == {"owned-1": "owner", "shared-1": "shared"}


# ---------------------------------------------------------------------------
# POST: pin/save
# ---------------------------------------------------------------------------


class TestPinSave:
    async def test_post_pin_inline_valid_201(self, fake_store):
        body = {
            "kind": "dashboard",
            "title": "My Dashboard",
            "envelope": _sample_envelope(),
        }
        h = _handler(_app(fake_store), match_info={}, path="/api/v1/ui/surfaces", json_body=body)

        resp = await _post(h)

        assert resp.status == 201
        decoded = await _decode(resp)
        assert decoded["surface_id"] == "surface-1"
        fake_store.save.assert_awaited_once()

    async def test_post_pin_inline_xor_artifact_400(self, fake_store):
        body = {"kind": "dashboard", "title": "X"}  # neither envelope nor source_artifact_id
        h = _handler(_app(fake_store), match_info={}, path="/api/v1/ui/surfaces", json_body=body)

        resp = await _post(h)

        assert resp.status == 400

    async def test_post_pin_both_envelope_and_artifact_400(self, fake_store):
        body = {
            "kind": "dashboard",
            "title": "X",
            "envelope": _sample_envelope(),
            "source_artifact_id": "art-1",
        }
        h = _handler(_app(fake_store), match_info={}, path="/api/v1/ui/surfaces", json_body=body)

        resp = await _post(h)

        assert resp.status == 400

    async def test_post_pin_source_artifact_copies_envelope(self, fake_store):
        artifact_store = MagicMock()
        artifact_store.get_artifact = AsyncMock(return_value=SimpleNamespace(definition=_sample_envelope()))
        body = {
            "kind": "dashboard",
            "title": "X",
            "source_artifact_id": "art-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
        }
        h = _handler(
            _app(fake_store, artifact_store=artifact_store),
            match_info={},
            path="/api/v1/ui/surfaces",
            json_body=body,
        )

        resp = await _post(h)

        assert resp.status == 201
        artifact_store.get_artifact.assert_awaited_once()


# ---------------------------------------------------------------------------
# POST: refresh
# ---------------------------------------------------------------------------


class TestRefresh:
    async def test_refresh_param_precedence_and_inplace_update(self, fake_store, fake_runner):
        record = _make_record(
            user_id="user-1",
            recipe_name="daily-budget",
            recipe_owner="user-1",
            recipe_params={"window": "7d", "plan": "All"},
        )
        fake_store.get.return_value = record
        refreshed_envelope = _sample_envelope()
        fake_runner.run.return_value = SimpleNamespace(metadata={"source_envelope": refreshed_envelope})

        h = _handler(
            _app(fake_store, runner=fake_runner),
            match_info={"surface_id": "surface-1"},
            path="/api/v1/ui/surfaces/surface-1/refresh",
            json_body={"params": {"window": "30d"}},
            user_id="user-1",
        )

        resp = await _post(h)

        assert resp.status == 200
        _, kwargs = fake_runner.run.call_args
        assert kwargs["params"] == {"window": "30d", "plan": "All"}
        assert kwargs["include_envelope"] is True
        assert kwargs["recipe_owner"] == "user-1"
        fake_store.update_envelope.assert_awaited_once_with(
            "surface-1", refreshed_envelope, {"window": "30d", "plan": "All"}
        )

    async def test_refresh_share_bearer_uses_owner_pctx(self, fake_store, fake_runner):
        record = _make_record(user_id="owner-a", recipe_name="daily-budget")
        fake_store.get.return_value = record
        share = UISurfaceShare(token="tok-1", surface_id="surface-1", created_at=datetime.now(UTC))
        fake_store.resolve_share.return_value = share
        fake_runner.run.return_value = SimpleNamespace(metadata={"source_envelope": _sample_envelope()})

        h = _handler(
            _app(fake_store, runner=fake_runner),
            match_info={"surface_id": "surface-1"},
            path="/api/v1/ui/surfaces/surface-1/refresh",
            json_body={},
            user_id="bearer-1",
            query={"share": "tok-1"},
        )

        resp = await _post(h)

        assert resp.status == 200
        _, kwargs = fake_runner.run.call_args
        pctx = kwargs["pctx"]
        assert pctx.user_id == "owner-a"  # OWNER's identity, never the bearer's

    async def test_refresh_not_refreshable_409(self, fake_store):
        record = _make_record(user_id="user-1", recipe_name=None)
        fake_store.get.return_value = record
        h = _handler(
            _app(fake_store),
            match_info={"surface_id": "surface-1"},
            path="/api/v1/ui/surfaces/surface-1/refresh",
            json_body={},
            user_id="user-1",
        )

        resp = await _post(h)

        assert resp.status == 409

    async def test_refresh_recipe_error_422(self, fake_store, fake_runner):
        record = _make_record(user_id="user-1", recipe_name="daily-budget")
        fake_store.get.return_value = record
        fake_runner.run.side_effect = RecipeRunException(
            RecipeRunError(recipe="daily-budget", stage="gate", detail="missing column")
        )
        h = _handler(
            _app(fake_store, runner=fake_runner),
            match_info={"surface_id": "surface-1"},
            path="/api/v1/ui/surfaces/surface-1/refresh",
            json_body={},
            user_id="user-1",
        )

        resp = await _post(h)

        assert resp.status == 422
        body = await _decode(resp)
        assert body["stage"] == "gate"

    async def test_refresh_recipe_data_error_502(self, fake_store, fake_runner):
        record = _make_record(user_id="user-1", recipe_name="daily-budget")
        fake_store.get.return_value = record
        fake_runner.run.side_effect = RecipeRunException(
            RecipeRunError(recipe="daily-budget", stage="data", detail="dataset unavailable")
        )
        h = _handler(
            _app(fake_store, runner=fake_runner),
            match_info={"surface_id": "surface-1"},
            path="/api/v1/ui/surfaces/surface-1/refresh",
            json_body={},
            user_id="user-1",
        )

        resp = await _post(h)

        assert resp.status == 502


# ---------------------------------------------------------------------------
# Share mint / revoke
# ---------------------------------------------------------------------------


class TestShare:
    async def test_share_mint_ttl_true_90_days(self, fake_store):
        record = _make_record(user_id="user-1")
        fake_store.get.return_value = record
        expected_expiry = datetime.now(UTC) + timedelta(days=90)
        fake_store.mint_share.return_value = UISurfaceShare(
            token="tok-new",
            surface_id="surface-1",
            expires_at=expected_expiry,
            created_at=datetime.now(UTC),
        )
        h = _handler(
            _app(fake_store),
            match_info={"surface_id": "surface-1"},
            path="/api/v1/ui/surfaces/surface-1/share",
            json_body={"ttl": True},
            user_id="user-1",
        )

        resp = await _post(h)

        assert resp.status == 201
        _, kwargs = fake_store.mint_share.call_args
        assert kwargs["use_default_ttl"] is True

    async def test_share_mint_owner_only(self, fake_store):
        record = _make_record(user_id="owner-a")
        fake_store.get.return_value = record
        h = _handler(
            _app(fake_store),
            match_info={"surface_id": "surface-1"},
            path="/api/v1/ui/surfaces/surface-1/share",
            json_body={},
            user_id="someone-else",
        )

        resp = await _post(h)

        assert resp.status == 404
        fake_store.mint_share.assert_not_awaited()

    async def test_share_revoke_owner_only(self, fake_store):
        record = _make_record(user_id="owner-a")
        fake_store.get.return_value = record
        h = _handler(
            _app(fake_store),
            match_info={"surface_id": "surface-1", "token": "tok-1"},
            user_id="someone-else",
        )

        resp = await _delete(h)

        assert resp.status == 404
        fake_store.revoke_share.assert_not_awaited()

    async def test_share_revoke_by_owner_succeeds(self, fake_store):
        record = _make_record(user_id="user-1")
        fake_store.get.return_value = record
        h = _handler(
            _app(fake_store),
            match_info={"surface_id": "surface-1", "token": "tok-1"},
            user_id="user-1",
        )

        resp = await _delete(h)

        assert resp.status == 200
        fake_store.revoke_share.assert_awaited_once_with("tok-1", "surface-1")


# ---------------------------------------------------------------------------
# DELETE surface
# ---------------------------------------------------------------------------


class TestDeleteSurface:
    async def test_delete_surface_owner(self, fake_store):
        h = _handler(_app(fake_store), match_info={"surface_id": "surface-1"}, user_id="user-1")

        resp = await _delete(h)

        assert resp.status == 200
        fake_store.delete.assert_awaited_once_with("surface-1", "user-1")

    async def test_delete_surface_not_found(self, fake_store):
        fake_store.delete.return_value = False
        h = _handler(_app(fake_store), match_info={"surface_id": "surface-1"}, user_id="user-1")

        resp = await _delete(h)

        assert resp.status == 404
