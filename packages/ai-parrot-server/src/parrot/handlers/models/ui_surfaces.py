"""PgUISurfaceStore — persistence for the ui_surfaces plane (FEAT-492).

Owns two auto-created Postgres tables:

- ``navigator.ui_surfaces`` — the persisted A2UI surface (dashboard,
  infographic, or widget) with its rehydratable envelope and, when it was
  produced by a recipe, the ``recipe_ref`` needed for in-place refresh.
- ``navigator.ui_surface_shares`` — opaque, revocable, DB-stored share
  tokens granting read+refresh access; ``claimed_by``/``claimed_at`` record
  which authenticated user first redeemed a token (shared-with-me listing).

Follows the ``AsyncDB("pg", dsn=default_dsn)`` per-call idiom used by
``handlers/comm_center.py`` (``_get_db()`` + ``async with await
db.connection() as conn:``) and the ``CREATE TABLE IF NOT EXISTS`` auto-create
convention illustrated by ``handlers/models/bots.py`` /
``autonomous/ledger.py``.
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Literal

from asyncdb import AsyncDB
from parrot.conf import default_dsn
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class UISurfaceKind(str, Enum):
    """Kind of persisted A2UI surface."""

    dashboard = "dashboard"
    infographic = "infographic"
    widget = "widget"


class UISurfaceRecord(BaseModel):
    """Row shape of ``navigator.ui_surfaces``."""

    surface_id: str
    kind: UISurfaceKind
    title: str
    envelope: dict[str, Any]
    catalog_id: str | None = None
    agent_id: str
    user_id: str
    session_id: str | None = None
    recipe_name: str | None = None
    recipe_owner: str | None = None
    recipe_params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @property
    def refreshable(self) -> bool:
        """Whether this surface can be refreshed via ``RecipeRunner`` replay."""
        return self.recipe_name is not None


class UISurfaceShare(BaseModel):
    """Row shape of ``navigator.ui_surface_shares``."""

    token: str
    surface_id: str
    permissions: Literal["read+refresh"] = "read+refresh"
    expires_at: datetime | None = None
    revoked: bool = False
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# DDL — idempotent auto-create (handlers/models/bots.py idiom)
# ---------------------------------------------------------------------------

_DDL_STATEMENTS: list[str] = [
    "CREATE SCHEMA IF NOT EXISTS navigator",
    """
    CREATE TABLE IF NOT EXISTS navigator.ui_surfaces (
        surface_id UUID PRIMARY KEY,
        kind VARCHAR(32) NOT NULL,
        title TEXT NOT NULL,
        envelope JSONB NOT NULL,
        catalog_id VARCHAR,
        agent_id VARCHAR NOT NULL,
        user_id VARCHAR NOT NULL,
        session_id VARCHAR,
        recipe_name VARCHAR,
        recipe_owner VARCHAR,
        recipe_params JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_ui_surfaces_user ON navigator.ui_surfaces (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_ui_surfaces_user_kind ON navigator.ui_surfaces (user_id, kind)",
    """
    CREATE TABLE IF NOT EXISTS navigator.ui_surface_shares (
        token TEXT PRIMARY KEY,
        surface_id UUID NOT NULL REFERENCES navigator.ui_surfaces(surface_id) ON DELETE CASCADE,
        permissions VARCHAR(32) NOT NULL DEFAULT 'read+refresh',
        expires_at TIMESTAMPTZ,
        revoked BOOLEAN NOT NULL DEFAULT FALSE,
        claimed_by TEXT,
        claimed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_ui_surface_shares_surface ON navigator.ui_surface_shares (surface_id)",
    "CREATE INDEX IF NOT EXISTS ix_ui_surface_shares_claimed_by ON navigator.ui_surface_shares (claimed_by)",
]


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_INSERT_SQL = """
INSERT INTO navigator.ui_surfaces
    (surface_id, kind, title, envelope, catalog_id, agent_id, user_id,
     session_id, recipe_name, recipe_owner, recipe_params, created_at, updated_at)
VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13)
"""

_UPSERT_SQL = _INSERT_SQL + """
ON CONFLICT (surface_id) DO UPDATE SET
    kind = EXCLUDED.kind,
    title = EXCLUDED.title,
    envelope = EXCLUDED.envelope,
    catalog_id = EXCLUDED.catalog_id,
    agent_id = EXCLUDED.agent_id,
    user_id = EXCLUDED.user_id,
    session_id = EXCLUDED.session_id,
    recipe_name = EXCLUDED.recipe_name,
    recipe_owner = EXCLUDED.recipe_owner,
    recipe_params = EXCLUDED.recipe_params,
    updated_at = EXCLUDED.updated_at
"""

_GET_SQL = """
SELECT surface_id, kind, title, envelope, catalog_id, agent_id, user_id,
       session_id, recipe_name, recipe_owner, recipe_params, created_at, updated_at
FROM navigator.ui_surfaces
WHERE surface_id = $1
"""

_LIST_SQL = _GET_SQL.replace("WHERE surface_id = $1", "WHERE user_id = $1") + "\nORDER BY updated_at DESC"

_LIST_BY_KIND_SQL = (
    _GET_SQL.replace("WHERE surface_id = $1", "WHERE user_id = $1 AND kind = $2")
    + "\nORDER BY updated_at DESC"
)

_LIST_SHARED_WITH_SQL = """
SELECT surface_id, kind, title, envelope, catalog_id, agent_id, user_id,
       session_id, recipe_name, recipe_owner, recipe_params, created_at, updated_at
FROM navigator.ui_surfaces
WHERE surface_id IN (
    SELECT surface_id FROM navigator.ui_surface_shares
    WHERE claimed_by = $1 AND revoked = FALSE
      AND (expires_at IS NULL OR expires_at > NOW())
)
ORDER BY updated_at DESC
"""

_UPDATE_ENVELOPE_SQL = """
UPDATE navigator.ui_surfaces
SET envelope = $2::jsonb, recipe_params = $3::jsonb, updated_at = NOW()
WHERE surface_id = $1
"""

_DELETE_SQL = """
DELETE FROM navigator.ui_surfaces
WHERE surface_id = $1 AND user_id = $2
RETURNING surface_id
"""

_MINT_SHARE_SQL = """
INSERT INTO navigator.ui_surface_shares
    (token, surface_id, permissions, expires_at, revoked, created_at)
VALUES ($1, $2, 'read+refresh', $3, FALSE, $4)
"""

_RESOLVE_SHARE_SQL = """
SELECT token, surface_id, permissions, expires_at, revoked, claimed_by, claimed_at, created_at
FROM navigator.ui_surface_shares
WHERE token = $1 AND revoked = FALSE AND (expires_at IS NULL OR expires_at > NOW())
"""

_CLAIM_SHARE_SQL = """
UPDATE navigator.ui_surface_shares
SET claimed_by = $2, claimed_at = NOW()
WHERE token = $1 AND claimed_by IS NULL
"""

_REVOKE_SHARE_SQL = """
UPDATE navigator.ui_surface_shares
SET revoked = TRUE
WHERE token = $1 AND surface_id = $2
RETURNING token
"""

_LIST_SHARES_SQL = """
SELECT token, surface_id, permissions, expires_at, revoked, claimed_by, claimed_at, created_at
FROM navigator.ui_surface_shares
WHERE surface_id = $1
ORDER BY created_at DESC
"""


def _looks_like_unique_violation(exc: Exception) -> bool:
    """Detect a Postgres unique-constraint violation from an insert error.

    Mirrors ``handlers/comm_center.py::_looks_like_unique_violation`` —
    prefers a precise ``asyncpg.exceptions.UniqueViolationError`` check and
    falls back to a message-content heuristic in case ``asyncdb`` re-wraps
    the original exception into one of its own types.

    Args:
        exc: The exception raised by the ``INSERT``.

    Returns:
        ``True`` if ``exc`` looks like a duplicate ``surface_id`` violation.
    """
    try:
        import asyncpg.exceptions as pg_exceptions

        if isinstance(exc, pg_exceptions.UniqueViolationError):
            return True
    except ImportError:
        pass
    message = str(exc).lower()
    return "unique" in message or "duplicate key" in message


def _decode_jsonb(raw: Any) -> dict[str, Any]:
    """Normalize a JSONB column value into a plain ``dict``.

    Depending on the driver's codec configuration, the value may already be
    a ``dict`` (asyncpg with the jsonb codec registered) or a JSON-encoded
    string/bytes.
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
            logger.warning("Could not decode JSONB column: %r", raw[:80])
            return {}
    return {}


def _row_to_record(row: Any) -> UISurfaceRecord:
    """Convert a DB row (asyncpg Record / dict) into a ``UISurfaceRecord``."""
    data = dict(row)
    return UISurfaceRecord(
        surface_id=str(data["surface_id"]),
        kind=UISurfaceKind(data["kind"]),
        title=data["title"],
        envelope=_decode_jsonb(data.get("envelope")),
        catalog_id=data.get("catalog_id"),
        agent_id=data["agent_id"],
        user_id=data["user_id"],
        session_id=data.get("session_id"),
        recipe_name=data.get("recipe_name"),
        recipe_owner=data.get("recipe_owner"),
        recipe_params=_decode_jsonb(data.get("recipe_params")),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


def _row_to_share(row: Any) -> UISurfaceShare:
    """Convert a DB row (asyncpg Record / dict) into a ``UISurfaceShare``."""
    data = dict(row)
    return UISurfaceShare(
        token=data["token"],
        surface_id=str(data["surface_id"]),
        permissions=data.get("permissions") or "read+refresh",
        expires_at=data.get("expires_at"),
        revoked=bool(data.get("revoked")),
        claimed_by=data.get("claimed_by"),
        claimed_at=data.get("claimed_at"),
        created_at=data["created_at"],
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class PgUISurfaceStore:
    """Postgres store for persisted A2UI surfaces + share tokens.

    Args:
        dsn: Optional connection string; defaults to
            :data:`parrot.conf.default_dsn` (spec §8 resolved decision).
    """

    #: Default share-token TTL (days) applied when a caller requests a TTL
    #: without an explicit ``expires_at`` (spec §8 resolved decision).
    DEFAULT_SHARE_TTL_DAYS = 90

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or default_dsn
        self.logger = logger
        self._schema_ensured = False

    def _get_db(self) -> AsyncDB:
        """Construct a fresh ``pg`` :class:`AsyncDB` wrapper for this store."""
        return AsyncDB("pg", dsn=self.dsn)

    async def _ensure_ready(self) -> None:
        """Lazily run :meth:`ensure_schema` on first store use."""
        if not self._schema_ensured:
            await self.ensure_schema()

    async def ensure_schema(self) -> None:
        """Create ``navigator.ui_surfaces`` / ``ui_surface_shares`` if missing.

        Idempotent — ``CREATE ... IF NOT EXISTS`` everywhere. Tolerates
        duplicate-object races under concurrent first-calls (two workers
        racing to auto-create the same index/table).
        """
        db = self._get_db()
        async with await db.connection() as conn:
            for stmt in _DDL_STATEMENTS:
                try:
                    await conn.execute(stmt)
                except Exception as exc:
                    if "already exists" in str(exc).lower():
                        self.logger.debug("ui_surfaces DDL race tolerated: %s", exc)
                        continue
                    raise
        self._schema_ensured = True
        self.logger.info("ui_surfaces schema ensured")

    async def save(self, record: UISurfaceRecord, *, overwrite: bool = False) -> str:
        """Persist a :class:`UISurfaceRecord`.

        Args:
            record: The surface row to persist.
            overwrite: When ``True``, upsert (``ON CONFLICT ... DO UPDATE``).
                When ``False`` (default), a duplicate ``surface_id`` raises
                ``ValueError``.

        Returns:
            The persisted ``surface_id``.
        """
        await self._ensure_ready()
        db = self._get_db()
        sql = _UPSERT_SQL if overwrite else _INSERT_SQL
        async with await db.connection() as conn:
            try:
                await conn.execute(
                    sql,
                    record.surface_id,
                    record.kind.value,
                    record.title,
                    json.dumps(record.envelope),
                    record.catalog_id,
                    record.agent_id,
                    record.user_id,
                    record.session_id,
                    record.recipe_name,
                    record.recipe_owner,
                    json.dumps(record.recipe_params),
                    record.created_at,
                    record.updated_at,
                )
            except Exception as exc:
                if not overwrite and _looks_like_unique_violation(exc):
                    raise ValueError(
                        f"UI surface {record.surface_id!r} already exists "
                        "(use overwrite=True to replace it)"
                    ) from exc
                raise
        return record.surface_id

    async def get(self, surface_id: str) -> UISurfaceRecord | None:
        """Fetch a surface by id, or ``None`` if it does not exist."""
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            row = await conn.fetchrow(_GET_SQL, surface_id)
        return _row_to_record(row) if row is not None else None

    async def list(
        self, user_id: str, *, kind: UISurfaceKind | None = None
    ) -> list[UISurfaceRecord]:
        """List surfaces owned by ``user_id``, optionally filtered by ``kind``."""
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            if kind is not None:
                rows = await conn.fetchall(_LIST_BY_KIND_SQL, user_id, kind.value)
            else:
                rows = await conn.fetchall(_LIST_SQL, user_id)
        return [_row_to_record(r) for r in rows]

    async def list_shared_with(self, user_id: str) -> list[UISurfaceRecord]:
        """List surfaces reachable via a live share token claimed by ``user_id``."""
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            rows = await conn.fetchall(_LIST_SHARED_WITH_SQL, user_id)
        return [_row_to_record(r) for r in rows]

    async def update_envelope(
        self, surface_id: str, envelope: dict[str, Any], recipe_params: dict[str, Any]
    ) -> None:
        """Replace ``envelope``/``recipe_params`` in place, bumping ``updated_at``."""
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            await conn.execute(
                _UPDATE_ENVELOPE_SQL, surface_id, json.dumps(envelope), json.dumps(recipe_params)
            )

    async def delete(self, surface_id: str, user_id: str) -> bool:
        """Delete a surface owned by ``user_id``. Returns ``True`` if a row was removed."""
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            result = await conn.fetchval(_DELETE_SQL, surface_id, user_id)
        return result is not None

    async def mint_share(
        self,
        surface_id: str,
        *,
        expires_at: datetime | None = None,
        use_default_ttl: bool = False,
    ) -> UISurfaceShare:
        """Mint a new opaque share token granting read+refresh access.

        Args:
            surface_id: The surface this token grants access to.
            expires_at: Explicit expiry. Takes precedence over
                ``use_default_ttl`` when set.
            use_default_ttl: When ``True`` and ``expires_at`` is not given,
                default to :attr:`DEFAULT_SHARE_TTL_DAYS` (90 days) from now
                (spec §8 resolved decision). Default: no expiry.
        """
        await self._ensure_ready()
        token = secrets.token_urlsafe(32)
        if expires_at is None and use_default_ttl:
            expires_at = datetime.now(UTC) + timedelta(days=self.DEFAULT_SHARE_TTL_DAYS)
        created_at = datetime.now(UTC)
        db = self._get_db()
        async with await db.connection() as conn:
            await conn.execute(_MINT_SHARE_SQL, token, surface_id, expires_at, created_at)
        return UISurfaceShare(
            token=token,
            surface_id=surface_id,
            permissions="read+refresh",
            expires_at=expires_at,
            revoked=False,
            claimed_by=None,
            claimed_at=None,
            created_at=created_at,
        )

    async def resolve_share(self, token: str) -> UISurfaceShare | None:
        """Resolve a live (non-revoked, non-expired) share token.

        Returns ``None`` for a missing, revoked, or expired token —
        indistinguishable by design (no existence oracle).
        """
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            row = await conn.fetchrow(_RESOLVE_SHARE_SQL, token)
        return _row_to_share(row) if row is not None else None

    async def claim_share(self, token: str, user_id: str) -> None:
        """Record ``user_id`` as the first authenticated claimant of ``token``.

        Idempotent: only sets ``claimed_by``/``claimed_at`` when unset — the
        first authenticated user wins; later users still get read access via
        the token, but shared-with-me listing keeps the original claimant.
        """
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            await conn.execute(_CLAIM_SHARE_SQL, token, user_id)

    async def revoke_share(self, token: str, surface_id: str) -> bool:
        """Revoke a share token. Returns ``True`` if a matching token was found."""
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            result = await conn.fetchval(_REVOKE_SHARE_SQL, token, surface_id)
        return result is not None

    async def list_shares(self, surface_id: str) -> list[UISurfaceShare]:
        """List every share token (live or not) minted for ``surface_id``."""
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            rows = await conn.fetchall(_LIST_SHARES_SQL, surface_id)
        return [_row_to_share(r) for r in rows]
