"""Route registration helper for parrot-formdesigner.

One-liner integration: setup_form_routes(app, registry=registry)

Authentication is applied via navigator-auth decorators when the package is
installed. When navigator-auth is not available, routes run without auth for
backward-compatible standalone/dev usage.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TYPE_CHECKING

from aiohttp import web

from ..services.registry import FormRegistry
from .api import FormAPIHandler
from .forms import FormPageHandler
from .telegram import TelegramWebAppHandler

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient

# ---------------------------------------------------------------------------
# Conditional import of navigator-auth decorators
# ---------------------------------------------------------------------------
try:
    from navigator_auth.decorators import is_authenticated, user_session
    _AUTH_AVAILABLE = True
except ImportError:
    _AUTH_AVAILABLE = False


_Handler = Callable[[web.Request], Awaitable[web.Response]]


def _wrap_auth(handler: _Handler) -> _Handler:
    """Wrap a bound handler method with navigator-auth authentication.

    Applies ``is_authenticated()`` (raises 401 if unauthenticated) and
    ``user_session()`` (attaches ``request.user`` and ``request.session``)
    to a single async handler function.

    When navigator-auth is not installed, returns the handler unchanged
    for backward-compatible standalone/dev usage.

    The handler methods on ``FormAPIHandler`` and ``FormPageHandler`` are
    bound methods with signature ``(request: web.Request) -> web.Response``.
    The ``user_session`` decorator's ``_func_wrapper`` would normally inject
    ``session=`` and ``user=`` kwargs — to avoid breaking the handler
    signatures, we strip those kwargs in the inner wrapper and instead rely
    on the decorator having set ``request.user`` and ``request.session`` via
    the middleware contract.

    Args:
        handler: A bound async method accepting ``request: web.Request``.

    Returns:
        The original handler (if navigator-auth unavailable) or a wrapped
        coroutine function protected by auth checks.
    """
    if not _AUTH_AVAILABLE:
        return handler

    @wraps(handler)
    async def _inner(request: web.Request, **kwargs) -> web.Response:
        # user_session's _func_wrapper injects session= and user= kwargs.
        # Our handlers don't accept those — consume them here so they
        # don't cause a TypeError, then call the original handler.
        return await handler(request)

    # At request time: is_authenticated runs first (outer), user_session second (inner).
    _decorated = user_session()(_inner)
    _decorated = is_authenticated(content_type="application/json")(_decorated)
    return _decorated


def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client: "AbstractClient | None" = None,
    prefix: str = "",
    protect_pages: bool = True,
) -> None:
    """Register all form routes on the aiohttp application.

    All ``FormAPIHandler`` (REST API) routes are wrapped with
    navigator-auth authentication when the package is installed.
    ``TelegramWebAppHandler`` routes remain unauthenticated (public
    Telegram WebApp entry points).

    When ``navigator-auth`` is not installed, all routes are registered
    without auth wrappers for backward-compatible standalone/dev usage.

    Args:
        app: The aiohttp Application to register routes on.
        registry: Optional FormRegistry. A new one is created if not provided.
        client: Optional LLM client for natural language form creation.
        prefix: Optional URL prefix for all routes (e.g. ``"/forms-app"``).
        protect_pages: When ``True`` (default), HTML page handlers are
            wrapped with navigator-auth decorators (server-side auth).
            Set to ``False`` when authentication is handled client-side
            (e.g. the ``page_shell`` auth script injects the JWT from
            localStorage into ``fetch()`` calls to API endpoints).
    """
    if registry is None:
        registry = FormRegistry()

    api = FormAPIHandler(registry=registry, client=client)
    page = FormPageHandler(registry=registry)
    telegram = TelegramWebAppHandler(registry=registry)

    p = prefix.rstrip("/")
    app["_form_prefix"] = p

    _page_wrap = _wrap_auth if protect_pages else lambda h: h

    # HTML page routes
    app.router.add_get(f"{p}/", _page_wrap(page.index))
    app.router.add_get(f"{p}/gallery", _page_wrap(page.gallery))
    app.router.add_get(f"{p}/forms/{{form_id}}/schema", _page_wrap(page.view_schema))
    app.router.add_get(f"{p}/forms/{{form_id}}", _page_wrap(page.render_form))
    app.router.add_post(f"{p}/forms/{{form_id}}", _page_wrap(page.submit_form))

    # Telegram WebApp route — public (no auth).
    # aiohttp matches /forms/{id}/telegram by path depth (3 segments), so it
    # is unambiguous with the /forms/{form_id} catch-all above (2 segments).
    app.router.add_get(f"{p}/forms/{{form_id}}/telegram", telegram.serve_webapp)

    # JSON REST API routes (v1) — authenticated via navigator-auth
    app.router.add_post(f"{p}/api/v1/forms", _wrap_auth(api.create_form))
    app.router.add_get(f"{p}/api/v1/forms", _wrap_auth(api.list_forms))
    app.router.add_post(f"{p}/api/v1/forms/from-db", _wrap_auth(api.load_from_db))
    app.router.add_get(f"{p}/api/v1/forms/{{form_id}}", _wrap_auth(api.get_form))
    app.router.add_get(f"{p}/api/v1/forms/{{form_id}}/schema", _wrap_auth(api.get_schema))
    app.router.add_get(f"{p}/api/v1/forms/{{form_id}}/style", _wrap_auth(api.get_style))
    app.router.add_get(f"{p}/api/v1/forms/{{form_id}}/html", _wrap_auth(api.get_html))
    app.router.add_post(f"{p}/api/v1/forms/{{form_id}}/validate", _wrap_auth(api.validate))

    # Telegram REST fallback (for WebApp payloads > 4 KB) — public (no auth)
    app.router.add_post(
        f"{p}/api/v1/forms/{{form_id}}/telegram-submit", telegram.rest_fallback
    )
