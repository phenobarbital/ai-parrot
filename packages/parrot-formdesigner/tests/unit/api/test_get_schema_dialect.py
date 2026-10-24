"""GET /forms/{uid}/schema dialect negotiation — FEAT-650 TASK-4194."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from parrot_formdesigner.api import handlers as handlers_module
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.api.render import _RENDERERS, register_renderer
from parrot_formdesigner.core.events import EventResolution, FormEventAbort
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.tenant_errors import TenantForbiddenError
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers import A2UIFormRenderer
from parrot_formdesigner.services.registry import FormRegistry

GOLDEN = Path(__file__).parent / "fixtures" / "golden_schema_legacy.json"


def _form(*, dialect: str = "json_schema", is_public: bool = True) -> FormSchema:
    """Build the stable two-section form captured in the legacy golden."""
    return FormSchema(
        form_id="golden-form",
        title={"en": "Golden Form"},
        description={"en": "Golden description"},
        tenant="navigator",
        dialect=dialect,
        is_public=is_public,
        sections=[
            FormSection(
                section_id="identity",
                title={"en": "Identity"},
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label={"en": "Name"}, required=True),
                    FormField(
                        field_id="choice",
                        field_type=FieldType.SELECT,
                        label={"en": "Choice"},
                        options=[{"value": "one", "label": "One"}, {"value": "two", "label": "Two"}],
                    ),
                ],
            ),
            FormSection(
                section_id="details",
                fields=[
                    FormField(field_id="quantity", field_type=FieldType.NUMBER, label={"en": "Quantity"}),
                    FormField(field_id="confirmed", field_type=FieldType.BOOLEAN, label={"en": "Confirmed"}),
                ],
            ),
        ],
    )


async def _handler(form: FormSchema) -> FormAPIHandler:
    """Register ``form`` in a real registry and return its API handler."""
    registry = FormRegistry()
    await registry.register(form)
    return FormAPIHandler(registry)


def _request(form: FormSchema, *, query: dict[str, str] | None = None, session: dict | None = None) -> MagicMock:
    """Build the request contract consumed by ``get_schema`` without a socket."""
    request = MagicMock(spec=web.Request)
    request.match_info = {"form_uid": str(form.form_uid)}
    request.query = query or {}
    request.headers = {}
    request.get = MagicMock(side_effect=lambda key, default=None: "navigator" if key == "tenant" else default)
    request.__contains__ = MagicMock(return_value=False)
    if session is not None:
        request.session = {"session": session}
    return request


async def test_legacy_body_is_golden() -> None:
    """Keep the legacy JSON-schema response byte-for-byte structured-identical."""
    form = _form()
    response = await (await _handler(form)).get_schema(_request(form))
    assert response.status == 200
    assert json.loads(response.body) == json.loads(GOLDEN.read_text())


@pytest.fixture(autouse=True)
def _a2ui_renderer() -> None:
    """Provide the real optional renderer and restore the global registry."""
    pytest.importorskip("parrot.outputs.a2ui")
    snapshot = dict(_RENDERERS)
    register_renderer("a2ui", A2UIFormRenderer())
    yield
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)


async def test_forced_json_schema_on_a2ui_form_is_golden() -> None:
    """An explicit JSON-schema request overrides a stored A2UI preference."""
    form = _form(dialect="a2ui")
    response = await (await _handler(form)).get_schema(_request(form, query={"dialect": "json_schema"}))
    assert response.status == 200
    assert json.loads(response.body) == json.loads(GOLDEN.read_text())


async def test_a2ui_single_envelope() -> None:
    """A requested A2UI schema is framed as one createSurface message."""
    form = _form()
    response = await (await _handler(form)).get_schema(_request(form, query={"dialect": "a2ui"}))
    assert response.status == 200
    assert response.content_type == "application/a2ui+json"
    assert json.loads(response.body)["createSurface"]["surfaceId"] == f"form-{form.form_uid}"


async def test_a2ui_with_overrides_is_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lifecycle overrides are translated into a second A2UI envelope."""

    async def resolve(*_args, **_kwargs) -> EventResolution:
        return EventResolution(schema_overrides={"title": "X"})

    monkeypatch.setattr(handlers_module, "dispatch", resolve)
    form = _form()
    response = await (await _handler(form)).get_schema(_request(form, query={"dialect": "a2ui"}))
    body = json.loads(response.body)
    assert response.status == 200
    assert response.content_type == "application/json"
    assert "createSurface" in body["messages"][0]
    assert "updateComponents" in body["messages"][1]


async def test_unknown_dialect_400_and_missing_extra_415() -> None:
    """Negotiation failures retain their documented JSON payloads."""
    form = _form()
    handler = await _handler(form)
    unknown = await handler.get_schema(_request(form, query={"dialect": "xml"}))
    assert unknown.status == 400
    assert "supported" in json.loads(unknown.body)
    _RENDERERS.pop("a2ui", None)
    unavailable = await handler.get_schema(_request(form, query={"dialect": "a2ui"}))
    assert unavailable.status == 415
    assert "supported" in json.loads(unavailable.body)


async def test_private_form_requires_membership_under_a2ui() -> None:
    """Dialect negotiation never bypasses the pre-negotiation membership gate."""
    form = _form(is_public=False)
    with pytest.raises(TenantForbiddenError):
        await (await _handler(form)).get_schema(_request(form, query={"dialect": "a2ui"}))


async def test_onschemaloaded_abort_is_json_under_both_dialects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lifecycle aborts remain JSON errors before dialect response framing."""

    async def abort(*_args, **_kwargs) -> EventResolution:
        raise FormEventAbort("gated", user_message="Denied", status_code=403)

    monkeypatch.setattr(handlers_module, "dispatch", abort)
    form = _form()
    handler = await _handler(form)
    for query in ({}, {"dialect": "a2ui"}):
        response = await handler.get_schema(_request(form, query=query))
        assert response.status == 403
        assert response.content_type == "application/json"
        assert json.loads(response.body) == {"error": "Denied", "reason": "gated"}
