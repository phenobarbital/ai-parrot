"""Neutral request scope seam shared by UI surfaces and Agent Studio (FEAT-605 M1)."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from aiohttp import web
from navigator_auth.conf import AUTH_SESSION_OBJECT
from navigator_session import get_session
from parrot.auth.session_identity import resolve_user_id

logger = logging.getLogger(__name__)

SCOPE_RESOLVER_APP_KEY = "scope_resolver"
LEGACY_SCOPE_RESOLVER_APP_KEY = "ui_surfaces_scope_resolver"
VISIBILITY_LEVELS: frozenset[str] = frozenset({"private", "tenant", "groups"})
VisibilityLevel = Literal["private", "tenant", "groups"]

__all__ = [
    "EMPTY_SCOPE",
    "LEGACY_SCOPE_RESOLVER_APP_KEY",
    "RequestScope",
    "SCOPE_RESOLVER_APP_KEY",
    "ScopeResolver",
    "SessionScopeResolver",
    "VISIBILITY_LEVELS",
    "VisibilityLevel",
    "get_scope_resolver",
    "has_installed_resolver",
    "normalize_visibility",
    "scope_grants",
]


@dataclass(frozen=True)
class RequestScope:
    """Caller identity + host-computed gates for one request.

    Attributes:
        user_id: Authenticated caller id, or ``None``.
        tenant: The caller's single tenant, or ``None``.
        groups: Opaque group memberships.
        is_superuser: Sees every record of ``tenant`` regardless of visibility.
        may_author: Host gate for authoring operations.
        may_administer: Host gate granting tenant-wide administration.
        studio_enabled: Host gate for the Agent Studio surface.
    """

    user_id: str | None
    tenant: str | None
    groups: frozenset[str]
    is_superuser: bool = False
    may_author: bool = True
    may_administer: bool = False
    studio_enabled: bool = True


#: Scope of an unauthenticated/unresolvable caller.
EMPTY_SCOPE = RequestScope(user_id=None, tenant=None, groups=frozenset(), is_superuser=False)
RequestScope.EMPTY = EMPTY_SCOPE  # type: ignore[attr-defined]  # FEAT-535 `SurfaceScope.EMPTY`


class ScopeResolver(Protocol):
    """Host-pluggable resolver installed at ``app["scope_resolver"]``."""

    async def resolve(self, request: web.Request) -> RequestScope:
        """Resolve the caller's scope for this request."""
        ...


class SessionScopeResolver:
    """Default resolver: reads the navigator-auth session.

    Resolves ``tenant`` from ``session[AUTH_SESSION_OBJECT]["programs"]``
    ONLY when that list has exactly one entry — never ``programs[0]`` for a
    multi-program session. Every value read from the session ``Mapping`` is
    type-checked, never truth-checked.
    """

    async def resolve(self, request: web.Request) -> RequestScope:
        """Resolve the caller's scope from the navigator-auth session.

        Args:
            request: The incoming aiohttp request.

        Returns:
            A :class:`RequestScope`; owner-only (no tenant) on any failure.
        """
        try:
            session = await get_session(request)
        except Exception:  # noqa: BLE001 - fail closed, never let a broken
            # session backend (or a test double lacking `.get()`) leak past
            # this resolver as an exception; an EMPTY_SCOPE is always safe.
            session = None

        user_id = resolve_user_id(request, session)

        if session is None:
            return RequestScope(user_id=user_id, tenant=None, groups=frozenset(), is_superuser=False)

        userinfo: Any = session.get(AUTH_SESSION_OBJECT)
        if not isinstance(userinfo, dict):
            return RequestScope(user_id=user_id, tenant=None, groups=frozenset(), is_superuser=False)

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

        return RequestScope(user_id=user_id, tenant=tenant, groups=groups, is_superuser=is_superuser)


_DEFAULT_RESOLVER = SessionScopeResolver()


def _app_get(app: Any, key: str) -> Any:
    try:
        return app.get(key)
    except AttributeError:
        return None


def has_installed_resolver(app: Any) -> bool:
    """True when the host installed a resolver under either key ("opted-in host")."""
    return _app_get(app, SCOPE_RESOLVER_APP_KEY) is not None or _app_get(app, LEGACY_SCOPE_RESOLVER_APP_KEY) is not None


def get_scope_resolver(app: Any) -> ScopeResolver:
    """``app["scope_resolver"]`` → ``app["ui_surfaces_scope_resolver"]`` → module default."""
    return _app_get(app, SCOPE_RESOLVER_APP_KEY) or _app_get(app, LEGACY_SCOPE_RESOLVER_APP_KEY) or _DEFAULT_RESOLVER


def normalize_visibility(value: Any) -> str:
    """Return ``value`` (str or enum with ``.value``) as a known visibility level; else ``"private"``."""
    raw = getattr(value, "value", value)
    if isinstance(raw, str) and raw in VISIBILITY_LEVELS:
        return raw
    return "private"


def scope_grants(*, tenant: str | None, visibility: str, allowed_groups: Iterable[str], scope: RequestScope) -> bool:
    """Pure grant rule; ignores ownership.

    Returns ``False`` when either tenant is ``None`` or they differ; otherwise
    ``True`` for superuser/administrator, ``tenant`` visibility, or ``groups``
    visibility with intersecting groups.
    """
    if scope.tenant is None or tenant is None or tenant != scope.tenant:
        return False
    if scope.is_superuser or scope.may_administer:
        return True
    level = normalize_visibility(visibility)
    if level == "tenant":
        return True
    if level == "groups":
        return bool(scope.groups & set(allowed_groups))
    return False
