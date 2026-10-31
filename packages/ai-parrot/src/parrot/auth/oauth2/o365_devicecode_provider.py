"""O365 device-code (headless) credential resolver — FEAT-266.

Wraps the existing :meth:`O365Client.interactive_login` device-code engine
to provide a :class:`~parrot.auth.credentials.CredentialResolver` for the
broker's ``device_code`` auth kind. CLI-only: :meth:`resolve` blocks inline
and returns the token on success — it does NOT raise
:class:`~parrot.auth.credentials.CredentialRequired` on the happy path.

Resolution steps:

1. Resolve the channel identity to its platform principal, failing closed
   when no binding exists.
2. Read and refresh the principal-keyed O365 grant through
   :meth:`O365OAuthManager.get_valid_token`.
3. On a miss, import one legacy ``o365:*`` grant while the migration window
   remains open.
4. Otherwise run
   ``O365Client.interactive_login(open_browser=False, device_flow_callback=…)``
   inline. The callback surfaces ``verification_uri`` + ``user_code`` via an
   injected ``prompt_callback`` (default: print to stdout). On success, the
   token set is persisted through ``O365OAuthManager.store_device_grant`` and
   ``access_token`` is returned. New O365 grants are never written to
   ``VaultTokenSync``; an optional legacy vault is read/deleted only during
   migration.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from parrot.auth.credentials import CredentialResolver
from parrot.auth.oauth2_base import _legacy_window_open
from parrot.auth.principal import Principal, resolve_principal

logger = logging.getLogger(__name__)

#: Vault provider prefix for the canonical Entra (o365) token set.
_O365_VAULT_PREFIX: str = "o365"

#: Fallback device-login verification URI (used by get_auth_url and as the
#: default device_flow_callback message source when the engine omits one).
_DEVICE_LOGIN_URL: str = "https://microsoft.com/devicelogin"


def _default_prompt_callback(flow: Dict[str, Any]) -> None:
    """Print the device-login prompt to stdout (the default `prompt_callback`).

    Deliberately bypasses ``self.logger`` — the device-code message is a
    user-facing CLI prompt, not a log line, and must never be confused with
    the secret-safe audit/logging path.
    """
    message = flow.get("message") or (
        f"To sign in, visit {flow.get('verification_uri', _DEVICE_LOGIN_URL)} "
        f"and enter the code: {flow.get('user_code', '')}"
    )
    print("\n" + "=" * 60)
    print(message)
    print("=" * 60 + "\n")


class O365DeviceCodeCredentialResolver(CredentialResolver):
    """Device-code (headless) credential resolver for O365 (FEAT-266).

    Implements the :class:`~parrot.auth.credentials.CredentialResolver`
    contract so the broker can gate any tool declaring
    ``credential_provider="o365"`` with ``auth="device_code"`` through this
    flow. CLI-only — see module docstring for the resolution steps.

    Args:
        o365_client: Configured :class:`~parrot.interfaces.o365.O365Client`
            used for the device-code engine (``interactive_login``).
        o365_oauth_manager: :class:`~parrot.auth.o365_oauth.O365OAuthManager`
            that owns principal-keyed O365 grants and refreshes them.
        scopes: Requested device-code scopes (defaults to
            ``DEFAULT_O365_SCOPES``, which includes ``offline_access`` so a
            refresh token is granted).
        prompt_callback: Callback invoked with the device-flow payload
            (``verification_uri``, ``user_code``, ``expires_in``,
            ``message``). Defaults to :func:`_default_prompt_callback`
            (prints to stdout).
        legacy_vault: Optional legacy ``VaultTokenSync`` reader used only to
            migrate and delete old e-mail/OID-keyed ``o365:*`` grants.
    """

    def __init__(
        self,
        o365_client: Any,
        o365_oauth_manager: Any,
        scopes: Optional[List[str]] = None,
        prompt_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        *,
        legacy_vault: Any = None,
    ) -> None:
        from parrot.auth.o365_oauth import DEFAULT_O365_SCOPES

        self._o365 = o365_client
        self._manager = o365_oauth_manager
        self._legacy_vault = legacy_vault
        self._pending_cleanup: set[str] = set()
        self._scopes: List[str] = list(scopes) if scopes else list(DEFAULT_O365_SCOPES)
        self._prompt_callback = prompt_callback or _default_prompt_callback
        self.logger = logger

    async def resolve(self, channel: str, user_id: str) -> Optional[str]:
        """Return a valid Entra access token for ``user_id``.

        Fails closed before store or device-flow access when the channel
        identity cannot be resolved to a platform principal.

        Args:
            channel: Surface channel (e.g. ``"cli"``).
            user_id: Canonical per-user identity (email / OID).

        Returns:
            The Entra access token. Never returns ``None`` on the CLI happy
            path — the device flow blocks until success or raises.

        Raises:
            ValueError: ``user_id`` is empty/``None`` (fail closed).
            PermissionError: The device-code flow failed or the engine
                returned no usable token.
        """
        if not user_id:
            raise ValueError(
                "O365DeviceCodeCredentialResolver.resolve: user_id is required — refusing an anonymous resolve."
            )
        principal = await resolve_principal(channel, user_id)
        if principal is None:
            raise PermissionError(f"No platform principal bound for channel {channel!r}; device code refused")
        try:
            token_set = await self._manager.get_valid_token(channel, principal.user_id)
        except PermissionError:
            token_set = None
        if token_set is not None:
            await self._retry_legacy_cleanup(user_id)
            return str(token_set.access_token)
        migrated = await self._migrate_legacy(user_id, principal, channel=channel)
        if migrated is not None:
            return migrated
        return await self._run_device_flow(user_id, principal=principal, channel=channel)

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """Return the Microsoft device-login verification URI.

        Used to populate the extended ``NeedsAuth``/``CredentialRequired``
        fields on failure/timeout and for the future chat surface.
        """
        return _DEVICE_LOGIN_URL

    async def is_connected(self, channel: str, user_id: str) -> bool:
        """Return whether the platform principal has a valid shared O365 grant."""
        if not user_id:
            return False
        principal = await resolve_principal(channel, user_id)
        if principal is None:
            return False
        return await self._manager.is_connected(channel, principal.user_id)

    # ------------------------------------------------------------------ internals

    async def _run_device_flow(self, user_id: str, *, principal: Principal, channel: str) -> str:
        """Run the inline blocking device-code flow and persist on success.

        ``O365Client.interactive_login`` raises on failure/timeout/MSAL
        error BEFORE returning a result, so no partial vault write happens
        on the unhappy path — this method only persists once a full,
        valid token payload is in hand.
        """

        def _on_device_flow(flow: Dict[str, Any]) -> None:
            self._prompt_callback(flow)

        result = await self._o365.interactive_login(
            scopes=self._scopes,
            open_browser=False,
            device_flow_callback=_on_device_flow,
        )

        if not result or "access_token" not in result:
            raise PermissionError("O365 device-code flow did not return an access_token for " f"user={user_id}")

        await self._persist_token_set(principal, result, channel=channel)
        self.logger.info(
            "O365DeviceCodeCredentialResolver: device-code flow succeeded " "for user=%s",
            user_id,
        )
        return str(result["access_token"])

    async def _persist_token_set(
        self,
        principal: Principal,
        payload: Dict[str, Any],
        *,
        channel: str,
    ) -> None:
        """Persist a fresh device-code response through the shared, durable-first O365 record."""
        await self._manager.store_device_grant(principal, payload, channel=channel)

    async def _migrate_legacy(self, canonical_id: str, principal: Principal, *, channel: str) -> Optional[str]:
        """Import one legacy ``o365:*`` grant while the S-1 migration window is open."""
        if self._legacy_vault is None or not _legacy_window_open():
            return None
        legacy = await self._legacy_vault.read_tokens(canonical_id, _O365_VAULT_PREFIX)
        if not legacy or not legacy.get("access_token"):
            return None
        try:
            token_set = await self._manager.migrate_legacy_device_grant(principal, legacy, channel=channel)
        except PermissionError:
            self.logger.info("Legacy o365 grant unusable for principal %s; device flow required", principal.user_id)
            return None
        # The legacy entry is spent either way: imported, or blocked for good by a current record or a
        # disconnect tombstone (both checked under the principal lock, so it can never be imported later).
        await self._delete_legacy(canonical_id)
        if token_set is None:
            return await self._current_token(channel, principal)
        return str(token_set.access_token)

    async def _current_token(self, channel: str, principal: Principal) -> Optional[str]:
        """Return the grant that beat the legacy import, if any; ``None`` sends the caller to the device flow."""
        try:
            current = await self._manager.get_valid_token(channel, principal.user_id)
        except PermissionError:
            return None
        return str(current.access_token) if current is not None else None

    async def _delete_legacy(self, canonical_id: str) -> None:
        """Best-effort legacy delete; failure leaves a retry marker, never a re-import.

        The marker is in-process only. After a restart a leftover legacy entry stays inert: the
        current-record-wins check and the revoke tombstone (which outlives the migration window) both
        block a re-import, and the next miss that reads it deletes it.
        """
        try:
            await self._legacy_vault.delete_tokens(canonical_id, _O365_VAULT_PREFIX)
        except Exception as exc:
            self._pending_cleanup.add(canonical_id)
            self.logger.warning("Legacy o365 delete failed for canonical id: %s", type(exc).__name__)
        else:
            self._pending_cleanup.discard(canonical_id)

    async def _retry_legacy_cleanup(self, canonical_id: str) -> None:
        """Retry a previously failed legacy delete for this id, if one is pending."""
        if canonical_id in self._pending_cleanup:
            await self._delete_legacy(canonical_id)
