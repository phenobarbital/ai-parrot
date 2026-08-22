"""Unit tests for CommCenterHandler routing, dispatch, and error mapping.

FEAT-417, Module 7. Full end-to-end HTTP tests (aiohttp ``TestClient`` +
authenticated session + a live/fake ``NotifyClient``) are sketched only as
elided placeholders in this task's own Test Specification (``client``,
``auth``, ``fake_notify`` fixtures are never defined there either) and
building that harness from scratch is out of this task's scope; these
tests instead exercise the handler's own logic directly — content-type
dispatch, template-source resolution, and error mapping — plus the
concrete route-registration test the spec does provide verbatim.
"""

import json
import uuid
from datetime import UTC, datetime

import pytest
from aiohttp import web
from parrot.handlers.comm_center import (
    CommCenterHandler,
    TemplateNotFoundError,
    _as_bool,
)
from parrot.services.comm_center.ingest import FileTooLargeError, IngestionError
from parrot.services.comm_center.render import RenderError


class TestRouteRegistration:
    """The exact scaffold given by this task's Test Specification."""

    def test_setup_registers_all_routes(self):
        app = web.Application()
        CommCenterHandler().setup(app)
        paths = {r.resource.canonical for r in app.router.routes()}
        assert "/api/v1/comm_center/sender" in paths
        assert "/api/v1/comm_center/sender/{batch_id}" in paths
        assert "/api/v1/comm_center/sender/{batch_id}/retry" in paths
        assert "/api/v1/comm_center/message" in paths
        assert "/api/v1/comm_center/placeholders" in paths
        assert "/api/v1/comm_center/templates" in paths
        assert "/api/v1/comm_center/templates/{template_id}" in paths

    def test_setup_registers_get_sender_batch_list_route(self):
        """FEAT-445 TASK-2319: GET /sender (no path param) lists batches."""
        app = web.Application()
        CommCenterHandler().setup(app)
        methods_by_path: dict = {}
        for r in app.router.routes():
            methods_by_path.setdefault(r.resource.canonical, set()).add(r.method)
        assert methods_by_path["/api/v1/comm_center/sender"] == {"GET", "POST"}

    def test_setup_registers_all_twelve_routes(self):
        app = web.Application()
        CommCenterHandler().setup(app)
        assert len(list(app.router.routes())) == 12

    def test_handler_is_instantiable(self):
        assert CommCenterHandler() is not None

    def test_placeholder_catalog_cached_once(self):
        handler = CommCenterHandler()
        assert handler._placeholder_catalog is handler._placeholder_catalog


class TestAsBool:
    """The query-string / form-field boolean coercion helper."""

    @pytest.mark.parametrize("value", [True, "true", "True", "1", "yes", "YES"])
    def test_truthy_values(self, value):
        assert _as_bool(value) is True

    @pytest.mark.parametrize("value", [False, "false", "0", "no", None, ""])
    def test_falsy_values(self, value):
        assert _as_bool(value) is False


class TestErrorMapping:
    """Service-layer exceptions map to the spec §2 Edge Cases status table.

    ``_map_error`` always raises (never returns) — verified live that the
    inherited ``BaseHandler.error()`` only recognizes a fixed status
    whitelist (400/401/403/404/406/412/428) and silently falls back to 400
    for anything else, which would otherwise turn 413/503 into a
    misleading 400. ``_map_error`` raises the matching
    ``aiohttp.web.HTTPException`` subclass directly instead.
    """

    def test_file_too_large_maps_to_413(self):
        handler = CommCenterHandler()
        with pytest.raises(web.HTTPException) as excinfo:
            handler._map_error(FileTooLargeError("too big"))
        assert excinfo.value.status == 413

    def test_template_not_found_maps_to_404(self):
        handler = CommCenterHandler()
        with pytest.raises(web.HTTPException) as excinfo:
            handler._map_error(TemplateNotFoundError("not found"))
        assert excinfo.value.status == 404

    def test_bare_keyerror_does_not_leak_as_404(self):
        """Regression guard: KeyError is a LookupError subclass in stdlib —
        mapping on bare LookupError would misreport it as 404 instead of
        the generic 400 fallback (found and fixed during this task)."""
        handler = CommCenterHandler()
        with pytest.raises(web.HTTPException) as excinfo:
            handler._map_error(KeyError("surprise"))
        assert excinfo.value.status == 400

    def test_runtime_error_maps_to_503(self):
        handler = CommCenterHandler()
        with pytest.raises(web.HTTPException) as excinfo:
            handler._map_error(RuntimeError("async-notify missing"))
        assert excinfo.value.status == 503

    def test_ingestion_error_maps_to_400(self):
        handler = CommCenterHandler()
        with pytest.raises(web.HTTPException) as excinfo:
            handler._map_error(IngestionError("bad file"))
        assert excinfo.value.status == 400

    def test_render_error_maps_to_400(self):
        handler = CommCenterHandler()
        with pytest.raises(web.HTTPException) as excinfo:
            handler._map_error(RenderError("bad template"))
        assert excinfo.value.status == 400

    def test_value_error_maps_to_400(self):
        handler = CommCenterHandler()
        with pytest.raises(web.HTTPException) as excinfo:
            handler._map_error(ValueError("missing provider"))
        assert excinfo.value.status == 400


