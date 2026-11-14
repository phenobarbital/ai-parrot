"""PostgreSQL conversation backend using asyncpg via asyncdb[pg].

Production-grade backend for GCP deployments and dev environments with a
shared Postgres instance. Uses JSONB for payload columns.

Requirements:
  - Postgres 12+ (JSONB, GIN indexes assumed).
  - ``PARROT_POSTGRES_DSN`` environment variable.

Limitations:
  - No schema migrations in v1 — auto-create only handles first init.
  - Connection pool config is backend-internal (not surfaced on the ABC).

FEAT-116: dynamodb-fallback-redis — Module 5 (Postgres backend).
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple

from navconfig.logging import logging

from parrot.storage.backends.base import BackfillBatch, ConversationBackend
from parrot.storage.errors import (
    ConversationDeletedError,
    IndexNotReadyError,
    StorageError,
    StorageUnavailableError,
    StorageWriteError,
)


def _chrono_fields(data: dict) -> Tuple[Optional[datetime], int]:
    """Return ``(timestamp_utc, sequence)`` from a turn payload (``None`` timestamp when unusable).

    Naive values are read as UTC; a non-int / negative ``sequence`` yields ``0``.
    """
    raw = data.get("timestamp")
    ts: Optional[datetime] = None
    if isinstance(raw, datetime):
        ts = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            ts = datetime.fromisoformat(raw.strip())
        except ValueError:
            ts = None
    if ts is not None:
        ts = (ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts).astimezone(timezone.utc)
    seq = data.get("sequence")
    valid_seq = isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0
    return ts, (seq if valid_seq else 0)


# Fix #4: explicit JSONB codec registered on every new connection so that
# asyncpg sends/receives Python dicts natively rather than relying on an
# implicit TEXT↔JSONB cast. This removes the json.dumps() at every write site
# and eliminates the fragile asymmetry (write: str, read: dict).
async def _set_jsonb_codec(conn) -> None:
    """asyncpg connection initialiser: register Python dict ↔ JSONB codec."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


