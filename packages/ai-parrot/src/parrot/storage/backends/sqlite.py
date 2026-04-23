"""SQLite conversation backend — zero-dependency local storage.

Uses ``aiosqlite`` (a transitive dependency of ``asyncdb[sqlite]``) for
async SQLite access.  Suitable for:
  - Data-analyst laptops without Docker or AWS credentials.
  - CI environments without external services.

Limitations (see docs/storage-backends.md):
  - Single-writer: SQLite serializes writes. Not suitable for multi-process
    deployments. For multi-worker local setups, use Postgres via Docker.
  - No built-in background TTL sweeper in v1. Expired rows are filtered on
    read paths; call ``sweep_expired()`` explicitly when desired.
  - File path only (no ``:memory:`` URIs) in v1; the factory always provides
    a real path.

FEAT-116: dynamodb-fallback-redis — Module 4 (SQLite backend).
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import aiosqlite
from navconfig.logging import logging

from parrot.storage.backends.base import ConversationBackend


class ConversationSQLiteBackend(ConversationBackend):
    """Async SQLite implementation of ConversationBackend.

    Stores threads, turns, and artifacts in two local SQLite tables.
    Payload dicts are JSON-encoded so the schema stays simple.

    Turn IDs MUST be zero-padded for lexicographic ordering to match
    numeric ordering (e.g. ``"001"``, ``"002"``). This mirrors the
    DynamoDB reference implementation.

    Args:
        path: Filesystem path to the SQLite database file.
        default_ttl_days: TTL for new rows in days (default 180).
    """

    DEFAULT_TTL_DAYS = 180

    _CREATE_CONVERSATIONS = """
        CREATE TABLE IF NOT EXISTS conversations (
            user_id     TEXT NOT NULL,
            agent_id    TEXT NOT NULL,
            session_id  TEXT NOT NULL,
            kind        TEXT NOT NULL,
            sort_key    TEXT NOT NULL,
            payload     TEXT NOT NULL,
            updated_at  REAL NOT NULL,
            expires_at  REAL,
            PRIMARY KEY (user_id, agent_id, session_id, kind, sort_key)
        )
    """
    _CREATE_CONV_IDX_USER_AGENT = """
        CREATE INDEX IF NOT EXISTS idx_conv_user_agent
        ON conversations(user_id, agent_id, updated_at DESC)
    """
    _CREATE_CONV_IDX_EXPIRES = """
        CREATE INDEX IF NOT EXISTS idx_conv_expires
        ON conversations(expires_at)
    """
    _CREATE_ARTIFACTS = """
        CREATE TABLE IF NOT EXISTS artifacts (
            user_id     TEXT NOT NULL,
            agent_id    TEXT NOT NULL,
            session_id  TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            payload     TEXT NOT NULL,
            updated_at  REAL NOT NULL,
            expires_at  REAL,
            PRIMARY KEY (user_id, agent_id, session_id, artifact_id)
        )
    """

    def __init__(self, path: str, default_ttl_days: int = 180) -> None:
        self._path = path
        self._default_ttl_days = default_ttl_days
        self._conn: Optional[aiosqlite.Connection] = None
        self._initialized: bool = False
        self.logger = logging.getLogger("parrot.storage.ConversationSQLiteBackend")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Open the database connection and create tables (idempotent)."""
        if self._initialized and self._conn is not None:
            return
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute(self._CREATE_CONVERSATIONS)
        await self._conn.execute(self._CREATE_CONV_IDX_USER_AGENT)
        await self._conn.execute(self._CREATE_CONV_IDX_EXPIRES)
        await self._conn.execute(self._CREATE_ARTIFACTS)
        await self._conn.commit()
        self._initialized = True
        self.logger.info("SQLite backend initialized: %s", self._path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception as exc:
                self.logger.warning("Error closing SQLite backend: %s", exc)
            finally:
                self._conn = None
                self._initialized = False

    @property
    def is_connected(self) -> bool:
        """Return True when the connection is open."""
        return self._conn is not None and self._initialized

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _now_epoch(self) -> float:
        return time.time()

    def _expires_at(self, updated_at: float) -> Optional[float]:
        if self._default_ttl_days <= 0:
            # Fix #6: use updated_at - 1 so the row is always past-expired at
            # query time (avoids a race when both timestamps fall in the same
            # time.time() tick, which would make the > predicate miss the row).
            return updated_at - 1
        return updated_at + self._default_ttl_days * 86400

    def _not_expired(self) -> float:
        return self._now_epoch()

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
        """Create or replace a thread metadata row."""
        if not self.is_connected:
            return
        now = self._now_epoch()
        payload = {k: v for k, v in metadata.items()}
        # Serialize datetime values
        for k in list(payload):
            if isinstance(payload[k], datetime):
                payload[k] = payload[k].isoformat()
        expires = self._expires_at(now)
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO conversations
                (user_id, agent_id, session_id, kind, sort_key, payload, updated_at, expires_at)
            VALUES (?, ?, ?, 'thread', 'THREAD', ?, ?, ?)
            """,
            (user_id, agent_id, session_id, json.dumps(payload, default=str), now, expires),
        )
        await self._conn.commit()

    async def update_thread(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        **updates,
    ) -> None:
        """Update specific attributes on a thread metadata row."""
        if not self.is_connected or not updates:
            return
        now = self._now_epoch()
        cursor = await self._conn.execute(
            """
            SELECT payload FROM conversations
            WHERE user_id=? AND agent_id=? AND session_id=? AND kind='thread'
              AND sort_key='THREAD'
              AND (expires_at IS NULL OR expires_at > ?)
            """,
            (user_id, agent_id, session_id, now),
        )
        row = await cursor.fetchone()
        if row is None:
            # Thread doesn't exist yet; create it from updates
            payload = dict(updates)
        else:
            payload = json.loads(row["payload"])
            for k, v in updates.items():
                if isinstance(v, datetime):
                    v = v.isoformat()
                payload[k] = v

        expires = self._expires_at(now)
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO conversations
                (user_id, agent_id, session_id, kind, sort_key, payload, updated_at, expires_at)
            VALUES (?, ?, ?, 'thread', 'THREAD', ?, ?, ?)
            """,
            (user_id, agent_id, session_id, json.dumps(payload, default=str), now, expires),
        )
        await self._conn.commit()

    async def query_threads(
        self,
        user_id: str,
        agent_id: str,
        limit: int = 50,
    ) -> List[dict]:
        """List thread metadata items for a user+agent pair, newest first."""
        if not self.is_connected:
            return []
        now = self._not_expired()
        cursor = await self._conn.execute(
            """
            SELECT session_id, payload, updated_at FROM conversations
            WHERE user_id=? AND agent_id=? AND kind='thread'
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (user_id, agent_id, now, limit),
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            payload = json.loads(row["payload"])
            entry = {"session_id": row["session_id"], **payload}
            result.append(entry)
        return result

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
        """Store a conversation turn."""
        if not self.is_connected:
            return
        now = self._now_epoch()
        payload = dict(data)
        for k in list(payload):
            if isinstance(payload[k], datetime):
                payload[k] = payload[k].isoformat()
        sort_key = f"TURN#{turn_id}"
        expires = self._expires_at(now)
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO conversations
                (user_id, agent_id, session_id, kind, sort_key, payload, updated_at, expires_at)
            VALUES (?, ?, ?, 'turn', ?, ?, ?, ?)
            """,
            (user_id, agent_id, session_id, sort_key, json.dumps(payload, default=str), now, expires),
        )
        await self._conn.commit()

    async def query_turns(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        limit: int = 10,
        newest_first: bool = True,
    ) -> List[dict]:
        """Query conversation turns for a session."""
        if not self.is_connected:
            return []
        now = self._not_expired()
        # Fix #9: avoid f-string SQL (triggers static-analysis false positives).
        # ORDER direction is derived from a boolean — never user-controlled.
        _ORDER = {True: "DESC", False: "ASC"}
        sql = (
            "SELECT sort_key, payload, updated_at FROM conversations"
            " WHERE user_id=? AND agent_id=? AND session_id=? AND kind='turn'"
            "   AND (expires_at IS NULL OR expires_at > ?)"
            f" ORDER BY sort_key {_ORDER[newest_first]}"
            " LIMIT ?"
        )
        cursor = await self._conn.execute(
            sql,
            (user_id, agent_id, session_id, now, limit),
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            payload = json.loads(row["payload"])
            turn_id = row["sort_key"].replace("TURN#", "", 1)
            entry = {
                "session_id": session_id,
                "turn_id": turn_id,
                "updated_at": datetime.fromtimestamp(
                    row["updated_at"], tz=timezone.utc
                ).isoformat(),
                **payload,
            }
            result.append(entry)
        return result

    async def delete_turn(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        turn_id: str,
    ) -> bool:
        """Delete a single conversation turn.

        Returns:
            True if the turn existed and was deleted, False otherwise.
        """
        if not self.is_connected:
            return False
        sort_key = f"TURN#{turn_id}"
        cursor = await self._conn.execute(
            """
            DELETE FROM conversations
            WHERE user_id=? AND agent_id=? AND session_id=? AND kind='turn'
              AND sort_key=?
            """,
            (user_id, agent_id, session_id, sort_key),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def delete_thread_cascade(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> int:
        """Delete all conversation items + artifacts for a session.

        Returns:
            Number of rows deleted across both tables.
        """
        if not self.is_connected:
            return 0
        c1 = await self._conn.execute(
            "DELETE FROM conversations WHERE user_id=? AND agent_id=? AND session_id=?",
            (user_id, agent_id, session_id),
        )
        c2 = await self._conn.execute(
            "DELETE FROM artifacts WHERE user_id=? AND agent_id=? AND session_id=?",
            (user_id, agent_id, session_id),
        )
        await self._conn.commit()
        return c1.rowcount + c2.rowcount

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
        """Store an artifact row."""
        if not self.is_connected:
            return
        now = self._now_epoch()
        payload = dict(data)
        for k in list(payload):
            if isinstance(payload[k], datetime):
                payload[k] = payload[k].isoformat()
        expires = self._expires_at(now)
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO artifacts
                (user_id, agent_id, session_id, artifact_id, payload, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, agent_id, session_id, artifact_id,
             json.dumps(payload, default=str), now, expires),
        )
        await self._conn.commit()

    async def get_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
    ) -> Optional[dict]:
        """Get a single artifact by its key."""
        if not self.is_connected:
            return None
        now = self._not_expired()
        cursor = await self._conn.execute(
            """
            SELECT artifact_id, payload, updated_at FROM artifacts
            WHERE user_id=? AND agent_id=? AND session_id=? AND artifact_id=?
              AND (expires_at IS NULL OR expires_at > ?)
            """,
            (user_id, agent_id, session_id, artifact_id, now),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload"])
        return {
            "artifact_id": row["artifact_id"],
            "session_id": session_id,
            "updated_at": datetime.fromtimestamp(
                row["updated_at"], tz=timezone.utc
            ).isoformat(),
            **payload,
        }

    async def query_artifacts(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> List[dict]:
        """List all artifacts for a session."""
        if not self.is_connected:
            return []
        now = self._not_expired()
        cursor = await self._conn.execute(
            """
            SELECT artifact_id, payload, updated_at FROM artifacts
            WHERE user_id=? AND agent_id=? AND session_id=?
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY updated_at DESC
            """,
            (user_id, agent_id, session_id, now),
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            payload = json.loads(row["payload"])
            result.append({
                "artifact_id": row["artifact_id"],
                "session_id": session_id,
                "updated_at": datetime.fromtimestamp(
                    row["updated_at"], tz=timezone.utc
                ).isoformat(),
                **payload,
            })
        return result

    async def delete_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
    ) -> None:
        """Delete a single artifact row."""
        if not self.is_connected:
            return
        await self._conn.execute(
            """
            DELETE FROM artifacts
            WHERE user_id=? AND agent_id=? AND session_id=? AND artifact_id=?
            """,
            (user_id, agent_id, session_id, artifact_id),
        )
        await self._conn.commit()

    async def delete_session_artifacts(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> int:
        """Delete all artifacts for a session.

        Returns:
            Number of artifacts deleted.
        """
        if not self.is_connected:
            return 0
        cursor = await self._conn.execute(
            "DELETE FROM artifacts WHERE user_id=? AND agent_id=? AND session_id=?",
            (user_id, agent_id, session_id),
        )
        await self._conn.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # TTL helpers
    # ------------------------------------------------------------------

    async def sweep_expired(self) -> int:
        """Delete all rows whose ``expires_at`` is in the past.

        This helper is NOT called automatically in v1. Invoke it explicitly
        when you want to reclaim space (e.g., on a schedule or at startup).

        Returns:
            Number of rows deleted across both tables.
        """
        if not self.is_connected:
            return 0
        now = self._now_epoch()
        c1 = await self._conn.execute(
            "DELETE FROM conversations WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        )
        c2 = await self._conn.execute(
            "DELETE FROM artifacts WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        )
        await self._conn.commit()
        return c1.rowcount + c2.rowcount
