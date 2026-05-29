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
from typing import Any, Dict, Optional

try:
    from navigator_session.vault import SessionVault
except ImportError:  # pragma: no cover - optional dependency
    SessionVault = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _synth_session_uuid(nav_user_id: str) -> str:
    """Deterministic session_uuid used for persistent per-user vault access.

    The vault's *session layer* derives a key from ``session_uuid``; to make
    entries survive across Telegram bot sessions we deterministically map
    each navigator-auth user to a stable UUID-like string.
    """
    return f"telegram-persistent:{nav_user_id}"


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

    Notes:
        All failures (vault unavailable, Redis down, DB error) are logged
        and **swallowed** — callers get either ``None`` (reads) or silent
        success (writes / deletes). This is intentional: token
        persistence is supplementary (Redis is the primary store) and
        must never break the auth flow.
    """

    def __init__(
        self,
        db_pool: Any,
        redis: Any,
        session_ttl: int = 3600,
    ) -> None:
        self._pool = db_pool
        self._redis = redis
        self._session_ttl = session_ttl
        self.logger = logger

    async def _load_vault(self, nav_user_id: str) -> Optional[Any]:
        """Load (or return None on failure) a SessionVault for ``nav_user_id``."""
        if SessionVault is None:
            self.logger.warning(
                "VaultTokenSync: navigator_session.vault.SessionVault "
                "is not importable; vault operations are no-ops."
            )
            return None
        try:
            vault = await SessionVault.load_for_session(
                session_uuid=_synth_session_uuid(nav_user_id),
                user_id=_coerce_user_id(nav_user_id),
                db_pool=self._pool,
                redis=self._redis,
                session_ttl=self._session_ttl,
            )
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
        keys with blanks.
        """
        if not tokens:
            return
        vault = await self._load_vault(nav_user_id)
        if vault is None:
            return
        try:
            for key, value in tokens.items():
                if value is None:
                    continue
                vault_key = f"{provider}:{key}"
                await vault.set(vault_key, value)
            self.logger.info(
                "VaultTokenSync: stored %d tokens user=%s provider=%s",
                len(tokens),
                nav_user_id,
                provider,
            )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "VaultTokenSync: failed to store tokens user=%s provider=%s",
                nav_user_id,
                provider,
            )

    async def read_tokens(
        self,
        nav_user_id: str,
        provider: str,
    ) -> Optional[Dict[str, Any]]:
        """Read all ``{provider}:*`` keys from the user's vault.

        Returns:
            A dict of ``{field_name: value}`` (with provider prefix stripped),
            or ``None`` if the vault is unavailable or no keys exist.
        """
        vault = await self._load_vault(nav_user_id)
        if vault is None:
            return None
        prefix = f"{provider}:"
        try:
            all_keys = await vault.keys()
            matches = [k for k in all_keys if k.startswith(prefix)]
            if not matches:
                return None
            result: Dict[str, Any] = {}
            for full_key in matches:
                field = full_key[len(prefix):]
                value = await vault.get(full_key)
                if value is not None:
                    result[field] = value
            return result or None
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "VaultTokenSync: failed to read tokens user=%s provider=%s",
                nav_user_id,
                provider,
            )
            return None

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
