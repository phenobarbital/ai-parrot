"""S2 spike: SQLite/WAL episodic backend prototype (throwaway — M2 decides the real module)."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite  # pyproject.toml:192 — core dependency

from parrot.memory.episodic.models import EpisodeSearchResult, EpisodicMemory  # models.py:203,55

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    episode_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL,
    user_id TEXT, session_id TEXT, room_id TEXT, crew_id TEXT, model_id TEXT,
    created_at TEXT NOT NULL, expires_at TEXT, is_failure INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL, embedding TEXT
);
CREATE TABLE IF NOT EXISTS reviews (
    outcome_id TEXT NOT NULL, outcome_revision INTEGER NOT NULL, episode_id TEXT NOT NULL,
    grade INTEGER, recorded_at TEXT NOT NULL, PRIMARY KEY (outcome_id, outcome_revision, episode_id)
);
CREATE TABLE IF NOT EXISTS memory_state (
    episode_id TEXT PRIMARY KEY, apply_revision INTEGER NOT NULL, state TEXT NOT NULL
);
"""

# Columns namespace_filter / build_filter() dicts are allowed to key on. `model_id`
# is the prototype's own dimension (spec §2 "Encode backend/model without ambiguous
# slash concatenation") — it is a plain column here, never concatenated into anything.
_FILTERABLE_COLUMNS = ("tenant_id", "agent_id", "user_id", "session_id", "room_id", "crew_id", "model_id")


@dataclass(frozen=True)
class ReviewCommand:
    """Experimental review input: idempotency key is (outcome_id, outcome_revision), never episode provenance."""

    outcome_id: str
    outcome_revision: int
    episode_id: str
    grade: int
    expected_apply_revision: int
    new_state: dict[str, Any]


@dataclass(frozen=True)
class ReviewReceipt:
    """Result category per spec §7 Failure Contract."""

    episode_id: str
    result: str  # applied | duplicate | stale_revision | pending
    apply_revision: int
    reason: str = ""


