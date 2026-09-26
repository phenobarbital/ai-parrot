"""FEAT-598 TASK-3791 linked-surface persistence and refresh integration tests.

The real toolkit, linked service, UI-surface store, mixin, and handler are
exercised.  Only the Postgres connection, QuerySource, catalog row, and
data-plane authorization boundary are replaced.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from parrot.bots.mixins import InfographicAuthoringMixin
from parrot.handlers.models import ui_surfaces as store_module
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore
from parrot.handlers.ui_surfaces import UISurfacesHandler
from parrot.handlers.ui_surfaces_scope import SurfaceScope
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope
from parrot.outputs.a2ui.linked import has_data_sources
from parrot.outputs.a2ui.linked.service import LinkedSurfaceService
from parrot.outputs.a2ui.models import CreateSurface
from parrot_tools.querysource import _qs
from parrot_tools.querysource.toolkit import QuerysourceToolkit

pytestmark = pytest.mark.asyncio


class _FakeConnCtx:
    """Async context wrapper for the duplicated in-memory Postgres harness."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc_info):
        return False


def _row_from_insert_args(args) -> dict:
    """Build a fake ui_surfaces row from PgUISurfaceStore's INSERT args."""
    keys = (
        "surface_id", "kind", "title", "envelope", "catalog_id", "agent_id", "user_id", "session_id",
        "recipe_name", "recipe_owner", "recipe_params", "tenant", "visibility", "allowed_groups",
        "created_at", "updated_at",
    )
    return dict(zip(keys, args, strict=True))


class _FakeConn:
    """SQL-string dispatch over state.surfaces, including conditional update."""

    def __init__(self, state):
        self.state = state

    async def execute(self, sql, *args):
        if sql.strip().upper().startswith(("CREATE", "ALTER")):
            self.state.ddl_calls.append(sql)
            return None
        raise AssertionError(f"Unexpected execute SQL: {sql!r}")

    async def fetch_one(self, sql, *args):
        if sql == store_module._GET_SQL:
            row = self.state.surfaces.get(args[0])
            return dict(row) if row else None
        raise AssertionError(f"Unexpected fetch_one SQL: {sql!r}")

    async def fetchval(self, sql, *args):
        if sql in (store_module._INSERT_OR_SKIP_SQL, store_module._UPSERT_SQL):
            surface_id = args[0]
            if sql == store_module._INSERT_OR_SKIP_SQL and surface_id in self.state.surfaces:
                return None
            self.state.surfaces[surface_id] = _row_from_insert_args(args)
            return surface_id
        if sql == store_module._UPDATE_ENVELOPE_SQL:
            surface_id, envelope, recipe_params = args
            row = self.state.surfaces.get(surface_id)
            if row is None:
                return None
            row.update(envelope=envelope, recipe_params=recipe_params, updated_at=datetime.now(UTC))
            return surface_id
        if sql == store_module._UPDATE_ENVELOPE_IF_UNCHANGED_SQL:
            surface_id, envelope, recipe_params, expected_updated_at = args
            row = self.state.surfaces.get(surface_id)
            if row is None or row["updated_at"] != expected_updated_at:
                return None
            row.update(envelope=envelope, recipe_params=recipe_params, updated_at=datetime.now(UTC))
            return surface_id
        raise AssertionError(f"Unexpected fetchval SQL: {sql!r}")


class _FakeAsyncDB:
    """Duplicate suite-local asyncdb boundary."""

    def __init__(self, state):
        self.state = state

    async def connection(self):
        return _FakeConnCtx(_FakeConn(self.state))


@pytest.fixture
def fake_state():
    """Mutable in-memory UI-surface table state."""
    return SimpleNamespace(surfaces={}, ddl_calls=[])


@pytest.fixture
def store(monkeypatch, fake_state):
    """Real store wired to the duplicated in-memory connection."""
    value = PgUISurfaceStore(dsn="postgres://fake/linked-e2e")
    monkeypatch.setattr(value, "_get_db", lambda: _FakeAsyncDB(fake_state))
    return value


class _FakeRequest:
    """Minimal request accepted by UISurfacesHandler's undecorated methods."""

    def __init__(self, app, *, match_info=None, path="", json_body=None, user_id="owner-1", query=None):
        self.app = app
        self.match_info = match_info or {}
        self.path = path
        self._json_body = json_body
        self.user = SimpleNamespace(user_id=user_id) if user_id else None
        self.query = query or {}
        self.headers = {}

    async def json(self):
        if self._json_body is None:
            raise ValueError("no body")
        return self._json_body


def _handler(app, **kwargs):
    """Construct a handler without the full navigator view lifecycle."""
    handler = UISurfacesHandler.__new__(UISurfacesHandler)
    handler.logger = logging.getLogger("test.linked_surfaces_e2e")
    handler._request = _FakeRequest(app, **kwargs)
    return handler


def _unwrap(method):
    """Unwrap navigator decorators for direct handler invocation."""
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _get(handler):
    """Invoke the real GET handler."""
    return await _unwrap(UISurfacesHandler.get)(handler)


