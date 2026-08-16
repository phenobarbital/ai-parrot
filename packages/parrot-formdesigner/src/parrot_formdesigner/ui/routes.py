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
from ..api.tenant import requires_tenant


logger = logging.getLogger(__name__)


_Handler = Callable[[web.Request], Awaitable[web.Response]]

_TENANT_MODES = ("required", "public", "none")


def _page_wrap(
    handler: _Handler, *, protect: bool, tenant: str = "required"
) -> _Handler:
    """Optionally wrap an HTML page handler with navigator-auth.

    The ``requires_tenant`` layer (FEAT-421) is applied BEFORE the
    ``protect=False`` early-return: fieldsync runs with
    ``protect_pages=False``, so if the tenant layer were only added to the
    ``protect=True`` branch, the very deployment this feature exists for
    would get no tenant validation at all.

    Args:
        handler: A bound async coroutine accepting ``request: web.Request``.
        protect: When ``True``, decorate the handler with
            ``is_authenticated`` + ``user_session``. When ``False``, skip
            navigator-auth (auth handled client-side) but still apply the
            tenant layer.
        tenant: Tenant-enforcement mode — one of ``"required"``,
            ``"public"``, or ``"none"``. See ``api.routes._wrap_auth`` for
            the full mode contract.

    Returns:
        The (possibly decorated) handler.

    Raises:
        ValueError: ``tenant`` is not one of the three valid modes.
    """
    if tenant not in _TENANT_MODES:
        raise ValueError(f"tenant must be one of {_TENANT_MODES}, got {tenant!r}")

    tenant_applied = tenant != "none"
    if tenant_applied:
        handler = requires_tenant(public=(tenant == "public"))(handler)

    if not protect:
        if tenant_applied:
            handler._requires_tenant = True
        return handler

    @wraps(handler)
    async def _inner(request: web.Request, **kwargs) -> web.Response:
        return await handler(request)

    decorated = user_session()(_inner)
    # HTML page routes — return text/html on auth failure so browsers
    # render the response, not a raw JSON 401 body.
    decorated = is_authenticated(content_type="text/html")(decorated)
    if tenant_applied:
        decorated._requires_tenant = True
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
    # FEAT-421: HTML page routes are re-prefixed under the same `t/{tenant}`
    # marker segment as the JSON REST surface (api/routes.py), for the same
    # reason — the tenant is a declared, cross-checkable path component.
    tp = f"{bp}/t/{{tenant}}"

    # HTML page routes
    app.router.add_get(f"{tp}/", _page_wrap(page.index, protect=protect_pages))
    app.router.add_get(
        f"{tp}/gallery", _page_wrap(page.gallery, protect=protect_pages)
    )
    app.router.add_get(
        f"{tp}/forms/{{form_uid}}/schema",
        _page_wrap(page.view_schema, protect=protect_pages),
    )
    app.router.add_get(
        f"{tp}/forms/{{form_uid}}",
        _page_wrap(page.render_form, protect=protect_pages),
    )
    app.router.add_post(
        f"{tp}/forms/{{form_uid}}",
        _page_wrap(page.submit_form, protect=protect_pages),
    )

    # Telegram WebApp routes — PUBLIC (no auth). Re-prefixed for path
    # consistency (FEAT-421); the tenant is declared but not yet validated
    # here — the inline tenant check inside the handlers is TASK-2204's job
    # (these routes are not `_page_wrap`-ed at all, matching the audio WS
    # route's rationale: Telegram WebApp clients cannot go through
    # navigator-auth).
    app.router.add_get(
        f"{tp}/forms/{{form_uid}}/telegram", telegram.serve_webapp
    )
    # Telegram REST fallback (for WebApp payloads > 4 KB) — public.
    app.router.add_post(
        f"{bp}/api/v1/t/{{tenant}}/forms/{{form_uid}}/telegram-submit",
        telegram.rest_fallback,
    )

    logger.info(
        "setup_form_ui: mounted on %s (protect_pages=%s)", bp, protect_pages
    )
