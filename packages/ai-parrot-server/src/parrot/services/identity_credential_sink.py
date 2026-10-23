"""
IdentityVaultCredentialSink — keep navigator-auth's Identity Vault in step
with the Redis hot cache for Jira grants (FEAT-735).

One Atlassian 3LO grant used to live in three unsynchronised places: Redis
(the live tool read path), the Session Vault (``auth.user_vault_secrets``,
written once and never refreshed) and the Identity Vault
(``auth.user_identities``, written once by the Telegram login). FEAT-735 named
the **Identity Vault** the durable owner; this sink is how
:class:`parrot.auth.jira_oauth.JiraOAuthManager` keeps it current without
importing the server package — it satisfies that module's ``CredentialSink``
Protocol structurally.

See ``docs/auth/jira-credential-ownership.md``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict


class IdentityVaultCredentialSink:
    """``CredentialSink`` backed by navigator-auth's Identity Vault.

    Args:
        db_pool: The asyncdb ``authdb`` pool (``app['authdb']``) — not a raw
            asyncpg pool: :class:`IdentityStore` acquires it with
            ``async with await pool.acquire()``.
        provider: The identity provider these grants belong to.
    """

    def __init__(self, db_pool: Any, provider: str = "jira") -> None:
        self._db_pool = db_pool
        self._provider = provider
        self.logger = logging.getLogger(__name__)

    def _store(self) -> Any:
        """Build an :class:`IdentityStore` over the configured pool."""
        from navigator_auth.identity.store import IdentityStore

        return IdentityStore(self._db_pool)

    def _as_token_response(self, token: Any) -> Any:
        """Map a ``JiraTokenSet`` onto navigator-auth's ``TokenResponse``."""
        from navigator_auth.identity.types import TokenResponse

        raw_expiry = getattr(token, "expires_at", None)
        expires_at = (
            datetime.fromtimestamp(float(raw_expiry), tz=timezone.utc)
            if isinstance(raw_expiry, (int, float)) and raw_expiry
            else None
        )
        return TokenResponse(
            access_token=token.access_token,
            refresh_token=getattr(token, "refresh_token", None) or None,
            expires_at=expires_at,
            scopes=list(getattr(token, "scopes", None) or []),
            provider_user_id=token.account_id,
            raw={"cloud_id": token.cloud_id, "site_url": token.site_url},
        )

    async def persist_minted(
        self,
        channel: str,
        user_id: str,
        token: Any,
        state_payload: Dict[str, Any],
    ) -> None:
        """Seal a newly minted grant on the owner's identity row.

        Unlike :meth:`persist`, link time *has* ``userinfo`` — account id,
        cloud id, site url, display name — so this is the full
        ``save_linked_identity`` write, and it is the call that creates the
        row on a first link.

        The Navigator user is resolved in this order:

        1. ``state_payload["extra"]["nav_user_id"]`` — the combined Telegram
           login is the only flow that carries it today;
        2. the Atlassian account's existing row, for a re-link;
        3. neither — a logged no-op.

        Case 3 is real: the Slack and MS Teams authorize states carry a
        channel id, not a Navigator one, so a first-ever link from those
        channels has no owner to attach the credential to. Guessing one is
        what put a composite ``team:user`` string and an AAD GUID into a
        ``bigint`` column before.
        """
        account_id = getattr(token, "account_id", None)
        extra = (state_payload or {}).get("extra") or {}
        nav_user_id = extra.get("nav_user_id")
        if not nav_user_id and account_id:
            nav_user_id = await self._store().find_user_by_provider_account(self._provider, account_id)
        if not nav_user_id:
            self.logger.warning(
                "Jira credential sink: link for %s:%s carries no Navigator user and "
                "account %s owns no identity row — durable copy skipped",
                channel,
                user_id,
                account_id or "<none>",
            )
            return
        await self._store().save_linked_identity(
            user_id=nav_user_id,
            provider=self._provider,
            token=self._as_token_response(token),
            userinfo={
                "account_id": account_id,
                "cloud_id": getattr(token, "cloud_id", None),
                "site_url": getattr(token, "site_url", None),
                "display_name": getattr(token, "display_name", None),
                "email": getattr(token, "email", None),
            },
        )
        self.logger.info(
            "Jira credential sink: minted grant sealed for user %s (account %s)",
            nav_user_id,
            account_id,
        )

    async def persist(self, channel: str, user_id: str, token: Any) -> None:
        """Re-seal a rotated grant on the owner's identity row.

        The manager only knows the *channel's* user id (a Telegram id, an AAD
        object id), so the Navigator user is resolved from the Atlassian
        account id instead — the one key both sides hold.

        Uses ``update_tokens``, never ``save_linked_identity``: the latter
        rewrites ``auth_data`` from its ``userinfo`` argument, which on a
        refresh (no userinfo) would wipe ``account_id`` / ``cloud_id`` /
        ``site_url`` off the row.

        An account with no identity row is a logged no-op — a user who linked
        Jira before FEAT-729 has no row to update, and inventing one here
        would write a credential nobody can attribute.
        """
        store = self._store()
        account_id = getattr(token, "account_id", None)
        if not account_id:
            self.logger.warning(
                "Jira credential sink: refreshed grant for %s:%s carries no account id",
                channel,
                user_id,
            )
            return
        nav_user_id = await store.find_user_by_provider_account(self._provider, account_id)
        if not nav_user_id:
            self.logger.warning(
                "Jira credential sink: account %s owns no identity row — " "durable copy not updated for %s:%s",
                account_id,
                channel,
                user_id,
            )
            return
        identity = await store.get_for_provider_account(nav_user_id, self._provider, account_id)
        if identity is None:
            self.logger.warning(
                "Jira credential sink: no %s identity for user %s / account %s",
                self._provider,
                nav_user_id,
                account_id,
            )
            return
        await store.update_tokens(identity, self._as_token_response(token))
        self.logger.info(
            "Jira credential sink: refreshed grant sealed for user %s (account %s)",
            nav_user_id,
            account_id,
        )
