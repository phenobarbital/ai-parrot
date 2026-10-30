"""Transactional CredentialStore adapter for navigator-auth's Identity Vault."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from navigator_auth.identity.store import _IDENTITY_TABLE, IdentityCredentialError
from parrot.services.identity_mapping import _raw_connection

if TYPE_CHECKING:
    from parrot.auth.principal import Principal


_METADATA_KEYS = frozenset({"account_id", "display_name", "email", "cloud_id", "site_url", "scopes_granted"})


def _as_datetime(value: Any) -> Optional[datetime]:
    """Convert an epoch value or datetime to a timezone-aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def _epoch(value: Any) -> Optional[float]:
    """Convert a datetime or epoch value to an epoch float."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.timestamp()
    return float(value)


def _metadata(payload: Any) -> Dict[str, Any]:
    """Return only the provider metadata allowed in ``auth_data``."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    if not isinstance(payload, dict):
        return {}
    return {key: payload[key] for key in _METADATA_KEYS if key in payload and payload[key] is not None}


class IdentityVaultCredentialStore:
    """``CredentialStore`` over navigator-auth's Identity Vault for any 3LO provider (FEAT-773 M8).

    Single account per (principal, provider) in v1 (S3): a minted save atomically replaces superseded accounts.
    The caller (AbstractOAuth2Manager) holds the per-principal lock; this class never takes it.
    """

    def __init__(self, db_pool: Any, cipher: Optional[Any] = None) -> None:
        self._db_pool = db_pool
        self._cipher = cipher
        self.logger = logging.getLogger(__name__)

    def _store(self) -> Any:
        """Build an IdentityStore over the configured pool."""
        from navigator_auth.identity.store import IdentityStore

        return IdentityStore(self._db_pool, cipher=self._cipher)

    def _identity_cipher(self) -> Any:
        """Return the configured cipher or navigator-auth's default cipher."""
        from navigator_auth.identity.crypto import IdentityCipher

        return self._cipher or IdentityCipher()

    async def load(self, user_id: str, provider: str) -> Optional[Dict[str, Any]]:
        """Load the newest enabled row as an OAuth token payload, or ``None``."""
        store = self._store()
        try:
            identity = await store.get_by_provider(int(user_id), provider)
            if identity is None:
                return None
            token = store.decrypt_credential(identity)
        except IdentityCredentialError as exc:
            self.logger.warning("Could not decrypt %s credential for user %s: %s", provider, user_id, exc)
            return None

        payload: Dict[str, Any] = {
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
            "id_token": token.id_token,
            "expires_at": _epoch(token.expires_at),
            "scopes": list(token.scopes or []),
            "account_id": identity.provider_user_id,
        }
        payload.update(_metadata(identity.auth_data or {}))
        return {key: value for key, value in payload.items() if value is not None}

    async def save(
        self,
        user_id: str,
        provider: str,
        payload: Dict[str, Any],
        *,
        minted: bool,
        principal: Optional["Principal"],
        state_payload: Optional[Dict[str, Any]],
    ) -> None:
        """Persist a minted grant by replacement or refresh the selected grant."""
        del principal, state_payload
        if minted:
            await self._replace_account_tx(int(user_id), provider, payload)
        else:
            await self._update_selected_tx(int(user_id), provider, payload)

    async def delete(self, user_id: str, provider: str) -> None:
        """Delete every credential row for a principal and provider atomically."""
        async with await self._db_pool.acquire() as conn:
            raw = _raw_connection(conn)
            async with raw.transaction():
                await raw.execute(
                    f"DELETE FROM {_IDENTITY_TABLE} WHERE user_id = $1 AND auth_provider = $2",
                    int(user_id),
                    provider,
                )

    async def _replace_account_tx(self, user_id: int, provider: str, payload: Dict[str, Any]) -> None:
        """Lock, upsert the selected account, and remove superseded accounts in one transaction."""
        account_id = payload.get("account_id")
        if not account_id:
            raise ValueError("minted credential payload requires account_id")
        cipher = self._identity_cipher()
        values: Dict[str, Any] = {
            "provider_user_id": str(account_id),
            "auth_data": json.dumps(_metadata(payload)),
            "scopes": json.dumps(list(payload.get("scopes") or [])),
            "token_type": payload.get("token_type", "Bearer"),
            "expires_at": _as_datetime(payload.get("expires_at")),
            "refreshed_at": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc),
            "enabled": True,
            "key_version": cipher.key_id,
        }
        for field in ("access_token", "refresh_token", "id_token"):
            value = payload.get(field)
            if value is not None:
                values[field] = cipher.encrypt(
                    value,
                    user_id=user_id,
                    auth_provider=provider,
                    provider_user_id=str(account_id),
                    field=field,
                )

        async with await self._db_pool.acquire() as conn:
            raw = _raw_connection(conn)
            async with raw.transaction():
                rows = await raw.fetch(
                    f"SELECT identity_id, provider_user_id FROM {_IDENTITY_TABLE} "
                    "WHERE user_id = $1 AND auth_provider = $2 FOR UPDATE",
                    user_id,
                    provider,
                )
                existing = next((row for row in rows if row["provider_user_id"] == str(account_id)), None)
                if existing is not None:
                    assignments = [
                        f"{key} = ${index}{'::jsonb' if key in {'auth_data', 'scopes'} else ''}"
                        for index, key in enumerate(values, start=3)
                    ]
                    await raw.execute(
                        f"UPDATE {_IDENTITY_TABLE} SET {', '.join(assignments)} "
                        "WHERE identity_id = $1 AND user_id = $2",
                        existing["identity_id"],
                        user_id,
                        *values.values(),
                    )
                    selected_id = existing["identity_id"]
                else:
                    selected_id = uuid.uuid4()
                    columns = ["identity_id", "user_id", "auth_provider", *values]
                    placeholders = ", ".join(
                        f"${index}{'::jsonb' if column in {'auth_data', 'scopes'} else ''}"
                        for index, column in enumerate(columns, start=1)
                    )
                    await raw.execute(
                        f"INSERT INTO {_IDENTITY_TABLE} ({', '.join(columns)}) VALUES ({placeholders})",
                        selected_id,
                        user_id,
                        provider,
                        *values.values(),
                    )
                await raw.execute(
                    f"DELETE FROM {_IDENTITY_TABLE} WHERE user_id = $1 AND auth_provider = $2 " "AND identity_id <> $3",
                    user_id,
                    provider,
                    selected_id,
                )

    async def _update_selected_tx(self, user_id: int, provider: str, payload: Dict[str, Any]) -> None:
        """Refresh only the row that still owns the payload's selected account."""
        account_id = payload.get("account_id")
        if not account_id:
            self.logger.warning("Skipping %s refresh for user %s without account id", provider, user_id)
            return
        cipher = self._identity_cipher()
        async with await self._db_pool.acquire() as conn:
            raw = _raw_connection(conn)
            async with raw.transaction():
                row = await raw.fetchrow(
                    f"SELECT identity_id, provider_user_id FROM {_IDENTITY_TABLE} "
                    "WHERE user_id = $1 AND auth_provider = $2 AND enabled = TRUE "
                    "ORDER BY created_at DESC NULLS LAST LIMIT 1 FOR UPDATE",
                    user_id,
                    provider,
                )
                if row is None or row["provider_user_id"] != str(account_id):
                    self.logger.info("Skipping stale %s refresh for user %s", provider, user_id)
                    return
                values: Dict[str, Any] = {
                    "expires_at": _as_datetime(payload.get("expires_at")),
                    "refreshed_at": datetime.now(timezone.utc),
                    "key_version": cipher.key_id,
                }
                for field in ("access_token", "refresh_token"):
                    if payload.get(field) is not None:
                        values[field] = cipher.encrypt(
                            payload[field],
                            user_id=user_id,
                            auth_provider=provider,
                            provider_user_id=str(account_id),
                            field=field,
                        )
                assignments = ", ".join(f"{key} = ${index}" for index, key in enumerate(values, start=2))
                await raw.execute(
                    f"UPDATE {_IDENTITY_TABLE} SET {assignments} WHERE identity_id = $1",
                    row["identity_id"],
                    *values.values(),
                )


