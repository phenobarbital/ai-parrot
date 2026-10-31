"""Generic Teams connection commands (FEAT-775 M3): one guarded connector for commands and automatic offers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, List, Optional

from botbuilder.core import TurnContext

from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.permission import PermissionContext
from parrot.auth.principal import Principal
from parrot.integrations.msteams.connections import (
    MSTEAMS_CHANNEL,
    MSTeamsPrincipalSource,
    TeamsConnectState,
    build_msteams_permission_context,
    connect_card,
    connections_status_card,
    provider_picker_card,
    send_adaptive_card,
)

if TYPE_CHECKING:  # pragma: no cover
    from parrot.integrations.msteams.commands import MSTeamsCommandRouter

logger = logging.getLogger(__name__)

PERSONAL_ONLY = "Connections are personal — message me directly (1:1 chat) to manage them."
LOGIN_FIRST = "Please `/login` first, then try again."
AUTH_DISABLED = "Connections need Navigator sign-in; ask an operator to enable it."


@dataclass(frozen=True)
class TeamsGuard:
    """A turn that passed the personal and live-principal guard."""

    principal: Principal
    context: PermissionContext


class TeamsConnector:
    """Principal and service calls plus cards, shared by commands and automatic needs-auth offers."""

    def __init__(
        self,
        *,
        principal_source: MSTeamsPrincipalSource,
        service_factory: Callable[[], Any],
        provider_ids: Callable[[], List[str]],
        bot_app_id: str,
        auth_enabled: bool,
    ) -> None:
        self._principals = principal_source
        self._service_factory = service_factory
        self._provider_ids = provider_ids
        self._bot_app_id = bot_app_id
        self._auth_enabled = auth_enabled

    async def require_guard(self, turn_context: TurnContext) -> Optional[TeamsGuard]:
        """Return a personal turn's trusted principal/context, otherwise reply once."""
        conversation = getattr(turn_context.activity, "conversation", None)
        if getattr(conversation, "conversation_type", None) != "personal":
            await turn_context.send_activity(PERSONAL_ONLY)
            return None
        if not self._auth_enabled:
            await turn_context.send_activity(AUTH_DISABLED)
            return None
        session = await self._principals.session_for_turn(turn_context)
        if session is None:
            await turn_context.send_activity(LOGIN_FIRST)
            return None
        principal = await self._principals.principal_for_turn(turn_context)
        if principal is None:
            await turn_context.send_activity(LOGIN_FIRST)
            return None
        return TeamsGuard(principal=principal, context=build_msteams_permission_context(session))

    async def require_personal_principal(self, turn_context: TurnContext) -> Optional[Principal]:
        """Return only the principal after applying the shared guard."""
        guard = await self.require_guard(turn_context)
        return guard.principal if guard else None

    def _state(self, turn_context: TurnContext) -> dict[str, Any]:
        """Return a serialized conversation reference and issuing bot app id."""
        reference = TurnContext.get_conversation_reference(turn_context.activity)
        return TeamsConnectState(
            conversation_reference=json.loads(json.dumps(reference.serialize())),
            bot_app_id=self._bot_app_id,
        ).model_dump()

    async def connect(self, turn_context: TurnContext, provider_id: str, *, scopes: Optional[List[str]] = None) -> None:
        """Apply the guard and start or report a provider connection."""
        guard = await self.require_guard(turn_context)
        if guard is not None:
            await self.connect_guarded(turn_context, guard, provider_id, scopes=scopes)

    async def connect_guarded(
        self, turn_context: TurnContext, guard: TeamsGuard, provider_id: str, *, scopes: Optional[List[str]] = None
    ) -> None:
        """Report a sufficient grant or mint a Teams-state connect card."""
        provider = OAuth2ProviderRegistry().get(provider_id)
        if provider is None:
            await turn_context.send_activity(f"Unknown provider '{provider_id}'. Try `/connect` to see the list.")
            return
        requested = sorted(set(scopes or [])) or list(provider.default_scopes)
        service = self._service_factory()
        principal, context = guard.principal, guard.context
        try:
            descriptor = await self._status_with_legacy(service, provider, principal, context)
            if descriptor.status == "connected" and set(requested) <= set(descriptor.scopes_granted):
                account = descriptor.display_account_name or "your account"
                await turn_context.send_activity(f"{provider.display_name} is already connected as **{account}**.")
                return
            response = await service.start_connect(
                principal.user_id,
                provider_id,
                channel=MSTEAMS_CHANNEL,
                principal=principal,
                scopes=requested,
                permission_context=context,
                extra_state=self._state(turn_context),
            )
            await send_adaptive_card(turn_context, connect_card(provider.display_name, response.auth_url))
        except PermissionError:
            await turn_context.send_activity(f"You're not allowed to use {provider.display_name} connections.")

    async def _status_with_legacy(
        self, service: Any, provider: Any, principal: Principal, context: PermissionContext
    ) -> Any:
        """Return status, migrating a valid legacy token into a connection row when needed."""
        descriptor = await service.status(
            principal.user_id,
            provider.provider_id,
            principal=principal,
            permission_context=context,
        )
        if descriptor.status != "disconnected":
            return descriptor
        token = await provider.manager.get_valid_token(
            MSTEAMS_CHANNEL,
            principal.user_id,
            channel_user_id=principal.channel_user_id,
        )
        if token is None:
            return descriptor
        await service.persist_credential(
            principal.user_id,
            provider.provider_id,
            token,
            channel=MSTEAMS_CHANNEL,
            canonical_identity=principal.canonical_identity,
        )
        return await service.status(
            principal.user_id,
            provider.provider_id,
            principal=principal,
            permission_context=context,
        )

    async def disconnect(self, turn_context: TurnContext, provider_id: str) -> None:
        """Disconnect a provider using the Teams channel identity."""
        guard = await self.require_guard(turn_context)
        if guard is None:
            return
        provider = OAuth2ProviderRegistry().get(provider_id)
        if provider is None:
            await turn_context.send_activity(f"Unknown provider '{provider_id}'. Try `/connect` to see the list.")
            return
        try:
            await self._service_factory().disconnect(
                guard.principal.user_id,
                provider_id,
                channel=MSTEAMS_CHANNEL,
                principal=guard.principal,
                permission_context=guard.context,
            )
            await turn_context.send_activity(f"{provider.display_name} disconnected.")
        except PermissionError:
            await turn_context.send_activity(f"You're not allowed to use {provider.display_name} connections.")

    async def status(self, turn_context: TurnContext, provider_id: Optional[str] = None) -> None:
        """Send a status card for one provider or every permitted provider."""
        guard = await self.require_guard(turn_context)
        if guard is None:
            return
        service = self._service_factory()
        try:
            if provider_id is None:
                rows = await service.list_for_principal(
                    guard.principal.user_id,
                    principal=guard.principal,
                    permission_context=guard.context,
                )
            else:
                provider = OAuth2ProviderRegistry().get(provider_id)
                if provider is None:
                    await turn_context.send_activity(
                        f"Unknown provider '{provider_id}'. Try `/connect` to see the list."
                    )
                    return
                rows = [await self._status_with_legacy(service, provider, guard.principal, guard.context)]
            await send_adaptive_card(turn_context, connections_status_card(rows))
        except PermissionError:
            provider = OAuth2ProviderRegistry().get(provider_id) if provider_id else None
            name = provider.display_name if provider is not None else "these"
            await turn_context.send_activity(f"You're not allowed to use {name} connections.")

    async def pick_provider(self, turn_context: TurnContext) -> None:
        """Send the picker card for configured provider ids after the shared guard."""
        guard = await self.require_guard(turn_context)
        if guard is None:
            return
        providers = []
        for provider_id in self._provider_ids():
            provider = OAuth2ProviderRegistry().get(provider_id)
            if provider is not None:
                providers.append((provider_id, provider.display_name))
        await send_adaptive_card(turn_context, provider_picker_card(providers))


def register_connection_commands(router: "MSTeamsCommandRouter", *, connector: TeamsConnector) -> None:
    """Register generic Teams connection commands and legacy Jira aliases."""
    from parrot.integrations.msteams.commands import command_args
    from parrot.integrations.msteams.commands.jira_commands import register_jira_commands

    def _first_arg(turn_context: TurnContext) -> str:
        parts = command_args(turn_context).split()
        return parts[0].lower() if parts else ""

    async def _connect(turn_context: TurnContext) -> None:
        provider_id = _first_arg(turn_context)
        if provider_id:
            await connector.connect(turn_context, provider_id)
        else:
            await connector.pick_provider(turn_context)

    async def _disconnect(turn_context: TurnContext) -> None:
        provider_id = _first_arg(turn_context)
        if not provider_id:
            await turn_context.send_activity("Usage: `/disconnect <provider>`")
            return
        await connector.disconnect(turn_context, provider_id)

    async def _connections(turn_context: TurnContext) -> None:
        await connector.status(turn_context, _first_arg(turn_context) or None)

    router.register("connect", _connect)
    router.register("disconnect", _disconnect)
    router.register("connections", _connections)
    register_jira_commands(router, connector)
    logger.info("Registered Teams connection commands")
