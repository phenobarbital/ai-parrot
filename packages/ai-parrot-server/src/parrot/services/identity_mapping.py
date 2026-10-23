"""
IdentityMappingService — CRUD for navigator-auth ``user_identities``.

Links navigator-auth internal user IDs with external provider identities
(Telegram numeric IDs, Teams AAD object ids, Jira account IDs, etc.).

Schema facts that shape this module (``auth.user_identities``,
navigator-auth >= 0.28.8):

* PK is ``identity_id`` (uuid, ``gen_random_uuid()``); there is no ``uid``.
* ``user_id`` is ``bigint`` with a deferred FK to ``auth.users``.
* The only unique index usable as an upsert arbiter is the PARTIAL index
  ``UNIQUE (user_id, auth_provider, provider_user_id) WHERE
  provider_user_id IS NOT NULL``. ``(user_id, auth_provider)`` is NOT
  unique (one user may link several accounts of a provider), so the old
  ``ON CONFLICT (user_id, auth_provider)`` failed with 42P10 on every call.

Two write paths:

* channel mappings (msteams/slack/telegram) carry no credential and are
  written with raw SQL below;
* token-bearing providers (jira) go through navigator-auth's
  :class:`IdentityStore`, which ciphers the credential.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from navigator_auth.identity.store import IdentityStore
    from navigator_auth.identity.types import TokenResponse

logger = logging.getLogger(__name__)


# ``$1::text::bigint`` lets callers pass the navigator user id as a string
# (asyncpg would otherwise reject a ``str`` for a bigint parameter) while a
# non-numeric id fails loudly server-side instead of being coerced.
_UPSERT_SQL = """
INSERT INTO auth.user_identities
    (user_id, auth_provider, provider_user_id, auth_data, display_name, email, created_at)
VALUES ($1::text::bigint, $2, $3, $4::jsonb, $5, $6, NOW())
ON CONFLICT (user_id, auth_provider, provider_user_id)
    WHERE provider_user_id IS NOT NULL
DO UPDATE SET
    auth_data = EXCLUDED.auth_data,
    display_name = COALESCE(EXCLUDED.display_name, auth.user_identities.display_name),
    email = COALESCE(EXCLUDED.email, auth.user_identities.email)
RETURNING identity_id, user_id, auth_provider, provider_user_id, auth_data
"""

# Metadata stamp applied after an IdentityStore write: merges the
# non-secret provider payload into ``auth_data`` (IdentityStore only keeps
# a fixed set of userinfo keys there).
#
# ``$2::text::jsonb``, not ``$2::jsonb``: in the operator position asyncpg
# infers the parameter as jsonb and encodes the Python ``str`` as a JSON
# *string scalar*, so ``||`` APPENDS it and the row ends up as
# ``[{profile}, "{...}"]`` — a jsonb array, from which _decode_auth_data
# returns ``{}``. Forcing text first makes Postgres parse it and merge.
# Verified against auth.user_identities on navigator-auth 0.28.8.
_STAMP_METADATA_SQL = """
UPDATE auth.user_identities
SET auth_data = COALESCE(auth_data, '{}'::jsonb) || $2::text::jsonb,
    display_name = COALESCE($3, display_name),
    email = COALESCE($4, email)
WHERE identity_id = $1
RETURNING identity_id
"""

_GET_SQL = """
SELECT identity_id, user_id, auth_provider, provider_user_id, auth_data,
       display_name, email, created_at
FROM auth.user_identities
WHERE user_id = $1::text::bigint AND auth_provider = $2
ORDER BY created_at DESC NULLS LAST
LIMIT 1
"""

_GET_ALL_SQL = """
SELECT identity_id, user_id, auth_provider, provider_user_id, auth_data,
       display_name, email, created_at
FROM auth.user_identities
WHERE user_id = $1::text::bigint
ORDER BY auth_provider
"""

_DELETE_SQL = """
DELETE FROM auth.user_identities
WHERE user_id = $1::text::bigint AND auth_provider = $2
"""

#: Keys that must never be written in cleartext into ``auth_data``.
_SECRET_KEYS = frozenset({"access_token", "refresh_token", "id_token", "token", "client_secret"})


def _raw_connection(conn: Any) -> Any:
    """Return the asyncpg connection behind ``conn``.

    The ``authdb`` pool is an asyncdb ``pgPool`` whose connections wrap
    asyncpg; asyncdb's ``execute`` returns ``(result, error)`` instead of
    raising on most Postgres errors, which would hide a failed write. The
    raw asyncpg connection always raises.
    """
    engine = getattr(conn, "engine", None)
    if callable(engine):
        return engine()
    return conn


def _decode_auth_data(raw: Any) -> Dict[str, Any]:
    """Normalize ``auth_data`` from the DB into a Python dict.

    The column is JSONB; depending on driver it may already be a dict
    (asyncpg with jsonb codec) or a JSON-encoded string.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Could not decode auth_data JSON: %r", raw[:80])
            return {}
    return {}


