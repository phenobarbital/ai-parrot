"""SQLite conversation backend — zero-dependency local storage.

Uses ``aiosqlite`` (a transitive dependency of ``asyncdb[sqlite]``) for
async SQLite access.  Suitable for:
  - Data-analyst laptops without Docker or AWS credentials.
  - CI environments without external services.

Limitations (see wiki/stores/storage-backends.md):
  - Single-writer: SQLite serializes writes. Not suitable for multi-process
    deployments. For multi-worker local setups, use Postgres via Docker.
  - No built-in background TTL sweeper in v1. Expired rows are filtered on
    read paths; call ``sweep_expired()`` explicitly when desired.
  - File path only (no ``:memory:`` URIs) in v1; the factory always provides
    a real path.

FEAT-116: dynamodb-fallback-redis — Module 4 (SQLite backend).
"""

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiosqlite
from navconfig.logging import logging

# aiosqlite logs the full SQL + bind params at DEBUG, which leaks
# conversation payloads into stdout/CloudWatch. Silence at import time.
logging.getLogger("aiosqlite").setLevel(logging.INFO)

from parrot.storage.backends.base import BackfillBatch, ConversationBackend
from parrot.storage.errors import (
    ConversationDeletedError,
    IndexNotReadyError,
    StorageUnavailableError,
    StorageWriteError,
)


