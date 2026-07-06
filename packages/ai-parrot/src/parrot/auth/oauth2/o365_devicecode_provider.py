"""O365 device-code (headless) credential resolver — FEAT-266.

Wraps the existing :meth:`O365Client.interactive_login` device-code engine
to provide a :class:`~parrot.auth.credentials.CredentialResolver` for the
broker's ``device_code`` auth kind. CLI-only: :meth:`resolve` blocks inline
and returns the token on success — it does NOT raise
:class:`~parrot.auth.credentials.CredentialRequired` on the happy path.

Resolution steps:

1. Read the user's ``o365:*`` token set from
   :class:`~parrot.services.vault_token_sync.VaultTokenSync`. If
   ``access_token`` is present and not near expiry, return it (cache hit).
2. If expired and a ``refresh_token`` is present, silently refresh via
   :meth:`O365OAuthManager.refresh_access_token`, re-persist, and return.
   On :class:`PermissionError` (dead refresh token), fall through to the
   device-code flow.
3. On a vault miss (or dead refresh), run
   ``O365Client.interactive_login(open_browser=False, device_flow_callback=…)``
   inline. The callback surfaces ``verification_uri`` + ``user_code`` via an
   injected ``prompt_callback`` (default: print to stdout). On success, the
   canonical token set is persisted to ``VaultTokenSync`` under prefix
   ``"o365"`` and ``access_token`` is returned.

Canonical ``o365:*`` field contract (persisted EXACTLY these fields):
``access_token``, ``refresh_token``, ``expires_at`` (epoch seconds),
``scope``, ``id_token`` (optional), ``tenant_id``.

Device-code is CLI-only — Telegram is explicitly out of scope (spec §1
Non-Goals). Callers MUST construct the injected ``vault_token_sync`` with a
non-Telegram ``session_scheme`` (e.g. ``"cli-persistent"``) so tokens are not
filed under :class:`~parrot.services.vault_token_sync.VaultTokenSync`'s
default Telegram-namespaced session-uuid scheme.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from parrot.auth.credentials import CredentialResolver

logger = logging.getLogger(__name__)

#: Vault provider prefix for the canonical Entra (o365) token set.
_O365_VAULT_PREFIX: str = "o365"

#: Treat tokens expiring within this many seconds as already expired
#: (avoids racing the access token's actual expiry during a tool call).
_EXPIRY_SKEW_SECONDS: int = 60

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
            used for the silent refresh primitive
            (``refresh_access_token``).
        vault_token_sync: :class:`~parrot.services.vault_token_sync.VaultTokenSync`
            instance used to persist/read the canonical ``o365:*`` token
            set. CLI callers should construct this instance with a
            non-Telegram ``session_scheme`` (e.g. ``"cli-persistent"``).
        scopes: Requested device-code scopes (defaults to
            ``DEFAULT_O365_SCOPES``, which includes ``offline_access`` so a
            refresh token is granted).
        prompt_callback: Callback invoked with the device-flow payload
            (``verification_uri``, ``user_code``, ``expires_in``,
            ``message``). Defaults to :func:`_default_prompt_callback`
            (prints to stdout).
    """

    def __init__(
        self,
        o365_client: Any,
        o365_oauth_manager: Any,
        vault_token_sync: Any,
        scopes: Optional[List[str]] = None,
        prompt_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        from parrot.auth.o365_oauth import DEFAULT_O365_SCOPES

        self._o365 = o365_client
        self._manager = o365_oauth_manager
        self._vault = vault_token_sync
        self._scopes: List[str] = list(scopes) if scopes else list(DEFAULT_O365_SCOPES)
        self._prompt_callback = prompt_callback or _default_prompt_callback
        self.logger = logger

    async def resolve(self, channel: str, user_id: str) -> Optional[str]:
        """Return a valid Entra access token for ``user_id``.

        Fails closed: an absent/empty ``user_id`` raises ``ValueError``
        rather than touching the vault under an anonymous key.

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
                "O365DeviceCodeCredentialResolver.resolve: user_id is "
                "required — refusing to resolve under an anonymous vault key."
            )

        tokens = await self._vault.read_tokens(user_id, _O365_VAULT_PREFIX)
        if tokens and tokens.get("access_token"):
            expires_at = self._coerce_epoch(tokens.get("expires_at"))
            # FEAT-267: expires_at is always part of a successful device-flow/
            # refresh persist for this provider (module docstring's canonical
            # o365:* field contract) — a missing value on a freshly-read
            # token set is always anomalous (e.g. a partial
            # VaultTokenSync.store_tokens write), so it is treated as
            # EXPIRED here, not valid-forever. This intentionally diverges
            # from the "field legitimately absent" fallback used elsewhere
            # for providers without a fixed field contract.
            if expires_at is not None and expires_at > time.time() + _EXPIRY_SKEW_SECONDS:
                self.logger.debug(
                    "O365DeviceCodeCredentialResolver: cache hit user=%s", user_id,
                )
                return str(tokens["access_token"])

            refresh_token = tokens.get("refresh_token")
            if refresh_token:
                try:
                    payload = await self._manager.refresh_access_token(refresh_token)
                except PermissionError:
                    self.logger.info(
                        "O365DeviceCodeCredentialResolver: refresh token dead "
                        "for user=%s; falling back to device flow", user_id,
                    )
                else:
                    await self._persist_token_set(
                        user_id, payload, fallback_refresh_token=refresh_token,
                    )
                    self.logger.info(
                        "O365DeviceCodeCredentialResolver: silently refreshed "
                        "token for user=%s", user_id,
                    )
                    return str(payload["access_token"])

        return await self._run_device_flow(user_id)

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """Return the Microsoft device-login verification URI.

        Used to populate the extended ``NeedsAuth``/``CredentialRequired``
        fields on failure/timeout and for the future chat surface.
        """
        return _DEVICE_LOGIN_URL

    async def is_connected(self, channel: str, user_id: str) -> bool:
        """Return True when a non-expired ``o365:*`` token exists for ``user_id``.

        FEAT-267: mirrors :meth:`resolve`'s cache-hit interpretation — a
        missing ``expires_at`` on a read token set is treated as expired
        (returns ``False``), not valid-forever, so the two methods never
        silently diverge on the same ``o365:*`` field contract.
        """
        if not user_id:
            return False
        tokens = await self._vault.read_tokens(user_id, _O365_VAULT_PREFIX)
        if not tokens or not tokens.get("access_token"):
            return False
        expires_at = self._coerce_epoch(tokens.get("expires_at"))
        return expires_at is not None and expires_at > time.time() + _EXPIRY_SKEW_SECONDS

    # ------------------------------------------------------------------ internals

    async def _run_device_flow(self, user_id: str) -> str:
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
            raise PermissionError(
                "O365 device-code flow did not return an access_token for "
                f"user={user_id}"
            )

        await self._persist_token_set(user_id, result)
        self.logger.info(
            "O365DeviceCodeCredentialResolver: device-code flow succeeded "
            "for user=%s", user_id,
        )
        return str(result["access_token"])

    async def _persist_token_set(
        self,
        user_id: str,
        payload: Dict[str, Any],
        fallback_refresh_token: Optional[str] = None,
    ) -> None:
        """Persist ``payload`` to ``VaultTokenSync`` under the canonical field set."""
        now = time.time()
        expires_in = payload.get("expires_in")
        if expires_in is None:
            # Entra's token endpoint always includes `expires_in` per the OAuth2
            # spec; its absence here is anomalous, not an expected shape. Since
            # FEAT-267 treats a missing `expires_at` on read as *expired* (not
            # valid-forever — see `resolve`/`is_connected`), a token persisted
            # without it will force an extra refresh/device-flow round-trip on
            # the next `resolve()` call. That's a safe (if wasteful) fail-safe
            # trade-off, but log it loudly so a non-compliant upstream response
            # is observable rather than silently swallowed.
            logger.warning(
                "O365DeviceCodeCredentialResolver: token payload for user=%s "
                "is missing 'expires_in' (unexpected for Entra) — persisting "
                "without expires_at; next resolve() will treat this token as "
                "expired.",
                user_id,
            )
        expires_at = int(now + int(expires_in)) if expires_in is not None else None

        canonical: Dict[str, Any] = {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token") or fallback_refresh_token,
            "expires_at": expires_at,
            "scope": payload.get("scope") or " ".join(self._scopes),
            "id_token": payload.get("id_token"),
            "tenant_id": getattr(self._o365, "tenant_id", None),
        }
        await self._vault.store_tokens(user_id, _O365_VAULT_PREFIX, canonical)

    @staticmethod
    def _coerce_epoch(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
