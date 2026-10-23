"""
IdentityMappingService — CRUD for navigator-auth ``user_identities``.

Links navigator-auth internal user IDs with external provider identities
(Telegram numeric IDs, Jira account IDs, etc.). Records live in the
``auth.user_identities`` table.

Keying
------
The table's only usable unique index is **partial**::

    UNIQUE (user_id, auth_provider, provider_user_id) WHERE provider_user_id IS NOT NULL

There is deliberately no unique index on ``(user_id, auth_provider)``: the
canonical navigator-auth schema lets one user hold several accounts on the
same provider, discriminated by ``provider_user_id``. Every write therefore
carries a non-NULL ``provider_user_id`` — a NULL falls outside the partial
index, so Postgres cannot arbitrate it and the row would be duplicated
instead of updated.

Credentials
-----------
A caller that holds a real OAuth grant passes ``token=TokenResponse(...)``:
the write then goes through navigator-auth's ``IdentityStore``, which seals
every token column with the vault master keys, bound to
``(user_id, auth_provider, provider_user_id, column)``. Tokens never reach
``auth_data``. A channel↔Navigator mapping (Teams, Slack, Telegram) has no
credential at all and takes the metadata-only SQL path below.

Driver
------
``app["authdb"]`` is an **asyncdb** pool (``navigator_auth.storages.postgres``
builds it with ``driver="pg"``), which is also what ``IdentityStore``
expects. Its ``execute()`` *swallows* most Postgres errors and returns
``[result, error]`` instead of raising, so every write here goes through
``fetch_one`` with a ``RETURNING`` clause, or checks the returned error
explicitly. Failures raise :class:`IdentityWriteError`; this service never
logs-and-continues, because that is precisely what hid a 100 %-failure bug
for the lifetime of this code (``issue:0115386145f2``).
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from navigator_auth.identity.types import TokenResponse

logger = logging.getLogger(__name__)


class IdentityWriteError(RuntimeError):
    """An ``auth.user_identities`` row could not be written or removed."""


_UPSERT_SQL = """
INSERT INTO auth.user_identities
    (user_id, auth_provider, provider_user_id, auth_data,
     display_name, email, created_at)
VALUES ($1, $2, $3, $4::text::jsonb, $5, $6, NOW())
ON CONFLICT (user_id, auth_provider, provider_user_id)
    WHERE provider_user_id IS NOT NULL
DO UPDATE SET
    auth_data = EXCLUDED.auth_data,
    display_name = COALESCE(EXCLUDED.display_name, auth.user_identities.display_name),
    email = COALESCE(EXCLUDED.email, auth.user_identities.email)
RETURNING identity_id, user_id, auth_provider, provider_user_id, auth_data,
          display_name, email, created_at
"""

# ``$4::text::jsonb`` rather than ``$4::jsonb``: with the single cast asyncpg
# infers the parameter as jsonb and encodes the Python ``str`` as a JSON
# *string scalar*, so ``||`` appends it instead of merging it (the row ends up
# as ``[{profile}, "{...}"]``). Forcing text first makes Postgres parse it.
#
# Non-secret columns for the credential path: IdentityStore writes the sealed
# token columns and a filtered OIDC-ish profile into auth_data, and never
# touches display_name/email or provider-specific keys such as Jira's
# cloud_id. This merge keeps the row as informative as the SQL path's.
_MERGE_PROFILE_SQL = """
UPDATE auth.user_identities
   SET auth_data = COALESCE(auth_data, '{}'::jsonb) || $4::text::jsonb,
       display_name = COALESCE($5, display_name),
       email = COALESCE($6, email)
 WHERE user_id = $1 AND auth_provider = $2 AND provider_user_id = $3
RETURNING identity_id, user_id, auth_provider, provider_user_id, auth_data,
          display_name, email, created_at
"""

_GET_SQL = """
SELECT identity_id, user_id, auth_provider, provider_user_id, auth_data,
       display_name, email, created_at
FROM auth.user_identities
WHERE user_id = $1 AND auth_provider = $2
  AND ($3::varchar IS NULL OR provider_user_id = $3)
