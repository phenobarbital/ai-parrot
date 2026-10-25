"""Tenant + bearer resolution for FormDesigner serving (FEAT-734 M2). Pure functions, no I/O."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from botbuilder.core import TurnContext


class TenantUnresolved(Exception):
    """No tier yielded a FormDesigner tenant slug -- never guess one."""


class TenantResolution(BaseModel):
    """Which tenant won, and why -- logged on every fetch."""

    tenant: str
    source: Literal["aad_map", "session_aad_map", "config"]


class UserSessionLike(Protocol):
    """The subset of FEAT-729's MSTeamsUserSession (auth.py:45) this feature consumes."""

    authenticated: bool
    nav_session_token: str | None
    nav_user_id: str | None
    tenant_id: str | None  # AAD GUID -- NEVER a FormDesigner slug


class TeamsSessionStoreLike(Protocol):
    """The subset of MSTeamsSessionStore (auth.py:102) this feature may call.

    ``get_or_create`` is read-only and never exchanges (the ``_effective_user_id``
    precedent, wrapper.py:345). NEVER call MSTeamsAuthStrategy.ensure_authenticated()
    (auth.py:301): it may send a sign-in card as a side effect.
    """

    async def get_or_create(self, turn_context: "TurnContext") -> UserSessionLike: ...

    def is_expired(self, session: UserSessionLike) -> bool: ...


class LocalFormAuthorizer(Protocol):
    """Host adapter to the embedded app's authoritative membership policy (NEW contract).

    Missing adapter, rejection or lookup failure all deny. Neither the AAD map nor
    client-supplied tenant metadata proves membership.
    """

    async def require_membership(self, *, tenant: str, bearer_token: str, user_id: str) -> None:
        """Return only for an authorized principal; otherwise raise PermissionError."""
        ...


def resolve_form_tenant(
    *,
    asserted_tenant_id: str | None,
    session_tenant_id: str | None,
    tenant_map: dict[str, str] | None,
    config_tenant: str | None,
) -> TenantResolution:
    """Resolve the FormDesigner tenant using the required three-tier precedence.

    Args:
        asserted_tenant_id: AAD tenant GUID asserted by the current activity.
        session_tenant_id: AAD tenant GUID cached on the user's session.
        tenant_map: Mapping from AAD tenant GUIDs to FormDesigner tenant slugs.
        config_tenant: Last-resort FormDesigner tenant slug from bot config.

    Returns:
        The resolved tenant slug and the source tier that supplied it.

    Raises:
        TenantUnresolved: When no tier yields a slug.
    """
    mapping = tenant_map or {}
    if asserted_tenant_id is not None and asserted_tenant_id in mapping:
        return TenantResolution(tenant=mapping[asserted_tenant_id], source="aad_map")
    if session_tenant_id is not None and session_tenant_id in mapping:
        return TenantResolution(tenant=mapping[session_tenant_id], source="session_aad_map")
    if config_tenant:
        return TenantResolution(tenant=config_tenant, source="config")
    raise TenantUnresolved("No FormDesigner tenant could be resolved")


def resolve_bearer(session: UserSessionLike | None, *, expired: bool = False) -> str | None:
    """Return the authenticated, unexpired session bearer or ``None``.

    Args:
        session: User session containing the Navigator bearer, when available.
        expired: Whether the caller determined that the session has expired.

    Returns:
        The Navigator session token, or ``None`` when it is unsafe to use.
    """
    if session is None or expired or not getattr(session, "authenticated", False):
        return None
    token = getattr(session, "nav_session_token", None)
    return token or None