class TestResolveTemplateSource:
    """Exactly-one-of-four template source validation."""

    async def test_requires_exactly_one_source(self):
        handler = CommCenterHandler()

        class Meta:
            template_id = None
            template_name = None
            template = None
            template_file = None

        with pytest.raises(ValueError, match="Exactly one"):
            await handler._resolve_template_source(Meta())

    async def test_rejects_more_than_one_source(self):
        handler = CommCenterHandler()

        class Meta:
            template_id = None
            template_name = None
            template = "Hola {{ name }}"
            template_file = "welcome.html"

        with pytest.raises(ValueError, match="Exactly one"):
            await handler._resolve_template_source(Meta())

    async def test_inline_template_returned_directly(self):
        handler = CommCenterHandler()

        class Meta:
            template_id = None
            template_name = None
            template = "Hola {{ name }}"
            template_file = None

        body, subject = await handler._resolve_template_source(Meta())
        assert body == "Hola {{ name }}"
        assert subject is None

    async def test_missing_template_file_raises_template_not_found(
        self, tmp_path, monkeypatch
    ):
        import parrot.handlers.comm_center as comm_center_module

        class FakeConf:
            TEMPLATE_DIR = tmp_path

        monkeypatch.setitem(
            __import__("sys").modules, "notify.conf", FakeConf()
        )
        handler = comm_center_module.CommCenterHandler()

        class Meta:
            template_id = None
            template_name = None
            template = None
            template_file = "does-not-exist.html"

        with pytest.raises(TemplateNotFoundError):
            await handler._resolve_template_source(Meta())


class TestIngestFromRequest:
    """Content-type dispatch across the three transports."""

    async def test_json_recipients_transport(self, monkeypatch):
        import parrot.handlers.comm_center as comm_center_module

        captured = {}

        async def fake_ingest_recipients(**kwargs):
            captured.update(kwargs)
            return ["fake-recipient"]

        monkeypatch.setattr(
            comm_center_module, "ingest_recipients", fake_ingest_recipients
        )

        class FakeRequest:
            content_type = "application/json"

            async def json(self, **kwargs):
                return {"provider": "email", "recipients": [{"name": "Ana"}]}

        handler = CommCenterHandler()

        async def fake_get_json(request=None):
            return {"provider": "email", "recipients": [{"name": "Ana"}]}

        monkeypatch.setattr(handler, "get_json", fake_get_json)
        recipients, meta = await handler._ingest_from_request(FakeRequest())
        assert recipients == ["fake-recipient"]
        assert meta["provider"] == "email"
        assert captured == {"rows": [{"name": "Ana"}]}

    async def test_json_missing_recipients_and_file_b64_raises(self, monkeypatch):
        handler = CommCenterHandler()

        class FakeRequest:
            content_type = "application/json"

        async def fake_get_json(request=None):
            return {"provider": "email"}

        monkeypatch.setattr(handler, "get_json", fake_get_json)
        with pytest.raises(IngestionError):
            await handler._ingest_from_request(FakeRequest())

    async def test_unsupported_content_type_raises(self):
        handler = CommCenterHandler()

        class FakeRequest:
            content_type = "text/plain"

        with pytest.raises(IngestionError, match="Unsupported Content-Type"):
            await handler._ingest_from_request(FakeRequest())


class _FakeBatchRow(dict):
    """A dict subclass so ``row["key"]`` access (asyncdb's fetchall shape) works."""


class _FakeBatchConn:
    """Captures every ``fetchall`` call and answers list vs. count queries.

    The handler issues exactly two ``fetchall`` calls per request: the
    paginated, aggregated batch list (query contains ``ORDER BY``), then the
    total-batch-count query (no ``ORDER BY``). Distinguishing on that
    substring avoids coupling the test to exact SQL text.
    """

    def __init__(self, list_rows: list, total: int):
        self.list_rows = list_rows
        self.total = total
        self.queries: list = []

    async def fetchall(self, query, params=None):
        self.queries.append((query, params))
        if "ORDER BY" in query:
            return self.list_rows
        return [{"total": self.total}]


class _FakeBatchConnCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc_info):
        return False


class _FakeBatchAsyncDB:
    def __init__(self, conn):
        self._conn = conn

    async def connection(self):
        return _FakeBatchConnCtx(self._conn)


def _fake_request(query: dict):
    class FakeRequest:
        def __init__(self, q):
            self.query = q

    return FakeRequest(query)


async def _decode(response: web.Response) -> dict:
    return json.loads(response.body)


async def _call_get_batches(handler, request):
    """Call the real ``get_batches`` logic, bypassing ``@is_authenticated()``.

    ``@is_authenticated()`` wraps the coroutine with ``functools.wraps``, so
    ``__wrapped__`` is the original, undecorated method — calling it
    directly exercises the handler's own logic without needing a real
    aiohttp ``web.Request``/session/app (the decorator's own
    ``isinstance(request, web.Request)`` check would otherwise reject the
    lightweight fake request used throughout this module, matching every
    other test in this file that talks to a handler method directly).
    Authentication enforcement itself is asserted separately in
    ``TestGetBatchesAuthentication`` against a real ``web.Request``.
    """
    return await CommCenterHandler.get_batches.__wrapped__(handler, request)