def _chrono_fields(data: dict) -> Tuple[Optional[datetime], int]:
    """Return ``(timestamp_utc, sequence)`` from a turn payload.

    A missing or unparseable ``timestamp`` yields ``None``; naive values are read as UTC;
    a non-int / negative ``sequence`` yields ``0``.
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
    _ADD_COLUMN_SQL = {
        "ts_utc": "ALTER TABLE conversations ADD COLUMN ts_utc REAL",
        "seq": "ALTER TABLE conversations ADD COLUMN seq INTEGER",
        "turn_id": "ALTER TABLE conversations ADD COLUMN turn_id TEXT",
    }
    _CREATE_CHRONO_IDX = """
        CREATE INDEX IF NOT EXISTS idx_conv_turn_chrono
        ON conversations(user_id, agent_id, session_id, kind, ts_utc DESC, seq DESC, turn_id DESC)
    """
    _CREATE_TOMBSTONES = """
        CREATE TABLE IF NOT EXISTS conversation_tombstones (
            user_id    TEXT NOT NULL,
            agent_id   TEXT NOT NULL,
            session_id TEXT NOT NULL,
            turn_id    TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            PRIMARY KEY (user_id, agent_id, session_id, turn_id)
        )
    """
    _CREATE_INDEX_STATE = """
        CREATE TABLE IF NOT EXISTS conversation_index_state (
            user_id    TEXT NOT NULL,
            agent_id   TEXT NOT NULL,
            session_id TEXT NOT NULL,
            state      TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (user_id, agent_id, session_id)
        )
    """
    # One statement: tombstone guard + upsert. Params: 10 insert values, then 4 guard values.
    # On conflict, ordering (ts_utc/seq/turn_id and payload timestamp/sequence) is kept once set.
    _UPSERT_TURN = """
        INSERT INTO conversations
            (user_id, agent_id, session_id, kind, sort_key, payload, updated_at, expires_at,
             ts_utc, seq, turn_id)
        SELECT ?, ?, ?, 'turn', ?, ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM conversation_tombstones
            WHERE user_id = ? AND agent_id = ? AND session_id = ? AND turn_id IN ('', ?)
        )
        ON CONFLICT (user_id, agent_id, session_id, kind, sort_key) DO UPDATE SET
            payload = CASE WHEN conversations.ts_utc IS NULL THEN excluded.payload
                ELSE json_patch(excluded.payload, json_object(
                    'timestamp', json_extract(conversations.payload, '$.timestamp'),
                    'sequence',  json_extract(conversations.payload, '$.sequence'))) END,
            updated_at = excluded.updated_at,
            expires_at = excluded.expires_at,
            seq = CASE WHEN conversations.ts_utc IS NULL THEN excluded.seq ELSE conversations.seq END,
            turn_id = excluded.turn_id,
            ts_utc = COALESCE(conversations.ts_utc, excluded.ts_utc)
    """
    _SELECT_WINDOW = """
        SELECT c.sort_key, c.payload, c.updated_at FROM conversations AS c
        WHERE c.user_id = ? AND c.agent_id = ? AND c.session_id = ? AND c.kind = 'turn'
          AND c.ts_utc IS NOT NULL AND (c.expires_at IS NULL OR c.expires_at > ?)
          AND NOT EXISTS (
              SELECT 1 FROM conversation_tombstones t
              WHERE t.user_id = c.user_id AND t.agent_id = c.agent_id
                AND t.session_id = c.session_id AND t.turn_id = c.turn_id)
        ORDER BY c.ts_utc DESC, c.seq DESC, c.turn_id DESC
        LIMIT ?
    """
    _HAS_UNINDEXED = """
        SELECT 1 FROM conversations
        WHERE user_id = ? AND agent_id = ? AND session_id = ? AND kind = 'turn'
          AND ts_utc IS NULL AND (expires_at IS NULL OR expires_at > ?)
        LIMIT 1
    """
    _SELECT_LEGACY = """
        SELECT c.user_id, c.agent_id, c.session_id, c.sort_key, c.payload FROM conversations AS c
        WHERE c.kind = 'turn' AND c.ts_utc IS NULL AND (c.expires_at IS NULL OR c.expires_at > ?)
          AND (c.user_id, c.agent_id, c.session_id, c.sort_key) > (?, ?, ?, ?)
          AND NOT EXISTS (
              SELECT 1 FROM conversation_tombstones t
              WHERE t.user_id = c.user_id AND t.agent_id = c.agent_id AND t.session_id = c.session_id
                AND t.turn_id IN ('', substr(c.sort_key, 6)))
        ORDER BY c.user_id, c.agent_id, c.session_id, c.sort_key
        LIMIT ?
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
        try:
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute(self._CREATE_CONVERSATIONS)
            await self._conn.execute(self._CREATE_CONV_IDX_USER_AGENT)
            await self._conn.execute(self._CREATE_CONV_IDX_EXPIRES)
            await self._conn.execute(self._CREATE_ARTIFACTS)
            await self._migrate_chrono_schema()
            await self._conn.commit()
        except BaseException:
            # An open aiosqlite connection owns a non-daemon worker thread; a failed
            # schema step must not leave it running (it would pin the process).
            await self.close()
            raise
        self._initialized = True
        self.logger.info("SQLite backend initialized: %s", self._path)

    async def _migrate_chrono_schema(self) -> None:
        """Additive, idempotent: chrono columns + index + tombstone/index-state tables."""
        cursor = await self._conn.execute("PRAGMA table_info(conversations)")
        existing = {row["name"] for row in await cursor.fetchall()}
        for name, statement in self._ADD_COLUMN_SQL.items():
            if name in existing:
                continue
            try:
                await self._conn.execute(statement)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():   # a concurrent initialize won
                    raise
        await self._conn.execute(self._CREATE_CHRONO_IDX)
        await self._conn.execute(self._CREATE_TOMBSTONES)
        await self._conn.execute(self._CREATE_INDEX_STATE)

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

    def _require_connection(self) -> None:
        """Raise ``StorageUnavailableError`` when the backend is not connected."""
        if not self.is_connected:
            raise StorageUnavailableError("SQLite conversation backend is not connected")

    async def put_turn(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        turn_id: str,
        data: dict,
    ) -> None:
        """Idempotent upsert by ``turn_id``, atomic with the tombstone guard.

        Raises:
            StorageUnavailableError: the backend is not connected.
            ConversationDeletedError: the session or this turn is tombstoned.
            StorageWriteError: the write failed (nothing is swallowed).
        """
        self._require_connection()
        payload = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in data.items()}
        ts, seq = _chrono_fields(data)
        now = self._now_epoch()
        params = (
            user_id, agent_id, session_id, f"TURN#{turn_id}",
            json.dumps(payload, default=str), now, self._expires_at(now),
            ts.timestamp() if ts is not None else None, seq, turn_id,
            user_id, agent_id, session_id, turn_id,
        )
        try:
            cursor = await self._conn.execute(self._UPSERT_TURN, params)
            await self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(
                f"SQLite put_turn failed for session {session_id} turn {turn_id}: {exc}"
            ) from exc
        if cursor.rowcount == 0:
            raise ConversationDeletedError(
                f"session {session_id} or turn {turn_id} is tombstoned; write rejected"
            )

    async def query_turns(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        limit: int = 10,
        newest_first: bool = True,
    ) -> List[dict]:
        """Query conversation turns for a session.

        Raises:
            StorageUnavailableError: disconnected or the read failed.
        """
        self._require_connection()
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
        try:
            cursor = await self._conn.execute(sql, (user_id, agent_id, session_id, now, limit))
            rows = await cursor.fetchall()
        except sqlite3.Error as exc:
            raise StorageUnavailableError(f"SQLite query_turns failed for {session_id}: {exc}") from exc
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
    # FEAT-886: ordered window, tombstones, index state, backfill
    # ------------------------------------------------------------------

    async def query_turn_window(
        self, user_id: str, agent_id: str, session_id: str, limit: int
    ) -> List[dict]:
        """Newest ``limit`` turns by (ts_utc, seq, turn_id), limit applied descending, returned ascending."""
        self._require_connection()
        if await self.is_deleted(user_id, agent_id, session_id):
            raise ConversationDeletedError(f"session {session_id} is tombstoned")
        if await self.get_index_state(user_id, agent_id, session_id) != "ready":
            raise IndexNotReadyError(f"chronological index of session {session_id} is not ready")
        if limit <= 0:
            return []
        try:
            cursor = await self._conn.execute(
                self._SELECT_WINDOW, (user_id, agent_id, session_id, self._not_expired(), limit)
            )
            rows = await cursor.fetchall()
        except sqlite3.Error as exc:
            raise StorageUnavailableError(f"SQLite query_turn_window failed: {exc}") from exc
        window = [
            {
                "session_id": session_id,
                "turn_id": row["sort_key"].replace("TURN#", "", 1),
                "updated_at": datetime.fromtimestamp(row["updated_at"], tz=timezone.utc).isoformat(),
                **json.loads(row["payload"]),
            }
            for row in rows
        ]
        window.reverse()
        return window

    async def max_sequence(self, user_id: str, agent_id: str, session_id: str) -> int:
        """Highest stored sequence for the session, ``0`` when none (includes expired rows: durable maximum)."""
        self._require_connection()
        try:
            cursor = await self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS m FROM conversations"
                " WHERE user_id=? AND agent_id=? AND session_id=? AND kind='turn'",
                (user_id, agent_id, session_id),
            )
            row = await cursor.fetchone()
        except sqlite3.Error as exc:
            raise StorageUnavailableError(f"SQLite max_sequence failed: {exc}") from exc
        return int(row["m"])

    async def put_tombstone(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> None:
        """Durably record a session (``turn_id=None``) or turn deletion. Idempotent; no TTL."""
        self._require_connection()
        if turn_id == "":
            raise ValueError("turn_id must be non-empty (use None for a session tombstone)")
        try:
            await self._conn.execute(
                "INSERT OR IGNORE INTO conversation_tombstones"
                " (user_id, agent_id, session_id, turn_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, agent_id, session_id, turn_id or "", self._now_epoch()),
            )
            await self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(f"SQLite put_tombstone failed for session {session_id}: {exc}") from exc

    async def is_deleted(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> bool:
        """Whether the session (or session OR this turn) is tombstoned; raises when it cannot be determined."""
        self._require_connection()
        try:
            cursor = await self._conn.execute(
                "SELECT 1 FROM conversation_tombstones"
                " WHERE user_id=? AND agent_id=? AND session_id=? AND turn_id IN ('', ?) LIMIT 1",
                (user_id, agent_id, session_id, turn_id or ""),
            )
            return await cursor.fetchone() is not None
        except sqlite3.Error as exc:
            raise StorageUnavailableError(f"SQLite is_deleted failed for session {session_id}: {exc}") from exc

    async def get_index_state(self, user_id: str, agent_id: str, session_id: str) -> str:
        """``'ready'`` | ``'pending'`` | ``'invalid'``.

        Derived: a session is ``ready`` iff it has no live turn row without ``ts_utc``;
        the ``conversation_index_state`` table only distinguishes ``invalid`` from ``pending``.
        """
        self._require_connection()
        try:
            cursor = await self._conn.execute(
                self._HAS_UNINDEXED, (user_id, agent_id, session_id, self._not_expired())
            )
            if await cursor.fetchone() is None:
                return "ready"
            cursor = await self._conn.execute(
                "SELECT state FROM conversation_index_state WHERE user_id=? AND agent_id=? AND session_id=?",
                (user_id, agent_id, session_id),
            )
            row = await cursor.fetchone()
        except sqlite3.Error as exc:
            raise StorageUnavailableError(f"SQLite get_index_state failed for {session_id}: {exc}") from exc
        return "invalid" if row is not None and row["state"] == "invalid" else "pending"

    @staticmethod
    def _encode_cursor(row) -> str:
        return json.dumps([row["user_id"], row["agent_id"], row["session_id"], row["sort_key"]])

    @staticmethod
    def _decode_cursor(cursor: Optional[str]) -> Tuple[str, str, str, str]:
        if cursor is None:
            return ("", "", "", "")
        user_id, agent_id, session_id, sort_key = json.loads(cursor)
        return (user_id, agent_id, session_id, sort_key)

    async def _index_legacy_row(self, row) -> bool:
        """Fill ``ts_utc``/``seq``/``turn_id`` of one legacy row; ``False`` when its timestamp is unusable."""
        ts, seq = _chrono_fields(json.loads(row["payload"]))
        if ts is None:
            return False
        await self._conn.execute(
            "UPDATE conversations SET ts_utc=?, seq=?, turn_id=?"
            " WHERE user_id=? AND agent_id=? AND session_id=? AND kind='turn' AND sort_key=? AND ts_utc IS NULL",
            (ts.timestamp(), seq, row["sort_key"].replace("TURN#", "", 1),
             row["user_id"], row["agent_id"], row["session_id"], row["sort_key"]),
        )
        return True

    async def _finalize_session(self, key: Tuple[str, str, str], saw_invalid: bool, now: float) -> None:
        """Write ``invalid`` / ``ready`` for a session touched by a batch (otherwise leave it pending)."""
        if saw_invalid:
            state = "invalid"
        else:
            cursor = await self._conn.execute(self._HAS_UNINDEXED, (*key, now))
            if await cursor.fetchone() is not None:
                return  # unindexed turns remain (later batch, or an earlier invalid one)
            state = "ready"
        await self._conn.execute(
            "INSERT OR REPLACE INTO conversation_index_state (user_id, agent_id, session_id, state, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (*key, state, now),
        )

    async def backfill_batch(self, cursor: Optional[str], batch_size: int) -> BackfillBatch:
        """Index up to ``batch_size`` legacy turns after ``cursor`` (resumable, safe next to new writes).

        ``invalid_sessions`` entries are formatted ``"<user_id>/<agent_id>/<session_id>"``.
        """
        self._require_connection()
        now = self._now_epoch()
        touched: Dict[Tuple[str, str, str], bool] = {}
        indexed_count = 0
        try:
            cur = await self._conn.execute(
                self._SELECT_LEGACY, (now, *self._decode_cursor(cursor), batch_size)
            )
            rows = await cur.fetchall()
            for row in rows:
                key = (row["user_id"], row["agent_id"], row["session_id"])
                indexed = await self._index_legacy_row(row)
                indexed_count += int(indexed)
                touched[key] = touched.get(key, False) or not indexed
            for key, saw_invalid in touched.items():
                await self._finalize_session(key, saw_invalid, now)
            await self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(f"SQLite backfill_batch failed: {exc}") from exc
        invalid = tuple(f"{u}/{a}/{s}" for (u, a, s), bad in touched.items() if bad)
        next_cursor = self._encode_cursor(rows[-1]) if rows and len(rows) == batch_size else None
        return BackfillBatch(processed=indexed_count, next_cursor=next_cursor, invalid_sessions=invalid)

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
