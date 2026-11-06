"""Request body-size caps for the A2UI form endpoints.

FEAT-822 / ``issue:bf978b6bae8a`` (FEAT-650 review items I2 and S3).

Two layers, because the bug had two halves:

1. **Mechanism** — exercised against a *real* ``aiohttp`` server, because the
   half of the bug that mocks cannot see is a chunked body, where
   ``request.content_length`` is ``None`` and every ``Content-Length`` guard
   silently passes. These tests also pin the private attribute
   :func:`a2ui_wire.apply_body_cap` assigns: if a future aiohttp stops reading
   ``_client_max_size`` inside ``BaseRequest.read()``, they go red here rather
   than failing open in production.
2. **Handler shape** — each capped route returns the 413 body its wire
   expects, using this package's mocked-request convention.
"""

from __future__ import annotations

import importlib.util
import json as _json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot_formdesigner.api import a2ui_wire
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import FormValidator, ValidationResult

_HAS_A2UI = importlib.util.find_spec("parrot.outputs.a2ui") is not None
a2ui_only = pytest.mark.skipif(not _HAS_A2UI, reason="requires the optional A2UI extra")

_TEST_TENANT = "test-tenant"
_FORM_UID = "11111111-1111-1111-1111-111111111111"
_CAP = 1024


# ---------------------------------------------------------------------------
# Layer 1 — the mechanism, against a real aiohttp server
# ---------------------------------------------------------------------------


def _cap_app(*, cap: int = _CAP, surface_id: str | None = None, client_max_size: int | None = None) -> web.Application:
    """An app whose one route uses exactly the handler recipe FEAT-822 ships."""
    seen: dict[str, object] = {}

    async def handler(request: web.Request) -> web.Response:
        seen["content_length"] = request.content_length
        limit = a2ui_wire.apply_body_cap(request, limit=cap)
        seen["limit"] = limit
        try:
            body = await request.json()
        except web.HTTPRequestEntityTooLarge:
            return a2ui_wire.oversized_response(request, limit=limit, surface_id=surface_id)
        return web.json_response({"ok": True, "len": len(body["pad"])})

    kwargs = {} if client_max_size is None else {"client_max_size": client_max_size}
    app = web.Application(**kwargs)
    app["seen"] = seen
    app.router.add_post("/", handler)
    return app


async def _chunked(total: int, piece: int = 128):
    """An async body iterable — makes aiohttp use ``Transfer-Encoding: chunked``."""
    sent = 0
    while sent < total:
        size = min(piece, total - sent)
        yield b"x" * size
        sent += size


async def test_under_cap_body_is_read_normally(aiohttp_client):
    """A body under the cap reaches the handler untouched."""
    app = _cap_app()
    client = await aiohttp_client(app)

    resp = await client.post("/", json={"pad": "a" * 10})

    assert resp.status == 200
    assert (await resp.json())["len"] == 10


async def test_sized_body_over_cap_is_rejected(aiohttp_client):
    """A declared-length body over the cap gets the plain-JSON 413."""
    app = _cap_app()
    client = await aiohttp_client(app)

    resp = await client.post("/", json={"pad": "a" * (_CAP * 2)})

    assert resp.status == 413
    assert await resp.json() == {"error": "body too large", "max_bytes": _CAP}


async def test_chunked_body_over_cap_is_rejected(aiohttp_client):
    """The bypass this feature closes: no Content-Length, still 413.

    Asserts the server really saw ``content_length is None`` — otherwise the
    test would pass for the wrong reason and prove nothing about the bug.
    """
    app = _cap_app()
    client = await aiohttp_client(app)

    resp = await client.post(
        "/",
        data=_chunked(_CAP * 4),
        headers={"Content-Type": "application/json"},
    )

    assert resp.status == 413
    assert app["seen"]["content_length"] is None


async def test_chunked_body_under_cap_still_succeeds(aiohttp_client):
    """Chunked framing on its own is not an error — only the byte count is."""
    app = _cap_app()
    client = await aiohttp_client(app)
    payload = _json.dumps({"pad": "a" * 32}).encode()

    async def _stream():
        yield payload

    resp = await client.post("/", data=_stream(), headers={"Content-Type": "application/json"})

    assert resp.status == 200
    assert app["seen"]["content_length"] is None


async def test_cap_never_widens_a_stricter_host_limit(aiohttp_client):
    """A host app with a smaller ``client_max_size`` keeps it."""
    app = _cap_app(cap=_CAP * 100, client_max_size=256)
    client = await aiohttp_client(app)

    resp = await client.post("/", json={"pad": "a" * 1024})

    assert resp.status == 413
    assert (await resp.json())["max_bytes"] == 256
    assert app["seen"]["limit"] == 256


@a2ui_only
async def test_a2ui_caller_over_cap_gets_an_envelope(aiohttp_client):
    """An ``application/a2ui+json`` caller keeps the A2UI error shape on 413."""
    app = _cap_app(surface_id="form-import")
    client = await aiohttp_client(app)

    resp = await client.post(
        "/",
        data=b"x" * (_CAP * 2),
        headers={"Content-Type": "application/a2ui+json"},
    )

    assert resp.status == 413
    assert "form-import" in await resp.text()


async def test_non_a2ui_caller_over_cap_gets_plain_json(aiohttp_client):
    """Without an A2UI content type the plain shape is used, envelope or not."""
    app = _cap_app(surface_id="form-import")
    client = await aiohttp_client(app)

    resp = await client.post("/", data=b"x" * (_CAP * 2), headers={"Content-Type": "application/json"})

    assert resp.status == 413
    assert await resp.json() == {"error": "body too large", "max_bytes": _CAP}


