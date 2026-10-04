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

from parrot.handlers.models.ui_surfaces import UISurfaceRecord
from parrot.handlers.scope import (
    EMPTY_SCOPE,
    RequestScope,
    ScopeResolver,
    SessionScopeResolver,
    get_scope_resolver,
)
from parrot.handlers.scope import scope_grants as _scope_grants

logger = logging.getLogger(__name__)

__all__ = [
    "EMPTY_SCOPE",
    "SessionSurfaceScopeResolver",
    "SurfaceScope",
    "SurfaceScopeResolver",
    "get_scope_resolver",
    "scope_grants",
]

# FEAT-605: the seam moved to ``parrot.handlers.scope``; FEAT-535 names are aliases.
SurfaceScope = RequestScope
SurfaceScopeResolver = ScopeResolver
SessionSurfaceScopeResolver = SessionScopeResolver


def scope_grants(record: UISurfaceRecord, scope: SurfaceScope) -> bool:
    """FEAT-535 adapter over :func:`parrot.handlers.scope.scope_grants` (signature unchanged).

    Pure — does NOT consider ownership.
    """
    return _scope_grants(
        tenant=record.tenant,
        visibility=getattr(record.visibility, "value", record.visibility),
        allowed_groups=record.allowed_groups,
        scope=scope,
    )