class IdentityMappingService:
    """CRUD service for ``auth.user_identities`` records.

    Args:
        db_pool: An asyncpg-compatible connection pool (typically the
            navigator-auth ``authdb`` pool obtained from
            ``app.get("authdb")``).

    Example:
        >>> service = IdentityMappingService(db_pool=app["authdb"])
        >>> await service.upsert_identity(
        ...     nav_user_id="nav-123",
        ...     auth_provider="jira",
        ...     provider_user_id="abc",
        ...     auth_data={"account_id": "abc", "cloud_id": "def"},
        ...     display_name="Jane Doe",
        ...     email="jane@example.com",
        ... )
    """

    def __init__(self, db_pool: Any, identity_store: Optional["IdentityStore"] = None) -> None:
        self._pool = db_pool
        self._identity_store = identity_store
        self.logger = logger

    def _get_identity_store(self) -> "IdentityStore":
        """Return (lazily building) the navigator-auth ``IdentityStore``.

        Built lazily so channel-only deployments do not need the vault
        master keys that ``IdentityCipher`` requires.
        """
        if self._identity_store is None:
            from navigator_auth.identity.store import IdentityStore

            self._identity_store = IdentityStore(self._pool)
        return self._identity_store

    async def upsert_identity(
        self,
        *,
        nav_user_id: str,
        auth_provider: str,
        provider_user_id: str,
        auth_data: Dict[str, Any],
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        token: Optional["TokenResponse"] = None,
    ) -> None:
        """Write one identity row.

        ``provider_user_id`` is REQUIRED: the only usable unique index is
        partial on it being non-NULL, so a NULL re-introduces the 42P10.
        When ``token`` is given the write goes through ``IdentityStore`` so the
        credential is ciphered; otherwise it is a metadata-only channel mapping
        and goes through the SQL above.

        Args:
            nav_user_id: navigator-auth user_id (PK of auth.users).
            auth_provider: Provider key (e.g., ``"telegram"``, ``"jira"``).
            provider_user_id: The account id on the provider side.
            auth_data: Non-secret provider payload (serialized to JSONB).
            display_name: Optional display name override.
            email: Optional email override.
            token: Credential for token-bearing providers.

        Raises:
            ValueError: If ``provider_user_id`` is empty or ``auth_data``
                carries a secret.
            Exception: Any database/cipher failure propagates — callers
                decide how to surface it.
        """
        if provider_user_id is None or str(provider_user_id) == "":
            raise ValueError(
                "provider_user_id is required: a NULL falls outside the partial " "unique index on auth.user_identities"
            )
        provider_user_id = str(provider_user_id)
        data = dict(auth_data or {})
        leaked = _SECRET_KEYS.intersection(data)
        if leaked:
            raise ValueError(f"auth_data must not carry secrets: {sorted(leaked)}")
        payload = json.dumps(data, default=str)

        if token is not None:
            if token.provider_user_id is None:
                token = dataclasses.replace(token, provider_user_id=provider_user_id)
            userinfo: Dict[str, Any] = {"id": provider_user_id}
            if display_name:
                userinfo["name"] = display_name
            if email:
                userinfo["email"] = email
            user_id: Any = int(nav_user_id) if str(nav_user_id).isdigit() else nav_user_id
            identity = await self._get_identity_store().save_linked_identity(
                user_id, auth_provider, token, userinfo=userinfo
            )
            async with self._pool.acquire() as conn:
                await _raw_connection(conn).fetchrow(
                    _STAMP_METADATA_SQL,
                    identity.identity_id,
                    payload,
                    display_name,
                    email,
                )
        else:
            async with self._pool.acquire() as conn:
                row = await _raw_connection(conn).fetchrow(
                    _UPSERT_SQL,
                    str(nav_user_id),
                    auth_provider,
                    provider_user_id,
                    payload,
                    display_name,
                    email,
                )
            if row is None:
                raise RuntimeError(f"identity upsert returned no row (user={nav_user_id} provider={auth_provider})")
        self.logger.info(
            "IdentityMappingService: upserted identity user=%s provider=%s account=%s",
            nav_user_id,
            auth_provider,
            provider_user_id,
        )

    async def get_identity(
        self,
        nav_user_id: str,
        auth_provider: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch a single identity record by (user_id, provider).

        Args:
            nav_user_id: navigator-auth user_id.
            auth_provider: Provider key.

        Returns:
            A dict with ``auth_data``, ``display_name``, ``email``,
            ``identity_id``, ``created_at``, or None if no record exists.
        """
        async with self._pool.acquire() as conn:
            row = await _raw_connection(conn).fetchrow(_GET_SQL, str(nav_user_id), auth_provider)
        if row is None:
            return None
        return self._row_to_dict(row)

    async def get_all_identities(
        self,
        nav_user_id: str,
    ) -> List[Dict[str, Any]]:
        """List all identity records for a user.

        Args:
            nav_user_id: navigator-auth user_id.

        Returns:
            List of identity dicts (empty if no identities are linked).
        """
        async with self._pool.acquire() as conn:
            rows = await _raw_connection(conn).fetch(_GET_ALL_SQL, str(nav_user_id))
        return [self._row_to_dict(r) for r in rows]

    async def delete_identity(
        self,
        nav_user_id: str,
        auth_provider: str,
    ) -> None:
        """Remove the identity record for (user_id, provider).

        No-op if no matching row exists.
        """
        async with self._pool.acquire() as conn:
            await _raw_connection(conn).execute(_DELETE_SQL, str(nav_user_id), auth_provider)
        self.logger.info(
            "IdentityMappingService: deleted identity user=%s provider=%s",
            nav_user_id,
            auth_provider,
        )

    @staticmethod
    def _row_to_dict(row: Any) -> Dict[str, Any]:
        """Convert a DB row (asyncpg Record / dict) to a plain dict."""
        # asyncpg Record supports dict(row); plain dicts work directly.
        try:
            data = dict(row)
        except TypeError:
            # Fall back to attribute access if row is dict-like but not iterable.
            data = {
                k: row[k]
                for k in (
                    "identity_id",
                    "user_id",
                    "auth_provider",
                    "provider_user_id",
                    "auth_data",
                    "display_name",
                    "email",
                    "created_at",
                )
                if k in row
            }
        data["auth_data"] = _decode_auth_data(data.get("auth_data"))
        return data
