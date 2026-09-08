"""FEAT-492 TASK-2705 — end-to-end tests for the ui_surfaces plane (spec §4
Integration Tests table).

Wires REAL components — the real ``InfographicAuthoringMixin.publish_surface``
(called unbound against a lightweight stand-in, same technique
``test_infographic_recipes.py``/``test_ui_surfaces_handler.py`` use to avoid
constructing a full agent), the real ``PgUISurfaceStore``/``UISurfaceRecord``,
the real ``UISurfacesHandler``/``A2UIHandler``/``SurfaceNegotiationService`` —
no fakes of the FEATURE's own logic. The only fake is the Postgres
connection itself (``_FakeAsyncDB``, the exact harness TASK-2700's own
``test_ui_surfaces_store.py`` uses), which is what keeps this suite DB-less
(spec's own resolved decision — no live Postgres needed for CI).

Follows ``test_a2ui_e2e.py``'s environment conventions: real
``aiohttp_client``, minimal fakes only at true external boundaries. Per the
task's own instruction, a failing assertion here means a defect in the layer
that owns it (recorded in the Completion Note), never weakened to pass.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.web_urldispatcher import MatchInfoError
from parrot.bots.mixins import InfographicAuthoringMixin
from parrot.handlers.a2ui import A2UIHandler
from parrot.handlers.models import ui_surfaces as store_module
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore, SurfaceVisibility
from parrot.handlers.ui_surfaces import SurfaceNegotiationService, UISurfacesHandler
from parrot.handlers.ui_surfaces_scope import SurfaceScope
from parrot.outputs.a2ui.models import Component, CreateSurface

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# In-memory fake AsyncDB (identical harness to TASK-2700's
# test_ui_surfaces_store.py — see that file's docstring for rationale;
# duplicated rather than cross-imported, per this suite's own file-scope).
# ---------------------------------------------------------------------------


class _FakeConnCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc_info):
        return False


def _row_from_insert_args(args) -> dict:
    return {
        "surface_id": args[0],
        "kind": args[1],
        "title": args[2],
        "envelope": args[3],
        "catalog_id": args[4],
        "agent_id": args[5],
        "user_id": args[6],
        "session_id": args[7],
        "recipe_name": args[8],
        "recipe_owner": args[9],
        "recipe_params": args[10],
        "tenant": args[11],
        "visibility": args[12],
        "allowed_groups": args[13],
        "created_at": args[14],
        "updated_at": args[15],
    }


def _row_allowed_groups(row: dict) -> list[str]:
    """Decode a fake row's ``allowed_groups`` (JSON string, list, or missing)."""
    raw = row.get("allowed_groups")
    if raw is None:
        return []
    if isinstance(raw, list):
        return list(raw)
    return json.loads(raw)


def _row_visible(row: dict, *, user_id, tenant, groups, is_superuser) -> bool:
    """Mirrors ``_LIST_VISIBLE_SQL``'s WHERE clause (identical to
    ``test_ui_surfaces_store.py``'s fake — TASK-2932)."""
    if row["user_id"] == user_id:
        return True
    row_tenant = row.get("tenant")
    if tenant is None or row_tenant is None or row_tenant != tenant:
        return False
    visibility = row.get("visibility") or store_module.SurfaceVisibility.private.value
    if visibility == store_module.SurfaceVisibility.tenant.value:
        return True
    if is_superuser:
        return True
    if visibility == store_module.SurfaceVisibility.groups.value:
        return bool(set(_row_allowed_groups(row)) & set(groups))
    return False


