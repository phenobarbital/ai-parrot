"""Unit tests for module-level tenant migration (FEAT-421 TASK-2203)."""

import pytest
from aiohttp.test_utils import make_mocked_request
from parrot_formdesigner.api.operations import handle_operations
from parrot_formdesigner.api.render import (
    _RENDERERS,
    get_renderer,
    handle_render,
    register_renderer,
)
from parrot_formdesigner.api.uploads import handle_rest_upload
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.renderers.base import AbstractFormRenderer
from parrot_formdesigner.services.registry import FormRegistry


class TestUtilsCleanup:
    def test_get_request_tenant_is_gone(self):
        from parrot_formdesigner.api import _utils

        assert not hasattr(_utils, "_get_request_tenant")

    def test_surviving_helpers_still_importable(self):
        from parrot_formdesigner.api._utils import (
            _bump_version,
            _deep_merge,
            _loc_to_str,
        )

        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
        assert _bump_version("1.0") == "1.1"
        assert _loc_to_str({"en": "hi"}) == "hi"


@pytest.fixture
def registry():
    return FormRegistry()


def _request(method, path, *, app, tenant=None, match_info=None):
    request = make_mocked_request(method, path, app=app, match_info=match_info or {})
    if tenant is not None:
        request["tenant"] = tenant
    return request


class TestOperationsModuleLevel:
    async def test_no_tenant_raises_rather_than_defaults(self, registry):
        app = {"form_registry": registry}
        request = _request(
            "PATCH",
            "/api/v1/x/forms/uid/operations",
            app=app,
            match_info={"form_uid": "00000000-0000-0000-0000-000000000000"},
        )
        with pytest.raises(RuntimeError):
            await handle_operations(request)

    async def test_operations_uses_declared_tenant(self, registry):
        form = FormSchema(
            form_id="contact", title={"en": "Contact"}, tenant="flexroc", sections=[]
        )
        await registry.register(form, tenant="flexroc")

        app = {"form_registry": registry}
        request = _request(
            "PATCH",
            f"/api/v1/navigator/forms/{form.form_uid}/operations",
            app=app,
            tenant="navigator",
            match_info={"form_uid": str(form.form_uid)},
        )
        resp = await handle_operations(request)
        # Declared tenant (navigator) does not own this form (flexroc) —
        # registry.get() is tenant-scoped, so it must 404, not leak across
        # tenants.
        assert resp.status == 404


class TestRenderModuleLevel:
    @pytest.fixture(autouse=True)
    def _reset_renderers(self):
        snapshot = dict(_RENDERERS)
        _RENDERERS.clear()
        yield
        _RENDERERS.clear()
        _RENDERERS.update(snapshot)

    async def test_no_tenant_raises_rather_than_defaults(self, registry):
        class _Dummy(AbstractFormRenderer):
            async def render(self, form, **kwargs):
                raise NotImplementedError

        register_renderer("html", _Dummy())
        assert get_renderer("html") is not None

        app = {"form_registry": registry}
        request = _request(
            "GET",
            "/api/v1/x/forms/uid/render/html",
            app=app,
            match_info={
                "form_uid": "00000000-0000-0000-0000-000000000000",
                "format": "html",
            },
        )
        with pytest.raises(RuntimeError):
            await handle_render(request)

    async def test_render_uses_declared_tenant(self, registry):
        class _Dummy(AbstractFormRenderer):
            async def render(self, form, **kwargs):
                from parrot_formdesigner.core.schema import RenderedForm

                return RenderedForm(content="<x/>", content_type="application/xml")

        register_renderer("html", _Dummy())

        form = FormSchema(
            form_id="contact", title={"en": "Contact"}, tenant="flexroc", sections=[]
        )
        await registry.register(form, tenant="flexroc")

        app = {"form_registry": registry}
        request = _request(
            "GET",
            f"/api/v1/navigator/forms/{form.form_uid}/render/html",
            app=app,
            tenant="navigator",
            match_info={"form_uid": str(form.form_uid), "format": "html"},
        )
        resp = await handle_render(request)
        assert resp.status == 404


class TestUploadModuleLevel:
    async def test_no_tenant_raises_rather_than_defaults(self, registry):
        app = {"form_registry": registry}
        request = _request(
            "POST",
            "/api/v1/x/forms/uid/fields/field/upload",
            app=app,
            match_info={
                "form_uid": "00000000-0000-0000-0000-000000000000",
                "field_uid": "00000000-0000-0000-0000-000000000001",
            },
        )
        with pytest.raises(RuntimeError):
            await handle_rest_upload(request)