ORDER BY created_at DESC
LIMIT 1
"""

_GET_ALL_SQL = """
SELECT identity_id, user_id, auth_provider, provider_user_id, auth_data,
       display_name, email, created_at
FROM auth.user_identities
WHERE user_id = $1
ORDER BY auth_provider, created_at DESC
"""

_DELETE_SQL = """
DELETE FROM auth.user_identities
WHERE user_id = $1 AND auth_provider = $2
  AND ($3::varchar IS NULL OR provider_user_id = $3)
"""


def _coerce_user_id(nav_user_id: Any) -> Any:
    """Coerce ``nav_user_id`` to the type ``auth.user_identities.user_id`` has.

    The column is ``bigint``; a bound parameter is typed, so asyncpg rejects
    the string form (``'1'``) outright instead of letting Postgres cast it.
    Sessions routinely carry the id as a string, and all four call sites pass
    ``str(nav_user_id)``.

    Args:
        nav_user_id: The navigator-auth user identifier.

    Returns:
        ``int`` for an integer or digit-only string, otherwise the value
        unchanged (some navigator-auth schemas key users by UUID).
    """
    if isinstance(nav_user_id, bool):
        return nav_user_id
    if isinstance(nav_user_id, int):
        return nav_user_id
    if isinstance(nav_user_id, str) and nav_user_id.strip().isdigit():
        return int(nav_user_id.strip())
    return nav_user_id


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


async def _fetch_one(conn: Any, sentence: str, *args: Any) -> Any:
    """Run a single-row query, raising whatever the driver raises.

    asyncdb's pg driver exposes ``fetch_one(sentence, *args)``; raw asyncpg
    connections expose ``fetchrow(sentence, *args)``. Production injects the
    asyncdb pool, but the service has always been documented as taking "an
    asyncpg-compatible pool", so both are accepted rather than failing with
    an obscure ``TypeError``.
    """
    if hasattr(conn, "fetch_one"):
        return await conn.fetch_one(sentence, *args)
    return await conn.fetchrow(sentence, *args)


def _driver_error(result: Any) -> Optional[str]:
    """The error asyncdb's ``execute()`` returns instead of raising.

    asyncdb's pg driver returns ``[result, error]`` and only re-raises a
    handful of integrity errors; everything else — the 42P10 that broke every
    write of this service — arrives as a message in the second slot.
    """
    if isinstance(result, (tuple, list)) and len(result) == 2 and result[1]:
        return str(result[1])
    return None


class IdentityMappingService:
    """CRUD service for ``auth.user_identities`` records.

    Args:
        db_pool: The navigator-auth ``authdb`` pool (``app["authdb"]``), an
            asyncdb ``pg`` pool.

    Example:
        >>> service = IdentityMappingService(db_pool=app["authdb"])
        >>> await service.upsert_identity(
        ...     nav_user_id="35",
        ...     auth_provider="telegram",
        ...     provider_user_id="483920114",
        ...     auth_data={"telegram_id": 483920114, "username": "jane"},
        ...     display_name="Jane Doe",
        ...     email="jane@example.com",
        ... )
    """

    def __init__(self, db_pool: Any) -> None:
        self._pool = db_pool
        self.logger = logger

    async def upsert_identity(
        self,
        *,
        nav_user_id: Any,
        auth_provider: str,
        provider_user_id: Any,
        auth_data: Dict[str, Any],
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        token: Optional["TokenResponse"] = None,
    ) -> Dict[str, Any]:
        """Write one identity row, and return it as it landed.

        ``provider_user_id`` is required: the only usable unique index is
        partial on it being non-NULL, so a NULL re-introduces the ``42P10``
        this method used to fail with on every call — or, once arbitration is
        skipped, silently duplicates the row.

        When ``token`` is given the credential is written through
        navigator-auth's ``IdentityStore`` (sealed with the vault master
        keys) and the non-secret columns are merged on top; otherwise this is
        a metadata-only channel mapping and goes through plain SQL.

        Args:
            nav_user_id: navigator-auth ``user_id`` (``auth.users`` PK).
            auth_provider: Provider key (``"telegram"``, ``"jira"``, …).
            provider_user_id: The external account id on that provider.
            auth_data: Provider-specific, non-secret payload (JSONB).
            display_name: Optional display name override.
            email: Optional email override.
            token: The OAuth grant, when one exists. Never put a token in
                ``auth_data``.

        Returns:
            The stored row as a dict, with ``auth_data`` decoded.

        Raises:
            IdentityWriteError: If the row cannot be written. Callers must
                not swallow this silently — see the module docstring.
        """
        account = self._require_account_id(auth_provider, provider_user_id)
        user_id = _coerce_user_id(nav_user_id)
        payload = json.dumps(auth_data or {})

        if token is not None:
            return await self._store_credential(
                user_id=user_id,
                auth_provider=auth_provider,
                provider_user_id=account,
                payload=payload,
                display_name=display_name,
                email=email,
                token=token,
            )

        try:
            async with self._pool.acquire() as conn:
                row = await _fetch_one(
                    conn,
                    _UPSERT_SQL,
                    user_id,
                    auth_provider,
                    account,
                    payload,
                    display_name,
                    email,
                )
        except IdentityWriteError:
            raise
        except Exception as err:  # noqa: BLE001 — re-raised with context below
            raise IdentityWriteError(
                f"identity upsert failed for user={nav_user_id} "
                f"provider={auth_provider} account={account}: {err}"
            ) from err
        if row is None:
            raise IdentityWriteError(
                f"identity upsert returned no row for user={nav_user_id} "
                f"provider={auth_provider} account={account}"
            )
        self.logger.info(
            "IdentityMappingService: upserted identity user=%s provider=%s account=%s",
            nav_user_id,
            auth_provider,
            account,
        )
        return self._row_to_dict(row)

    async def _store_credential(
        self,
        *,
        user_id: Any,
        auth_provider: str,
        provider_user_id: str,
        payload: str,
        display_name: Optional[str],
        email: Optional[str],
        token: "TokenResponse",
    ) -> Dict[str, Any]:
        """Seal the credential through ``IdentityStore``, then merge metadata.

        ``save_linked_identity`` is navigator-auth's only write path and the
        same one ``TokenExchangeAuth`` uses, so the credential has a single
        writer. It writes the sealed token columns plus a filtered profile
        into ``auth_data``; ``_MERGE_PROFILE_SQL`` then adds the
        provider-specific keys and the ``display_name`` / ``email`` columns it
        does not touch.
        """
        try:
            from navigator_auth.identity.store import IdentityStore
        except ImportError as err:  # pragma: no cover - navigator-auth is a hard dep
            raise IdentityWriteError(
                f"navigator-auth IdentityStore is unavailable: {err}"
            ) from err

        if token.provider_user_id is None:
            token.provider_user_id = provider_user_id
        elif str(token.provider_user_id) != provider_user_id:
            raise IdentityWriteError(
                "token.provider_user_id "
                f"({token.provider_user_id!r}) does not match provider_user_id "
                f"({provider_user_id!r}); the credential would be sealed for "
                "another account"
            )

        userinfo = {
            key: value
            for key, value in (
                ("sub", provider_user_id),
                ("name", display_name),
                ("displayName", display_name),
                ("email", email),
            )
            if value
        }
        try:
            store = IdentityStore(self._pool)
            await store.save_linked_identity(
                user_id, auth_provider, token, userinfo=userinfo
            )
            async with self._pool.acquire() as conn:
                row = await _fetch_one(
                    conn,
                    _MERGE_PROFILE_SQL,
                    user_id,
                    auth_provider,
                    provider_user_id,
                    payload,
                    display_name,
                    email,
                )
        except IdentityWriteError:
            raise
        except Exception as err:  # noqa: BLE001 — re-raised with context below
            raise IdentityWriteError(
                f"identity credential write failed for user={user_id} "
                f"provider={auth_provider} account={provider_user_id}: {err}"
            ) from err
        if row is None:
            raise IdentityWriteError(
                f"identity credential write left no row for user={user_id} "
                f"provider={auth_provider} account={provider_user_id}"
            )
        self.logger.info(
            "IdentityMappingService: sealed credential user=%s provider=%s account=%s",
            user_id,
            auth_provider,
            provider_user_id,
        )
        return self._row_to_dict(row)

    async def get_identity(
        self,
        nav_user_id: Any,
        auth_provider: str,
        provider_user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch one identity record.

        Args:
            nav_user_id: navigator-auth user_id.
            auth_provider: Provider key.
            provider_user_id: Narrow to one external account. Without it the
                most recently created account on that provider is returned,
                which is ambiguous for a user holding several.

        Returns:
            The identity dict, or None if no record exists.
        """
        async with self._pool.acquire() as conn:
            row = await _fetch_one(
                conn,
                _GET_SQL,
                _coerce_user_id(nav_user_id),
                auth_provider,
                provider_user_id,
            )
        if row is None:
            return None
        return self._row_to_dict(row)

    async def get_all_identities(self, nav_user_id: Any) -> List[Dict[str, Any]]:
        """List every identity record of a user (empty when none are linked)."""
        async with self._pool.acquire() as conn:
            user_id = _coerce_user_id(nav_user_id)
            if hasattr(conn, "fetch_all"):
                rows = await conn.fetch_all(_GET_ALL_SQL, user_id)
            else:
                rows = await conn.fetch(_GET_ALL_SQL, user_id)
        return [self._row_to_dict(r) for r in rows or []]

    async def delete_identity(
        self,
        nav_user_id: Any,
        auth_provider: str,
        provider_user_id: Optional[str] = None,
    ) -> None:
        """Remove identity records for a provider.

        Args:
            nav_user_id: navigator-auth user_id.
            auth_provider: Provider key.
            provider_user_id: Delete only this external account. Without it
                EVERY account the user holds on that provider is removed.

        Raises:
            IdentityWriteError: If the delete fails.
        """
        user_id = _coerce_user_id(nav_user_id)
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    _DELETE_SQL, user_id, auth_provider, provider_user_id
                )
        except Exception as err:  # noqa: BLE001 — re-raised with context below
            raise IdentityWriteError(
                f"identity delete failed for user={nav_user_id} "
                f"provider={auth_provider}: {err}"
            ) from err
        error = _driver_error(result)
        if error:
            raise IdentityWriteError(
                f"identity delete failed for user={nav_user_id} "
                f"provider={auth_provider}: {error}"
            )
        self.logger.info(
            "IdentityMappingService: deleted identity user=%s provider=%s account=%s",
            nav_user_id,
            auth_provider,
            provider_user_id,
        )

    @staticmethod
    def _require_account_id(auth_provider: str, provider_user_id: Any) -> str:
        """Validate ``provider_user_id`` and return it as a string.

        Raises:
            IdentityWriteError: If it is missing or blank. A NULL
                ``provider_user_id`` is excluded by the partial unique index,
                so the upsert cannot arbitrate and would duplicate the row.
        """
        if provider_user_id is None:
            raise IdentityWriteError(
                f"provider_user_id is required for provider {auth_provider!r}: "
                "the unique index is partial on it being non-NULL"
            )
        account = str(provider_user_id).strip()
        if not account:
            raise IdentityWriteError(
                f"provider_user_id is empty for provider {auth_provider!r}"
            )
        return account

    @staticmethod
    def _row_to_dict(row: Any) -> Dict[str, Any]:
        """Convert a DB row (asyncpg Record / dict) to a plain dict."""
        # asyncpg Record supports dict(row); plain dicts work directly.
        try:
            data = dict(row)
        except TypeError:
            # Fall back to attribute access if row is dict-like but not iterable.
            data = {k: row[k] for k in (
                "identity_id", "user_id", "auth_provider", "provider_user_id",
                "auth_data", "display_name", "email", "created_at"
            ) if k in row}
        data["auth_data"] = _decode_auth_data(data.get("auth_data"))
        return data