class _FakeConn:
    """Mirrors ``test_ui_surfaces_store.py``'s fake (TASK-2932) — the store's
    own asyncdb-quirks fix (2026-09-05) routes DDL through ``execute``,
    every write with a ``RETURNING`` clause through ``fetchval``, and reads
    through ``fetch_one``/``fetch_all`` (never ``fetchrow``/``fetchall``)."""

    def __init__(self, state):
        self.state = state

    async def execute(self, sql, *args):
        state = self.state
        if sql.strip().upper().startswith(("CREATE", "ALTER")):
            state.ddl_calls.append(sql)
            return None
        raise AssertionError(f"Unexpected execute SQL: {sql!r}")

    async def fetch_one(self, sql, *args):
        m = store_module
        state = self.state
        if sql == m._GET_SQL:
            row = state.surfaces.get(args[0])
            return dict(row) if row else None
        if sql == m._RESOLVE_SHARE_SQL:
            row = state.shares.get(args[0])
            if row is None or row["revoked"]:
                return None
            if row["expires_at"] is not None and row["expires_at"] <= datetime.now(UTC):
                return None
            return dict(row)
        raise AssertionError(f"Unexpected fetch_one SQL: {sql!r}")

    async def fetchval(self, sql, *args):
        m = store_module
        state = self.state
        if sql == m._INSERT_OR_SKIP_SQL:
            surface_id = args[0]
            if surface_id in state.surfaces:
                return None  # ON CONFLICT DO NOTHING — no RETURNING row
            state.surfaces[surface_id] = _row_from_insert_args(args)
            return surface_id
        if sql == m._UPSERT_SQL:
            surface_id = args[0]
            state.surfaces[surface_id] = _row_from_insert_args(args)
            return surface_id
        if sql == m._UPDATE_ENVELOPE_SQL:
            surface_id, envelope_json, params_json = args
            row = state.surfaces.get(surface_id)
            if row is not None:
                row["envelope"] = envelope_json
                row["recipe_params"] = params_json
                row["updated_at"] = datetime.now(UTC)
            return surface_id
        if sql == m._UPDATE_VISIBILITY_SQL:
            surface_id, user_id, visibility, allowed_groups_value = args
            row = state.surfaces.get(surface_id)
            if row is not None and row["user_id"] == user_id:
                row["visibility"] = visibility
                row["allowed_groups"] = allowed_groups_value
                row["updated_at"] = datetime.now(UTC)
                return surface_id
            return None
        if sql == m._DELETE_SQL:
            surface_id, user_id = args
            row = state.surfaces.get(surface_id)
            if row is not None and row["user_id"] == user_id:
                del state.surfaces[surface_id]
                return surface_id
            return None
        if sql == m._MINT_SHARE_SQL:
            token, surface_id, expires_at, created_at = args
            state.shares[token] = {
                "token": token,
                "surface_id": surface_id,
                "permissions": "read+refresh",
                "expires_at": expires_at,
                "revoked": False,
                "claimed_by": None,
                "claimed_at": None,
                "created_at": created_at,
            }
            return token
        if sql == m._CLAIM_SHARE_SQL:
            token, user_id = args
            row = state.shares.get(token)
            if row is not None and row["claimed_by"] is None:
                row["claimed_by"] = user_id
                row["claimed_at"] = datetime.now(UTC)
            return token
        if sql == m._REVOKE_SHARE_SQL:
            token, surface_id = args
            row = state.shares.get(token)
            if row is not None and row["surface_id"] == surface_id:
                row["revoked"] = True
                return token
            return None
        raise AssertionError(f"Unexpected fetchval SQL: {sql!r}")

    async def fetch_all(self, sql, *args):
        m = store_module
        state = self.state
        if sql == m._LIST_SQL:
            user_id = args[0]
            rows = [r for r in state.surfaces.values() if r["user_id"] == user_id]
        elif sql == m._LIST_BY_KIND_SQL:
            user_id, kind = args
            rows = [r for r in state.surfaces.values() if r["user_id"] == user_id and r["kind"] == kind]
        elif sql == m._LIST_SHARED_WITH_SQL:
            user_id = args[0]
            now = datetime.now(UTC)
            live_ids = {
                s["surface_id"]
                for s in state.shares.values()
                if s["claimed_by"] == user_id
                and not s["revoked"]
                and (s["expires_at"] is None or s["expires_at"] > now)
            }
            rows = [r for r in state.surfaces.values() if r["surface_id"] in live_ids]
        elif sql == m._LIST_SHARES_SQL:
            surface_id = args[0]
            rows = [r for r in state.shares.values() if r["surface_id"] == surface_id]
        elif sql == m._LIST_VISIBLE_SQL:
            user_id, tenant, groups, is_superuser = args
            rows = [
                r
                for r in state.surfaces.values()
                if _row_visible(r, user_id=user_id, tenant=tenant, groups=groups, is_superuser=is_superuser)
            ]
        elif sql == m._LIST_VISIBLE_BY_KIND_SQL:
            user_id, tenant, groups, is_superuser, kind = args
            rows = [
                r
                for r in state.surfaces.values()
                if _row_visible(r, user_id=user_id, tenant=tenant, groups=groups, is_superuser=is_superuser)
                and r["kind"] == kind
            ]
        else:
            raise AssertionError(f"Unexpected fetch_all SQL: {sql!r}")
        rows = sorted(rows, key=lambda r: r["updated_at" if "updated_at" in r else "created_at"], reverse=True)
        return [dict(r) for r in rows]


