"""Tenant/group scope resolution for the ui_surfaces plane (FEAT-535, Module 2).

Parrot must not know how a host decides the caller's tenant — FieldSync
reads it from the URL (a declared program), another host might read it
from the session, a third might have no notion of tenant at all. So the
handler asks a pluggable :class:`SurfaceScopeResolver` installed on the app
under ``app["ui_surfaces_scope_resolver"]``; when none is installed, the
:class:`SessionSurfaceScopeResolver` default reads the navigator-auth
session and resolves a tenant ONLY when the session carries exactly one
program (see its own docstring for why).

:func:`scope_grants` is the pure "who, besides the owner, may see this
record" rule — the owner is handled upstream by the caller
(``resolve_surface_access``), never here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from aiohttp import web
from navigator_auth.conf import AUTH_SESSION_OBJECT
from navigator_session import get_session
from parrot.auth.session_identity import resolve_user_id
from parrot.handlers.models.ui_surfaces import SurfaceVisibility, UISurfaceRecord

logger = logging.getLogger(__name__)

__all__ = [
    "EMPTY_SCOPE",
    "SessionSurfaceScopeResolver",
    "SurfaceScope",
    "SurfaceScopeResolver",
    "get_scope_resolver",
    "scope_grants",
]


@dataclass(frozen=True)
class SurfaceScope:
    """The caller's identity, tenant, groups and superuser flag for a request.

    Attributes:
        user_id: The authenticated caller's id, or ``None`` when
            unauthenticated/unresolvable.
        tenant: The caller's single declared tenant, or ``None`` when the
            host/session has none (or more than one) — a caller without a
            tenant never matches the tenant/group visibility rule.
        groups: The caller's group memberships (opaque strings; spec §8 —
            parrot does not interpret their vocabulary).
        is_superuser: Whether the caller sees every surface of ``tenant``,
            regardless of ``visibility``/``allowed_groups``. Never
            cross-tenant.
    """

    user_id: str | None
    tenant: str | None
    groups: frozenset[str]
    is_superuser: bool = False


#: The scope of an unauthenticated/unresolvable caller — owns nothing, sees
#: nothing beyond what ``resolve_surface_access`` grants via ownership or a
#: share token.
EMPTY_SCOPE = SurfaceScope(user_id=None, tenant=None, groups=frozenset(), is_superuser=False)

# Also reachable as `SurfaceScope.EMPTY` (spec §3 Module 2).
SurfaceScope.EMPTY = EMPTY_SCOPE  # type: ignore[attr-defined]


class SurfaceScopeResolver(Protocol):
    """Host-pluggable resolver of the caller's :class:`SurfaceScope`.

    A host with its own tenancy seam (e.g. FieldSync's URL-declared
    program) installs an implementation of this protocol under
    ``app["ui_surfaces_scope_resolver"]`` (see :func:`get_scope_resolver`).
    """

    async def resolve(self, request: web.Request) -> SurfaceScope:
        """Resolve the caller's scope for this request."""
        ...


class SessionSurfaceScopeResolver:
    """Default resolver: reads the navigator-auth session.

    Resolves ``tenant`` from ``session[AUTH_SESSION_OBJECT]["programs"]``
    ONLY when that list has exactly one entry — a multi-program session
    (FieldSync's shape: one admin session spans many programs) yields
    ``tenant=None``, which makes every tenant/group rule evaluate to "no
    match" (spec §2), keeping owner-only behaviour for hosts that did not
    opt in. The ``programs[0]`` convention for a multi-program session was
    the FEAT-366 failure in FieldSync — never repeat it here. A host with
    URL-declared tenants (FieldSync) must install its own resolver.

    Every value read from the session ``Mapping`` is type-checked, never
    truth-checked — a ``Mock`` answers ``.get()`` with a truthy ``Mock``,
    so an ``isinstance`` check is the only safe guard.
    """

    async def resolve(self, request: web.Request) -> SurfaceScope:
        """Resolve the caller's scope from the navigator-auth session.

        Args:
            request: The incoming aiohttp request.

        Returns:
            :data:`EMPTY_SCOPE` for an unauthenticated request or one with
            no session storage configured; otherwise a :class:`SurfaceScope`
            built from the session's ``user_id``/``programs``/``groups``/
            ``superuser``.
        """
        try:
            session = await get_session(request)
        except Exception:  # noqa: BLE001 - fail closed, never let a broken
            # session backend (or a test double lacking `.get()`) leak past
            # this resolver as an exception; an EMPTY_SCOPE is always safe.
            session = None

        user_id = resolve_user_id(request, session)

        if session is None:
            return SurfaceScope(user_id=user_id, tenant=None, groups=frozenset(), is_superuser=False)

        userinfo: Any = session.get(AUTH_SESSION_OBJECT)
        if not isinstance(userinfo, dict):
            return SurfaceScope(user_id=user_id, tenant=None, groups=frozenset(), is_superuser=False)

        programs = userinfo.get("programs")
        programs_list = [p for p in programs if isinstance(p, str)] if isinstance(programs, (list, tuple)) else []

        groups_raw = userinfo.get("groups")
        groups = (
            frozenset(g for g in groups_raw if isinstance(g, str))
            if isinstance(groups_raw, (list, tuple))
            else frozenset()
        )

        superuser_raw = userinfo.get("superuser")
        is_superuser = superuser_raw if isinstance(superuser_raw, bool) else False

        tenant = programs_list[0] if len(programs_list) == 1 else None

        return SurfaceScope(user_id=user_id, tenant=tenant, groups=groups, is_superuser=is_superuser)


def get_scope_resolver(app: Any) -> SurfaceScopeResolver:
    """Return the host's installed scope resolver, or the default.

    Args:
        app: The aiohttp ``web.Application`` (or, in tests, any plain
            ``dict``-like object exposing ``.get()``).

    Returns:
        ``app["ui_surfaces_scope_resolver"]`` when installed, else a
        shared :class:`SessionSurfaceScopeResolver` instance.
    """
    resolver: SurfaceScopeResolver | None = None
    try:
        resolver = app.get("ui_surfaces_scope_resolver")
    except AttributeError:
        resolver = None
    return resolver or _DEFAULT_RESOLVER


_DEFAULT_RESOLVER = SessionSurfaceScopeResolver()


def scope_grants(record: UISurfaceRecord, scope: SurfaceScope) -> bool:
    """Whether ``scope`` may see ``record`` by tenant/group/superuser rule.

    Pure — does NOT consider ownership (the caller, ``resolve_surface_access``,
    checks ``record.user_id == scope.user_id`` first and never reaches here
    for the owner).

    Args:
        record: The stored surface.
        scope: The caller's resolved scope.

    Returns:
        ``False`` when ``scope.tenant`` is ``None``, ``record.tenant`` is
        ``None``, or they differ (a caller/row without a tenant never
        matches). Otherwise ``True`` when ``scope.is_superuser``, or
        ``record.visibility is SurfaceVisibility.tenant``, or
        ``record.visibility is SurfaceVisibility.groups`` and ``scope.groups``
        intersects ``record.allowed_groups``.
    """
    if scope.tenant is None or record.tenant is None or record.tenant != scope.tenant:
        return False
    if scope.is_superuser:
        return True
    if record.visibility is SurfaceVisibility.tenant:
        return True
    if record.visibility is SurfaceVisibility.groups:
        return bool(scope.groups & set(record.allowed_groups))
    return False
