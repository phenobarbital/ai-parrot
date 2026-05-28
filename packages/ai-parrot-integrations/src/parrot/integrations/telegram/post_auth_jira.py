"""Jira implementation of the ``PostAuthProvider`` protocol.

Wraps :class:`parrot.auth.jira_oauth.JiraOAuthManager` to participate in
the combined Telegram auth flow:

1. ``build_auth_url`` asks the manager for an Atlassian consent URL and
   stashes the primary BasicAuth payload inside the CSRF nonce's
   ``extra_state`` so it can be reunited with the Jira code at the
   combined callback.
2. ``handle_result`` exchanges the Jira code for tokens (via
   :meth:`JiraOAuthManager.handle_callback`, which already writes to
   Redis), then additionally persists the tokens in the user's Vault
   (:class:`VaultTokenSync`) and creates identity-mapping rows in
   ``auth.user_identities`` (:class:`IdentityMappingService`) for both
   the Telegram and Jira providers.

Vault and identity-mapping failures are logged but do NOT fail the auth
— Redis is the primary store and the flow must stay resilient.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

from parrot.integrations.telegram.jira_commands import _TELEGRAM_CHANNEL

if TYPE_CHECKING:
    from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet
    from parrot.integrations.telegram.auth import TelegramUserSession
    from parrot.integrations.telegram.models import TelegramAgentConfig
    from parrot.services.identity_mapping import IdentityMappingService
    from parrot.services.vault_token_sync import VaultTokenSync

logger = logging.getLogger(__name__)


class JiraPostAuthProvider:
    """Secondary auth provider for Atlassian Jira (OAuth2 3LO).

    Args:
        oauth_manager: Pre-configured :class:`JiraOAuthManager` (typically
            obtained from ``app["jira_oauth_manager"]``).
        identity_service: :class:`IdentityMappingService` for writing
            ``auth.user_identities`` rows.
        vault_sync: :class:`VaultTokenSync` for encrypted token persistence.
    """

    provider_name = "jira"

    def __init__(
        self,
        oauth_manager: "JiraOAuthManager",
        identity_service: "IdentityMappingService",
        vault_sync: "VaultTokenSync",
    ) -> None:
        self._oauth = oauth_manager
        self._identity = identity_service
        self._vault = vault_sync
        self.logger = logger

    # -------------------------------------------------------------- URL

    async def build_auth_url(
        self,
        session: "TelegramUserSession",
        config: "TelegramAgentConfig",
        callback_base_url: str,
    ) -> str:
        """Return a Jira authorization URL with BasicAuth state embedded.

        The BasicAuth context (``nav_user_id``, ``nav_display_name``,
        ``nav_email``, ``telegram_id``, ``telegram_username``) is stashed
        inside ``extra_state`` so the combined callback handler can
        retrieve it when the user returns from Atlassian.

        Args:
            session: Current Telegram user session (may or may not be
                authenticated yet — both are fine).
            config: Telegram agent config (unused today, reserved for
                per-agent overrides).
            callback_base_url: Public base URL the callback is mounted at
                (accepted for interface symmetry; the actual redirect URI
                configured on the manager already points at the combined
                callback).

        Returns:
            Atlassian authorization URL.
        """
        extra_state: Dict[str, Any] = {
            "flow": "combined",
            "telegram_id": session.telegram_id,
            "telegram_username": session.telegram_username,
            "callback_base_url": callback_base_url,
        }
        # Include already-known primary auth details if present — they'll be
        # echoed back in the callback for the wrapper to re-apply.
        if getattr(session, "nav_user_id", None):
            extra_state["nav_user_id"] = session.nav_user_id
        if getattr(session, "nav_display_name", None):
            extra_state["nav_display_name"] = session.nav_display_name
        if getattr(session, "nav_email", None):
            extra_state["nav_email"] = session.nav_email

        url, nonce = await self._oauth.create_authorization_url(
            channel=_TELEGRAM_CHANNEL,
            user_id=str(session.telegram_id),
            extra_state=extra_state,
        )
        self.logger.info(
            "JiraPostAuthProvider: built auth URL for telegram_id=%s nonce=%s…",
            session.telegram_id,
            (nonce[:8] if len(nonce) > 8 else nonce),
        )
        return url

    # -------------------------------------------------------------- callback

    async def handle_result(
        self,
        data: Dict[str, Any],
        session: "TelegramUserSession",
        primary_auth_data: Dict[str, Any],
    ) -> bool:
        """Exchange the Jira code and persist tokens + identities.

        Args:
            data: ``{"code": ..., "state": ...}`` extracted from the
                combined ``WebApp.sendData`` payload.
            session: Telegram user session (already authenticated by the
                primary handler).
            primary_auth_data: Payload from the primary (BasicAuth) step —
                may include ``user_id`` / ``token`` / ``display_name`` /
                ``email``.

        Returns:
            True on a clean exchange, False if the OAuth step fails. Vault
            and identity-mapping failures are logged but still return True
            because the core auth (Redis token) succeeded.
        """
        code = data.get("code")
        state = data.get("state")
        if not code or not state:
            self.logger.warning(
                "JiraPostAuthProvider.handle_result: missing code/state "
                "(code=%s state=%s)",
                bool(code),
                bool(state),
            )
            return False

        try:
            token_set, state_payload = await self._oauth.handle_callback(
                code, state
            )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "JiraPostAuthProvider: Jira handle_callback failed"
            )
            return False

        # Resolve the navigator user_id: prefer the one carried in the
        # primary auth payload; fall back to extra_state, then session.
        extra = (state_payload or {}).get("extra") or {}
        nav_user_id = (
            primary_auth_data.get("user_id")
            or primary_auth_data.get("nav_user_id")
            or extra.get("nav_user_id")
            or session.nav_user_id
        )

        # Best-effort Vault write. The JiraOAuthManager already wrote to Redis.
        await self._store_in_vault(nav_user_id, token_set)

        # Best-effort identity mappings (Telegram + Jira).
        await self._write_identity_records(
            nav_user_id=nav_user_id,
            token_set=token_set,
            session=session,
            primary_auth_data=primary_auth_data,
        )

        # Surface the Jira identity on the Telegram session so prompt
        # enrichment and tool context use the connected Jira account
        # instead of the primary Navigator login email.
        try:
            session.set_jira_authenticated(
                account_id=token_set.account_id,
                email=token_set.email,
                display_name=token_set.display_name,
                cloud_id=token_set.cloud_id,
            )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "JiraPostAuthProvider: failed to stamp jira identity on session"
            )

        self.logger.info(
            "JiraPostAuthProvider: combined auth complete "
            "(nav_user_id=%s jira_account=%s jira_email=%s)",
            nav_user_id,
            token_set.account_id,
            token_set.email,
        )
        return True

    # ---------------------------------------------------------- helpers

    async def _store_in_vault(
        self,
        nav_user_id: Optional[str],
        token_set: "JiraTokenSet",
    ) -> None:
        """Write the Jira token fields as flat keys in the user's vault."""
        if not nav_user_id:
            self.logger.warning(
                "JiraPostAuthProvider: no nav_user_id — skipping vault write"
            )
            return
        tokens: Dict[str, Any] = {
            "access_token": token_set.access_token,
            "refresh_token": token_set.refresh_token,
            "cloud_id": token_set.cloud_id,
            "site_url": token_set.site_url,
            "account_id": token_set.account_id,
        }
        try:
            await self._vault.store_tokens(
                nav_user_id=str(nav_user_id),
                provider=self.provider_name,
                tokens=tokens,
            )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "JiraPostAuthProvider: vault store failed "
                "(nav_user_id=%s)",
                nav_user_id,
            )

    async def _write_identity_records(
        self,
        nav_user_id: Optional[str],
        token_set: "JiraTokenSet",
        session: "TelegramUserSession",
        primary_auth_data: Dict[str, Any],
    ) -> None:
        """Upsert ``telegram`` and ``jira`` identities for ``nav_user_id``."""
        if not nav_user_id:
            self.logger.warning(
                "JiraPostAuthProvider: no nav_user_id — skipping identity mapping"
            )
            return
        # Telegram identity
        try:
            await self._identity.upsert_identity(
                nav_user_id=str(nav_user_id),
                auth_provider="telegram",
                auth_data={
                    "telegram_id": session.telegram_id,
                    "username": session.telegram_username,
                },
                display_name=primary_auth_data.get("display_name"),
                email=primary_auth_data.get("email"),
            )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "JiraPostAuthProvider: telegram identity upsert failed"
            )

        # Jira identity
        try:
            await self._identity.upsert_identity(
                nav_user_id=str(nav_user_id),
                auth_provider=self.provider_name,
                auth_data={
                    "account_id": token_set.account_id,
                    "cloud_id": token_set.cloud_id,
                    "site_url": token_set.site_url,
                    "display_name": token_set.display_name,
                },
                display_name=token_set.display_name,
                email=token_set.email,
            )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "JiraPostAuthProvider: jira identity upsert failed"
            )
