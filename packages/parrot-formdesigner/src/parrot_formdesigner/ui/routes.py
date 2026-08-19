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


def _reserved_tenant_segments(app: web.Application, bp: str) -> frozenset[str]:
    """Derive reserved literal segments from the router (FEAT-429 Module 5).

    Introspects every route already registered on ``app`` and collects the
    literal (non-``{tenant}``) first path segment of any route mounted
    directly under ``bp`` — the exact tree level the dynamic ``{tenant}``
    segment occupies. This is what makes the reserved set DERIVED rather
    than hardcoded (spec Module 5 / AC13): calling this AFTER this
    module's own routes are registered means any literal added later in
    this same function is picked up automatically, with no second edit
    required. Duplicated from ``api/routes.py`` rather than shared — this
    package's convention (see ``_TENANT_MODES`` above) keeps the two route
    modules independent.

    Args:
        app: The aiohttp application whose router has already had this
            module's routes registered.
        bp: The stripped base path (``base_path.rstrip("/")``) routes in
            this module were mounted under — ``""`` for a root mount.

    Returns:
        The set of literal first-segment strings sitting at the same tree
        level as ``{tenant}`` under ``bp`` (e.g. ``{"api"}``). Empty when
        no such literal exists.
    """
    reserved: set[str] = set()
    for route in app.router.routes():
        resource = route.resource
        if resource is None:
            continue
        canonical = resource.canonical
        if bp and not canonical.startswith(f"{bp}/"):
            continue
        remainder = canonical[len(bp):].lstrip("/")
        if not remainder:
            continue
        first_segment = remainder.split("/", 1)[0]
        if first_segment and not first_segment.startswith("{"):
            reserved.add(first_segment)
    return frozenset(reserved)


def _page_wrap(
    handler: _Handler, *, protect: bool, tenant: str = "required"
) -> _Handler:
    """Optionally wrap an HTML page handler with navigator-auth.

    The ``requires_tenant`` layer (FEAT-421) is applied BEFORE the
    ``protect=False`` early-return: fieldsync runs with
    ``protect_pages=False``, so if the tenant layer were only added to the
    ``protect=True`` branch, the very deployment this feature exists for
    would get no tenant validation at all.

    FEAT-421 review fix (2nd pass, CRITICAL): when ``protect=False``,
    navigator-auth's ``user_session()`` never runs, so ``request.session``
    is never populated. ``requires_tenant(public=False)``'s membership
    check unconditionally reads that session — with no session, EVERY
    caller (including the legitimate tenant owner) would be rejected with
    403, silently breaking the exact ``protect_pages=False`` deployment
    (fieldsync, and this repo's own ``app.py``) this feature must serve
    without any application-code change (spec AC10). There is no session
    to authorize against in this mode regardless of the caller's true
    membership, so ``tenant="required"`` is downgraded to declare-only
    (``public=True``) whenever ``protect=False`` — mirroring the Telegram
    routes' already-established workaround for the same root cause.

    Args:
        handler: A bound async coroutine accepting ``request: web.Request``.
        protect: When ``True``, decorate the handler with
            ``is_authenticated`` + ``user_session``. When ``False``, skip
            navigator-auth (auth handled client-side) but still apply the
            tenant layer.
        tenant: Tenant-enforcement mode — one of ``"required"``,
            ``"public"``, or ``"none"``. See ``api.routes._wrap_auth`` for
            the full mode contract. Downgraded to declare-only when
            ``protect=False`` (see above).

    Returns:
        The (possibly decorated) handler.

    Raises:
        ValueError: ``tenant`` is not one of the three valid modes.
    """
    if tenant not in _TENANT_MODES:
        raise ValueError(f"tenant must be one of {_TENANT_MODES}, got {tenant!r}")

    tenant_applied = tenant != "none"
    if tenant_applied:
        effective_public = (tenant == "public") or not protect
        handler = requires_tenant(public=effective_public)(handler)

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
    # FEAT-421: HTML page routes are mounted under the same `{tenant}`
    # path component as the JSON REST surface (api/routes.py), for the
    # same reason — the tenant is a declared, cross-checkable path
    # component. FEAT-429 removed the literal `t` disambiguation marker
    # segment as unnecessary (see spec §2).
    tp = f"{bp}/{{tenant}}"

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

    # Telegram WebApp routes — PUBLIC (no navigator-auth session; Telegram
    # WebApp clients cannot carry one). FEAT-421 TASK-2204: still wrapped
    # with `_page_wrap(..., protect=False, tenant="public")` — protect=False
    # skips navigator-auth's is_authenticated/user_session entirely (the
    # early-return in _page_wrap), but the tenant layer (declare + skip
    # authorization) still applies, so `declared_tenant()` works inside
    # `TelegramWebAppHandler`.
    app.router.add_get(
        f"{tp}/forms/{{form_uid}}/telegram",
        _page_wrap(telegram.serve_webapp, protect=False, tenant="public"),
    )
    # Telegram REST fallback (for WebApp payloads > 4 KB) — public.
    app.router.add_post(
        f"{bp}/api/v1/{{tenant}}/forms/{{form_uid}}/telegram-submit",
        _page_wrap(telegram.rest_fallback, protect=False, tenant="public"),
    )

    # FEAT-429 Module 5: reserved-segment guard. Every route above is now
    # registered, so introspect the router for literal (non-`{tenant}`)
    # first-path-segments sitting directly under `bp` — the exact tree
    # level `{tenant}` occupies (today: `api`, from the telegram-submit
    # fallback route above). DERIVED from the actual registrations (spec
    # Module 5 / AC13: "never hardcoded"), so a future literal route added
    # anywhere above is reserved automatically, with no second edit
    # required. Merged (union) with any reserved set already stashed by
    # setup_form_api on the same app, since requires_tenant() is shared
    # across the API and UI surfaces and a tenant identity is not siloed
    # per mount.
    ui_reserved_tenant_segments = _reserved_tenant_segments(app, bp)
    app["formdesigner_reserved_tenant_segments"] = (
        app.get("formdesigner_reserved_tenant_segments", frozenset())
        | ui_reserved_tenant_segments
    )

    logger.info(
        "setup_form_ui: mounted on %s (protect_pages=%s)", bp, protect_pages
    )