def test_apply_body_cap_defaults_to_the_module_attribute(monkeypatch):
    """``limit=None`` resolves at call time, so the attribute stays patchable."""
    monkeypatch.setattr(a2ui_wire, "A2UI_MAX_BODY_BYTES", 4096)
    request = MagicMock(spec=web.Request)

    assert a2ui_wire.apply_body_cap(request) == 4096
    assert request._client_max_size == 4096


# ---------------------------------------------------------------------------
# Layer 1b — the iterative schema-depth check (S3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "max_depth", "expected"),
    [
        ({"a": 1}, 1, False),
        ({"a": {"b": 1}}, 1, True),
        ({"a": {"b": 1}}, 2, False),
        ([[1]], 1, True),
        ([[1]], 2, False),
        ("scalar", 1, False),
        ({}, 1, False),
    ],
)
def test_exceeds_json_depth(value, max_depth, expected):
    assert a2ui_wire.exceeds_json_depth(value, max_depth=max_depth) is expected


def test_exceeds_json_depth_survives_a_hostile_schema():
    """A 10 000-deep payload is rejected without touching the recursion limit."""
    deep: dict = {}
    node = deep
    for _ in range(10_000):
        node["properties"] = {}
        node = node["properties"]

    assert a2ui_wire.exceeds_json_depth(deep, max_depth=32) is True


# ---------------------------------------------------------------------------
# Layer 2 — the handler 413 shapes
# ---------------------------------------------------------------------------


def _make_form() -> FormSchema:
    return FormSchema(
        form_uid=_FORM_UID,
        form_id="test-form",
        title="Test Form",
        tenant=_TEST_TENANT,
        is_public=True,
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True)],
            )
        ],
    )


def _oversized_request(*, content_type: str = "application/json") -> MagicMock:
    """A request whose body read blows the cap, exactly as aiohttp signals it."""
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": _FORM_UID}
    req.query = MagicMock()
    req.query.get = MagicMock(return_value="")
    req.__contains__ = lambda self, key: False
    req.json = AsyncMock(side_effect=web.HTTPRequestEntityTooLarge(_CAP, actual_size=_CAP * 2))
    req.get = MagicMock(side_effect=lambda key, default=None: _TEST_TENANT if key == "tenant" else default)
    req.session = {"session": {"programs": [_TEST_TENANT]}}
    req.content_type = content_type
    req.content_length = None  # chunked: the guard this replaces saw nothing
    return req


def _make_handler(form: FormSchema | None = None) -> FormAPIHandler:
    registry = MagicMock()
    registry.get = AsyncMock(return_value=form)
    handler = FormAPIHandler(registry=registry)
    handler.validator = MagicMock(spec=FormValidator)
    handler.validator.validate = AsyncMock(
        return_value=ValidationResult(is_valid=True, errors={}, sanitized_data={}, extra_data={})
    )
    handler._rbac_shadow_gate = AsyncMock(return_value=None)
    return handler


async def _body(response: web.Response) -> dict:
    return _json.loads(response.body)


@pytest.mark.parametrize("route", ["export_forms", "translate_form", "create_form"])
async def test_plain_routes_return_413(route, monkeypatch):
    """export/translate/create all reject an over-cap body with the plain shape."""
    monkeypatch.setattr(a2ui_wire, "A2UI_MAX_BODY_BYTES", _CAP)
    handler = _make_handler()

    response = await getattr(handler, route)(_oversized_request())

    assert response.status == 413
    assert await _body(response) == {"error": "body too large", "max_bytes": _CAP}


@a2ui_only
async def test_create_form_keeps_the_a2ui_envelope(monkeypatch):
    """An A2UI surface import over the cap still answers on the A2UI wire."""
    monkeypatch.setattr(a2ui_wire, "A2UI_MAX_BODY_BYTES", _CAP)
    handler = _make_handler()

    response = await handler.create_form(_oversized_request(content_type="application/a2ui+json"))

    assert response.status == 413
    assert "form-import" in response.body.decode()


@pytest.mark.parametrize("route", ["submit_data", "validate"])
async def test_form_routes_return_plain_413_for_a_plain_caller(route, monkeypatch):
    monkeypatch.setattr(a2ui_wire, "A2UI_MAX_BODY_BYTES", _CAP)
    handler = _make_handler(_make_form())

    response = await getattr(handler, route)(_oversized_request())

    assert response.status == 413
    assert await _body(response) == {"error": "body too large", "max_bytes": _CAP}


@a2ui_only
@pytest.mark.parametrize("route", ["submit_data", "validate"])
async def test_form_routes_return_an_envelope_for_an_a2ui_caller(route, monkeypatch):
    """The A2UI 413 names the form's own surface, chosen from headers alone."""
    monkeypatch.setattr(a2ui_wire, "A2UI_MAX_BODY_BYTES", _CAP)
    handler = _make_handler(_make_form())

    response = await getattr(handler, route)(_oversized_request(content_type="application/a2ui+json"))

    assert response.status == 413
    assert f"form-{_FORM_UID}" in response.body.decode()


async def test_no_handler_trusts_content_length_any_more():
    """AC4 — not one ``content_length``-versus-cap comparison is left."""
    from pathlib import Path

    import parrot_formdesigner.api.handlers as handlers_module

    source = Path(handlers_module.__file__).read_text()

    assert "content_length" not in source