_TOKEN_COLUMNS = ("access_token", "refresh_token", "id_token")
_ROW_COLUMNS = (
    "identity_id, user_id, auth_provider, provider_user_id, access_token, refresh_token, id_token, "
    "enabled, key_version"
)
_logger = logging.getLogger(__name__)


def _open_column(cipher: Any, row: Any, field: str) -> Any:
    """Decrypt one token column of ``row``; raise ``IdentityCredentialError`` on any failure."""
    try:
        return cipher.decrypt(
            row[field],
            user_id=row["user_id"],
            auth_provider=row["auth_provider"],
            provider_user_id=row["provider_user_id"],
            field=field,
        )
    except Exception as exc:
        _logger.error(
            "Identity re-seal decrypt failure: identity=%s provider=%s field=%s error=%s",
            row["identity_id"],
            row["auth_provider"],
            field,
            type(exc).__name__,
        )
        raise IdentityCredentialError(row["auth_provider"], field, type(exc).__name__) from None


async def list_credential_rows(db_pool: Any, providers: Sequence[str]) -> List[Any]:
    """Every credential-bearing identity row (disabled included) for ``providers`` (empty -> all)."""
    query = (
        f"SELECT {_ROW_COLUMNS} FROM {_IDENTITY_TABLE} "
        "WHERE (access_token IS NOT NULL OR refresh_token IS NOT NULL OR id_token IS NOT NULL)"
    )
    args: List[Any] = []
    if providers:
        query += " AND auth_provider = ANY($1)"
        args.append(list(providers))
    async with await db_pool.acquire() as conn:
        raw = _raw_connection(conn)
        return list(await raw.fetch(query, *args))


