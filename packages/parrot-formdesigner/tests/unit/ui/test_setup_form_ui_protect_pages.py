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
    handler = _find_handler(app, "/t/{tenant}/")
    # When protected, the handler is wrapped — its __name__ is the wrapped
    # name from is_authenticated/user_session, not the original "index".
    assert not (
        hasattr(handler, "__self__") and isinstance(handler.__self__, FormPageHandler)
    )


def test_protect_pages_false_passes_through():
    """FEAT-421 TASK-2200/2206: protect=False no longer means "no wrapping
    at all" — the tenant layer (`requires_tenant`) is still applied even
    when navigator-auth is skipped, so fieldsync's `protect_pages=False`
    deployment still gets tenant validation. The old assertion here
    ("unprotected page = the original bound method, untouched") was
    encoding exactly the gap this feature closes; rewritten to the new
    contract rather than preserving the stale expectation."""
    app = web.Application()
    setup_form_ui(app, FormRegistry(), protect_pages=False)
    handler = _find_handler(app, "/t/{tenant}/")
    # Navigator-auth is skipped (no is_authenticated/user_session wrap), so
    # the handler is NOT a bound FormPageHandler method anymore — it's the
    # plain function requires_tenant() returns, tagged with the marker
    # attribute _wrap_auth/_page_wrap use for router-wide coverage checks.
    assert not hasattr(handler, "__self__")
    assert getattr(handler, "_requires_tenant", False) is True
