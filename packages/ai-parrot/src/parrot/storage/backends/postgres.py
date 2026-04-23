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

import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from navconfig.logging import logging

from parrot.storage.backends.base import ConversationBackend


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
            dsn=self._dsn, min_size=1, max_size=5, init=_set_jsonb_codec,
        )
        async with self._pool.acquire() as conn:
            await conn.execute(self._CREATE_CONVERSATIONS)
            await conn.execute(self._CREATE_CONV_IDX_USER_AGENT)
            await conn.execute(self._CREATE_CONV_IDX_GIN)
            await conn.execute(self._CREATE_ARTIFACTS)
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
            from datetime import timedelta  # noqa: PLC0415
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

    def _encode_payload(self, data: dict) -> dict:
        """Normalize datetime values in a payload dict to ISO strings."""
        return {
            k: v.isoformat() if isinstance(v, datetime) else v
            for k, v in data.items()
        }

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
                user_id, agent_id, session_id, payload, expires,
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
                user_id, agent_id, session_id, now,
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
                user_id, agent_id, session_id, payload, expires,
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
                user_id, agent_id, now, limit,
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
        if not self.is_connected:
            return
        payload = self._encode_payload(data)
        sort_key = f"TURN#{turn_id}"
        expires = self._expires_at()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO parrot_conversations
                    (user_id, agent_id, session_id, kind, sort_key, payload, updated_at, expires_at)
                VALUES ($1, $2, $3, 'turn', $4, $5, now(), $6)
                ON CONFLICT (user_id, agent_id, session_id, kind, sort_key)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = now(), expires_at = EXCLUDED.expires_at
                """,
                user_id, agent_id, session_id, sort_key, payload, expires,
            )

    async def query_turns(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        limit: int = 10,
        newest_first: bool = True,
    ) -> List[dict]:
        if not self.is_connected:
            return []
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
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, user_id, agent_id, session_id, now, limit)
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
                user_id, agent_id, session_id, sort_key,
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
                user_id, agent_id, session_id,
            )
            r2 = await conn.execute(
                "DELETE FROM parrot_artifacts WHERE user_id=$1 AND agent_id=$2 AND session_id=$3",
                user_id, agent_id, session_id,
            )
        return int(r1.split()[-1]) + int(r2.split()[-1])

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
                user_id, agent_id, session_id, artifact_id, payload, expires,
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
                user_id, agent_id, session_id, artifact_id, now,
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
                user_id, agent_id, session_id, now,
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
                user_id, agent_id, session_id, artifact_id,
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
                user_id, agent_id, session_id,
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
