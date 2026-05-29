"""
IdentityMappingService — CRUD for navigator-auth ``user_identities``.

Links navigator-auth internal user IDs with external provider identities
(Telegram numeric IDs, Jira account IDs, etc.). Records live in the
``auth.users_identities`` table and have a unique composite key
``(user_id, auth_provider)``.

Uses raw SQL against the ``authdb`` connection pool because the
``UserIdentity`` ORM model from navigator-auth is not always importable
from ai-parrot, and raw SQL keeps the service portable.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


_UPSERT_SQL = """
INSERT INTO auth.user_identities
    (user_id, auth_provider, auth_data, display_name, email, created_at)
VALUES ($1, $2, $3::jsonb, $4, $5, NOW())
ON CONFLICT (user_id, auth_provider)
DO UPDATE SET
    auth_data = EXCLUDED.auth_data,
    display_name = COALESCE(EXCLUDED.display_name, auth.user_identities.display_name),
    email = COALESCE(EXCLUDED.email, auth.user_identities.email)
"""

_GET_SQL = """
SELECT identity_id, user_id, auth_provider, auth_data,
       display_name, email, created_at
FROM auth.user_identities
WHERE user_id = $1 AND auth_provider = $2
LIMIT 1
"""

_GET_ALL_SQL = """
SELECT identity_id, user_id, auth_provider, auth_data,
       display_name, email, created_at
FROM auth.user_identities
WHERE user_id = $1
ORDER BY auth_provider
"""

_DELETE_SQL = """
DELETE FROM auth.user_identities
WHERE user_id = $1 AND auth_provider = $2
"""


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
        ...     auth_data={"account_id": "abc", "cloud_id": "def"},
        ...     display_name="Jane Doe",
        ...     email="jane@example.com",
        ... )
    """

    def __init__(self, db_pool: Any) -> None:
        self._pool = db_pool
        self.logger = logger

    async def upsert_identity(
        self,
        nav_user_id: str,
        auth_provider: str,
        auth_data: Dict[str, Any],
        display_name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> None:
        """Create or update a user identity record.

        Uses ``ON CONFLICT (user_id, auth_provider) DO UPDATE`` so calling
        this method multiple times for the same provider refreshes the
        ``auth_data`` (and optionally ``display_name`` / ``email``).

        Args:
            nav_user_id: navigator-auth user_id (PK of auth.users).
            auth_provider: Provider key (e.g., ``"telegram"``, ``"jira"``).
            auth_data: Provider-specific payload (serialized to JSONB).
            display_name: Optional display name override.
            email: Optional email override.
        """
        payload = json.dumps(auth_data or {})
        async with self._pool.acquire() as conn:
            await conn.execute(
                _UPSERT_SQL,
                nav_user_id,
                auth_provider,
                payload,
                display_name,
                email,
            )
        self.logger.info(
            "IdentityMappingService: upserted identity user=%s provider=%s",
            nav_user_id,
            auth_provider,
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
            row = await conn.fetchrow(_GET_SQL, nav_user_id, auth_provider)
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
            rows = await conn.fetch(_GET_ALL_SQL, nav_user_id)
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
            await conn.execute(_DELETE_SQL, nav_user_id, auth_provider)
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
            data = {k: row[k] for k in (
                "identity_id", "user_id", "auth_provider", "auth_data",
                "display_name", "email", "created_at"
            ) if k in row}
        data["auth_data"] = _decode_auth_data(data.get("auth_data"))
        return data