class _FakeAsyncDB:
    def __init__(self, state):
        self.state = state

    async def connection(self):
        return _FakeConnCtx(_FakeConn(self.state))


@pytest.fixture
def fake_state():
    return SimpleNamespace(surfaces={}, shares={}, ddl_calls=[])


@pytest.fixture
def store(monkeypatch, fake_state):
    s = PgUISurfaceStore(dsn="postgres://fake/e2e")
    monkeypatch.setattr(s, "_get_db", lambda: _FakeAsyncDB(fake_state))
    return s


# ---------------------------------------------------------------------------
# Handler test harness (test_ui_surfaces_handler.py / test_infographic_recipes.py idiom)
# ---------------------------------------------------------------------------


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
    h = UISurfacesHandler.__new__(UISurfacesHandler)
    h.logger = logging.getLogger("test.e2e.ui_surfaces")
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


async def _patch(h):
    return await _unwrap(UISurfacesHandler.patch)(h)


async def _decode(response) -> dict:
    return json.loads(response.body)


class _StubResolver:
    """Installs a fixed :class:`SurfaceScope` on ``app["ui_surfaces_scope_resolver"]``
    (FEAT-535, spec §3 Module 2/3 — same fixture idiom as
    ``test_ui_surfaces_handler.py``/``test_a2ui_surfaces_route.py``)."""

    def __init__(self, scope: SurfaceScope):
        self._scope = scope

    async def resolve(self, request):
        return self._scope


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _chart_envelope(surface_id: str) -> dict:
    """A minimal valid CreateSurface dump with a chart component (spec §4)."""
    return CreateSurface(
        surfaceId=surface_id,
        components=[
            Component(
                id="root",
                component="Chart",
                title="Actual vs Budget",
                type="bar",
                x="day",
                y=["actual"],
                data={"path": "/rows"},
            ),
        ],
        dataModel={
            "rows": [{"day": "Mon", "actual": 10}],
            "filters": {"window": "all", "plan": "All"},
        },
    ).model_dump(by_alias=True, mode="json")


def _broken_chart_envelope(surface_id: str) -> dict:
    """A ``Chart`` envelope whose ``data`` binding points to a data-model key
    that is absent, and NO ``parrot_optional`` marker — deterministically
    raises ``BakeError`` at render time (FEAT-499 TASK-2755 guard-rail: a
    stored surface that can no longer be baked must come back as a
    structured 422, not an uncaught 500)."""
    return CreateSurface(
        surfaceId=surface_id,
        components=[
            Component(
                id="root",
                component="Chart",
                title="Broken",
                type="bar",
                x="day",
                y=["actual"],
                data={"path": "/rows"},
            ),
        ],
        dataModel={"filters": {"window": "all", "plan": "All"}},  # "rows" deliberately absent
    ).model_dump(by_alias=True, mode="json")


