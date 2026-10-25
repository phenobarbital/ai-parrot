"""POST /forms/export — FEAT-650 TASK-4197."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot_formdesigner.api import handlers as handlers_module
from parrot_formdesigner.api import routes as api_routes
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.api.render import _RENDERERS, register_renderer
from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, RenderedForm
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.base import AbstractFormRenderer
from parrot_formdesigner.services.registry import FormRegistry


class _FakeA2UIRenderer(AbstractFormRenderer):
    """Minimal optional renderer used to exercise the export endpoint."""

    async def render(
        self,
        form: FormSchema,
        style: Any = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm:
        """Return a stable A2UI-shaped envelope for one form."""
        return RenderedForm(
            content={"createSurface": {"surfaceId": f"form-{form.form_uid}", "locale": locale}},
            content_type="application/a2ui+json",
            metadata={},
            warnings=[],
        )


class _FakeStreamResponse:
    """In-memory stream replacement for a runner that prohibits sockets."""

    def __init__(self, *, status: int, headers: dict[str, str]) -> None:
        """Store response metadata and collect response bytes."""
        self.status = status
        self.headers = headers
        self.content_type = headers["Content-Type"]
        self.prepared = False
        self.eof = False
        self.body = bytearray()

    async def prepare(self, _request: web.Request) -> None:
        """Mark the stream prepared."""
        self.prepared = True

    async def write(self, data: bytes) -> None:
        """Append an NDJSON row."""
        self.body.extend(data)

    async def write_eof(self) -> None:
        """Mark the stream complete."""
        self.eof = True

    async def text(self) -> str:
        """Return response bytes decoded as UTF-8."""
        return self.body.decode("utf-8")


def _passthrough_decorator_factory(*_args: Any, **_kwargs: Any):
    """Return a decorator that leaves the real tenant wrapper intact."""

    def _decorator(handler: Any) -> Any:
        return handler

    return _decorator


def _form(form_id: str, *, tenant: str = "navigator", published: str | None = None) -> FormSchema:
    """Build a minimal form for the supplied tenant."""
    return FormSchema(
        form_id=form_id,
        title={"en": form_id},
        tenant=tenant,
        published_version=published,
        sections=[
            FormSection(
                section_id="main",
                fields=[FormField(field_id="name", field_type=FieldType.TEXT, label={"en": "Name"})],
            )
        ],
    )


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[FormAPIHandler, list[FormSchema]]]:
    """Build a handler and inspect setup_form_api wiring without sockets."""
    monkeypatch.setattr(api_routes, "is_authenticated", _passthrough_decorator_factory)
    monkeypatch.setattr(api_routes, "user_session", _passthrough_decorator_factory)
    snapshot = dict(_RENDERERS)
    _RENDERERS.clear()
    register_renderer("a2ui", _FakeA2UIRenderer())

    registry = FormRegistry()
    forms = [
        _form("draft"),
        _form("published", published="1.0"),
        _form("third"),
        _form("foreign", tenant="other"),
    ]
    for form in forms:
        await registry.register(form, tenant=form.tenant)
    app = web.Application()
    setup_form_api(app, registry)
    paths = {route.resource.canonical for route in app.router.routes()}
    assert "/api/v1/{tenant}/forms/export" in paths
    monkeypatch.setattr(handlers_module.web, "StreamResponse", _FakeStreamResponse)
    yield FormAPIHandler(registry), forms
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)


async def _post(handler: FormAPIHandler, body: Any) -> Any:
    """Call the real handler with precisely the request fields it consumes."""
    request = MagicMock(spec=web.Request)
    request.json = AsyncMock(return_value=body)
    request.get = MagicMock(side_effect=lambda key, default=None: "navigator" if key == "tenant" else default)
    return await handler.export_forms(request)


async def _lines(response: _FakeStreamResponse) -> list[dict[str, Any]]:
    """Decode NDJSON rows from an in-memory export response."""
    return [json.loads(line) for line in (await response.text()).splitlines() if line]


async def test_ndjson_framing_and_tenant_isolation(client: tuple[FormAPIHandler, list[FormSchema]]) -> None:
    """The URL tenant controls a framed stream even when the body says otherwise."""
    handler, _forms = client
    response = await _post(handler, {"dialect": "a2ui", "tenant": "other"})

    rows = await _lines(response)

    assert response.status == 200
    assert response.content_type == "application/x-ndjson"
    assert response.prepared and response.eof
    assert len(rows) == 3
    assert all(row["dialect"] == "a2ui" and row["envelope"] for row in rows)
    assert {row["form_id"] for row in rows} == {"draft", "published", "third"}


async def test_published_only_and_form_uids_filter(client: tuple[FormAPIHandler, list[FormSchema]]) -> None:
    """Boolean and UUID filters narrow the export before streaming."""
    handler, forms = client
    published_response = await _post(handler, {"published_only": True})
    selected_response = await _post(handler, {"form_uids": [str(forms[0].form_uid)]})
    malformed_response = await _post(handler, {"form_uids": ["not-a-uuid"]})
    invalid_boolean = await _post(handler, {"published_only": "true"})

    assert [row["form_id"] for row in await _lines(published_response)] == ["published"]
    assert [row["form_id"] for row in await _lines(selected_response)] == ["draft"]
    assert malformed_response.status == 400
    assert invalid_boolean.status == 400


async def test_json_schema_dialect(client: tuple[FormAPIHandler, list[FormSchema]]) -> None:
    """The legacy export dialect produces JSON Schema envelopes."""
    handler, _forms = client
    rows = await _lines(await _post(handler, {"dialect": "json_schema"}))

    assert rows
    assert all(row["dialect"] == "json_schema" and row["envelope"]["type"] == "object" for row in rows)


async def test_bad_body_unknown_dialect_and_missing_renderer(
    client: tuple[FormAPIHandler, list[FormSchema]],
) -> None:
    """Invalid input and unavailable optional renderers fail before the stream starts."""
    handler, _forms = client
    non_object = await _post(handler, ["not", "an", "object"])
    unknown = await _post(handler, {"dialect": "xml"})
    _RENDERERS.pop("a2ui", None)
    unavailable = await _post(handler, {"dialect": "a2ui"})

    assert non_object.status == 400
    assert unknown.status == 400
    assert "supported" in json.loads(unknown.body)
    assert unavailable.status == 415
    assert "supported" in json.loads(unavailable.body)