def _cosine(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity — no numpy dependency needed for the spike."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class SQLiteEpisodeBackend:
    """Implements AbstractEpisodeBackend (abstract.py:11) plus apply_review/search_text/replay for the gate."""

    def __init__(self, path: Path, *, busy_timeout_ms: int = 5000) -> None:
        self._path = Path(path)
        self._busy_timeout_ms = busy_timeout_ms
        self._db: aiosqlite.Connection | None = None
        self._fts_enabled = False

    async def configure(self) -> None:
        """Open the connection, enable WAL + busy_timeout, create schema.

        Uses ``isolation_level=None`` (autocommit) so that ordinary CRUD
        statements commit immediately, while ``apply_review`` manages its own
        explicit ``BEGIN IMMEDIATE`` / ``COMMIT`` / ``ROLLBACK`` transaction —
        this is what makes the review protocol's one-transaction guarantee
        possible instead of fighting sqlite3's implicit transaction wrapping.
        """
        self._db = await aiosqlite.connect(str(self._path), isolation_level=None, timeout=self._busy_timeout_ms / 1000)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(SCHEMA)
        try:
            await self._db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(episode_id UNINDEXED, text)")
            self._fts_enabled = True
        except aiosqlite.OperationalError:
            self._fts_enabled = False
            logger.warning("FTS5 unavailable in this SQLite build; search_text() falls back to LIKE.")
        logger.info("S2 sqlite backend ready at %s (fts5=%s)", self._path, self._fts_enabled)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> "SQLiteEpisodeBackend":
        await self.configure()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    @staticmethod
    def _build_where(namespace_filter: dict[str, Any], include_failures_only: bool = False) -> tuple[str, list[Any]]:
        """Build a WHERE clause restricted to known columns, applied BEFORE any top-k/LIMIT."""
        clauses = ["1=1"]
        params: list[Any] = []
        for field, value in namespace_filter.items():
            if field not in _FILTERABLE_COLUMNS:
                continue
            clauses.append(f"{field} = ?")
            params.append(value)
        if include_failures_only:
            clauses.append("is_failure = 1")
        return " AND ".join(clauses), params

    async def store(self, episode: EpisodicMemory) -> str:
        """INSERT OR IGNORE (duplicate ids are no-ops, like FAISS/PG); model_id from episode.metadata."""
        assert self._db is not None
        model_id = episode.metadata.get("model_id")
        payload = json.dumps(episode.to_dict())
        embedding = json.dumps(episode.embedding) if episode.embedding else None
        cur = await self._db.execute(
            "INSERT OR IGNORE INTO episodes "
            "(episode_id, tenant_id, agent_id, user_id, session_id, room_id, crew_id, model_id, "
            " created_at, expires_at, is_failure, payload, embedding) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                episode.episode_id,
                episode.tenant_id,
                episode.agent_id,
                episode.user_id,
                episode.session_id,
                episode.room_id,
                episode.crew_id,
                model_id,
                episode.created_at.isoformat(),
                episode.expires_at.isoformat() if episode.expires_at else None,
                int(episode.is_failure),
                payload,
                embedding,
            ),
        )
        if cur.rowcount and self._fts_enabled:
            await self._db.execute(
                "INSERT INTO episodes_fts (episode_id, text) VALUES (?, ?)",
                (episode.episode_id, episode.searchable_text()),
            )
        return episode.episode_id

    async def search_similar(
        self,
        embedding: list[float],
        namespace_filter: dict[str, Any],
        top_k: int = 5,
        score_threshold: float = 0.3,
        include_failures_only: bool = False,
    ) -> list[EpisodeSearchResult]:
        """SQL filter (incl. model_id) BEFORE top-k, cosine in Python over the filtered candidate set."""
        assert self._db is not None
        where_sql, params = self._build_where(namespace_filter, include_failures_only)
        cur = await self._db.execute(
            f"SELECT payload, embedding FROM episodes WHERE {where_sql} AND embedding IS NOT NULL", params
        )
        rows = await cur.fetchall()
        scored: list[tuple[float, dict[str, Any]]] = []
        for payload_json, embedding_json in rows:
            candidate = json.loads(embedding_json)
            score = _cosine(embedding, candidate)
            if score < score_threshold:
                continue
            scored.append((score, json.loads(payload_json)))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [EpisodeSearchResult(**data, score=min(score, 1.01)) for score, data in scored[:top_k]]

    async def search_text(self, query: str, namespace_filter: dict[str, Any], top_k: int = 5) -> list[EpisodeSearchResult]:
        """FTS5 bm25 (normalized to [0,1]) when available, else a LIKE fallback — recall without embeddings."""
        assert self._db is not None
        where_sql, params = self._build_where(namespace_filter)
        if self._fts_enabled:
            # FTS5 parses the MATCH argument through its own query grammar even when bound as a
            # parameter — an unquoted term containing `-`, `:` or `"` is control syntax there, not
            # literal text (e.g. "w3-624" raises "no such column: 624"). Quoting as a phrase makes
            # arbitrary caller text safe to search verbatim.
            fts_query = '"' + query.replace('"', '""') + '"'
            sql = (
                "SELECT e.payload, bm25(episodes_fts) AS rank FROM episodes_fts "
                "JOIN episodes e ON e.episode_id = episodes_fts.episode_id "
                f"WHERE episodes_fts MATCH ? AND {where_sql} ORDER BY rank LIMIT ?"
            )
            cur = await self._db.execute(sql, [fts_query, *params, top_k])
            rows = await cur.fetchall()
            if not rows:
                return []
            ranks = [rank for _, rank in rows]
            lo, hi = min(ranks), max(ranks)
            spread = hi - lo
            results = []
            for payload_json, rank in rows:
                # bm25(): a MORE NEGATIVE value is a BETTER match; normalize so best -> 1.0.
                score = 1.0 if spread == 0 else (hi - rank) / spread
                results.append(EpisodeSearchResult(**json.loads(payload_json), score=round(score, 6)))
            return results

        like_query = f"%{query}%"
        sql = f"SELECT payload FROM episodes WHERE {where_sql} AND payload LIKE ? LIMIT ?"
        cur = await self._db.execute(sql, [*params, like_query, top_k])
        rows = await cur.fetchall()
        return [EpisodeSearchResult(**json.loads(row[0]), score=1.0) for row in rows]

    async def apply_review(self, command: ReviewCommand) -> ReviewReceipt:
        """One transaction: dedupe(outcome_id, outcome_revision) + apply_revision check + review + state + ack.

        Honours ``S2_CRASH_AT`` (before_log | after_log | after_state) by calling
        ``os._exit(137)`` at the matching point INSIDE the still-open transaction —
        since none of those points has reached ``COMMIT`` yet, SQLite rolls the
        whole transaction back on the next connection, proving the invariant that
        a crash at any point before the ack never leaves a partial write behind.
        """
        assert self._db is not None
        crash_at = os.environ.get("S2_CRASH_AT")
        await self._db.execute("BEGIN IMMEDIATE")
        try:
            cur = await self._db.execute(
                "SELECT 1 FROM reviews WHERE outcome_id = ? AND outcome_revision = ? AND episode_id = ?",
                (command.outcome_id, command.outcome_revision, command.episode_id),
            )
            duplicate = await cur.fetchone() is not None

            state_cur = await self._db.execute(
                "SELECT apply_revision FROM memory_state WHERE episode_id = ?", (command.episode_id,)
            )
            state_row = await state_cur.fetchone()
            current_rev = state_row[0] if state_row is not None else 0

            if duplicate:
                await self._db.execute("ROLLBACK")
                return ReviewReceipt(
                    episode_id=command.episode_id,
                    result="duplicate",
                    apply_revision=current_rev,
                    reason="outcome_id/outcome_revision already recorded",
                )

            if current_rev != command.expected_apply_revision:
                await self._db.execute("ROLLBACK")
                return ReviewReceipt(
                    episode_id=command.episode_id,
                    result="stale_revision",
                    apply_revision=current_rev,
                    reason=f"expected apply_revision={command.expected_apply_revision}, found {current_rev}",
                )

            if crash_at == "before_log":
                os._exit(137)

            recorded_at = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                "INSERT INTO reviews (outcome_id, outcome_revision, episode_id, grade, recorded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (command.outcome_id, command.outcome_revision, command.episode_id, command.grade, recorded_at),
            )

            if crash_at == "after_log":
                os._exit(137)

            new_rev = current_rev + 1
            await self._db.execute(
                "INSERT INTO memory_state (episode_id, apply_revision, state) VALUES (?, ?, ?) "
                "ON CONFLICT(episode_id) DO UPDATE SET apply_revision = excluded.apply_revision, "
                "state = excluded.state",
                (command.episode_id, new_rev, json.dumps(command.new_state)),
            )

            if crash_at == "after_state":
                os._exit(137)

            await self._db.execute("COMMIT")
            return ReviewReceipt(episode_id=command.episode_id, result="applied", apply_revision=new_rev)
        except Exception:
            try:
                await self._db.execute("ROLLBACK")
            except Exception:  # noqa: BLE001 - best-effort cleanup, original exception re-raised below
                pass
            raise

    async def replay(self, log_rows: list[ReviewCommand]) -> int:
        """Re-apply commands idempotently. Convergence invariant: spec §2 Durable Storage.

        Returns:
            Number of commands that transitioned to ``applied`` on this replay
            (already-applied commands come back ``duplicate`` and are not counted).
        """
        applied = 0
        for command in log_rows:
            receipt = await self.apply_review(command)
            if receipt.result == "applied":
                applied += 1
        return applied

    async def get_recent(
        self,
        namespace_filter: dict[str, Any],
        limit: int = 10,
        since: datetime | None = None,
    ) -> list[EpisodicMemory]:
        assert self._db is not None
        where_sql, params = self._build_where(namespace_filter)
        query = f"SELECT payload FROM episodes WHERE {where_sql}"
        if since is not None:
            query += " AND created_at > ?"
            params.append(since.isoformat())
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cur = await self._db.execute(query, params)
        rows = await cur.fetchall()
        return [EpisodicMemory.from_dict(json.loads(row[0])) for row in rows]

    async def get_failures(self, agent_id: str, tenant_id: str = "default", limit: int = 5) -> list[EpisodicMemory]:
        assert self._db is not None
        cur = await self._db.execute(
            "SELECT payload FROM episodes WHERE agent_id = ? AND tenant_id = ? AND is_failure = 1 "
            "ORDER BY created_at DESC LIMIT ?",
            (agent_id, tenant_id, limit),
        )
        rows = await cur.fetchall()
        return [EpisodicMemory.from_dict(json.loads(row[0])) for row in rows]

    async def delete_expired(self) -> int:
        """Delete episodes past ``expires_at``. Rows with ``expires_at IS NULL`` (imported feedback) are exempt."""
        assert self._db is not None
        now = datetime.now(timezone.utc).isoformat()
        cur = await self._db.execute(
            "SELECT episode_id FROM episodes WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,)
        )
        rows = await cur.fetchall()
        ids = [row[0] for row in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            await self._db.execute(f"DELETE FROM episodes WHERE episode_id IN ({placeholders})", ids)
            if self._fts_enabled:
                await self._db.execute(f"DELETE FROM episodes_fts WHERE episode_id IN ({placeholders})", ids)
        return len(ids)

    async def count(self, namespace_filter: dict[str, Any]) -> int:
        assert self._db is not None
        where_sql, params = self._build_where(namespace_filter)
        cur = await self._db.execute(f"SELECT COUNT(*) FROM episodes WHERE {where_sql}", params)
        row = await cur.fetchone()
        return row[0] if row else 0

    async def update_metadata(self, episode_ids: list[str], patch: dict[str, Any]) -> int:
        """Shallow merge into the payload's ``metadata`` — same non-atomic shape as PG/Redis (spec §6);

        NOT the review protocol's mechanism, only completes the AbstractEpisodeBackend contract.
        """
        assert self._db is not None
        if not episode_ids:
            return 0
        updated = 0
        for episode_id in episode_ids:
            cur = await self._db.execute("SELECT payload FROM episodes WHERE episode_id = ?", (episode_id,))
            row = await cur.fetchone()
            if row is None:
                continue
            data = json.loads(row[0])
            data.setdefault("metadata", {}).update(patch)
            await self._db.execute(
                "UPDATE episodes SET payload = ? WHERE episode_id = ?", (json.dumps(data), episode_id)
            )
            updated += 1
        return updated
