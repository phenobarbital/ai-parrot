"""SQLite episode persistence under the accepted local-store contract."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from parrot.memory.episodic.backends.abstract import AbstractEpisodeBackend
from parrot.memory.episodic.models import EpisodeSearchResult, EpisodicMemory


logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1
_DEFAULT_VECTOR_CEILING = 5_000
_FILTERABLE_COLUMNS = (
    "tenant_id",
    "agent_id",
    "user_id",
    "session_id",
    "room_id",
    "crew_id",
    "model_id",
)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    episode_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    user_id TEXT,
    session_id TEXT,
    room_id TEXT,
    crew_id TEXT,
    model_id TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    is_failure INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL,
    embedding BLOB,
    embedding_dim INTEGER
);
CREATE INDEX IF NOT EXISTS idx_episodes_scope_created
    ON episodes (tenant_id, agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_expiry
    ON episodes (expires_at);
"""


def _pack_embedding(embedding: list[float] | None) -> tuple[bytes | None, int | None]:
    """Encode a finite embedding as little-endian float32 values.

    Args:
        embedding: Optional vector to persist.

    Returns:
        The encoded vector and its dimension, or two ``None`` values.

    Raises:
        ValueError: If an embedding is empty or contains a non-finite value.
    """
    if embedding is None:
        return None, None
    if not embedding:
        raise ValueError("embedding must not be empty")
    if not all(math.isfinite(value) for value in embedding):
        raise ValueError("embedding values must be finite")
    return struct.pack(f"<{len(embedding)}f", *embedding), len(embedding)


def _unpack_embedding(payload: bytes, dimension: int) -> list[float]:
    """Decode an embedding stored by :func:`_pack_embedding`.

    Args:
        payload: Little-endian float32 bytes from SQLite.
        dimension: Number of stored vector dimensions.

    Returns:
        The decoded vector.

    Raises:
        ValueError: If a stored vector has an invalid shape or non-finite value.
    """
    if dimension <= 0 or len(payload) != dimension * 4:
        raise ValueError("stored embedding has an invalid shape")
    values = list(struct.unpack(f"<{dimension}f", payload))
    if not all(math.isfinite(value) for value in values):
        raise ValueError("stored embedding values must be finite")
    return values


