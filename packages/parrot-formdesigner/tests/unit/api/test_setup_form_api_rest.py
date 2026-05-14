"""Unit tests for ``setup_form_api`` REST-field bootstrap wiring — FEAT-170."""

from __future__ import annotations

from unittest.mock import MagicMock

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


def test_setup_no_rest_kwargs_still_works() -> None:
    """setup_form_api without REST kwargs must succeed and set defaults to None."""
    app = web.Application()
    registry = FormRegistry()
    setup_form_api(app, registry)
    assert app["blob_storage"] is None
    assert app["rest_resolver"] is None


def test_setup_with_blob_storage_stashed() -> None:
    """blob_storage kwarg must be stashed on the app."""
    app = web.Application()
    registry = FormRegistry()
    mock_storage = MagicMock()
    setup_form_api(app, registry, blob_storage=mock_storage)
    assert app["blob_storage"] is mock_storage


def test_setup_with_resolver_stashed() -> None:
    """resolver kwarg must be stashed on the app."""
    app = web.Application()
    registry = FormRegistry()
    mock_resolver = MagicMock()
    setup_form_api(app, registry, resolver=mock_resolver)
    assert app["rest_resolver"] is mock_resolver


def test_setup_with_both_rest_kwargs() -> None:
    """Both blob_storage and resolver kwargs must be stashed together."""
    app = web.Application()
    registry = FormRegistry()
    mock_storage = MagicMock()
    mock_resolver = MagicMock()
    setup_form_api(app, registry, blob_storage=mock_storage, resolver=mock_resolver)
    assert app["blob_storage"] is mock_storage
    assert app["rest_resolver"] is mock_resolver


def test_setup_upload_route_mounted() -> None:
    """Upload route must be registered after setup_form_api."""
    app = web.Application()
    registry = FormRegistry()
    setup_form_api(app, registry)
    paths = {r.resource.canonical for r in app.router.routes()}
    assert "/api/v1/forms/{form_id}/fields/{field_id}/upload" in paths


def test_setup_upload_route_custom_base_path() -> None:
    """Upload route must respect custom base_path."""
    app = web.Application()
    registry = FormRegistry()
    setup_form_api(app, registry, base_path="/custom/v2")
    paths = {r.resource.canonical for r in app.router.routes()}
    assert "/custom/v2/forms/{form_id}/fields/{field_id}/upload" in paths


def test_setup_existing_routes_still_mounted() -> None:
    """Existing routes must still be present after adding REST kwargs."""
    app = web.Application()
    registry = FormRegistry()
    setup_form_api(app, registry, blob_storage=MagicMock())
    paths = {r.resource.canonical for r in app.router.routes()}
    assert "/api/v1/forms" in paths
    assert "/api/v1/forms/{form_id}" in paths
    assert "/api/v1/forms/{form_id}/data" in paths