class ConversationPostgresBackend(ConversationBackend):
    """Async PostgreSQL implementation of ConversationBackend.

    Uses asyncpg directly (via a thin wrapper) for JSONB support.
    Every ``put_*`` operation uses ``INSERT ... ON CONFLICT ... DO UPDATE``
    semantics to match DynamoDB's overwrite-or-create behaviour.

    Args:
        dsn: PostgreSQL DSN, e.g.
            ``"postgresql://user:pw@host:5432/parrot"``.
        default_ttl_days: TTL for new rows in days (default 180).
    """

    DEFAULT_TTL_DAYS = 180

    _CREATE_CONVERSATIONS = """
        CREATE TABLE IF NOT EXISTS parrot_conversations (
            user_id     TEXT NOT NULL,
            agent_id    TEXT NOT NULL,
            session_id  TEXT NOT NULL,
            kind        TEXT NOT NULL,
            sort_key    TEXT NOT NULL,
            payload     JSONB NOT NULL,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at  TIMESTAMPTZ,
            PRIMARY KEY (user_id, agent_id, session_id, kind, sort_key)
        )
    """
    _CREATE_CONV_IDX_USER_AGENT = """
        CREATE INDEX IF NOT EXISTS idx_parrot_conv_user_agent
        ON parrot_conversations(user_id, agent_id, updated_at DESC)
    """
    _CREATE_CONV_IDX_GIN = """
        CREATE INDEX IF NOT EXISTS idx_parrot_conv_payload_gin
        ON parrot_conversations USING GIN (payload)
    """
    _CREATE_ARTIFACTS = """
        CREATE TABLE IF NOT EXISTS parrot_artifacts (
            user_id     TEXT NOT NULL,
            agent_id    TEXT NOT NULL,
            session_id  TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            payload     JSONB NOT NULL,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at  TIMESTAMPTZ,
            PRIMARY KEY (user_id, agent_id, session_id, artifact_id)
        )
    """

    _ADD_COLUMNS = (
        "ALTER TABLE parrot_conversations ADD COLUMN IF NOT EXISTS ts_utc TIMESTAMPTZ",
        "ALTER TABLE parrot_conversations ADD COLUMN IF NOT EXISTS seq BIGINT",
        "ALTER TABLE parrot_conversations ADD COLUMN IF NOT EXISTS turn_id TEXT",
    )
    _CREATE_CHRONO_IDX = """
        CREATE INDEX IF NOT EXISTS idx_parrot_conv_turn_chrono
        ON parrot_conversations (user_id, agent_id, session_id, kind, ts_utc DESC, seq DESC, turn_id COLLATE "C" DESC)
    """
    _CREATE_TOMBSTONES = """
        CREATE TABLE IF NOT EXISTS parrot_conversation_tombstones (
            user_id    TEXT NOT NULL,
            agent_id   TEXT NOT NULL,
            session_id TEXT NOT NULL,
            turn_id    TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, agent_id, session_id, turn_id)
        )
    """
    _CREATE_INDEX_STATE = """
        CREATE TABLE IF NOT EXISTS parrot_conversation_index_state (
            user_id    TEXT NOT NULL,
            agent_id   TEXT NOT NULL,
            session_id TEXT NOT NULL,
            state      TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, agent_id, session_id)
        )
    """
    _LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))"
    _DDL_LOCK_KEY = "parrot_conversations:ddl"
    _TOMBSTONE_SQL = (
        "SELECT 1 FROM parrot_conversation_tombstones"
        " WHERE user_id=$1 AND agent_id=$2 AND session_id=$3 AND turn_id IN ('', $4) LIMIT 1"
    )
    # $1..$9: user, agent, session, sort_key, payload, expires_at, ts_utc, seq, turn_id
    _UPSERT_TURN = """
        INSERT INTO parrot_conversations
            (user_id, agent_id, session_id, kind, sort_key, payload, updated_at, expires_at,
             ts_utc, seq, turn_id)
        VALUES ($1, $2, $3, 'turn', $4, $5, now(), $6, $7, $8, $9)
        ON CONFLICT (user_id, agent_id, session_id, kind, sort_key) DO UPDATE SET
            payload = CASE WHEN parrot_conversations.ts_utc IS NULL THEN EXCLUDED.payload
                ELSE ((EXCLUDED.payload - 'timestamp' - 'sequence') || jsonb_strip_nulls(
                    jsonb_build_object('timestamp', parrot_conversations.payload->'timestamp',
                                       'sequence',  parrot_conversations.payload->'sequence'))) END,
            updated_at = now(),
            expires_at = EXCLUDED.expires_at,
            seq = CASE WHEN parrot_conversations.ts_utc IS NULL THEN EXCLUDED.seq
                       ELSE parrot_conversations.seq END,
            turn_id = EXCLUDED.turn_id,
            ts_utc = COALESCE(parrot_conversations.ts_utc, EXCLUDED.ts_utc)
    """
    _SELECT_WINDOW = """
        SELECT c.session_id, c.sort_key, c.payload, c.updated_at FROM parrot_conversations AS c
        WHERE c.user_id=$1 AND c.agent_id=$2 AND c.session_id=$3 AND c.kind='turn'
          AND c.ts_utc IS NOT NULL AND (c.expires_at IS NULL OR c.expires_at > $4)
          AND NOT EXISTS (
              SELECT 1 FROM parrot_conversation_tombstones t
              WHERE t.user_id=c.user_id AND t.agent_id=c.agent_id
                AND t.session_id=c.session_id AND t.turn_id=c.turn_id)
        ORDER BY c.ts_utc DESC, c.seq DESC, c.turn_id COLLATE "C" DESC
        LIMIT $5
    """
    _HAS_UNINDEXED = """
        SELECT 1 FROM parrot_conversations
        WHERE user_id=$1 AND agent_id=$2 AND session_id=$3 AND kind='turn'
          AND ts_utc IS NULL AND (expires_at IS NULL OR expires_at > $4) LIMIT 1
    """
    _SELECT_LEGACY = """
        SELECT c.user_id, c.agent_id, c.session_id, c.sort_key, c.payload
        FROM parrot_conversations AS c
        WHERE c.kind='turn' AND c.ts_utc IS NULL AND (c.expires_at IS NULL OR c.expires_at > $1)
          AND (c.user_id, c.agent_id, c.session_id, c.sort_key) > ($2, $3, $4, $5)
          AND NOT EXISTS (
              SELECT 1 FROM parrot_conversation_tombstones t
              WHERE t.user_id=c.user_id AND t.agent_id=c.agent_id AND t.session_id=c.session_id
                AND t.turn_id IN ('', substr(c.sort_key, 6)))
        ORDER BY c.user_id, c.agent_id, c.session_id, c.sort_key
        LIMIT $6
    """
    _INDEX_ROW_SQL = (
        "UPDATE parrot_conversations SET ts_utc=$1, seq=$2, turn_id=$3"
        " WHERE user_id=$4 AND agent_id=$5 AND session_id=$6 AND kind='turn' AND sort_key=$7"
        " AND ts_utc IS NULL"
    )
    _UPSERT_STATE_SQL = """
        INSERT INTO parrot_conversation_index_state (user_id, agent_id, session_id, state, updated_at)
        VALUES ($1, $2, $3, $4, now())
        ON CONFLICT (user_id, agent_id, session_id) DO UPDATE SET state = EXCLUDED.state, updated_at = now()
    """

    def __init__(self, dsn: str, default_ttl_days: int = 180) -> None:
        self._dsn = dsn
        self._default_ttl_days = default_ttl_days
        self._pool = None
        self._initialized: bool = False
        self.logger = logging.getLogger("parrot.storage.ConversationPostgresBackend")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Open connection pool and create tables (idempotent)."""
        if self._initialized and self._pool is not None:
            return
        import asyncpg  # type: ignore[import]

        # Fix #4: pass _set_jsonb_codec as init so every pooled connection
        # speaks Python-dict↔JSONB natively.
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=1,
            max_size=5,
            init=_set_jsonb_codec,
        )
        async with self._pool.acquire() as conn:
            await conn.execute(self._CREATE_CONVERSATIONS)
            await conn.execute(self._CREATE_CONV_IDX_USER_AGENT)
            await conn.execute(self._CREATE_CONV_IDX_GIN)
            await conn.execute(self._CREATE_ARTIFACTS)
            await self._migrate_chrono_schema(conn)
        self._initialized = True
        self.logger.info("Postgres backend initialized")

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool is not None:
            try:
                await self._pool.close()
            except Exception as exc:
                self.logger.warning("Error closing Postgres pool: %s", exc)
            finally:
                self._pool = None
                self._initialized = False

    @property
    def is_connected(self) -> bool:
        return self._pool is not None and self._initialized

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _expires_at(self) -> Optional[datetime]:
        if self._default_ttl_days <= 0:
            # Fix #6 (Postgres variant): use a past timestamp so the row is
            # immediately expired at query time.
            return datetime.now(timezone.utc) - timedelta(seconds=1)
        return datetime.now(timezone.utc) + timedelta(days=self._default_ttl_days)

    def _not_expired_cond(self) -> datetime:
        return datetime.now(timezone.utc)

    def _row_to_thread(self, record) -> dict:
        d = dict(record)
        # Fix #4: with explicit JSONB codec, payload is already a dict
        payload = d.pop("payload") or {}
        updated_at = d.get("updated_at")
        return {
            "session_id": d["session_id"],
            "updated_at": updated_at.isoformat() if updated_at else None,
            **payload,
        }

    def _row_to_turn(self, record) -> dict:
        d = dict(record)
        payload = d.pop("payload") or {}
        updated_at = d.get("updated_at")
        turn_id = d["sort_key"].replace("TURN#", "", 1)
        return {
            "session_id": d["session_id"],
            "turn_id": turn_id,
            "updated_at": updated_at.isoformat() if updated_at else None,
            **payload,
        }

    def _row_to_artifact(self, record) -> dict:
        d = dict(record)
        payload = d.pop("payload") or {}
        updated_at = d.get("updated_at")
        return {
            "artifact_id": d["artifact_id"],
            "session_id": d["session_id"],
            "updated_at": updated_at.isoformat() if updated_at else None,
            **payload,
        }

    async def _migrate_chrono_schema(self, conn) -> None:
        """Additive, idempotent migration; serialized across pods with a transaction-scoped advisory lock."""
        async with conn.transaction():
            await conn.execute(self._LOCK_SQL, self._DDL_LOCK_KEY)
            for statement in self._ADD_COLUMNS:
                await conn.execute(statement)
            await conn.execute(self._CREATE_CHRONO_IDX)
            await conn.execute(self._CREATE_TOMBSTONES)
            await conn.execute(self._CREATE_INDEX_STATE)

    def _require_connection(self) -> None:
        """Raise ``StorageUnavailableError`` when the backend is not connected."""
        if not self.is_connected:
            raise StorageUnavailableError("Postgres conversation backend is not connected")

    @staticmethod
    def _translate(exc: BaseException, *, write: bool) -> StorageError:
        """Map a driver/transport exception to the typed storage error (never swallow)."""
        import asyncpg  # lazy: optional dependency

        transport = (OSError, asyncio.TimeoutError, asyncpg.InterfaceError, asyncpg.PostgresConnectionError)
        if isinstance(exc, transport):
            return StorageUnavailableError(f"Postgres unavailable: {exc}")
        cls = StorageWriteError if write else StorageUnavailableError
        return cls(f"Postgres operation failed: {exc}")

    @staticmethod
    def _lock_key(user_id: str, agent_id: str, session_id: str) -> str:
        return f"{user_id}\x1f{agent_id}\x1f{session_id}"

    def _encode_payload(self, data: dict) -> dict:
        """Normalize datetime values in a payload dict to ISO strings."""
        return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in data.items()}

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------

    async def put_thread(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        metadata: dict,
    ) -> None:
        if not self.is_connected:
            return
        payload = self._encode_payload(metadata)
        expires = self._expires_at()
        async with self._pool.acquire() as conn:
            # Fix #4: pass dict directly — asyncpg encodes via the registered
            # JSONB codec; no manual json.dumps() needed.
            await conn.execute(
                """
                INSERT INTO parrot_conversations
                    (user_id, agent_id, session_id, kind, sort_key, payload, updated_at, expires_at)
                VALUES ($1, $2, $3, 'thread', 'THREAD', $4, now(), $5)
                ON CONFLICT (user_id, agent_id, session_id, kind, sort_key)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = now(), expires_at = EXCLUDED.expires_at
                """,
                user_id,
                agent_id,
                session_id,
                payload,
                expires,
            )

    async def update_thread(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        **updates,
    ) -> None:
        if not self.is_connected or not updates:
            return
        now = self._not_expired_cond()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT payload FROM parrot_conversations
                WHERE user_id=$1 AND agent_id=$2 AND session_id=$3
                  AND kind='thread' AND sort_key='THREAD'
                  AND (expires_at IS NULL OR expires_at > $4)
                """,
                user_id,
                agent_id,
                session_id,
                now,
            )
            # Fix #4: payload is already a dict (JSONB codec decodes it)
            payload: dict = dict(row["payload"]) if row and row["payload"] else {}
            for k, v in updates.items():
                payload[k] = v.isoformat() if isinstance(v, datetime) else v
            expires = self._expires_at()
            await conn.execute(
                """
                INSERT INTO parrot_conversations
                    (user_id, agent_id, session_id, kind, sort_key, payload, updated_at, expires_at)
                VALUES ($1, $2, $3, 'thread', 'THREAD', $4, now(), $5)
                ON CONFLICT (user_id, agent_id, session_id, kind, sort_key)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = now(), expires_at = EXCLUDED.expires_at
                """,
                user_id,
                agent_id,
                session_id,
                payload,
                expires,
            )

    async def query_threads(
        self,
        user_id: str,
        agent_id: str,
        limit: int = 50,
    ) -> List[dict]:
        if not self.is_connected:
            return []
        now = self._not_expired_cond()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, sort_key, payload, updated_at FROM parrot_conversations
                WHERE user_id=$1 AND agent_id=$2 AND kind='thread'
                  AND (expires_at IS NULL OR expires_at > $3)
                ORDER BY updated_at DESC
                LIMIT $4
                """,
                user_id,
                agent_id,
                now,
                limit,
            )
        return [self._row_to_thread(r) for r in rows]

    # ------------------------------------------------------------------
    # Turns
    # ------------------------------------------------------------------

    async def put_turn(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        turn_id: str,
        data: dict,
    ) -> None:
        """Idempotent upsert by ``turn_id``; tombstone check + upsert in one locked transaction.

        Raises:
            StorageUnavailableError: not connected / transport failure.
            ConversationDeletedError: the session or this turn is tombstoned.
            StorageWriteError: the durable write failed (nothing is swallowed).
        """
        self._require_connection()
        payload = self._encode_payload(data)
        ts, seq = _chrono_fields(data)
        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(self._LOCK_SQL, self._lock_key(user_id, agent_id, session_id))
                    if await conn.fetchval(self._TOMBSTONE_SQL, user_id, agent_id, session_id, turn_id):
                        raise ConversationDeletedError(
                            f"session {session_id} or turn {turn_id} is tombstoned; write rejected"
                        )
                    await conn.execute(
                        self._UPSERT_TURN,
                        user_id,
                        agent_id,
                        session_id,
                        f"TURN#{turn_id}",
                        payload,
                        self._expires_at(),
                        ts,
                        seq,
                        turn_id,
                    )
        except StorageError:
            raise
        except Exception as exc:
            raise self._translate(exc, write=True) from exc

    async def query_turns(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        limit: int = 10,
        newest_first: bool = True,
    ) -> List[dict]:
        self._require_connection()
        now = self._not_expired_cond()
        # Fix #9: avoid f-string SQL — ORDER direction is boolean-derived,
        # never user-supplied, but static analysers flag it as injection risk.
        _ORDER = {True: "DESC", False: "ASC"}
        sql = (
            "SELECT session_id, sort_key, payload, updated_at FROM parrot_conversations"
            " WHERE user_id=$1 AND agent_id=$2 AND session_id=$3 AND kind='turn'"
            "   AND (expires_at IS NULL OR expires_at > $4)"
            f" ORDER BY sort_key {_ORDER[newest_first]}"
            " LIMIT $5"
        )
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, user_id, agent_id, session_id, now, limit)
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        return [self._row_to_turn(r) for r in rows]

    async def delete_turn(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        turn_id: str,
    ) -> bool:
        if not self.is_connected:
            return False
        sort_key = f"TURN#{turn_id}"
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM parrot_conversations
                WHERE user_id=$1 AND agent_id=$2 AND session_id=$3
                  AND kind='turn' AND sort_key=$4
                """,
                user_id,
                agent_id,
                session_id,
                sort_key,
            )
        # asyncpg returns "DELETE N" as the status string
        return int(result.split()[-1]) > 0

    async def delete_thread_cascade(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> int:
        if not self.is_connected:
            return 0
        async with self._pool.acquire() as conn:
            r1 = await conn.execute(
                "DELETE FROM parrot_conversations WHERE user_id=$1 AND agent_id=$2 AND session_id=$3",
                user_id,
                agent_id,
                session_id,
            )
            r2 = await conn.execute(
                "DELETE FROM parrot_artifacts WHERE user_id=$1 AND agent_id=$2 AND session_id=$3",
                user_id,
                agent_id,
                session_id,
            )
        return int(r1.split()[-1]) + int(r2.split()[-1])

    # ------------------------------------------------------------------
    # FEAT-886: ordered window, tombstones, index state, backfill
    # ------------------------------------------------------------------

    async def query_turn_window(self, user_id: str, agent_id: str, session_id: str, limit: int) -> List[dict]:
        """Newest ``limit`` turns by (ts_utc, seq, turn_id), limit applied descending, returned ascending."""
        self._require_connection()
        if await self.is_deleted(user_id, agent_id, session_id):
            raise ConversationDeletedError(f"session {session_id} is tombstoned")
        if await self.get_index_state(user_id, agent_id, session_id) != "ready":
            raise IndexNotReadyError(f"chronological index of session {session_id} is not ready")
        if limit <= 0:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    self._SELECT_WINDOW, user_id, agent_id, session_id, self._not_expired_cond(), limit
                )
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        window = [self._row_to_turn(r) for r in rows]
        window.reverse()
        return window

    async def max_sequence(self, user_id: str, agent_id: str, session_id: str) -> int:
        """Highest stored sequence for the session, ``0`` when none (durable maximum)."""
        self._require_connection()
        try:
            async with self._pool.acquire() as conn:
                return int(
                    await conn.fetchval(
                        "SELECT COALESCE(MAX(seq), 0) FROM parrot_conversations"
                        " WHERE user_id=$1 AND agent_id=$2 AND session_id=$3 AND kind='turn'",
                        user_id,
                        agent_id,
                        session_id,
                    )
                )
        except Exception as exc:
            raise self._translate(exc, write=False) from exc

    async def put_tombstone(self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None) -> None:
        """Durably record a session (``turn_id=None``) or turn deletion. Idempotent; no TTL."""
        self._require_connection()
        if turn_id == "":
            raise ValueError("turn_id must be non-empty (use None for a session tombstone)")
        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(self._LOCK_SQL, self._lock_key(user_id, agent_id, session_id))
                    await conn.execute(
                        "INSERT INTO parrot_conversation_tombstones (user_id, agent_id, session_id, turn_id)"
                        " VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
                        user_id,
                        agent_id,
                        session_id,
                        turn_id or "",
                    )
        except Exception as exc:
            raise self._translate(exc, write=True) from exc

    async def deleted_turn_ids(self, user_id: str, agent_id: str, session_id: str) -> Set[str]:
        """Every turn-scoped tombstone of the session in one query."""
        self._require_connection()
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT turn_id FROM parrot_conversation_tombstones"
                    " WHERE user_id=$1 AND agent_id=$2 AND session_id=$3 AND turn_id <> ''",
                    user_id,
                    agent_id,
                    session_id,
                )
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        return {r["turn_id"] for r in rows}

    async def deleted_session_ids(self, user_id: str, agent_id: str, session_ids: Sequence[str]) -> Set[str]:
        """The session-tombstoned members of ``session_ids`` in one query (ids bound as a ``text[]``)."""
        self._require_connection()
        wanted = list(dict.fromkeys(session_ids))
        if not wanted:
            return set()
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT session_id FROM parrot_conversation_tombstones"
                    " WHERE user_id=$1 AND agent_id=$2 AND turn_id = '' AND session_id = ANY($3::text[])",
                    user_id,
                    agent_id,
                    wanted,
                )
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        return {r["session_id"] for r in rows}

    async def is_deleted(self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None) -> bool:
        """Whether the session (or session OR this turn) is tombstoned; raises when it cannot be determined."""
        self._require_connection()
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchval(self._TOMBSTONE_SQL, user_id, agent_id, session_id, turn_id or "")
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        return row is not None

    async def get_index_state(self, user_id: str, agent_id: str, session_id: str) -> str:
        """``'ready'`` | ``'pending'`` | ``'invalid'``.

        Derived: ``ready`` iff the session has no live turn row without ``ts_utc``; the state table
        only distinguishes ``invalid`` from ``pending``.
        """
        self._require_connection()
        try:
            async with self._pool.acquire() as conn:
                unindexed = await conn.fetchval(
                    self._HAS_UNINDEXED, user_id, agent_id, session_id, self._not_expired_cond()
                )
                if unindexed is None:
                    return "ready"
                state = await conn.fetchval(
                    "SELECT state FROM parrot_conversation_index_state"
                    " WHERE user_id=$1 AND agent_id=$2 AND session_id=$3",
                    user_id,
                    agent_id,
                    session_id,
                )
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        return "invalid" if state == "invalid" else "pending"

    @staticmethod
    def _encode_cursor(row) -> str:
        return json.dumps([row["user_id"], row["agent_id"], row["session_id"], row["sort_key"]])

    @staticmethod
    def _decode_cursor(cursor: Optional[str]) -> Tuple[str, str, str, str]:
        if cursor is None:
            return ("", "", "", "")
        user_id, agent_id, session_id, sort_key = json.loads(cursor)
        return (user_id, agent_id, session_id, sort_key)

    async def _index_session(self, conn, key: Tuple[str, str, str], rows: list) -> Tuple[int, bool]:
        """Index one session's legacy rows under its advisory lock; returns ``(indexed, saw_invalid)``."""
        indexed, saw_invalid = 0, False
        async with conn.transaction():
            await conn.execute(self._LOCK_SQL, self._lock_key(*key))
            if await conn.fetchval(self._TOMBSTONE_SQL, *key, ""):  # tombstoned since the SELECT: leave it
                return 0, False
            for row in rows:
                ts, seq = _chrono_fields(row["payload"])
                if ts is None:
                    saw_invalid = True
                    continue
                await conn.execute(self._INDEX_ROW_SQL, ts, seq, row["sort_key"][5:], *key, row["sort_key"])
                indexed += 1
            state = "invalid" if saw_invalid else None
            if not saw_invalid and await conn.fetchval(self._HAS_UNINDEXED, *key, self._not_expired_cond()) is None:
                state = "ready"
            if state is not None:
                await conn.execute(self._UPSERT_STATE_SQL, *key, state)
        return indexed, saw_invalid

    async def backfill_batch(self, cursor: Optional[str], batch_size: int) -> BackfillBatch:
        """Index up to ``batch_size`` legacy turns after ``cursor`` (resumable, safe next to new writes).

        ``invalid_sessions`` entries are formatted ``"<user_id>/<agent_id>/<session_id>"``.
        """
        self._require_connection()
        groups: Dict[Tuple[str, str, str], list] = {}
        indexed_total, invalid = 0, []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    self._SELECT_LEGACY, self._not_expired_cond(), *self._decode_cursor(cursor), batch_size
                )
                for row in rows:
                    groups.setdefault((row["user_id"], row["agent_id"], row["session_id"]), []).append(row)
                for key, session_rows in groups.items():
                    done, bad = await self._index_session(conn, key, session_rows)
                    indexed_total += done
                    if bad:
                        invalid.append("/".join(key))
        except Exception as exc:
            raise self._translate(exc, write=True) from exc
        next_cursor = self._encode_cursor(rows[-1]) if rows and len(rows) == batch_size else None
        return BackfillBatch(processed=indexed_total, next_cursor=next_cursor, invalid_sessions=tuple(invalid))

    # ------------------------------------------------------------------
    # Artifacts
    # ------------------------------------------------------------------

    async def put_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
        data: dict,
    ) -> None:
        if not self.is_connected:
            return
        payload = self._encode_payload(data)
        expires = self._expires_at()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO parrot_artifacts
                    (user_id, agent_id, session_id, artifact_id, payload, updated_at, expires_at)
                VALUES ($1, $2, $3, $4, $5, now(), $6)
                ON CONFLICT (user_id, agent_id, session_id, artifact_id)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = now(), expires_at = EXCLUDED.expires_at
                """,
                user_id,
                agent_id,
                session_id,
                artifact_id,
                payload,
                expires,
            )

    async def get_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
    ) -> Optional[dict]:
        if not self.is_connected:
            return None
        now = self._not_expired_cond()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT artifact_id, session_id, payload, updated_at FROM parrot_artifacts
                WHERE user_id=$1 AND agent_id=$2 AND session_id=$3 AND artifact_id=$4
                  AND (expires_at IS NULL OR expires_at > $5)
                """,
                user_id,
                agent_id,
                session_id,
                artifact_id,
                now,
            )
        if row is None:
            return None
        return self._row_to_artifact(row)

    async def query_artifacts(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> List[dict]:
        if not self.is_connected:
            return []
        now = self._not_expired_cond()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT artifact_id, session_id, payload, updated_at FROM parrot_artifacts
                WHERE user_id=$1 AND agent_id=$2 AND session_id=$3
                  AND (expires_at IS NULL OR expires_at > $4)
                ORDER BY updated_at DESC
                """,
                user_id,
                agent_id,
                session_id,
                now,
            )
        return [self._row_to_artifact(r) for r in rows]

    async def delete_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
    ) -> None:
        if not self.is_connected:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM parrot_artifacts
                WHERE user_id=$1 AND agent_id=$2 AND session_id=$3 AND artifact_id=$4
                """,
                user_id,
                agent_id,
                session_id,
                artifact_id,
            )

    async def delete_session_artifacts(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> int:
        if not self.is_connected:
            return 0
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM parrot_artifacts WHERE user_id=$1 AND agent_id=$2 AND session_id=$3",
                user_id,
                agent_id,
                session_id,
            )
        return int(result.split()[-1])

    async def sweep_expired(self) -> int:
        """Delete rows past their TTL (optional helper, not auto-called)."""
        if not self.is_connected:
            return 0
        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            r1 = await conn.execute(
                "DELETE FROM parrot_conversations WHERE expires_at IS NOT NULL AND expires_at <= $1",
                now,
            )
            r2 = await conn.execute(
                "DELETE FROM parrot_artifacts WHERE expires_at IS NOT NULL AND expires_at <= $1",
                now,
            )
        return int(r1.split()[-1]) + int(r2.split()[-1])