class _MiniBot(InfographicAuthoringMixin):
    """Lightweight REAL instance of the mixin — publish_surface only needs
    ``self.logger``/``self.name`` (+ optional ``self.user_id``), so this
    skips the (heavy) cooperative ``PandasAgent`` composition entirely while
    still exercising the actual mixin method as a genuine bound call (not an
    unbound one — that would miss the mixin's OTHER instance/static helpers,
    e.g. ``_lazy_import_ui_surfaces_models``)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.logger = logging.getLogger(f"test.e2e.{name}")


async def _publish(store, *, surface_id, user_id, recipe_name=None, recipe_owner=None, recipe_params=None):
    bot = _MiniBot("reporter")
    return await bot.publish_surface(
        kind="dashboard",
        title="E2E Surface",
        envelope=_chart_envelope(surface_id),
        recipe_name=recipe_name,
        recipe_owner=recipe_owner,
        recipe_params=recipe_params,
        surface_store=store,
        user_id=user_id,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestE2E:
    async def test_e2e_publish_get_json_get_html(self, store):
        """publish (mixin) -> GET JSON (envelope matches) -> GET HTML
        (interactive doc + a rendered chart) for a chart surface."""
        surface_id = await _publish(store, surface_id="surface-e2e-1", user_id="owner-1")
        # The row PK is ALWAYS a freshly-minted UUID (code review fix) —
        # independent of the envelope's own (renderer-scoped) surfaceId.
        assert uuid.UUID(surface_id)

        app = {"ui_surfaces_store": store}

        h_json = _handler(app, match_info={"surface_id": surface_id}, user_id="owner-1")
        resp_json = await _get(h_json)
        assert resp_json.status == 200
        body = await _decode(resp_json)
        assert body["envelope"]["surfaceId"] == "surface-e2e-1"
        assert body["envelope"]["dataModel"]["rows"] == [{"day": "Mon", "actual": 10}]
        assert body["metadata"]["refreshable"] is False

        pytest.importorskip(
            "parrot.outputs.a2ui_renderers.interactive_html",
            reason="ai-parrot-visualizations not installed — HTML leg skipped",
        )
        h_html = _handler(app, match_info={"surface_id": surface_id}, user_id="owner-1", query={"format": "html"})
        resp_html = await _get(h_html)
        assert resp_html.status == 200
        doc = resp_html.body.decode() if isinstance(resp_html.body, (bytes, bytearray)) else resp_html.body
        assert "<html" in doc.lower()
        # NOTE (deviation — see Completion Note): the spec text's own phrase
        # "an ECharts <script>" is stale — the HTML lane's renderer
        # (InteractiveHTMLRenderer, per TASK-2702's guarded import) is
        # documented as vendoring Chart.js, not ECharts. Assert what the
        # ACTUAL renderer produces: a self-contained doc with an inline
        # <script> block driving the chart.
        assert "<script" in doc.lower()
        assert "chart" in doc.lower()

    async def test_e2e_pin_then_bookmark_new_session(self, store):
        """POST pin (frontend writer) -> GET from a brand-new
        handler/request instance (same owner) -> 200 with the envelope."""
        envelope = _chart_envelope("surface-e2e-2")
        app = {"ui_surfaces_store": store}

        h_post = _handler(
            app,
            match_info={},
            path="/api/v1/ui/surfaces",
            json_body={"kind": "dashboard", "title": "Pinned", "envelope": envelope},
            user_id="owner-2",
        )
        resp_post = await _post(h_post)
        assert resp_post.status == 201
        surface_id = (await _decode(resp_post))["surface_id"]
        # Pin/save always mints a fresh row id (TASK-2702) — it does NOT
        # reuse the inline envelope's own surfaceId field, which is a
        # renderer-scoped identifier, not the store's primary key.
        assert surface_id

        # A DIFFERENT handler/request instance, simulating a fresh session —
        # only the (store-backed) row and the owner id carry over.
        h_get = _handler(app, match_info={"surface_id": surface_id}, user_id="owner-2")
        resp_get = await _get(h_get)
        assert resp_get.status == 200
        body = await _decode(resp_get)
        assert body["envelope"]["surfaceId"] == "surface-e2e-2"

    async def test_e2e_refresh_flow(self, store):
        """recipe-backed surface -> refresh with a param override (stubbed
        RecipeRunner) -> GET shows the refreshed dataModel, updated_at advanced."""
        surface_id = await _publish(
            store,
            surface_id="surface-e2e-3",
            user_id="owner-3",
            recipe_name="daily-budget",
            recipe_owner="owner-3",
            recipe_params={"window": "all"},
        )
        before = await store.get(surface_id)

        refreshed_envelope = _chart_envelope(surface_id)
        refreshed_envelope["dataModel"]["rows"] = [{"day": "Tue", "actual": 99}]
        runner = MagicMock()
        runner.run = AsyncMock(return_value=SimpleNamespace(metadata={"source_envelope": refreshed_envelope}))

        app = {"ui_surfaces_store": store, "recipe_runner": runner}
        h_refresh = _handler(
            app,
            match_info={"surface_id": surface_id},
            path=f"/api/v1/ui/surfaces/{surface_id}/refresh",
            json_body={"params": {"window": "7d"}},
            user_id="owner-3",
        )
        resp_refresh = await _post(h_refresh)
        assert resp_refresh.status == 200

        runner.run.assert_awaited_once()
        _, kwargs = runner.run.call_args
        # Param precedence: request ("7d") wins over stored ("all").
        assert kwargs["params"] == {"window": "7d"}
        assert kwargs["include_envelope"] is True
        assert kwargs["recipe_owner"] == "owner-3"

        after = await store.get(surface_id)
        assert after.envelope["dataModel"]["rows"] == [{"day": "Tue", "actual": 99}]
        assert after.updated_at > before.updated_at

    async def test_e2e_share_lifecycle(self, store):
        """mint -> GET with token (200, claim recorded, shared-with-me list)
        -> refresh with token (200, OWNER pctx) -> revoke -> GET 410."""
        surface_id = await _publish(
            store,
            surface_id="surface-e2e-4",
            user_id="owner-4",
            recipe_name="daily-budget",
            recipe_owner="owner-4",
            recipe_params={},
        )
        app = {"ui_surfaces_store": store}

        h_mint = _handler(
            app,
            match_info={"surface_id": surface_id},
            path=f"/api/v1/ui/surfaces/{surface_id}/share",
            json_body={},
            user_id="owner-4",
        )
        resp_mint = await _post(h_mint)
        assert resp_mint.status == 201
        token = (await _decode(resp_mint))["token"]

        # GET with token: 200 + claim recorded.
        h_get = _handler(app, match_info={"surface_id": surface_id}, user_id="viewer-1", query={"share": token})
        resp_get = await _get(h_get)
        assert resp_get.status == 200

        # Appears in the bearer's shared-with-me list.
        h_list = _handler(app, match_info={}, user_id="viewer-1")
        resp_list = await _get(h_list)
        surfaces = (await _decode(resp_list))["surfaces"]
        access_by_id = {s["surface_id"]: s["access"] for s in surfaces}
        assert access_by_id.get(surface_id) == "shared"

        # Refresh with token: 200, and the runner is called with the OWNER's
        # PermissionContext — never the bearer's identity.
        runner = MagicMock()
        refreshed = _chart_envelope(surface_id)
        runner.run = AsyncMock(return_value=SimpleNamespace(metadata={"source_envelope": refreshed}))
        app["recipe_runner"] = runner
        h_refresh = _handler(
            app,
            match_info={"surface_id": surface_id},
            path=f"/api/v1/ui/surfaces/{surface_id}/refresh",
            json_body={},
            user_id="viewer-1",
            query={"share": token},
        )
        resp_refresh = await _post(h_refresh)
        assert resp_refresh.status == 200
        _, kwargs = runner.run.call_args
        assert kwargs["pctx"].user_id == "owner-4"

        # Revoke (owner only).
        h_revoke = _handler(app, match_info={"surface_id": surface_id, "token": token}, user_id="owner-4")
        resp_revoke = await _delete(h_revoke)
        assert resp_revoke.status == 200

        # GET with the now-revoked token -> 410, no oracle.
        h_get2 = _handler(app, match_info={"surface_id": surface_id}, user_id="viewer-1", query={"share": token})
        resp_get2 = await _get(h_get2)
        assert resp_get2.status == 410

    async def test_e2e_tenant_visibility_roundtrip(self, store):
        """FEAT-535 spec §4 Integration Tests: pin (``visibility=tenant``) ->
        list as a tenant peer (``access=tenant``) -> GET+refresh as that peer
        -> absent/404 for a caller in a DIFFERENT tenant -> PATCH to
        ``groups`` -> group hit/miss -> superuser sees it regardless ->
        viewer delete stays ``404``, row intact.

        A stub :class:`SurfaceScopeResolver` is installed on the app dict
        (spec §3 Module 2/3 test fixture) and swapped between calls to
        simulate different callers hitting the SAME running app — exactly
        how ``app["ui_surfaces_scope_resolver"]`` is meant to be consumed.
        """
        tenant_t = "epson"
        tenant_u = "acme"
        scope_a = SurfaceScope(user_id="user-a", tenant=tenant_t, groups=frozenset(), is_superuser=False)
        app = {"ui_surfaces_store": store, "ui_surfaces_scope_resolver": _StubResolver(scope_a)}

        envelope = _chart_envelope("surface-e2e-tenant")
        h_post = _handler(
            app,
            match_info={},
            path="/api/v1/ui/surfaces",
            json_body={
                "kind": "dashboard",
                "title": "Program Report",
                "envelope": envelope,
                "visibility": "tenant",
                "recipe_name": "daily-budget",
                "recipe_owner": "user-a",
            },
            user_id="user-a",
        )
        resp_post = await _post(h_post)
        assert resp_post.status == 201
        surface_id = (await _decode(resp_post))["surface_id"]

        stored = await store.get(surface_id)
        assert stored.tenant == tenant_t
        assert stored.visibility is SurfaceVisibility.tenant

        # List as B (same tenant): present, tagged "tenant".
        scope_b = SurfaceScope(user_id="user-b", tenant=tenant_t, groups=frozenset(), is_superuser=False)
        app["ui_surfaces_scope_resolver"] = _StubResolver(scope_b)
        h_list_b = _handler(app, match_info={}, user_id="user-b")
        resp_list_b = await _get(h_list_b)
        assert resp_list_b.status == 200
        access_by_id = {s["surface_id"]: s["access"] for s in (await _decode(resp_list_b))["surfaces"]}
        assert access_by_id.get(surface_id) == "tenant"

        # GET as B: 200.
        h_get_b = _handler(app, match_info={"surface_id": surface_id}, user_id="user-b")
        resp_get_b = await _get(h_get_b)
        assert resp_get_b.status == 200

        # Refresh as B: 200, replay still runs under OWNER's (A's) pctx.
        runner = MagicMock()
        refreshed = _chart_envelope(surface_id)
        runner.run = AsyncMock(return_value=SimpleNamespace(metadata={"source_envelope": refreshed}))
        app["recipe_runner"] = runner
        h_refresh_b = _handler(
            app,
            match_info={"surface_id": surface_id},
            path=f"/api/v1/ui/surfaces/{surface_id}/refresh",
            json_body={},
            user_id="user-b",
        )
        resp_refresh_b = await _post(h_refresh_b)
        assert resp_refresh_b.status == 200
        _, kwargs = runner.run.call_args
        assert kwargs["pctx"].user_id == "user-a"

        # List as C in a DIFFERENT tenant: absent.
        scope_c = SurfaceScope(user_id="user-c", tenant=tenant_u, groups=frozenset(), is_superuser=False)
        app["ui_surfaces_scope_resolver"] = _StubResolver(scope_c)
        h_list_c = _handler(app, match_info={}, user_id="user-c")
        resp_list_c = await _get(h_list_c)
        surfaces_c = {s["surface_id"] for s in (await _decode(resp_list_c))["surfaces"]}
        assert surface_id not in surfaces_c

        # GET as C directly: 404, no existence oracle.
        h_get_c = _handler(app, match_info={"surface_id": surface_id}, user_id="user-c")
        resp_get_c = await _get(h_get_c)
        assert resp_get_c.status == 404

        # PATCH to visibility=groups, allowed_groups=["g1"] as owner A.
        app["ui_surfaces_scope_resolver"] = _StubResolver(scope_a)
        h_patch = _handler(
            app,
            match_info={"surface_id": surface_id},
            json_body={"visibility": "groups", "allowed_groups": ["g1"]},
            user_id="user-a",
        )
        resp_patch = await _patch(h_patch)
        assert resp_patch.status == 200

        # B with groups=["g1"]: sees it.
        scope_b_g1 = SurfaceScope(user_id="user-b", tenant=tenant_t, groups=frozenset({"g1"}), is_superuser=False)
        app["ui_surfaces_scope_resolver"] = _StubResolver(scope_b_g1)
        h_get_b_g1 = _handler(app, match_info={"surface_id": surface_id}, user_id="user-b")
        resp_get_b_g1 = await _get(h_get_b_g1)
        assert resp_get_b_g1.status == 200

        # B with groups=["g2"]: does not.
        scope_b_g2 = SurfaceScope(user_id="user-b", tenant=tenant_t, groups=frozenset({"g2"}), is_superuser=False)
        app["ui_surfaces_scope_resolver"] = _StubResolver(scope_b_g2)
        h_get_b_g2 = _handler(app, match_info={"surface_id": surface_id}, user_id="user-b")
        resp_get_b_g2 = await _get(h_get_b_g2)
        assert resp_get_b_g2.status == 404

        # Superuser in T sees it regardless of allowed_groups.
        scope_super = SurfaceScope(user_id="root", tenant=tenant_t, groups=frozenset(), is_superuser=True)
        app["ui_surfaces_scope_resolver"] = _StubResolver(scope_super)
        h_get_super = _handler(app, match_info={"surface_id": surface_id}, user_id="root")
        resp_get_super = await _get(h_get_super)
        assert resp_get_super.status == 200

        # Viewer (B, groups=["g1"]) cannot delete -> 404, row intact.
        app["ui_surfaces_scope_resolver"] = _StubResolver(scope_b_g1)
        h_delete_b = _handler(app, match_info={"surface_id": surface_id}, user_id="user-b")
        resp_delete_b = await _delete(h_delete_b)
        assert resp_delete_b.status == 404
        assert await store.get(surface_id) is not None

    async def test_integration_routes_registered(self, store):
        """After route registration (mirrors BotManager.setup_app()'s FEAT-492
        block), all eight routes resolve; the literal 'capabilities'/
        'surfaces' segments match BEFORE the bare '{agent_id}/a2ui' pattern."""
        app = web.Application()
        app["ui_surfaces_store"] = store
        app["ui_surfaces_negotiation"] = SurfaceNegotiationService()
        router = app.router

        # Same order + literal-before-bare-pattern discipline as manager.py.
        router.add_view("/api/v1/agents/{agent_id}/a2ui/capabilities", A2UIHandler)
        router.add_view("/api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}", A2UIHandler)
        router.add_view("/api/v1/agents/{agent_id}/a2ui", A2UIHandler)
        router.add_view("/api/v1/ui/surfaces", UISurfacesHandler)
        router.add_view("/api/v1/ui/surfaces/{surface_id}", UISurfacesHandler)
        router.add_view("/api/v1/ui/surfaces/{surface_id}/refresh", UISurfacesHandler)
        router.add_view("/api/v1/ui/surfaces/{surface_id}/share", UISurfacesHandler)
        router.add_view("/api/v1/ui/surfaces/{surface_id}/share/{token}", UISurfacesHandler)

        # Registration order — proves the literal segments were registered
        # BEFORE the bare "{agent_id}/a2ui" pattern (aiohttp resolves
        # dynamic patterns in registration order for ambiguous prefixes).
        resource_paths = [(r.get_info().get("formatter") or r.get_info().get("path")) for r in router.resources()]
        assert resource_paths == [
            "/api/v1/agents/{agent_id}/a2ui/capabilities",
            "/api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}",
            "/api/v1/agents/{agent_id}/a2ui",
            "/api/v1/ui/surfaces",
            "/api/v1/ui/surfaces/{surface_id}",
            "/api/v1/ui/surfaces/{surface_id}/refresh",
            "/api/v1/ui/surfaces/{surface_id}/share",
            "/api/v1/ui/surfaces/{surface_id}/share/{token}",
        ]

        # And each of the eight URL shapes genuinely resolves to a real
        # handler (not aiohttp's own "no matching route" — a MatchInfoError).
        cases = [
            ("GET", "/api/v1/agents/demo/a2ui/capabilities"),
            ("GET", "/api/v1/agents/demo/a2ui/surfaces/some-id"),
            ("GET", "/api/v1/agents/demo/a2ui"),
            ("GET", "/api/v1/ui/surfaces"),
            ("GET", "/api/v1/ui/surfaces/some-id"),
            ("POST", "/api/v1/ui/surfaces/some-id/refresh"),
            ("POST", "/api/v1/ui/surfaces/some-id/share"),
            ("DELETE", "/api/v1/ui/surfaces/some-id/share/tok-1"),
        ]
        from aiohttp.test_utils import make_mocked_request

        router.freeze()
        for method, path in cases:
            match_info = await router.resolve(make_mocked_request(method, path))
            assert not isinstance(match_info, MatchInfoError), f"{method} {path} did not resolve"


class TestRenderFailureBothRoutes:
    """FEAT-499 TASK-2755: a stored surface that cannot be re-baked returns a
    structured 422 (never an uncaught 500) — via BOTH the ``UISurfacesHandler``
    REST lane AND the ``SurfaceNegotiationService.respond()`` call the
    ``A2UIHandler`` mirror route delegates to for the SAME record (FEAT-492
    G6: the two routes share one negotiation service instance by design, so
    a call into it directly IS the mirror route's own behaviour — the
    full-HTTP-both-URL-shapes parity check lives in
    ``test_a2ui_surfaces_route.py::TestBothRoutesAgree``)."""

    async def test_get_html_render_failure_returns_422(self, store):
        pytest.importorskip(
            "parrot.outputs.a2ui_renderers.interactive_html",
            reason="ai-parrot-visualizations not installed — HTML leg skipped",
        )
        surface_id = await _publish(
            store,
            surface_id="surface-e2e-broken",
            user_id="owner-broken",
        )
        # Overwrite with a genuinely unbakeable envelope (a required binding
        # with no parrot_optional marker and an absent data-model key).
        broken = _broken_chart_envelope("surface-e2e-broken")
        record = await store.get(surface_id)
        await store.update_envelope(surface_id, broken, record.recipe_params)

        app = {"ui_surfaces_store": store}
        h_html = _handler(app, match_info={"surface_id": surface_id}, user_id="owner-broken", query={"format": "html"})
        resp_rest = await _get(h_html)
        assert resp_rest.status == 422
        body_rest = await _decode(resp_rest)
        assert body_rest["status"] == "error"

        record = await store.get(surface_id)
        negotiation = SurfaceNegotiationService()
        resp_mirror = await negotiation.respond(record, "text/html")
        assert resp_mirror.status == 422
        body_mirror = json.loads(resp_mirror.body)
        assert body_mirror == body_rest
