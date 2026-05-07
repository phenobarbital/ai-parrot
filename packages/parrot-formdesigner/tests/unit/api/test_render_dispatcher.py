"""Unit tests for the render dispatcher in ``parrot_formdesigner.api.render``."""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp import web

from parrot_formdesigner.api.render import (
    _RENDERERS,
    _seed_default_renderers,
    get_renderer,
    handle_render,
    register_renderer,
    supported_formats,
)
from parrot_formdesigner.core.schema import (
    FormField,
    FormSchema,
    FormSection,
    RenderedForm,
)
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.base import AbstractFormRenderer
from parrot_formdesigner.services.registry import FormRegistry


@pytest.fixture(autouse=True)
def _reset_renderers():
    snapshot = dict(_RENDERERS)
    _RENDERERS.clear()
    yield
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)


@pytest.fixture
def sample_form() -> FormSchema:
    return FormSchema(
        form_id="test-form",
        title={"en": "Test"},
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label={"en": "Name"},
                    ),
                ],
            )
        ],
    )


def test_default_seed_includes_html_and_adaptive():
    _seed_default_renderers()
    assert "html" in _RENDERERS
    assert "adaptive" in _RENDERERS


def test_register_renderer_overwrites():
    class _R(AbstractFormRenderer):
        async def render(
            self,
            form: FormSchema,
            style=None,
            *,
            locale: str = "en",
            prefilled=None,
            errors=None,
        ) -> RenderedForm:
            return RenderedForm(content="<x/>", content_type="application/xml")

    r = _R()
    register_renderer("xml", r)
    assert get_renderer("xml") is r
    register_renderer("xml", r)  # idempotent
    assert get_renderer("xml") is r


def test_supported_formats_sorted():
    register_renderer("zeta", _make_dummy_renderer())
    register_renderer("alpha", _make_dummy_renderer())
    assert supported_formats() == sorted(supported_formats())


def _make_dummy_renderer() -> AbstractFormRenderer:
    class _Dummy(AbstractFormRenderer):
        async def render(
            self,
            form: FormSchema,
            style=None,
            *,
            locale: str = "en",
            prefilled=None,
            errors=None,
        ) -> RenderedForm:
            return RenderedForm(content="<x/>", content_type="application/xml")

    return _Dummy()


async def test_dispatcher_returns_415_for_unknown_format(aiohttp_client, sample_form):
    register_renderer("html", _make_dummy_renderer())
    registry = FormRegistry()
    await registry.register(sample_form)

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get(
        "/api/v1/forms/{form_id}/render/{format}", handle_render
    )

    client = await aiohttp_client(app)
    resp = await client.get(f"/api/v1/forms/{sample_form.form_id}/render/foo")
    assert resp.status == 415
    body = await resp.json()
    assert "supported" in body
    assert "html" in body["supported"]


async def test_dispatcher_html_delegates(aiohttp_client, sample_form):
    captured: dict[str, Any] = {}

    class _R(AbstractFormRenderer):
        async def render(self, form, style=None, *, locale="en",
                         prefilled=None, errors=None):
            captured["form_id"] = form.form_id
            captured["locale"] = locale
            return RenderedForm(content="<html/>", content_type="text/html")

    register_renderer("html", _R())
    registry = FormRegistry()
    await registry.register(sample_form)

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get(
        "/api/v1/forms/{form_id}/render/{format}", handle_render
    )

    client = await aiohttp_client(app)
    resp = await client.get(
        f"/api/v1/forms/{sample_form.form_id}/render/html"
    )
    assert resp.status == 200
    assert resp.content_type == "text/html"
    assert captured["form_id"] == sample_form.form_id
    assert captured["locale"] == "en"


async def test_dispatcher_404_when_form_unknown(aiohttp_client):
    register_renderer("html", _make_dummy_renderer())
    registry = FormRegistry()

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get(
        "/api/v1/forms/{form_id}/render/{format}", handle_render
    )

    client = await aiohttp_client(app)
    resp = await client.get("/api/v1/forms/missing/render/html")
    assert resp.status == 404