async def _post(handler):
    """Invoke the real POST handler."""
    return await _unwrap(UISurfacesHandler.post)(handler)


async def _decode(response) -> dict:
    """Decode an aiohttp JSON response."""
    return json.loads(response.body)


class _StubResolver:
    """Fixed owner scope for handler calls."""

    def __init__(self, scope: SurfaceScope):
        self._scope = scope

    async def resolve(self, request):
        return self._scope


class _MiniBot(InfographicAuthoringMixin):
    """Lightweight real mixin host for publish_surface."""

    def __init__(self) -> None:
        self.name = "reporter"
        self.logger = logging.getLogger("test.linked_surfaces_e2e.bot")


@pytest.fixture
def fake_core_qs(monkeypatch):
    """Patch QuerySlugSource QS factories and record bounded executions."""
    state = SimpleNamespace(
        executions=0,
        kwargs=[],
        closed=0,
        frame=pd.DataFrame(
            {
                "day": pd.date_range("2026-09-01", periods=3, tz="UTC"),
                "visits": [1, 2, 3],
                "program": ["epson", "epson", "epson"],
            }
        ),
    )

    class FakeQS:
        def __init__(self, **kwargs):
            state.kwargs.append(kwargs)

        async def query(self, output_format=None):
            state.executions += 1
            return state.frame.copy(), None

        async def close(self):
            state.closed += 1

    import parrot.tools.dataset_manager.sources.query_slug as query_slug

    monkeypatch.setattr(query_slug, "_get_qs", lambda: FakeQS)
    monkeypatch.setattr(query_slug, "_get_multiqs", lambda: FakeQS)
    return state


@pytest.fixture
def allow_guard():
    """Recording allow-all data-plane guard used by LinkedSurfaceService."""
    class Guard:
        calls: list[tuple[str, str]] = []

        async def authorize_source(self, ctx, resources):
            if resources.source_type == "query_slug":
                self.calls.append((resources.source_type, resources.source_id))

        async def rls_predicates(self, ctx, resources):
            """Allow the authorizing wrapper to continue without row filters."""
            return []

    return Guard()


@pytest.fixture
def app(store, allow_guard):
    """Handler wiring with an owner scope and configured linked guard."""
    return {
        "ui_surfaces_store": store,
        "ui_surfaces_scope_resolver": _StubResolver(
            SurfaceScope(user_id="owner-1", tenant=None, groups=frozenset())
        ),
        "linked_surface_service": LinkedSurfaceService(guard=allow_guard),
    }


@pytest.fixture
def patched_catalog(monkeypatch):
    """One public.queries row for the toolkit's real SlugCatalog."""
    row = SimpleNamespace(
        query_slug="epson_field_activity",
        program_slug="epson",
        description="Field activity",
        provider="db",
        is_cached=True,
        cache_timeout=3600,
        conditions={"firstdate": "2026-09-01", "lastdate": "2026-09-03"},
        cond_definition={"firstdate": "date", "lastdate": "date"},
        filtering={},
        fields=[],
        ordering=[],
        grouping=[],
        query_raw="SELECT * FROM activity WHERE day BETWEEN {firstdate} AND {lastdate} {where_cond}",
    )

    class FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    class FakeAsyncDB:
        def __init__(self, *args, **kwargs):
            pass

        async def connection(self):
            return FakeConn()

        async def close(self):
            return None

    class FakeQueryModel:
        @classmethod
        async def get(cls, *, query_slug, _connection=None):
            if query_slug != row.query_slug:
                raise LookupError(query_slug)
            return row

    monkeypatch.setattr(_qs, "QueryModel", FakeQueryModel)
    monkeypatch.setattr("parrot_tools.querysource.catalog.AsyncDB", FakeAsyncDB)


