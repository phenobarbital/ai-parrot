"""Unit tests for the ``protect_pages`` flag on ``setup_form_ui``."""

from __future__ import annotations

from aiohttp import web

from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.ui import setup_form_ui
from parrot_formdesigner.ui.handlers import FormPageHandler


def _find_handler(app: web.Application, path: str):
    for route in app.router.routes():
        if route.resource.canonical == path and route.method == "GET":
            return route.handler
    raise AssertionError(f"route not found: {path}")


def test_protect_pages_true_wraps_handlers():
    app = web.Application()
    setup_form_ui(app, FormRegistry(), protect_pages=True)
    handler = _find_handler(app, "/")
    # When protected, the handler is wrapped — its __name__ is the wrapped
    # name from is_authenticated/user_session, not the original "index".
    assert not (
        hasattr(handler, "__self__") and isinstance(handler.__self__, FormPageHandler)
    )


def test_protect_pages_false_passes_through():
    app = web.Application()
    setup_form_ui(app, FormRegistry(), protect_pages=False)
    handler = _find_handler(app, "/")
    # When unprotected, the bound method is registered directly.
    assert hasattr(handler, "__self__")
    assert isinstance(handler.__self__, FormPageHandler)
