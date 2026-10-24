"""POST /forms/translate — FEAT-650 TASK-4200."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot_formdesigner.api import a2ui_wire
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.api.render import _RENDERERS, register_renderer
from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.core.schema import FormSchema, RenderedForm
from parrot_formdesigner.renderers.base import AbstractFormRenderer
from parrot_formdesigner.services.registry import FormRegistry

SCHEMA = {
    "type": "object",
    "title": "T",
    "properties": {"a": {"type": "string", "title": "A"}},
    "required": ["a"],
}


class _FakeA2UIRenderer(AbstractFormRenderer):
    """Renderer exposing the translated form's route tenant in its output."""

    async def render(
        self,
        form: FormSchema,
        style: Any = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm:
        """Return a stable createSurface envelope for handler assertions."""
        return RenderedForm(
            content={"createSurface": {"surfaceId": "x", "tenant": form.tenant}},
            content_type="application/a2ui+json",
            warnings=[],
            metadata={"locale": locale},
        )


class _Response:
    """Async JSON facade over an aiohttp response."""

    def __init__(self, response: web.Response) -> None:
        """Store response fields used by the tests."""
        self._response = response
        self.status = response.status
        self.content_type = response.content_type

    async def json(self) -> dict[str, Any]:
        """Decode the response body."""
        return json.loads(self._response.body)


class _HandlerClient:
    """Drive the translate handler without opening a sandboxed socket."""

    def __init__(self, handler: FormAPIHandler) -> None:
        """Store the handler under test."""
        self._handler = handler

    async def post(
        self,
        target: str,
        *,
        json_body: Any = None,
        content_length: int | None = None,
        json_error: Exception | None = None,
    ) -> _Response:
        """Build the request contract consumed by ``translate_form``."""
        request = MagicMock(spec=web.Request)
        request.content_length = content_length
        request.query = {"with_meta": "true"} if "with_meta=true" in target else {}
        request.get = MagicMock(side_effect=lambda key, default=None: "navigator" if key == "tenant" else default)
        request.json = (
            AsyncMock(side_effect=json_error) if json_error is not None else AsyncMock(return_value=json_body)
        )
        return _Response(await self._handler.translate_form(request))


@pytest.fixture
async def registry() -> AsyncIterator[FormRegistry]:
    """Provide the real registry so persistence side effects are observable."""
    yield FormRegistry()


@pytest.fixture
async def client(registry: FormRegistry) -> AsyncIterator[_HandlerClient]:
    """Register the fake renderer and verify the endpoint route wiring."""
    snapshot = dict(_RENDERERS)
    _RENDERERS.clear()
    register_renderer("a2ui", _FakeA2UIRenderer())
    app = web.Application()
    setup_form_api(app, registry)
    routes = {route.resource.canonical: route.handler for route in app.router.routes()}
    route = routes["/api/v1/{tenant}/forms/translate"]
    assert getattr(route, "_requires_tenant", False)
    yield _HandlerClient(FormAPIHandler(registry))
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)


async def test_translate_stamps_route_tenant_and_never_persists(client: _HandlerClient, registry: FormRegistry) -> None:
    """The route tenant wins over body input and translation remains stateless."""
    before = len(await registry.list_forms(tenant="navigator"))
    response = await client.post(
        "/api/v1/navigator/forms/translate",
        json_body={"schema": SCHEMA, "tenant": "other"},
    )

    assert response.status == 200
    assert response.content_type == "application/a2ui+json"
    assert (await response.json())["createSurface"]["tenant"] == "navigator"
    assert len(await registry.list_forms(tenant="navigator")) == before


async def test_with_meta_wrapper(client: _HandlerClient) -> None:
    """Metadata mode returns the standard render-result wrapper."""
    response = await client.post(
        "/api/v1/navigator/forms/translate?with_meta=true",
        json_body={"schema": SCHEMA, "locale": "es"},
    )

    assert response.status == 200
    assert set(await response.json()) == {"content", "content_type", "warnings", "metadata"}
    assert (await response.json())["metadata"] == {"locale": "es"}


async def test_400_413_415(client: _HandlerClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Input shape, size, JSON parsing, and renderer availability are guarded."""
    missing = await client.post("/api/v1/navigator/forms/translate", json_body={})
    invalid = await client.post("/api/v1/navigator/forms/translate", json_body={"schema": "x"})
    invalid_json = await client.post(
        "/api/v1/navigator/forms/translate",
        json_error=json.JSONDecodeError("bad", "", 0),
    )
    monkeypatch.setattr(a2ui_wire, "A2UI_MAX_BODY_BYTES", 10)
    oversized = await client.post(
        "/api/v1/navigator/forms/translate",
        json_body={"schema": SCHEMA},
        content_length=11,
    )
    _RENDERERS.pop("a2ui", None)
    unavailable = await client.post("/api/v1/navigator/forms/translate", json_body={"schema": SCHEMA})

    assert missing.status == 400
    assert invalid.status == 400
    assert invalid_json.status == 400
    assert oversized.status == 413
    assert unavailable.status == 415


async def test_real_renderer_validates() -> None:
    """The production renderer emits a catalog-valid createSurface envelope."""
    pytest.importorskip("parrot.outputs.a2ui")
    from parrot.outputs.a2ui.catalog import validate_envelope
    from parrot.outputs.a2ui.catalog.base import ProducerOrigin
    from parrot.outputs.a2ui.serialization import deserialize
    from parrot_formdesigner.renderers import A2UIFormRenderer

    snapshot = dict(_RENDERERS)
    _RENDERERS.clear()
    register_renderer("a2ui", A2UIFormRenderer())
    try:
        handler = FormAPIHandler(FormRegistry())
        response = await _HandlerClient(handler).post(
            "/api/v1/navigator/forms/translate",
            json_body={"schema": SCHEMA},
        )
        message = deserialize(await response.json())
        assert message.create_surface is not None
        validate_envelope(message.create_surface, origin=ProducerOrigin.TOOL)
    finally:
        _RENDERERS.clear()
        _RENDERERS.update(snapshot)
