"""SQLite episode persistence under the accepted local-store contract."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import struct
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import numpy as np

from parrot.memory.episodic.backends.abstract import AbstractEpisodeBackend
from parrot.memory.episodic.models import EpisodeSearchResult, EpisodicMemory, MemoryNamespace
from parrot.memory.dynamics.fsrs import transition
from parrot.memory.dynamics.models import (
    Grade,
    MemoryCitation,
    MemoryParameters,
    MemoryState,
    ReviewCommand,
    ReviewReceipt,
)

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 3
_DEFAULT_VECTOR_CEILING = 5_000
_STATE_READ_BATCH = 500
_ID_READ_BATCH = 500
_SCORE_BLOCK_ROWS = 1_024
_CITATION_RETENTION_DAYS = 30
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
CREATE TABLE IF NOT EXISTS reviews (
    dedupe_key TEXT PRIMARY KEY,
    outcome_id TEXT NOT NULL,
    outcome_revision INTEGER NOT NULL,
    ref_key TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    payload TEXT NOT NULL,
    apply_revision INTEGER NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_outcome_ref
    ON reviews (outcome_id, ref_key, outcome_revision);
CREATE TABLE IF NOT EXISTS memory_state (
    ref_key TEXT PRIMARY KEY,
    apply_revision INTEGER NOT NULL,
    state TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS citations (
    exposure_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_citations_updated
    ON citations (updated_at);
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


def _rank_candidates(
    embedding: list[float],
    candidates: list[tuple[bytes, int]],
    score_threshold: float,
    top_k: int,
) -> list[tuple[int, float]]:
    """Score stored vectors against a query and return the best matches.

    The work is CPU-bound and is meant to run in a worker thread. A stored vector
    whose dimension differs from the query, or whose norm is zero, scores 0.0.
    Equal scores keep candidate order, so the newest row wins a tie.

    Args:
        embedding: Finite query vector.
        candidates: Stored ``(little-endian float32 bytes, dimension)`` pairs, as written by :func:`_pack_embedding`.
        score_threshold: Minimum cosine similarity to keep.
        top_k: Maximum number of matches.

    Returns:
        ``(candidate index, cosine similarity)`` pairs, best first.

    Raises:
        ValueError: If a stored vector has an invalid shape or a non-finite value.
    """
    query = np.asarray(embedding, dtype=np.float64)
    dimension = int(query.shape[0])
    scores = np.zeros(len(candidates), dtype=np.float64)
    comparable: list[int] = []
    for index, (payload, stored_dimension) in enumerate(candidates):
        if stored_dimension <= 0 or len(payload) != stored_dimension * 4:
            raise ValueError("stored embedding has an invalid shape")
        if stored_dimension == dimension:
            comparable.append(index)
        elif not np.isfinite(np.frombuffer(payload, dtype="<f4")).all():
            raise ValueError("stored embedding values must be finite")

    # Sums accumulate in float64 straight from the float32 blobs, so no widened copy of the vectors is made.
    # A query whose norm overflows scores 0.0 or NaN; NaN ranks last and never qualifies.
    with np.errstate(over="ignore", invalid="ignore"):
        query_norm = np.sqrt(query @ query)
        for start in range(0, len(comparable), _SCORE_BLOCK_ROWS):
            block_rows = comparable[start : start + _SCORE_BLOCK_ROWS]
            block = np.frombuffer(b"".join(candidates[index][0] for index in block_rows), dtype="<f4").reshape(
                len(block_rows), dimension
            )
            squared_norms = np.einsum("ij,ij->i", block, block, dtype=np.float64)
            # A finite float32 vector cannot overflow a float64 sum, so a non-finite sum means a non-finite value.
            if not np.isfinite(squared_norms).all():
                raise ValueError("stored embedding values must be finite")
            denominators = np.sqrt(squared_norms) * query_norm
            scores[block_rows] = np.divide(
                np.einsum("ij,j->i", block, query, dtype=np.float64),
                denominators,
                out=np.zeros(len(block_rows), dtype=np.float64),
                where=denominators > 0.0,
            )

    ranked: list[tuple[int, float]] = []
    for index in np.argsort(-scores, kind="stable"):
        score = float(scores[index])
        if not score >= score_threshold:
            break
        ranked.append((int(index), score))
        if len(ranked) == top_k:
            break
    return ranked


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
                columns_cursor = await database.execute("PRAGMA table_info(reviews)")
                columns = {row[1] for row in await columns_cursor.fetchall()}
                for column, definition in (
                    ("grade", "INTEGER"),
                    ("before_state", "TEXT"),
                    ("after_state", "TEXT"),
                    ("parameter_id", "TEXT"),
                    ("memory_error_signature", "TEXT"),
                ):
                    if column in columns:
                        continue
                    try:
                        await database.execute(f"ALTER TABLE reviews ADD COLUMN {column} {definition}")
                    except aiosqlite.OperationalError as exc:
                        if "duplicate column name" not in str(exc).lower():
                            raise
                if version < _SCHEMA_VERSION:
                    await database.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                try:
                    await database.execute(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts " "USING fts5(episode_id UNINDEXED, text)"
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

    async def apply_review(
        self,
        command: ReviewCommand,
        *,
        grade: Grade | None = None,
        memory_error_signature: str | None = None,
        parameters: MemoryParameters | None = None,
    ) -> ReviewReceipt:
        """Atomically deduplicate, check revision and commit review state.

        The review row contains the complete validated command, making the local
        transaction both the authoritative review log and the replay/archive
        source.  A caller can therefore safely retry after losing an
        acknowledgement or after a subordinate export fails.
        """
        if (grade is None) != (parameters is None):
            raise ValueError("grade and parameters must be supplied together")

        ref_key = command.ref.canonical_key
        payload = json.dumps(command.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        namespace = command.ref.namespace

        async with self._write_lock:
            database = self._require_database()
            await database.execute("BEGIN IMMEDIATE")
            try:
                if command.ref.kind != "episode":
                    await database.execute("ROLLBACK")
                    return ReviewReceipt(
                        status="ignored",
                        dedupe_key=command.dedupe_key,
                        outcome_id=command.signal.outcome_id,
                        ref_key=ref_key,
                        reason="memory ref is unavailable",
                    )

                review_cursor = await database.execute(
                    "SELECT payload_digest, apply_revision FROM reviews WHERE dedupe_key = ?",
                    (command.dedupe_key,),
                )
                review_row = await review_cursor.fetchone()
                if review_row is not None:
                    await database.execute("ROLLBACK")
                    if review_row[0] == command.payload_digest:
                        return ReviewReceipt(
                            status="duplicate",
                            dedupe_key=command.dedupe_key,
                            outcome_id=command.signal.outcome_id,
                            ref_key=ref_key,
                            apply_revision=int(review_row[1]),
                            reason="review already committed",
                        )
                    return ReviewReceipt(
                        status="conflict",
                        dedupe_key=command.dedupe_key,
                        outcome_id=command.signal.outcome_id,
                        ref_key=ref_key,
                        reason="dedupe key was committed with a different payload",
                    )

                # The ref key is derived from the whole namespace, so the episode must match every dimension:
                # an unset dimension admits only an episode that leaves it unset.
                clauses = ["episode_id = ?"]
                episode_parameters: list[Any] = [command.ref.memory_id]
                for field in _FILTERABLE_COLUMNS:
                    value = getattr(namespace, field)
                    if value is None:
                        clauses.append(f"{field} IS NULL")
                    else:
                        clauses.append(f"{field} = ?")
                        episode_parameters.append(value)
                episode_cursor = await database.execute(
                    f"SELECT 1 FROM episodes WHERE {' AND '.join(clauses)}", episode_parameters
                )
                if await episode_cursor.fetchone() is None:
                    await database.execute("ROLLBACK")
                    return ReviewReceipt(
                        status="ignored",
                        dedupe_key=command.dedupe_key,
                        outcome_id=command.signal.outcome_id,
                        ref_key=ref_key,
                        reason="memory ref is unavailable",
                    )

                state_cursor = await database.execute(
                    "SELECT apply_revision, state FROM memory_state WHERE ref_key = ?", (ref_key,)
                )
                state_row = await state_cursor.fetchone()
                current_revision = int(state_row[0]) if state_row is not None else 0

                latest_cursor = await database.execute(
                    "SELECT MAX(outcome_revision) FROM reviews WHERE outcome_id = ? AND ref_key = ?",
                    (command.signal.outcome_id, ref_key),
                )
                latest_row = await latest_cursor.fetchone()
                latest_revision = latest_row[0] if latest_row is not None else None
                if latest_revision is not None and command.signal.outcome_revision < int(latest_revision):
                    await database.execute("ROLLBACK")
                    return ReviewReceipt(
                        status="stale_revision",
                        dedupe_key=command.dedupe_key,
                        outcome_id=command.signal.outcome_id,
                        ref_key=ref_key,
                        apply_revision=current_revision,
                        reason="outcome revision is older than the committed revision",
                    )

                if current_revision != command.expected_revision:
                    await database.execute("ROLLBACK")
                    return ReviewReceipt(
                        status="stale_revision",
                        dedupe_key=command.dedupe_key,
                        outcome_id=command.signal.outcome_id,
                        ref_key=ref_key,
                        apply_revision=current_revision,
                        reason=(f"expected apply_revision={command.expected_revision}, " f"found {current_revision}"),
                    )

                new_revision = current_revision + 1
                reviewed_at = datetime.now(timezone.utc)
                recorded_at = reviewed_at.isoformat()
                before_state: MemoryState | None = None
                after_state: MemoryState | None = None
                if grade is not None and parameters is not None:
                    stored_state = json.loads(state_row[1]) if state_row is not None else {}
                    before_state = MemoryState.model_validate(stored_state.get("memory_state", {}))
                    after_state = transition(before_state, grade, reviewed_at=reviewed_at, parameters=parameters)
                await database.execute(
                    "INSERT INTO reviews "
                    "(dedupe_key, outcome_id, outcome_revision, ref_key, payload_digest, payload, "
                    "apply_revision, recorded_at, grade, before_state, after_state, parameter_id, "
                    "memory_error_signature) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        command.dedupe_key,
                        command.signal.outcome_id,
                        command.signal.outcome_revision,
                        ref_key,
                        command.payload_digest,
                        payload,
                        new_revision,
                        recorded_at,
                        int(grade) if grade is not None else None,
                        (
                            json.dumps(before_state.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
                            if before_state is not None
                            else None
                        ),
                        (
                            json.dumps(after_state.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
                            if after_state is not None
                            else None
                        ),
                        parameters.parameter_id if parameters is not None else None,
                        memory_error_signature[:2000] if memory_error_signature is not None else None,
                    ),
                )
                state_contents: dict[str, Any] = {
                    "apply_revision": new_revision,
                    "command": command.model_dump(mode="json"),
                }
                if after_state is not None:
                    state_contents["memory_state"] = after_state.model_dump(mode="json")
                state_payload = json.dumps(
                    state_contents,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                await database.execute(
                    "INSERT INTO memory_state (ref_key, apply_revision, state, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(ref_key) DO UPDATE SET apply_revision = excluded.apply_revision, "
                    "state = excluded.state, updated_at = excluded.updated_at",
                    (ref_key, new_revision, state_payload, recorded_at),
                )
                await database.execute("COMMIT")
            except BaseException:
                await self._rollback(database)
                raise

        return ReviewReceipt(
            status="applied",
            dedupe_key=command.dedupe_key,
            outcome_id=command.signal.outcome_id,
            ref_key=ref_key,
            apply_revision=new_revision,
        )

    async def get_review_expected_revision(self, dedupe_key: str) -> int | None:
        """Read the ``expected_revision`` of the review committed for a dedupe key.

        A retry has to present the command exactly as it was committed to be
        recognized as a duplicate. The committed row is the only source that
        survives a restart, so a caller rebuilds its command from this value
        instead of from process-local bookkeeping.

        Args:
            dedupe_key: ``ReviewCommand.dedupe_key`` of the review being retried.

        Returns:
            The committed command's ``expected_revision``, or ``None`` when no
            review is committed for the key.

        Raises:
            RuntimeError: If the backend has not been configured.
        """
        cursor = await self._require_database().execute(
            "SELECT json_extract(payload, '$.expected_revision') FROM reviews WHERE dedupe_key = ?",
            (dedupe_key,),
        )
        row = await cursor.fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])

    async def merge_citation(self, citation: MemoryCitation) -> MemoryCitation:
        """Durably merge a citation into the references already cited for its exposure.

        The read, merge and write happen in one ``BEGIN IMMEDIATE`` transaction,
        so two processes citing the same exposure cannot lose each other's
        references. Citations older than the retention window are pruned in
        the same transaction, which keeps the table bounded without a
        separate maintenance job.

        Args:
            citation: Validated references cited for one final-delivery exposure.

        Returns:
            Every reference cited for the exposure after the merge.

        Raises:
            ValueError: If the exposure was cited under another namespace or the
                merge exceeds the citation cardinality.
            RuntimeError: If the backend has not been configured.
        """
        now = datetime.now(timezone.utc)
        async with self._write_lock:
            database = self._require_database()
            await database.execute("BEGIN IMMEDIATE")
            try:
                await database.execute(
                    "DELETE FROM citations WHERE updated_at < ?",
                    ((now - timedelta(days=_CITATION_RETENTION_DAYS)).isoformat(),),
                )
                cursor = await database.execute(
                    "SELECT payload FROM citations WHERE exposure_id = ?", (citation.exposure_id,)
                )
                row = await cursor.fetchone()
                merged = citation
                if row is not None:
                    merged = MemoryCitation.model_validate_json(row[0]).merged_with(citation)
                await database.execute(
                    "INSERT INTO citations (exposure_id, payload, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(exposure_id) DO UPDATE SET payload = excluded.payload, "
                    "updated_at = excluded.updated_at",
                    (citation.exposure_id, merged.model_dump_json(), now.isoformat()),
                )
                await database.execute("COMMIT")
            except BaseException:
                await self._rollback(database)
                raise
        return merged

    async def get_citation(self, exposure_id: str) -> MemoryCitation | None:
        """Read the references durably cited for one exposure.

        Args:
            exposure_id: Final-delivery exposure identifier.

        Returns:
            The committed citation, or ``None`` when the exposure was never cited
            or its citation has been pruned.

        Raises:
            RuntimeError: If the backend has not been configured.
        """
        cursor = await self._require_database().execute(
            "SELECT payload FROM citations WHERE exposure_id = ?", (exposure_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return MemoryCitation.model_validate_json(row[0])

    async def delete_citations(self, exposure_ids: list[str]) -> int:
        """Delete the durable citations of released exposures.

        Args:
            exposure_ids: Final-delivery exposure identifiers to forget.

        Returns:
            The number of citations deleted.

        Raises:
            RuntimeError: If the backend has not been configured.
        """
        unique_ids = list(dict.fromkeys(exposure_ids))
        if not unique_ids:
            return 0
        async with self._write_lock:
            database = self._require_database()
            await database.execute("BEGIN IMMEDIATE")
            try:
                cursor = await database.execute(
                    f"DELETE FROM citations WHERE exposure_id IN ({', '.join('?' * len(unique_ids))})",
                    unique_ids,
                )
                deleted = cursor.rowcount
                await database.execute("COMMIT")
            except BaseException:
                await self._rollback(database)
                raise
        return deleted

    async def get_memory_states(self, ref_keys: Sequence[str]) -> dict[str, MemoryState]:
        """Read the earned dynamics state committed for the given memory references.

        A reference key is the ``MemoryRef.canonical_key`` hash of the full
        namespace, memory id and content version, so a caller can only read
        the state of a memory whose exact scope it already holds.

        Args:
            ref_keys: Canonical reference keys to resolve; duplicates are read once.

        Returns:
            The committed state per reference key. A key with no review, or with a
            review that recorded no state, is absent.

        Raises:
            RuntimeError: If the backend has not been configured.
        """
        database = self._require_database()
        unique_keys = list(dict.fromkeys(ref_keys))
        states: dict[str, MemoryState] = {}
        for start in range(0, len(unique_keys), _STATE_READ_BATCH):
            batch = unique_keys[start : start + _STATE_READ_BATCH]
            cursor = await database.execute(
                f"SELECT ref_key, state FROM memory_state WHERE ref_key IN ({', '.join('?' * len(batch))})",
                batch,
            )
            for ref_key, payload in await cursor.fetchall():
                try:
                    stored_state = json.loads(payload).get("memory_state")
                    if stored_state is not None:
                        states[ref_key] = MemoryState.model_validate(stored_state)
                except (ValueError, AttributeError) as exc:
                    logger.warning("Ignoring unreadable dynamics state for %s: %s", ref_key, exc)
        return states

    async def list_reviews(self, namespace: MemoryNamespace, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Return committed reviews for one namespace in a deterministic total order.

        Args:
            namespace: Scope of committed review commands to return. Every set dimension must match;
                unset dimensions are unconstrained, exactly as in ``build_filter``.
            limit: Optional maximum row count after scope filtering and ordering.

        Returns:
            Serialized committed review rows in durable total order.

        Raises:
            ValueError: If ``limit`` is non-positive.
            RuntimeError: If the backend has not been configured.
        """
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")

        clauses: list[str] = []
        parameters: list[Any] = []
        for field, value in namespace.build_filter().items():
            clauses.append(f"json_extract(payload, '$.ref.namespace.{field}') = ?")
            parameters.append(value)

        query = (
            "SELECT dedupe_key, outcome_id, outcome_revision, ref_key, apply_revision, recorded_at, payload, "
            "grade, before_state, after_state, parameter_id, memory_error_signature "
            f"FROM reviews WHERE {' AND '.join(clauses)} "
            # rowid follows commit order; recorded_at is a wall clock that can step back between processes.
            "ORDER BY rowid ASC"
        )
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)

        database = self._require_database()
        cursor = await database.execute(query, parameters)
        rows = await cursor.fetchall()
        reviews: list[dict[str, Any]] = []
        for row in rows:
            review = {
                "dedupe_key": row[0],
                "outcome_id": row[1],
                "outcome_revision": row[2],
                "ref_key": row[3],
                "apply_revision": row[4],
                "recorded_at": row[5],
                "command": json.loads(row[6]),
            }
            if row[7] is not None:
                review["record"] = {
                    "grade": int(row[7]),
                    "before": json.loads(row[8]),
                    "after": json.loads(row[9]),
                    "parameter_id": row[10],
                    "memory_error_signature": row[11],
                }
            reviews.append(review)
        return reviews

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
        when the measured exact-search ceiling is exceeded. Candidates are scored
        in a worker thread, and only the winning rows have their payload read.
        """
        self._validate_search_arguments(embedding, top_k, score_threshold)
        if top_k == 0:
            return []
        where_sql, params = self._build_where(namespace_filter, include_failures_only)
        database = self._require_database()
        cursor = await database.execute(
            f"SELECT episode_id, embedding, embedding_dim FROM episodes WHERE {where_sql} "
            "AND embedding IS NOT NULL ORDER BY created_at DESC, episode_id DESC LIMIT ?",
            [*params, self._vector_ceiling + 1],
        )
        rows = list(await cursor.fetchall())
        if not rows:
            return []
        if len(rows) > self._vector_ceiling:
            # One row beyond the ceiling is read only to detect truncation; it is never scored.
            del rows[self._vector_ceiling :]
            logger.warning(
                "Vector search is degraded: the scope holds more than %d candidates, only the newest %d are scored "
                "(scope dimensions: %s)",
                self._vector_ceiling,
                self._vector_ceiling,
                ", ".join(sorted(namespace_filter)) or "none",
            )
        ranked = await asyncio.to_thread(
            _rank_candidates,
            embedding,
            [(row[1], int(row[2])) for row in rows],
            score_threshold,
            top_k,
        )
        payloads = await self._payloads_by_id([rows[index][0] for index, _ in ranked])
        results: list[EpisodeSearchResult] = []
        for index, score in ranked:
            # A row deleted between the two reads is no longer a result.
            payload = payloads.get(rows[index][0])
            if payload is not None:
                results.append(EpisodeSearchResult(**json.loads(payload), score=min(max(score, 0.0), 1.01)))
        return results

    async def review_status(self, namespace_filter: dict[str, Any]) -> dict[str, int | str]:
        """Verify storage availability before reporting this backend's transactional review state.

        SQLite commits each review and its derived state atomically; it has no durable replay queue.
        A closed or failed connection raises instead of advertising a synchronized store.
        """
        await self.count(namespace_filter)
        return {"status": "synchronized", "durable_pending_reviews": 0}

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

    async def get_by_ids(
        self,
        episode_ids: Sequence[str],
        namespace_filter: dict[str, Any],
    ) -> list[EpisodicMemory]:
        """Return the requested episodes that lie inside a scope, newest first.

        An unknown id and an id outside the scope are both simply absent, so a
        caller cannot tell one from the other.

        Args:
            episode_ids: Episode ids to read. Duplicates are read once.
            namespace_filter: Scope dimensions every returned episode must match.

        Returns:
            The matching episodes, ordered like :meth:`get_recent`.
        """
        unique_ids = list(dict.fromkeys(episode_ids))
        if not unique_ids:
            return []
        where_sql, params = self._build_where(namespace_filter)
        database = self._require_database()
        rows: list[Any] = []
        for start in range(0, len(unique_ids), _ID_READ_BATCH):
            batch = unique_ids[start : start + _ID_READ_BATCH]
            placeholders = ", ".join("?" for _ in batch)
            cursor = await database.execute(
                f"SELECT created_at, episode_id, payload FROM episodes WHERE {where_sql} "
                f"AND episode_id IN ({placeholders})",
                [*params, *batch],
            )
            rows.extend(await cursor.fetchall())
        rows.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return [EpisodicMemory.from_dict(json.loads(row[2])) for row in rows]

    async def get_recent_matching(
        self,
        namespace_filter: dict[str, Any],
        *,
        limit: int | None = None,
        categories: Sequence[str] | None = None,
        failures_only: bool = False,
        before_id: str | None = None,
    ) -> list[EpisodicMemory]:
        """Return scoped episodes newest first, selecting by category, failure and page in SQL.

        Args:
            namespace_filter: Scope dimensions applied before every other predicate.
            limit: Maximum number of rows, or ``None`` for every matching row.
            categories: Category values to keep; ``None`` keeps every category.
            failures_only: Whether to keep only failure episodes.
            before_id: Episode id of the last row of the previous page. Only rows
                ordered after it are returned; if that episode no longer exists
                the page is empty.

        Returns:
            The matching episodes, ordered like :meth:`get_recent`.

        Raises:
            ValueError: If ``limit`` is negative.
        """
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        if limit == 0 or (categories is not None and not categories):
            return []
        where_sql, params = self._build_where(namespace_filter, failures_only)
        query = f"SELECT payload FROM episodes WHERE {where_sql}"
        if categories is not None:
            placeholders = ", ".join("?" for _ in categories)
            query += f" AND json_extract(payload, '$.category') IN ({placeholders})"
            params.extend(categories)
        if before_id is not None:
            query += (
                " AND (created_at, episode_id) < (SELECT created_at, episode_id FROM episodes WHERE episode_id = ?)"
            )
            params.append(before_id)
        query += " ORDER BY created_at DESC, episode_id DESC"
        if limit is not None:
            query += " LIMIT ?"
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
    def _build_where(namespace_filter: dict[str, Any], include_failures_only: bool = False) -> tuple[str, list[Any]]:
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

    async def _payloads_by_id(self, episode_ids: Sequence[str]) -> dict[str, str]:
        """Read the serialized payload of specific episodes.

        Args:
            episode_ids: Episode ids already admitted by a scoped query.

        Returns:
            Serialized payloads keyed by episode id; a missing id is absent.
        """
        database = self._require_database()
        payloads: dict[str, str] = {}
        for start in range(0, len(episode_ids), _ID_READ_BATCH):
            batch = list(episode_ids[start : start + _ID_READ_BATCH])
            placeholders = ", ".join("?" for _ in batch)
            cursor = await database.execute(
                f"SELECT episode_id, payload FROM episodes WHERE episode_id IN ({placeholders})", batch
            )
            payloads.update({row[0]: row[1] for row in await cursor.fetchall()})
        return payloads

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
