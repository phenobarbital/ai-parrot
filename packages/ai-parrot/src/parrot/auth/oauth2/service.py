"""IntegrationsService — orchestration layer for the OAuth2 integration flows.

Provides four operations (list, start_connect, confirm_enable, disconnect) plus
``persist_credential()`` which is called from the web-channel OAuth2 callback
handler after a successful code exchange.

All origin validation is performed here (not in the handler) so that it is
covered by service-level unit tests.

PBAC convention
---------------
When the ``abac`` PDP is absent from the request (or when this service is called
without a request), the service fails **closed** for the integrations surface
(overrides the general fail-open convention in ``AgentTalk._check_pbac_agent_access``).
This was resolved as the correct behaviour for FEAT-144 Q-B.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from navconfig.logging import logging  # noqa: F811

from parrot.auth.oauth2 import _WEB_CHANNEL

if TYPE_CHECKING:  # pragma: no cover
    from parrot.auth.jira_oauth import JiraTokenSet
from parrot.auth.oauth2.models import (
    ConnectInitResponse,
    DisconnectResponse,
    IntegrationDescriptor,
    UserAgentToolkitRow,
    UsersIntegrationRow,
)
from parrot.auth.oauth2.persistence import (
    delete_user_agent_toolkits_by_provider,
    delete_users_integration,
    get_users_integration,
    list_user_agent_toolkits,
    upsert_user_agent_toolkit,
    upsert_users_integration,
)
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry

logger = logging.getLogger(__name__)


def _get_allowed_origins() -> List[str]:
    """Return the configured list of allowed OAuth2 return origins.

    Reads ``WEB_OAUTH_ALLOWED_ORIGINS`` from :mod:`parrot.conf`, which
    normalises the raw env-var into a ``list[str]`` at import time.

    Returns:
        List of origin strings, e.g. ``["https://app.example.com"]``.
    """
    from parrot.conf import WEB_OAUTH_ALLOWED_ORIGINS  # type: ignore[attr-defined]

    if isinstance(WEB_OAUTH_ALLOWED_ORIGINS, list):
        return list(WEB_OAUTH_ALLOWED_ORIGINS)
    if isinstance(WEB_OAUTH_ALLOWED_ORIGINS, str) and WEB_OAUTH_ALLOWED_ORIGINS:
        return [o.strip() for o in WEB_OAUTH_ALLOWED_ORIGINS.split(",") if o.strip()]
    return []


class IntegrationsService:
    """Orchestrates OAuth2 provider registry, persistence, and PBAC checks.

    All public methods are coroutines. Instantiate once per request: the
    service memoizes the ``VaultTokenSync`` used to probe stored tokens, so one
    listing loads each user's vault only once.

    Args:
        vault_token_sync: Optional pre-built token reader (tests / callers that
            already hold one).
    """

    def __init__(self, vault_token_sync: Any = None) -> None:
        self._vault_token_sync = vault_token_sync

    async def list_for_user(
        self,
        user_id: str,
        agent_id: str,
        request: Any = None,
    ) -> List[IntegrationDescriptor]:
        """Return a PBAC-filtered list of integration descriptors.

        For each registered provider, fetches whether the user has a connected
        credential (``users_integrations`` row) and whether it is enabled on
        this specific agent (``user_agent_toolkits`` row).

        Args:
            user_id: Navigator user identifier.
            agent_id: Agent identifier.
            request: Optional aiohttp request used for PBAC evaluation. When
                ``None`` or when ``abac`` is absent, the service fails closed
                and returns an empty list.

        Returns:
            List of :class:`~parrot.integrations.oauth2.models.IntegrationDescriptor`
            instances, one per allowed provider.
        """
        registry = OAuth2ProviderRegistry()
        providers = registry.all()

        # PBAC: fail-closed for integrations surface (Q-B resolution)
        if not await self._check_pbac(request, "integration:list"):
            logger.debug(
                "PBAC denied integration:list for user_id=%s — returning empty list",
                user_id,
            )
            return []

        # Fetch persistence state concurrently would be ideal; use sequential
        # for simplicity (N providers is small — typically 1 for v1).
        result: List[IntegrationDescriptor] = []
        enabled_toolkits = await list_user_agent_toolkits(user_id, agent_id)
        enabled_provider_ids = {row.provider for row in enabled_toolkits}

        for provider in providers:
            # Check whether a per-provider PBAC check passes
            if not await self._check_pbac(
                request, "integration:list", provider.provider_id
            ):
                continue

            integration_row = await get_users_integration(user_id, provider.provider_id)
            status = "disconnected"
            if integration_row is not None:
                status = await self._token_status(user_id, provider.provider_id, request)
            descriptor = IntegrationDescriptor(
                provider=provider.provider_id,
                display_name=provider.display_name,
                icon=provider.icon,
                default_scopes=provider.default_scopes,
                status=status,
                enabled_on_agent=provider.provider_id in enabled_provider_ids,
                account_id=integration_row.account_id if integration_row else None,
                display_account_name=(
                    integration_row.display_name if integration_row else None
                ),
                email=integration_row.email if integration_row else None,
                connected_at=integration_row.connected_at if integration_row else None,
            )
            result.append(descriptor)

        return result

    def _vault_sync(self, request: Any) -> Any:
        """One ``VaultTokenSync`` per request (loads each user's vault once).

        Returns:
            A ``VaultTokenSync`` bound to the app's pools, or ``None`` when the
            service/app cannot provide them.
        """
        if self._vault_token_sync is not None:
            return self._vault_token_sync
        app = getattr(request, "app", None)
        if app is None:
            return None
        try:
            from parrot.services.vault_token_sync import VaultTokenSync
        except ImportError:  # pragma: no cover - server package not installed
            return None
        db_pool = app.get("authdb")
        if db_pool is None:
            return None
        self._vault_token_sync = VaultTokenSync(db_pool=db_pool, redis=app.get("redis"))
        return self._vault_token_sync

    async def _token_status(self, user_id: str, provider_id: str, request: Any) -> str:
        """Status of a connected provider based on its stored vault tokens.

        A ``users_integrations`` row only says the user linked the provider; the
        tokens live in the Session Vault. When they are missing or fail the
        vault's integrity checks the UI must offer a re-connect instead of
        showing the integration as usable.

        Returns:
            ``"connected"`` or ``"needs_reconnect"``. Falls back to
            ``"connected"`` when the vault cannot be probed, so a vault outage
            never hides working integrations.
        """
        sync = self._vault_sync(request)
        if sync is None:
            return "connected"
        try:
            result = await sync.read_tokens_result(user_id, provider_id)
        except Exception:  # noqa: BLE001 - probing must never break the listing
            logger.warning(
                "Integrations: token probe failed for user=%s provider=%s",
                user_id, provider_id,
            )
            return "connected"
        if result.status in ("missing", "unreadable"):
            logger.info(
                "Integrations: provider=%s needs reconnect for user=%s (%s)",
                provider_id, user_id, result.status,
            )
            return "needs_reconnect"
        return "connected"

    async def start_connect(
        self,
        user_id: str,
        agent_id: str,
        provider_id: str,
        return_origin: str,
    ) -> ConnectInitResponse:
        """Validate the return origin and generate the OAuth2 authorization URL.

        Args:
            user_id: Navigator user identifier.
            agent_id: Agent identifier (embedded in ``extra_state`` for the
                callback handler to use during ``confirm_enable``).
            provider_id: Provider identifier, e.g. ``"jira"``.
            return_origin: The caller's ``window.location.origin``.  Must be in
                ``WEB_OAUTH_ALLOWED_ORIGINS``.

        Returns:
            :class:`~parrot.integrations.oauth2.models.ConnectInitResponse` with
            the authorization URL, opaque state nonce, and scopes.

        Raises:
            ValueError: If ``return_origin`` is not in the allowed origins list.
            ValueError: If ``provider_id`` is not registered.
        """
        allowed = _get_allowed_origins()
        if return_origin not in allowed:
            raise ValueError(
                f"Origin {return_origin!r} is not in the list of allowed OAuth2 "
                f"return origins.  Allowed: {allowed!r}"
            )

        registry = OAuth2ProviderRegistry()
        provider = registry.get(provider_id)
        if provider is None:
            raise ValueError(f"Unknown provider: {provider_id!r}")

        extra_state: Dict[str, Any] = {
            "channel": _WEB_CHANNEL,
            "provider_id": provider_id,
            "agent_id": agent_id,
            "return_origin": return_origin,
        }
        auth_url, nonce = await provider.manager.create_authorization_url(
            channel=_WEB_CHANNEL,
            user_id=user_id,
            extra_state=extra_state,
        )
        return ConnectInitResponse(
            auth_url=auth_url,
            state=nonce,
            scopes=provider.default_scopes,
            expires_in=600,
        )

    async def confirm_enable(
        self,
        user_id: str,
        agent_id: str,
        provider_id: str,
    ) -> IntegrationDescriptor:
        """Enable a connected integration on a specific agent.

        Requires that a ``users_integrations`` row already exists for
        ``(user_id, provider_id)`` (i.e. the OAuth callback completed
        successfully).  Upserts a ``user_agent_toolkits`` row.

        Args:
            user_id: Navigator user identifier.
            agent_id: Agent identifier.
            provider_id: Provider identifier, e.g. ``"jira"``.

        Returns:
            Updated :class:`~parrot.integrations.oauth2.models.IntegrationDescriptor`
            with ``connected=True`` and ``enabled_on_agent=True``.

        Raises:
            LookupError: If no ``users_integrations`` row exists for
                ``(user_id, provider_id)`` — the popup OAuth flow has not
                completed yet.
        """
        integration_row = await get_users_integration(user_id, provider_id)
        if integration_row is None:
            raise LookupError(
                f"No credential found for user_id={user_id!r} provider={provider_id!r}. "
                "Complete the OAuth2 popup flow before calling confirm_enable."
            )

        registry = OAuth2ProviderRegistry()
        provider = registry.get(provider_id)
        if provider is None:
            raise ValueError(f"Unknown provider: {provider_id!r}")

        toolkit_row = UserAgentToolkitRow(
            user_id=user_id,
            agent_id=agent_id,
            toolkit_id=provider_id,
            provider=provider_id,
            enabled_at=datetime.now(tz=timezone.utc),
        )
        await upsert_user_agent_toolkit(toolkit_row)

        return IntegrationDescriptor(
            provider=provider.provider_id,
            display_name=provider.display_name,
            icon=provider.icon,
            default_scopes=provider.default_scopes,
            connected=True,
            enabled_on_agent=True,
            account_id=integration_row.account_id,
            display_account_name=integration_row.display_name,
            email=integration_row.email,
            connected_at=integration_row.connected_at,
        )

    async def disconnect(
        self,
        user_id: str,
        agent_id: str,  # noqa: ARG002 — kept for API symmetry; cascade ignores agent
        provider_id: str,
    ) -> DisconnectResponse:
        """Disconnect a provider for a user.

        Deletes the ``users_integrations`` row AND cascade-deletes all
        ``user_agent_toolkits`` rows for ``(user_id, provider_id)`` regardless
        of ``agent_id``.  Idempotent — a second call is a no-op.

        Args:
            user_id: Navigator user identifier.
            agent_id: Agent identifier (present for API symmetry; the cascade
                deletes across ALL agents for this user+provider).
            provider_id: Provider identifier, e.g. ``"jira"``.

        Returns:
            :class:`~parrot.integrations.oauth2.models.DisconnectResponse` with
            ``disconnected=True``.
        """
        # Cascade-delete enablement rows first (foreign-key order)
        await delete_user_agent_toolkits_by_provider(user_id, provider_id)
        # Then delete the credential record
        await delete_users_integration(user_id, provider_id)

        logger.info(
            "Disconnected provider=%s for user_id=%s (all agents)",
            provider_id,
            user_id,
        )
        return DisconnectResponse(provider=provider_id, disconnected=True)

    async def persist_credential(
        self,
        user_id: str,
        provider_id: str,
        token_set: Any,
    ) -> UsersIntegrationRow:
        """Upsert a ``users_integrations`` row from any provider's token set.

        Called from the web-channel branch of both Jira and the generic
        OAuth2 callback after a successful authorization code exchange.

        Args:
            user_id: Navigator user identifier.
            provider_id: Provider identifier (``"jira"``, ``"o365"``, …).
            token_set: Provider-specific token set (duck-typed). Must
                expose ``account_id``, ``display_name``, ``email``,
                ``scopes``. Optional Jira-only fields (``cloud_id``,
                ``site_url``) are read with ``getattr`` and forwarded
                when present.

        Returns:
            The :class:`~parrot.integrations.oauth2.models.UsersIntegrationRow`
            that was persisted.
        """
        row = UsersIntegrationRow(
            user_id=user_id,
            provider=provider_id,
            channel=_WEB_CHANNEL,
            status="active",
            account_id=getattr(token_set, "account_id", "") or "",
            display_name=getattr(token_set, "display_name", "") or "",
            email=getattr(token_set, "email", None),
            scopes=list(getattr(token_set, "scopes", []) or []),
            cloud_id=getattr(token_set, "cloud_id", None),
            site_url=getattr(token_set, "site_url", None),
            connected_at=datetime.now(tz=timezone.utc),
        )
        await upsert_users_integration(row)
        logger.info(
            "Persisted credential for user_id=%s provider=%s account_id=%s",
            user_id,
            provider_id,
            row.account_id,
        )
        return row

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _check_pbac(
        self,
        request: Any,
        action: str,
        provider_id: Optional[str] = None,
    ) -> bool:
        """Evaluate a PBAC policy for the given action.

        Fails **closed** when the PDP is unavailable (FEAT-144 Q-B resolution).

        Args:
            request: The aiohttp request (may be ``None`` in tests).
            action: PBAC action string, e.g. ``"integration:list"``.
            provider_id: Optional provider identifier used as a context attribute
                on the EvalContext (not baked into the action string).

        Returns:
            ``True`` if the action is permitted, ``False`` otherwise.
        """
        if request is None:
            # No request context — fail-closed
            return False

        abac = getattr(request, "app", {}).get("abac") if hasattr(request, "app") else None
        if abac is None:
            # No PDP configured — fail-closed for integrations surface
            return False

        # If a full PBAC evaluator is present, use it.
        # Context: the provider_id is passed as an attribute, not baked into action.
        try:
            ctx: Dict[str, Any] = {"action": action}
            if provider_id:
                ctx["provider"] = provider_id
            result = await abac.is_allowed(request, ctx)
            return bool(result)
        except Exception:  # noqa: BLE001
            logger.exception(
                "PBAC evaluation failed for action=%s provider=%s — denying",
                action,
                provider_id,
            )
            return False
