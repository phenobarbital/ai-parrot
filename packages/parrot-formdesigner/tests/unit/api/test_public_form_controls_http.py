"""FEAT-730 — HTTP surface: 409 bodies, /availability, flag plumbing."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot_formdesigner.api import routes as routes_module
from parrot_formdesigner.api.errors import TenantForbiddenError
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.submissions import (
    DuplicateResponse,
    FormSubmissionStorage,
    ResponseLimitReached,
)

_TENANT = "test-tenant"
_FORM_UID = "11111111-1111-1111-1111-111111111111"


def _form(public_access=None, *, is_public: bool = True) -> FormSchema:
    return FormSchema(
        form_id="pub-form",
        title="Pub",
        tenant=_TENANT,
        is_public=is_public,
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="email", field_type=FieldType.EMAIL, label="Email")],
            )
        ],
        public_access=public_access,
    )


def _request(body: dict | None = None, *, member: bool = True) -> MagicMock:
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": _FORM_UID}
    req.query = MagicMock()
    req.query.get = MagicMock(return_value="")
    req.__contains__ = lambda self, key: False
    req.json = AsyncMock(return_value=body or {})
    req.get = MagicMock(
        side_effect=lambda key, default=None: (
            _TENANT if key == "tenant" else ({"id": "user-1"} if key == "session" else default)
        )
    )
    req.session = {"session": {"programs": [_TENANT] if member else []}}
    return req


def _json(resp) -> dict:
    return json.loads(resp.body)


def _handler(form: FormSchema, *, tenant_scoped: bool = False):
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)
    storage = MagicMock(spec=FormSubmissionStorage)
    storage.store = AsyncMock(return_value="sub-1")
    storage.store_guarded = AsyncMock(return_value="sub-1")
    storage.count_responses = AsyncMock(return_value=0)
    handler = FormAPIHandler(
        registry=registry, submission_storage=storage, tenant_scoped_submissions=tenant_scoped
    )
    return handler, storage


async def test_submit_data_409_body():
    form = _form({"max_responses": 1, "unique_key_field": "email"})
    handler, storage = _handler(form)

    storage.store_guarded.side_effect = ResponseLimitReached()
    resp = await handler.submit_data(_request({"email": "a@x.com"}))
    assert resp.status == 409
    body = _json(resp)
    assert body["reason"] == "response_limit_reached" and "field_id" not in body and body["error"]

    storage.store_guarded.side_effect = DuplicateResponse("email")
    resp = await handler.submit_data(_request({"email": "a@x.com"}))
    assert resp.status == 409
    assert _json(resp)["reason"] == "duplicate_response"
    assert _json(resp)["field_id"] == "email"

    closed = _form({"closes_at": datetime.now(timezone.utc) - timedelta(minutes=1)})
    handler, storage = _handler(closed)
    resp = await handler.submit_data(_request({"email": "a@x.com"}))
    assert resp.status == 409
    assert _json(resp)["reason"] == "form_closed" and "field_id" not in _json(resp)
    storage.store.assert_not_called()
    storage.store_guarded.assert_not_called()


async def test_availability_states():
    # no block
    handler, _ = _handler(_form())
    resp = await handler.get_availability(_request())
    assert resp.status == 200
    assert _json(resp) == {"accepting": True, "reason": None, "completion": None}

    # open with a completion action
    completion = {"mode": "message", "message": "Thanks"}
    handler, _ = _handler(_form({"completion": completion}))
    body = _json(await handler.get_availability(_request()))
    assert body["accepting"] is True and body["completion"]["message"] == "Thanks"

    # closed (manual) and closed (date)
    for pa in ({"accepting_responses": False}, {"closes_at": datetime.now(timezone.utc) - timedelta(seconds=5)}):
        handler, _ = _handler(_form(pa))
        body = _json(await handler.get_availability(_request()))
        assert body["accepting"] is False and body["reason"] == "form_closed"

    # limit reached / not yet
    handler, storage = _handler(_form({"max_responses": 3}))
    storage.count_responses.return_value = 2
    assert _json(await handler.get_availability(_request()))["accepting"] is True
    storage.count_responses.return_value = 3
    body = _json(await handler.get_availability(_request()))
    assert body["accepting"] is False and body["reason"] == "response_limit_reached"
    assert storage.count_responses.await_args.kwargs == {"tenant": None}  # flag off -> default table

    handler, storage = _handler(_form({"max_responses": 3}), tenant_scoped=True)
    storage.count_responses.return_value = 3
    await handler.get_availability(_request())
    assert storage.count_responses.await_args.kwargs == {"tenant": _TENANT}


async def test_availability_private_form_like_get_form():
    handler, _ = _handler(_form(is_public=False))
    with pytest.raises(TenantForbiddenError):
        await handler.get_availability(_request(member=False))
    with pytest.raises(TenantForbiddenError):
        await handler.get_form(_request(member=False))
    resp = await handler.get_availability(_request(member=True))
    assert resp.status == 200


async def test_setup_form_api_passes_tenant_flag():
    app = web.Application()
    setup_form_api(app, FormRegistry(), tenant_scoped_submissions=True)
    assert app["submission_pipeline"].tenant_scoped_submissions is True
    app = web.Application()
    setup_form_api(app, FormRegistry())
    assert app["submission_pipeline"].tenant_scoped_submissions is False


async def test_file_upload_route_is_public_mode(monkeypatch):
    modes: dict[str, str] = {}
    real = routes_module._wrap_auth

    def _spy(handler, *, tenant="required"):
        modes[getattr(handler, "__name__", repr(handler))] = tenant
        return real(handler, tenant=tenant)

    monkeypatch.setattr(routes_module, "_wrap_auth", _spy)
    app = web.Application()
    setup_form_api(app, FormRegistry())
    assert modes["handle_file_upload"] == "public"
    assert modes["get_availability"] == "public"
    paths = {r.resource.canonical for r in app.router.routes()}
    assert "/api/v1/{tenant}/forms/{form_uid}/availability" in paths
