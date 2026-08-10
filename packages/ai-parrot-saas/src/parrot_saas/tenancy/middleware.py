"""Resolve which tenant an HTTP request serves, and fail closed if unclear.

This middleware — not PBAC — is the isolation boundary. That is worth stating
plainly because the surrounding layers both fail *open*: navigator-auth's
``abac_middleware`` lets any unauthenticated request through
(``if request.get('authenticated', False) is False: return await handler(...)``),
and ``setup_pbac`` degrades to no policy engine at all when its policy
directory is missing. Neither is a defect in those layers; it does mean a
missing tenant must be an error here rather than a silent default.

Registration order matters and is not arbitrary. ``setup_pbac`` appends
``abac_middleware`` last, and aiohttp runs first-registered outermost, so
anything registered after it executes *inside* ABAC — after the authorization
decision was already made. This middleware must therefore be registered
**after** ``AuthHandler.setup`` (so a session exists) and **before**
``setup_pbac`` (so policies can read ``request["tenant"]``).
"""
from __future__ import annotations

import fnmatch
import ipaddress
from typing import Any, Awaitable, Callable, Iterable, Optional, Sequence

from aiohttp import web
from navconfig.logging import logging

from .context import TENANT_ID_PATTERN, TenantContext

logger = logging.getLogger("parrot_saas.tenancy.middleware")

#: Header carrying the tenant slug.
TENANT_HEADER = "X-Tenant-Id"

#: Key under which the resolved tenant is published on the request.
REQUEST_TENANT_KEY = "tenant"

#: Paths that never need a tenant. The control plane carries the tenant in its
#: own route and is gated by an admin policy instead.
DEFAULT_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/api/v1/saas/control/",
    "/api/v1/abac/",
    "/health",
    "/api/docs",
)

#: Resolution strategies, in the order they are attempted.
DEFAULT_STRATEGIES: tuple[str, ...] = ("header", "subdomain")


class TenantResolutionError(web.HTTPException):
    """Base for the middleware's fail-closed responses."""


def _json_error(status: int, code: str, message: str) -> web.Response:
    """Build a JSON error response.

    Args:
        status: HTTP status.
        code: Machine-readable error code.
        message: Human-readable explanation.

    Returns:
        The response.
    """
    return web.json_response(
        {"error": code, "message": message}, status=status
    )


def _from_header(request: web.Request) -> Optional[str]:
    """Read the tenant slug from the request header."""
    value = request.headers.get(TENANT_HEADER)
    return value.strip().lower() if value else None


def _from_subdomain(request: web.Request) -> Optional[str]:
    """Read the tenant slug from the left-most host label.

    Three kinds of host must not resolve a tenant:

    * fewer than three labels — ``example.com`` and ``localhost:8080`` have no
      subdomain to read;
    * an IP address — ``127.0.0.1`` splits into four labels and would
      otherwise resolve ``127`` as a tenant slug, which is exactly what
      happens against a test client or a service reached by address;
    * the conventional non-tenant labels ``www`` and ``api``.
    """
    host = (request.host or "").split(":", 1)[0].strip("[]")
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return None

    labels = host.split(".")
    if len(labels) < 3:
        return None
    candidate = labels[0].lower()
    return candidate if candidate not in {"www", "api"} else None


def _claim_reader(claim: str) -> Callable[[web.Request], Optional[str]]:
    """Build a strategy reading the tenant slug from a session claim.

    Off by default, and for a concrete reason: **no ``tenant_id`` or ``org_id``
    claim exists in this deployment today.** The nearest multi-tenant signal in
    the session is ``programs`` (a list), which is not a tenant. Enabling this
    strategy is therefore an explicit act once an issuer actually emits the
    claim, rather than an assumption baked into the default path.

    Args:
        claim: Name of the claim to read.

    Returns:
        A resolution strategy.
    """

    def _read(request: web.Request) -> Optional[str]:
        session = request.get("session") or {}
        try:
            from navigator_auth.conf import AUTH_SESSION_OBJECT
        except ImportError:  # pragma: no cover - navigator-auth is optional
            return None
        userinfo = session.get(AUTH_SESSION_OBJECT, {}) if session else {}
        value = None
        if isinstance(userinfo, dict):
            value = userinfo.get(claim)
        if not value and isinstance(session, dict):
            value = session.get(claim)
        return str(value).strip().lower() if value else None

    return _read