class TestGetBatches:
    """FEAT-445 TASK-2319: ``GET /api/v1/comm_center/sender`` — batch list."""

    async def test_empty_result(self, monkeypatch):
        import parrot.handlers.comm_center as comm_center_module

        conn = _FakeBatchConn(list_rows=[], total=0)
        monkeypatch.setattr(comm_center_module, "_get_db", lambda: _FakeBatchAsyncDB(conn))

        handler = CommCenterHandler()
        response = await _call_get_batches(handler, _fake_request({}))

        assert response.status == 200
        body = await _decode(response)
        assert body == {"batches": [], "total": 0, "limit": 25, "offset": 0}

    async def test_pagination_params_respected_and_clamped(self, monkeypatch):
        import parrot.handlers.comm_center as comm_center_module

        conn = _FakeBatchConn(list_rows=[], total=0)
        monkeypatch.setattr(comm_center_module, "_get_db", lambda: _FakeBatchAsyncDB(conn))

        handler = CommCenterHandler()
        response = await _call_get_batches(
            handler, _fake_request({"limit": "500", "offset": "10"})
        )
        body = await _decode(response)

        assert body["limit"] == 100  # clamped to the documented max
        assert body["offset"] == 10
        list_params = conn.queries[0][1]
        assert list_params[-2:] == (100, 10)  # (limit, offset) tail params

    async def test_status_filter_adds_subquery_predicate(self, monkeypatch):
        import parrot.handlers.comm_center as comm_center_module

        conn = _FakeBatchConn(list_rows=[], total=0)
        monkeypatch.setattr(comm_center_module, "_get_db", lambda: _FakeBatchAsyncDB(conn))

        handler = CommCenterHandler()
        await _call_get_batches(handler, _fake_request({"status": "skipped"}))

        list_query, list_params = conn.queries[0]
        assert "status = $1" in list_query
        assert list_params[0] == "skipped"

    async def test_created_after_and_before_filters(self, monkeypatch):
        import parrot.handlers.comm_center as comm_center_module

        conn = _FakeBatchConn(list_rows=[], total=0)
        monkeypatch.setattr(comm_center_module, "_get_db", lambda: _FakeBatchAsyncDB(conn))

        handler = CommCenterHandler()
        await _call_get_batches(
            handler,
            _fake_request(
                {"created_after": "2026-01-01", "created_before": "2026-12-31"}
            ),
        )

        list_query, list_params = conn.queries[0]
        assert "created_at >=" in list_query
        assert "created_at <=" in list_query
        assert "2026-01-01" in list_params
        assert "2026-12-31" in list_params

    async def test_aggregated_shape_and_batch_id_stringified(self, monkeypatch):
        import parrot.handlers.comm_center as comm_center_module

        batch_id = uuid.uuid4()
        now = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)
        row = _FakeBatchRow(
            batch_id=batch_id,
            created_at=now,
            created_by=42,
            template_ref="monthly-report",
            provider="email",
            total=150,
            queued=140,
            skipped=8,
            publish_failed=2,
            pending=0,
        )
        conn = _FakeBatchConn(list_rows=[row], total=1)
        monkeypatch.setattr(comm_center_module, "_get_db", lambda: _FakeBatchAsyncDB(conn))

        handler = CommCenterHandler()
        response = await _call_get_batches(handler, _fake_request({}))
        body = await _decode(response)

        assert body["total"] == 1
        batch = body["batches"][0]
        assert batch["batch_id"] == str(batch_id)
        assert batch["created_by"] == 42
        assert batch["total"] == 150
        assert batch["queued"] == 140
        assert batch["skipped"] == 8
        assert batch["publish_failed"] == 2
        assert batch["pending"] == 0
        assert batch["template_ref"] == "monthly-report"
        assert batch["provider"] == "email"


class TestGetBatchesAuthentication:
    """``GET /sender`` (batch list) requires authentication like every other
    CommCenter endpoint — exercised against the real ``@is_authenticated()``
    wrapper (not bypassed via ``__wrapped__`` like ``TestGetBatches`` above).
    """

    async def test_unauthenticated_request_rejected(self):
        """No auth backend configured -> the decorator itself raises before
        the handler's own DB-querying logic ever runs (proved by the absence
        of any ``_get_db``/``fetchall`` call — nothing is monkeypatched here,
        so a real DB call would error very differently, e.g. connection
        refused, not an HTTP exception raised by the decorator)."""
        from aiohttp.test_utils import make_mocked_request

        handler = CommCenterHandler()
        request = make_mocked_request("GET", "/api/v1/comm_center/sender")
        with pytest.raises(web.HTTPException) as excinfo:
            await handler.get_batches(request)
        assert excinfo.value.status in (400, 401, 403)
