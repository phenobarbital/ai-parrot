"""GET /forms dialect enrichment — FEAT-650 TASK-4195."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, NoReturn
from urllib.parse import parse_qsl, urlsplit
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot_formdesigner.api import handlers as handlers_module
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.api.render import _RENDERERS, register_renderer
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers import A2UIFormRenderer
from parrot_formdesigner.services.registry import FormRegistry, FormStorage


def _form(form_id: str, *, dialect: str = "json_schema") -> FormSchema:
    """Build a minimal renderable form for the list endpoint."""
    return FormSchema(
        form_id=form_id,
        title={"en": form_id.upper()},
        tenant="navigator",
        dialect=dialect,
        sections=[
            FormSection(
                section_id="main",
                fields=[FormField(field_id="name", field_type=FieldType.TEXT, label={"en": "Name"})],
            )
        ],
    )


class _Response:
    """Small async JSON facade over an aiohttp response."""

    def __init__(self, response: web.Response) -> None:
        """Store the handler response."""
        self._response = response
        self.status = response.status

    async def json(self) -> dict[str, Any]:
        """Decode the response body like aiohttp's test client."""
        return json.loads(self._response.body)


class _HandlerClient:
    """Drive ``list_forms`` directly without opening a sandboxed socket."""

    def __init__(self, handler: FormAPIHandler) -> None:
        """Store the handler under test."""
        self._handler = handler

    async def get(self, target: str, *, session: dict | None = None) -> _Response:
        """Build the request contract consumed by ``list_forms``."""
        parsed = urlsplit(target)
        request = MagicMock(spec=web.Request)
        request.query = dict(parse_qsl(parsed.query))
        request.app = {"_form_prefix": "/api/v1"}
        request.headers = {}
        request.get = MagicMock(side_effect=lambda key, default=None: "navigator" if key == "tenant" else default)
        request.__contains__ = MagicMock(return_value=False)
        if session is not None:
            request.session = {"session": session}
        return _Response(await self._handler.list_forms(request))


@pytest.fixture
async def client() -> AsyncIterator[_HandlerClient]:
    """Build a handler with two cached forms and one storage-only row."""
    pytest.importorskip("parrot.outputs.a2ui")
    first = _form("f1")
    second = _form("f2", dialect="a2ui")
    stored = _form("f3")

    storage = MagicMock(spec=FormStorage)
    storage.list_forms = AsyncMock(
        return_value=[
            {
                "form_uid": stored.form_uid,
                "form_id": stored.form_id,
                "title": stored.title,
                "description": stored.description,
                "version": stored.version,
                "created_at": None,
            }
        ]
    )
    storage.load = AsyncMock(return_value=stored)
    registry = FormRegistry(storage=storage)
    await registry.register(first, tenant="navigator")
    await registry.register(second, tenant="navigator")
    handler = FormAPIHandler(registry)

    snapshot = dict(_RENDERERS)
    register_renderer("a2ui", A2UIFormRenderer())
    yield _HandlerClient(handler)
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)


async def test_descriptor_carries_dialect_for_memory_entries(client: _HandlerClient) -> None:
    """Every descriptor — memory, a2ui-dialect, and storage-only — carries dialect."""
    response = await client.get("/api/v1/navigator/forms")
    forms = {form["form_id"]: form for form in (await response.json())["forms"]}
    assert forms["f1"]["dialect"] == "json_schema"
    assert forms["f2"]["dialect"] == "a2ui"
    assert forms["f3"]["dialect"] == "json_schema"
    assert "surface_url" not in forms["f1"]


async def test_manifest_does_not_render(client: _HandlerClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A2UI list manifests add URLs without paying the rendering cost."""
    calls: list[int] = []
    monkeypatch.setattr(handlers_module, "render_a2ui_schema", lambda *args, **kwargs: calls.append(1))

    response = await client.get("/api/v1/navigator/forms?dialect=a2ui")
    body = await response.json()

    assert response.status == 200
    assert all(form["surface_url"].endswith("/schema?dialect=a2ui") for form in body["forms"])
    assert calls == []


async def test_include_surface_inlines_envelopes(client: _HandlerClient) -> None:
    """An authorized tenant member gets every descriptor's inline envelope + warnings."""
    response = await client.get(
        "/api/v1/navigator/forms?dialect=a2ui&include=surface",
        session={"programs": ["navigator"]},
    )
    body = await response.json()

    assert response.status == 200
    assert all("createSurface" in form["surface"] for form in body["forms"])
    assert all(isinstance(form["warnings"], list) for form in body["forms"])


async def test_include_surface_filters_unauthorized_forms(client: _HandlerClient) -> None:
    """Without membership, descriptors keep surface_url but drop the inline body."""
    response = await client.get("/api/v1/navigator/forms?dialect=a2ui&include=surface")
    body = await response.json()

    assert response.status == 200
    assert all(form["surface_url"].endswith("/schema?dialect=a2ui") for form in body["forms"])
    assert all("surface" not in form for form in body["forms"])
    assert all("warnings" not in form for form in body["forms"])


async def test_include_surface_honors_on_schema_loaded(
    client: _HandlerClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """onSchemaLoaded overrides reach the inlined descriptor as a multi-envelope message list."""

    async def resolve(*_args, **_kwargs):
        from parrot_formdesigner.core.events import EventResolution

        return EventResolution(schema_overrides={"title": "Overridden"})

    monkeypatch.setattr(handlers_module, "dispatch", resolve)
    response = await client.get(
        "/api/v1/navigator/forms?dialect=a2ui&include=surface",
        session={"programs": ["navigator"]},
    )
    body = await response.json()

    assert response.status == 200
    for form in body["forms"]:
        assert "messages" in form["surface"]
        assert any("updateComponents" in m for m in form["surface"]["messages"])


async def test_cap_returns_400(client: _HandlerClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The inline cap rejects oversized lists before rendering."""
    monkeypatch.setattr(handlers_module, "A2UI_LIST_MAX", 1)
    response = await client.get("/api/v1/navigator/forms?dialect=a2ui&include=surface")
    assert response.status == 400
    assert (await response.json())["max"] == 1


async def test_unknown_dialect_400_and_missing_renderer_415(client: _HandlerClient) -> None:
    """Invalid dialects and unavailable optional renderers remain distinct."""
    unknown = await client.get("/api/v1/navigator/forms?dialect=xml")
    assert unknown.status == 400
    assert "supported" in await unknown.json()

    _RENDERERS.pop("a2ui", None)
    unavailable = await client.get("/api/v1/navigator/forms?dialect=a2ui")
    assert unavailable.status == 415
    assert "supported" in await unavailable.json()


async def test_inline_render_failure_is_isolated(client: _HandlerClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """One rendering exception produces a generic warning, never the raw exception text."""

    async def fail_render(_form: FormSchema, **_kwargs: Any) -> NoReturn:
        raise RuntimeError("broken surface")

    monkeypatch.setattr(handlers_module, "render_a2ui_schema", fail_render)
    response = await client.get(
        "/api/v1/navigator/forms?dialect=a2ui&include=surface",
        session={"programs": ["navigator"]},
    )
    body = await response.json()

    assert response.status == 200
    assert all(form["surface"] is None for form in body["forms"])
    assert all(form["warnings"] == ["render_failed"] for form in body["forms"])
