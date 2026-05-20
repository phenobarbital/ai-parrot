"""Unit tests for ``parrot_formdesigner.ui.setup_form_ui`` route registration."""

from __future__ import annotations

from aiohttp import web

from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.ui import setup_form_ui


def test_routes_mounted():
    app = web.Application()
    setup_form_ui(app, FormRegistry())
    paths = {r.resource.canonical for r in app.router.routes()}
    assert "/" in paths
    assert "/gallery" in paths
    assert "/forms/{form_id}" in paths
    assert "/forms/{form_id}/schema" in paths
    assert "/forms/{form_id}/telegram" in paths
    assert "/api/v1/forms/{form_id}/telegram-submit" in paths


def test_app_form_registry_set():
    app = web.Application()
    registry = FormRegistry()
    setup_form_ui(app, registry)
    assert app["form_registry"] is registry


def test_app_form_registry_setdefault_does_not_overwrite():
    """If app['form_registry'] is already set (e.g. setup_form_api ran first),
    setup_form_ui must not overwrite it."""
    app = web.Application()
    api_registry = FormRegistry()
    app["form_registry"] = api_registry

    ui_registry = FormRegistry()
    setup_form_ui(app, ui_registry)
    assert app["form_registry"] is api_registry  # untouched


def test_telegram_route_has_no_auth_wrapper():
    """The Telegram WebApp route is public (no `is_authenticated` wrap)."""

    app = web.Application()
    setup_form_ui(app, FormRegistry())

    # Find the telegram route handler
    for route in app.router.routes():
        if route.resource.canonical == "/forms/{form_id}/telegram":
            handler = route.handler
            # The handler should be the raw bound method (no decorator wrapping
            # — `is_authenticated`/`user_session` would replace it with a
            # `_decorated` function name).
            assert handler.__name__ == "serve_webapp" or hasattr(
                handler, "__self__"
            )
            return
    raise AssertionError("Telegram route not found")
