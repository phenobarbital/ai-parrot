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

    def test_setup_registers_all_eleven_routes(self):
        app = web.Application()
        CommCenterHandler().setup(app)
        assert len(list(app.router.routes())) == 11

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


class TestUnimplementedStubs:
    """Stubs left for TASK-2160 (templates CRUD) and TASK-2161 (post_message).

    Every route method is wrapped in ``@is_authenticated()``, whose
    ``_func_wrapper`` reads the request from the *last positional*
    argument (``args[-1]``) and requires an actual ``web.Request``
    instance — verified live, calling with a keyword ``request=None``
    raises ``ValueError`` before ever reaching the stub body. A real
    (``aiohttp.test_utils.make_mocked_request``) request is passed
    positionally instead, with ``authenticated=True`` pre-set so the
    decorator's own backend-authentication path is never exercised here
    (that is ``navigator_auth``'s concern, not this handler's).
    """

    @pytest.mark.parametrize(
        "method_name",
        [
            "post_message",
            "list_templates",
            "get_template",
            "create_template",
            "update_template",
            "delete_template",
        ],
    )
    async def test_stub_raises_not_implemented(self, method_name):
        from aiohttp.test_utils import make_mocked_request

        handler = CommCenterHandler()
        method = getattr(handler, method_name)
        request = make_mocked_request("GET", "/api/v1/comm_center/x")
        request["authenticated"] = True
        with pytest.raises(NotImplementedError):
            await method(request)
