"""Route registration for the HTML / Telegram UI surface of parrot-formdesigner.

Hard-imports navigator-auth (matching the api package). HTML page routes
honour the ``protect_pages`` flag via the ``_page_wrap`` helper; Telegram
WebApp routes are registered WITHOUT auth (public by design — Telegram
clients must be able to hit them).

Public API:

    setup_form_ui(app, registry, *, base_path="", protect_pages=True) -> None
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import wraps

from aiohttp import web

# HARD navigator-auth import — same policy as api/routes.py.
from navigator_auth.decorators import is_authenticated, user_session

from ..services.registry import FormRegistry
from .handlers import FormPageHandler
from .telegram import TelegramWebAppHandler


logger = logging.getLogger(__name__)


_Handler = Callable[[web.Request], Awaitable[web.Response]]


def _page_wrap(handler: _Handler, *, protect: bool) -> _Handler:
    """Optionally wrap an HTML page handler with navigator-auth.

    Args:
        handler: A bound async coroutine accepting ``request: web.Request``.
        protect: When ``True``, decorate the handler with
            ``is_authenticated`` + ``user_session``. When ``False``, return
            the handler unchanged (no-op wrapper).

    Returns:
        The (possibly decorated) handler.
    """
    if not protect:
        return handler

    @wraps(handler)
    async def _inner(request: web.Request, **kwargs) -> web.Response:
        return await handler(request)

    decorated = user_session()(_inner)
    # HTML page routes — return text/html on auth failure so browsers
    # render the response, not a raw JSON 401 body.
    decorated = is_authenticated(content_type="text/html")(decorated)
    return decorated


def setup_form_ui(
    app: web.Application,
    registry: FormRegistry,
    *,
    base_path: str = "",
    protect_pages: bool = True,
) -> None:
    """Mount the HTML page + Telegram WebApp surface on ``app``.

    Telegram routes are public (no auth). HTML page routes honour
    ``protect_pages``.

    Args:
        app: aiohttp application to register routes on.
        registry: Pre-built ``FormRegistry`` shared across requests.
        base_path: URL prefix for all routes (default ``""`` — root mount).
        protect_pages: When ``True`` (default), HTML page routes go through
            navigator-auth. When ``False``, they run without auth (useful
            when authentication is handled client-side).
    """
    # Allow callers to mount UI without API by ensuring registry is exposed.
    app.setdefault("form_registry", registry)
    app.setdefault("_form_prefix", base_path.rstrip("/"))

    page = FormPageHandler(registry=registry)
    telegram = TelegramWebAppHandler(registry=registry)

    bp = base_path.rstrip("/")

    # HTML page routes
    app.router.add_get(f"{bp}/", _page_wrap(page.index, protect=protect_pages))
    app.router.add_get(
        f"{bp}/gallery", _page_wrap(page.gallery, protect=protect_pages)
    )
    app.router.add_get(
        f"{bp}/forms/{{form_id}}/schema",
        _page_wrap(page.view_schema, protect=protect_pages),
    )
    app.router.add_get(
        f"{bp}/forms/{{form_id}}",
        _page_wrap(page.render_form, protect=protect_pages),
    )
    app.router.add_post(
        f"{bp}/forms/{{form_id}}",
        _page_wrap(page.submit_form, protect=protect_pages),
    )

    # Telegram WebApp routes — PUBLIC (no auth).
    app.router.add_get(
        f"{bp}/forms/{{form_id}}/telegram", telegram.serve_webapp
    )
    # Telegram REST fallback (for WebApp payloads > 4 KB) — public.
    app.router.add_post(
        f"{bp}/api/v1/forms/{{form_id}}/telegram-submit",
        telegram.rest_fallback,
    )

    logger.info(
        "setup_form_ui: mounted on %s (protect_pages=%s)", bp, protect_pages
    )