async def fetch_credential_row(db_pool: Any, identity_id: Any) -> Optional[Any]:
    """Re-read one identity row by id (fresh snapshot, e.g. to verify a re-seal); ``None`` when gone."""
    async with await db_pool.acquire() as conn:
        raw = _raw_connection(conn)
        return await raw.fetchrow(f"SELECT {_ROW_COLUMNS} FROM {_IDENTITY_TABLE} WHERE identity_id = $1", identity_id)


async def reseal_identity_row(db_pool: Any, row: Any, *, cipher: Optional[Any] = None) -> None:
    """Re-seal every present token column of one row under the active key; preserve all metadata.

    Raises:
        IdentityCredentialError: A present column cannot be decrypted; nothing is written.
    """
    if cipher is None:
        from navigator_auth.identity.crypto import IdentityCipher

        cipher = IdentityCipher()
    async with await db_pool.acquire() as conn:
        raw = _raw_connection(conn)
        async with raw.transaction():
            current = await raw.fetchrow(
                f"SELECT {_ROW_COLUMNS} FROM {_IDENTITY_TABLE} WHERE identity_id = $1 FOR UPDATE",
                row["identity_id"],
            )
            if current is None:
                return
            # Decrypt everything first: any failure must leave the row untouched.
            plain = {
                field: _open_column(cipher, current, field) for field in _TOKEN_COLUMNS if current[field] is not None
            }
            if not plain:
                return
            values: Dict[str, Any] = {
                field: cipher.encrypt(
                    value,
                    user_id=current["user_id"],
                    auth_provider=current["auth_provider"],
                    provider_user_id=current["provider_user_id"],
                    field=field,
                )
                for field, value in plain.items()
            }
            values["key_version"] = cipher.key_id
            assignments = ", ".join(f"{key} = ${index}" for index, key in enumerate(values, start=2))
            await raw.execute(
                f"UPDATE {_IDENTITY_TABLE} SET {assignments} WHERE identity_id = $1",
                current["identity_id"],
                *values.values(),
            )


def verify_active_only(row: Any, *, active_cipher: Any) -> bool:
    """True iff every present token column decrypts with a ring holding ONLY the active key."""
    for field in _TOKEN_COLUMNS:
        if row[field] is None:
            continue
        try:
            active_cipher.decrypt(
                row[field],
                user_id=row["user_id"],
                auth_provider=row["auth_provider"],
                provider_user_id=row["provider_user_id"],
                field=field,
            )
        except Exception:
            return False
    return True