def _cosine(left: list[float], right: list[float]) -> float:
    """Calculate cosine similarity for two same-sized finite vectors.

    Args:
        left: Query vector.
        right: Candidate vector.

    Returns:
        Similarity in the mathematical cosine range, or zero for zero norms.
    """
    if len(left) != len(right):
        return 0.0
    dot_product = sum(first * second for first, second in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot_product / (left_norm * right_norm)


class SQLiteEpisodeBackend(AbstractEpisodeBackend):
    """Persist scoped episodes using async I/O, WAL and the accepted vector ceiling."""

    def __init__(
        self,
        path: Path,
        *,
        busy_timeout_ms: int = 5_000,
        vector_ceiling: int = _DEFAULT_VECTOR_CEILING,
    ) -> None:
        """Retain configuration without opening resources or deleting existing data.

        Args:
            path: SQLite database path owned by this backend.
            busy_timeout_ms: SQLite busy timeout for contending writers.
            vector_ceiling: Largest scoped candidate set scored exactly per search.

        Raises:
            ValueError: If a configured limit is not positive.
        """
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        if vector_ceiling <= 0:
            raise ValueError("vector_ceiling must be positive")
        self.path = Path(path)
        self._busy_timeout_ms = busy_timeout_ms
        self._vector_ceiling = vector_ceiling
        self._db: aiosqlite.Connection | None = None
        self._fts_enabled = False
        self._lifecycle_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    async def configure(self) -> None:
        """Open the connection and apply idempotent versioned schema changes.

        Raises:
            ValueError: If the database schema is newer than this backend supports.
        """
        async with self._lifecycle_lock:
            if self._db is not None:
                return
            database = await aiosqlite.connect(
                str(self.path), isolation_level=None, timeout=self._busy_timeout_ms / 1_000
            )
            self._db = database
            try:
                await database.execute("PRAGMA journal_mode=WAL")
                await database.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
                await database.execute("PRAGMA synchronous=NORMAL")
                cursor = await database.execute("PRAGMA user_version")
                row = await cursor.fetchone()
                version = int(row[0]) if row is not None else 0
                if version > _SCHEMA_VERSION:
                    raise ValueError(f"unsupported SQLite episode schema version: {version}")
                await database.executescript(_SCHEMA)
                if version < _SCHEMA_VERSION:
                    await database.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                try:
                    await database.execute(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts "
                        "USING fts5(episode_id UNINDEXED, text)"
                    )
                    self._fts_enabled = True
                except aiosqlite.OperationalError:
                    self._fts_enabled = False
                    logger.warning("FTS5 unavailable in this SQLite build; search_text uses LIKE fallback")
            except BaseException:
                await self._close_database(database)
                self._db = None
                raise

    async def close(self) -> None:
        """Drain owned writes and release resources without claiming lost acknowledgements."""
        async with self._lifecycle_lock:
            async with self._write_lock:
                database = self._db
                self._db = None
                self._fts_enabled = False
                if database is not None:
                    await self._close_database(database)

    async def __aenter__(self) -> SQLiteEpisodeBackend:
        """Configure and return this backend for asynchronous context-manager use."""
        await self.configure()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        """Close this backend after asynchronous context-manager use."""
        await self.close()

    async def store(self, episode: EpisodicMemory) -> str:
        """Persist one episode and acknowledge only after commit.

        Args:
            episode: Episode to write once by its immutable identifier.

        Returns:
            The supplied episode identifier.
        """
        payload = json.dumps(episode.to_dict())
        embedding, embedding_dim = _pack_embedding(episode.embedding)
        async with self._write_lock:
            database = self._require_database()
            await database.execute("BEGIN IMMEDIATE")
            try:
                cursor = await database.execute(
                    "INSERT OR IGNORE INTO episodes "
                    "(episode_id, tenant_id, agent_id, user_id, session_id, room_id, crew_id, model_id, "
                    "created_at, expires_at, is_failure, payload, embedding, embedding_dim) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        episode.episode_id,
                        episode.tenant_id,
                        episode.agent_id,
                        episode.user_id,
                        episode.session_id,
                        episode.room_id,
                        episode.crew_id,
                        episode.model_id,
                        episode.created_at.isoformat(),
                        episode.expires_at.isoformat() if episode.expires_at is not None else None,
                        int(episode.is_failure),
                        payload,
                        embedding,
                        embedding_dim,
                    ),
                )
                if cursor.rowcount == 1 and self._fts_enabled:
                    await database.execute(
                        "INSERT INTO episodes_fts (episode_id, text) VALUES (?, ?)",
                        (episode.episode_id, episode.searchable_text()),
                    )
                await database.execute("COMMIT")
            except BaseException:
                await self._rollback(database)
                raise
        return episode.episode_id

    async def search_similar(
        self,
        embedding: list[float],
        namespace_filter: dict[str, Any],
        top_k: int = 5,
        score_threshold: float = 0.3,
        include_failures_only: bool = False,
    ) -> list[EpisodeSearchResult]:
        """Filter before ranking and expose vector-ceiling degradation explicitly.

        The first ``vector_ceiling`` candidates are the most recent scoped rows
        when the measured exact-search ceiling is exceeded.
        """
        self._validate_search_arguments(embedding, top_k, score_threshold)
        if top_k == 0:
            return []
        where_sql, params = self._build_where(namespace_filter, include_failures_only)
        database = self._require_database()
        cursor = await database.execute(
            f"SELECT payload, embedding, embedding_dim FROM episodes WHERE {where_sql} "
            "AND embedding IS NOT NULL ORDER BY created_at DESC, episode_id DESC LIMIT ?",
            [*params, self._vector_ceiling],
        )
        rows = await cursor.fetchall()
        scored: list[tuple[float, dict[str, Any]]] = []
        for payload, stored_embedding, dimension in rows:
            score = _cosine(embedding, _unpack_embedding(stored_embedding, int(dimension)))
            if score >= score_threshold:
                scored.append((score, json.loads(payload)))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            EpisodeSearchResult(**data, score=min(max(score, 0.0), 1.01))
            for score, data in scored[:top_k]
        ]

    async def vector_status(self, namespace_filter: dict[str, Any]) -> dict[str, int | str]:
        """Report whether a scope exceeded the measured exact-vector ceiling.

        Args:
            namespace_filter: Scope dimensions applied before counting candidates.

        Returns:
            Status, scoped candidate count, and configured vector ceiling.
        """
        where_sql, params = self._build_where(namespace_filter)
        database = self._require_database()
        cursor = await database.execute(
            f"SELECT COUNT(*) FROM episodes WHERE {where_sql} AND embedding IS NOT NULL", params
        )
        row = await cursor.fetchone()
        candidate_count = int(row[0]) if row is not None else 0
        return {
            "status": "degraded" if candidate_count > self._vector_ceiling else "ok",
            "candidate_count": candidate_count,
            "vector_ceiling": self._vector_ceiling,
        }

    async def search_text(
        self,
        query: str,
        namespace_filter: dict[str, Any],
        top_k: int = 5,
    ) -> list[EpisodeSearchResult]:
        """Search scoped text through FTS5 or a safely escaped LIKE fallback.

        Args:
            query: Literal search text.
            namespace_filter: Scope dimensions applied before limiting results.
            top_k: Maximum number of lexical results.

        Returns:
            Text-ranked episodes. These are never substituted for vector results.
        """
        if top_k < 0:
            raise ValueError("top_k must be non-negative")
        if top_k == 0:
            return []
        where_sql, params = self._build_where(namespace_filter)
        database = self._require_database()
        if self._fts_enabled:
            phrase = '"' + query.replace('"', '""') + '"'
            cursor = await database.execute(
                "SELECT e.payload, bm25(episodes_fts) AS rank FROM episodes_fts "
                "JOIN episodes e ON e.episode_id = episodes_fts.episode_id "
                f"WHERE episodes_fts MATCH ? AND {where_sql} ORDER BY rank LIMIT ?",
                [phrase, *params, top_k],
            )
            rows = await cursor.fetchall()
            if not rows:
                return []
            ranks = [float(row[1]) for row in rows]
            highest_rank = max(ranks)
            spread = highest_rank - min(ranks)
            return [
                EpisodeSearchResult(
                    **json.loads(payload),
                    score=1.0 if spread == 0 else (highest_rank - float(rank)) / spread,
                )
                for payload, rank in rows
            ]

        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        cursor = await database.execute(
            f"SELECT payload FROM episodes WHERE {where_sql} AND payload LIKE ? ESCAPE '\\' "
            "ORDER BY created_at DESC, episode_id DESC LIMIT ?",
            [*params, f"%{escaped_query}%", top_k],
        )
        rows = await cursor.fetchall()
        return [EpisodeSearchResult(**json.loads(row[0]), score=1.0) for row in rows]

    async def get_recent(
        self,
        namespace_filter: dict[str, Any],
        limit: int = 10,
        since: datetime | None = None,
    ) -> list[EpisodicMemory]:
        """Return scoped recent episodes, applying filters before the limit."""
        if limit < 0:
            raise ValueError("limit must be non-negative")
        where_sql, params = self._build_where(namespace_filter)
        query = f"SELECT payload FROM episodes WHERE {where_sql}"
        if since is not None:
            query += " AND created_at > ?"
            params.append(since.isoformat())
        query += " ORDER BY created_at DESC, episode_id DESC LIMIT ?"
        params.append(limit)
        cursor = await self._require_database().execute(query, params)
        rows = await cursor.fetchall()
        return [EpisodicMemory.from_dict(json.loads(row[0])) for row in rows]

    async def get_failures(
        self,
        agent_id: str,
        tenant_id: str = "default",
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        """Preserve baseline failure retrieval without bypassing scoped store admission."""
        if limit < 0:
            raise ValueError("limit must be non-negative")
        cursor = await self._require_database().execute(
            "SELECT payload FROM episodes WHERE agent_id = ? AND tenant_id = ? AND is_failure = 1 "
            "ORDER BY created_at DESC, episode_id DESC LIMIT ?",
            (agent_id, tenant_id, limit),
        )
        rows = await cursor.fetchall()
        return [EpisodicMemory.from_dict(json.loads(row[0])) for row in rows]

    async def delete_expired(self) -> int:
        """Prune permitted episode data without destroying imported feedback history."""
        now = datetime.now(timezone.utc).isoformat()
        async with self._write_lock:
            database = self._require_database()
            await database.execute("BEGIN IMMEDIATE")
            try:
                cursor = await database.execute(
                    "SELECT episode_id FROM episodes WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,)
                )
                episode_ids = [row[0] for row in await cursor.fetchall()]
                if episode_ids:
                    placeholders = ", ".join("?" for _ in episode_ids)
                    if self._fts_enabled:
                        await database.execute(
                            f"DELETE FROM episodes_fts WHERE episode_id IN ({placeholders})", episode_ids
                        )
                    await database.execute(f"DELETE FROM episodes WHERE episode_id IN ({placeholders})", episode_ids)
                await database.execute("COMMIT")
            except BaseException:
                await self._rollback(database)
                raise
        return len(episode_ids)

    async def count(self, namespace_filter: dict[str, Any]) -> int:
        """Count only records in the supplied scope."""
        where_sql, params = self._build_where(namespace_filter)
        cursor = await self._require_database().execute(f"SELECT COUNT(*) FROM episodes WHERE {where_sql}", params)
        row = await cursor.fetchone()
        return int(row[0]) if row is not None else 0

    async def update_metadata(self, episode_ids: list[str], patch: dict[str, Any]) -> int:
        """Preserve baseline metadata merge semantics and transactional persistence."""
        if not episode_ids:
            return 0
        json.dumps(patch)
        async with self._write_lock:
            database = self._require_database()
            await database.execute("BEGIN IMMEDIATE")
            updated = 0
            try:
                for episode_id in episode_ids:
                    cursor = await database.execute("SELECT payload FROM episodes WHERE episode_id = ?", (episode_id,))
                    row = await cursor.fetchone()
                    if row is None:
                        continue
                    payload = json.loads(row[0])
                    payload.setdefault("metadata", {}).update(patch)
                    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
                    await database.execute(
                        "UPDATE episodes SET payload = ? WHERE episode_id = ?", (json.dumps(payload), episode_id)
                    )
                    updated += 1
                await database.execute("COMMIT")
            except BaseException:
                await self._rollback(database)
                raise
        return updated

    @staticmethod
    def _build_where(
        namespace_filter: dict[str, Any], include_failures_only: bool = False
    ) -> tuple[str, list[Any]]:
        """Build a validated parameterized scope predicate.

        Args:
            namespace_filter: Exact field-value scope dimensions.
            include_failures_only: Whether to add the failure predicate.

        Returns:
            SQL predicate and its bound parameters.

        Raises:
            ValueError: If a caller supplies an unsupported filter dimension.
        """
        clauses: list[str] = []
        parameters: list[Any] = []
        for field, value in namespace_filter.items():
            if field not in _FILTERABLE_COLUMNS:
                raise ValueError(f"unsupported namespace filter: {field}")
            if value is None:
                clauses.append(f"{field} IS NULL")
            else:
                clauses.append(f"{field} = ?")
                parameters.append(value)
        if include_failures_only:
            clauses.append("is_failure = 1")
        return " AND ".join(clauses) if clauses else "1=1", parameters

    @staticmethod
    def _validate_search_arguments(embedding: list[float], top_k: int, score_threshold: float) -> None:
        """Validate exact-vector search inputs before issuing SQLite work."""
        if not embedding:
            raise ValueError("embedding must not be empty")
        if not all(math.isfinite(value) for value in embedding):
            raise ValueError("embedding values must be finite")
        if top_k < 0:
            raise ValueError("top_k must be non-negative")
        if not math.isfinite(score_threshold) or not 0.0 <= score_threshold <= 1.0:
            raise ValueError("score_threshold must be finite and between 0 and 1")

    def _require_database(self) -> aiosqlite.Connection:
        """Return the configured database or fail visibly before a false acknowledgement."""
        if self._db is None:
            raise RuntimeError("SQLiteEpisodeBackend is not configured")
        return self._db

    async def _rollback(self, database: aiosqlite.Connection) -> None:
        """Best-effort rollback preserving the original operation failure."""
        try:
            await asyncio.shield(database.execute("ROLLBACK"))
        except Exception:
            logger.exception("SQLite rollback failed")

    @staticmethod
    async def _close_database(database: aiosqlite.Connection) -> None:
        """Finish connection closure even if the caller is cancelled."""
        close_task = asyncio.create_task(database.close())
        try:
            await asyncio.shield(close_task)
        except asyncio.CancelledError:
            await asyncio.shield(close_task)
            raise
