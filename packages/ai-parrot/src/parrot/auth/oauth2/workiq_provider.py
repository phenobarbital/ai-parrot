"""Work IQ OAuth2 provider with Entra On-Behalf-Of (OBO) token exchange.

OQ#5 resolved (2026-06-27 — FEAT-263 / TASK-1649):
Work IQ (``github.com/microsoft/work-iq``) is an **MCP server** that supports
delegated Entra OBO authentication.  App-only access is NOT supported.

Required permission: ``WorkIQAgent.Ask`` (delegated, requires admin consent).
OAuth scope: ``api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask``.

Work IQ applies M365 permissions, sensitivity labels, and compliance policies
automatically — no additional filtering is required on the adapter side.

OBO flow:
1. User signs in via the o365 / Entra 3LO flow (covered by the existing
   ``O365OAuth2Provider``).  The Entra access token is stored in vault as
   ``o365:access_token``.
2. :class:`WorkIQOBOCredentialResolver` calls
   ``O365Interface.acquire_token_on_behalf_of(user_assertion, scopes)`` to
   exchange the Entra token for a Work IQ OBO token.
3. The OBO token is cached in vault as ``workiq:access_token`` and returned
   to the A2A bridge for use with the Work IQ MCP server.

One Entra sign-in covers both o365 and work-iq.

Registration::

    from parrot.auth.oauth2.workiq_provider import WorkIQOAuth2Provider
    from parrot.auth.oauth2.registry import register_oauth2_provider
    from parrot.interfaces.o365 import O365Interface

    o365 = O365Interface(credentials={...})
    provider = WorkIQOAuth2Provider(
        o365_interface=o365,
        o365_oauth_manager=o365_manager,
        vault_token_sync=vault,
    )
    register_oauth2_provider(provider)
    a2a_server.wire_workiq_resolver(provider.credential_resolver())
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from parrot.auth.credentials import CredentialResolver
from parrot.auth.oauth2.registry import OAuth2Provider

if TYPE_CHECKING:  # pragma: no cover
    from parrot.interfaces.o365 import O365Interface

logger = logging.getLogger(__name__)

#: Delegated OBO scope required for Work IQ MCP server access.
WORKIQ_SCOPE: str = "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"

#: Provider identifier used throughout the bridge and registry.
WORKIQ_PROVIDER_ID: str = "workiq"

#: Vault provider prefix for Work IQ OBO tokens.
_WORKIQ_VAULT_PREFIX: str = "workiq"

#: Vault provider prefix for the source Entra (o365) token used in OBO.
_O365_VAULT_PREFIX: str = "o365"


class WorkIQOBOCredentialResolver(CredentialResolver):
    """Credential resolver that exchanges an Entra assertion for a Work IQ OBO token.

    Implements the :class:`~parrot.auth.credentials.CredentialResolver` contract
    so the A2A bridge (FEAT-263 / TASK-1644) can gate any tool declaring
    ``credential_provider = "workiq"`` through this OBO flow.

    Resolution steps:

    1. Check vault for a cached ``workiq:access_token`` for *user_id*.
    2. If absent, look for the user's Entra token (``o365:access_token`` in vault).
    3. If the Entra token exists, call
       :meth:`O365Interface.acquire_token_on_behalf_of` with the Work IQ scope,
       cache the result as ``workiq:access_token``, and return the token.
    4. If neither is available, return ``None`` — the bridge will surface the
       Entra sign-in link from :meth:`get_auth_url`.

    Args:
        o365_interface: A configured
            :class:`~parrot.interfaces.o365.O365Interface` instance used for
            the OBO token exchange.
        o365_oauth_manager: The application-level O365 OAuth manager (must
            expose ``create_authorization_url(channel, user_id)``).
        vault_token_sync: A configured
            :class:`~parrot.services.vault_token_sync.VaultTokenSync` instance
            used for reading and writing per-user tokens.
        workiq_scope: The delegated OBO scope (default:
            ``api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask``).
    """

    def __init__(
        self,
        o365_interface: "O365Interface",
        o365_oauth_manager: Any,
        vault_token_sync: Any,
        workiq_scope: str = WORKIQ_SCOPE,
    ) -> None:
        self._o365 = o365_interface
        self._o365_manager = o365_oauth_manager
        self._vault = vault_token_sync
        self._scope = workiq_scope

    async def resolve(self, channel: str, user_id: str) -> Optional[str]:
        """Return the per-user Work IQ OBO access token, or ``None``.

        On the first call (no cached token) the method attempts an automatic
        OBO exchange using the user's stored Entra token.  The result is
        cached in vault so subsequent calls avoid round-trips.

        Returns ``None`` when:
        - No cached Work IQ token and no Entra token are in vault (user must
          complete the Entra sign-in surfaced via :meth:`get_auth_url`).
        - The OBO exchange fails (logs an exception; returns ``None`` so the
          bridge suspends the task and surfaces a retry link).

        Args:
            channel: A2A channel string (e.g. ``"a2a:copilot"``).
            user_id: Canonical per-user identity (email / OID).

        Returns:
            The Work IQ OBO access token as a plain string, or ``None``.
        """
        # 1. Check vault for a cached Work IQ OBO token.
        workiq_tokens: Optional[Dict[str, Any]] = await self._vault.read_tokens(
            user_id, _WORKIQ_VAULT_PREFIX
        )
        if workiq_tokens and (token := workiq_tokens.get("access_token")):
            logger.debug(
                "WorkIQOBOCredentialResolver: cached OBO token found for user=%s",
                user_id,
            )
            return str(token)

        # 2. Try to exchange via OBO using the user's Entra token.
        entra_tokens: Optional[Dict[str, Any]] = await self._vault.read_tokens(
            user_id, _O365_VAULT_PREFIX
        )
        if not entra_tokens or "access_token" not in entra_tokens:
            logger.debug(
                "WorkIQOBOCredentialResolver: no Entra token in vault for user=%s;"
                " OBO exchange unavailable — Entra sign-in required",
                user_id,
            )
            return None

        # 3. Perform the OBO exchange.
        try:
            result: Dict[str, Any] = self._o365.acquire_token_on_behalf_of(
                user_assertion=entra_tokens["access_token"],
                scopes=[self._scope],
            )
            access_token: Optional[str] = result.get("access_token")
            if not access_token:
                logger.warning(
                    "WorkIQOBOCredentialResolver: OBO exchange returned no access_token"
                    " for user=%s",
                    user_id,
                )
                return None

            # Cache the Work IQ OBO token so subsequent calls skip OBO.
            await self._vault.store_tokens(
                user_id,
                _WORKIQ_VAULT_PREFIX,
                {"access_token": access_token},
            )
            logger.info(
                "WorkIQOBOCredentialResolver: OBO token obtained and cached for user=%s",
                user_id,
            )
            return access_token

        except Exception:
            logger.exception(
                "WorkIQOBOCredentialResolver: OBO exchange failed for user=%s", user_id
            )
            return None

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """Return the Entra sign-in URL for the O365 delegated flow.

        Work IQ shares the Entra identity with o365: one sign-in covers both.
        After the user completes the Entra sign-in, the Entra access token is
        stored in vault and the next :meth:`resolve` call performs the OBO
        exchange automatically.

        Args:
            channel: A2A channel string.
            user_id: Canonical per-user identity.

        Returns:
            The Entra / Azure AD authorization URL.
        """
        url, _ = await self._o365_manager.create_authorization_url(channel, user_id)
        return url


class WorkIQOAuth2Provider(OAuth2Provider):
    """OAuth2 provider for Work IQ (Microsoft) — Entra delegated OBO flow.

    Work IQ is an MCP-based Microsoft enterprise assistant that applies M365
    permissions, sensitivity labels, and compliance policies automatically.
    Access requires admin consent for
    ``api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask``.

    This provider is a thin wrapper that:
    - Carries Work IQ provider metadata (``provider_id``, ``display_name``,
      ``default_scopes``) for the :class:`~parrot.auth.oauth2.registry.OAuth2ProviderRegistry`.
    - Holds a pre-built :class:`WorkIQOBOCredentialResolver` returned by
      :meth:`credential_resolver`.

    Registration::

        register_oauth2_provider(WorkIQOAuth2Provider(...))
        a2a_server.wire_workiq_resolver(provider.credential_resolver())

    Attributes:
        provider_id: Always ``"workiq"``.
        display_name: ``"Work IQ"``.
        icon: Material Design Icon key ``"mdi:microsoft"``.
        default_scopes: Work IQ delegated OBO scope list.
        pbac_action_namespace: ``"integration"``.
    """

    provider_id: str = WORKIQ_PROVIDER_ID
    display_name: str = "Work IQ"
    icon: str = "mdi:microsoft"
    default_scopes: List[str] = [WORKIQ_SCOPE]
    pbac_action_namespace: str = "integration"

    def __init__(
        self,
        o365_interface: "O365Interface",
        o365_oauth_manager: Any,
        vault_token_sync: Any,
        workiq_scope: str = WORKIQ_SCOPE,
    ) -> None:
        """Initialise the Work IQ OAuth2 provider.

        Args:
            o365_interface: Configured :class:`~parrot.interfaces.o365.O365Interface`
                for OBO token exchange.
            o365_oauth_manager: Application-level O365 OAuth manager (used for
                :meth:`get_auth_url` → Entra sign-in URL).
            vault_token_sync: Configured
                :class:`~parrot.services.vault_token_sync.VaultTokenSync` for
                per-user token persistence.
            workiq_scope: OBO scope override (default:
                ``api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask``).
        """
        self._o365 = o365_interface
        self._o365_manager = o365_oauth_manager
        self._vault = vault_token_sync
        self._resolver = WorkIQOBOCredentialResolver(
            o365_interface=o365_interface,
            o365_oauth_manager=o365_oauth_manager,
            vault_token_sync=vault_token_sync,
            workiq_scope=workiq_scope,
        )

    @property
    def manager(self) -> Any:
        """Return the underlying O365 OAuth manager.

        Returns:
            The o365 OAuth manager passed at construction time.
        """
        return self._o365_manager

    def credential_resolver(self) -> WorkIQOBOCredentialResolver:
        """Return the pre-built :class:`WorkIQOBOCredentialResolver`.

        Use this to wire the Work IQ resolver into the A2A bridge::

            a2a_server.wire_workiq_resolver(provider.credential_resolver())

        Returns:
            The configured :class:`WorkIQOBOCredentialResolver` instance.
        """
        return self._resolver

    def toolkit_factory(self, credential_resolver: Any) -> Any:
        """Not implemented — Work IQ is MCP-based, no native toolkit.

        Raises:
            NotImplementedError: Always. Use the MCP transport layer instead.
        """
        raise NotImplementedError(
            "WorkIQ is MCP-based; route calls through the Work IQ MCP server "
            "using the OBO token from WorkIQOBOCredentialResolver."
        )
