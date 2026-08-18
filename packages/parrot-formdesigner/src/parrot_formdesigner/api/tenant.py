"""Tenant declaration + authorization decorator (FEAT-421 Module 1).

This is the single enforcement point for the "client declares its tenant"
requirement: a per-route decorator composed into the existing
``_wrap_auth`` chain (``api/routes.py:69``), never an aiohttp middleware.
A decorator is attached to specific handlers at registration time, so it
is structurally incapable of observing a non-forms request.

Public API:

    requires_tenant(*, public: bool = False) -> decorator
    declared_tenant(request) -> str
    enforce_membership_unless_public(request, form, tenant) -> None
    assert_body_tenant_matches(body, tenant) -> None
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from aiohttp import web

from .errors import (
    TenantConflictError,
    TenantForbiddenError,
    TenantNotDeclaredError,
)

logger = logging.getLogger(__name__)

_Handler = Callable[[web.Request], Awaitable[web.Response]]

_EXPECTED_HINT = "/api/v1/{tenant}/forms/{form_uid}"


def _get_programs(request: web.Request) -> list[str]:
    """Extract programs (tenant context) from the user session.

    Mirrors ``FormAPIHandler._get_programs`` (``api/handlers.py:235``) — the
    exact session read the decorator must reuse.

    Args:
        request: Incoming HTTP request with ``session`` attribute attached
            by the navigator-auth ``user_session`` decorator.

    Returns:
        A list of program slug strings. Empty when no session/programs.
    """
    session = getattr(request, "session", None)
    if session is None:
        return []
    userinfo = session.get("session", {})
    return userinfo.get("programs", [])


def _is_superuser(request: web.Request) -> bool:
    """Read the ``superuser`` flag from the same session dict as programs.

    Args:
        request: Incoming HTTP request with ``session`` attribute attached
            by the navigator-auth ``user_session`` decorator.

    Returns:
        ``True`` when the session declares the caller a superuser.
    """
    session = getattr(request, "session", None)
    if session is None:
        return False
    userinfo = session.get("session", {})
    return bool(userinfo.get("superuser", False))


def _authorize(request: web.Request, tenant: str) -> None:
    """Authorize the declared tenant against the navigator-auth session.

    Args:
        request: Incoming HTTP request.
        tenant: The declared tenant, already validated as non-empty.

    Raises:
        TenantForbiddenError: The caller is not a member of ``tenant`` and
            is not a superuser.
    """
    if _is_superuser(request):
        return
    programs = _get_programs(request)
    if tenant in programs:
        return
    logger.warning(
        "Tenant authorization rejected: declared=%r, programs=%r",
        tenant,
        programs,
    )
    raise TenantForbiddenError(expected=_EXPECTED_HINT)


def requires_tenant(*, public: bool = False) -> Callable[[_Handler], _Handler]:
    """Decorator: validate + authorize the URL-declared tenant.

    Applied at route-registration time to forms handlers only. Never
    registered as an aiohttp middleware.

    Order of operations:
        1. Read ``request.match_info["tenant"]`` — 400
           ``tenant_not_declared`` if absent or empty/whitespace.
        2. When ``public=False``, authorize it against the navigator-auth
           session (membership in ``programs``, or ``superuser``) — 403
           ``tenant_forbidden`` otherwise. Skipped when ``public=True``.
        3. Stash the validated value under ``request["tenant"]`` and call
           the wrapped handler.

    Args:
        public: When ``True``, skip the authorization step (public-form
            routes, where ``is_public`` is the grant), but the tenant is
            still mandatory.

    Returns:
        A decorator that wraps a handler with the checks above.
    """

    def _decorator(handler: _Handler) -> _Handler:
        @wraps(handler)
        async def _inner(request: web.Request, **kwargs: Any) -> web.Response:
            tenant = (request.match_info.get("tenant") or "").strip()
            if not tenant:
                raise TenantNotDeclaredError(expected=_EXPECTED_HINT)
            if not public:
                _authorize(request, tenant)
            request["tenant"] = tenant
            return await handler(request)

        return _inner

    return _decorator


def declared_tenant(request: web.Request) -> str:
    """Return the tenant validated by :func:`requires_tenant` for this request.

    Args:
        request: Incoming HTTP request.

    Returns:
        The validated tenant slug.

    Raises:
        RuntimeError: ``request["tenant"]`` is absent — the route was
            mounted without :func:`requires_tenant`. This is a programming
            error, never a runtime fallback.
    """
    tenant = request.get("tenant")
    if not tenant:
        raise RuntimeError(
            "declared_tenant() called on a request with no validated tenant "
            "— the route was mounted without @requires_tenant()."
        )
    return str(tenant)


def enforce_membership_unless_public(
    request: web.Request, form: Any, tenant: str
) -> None:
    """Close the authorization gap on shared public/private routes.

    ``requires_tenant(public=True)`` skips membership authorization at the
    decorator level, because it runs BEFORE the handler resolves the form
    and therefore cannot know whether this SPECIFIC ``form_uid`` is
    actually public — the same route (``GET /forms/{form_uid}``, etc.)
    serves both public and private forms. Call this immediately after the
    form has been resolved and tenant-scoped (:func:`declared_tenant` +
    the registry's tenant-scoped lookup), so a private form on a
    ``public``-mode route still requires the caller to be a tenant member
    (or superuser) — exactly as if the route had been ``tenant="required"``.
    A truly public form (``form.is_public``) is exempt, matching the
    route's original intent.

    Args:
        request: Incoming HTTP request.
        form: The already-resolved, tenant-scoped form.
        tenant: The declared tenant for this request.

    Raises:
        TenantForbiddenError: ``form.is_public`` is falsy and the caller is
            not a member of ``tenant`` (and not a superuser).
    """
    if getattr(form, "is_public", False):
        return
    _authorize(request, tenant)


def assert_body_tenant_matches(body: dict, tenant: str) -> None:
    """Raise 400 when a POST/PUT/PATCH body declares a conflicting tenant.

    The body ``tenant`` key is an optional cross-check, never required and
    never authoritative — the URL is authoritative on every verb.

    Args:
        body: The parsed request body.
        tenant: The URL-declared (and already validated) tenant.

    Raises:
        TenantConflictError: ``body["tenant"]`` is truthy and differs from
            ``tenant``.
    """
    body_tenant = body.get("tenant")
    if body_tenant and body_tenant != tenant:
        raise TenantConflictError(expected=_EXPECTED_HINT)
