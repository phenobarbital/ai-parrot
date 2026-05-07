"""Unit tests for ``parrot_formdesigner.api.setup_form_api``."""

from __future__ import annotations

import pytest
from aiohttp import web

from parrot_formdesigner.api import setup_form_api
from parrot_formdesigner.api.render import _RENDERERS
from parrot_formdesigner.services.registry import FormRegistry


@pytest.fixture(autouse=True)
def _reset_renderers():
    snapshot = dict(_RENDERERS)
    _RENDERERS.clear()
    yield
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)


def test_setup_mounts_routes_and_registers_form_registry():
    app = web.Application()
    registry = FormRegistry()
    setup_form_api(app, registry)
    assert app["form_registry"] is registry

    paths = {r.resource.canonical for r in app.router.routes()}
    expected = {
        "/api/v1/forms",
        "/api/v1/forms/from-db",
        "/api/v1/forms/{form_id}",
        "/api/v1/forms/{form_id}/schema",
        "/api/v1/forms/{form_id}/style",
        "/api/v1/forms/{form_id}/render/{format}",
        "/api/v1/forms/{form_id}/validate",
        "/api/v1/forms/{form_id}/data",
        "/api/v1/forms/{form_id}/operations",
        "/api/v1/form-controls",
    }
    assert expected.issubset(paths)


def test_setup_seeds_default_renderers():
    app = web.Application()
    registry = FormRegistry()
    setup_form_api(app, registry)
    assert "html" in _RENDERERS
    assert "adaptive" in _RENDERERS


def test_setup_with_custom_base_path():
    app = web.Application()
    registry = FormRegistry()
    setup_form_api(app, registry, base_path="/custom/v2")
    paths = {r.resource.canonical for r in app.router.routes()}
    assert "/custom/v2/forms" in paths
    assert "/custom/v2/form-controls" in paths
