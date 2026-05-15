"""Unit tests for TASK-1171 — setup_form_api REST bootstrap kwargs."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from aiohttp import web

from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.services.registry import FormRegistry


@pytest.fixture()
def app() -> web.Application:
    return web.Application()


@pytest.fixture()
def registry() -> FormRegistry:
    return FormRegistry()


def test_setup_no_rest_kwargs_works(app, registry):
    """Calling setup_form_api without new kwargs succeeds (backwards-compat)."""
    setup_form_api(app, registry)
    assert "blob_storage" in app
    assert app["blob_storage"] is None
    assert "rest_resolver" in app
    assert app["rest_resolver"] is None


def test_setup_with_blob_storage_stashes(app, registry):
    """blob_storage kwarg is stashed on app."""
    mock_storage = MagicMock()
    setup_form_api(app, registry, blob_storage=mock_storage)
    assert app["blob_storage"] is mock_storage


def test_setup_with_resolver_stashes(app, registry):
    """resolver kwarg is stashed on app."""
    mock_resolver = MagicMock()
    setup_form_api(app, registry, resolver=mock_resolver)
    assert app["rest_resolver"] is mock_resolver


def test_setup_both_kwargs_stashed(app, registry):
    """Both blob_storage and resolver are stashed when provided."""
    mock_storage = MagicMock()
    mock_resolver = MagicMock()
    setup_form_api(app, registry, blob_storage=mock_storage, resolver=mock_resolver)
    assert app["blob_storage"] is mock_storage
    assert app["rest_resolver"] is mock_resolver


def test_setup_existing_kwargs_still_work(app, registry):
    """Legacy kwargs (client, submission_storage, forwarder) still accepted."""
    setup_form_api(
        app,
        registry,
        client=None,
        submission_storage=None,
        forwarder=None,
        base_path="/api/v2",
    )
    assert app["form_registry"] is registry