def tenant_resolution_middleware(
    *,
    repository: Any,
    cache: Optional[Any] = None,
    strategies: Sequence[str] = DEFAULT_STRATEGIES,
    exempt_prefixes: Iterable[str] = DEFAULT_EXEMPT_PREFIXES,
    exempt_patterns: Iterable[str] = (),
    session_claim: str = "tenant_id",
) -> Callable[[web.Request, Callable[[web.Request], Awaitable[Any]]], Awaitable[Any]]:
    """Build the tenant-resolution middleware.

    Args:
        repository: Object exposing ``async get(tenant_id) -> Tenant | None``.
        cache: Optional per-tenant runtime cache. Only consulted so that a
            resolved tenant can be warmed later; resolution never depends on
            it.
        strategies: Ordered resolution strategies, from ``"header"``,
            ``"subdomain"`` and ``"claim"``.
        exempt_prefixes: Path prefixes that skip resolution entirely.
        exempt_patterns: Glob patterns that skip resolution (for webhook
            routes authenticated by signature instead).
        session_claim: Claim name used by the ``"claim"`` strategy.

    Returns:
        An aiohttp middleware.

    Raises:
        ValueError: If an unknown strategy name is given.
    """
    readers: list[Callable[[web.Request], Optional[str]]] = []
    for name in strategies:
        if name == "header":
            readers.append(_from_header)
        elif name == "subdomain":
            readers.append(_from_subdomain)
        elif name == "claim":
            readers.append(_claim_reader(session_claim))
        else:
            raise ValueError(f"unknown tenant resolution strategy: {name!r}")

    prefixes = tuple(exempt_prefixes)
    patterns = tuple(exempt_patterns)

    def _is_exempt(path: str) -> bool:
        """Whether a path skips tenant resolution."""
        if path.startswith(prefixes):
            return True
        return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)

    @web.middleware
    async def _middleware(request: web.Request, handler) -> Any:
        """Resolve the tenant, or refuse the request."""
        if request.method == "OPTIONS" or _is_exempt(request.path):
            return await handler(request)

        slug: Optional[str] = None
        for read in readers:
            slug = read(request)
            if slug:
                break

        if not slug:
            return _json_error(
                400,
                "tenant_required",
                f"no tenant could be resolved; send the {TENANT_HEADER} header",
            )
        if not TENANT_ID_PATTERN.match(slug):
            return _json_error(
                400, "tenant_invalid", f"malformed tenant identifier: {slug!r}"
            )

        tenant = await repository.get(slug)
        if tenant is None:
            return _json_error(
                404, "unknown_tenant", f"no such tenant: {slug!r}"
            )

        context: TenantContext = tenant.to_context()
        if not context.is_active:
            return _json_error(
                403,
                "tenant_suspended",
                f"tenant {slug!r} is {context.status.value}",
            )

        request[REQUEST_TENANT_KEY] = context
        return await handler(request)

    return _middleware


def current_tenant(request: web.Request) -> TenantContext:
    """Return the tenant resolved for this request.

    Args:
        request: The in-flight request.

    Returns:
        The tenant context published by the middleware.

    Raises:
        RuntimeError: If called on an exempt route, or one the middleware
            never ran for. Deliberately loud: a handler that expected a tenant
            and silently got ``None`` is how cross-tenant reads happen.
    """
    tenant = request.get(REQUEST_TENANT_KEY)
    if tenant is None:
        raise RuntimeError(
            "no tenant on this request; either the route is exempt from "
            "tenant resolution or the middleware is not installed"
        )
    return tenant


__all__ = (
    "DEFAULT_EXEMPT_PREFIXES",
    "DEFAULT_STRATEGIES",
    "REQUEST_TENANT_KEY",
    "TENANT_HEADER",
    "current_tenant",
    "tenant_resolution_middleware",
)
