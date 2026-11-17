"""Navigator principal for CLI surfaces (FEAT-774 M2): login file + GET /api/v1/connections/me."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Tuple

import aiohttp

from parrot.auth.oauth2.remote_client import NotLoggedIn, ServerConnectionsClient
from parrot.auth.permission import PermissionContext, build_principal_context
from parrot.auth.principal import Principal
from parrot.cli.login import LoginExpired, LoginFileError, LoginStore

logger = logging.getLogger(__name__)
CLI_CHANNELS = frozenset({"cli", "agentd"})
_FALLBACK_TENANT = "default"


class CliPrincipalResolver:
    """Satisfies FEAT-773 ``PrincipalResolver`` for ``cli`` / ``agentd``."""

    def __init__(self, store: LoginStore, client: ServerConnectionsClient) -> None:
        self.store = store
        self.client = client
        self.logger = logger

    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:
        """Resolve a CLI or agentd identity to its Navigator principal."""
        resolved = await self.resolve_with_roles(channel, channel_user_id)
        return resolved[0] if resolved else None

    async def resolve_with_roles(
        self,
        channel: str,
        channel_user_id: str,
    ) -> Optional[Tuple[Principal, frozenset[str]]]:
        """Return the principal and server-issued roles and scopes."""
        if channel not in CLI_CHANNELS:
            return None

        try:
            record = await asyncio.to_thread(self.store.load_optional)
        except LoginFileError as exc:
            self.logger.warning("Could not load the CLI login: %s", type(exc).__name__)
            return None
        if record is None:
            return None

        try:
            who = await self.client.me()
        except (NotLoggedIn, LoginExpired) as exc:
            self.logger.warning("Could not resolve the CLI principal: %s", type(exc).__name__)
            return None
        except (RuntimeError, aiohttp.ClientError, TimeoutError) as exc:
            self.logger.warning("Could not resolve the CLI principal: %s", type(exc).__name__)
            return None

        principal = Principal(
            user_id=who.user_id,
            canonical_identity=who.canonical_identity or who.email,
            tenant_id=who.tenant_id,
            channel=channel,
            channel_user_id=channel_user_id,
        )
        return principal, frozenset(who.roles) | frozenset(who.scopes)


def build_cli_permission_context(principal: Principal, *, roles: frozenset[str] = frozenset()) -> PermissionContext:
    """Build a permission context using the server tenant rather than the principal."""
    tenant = principal.tenant_id or _FALLBACK_TENANT
    if not principal.tenant_id:
        logger.debug("CLI principal has no server tenant; using %s", _FALLBACK_TENANT)
    return build_principal_context(principal.user_id, channel=principal.channel, tenant_id=tenant, roles=roles)
