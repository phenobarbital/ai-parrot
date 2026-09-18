"""
VaultTokenSync — store and retrieve OAuth tokens in the user's navigator
Vault using a flat ``{provider}:{field}`` key scheme.

Works from non-HTTP contexts (e.g., the Telegram wrapper running under
aiogram polling) by instantiating :class:`navigator_session.vault.SessionVault`
directly via its ``load_for_session`` classmethod.

Example keys stored for a Jira auth:
    jira:access_token
    jira:refresh_token
    jira:cloud_id
    jira:site_url
    jira:account_id
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

try:
    from navigator_session.vault import SessionVault, VaultCryptoError
except ImportError:  # pragma: no cover - optional dependency
    SessionVault = None  # type: ignore[assignment]

    class VaultCryptoError(Exception):  # type: ignore[no-redef]
        """Placeholder when navigator-session vault crypto is unavailable."""


#: Outcome of a vault read: tokens present, absent, unreadable or no vault.
TokenReadStatus = Literal["ok", "missing", "unreadable", "unavailable"]


@dataclass(frozen=True)
class VaultTokenRead:
    """Typed result of :meth:`VaultTokenSync.read_tokens_result`.

    Attributes:
        tokens: Field → value mapping when ``status == "ok"``, else ``None``.
        status: ``ok`` (readable), ``missing`` (no keys stored),
            ``unreadable`` (stored but failed integrity/format checks) or
            ``unavailable`` (vault could not be loaded).
    """

    tokens: Optional[Dict[str, Any]]
    status: TokenReadStatus

    @property
    def needs_reconnect(self) -> bool:
        """True when the provider must be re-linked (tokens exist but are unusable)."""
        return self.status == "unreadable"

logger = logging.getLogger(__name__)


#: Legacy default session-uuid scheme — preserved verbatim for backward
#: compatibility with existing Telegram-surfaced callers (jira/fireflies).
_DEFAULT_SESSION_SCHEME: str = "telegram-persistent"


def _synth_session_uuid(
    nav_user_id: str, session_scheme: str = _DEFAULT_SESSION_SCHEME,
) -> str:
    """Deterministic session_uuid used for persistent per-user vault access.

    The vault's *session layer* derives a key from ``session_uuid``; to make
    entries survive across bot/CLI sessions we deterministically map each
    navigator-auth user to a stable UUID-like string.

    Args:
        nav_user_id: The navigator-auth user identifier.
        session_scheme: Session-uuid scheme prefix. Defaults to the legacy
            Telegram scheme (``"telegram-persistent"``) so existing
            jira/fireflies/workiq callers are unaffected. FEAT-266 introduces
            non-Telegram callers (e.g. the O365 device-code CLI resolver)
            that pass a different scheme (e.g. ``"cli-persistent"``) so
            tokens are not filed under a Telegram-namespaced key.
    """
    return f"{session_scheme}:{nav_user_id}"


def _coerce_user_id(nav_user_id: Any) -> Any:
    """Coerce nav_user_id to int if possible (load_for_session expects int).

    Falls back to the original value if it isn't numeric (some navigator-auth
    schemas use UUIDs).
    """
    if isinstance(nav_user_id, int):
        return nav_user_id
    if isinstance(nav_user_id, str):
        try:
            return int(nav_user_id)
        except (TypeError, ValueError):
            return nav_user_id
    return nav_user_id


class VaultTokenSync:
    """Persist OAuth tokens in the encrypted user vault.

    Args:
        db_pool: The ``authdb`` asyncpg pool (``app["authdb"]``).
        redis: The shared Redis client (``app["redis"]``).
        session_ttl: Vault session TTL in seconds (defaults to 1h).
        session_scheme: Session-uuid scheme prefix passed to
            :func:`_synth_session_uuid`. Defaults to the legacy Telegram
            scheme (``"telegram-persistent"``) — existing jira/fireflies/
            workiq callers are unaffected. Non-Telegram surfaces (FEAT-266:
            the O365 device-code CLI resolver) pass a different scheme
            (e.g. ``"cli-persistent"``) so their tokens round-trip under a
            non-Telegram-namespaced key.

    Notes:
        All failures (vault unavailable, Redis down, DB error) are logged
        and **swallowed** — callers get either ``None`` (reads) or silent
        success (writes / deletes). This is intentional: token
        persistence is supplementary (Redis is the primary store) and
        must never break the auth flow.
    """

    #: Field written first (before all other fields) by `store_tokens` so a
    #: mid-loop failure cannot leave a token set that reads as
    #: permanently valid — see FEAT-267 (o365-devicecode-followups spec §2
    #: Module 2). `SessionVault` (verified via `navigator_session.vault`)
    #: exposes only `get`/`set`/`delete`/`keys`/`exists` — no bulk/
    #: transactional write primitive — so this ordering is the mitigation,
    #: not a batched write.
    _WRITE_FIRST_FIELD: str = "expires_at"

    def __init__(
        self,
        db_pool: Any,
        redis: Any,
        session_ttl: int = 3600,
        session_scheme: str = _DEFAULT_SESSION_SCHEME,
    ) -> None:
        self._pool = db_pool
        self._redis = redis
        self._session_ttl = session_ttl
        self._session_scheme = session_scheme
        self._vaults: Dict[str, Any] = {}
        self.logger = logger

    def _invalidate_vault(self, nav_user_id: str) -> None:
        """Drop the cached vault after a write/delete."""
        self._vaults.pop(str(nav_user_id), None)

    async def _load_vault(self, nav_user_id: str) -> Optional[Any]:
        """Load (or return None on failure) a SessionVault for ``nav_user_id``.

        The vault is cached per instance, so listing several providers for one
        user costs a single load (instances are short-lived, one per request).
        """
        cached = self._vaults.get(str(nav_user_id))
        if cached is not None:
            return cached
        if SessionVault is None:
            self.logger.warning(
                "VaultTokenSync: navigator_session.vault.SessionVault "
                "is not importable; vault operations are no-ops."
            )
            return None
        try:
            vault = await SessionVault.load_for_session(
                session_uuid=_synth_session_uuid(nav_user_id, self._session_scheme),
                user_id=_coerce_user_id(nav_user_id),
                db_pool=self._pool,
                redis=self._redis,
                session_ttl=self._session_ttl,
            )
            self._vaults[str(nav_user_id)] = vault
            return vault
        except Exception:  # noqa: BLE001 - intentional broad catch
            self.logger.exception(
                "VaultTokenSync: failed to load vault for user=%s",
                nav_user_id,
            )
            return None

    async def store_tokens(
        self,
        nav_user_id: str,
        provider: str,
        tokens: Dict[str, Any],
    ) -> None:
        """Store each ``tokens[key]`` at ``{provider}:{key}`` in the vault.

        Empty / ``None`` values are skipped to avoid clobbering existing
        keys with blanks. ``expires_at`` (when present) is written FIRST, so
        a mid-loop failure either leaves ``expires_at`` already correctly
        persisted, or leaves other fields (e.g. ``access_token``) never
        written — a subsequent read cannot look "permanently valid" from a
        partial write (FEAT-267; no bulk/transactional vault write primitive
        exists, verified against ``SessionVault``'s public interface).

        A distinguishable warning is logged (in addition to the existing
        exception log) when the loop does not persist every expected key.
        """
        if not tokens:
            return
        vault = await self._load_vault(nav_user_id)
        if vault is None:
            return

        expected_items = [(key, value) for key, value in tokens.items() if value is not None]
        ordered_items = sorted(
            expected_items, key=lambda item: item[0] != self._WRITE_FIRST_FIELD,
        )

        written_keys: list[str] = []
        try:
            for key, value in ordered_items:
                vault_key = f"{provider}:{key}"
                await vault.set(vault_key, value)
                written_keys.append(key)
            self.logger.info(
                "VaultTokenSync: stored %d tokens user=%s provider=%s",
                len(written_keys),
                nav_user_id,
                provider,
            )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "VaultTokenSync: failed to store tokens user=%s provider=%s",
                nav_user_id,
                provider,
            )
        finally:
            self._invalidate_vault(nav_user_id)
            expected_keys = [key for key, _ in expected_items]
            missing_keys = [key for key in expected_keys if key not in written_keys]
            if missing_keys:
                self.logger.warning(
                    "VaultTokenSync: PARTIAL WRITE detected user=%s provider=%s "
                    "written=%s missing=%s — token set may be inconsistent "
                    "until the next successful store_tokens() call",
                    nav_user_id,
                    provider,
                    written_keys,
                    missing_keys,
                )

    async def read_tokens_result(
        self,
        nav_user_id: str,
        provider: str,
    ) -> VaultTokenRead:
        """Read all ``{provider}:*`` keys, distinguishing absent from unreadable.

        Args:
            nav_user_id: Navigator user identifier.
            provider: Vault key prefix (provider id).

        Returns:
            :class:`VaultTokenRead` — ``ok`` with the tokens, ``missing`` when
            nothing is stored, ``unreadable`` when a stored token fails the
            vault's integrity/format checks (the provider must be re-linked),
            or ``unavailable`` when the vault could not be loaded.
        """
        vault = await self._load_vault(nav_user_id)
        if vault is None:
            return VaultTokenRead(None, "unavailable")
        prefix = f"{provider}:"
        try:
            all_keys = await vault.keys()
            matches = [k for k in all_keys if k.startswith(prefix)]
            if not matches:
                return VaultTokenRead(None, "missing")
            result: Dict[str, Any] = {}
            for full_key in matches:
                field = full_key[len(prefix):]
                value = await vault.get(full_key)
                if value is not None:
                    result[field] = value
            return VaultTokenRead(result, "ok") if result else VaultTokenRead(None, "missing")
        except VaultCryptoError as err:
            # NEVER log token material — only the failure class.
            self.logger.error(
                "VaultTokenSync: stored tokens are unreadable user=%s provider=%s error=%s",
                nav_user_id,
                provider,
                type(err).__name__,
            )
            return VaultTokenRead(None, "unreadable")
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "VaultTokenSync: failed to read tokens user=%s provider=%s",
                nav_user_id,
                provider,
            )
            return VaultTokenRead(None, "unavailable")

    async def read_tokens(
        self,
        nav_user_id: str,
        provider: str,
    ) -> Optional[Dict[str, Any]]:
        """Read all ``{provider}:*`` keys from the user's vault.

        Returns:
            A dict of ``{field_name: value}`` (with provider prefix stripped),
            or ``None`` if the vault is unavailable, unreadable, or no keys
            exist. Use :meth:`read_tokens_result` to tell those apart.
        """
        return (await self.read_tokens_result(nav_user_id, provider)).tokens

    async def delete_tokens(
        self,
        nav_user_id: str,
        provider: str,
    ) -> None:
        """Remove every ``{provider}:*`` key from the user's vault."""
        vault = await self._load_vault(nav_user_id)
        if vault is None:
            return
        prefix = f"{provider}:"
        try:
            all_keys = await vault.keys()
            for full_key in [k for k in all_keys if k.startswith(prefix)]:
                await vault.delete(full_key)
            self.logger.info(
                "VaultTokenSync: deleted tokens user=%s provider=%s",
                nav_user_id,
                provider,
            )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "VaultTokenSync: failed to delete tokens user=%s provider=%s",
                nav_user_id,
                provider,
            )
        finally:
            self._invalidate_vault(nav_user_id)
