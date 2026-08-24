"""Session-derived tenant resolver for the crew handler surface (FEAT-446).

Interim, PRIVATE helper (hence the leading underscore in the module name):
tenant identity for the crew handlers (`handler.py`, `execution_handler.py`,
`execution_history_handler.py`) must come from the authenticated session,
never from request body or query string (spec Goals G2/G3). S1
(FEAT-442 program, resolved question U1) will supersede this helper with
the core `TenantContext` + a per-route decorator; nothing outside
``handlers/crew/`` should import from this module.

Public API:
    - ``resolve_session_tenant``: Resolve the caller's tenant from their
      session, enforcing SaaS-mode fail-closed semantics and rejecting any
      client-declared tenant that conflicts with the resolved one.
"""
from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger(__name__)


def _saas_mode() -> bool:
    """Return the current ``PARROT_SAAS_MODE`` value.

    Reads the attribute off the ``parrot.conf`` module at call time (rather
    than binding it at import time) so tests can
    ``monkeypatch.setattr(parrot.conf, "PARROT_SAAS_MODE", True)`` and have
    the change observed immediately.

    Returns:
        The current boolean value of ``parrot.conf.PARROT_SAAS_MODE``.
    """
    from parrot import conf

    return conf.PARROT_SAAS_MODE


async def resolve_session_tenant(
    request: web.Request, *, declared: str | None = None
) -> str:
    """Resolve the caller's tenant from their authenticated session.

    Resolution order:
        1. Explicit ``tenant_id`` claim in the userinfo session dict.
        2. ``programs[0]`` (the formdesigner heuristic, generalized).
        3. No result.

    When no tenant can be resolved: ``PARROT_SAAS_MODE=true`` raises
    ``web.HTTPForbidden``; with the flag off, returns ``"global"`` for
    legacy single-tenant compatibility.

    ``declared`` — a tenant value the caller found in the request body or
    query string — is NEVER used as the source of truth. If provided and
    it differs from the resolved tenant, this raises ``web.HTTPBadRequest``
    (FEAT-421 ``assert_body_tenant_matches`` semantics). This function does
    not itself read the request body; callers extract ``declared`` and
    pass it in.

    Args:
        request: The incoming aiohttp request with a Guardian-populated
            session (or one resolvable via ``navigator_session.get_session``).
        declared: A tenant value the caller found in the request body or
            query string, for the compatibility check only. ``None`` skips
            the check.

    Returns:
        The resolved tenant slug (or ``"global"`` in legacy mode when
        unresolvable).

    Raises:
        web.HTTPForbidden: No tenant could be resolved and
            ``PARROT_SAAS_MODE`` is true.
        web.HTTPBadRequest: ``declared`` is not ``None`` and differs from
            the resolved tenant.
    """
    session = getattr(request, "session", None)
    if session is None:
        try:
            from navigator_session import get_session
            session = await get_session(request)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug(
                "_tenancy: could not retrieve session: %s", exc
            )
            session = None

    try:
        from navigator_auth.conf import (
            AUTH_SESSION_OBJECT as _AUTH_SESSION,
        )
    except ImportError:
        _AUTH_SESSION = "userinfo"

    userinfo = session.get(_AUTH_SESSION, {}) if session else {}
    if not isinstance(userinfo, dict):
        userinfo = {}

    resolved: str | None = userinfo.get("tenant_id") or None
    if not resolved:
        programs = userinfo.get("programs") or []
        if programs:
            resolved = programs[0]

    if not resolved:
        if _saas_mode():
            logger.warning(
                "_tenancy: no tenant could be resolved from session "
                "(PARROT_SAAS_MODE=true) — denying with 403."
            )
            raise web.HTTPForbidden(
                reason="Unable to resolve tenant from the authenticated session."
            )
        resolved = "global"

    if declared is not None and declared != resolved:
        logger.warning(
            "_tenancy: declared tenant '%s' conflicts with resolved tenant "
            "'%s' — rejecting with 400.",
            declared,
            resolved,
        )
        raise web.HTTPBadRequest(
            reason=(
                f"Declared tenant '{declared}' does not match the "
                f"authenticated session's tenant."
            )
        )

    return resolved