async def _build_envelope(snapshot: bool) -> CreateSurface:
    """Build one linked chart through the real QuerysourceToolkit."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    result = await toolkit.build_linked_surface(
        "epson_field_activity",
        {"component": "Chart", "type": "bar", "x": "day", "y": ["visits"]},
        request={"placeholders": {"firstdate": "YESTERDAY", "lastdate": "TODAY"}},
        snapshot=snapshot,
    )
    return CreateSurface.model_validate(result["a2ui_envelope"])


class TestLinkedSurfacesE2E:
    """Cross-package linked-surface flows required by spec §4."""

    async def test_linked_surface_end_to_end(self, app, store, fake_core_qs, allow_guard, patched_catalog):
        """Tool output validates, bakes, persists, and refreshes through descriptors."""
        envelope = await _build_envelope(snapshot=True)
        assert fake_core_qs.executions == 1
        validate_envelope(envelope, origin=ProducerOrigin.TOOL)
        assert bake_envelope(envelope)

        bot = _MiniBot()
        bot._linked_surface_service = app["linked_surface_service"]
        surface_id = await bot.publish_surface(
            kind="dashboard", title="Linked", envelope=envelope, surface_store=store, user_id="owner-1"
        )
        record = await store.get(surface_id)
        assert record is not None and record.refreshable is True
        before = record.envelope["metadata"]["extensions"]["parrot_data_sources"]["epson_field_activity"]["snapshot_at"]

        response = await _post(
            _handler(
                app,
                match_info={"surface_id": surface_id},
                path=f"/api/v1/ui/surfaces/{surface_id}/refresh",
                json_body={"params": {}},
            )
        )
        assert response.status == 200
        assert fake_core_qs.executions == 2
        updated = await store.get(surface_id)
        assert updated is not None
        after = updated.envelope["metadata"]["extensions"]["parrot_data_sources"]["epson_field_activity"]["snapshot_at"]
        assert after >= before
        assert allow_guard.calls == [("query_slug", "public:epson_field_activity")] * 2
        assert all(kwargs["conditions"]["querylimit"] == 5000 for kwargs in fake_core_qs.kwargs)
        assert fake_core_qs.closed == 2

    async def test_linked_surface_no_snapshot_persist_roundtrip(self, app, store, fake_core_qs, patched_catalog):
        """Save materializes an empty snapshot once; JSON and HTML GET never execute."""
        envelope = await _build_envelope(snapshot=False)
        assert fake_core_qs.executions == 1
        data_key = "epson_field_activity"
        assert envelope.data_model[data_key] == {"rows": []}
        fake_core_qs.executions = 0

        response = await _post(
            _handler(
                app,
                path="/api/v1/ui/surfaces",
                json_body={"kind": "dashboard", "title": "Unbaked", "envelope": envelope.model_dump(by_alias=True, mode="json")},
            )
        )
        assert response.status == 201
        surface_id = (await _decode(response))["surface_id"]
        assert fake_core_qs.executions == 1
        persisted = await store.get(surface_id)
        assert persisted is not None
        assert persisted.envelope["dataModel"][data_key]["rows"]
        assert has_data_sources(persisted.envelope)

        fake_core_qs.executions = 0
        json_response = await _get(_handler(app, match_info={"surface_id": surface_id}))
        assert json_response.status == 200
        assert fake_core_qs.executions == 0
        pytest.importorskip(
            "parrot.outputs.a2ui_renderers.interactive_html",
            reason="ai-parrot-visualizations not installed — HTML leg skipped",
        )
        html_response = await _get(_handler(app, match_info={"surface_id": surface_id}, query={"format": "html"}))
        assert html_response.status == 200
        assert fake_core_qs.executions == 0

    async def test_linked_refresh_conflict_409(self, app, store, fake_core_qs, patched_catalog, monkeypatch):
        """A conditional refresh write that loses its race returns the newer snapshot."""
        envelope = await _build_envelope(snapshot=True)
        bot = _MiniBot()
        bot._linked_surface_service = app["linked_surface_service"]
        surface_id = await bot.publish_surface(
            kind="dashboard", title="Conflict", envelope=envelope, surface_store=store, user_id="owner-1"
        )
        record = await store.get(surface_id)
        assert record is not None
        source = record.envelope["metadata"]["extensions"]["parrot_data_sources"]["epson_field_activity"]
        source["snapshot_at"] = "2099-01-01T00:00:00+00:00"
        raw = next(iter(app["ui_surfaces_store"]._get_db().state.surfaces.values()))

        async def lose_race(*args, **kwargs):
            raw["updated_at"] = record.updated_at + timedelta(seconds=1)
            return False

        monkeypatch.setattr(store, "update_envelope", lose_race)

        response = await _post(
            _handler(
                app,
                match_info={"surface_id": surface_id},
                path=f"/api/v1/ui/surfaces/{surface_id}/refresh",
                json_body={"params": {}},
            )
        )
        assert response.status == 409
        body = await _decode(response)
        assert body == {"status": "error", "error": "stale refresh", "snapshot_at": "2099-01-01T00:00:00+00:00"}
        stored = await store.get(surface_id)
        assert stored is not None
        assert stored.envelope["metadata"]["extensions"]["parrot_data_sources"]["epson_field_activity"]["snapshot_at"] == source["snapshot_at"]

    async def test_linked_save_without_guard_fails_closed(self, store, fake_core_qs, patched_catalog):
        """A linked pin save without a configured guard is rejected before execution or persistence."""
        envelope = await _build_envelope(snapshot=False)
        fake_core_qs.executions = 0
        app = {
            "ui_surfaces_store": store,
            "ui_surfaces_scope_resolver": _StubResolver(
                SurfaceScope(user_id="owner-1", tenant=None, groups=frozenset())
            ),
        }
        response = await _post(
            _handler(
                app,
                path="/api/v1/ui/surfaces",
                json_body={"kind": "dashboard", "title": "Denied", "envelope": envelope.model_dump(by_alias=True, mode="json")},
            )
        )
        assert response.status == 403
        assert fake_core_qs.executions == 0
        assert not app["ui_surfaces_store"]._get_db().state.surfaces
