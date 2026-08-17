"""Unit tests for Telegram WebApp tenant handling (FEAT-421 TASK-2204).

Uses a mocked ``FormRegistry`` for the positive-path tests rather than a
real one: ``ui/telegram.py`` reads ``request.match_info["form_uid"]`` as a
plain string without coercing it to ``uuid.UUID`` via ``extract_form_uid``
(unlike ``api/handlers.py`` and the other module-level handlers) — a
pre-existing bug (TASK-1990/1246 era, predating FEAT-421) that makes a real
``FormRegistry.get()`` always return ``None`` regardless of tenant
correctness. Out of scope for this task (not listed anywhere in its Scope);
mocking the registry isolates the tenant-declaration behaviour this task
DOES own from that unrelated defect.
"""

from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import make_mocked_request
from parrot_formdesigner.api.errors import TenantNotDeclaredError
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.ui.telegram import TelegramWebAppHandler


def _request(method, path, *, tenant=None, match_info=None, app=None):
    request = make_mocked_request(
        method, path, app=app or {}, match_info=match_info or {}
    )
    if tenant is not None:
        request["tenant"] = tenant
    return request


class TestTelegramTenant:
    def test_local_duplicate_is_gone(self):
        from parrot_formdesigner.ui import telegram as telegram_module

        assert not hasattr(telegram_module, "_get_request_tenant")

    async def test_serve_webapp_uses_declared_tenant(self):
        form = FormSchema(
            form_id="contact", title={"en": "Contact"}, tenant="flexroc", sections=[]
        )
        registry = AsyncMock()
        registry.get.return_value = form
        telegram = TelegramWebAppHandler(registry=registry)

        request = _request(
            "GET",
            f"/t/flexroc/forms/{form.form_uid}/telegram",
            tenant="flexroc",
            match_info={"form_uid": str(form.form_uid)},
        )
        resp = await telegram.serve_webapp(request)

        registry.get.assert_awaited_once_with(str(form.form_uid), tenant="flexroc")
        assert resp.status == 200
        assert (
            f"/api/v1/t/flexroc/forms/{form.form_uid}/telegram-submit" in resp.text
        )

    async def test_serve_webapp_other_tenant_is_404(self):
        """registry.get(uid, tenant="flexroc") returns None when the form
        is registered under a different tenant — the tenant-scoped lookup
        itself is the 404 gate, before any explicit cross-check runs."""
        registry = AsyncMock()
        registry.get.return_value = None
        telegram = TelegramWebAppHandler(registry=registry)

        request = _request(
            "GET",
            "/t/flexroc/forms/some-uid/telegram",
            tenant="flexroc",
            match_info={"form_uid": "some-uid"},
        )
        resp = await telegram.serve_webapp(request)

        registry.get.assert_awaited_once_with("some-uid", tenant="flexroc")
        assert resp.status == 404

    async def test_rest_fallback_uses_declared_tenant(self):
        form = FormSchema(
            form_id="contact",
            title={"en": "Contact"},
            tenant="flexroc",
            sections=[],
        )
        registry = AsyncMock()
        registry.get.return_value = form
        telegram = TelegramWebAppHandler(registry=registry)

        request = _request(
            "POST",
            f"/api/v1/t/flexroc/forms/{form.form_uid}/telegram-submit",
            tenant="flexroc",
            match_info={"form_uid": str(form.form_uid)},
        )

        async def _json():
            return {}

        request.json = _json
        resp = await telegram.rest_fallback(request)

        registry.get.assert_awaited_once_with(str(form.form_uid), tenant="flexroc")
        assert resp.status in (200, 422)

    async def test_missing_tenant_is_400_through_the_wrapped_route(self):
        """The 400 comes from the requires_tenant decorator applied in
        ui/routes.py (`_page_wrap(..., protect=False, tenant="public")`),
        not from the handler itself — calling the raw handler with no
        decorator at all is a RuntimeError (programming error), covered by
        the next test and by TASK-2199/2200's generic decorator tests."""
        from parrot_formdesigner.ui.routes import _page_wrap

        registry = AsyncMock()
        telegram = TelegramWebAppHandler(registry=registry)
        wrapped = _page_wrap(telegram.serve_webapp, protect=False, tenant="public")
        request = _request(
            "GET",
            "/t//forms/uid/telegram",
            match_info={
                "tenant": "",
                "form_uid": "00000000-0000-0000-0000-000000000000",
            },
        )
        with pytest.raises(TenantNotDeclaredError):
            await wrapped(request)

    async def test_serve_webapp_raises_runtime_error_without_decorator(self):
        """declared_tenant() itself raises RuntimeError, never a default,
        when the route was mounted without the decorator at all."""
        registry = AsyncMock()
        telegram = TelegramWebAppHandler(registry=registry)
        request = _request(
            "GET",
            "/t/x/forms/uid/telegram",
            match_info={"form_uid": "00000000-0000-0000-0000-000000000000"},
        )
        with pytest.raises(RuntimeError):
            await telegram.serve_webapp(request)
