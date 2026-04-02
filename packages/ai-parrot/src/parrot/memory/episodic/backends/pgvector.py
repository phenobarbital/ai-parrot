"""PgVector backend for episodic memory storage.

Uses asyncpg directly for maximum control over pgvector queries.
Auto-creates schema, table, and indexes on configure().
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg

from ..models import (
    EpisodeCategory,
    EpisodeOutcome,
    EpisodeSearchResult,
    EpisodicMemory,
)

logger = logging.getLogger(__name__)

# SQL column list (excluding embedding and searchable_text) for SELECT queries
_COLUMNS = (
    "episode_id, created_at, updated_at, expires_at, "
    "tenant_id, agent_id, user_id, session_id, room_id, crew_id, "
    "situation, action_taken, outcome, outcome_details, error_type, error_message, "
    "reflection, lesson_learned, suggested_action, "
    "category, importance, is_failure, related_tools, related_entities, "
    "metadata"
)


def _row_to_episode(row: asyncpg.Record) -> EpisodicMemory:
    """Convert an asyncpg Record to an EpisodicMemory instance."""
    return EpisodicMemory(
        episode_id=str(row["episode_id"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        expires_at=row["expires_at"],
        tenant_id=row["tenant_id"],
        agent_id=row["agent_id"],
        user_id=row["user_id"],
        session_id=row["session_id"],
        room_id=row["room_id"],
        crew_id=row["crew_id"],
        situation=row["situation"],
        action_taken=row["action_taken"],
        outcome=EpisodeOutcome(row["outcome"]),
        outcome_details=row["outcome_details"],
        error_type=row["error_type"],
        error_message=row["error_message"],
        reflection=row["reflection"],
        lesson_learned=row["lesson_learned"],
        suggested_action=row["suggested_action"],
        category=EpisodeCategory(row["category"]),
        importance=row["importance"],
        is_failure=row["is_failure"],
        related_tools=list(row["related_tools"]) if row["related_tools"] else [],
        related_entities=list(row["related_entities"]) if row["related_entities"] else [],
        metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else (row["metadata"] or {}),
    )


class PgVectorBackend:
    """PostgreSQL + pgvector backend for episodic memory.

    Uses asyncpg connection pool for async access. Auto-creates schema,
    table, and indexes on configure(). Similarity search uses cosine
    distance with dimensional WHERE filters.

    Args:
        dsn: PostgreSQL connection string.
        schema: PostgreSQL schema name.
        table: Table name within the schema.
        pool_size: Connection pool size.
    """

    def __init__(
        self,
        dsn: str,
        schema: str = "parrot_memory",
        table: str = "episodic_memory",
        pool_size: int = 10,
    ) -> None:
        self._dsn = dsn
        self._schema = schema
        self._table = table
        self._pool_size = pool_size
        self._pool: asyncpg.Pool | None = None

    @property
    def _fqtn(self) -> str:
        """Fully-qualified table name."""
        return f"{self._schema}.{self._table}"

    async def configure(self) -> None:
        """Create connection pool, schema, table, and indexes.

        All DDL statements use IF NOT EXISTS for idempotency.
        """
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=1,
            max_size=self._pool_size,
        )
        async with self._pool.acquire() as conn:
            # Enable pgvector extension
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

            # Create schema
            await conn.execute(
                f"CREATE SCHEMA IF NOT EXISTS {self._schema}"
            )

            # Create table
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._fqtn} (
                    episode_id      UUID PRIMARY KEY,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at      TIMESTAMPTZ,

                    tenant_id       VARCHAR(64) NOT NULL DEFAULT 'default',
                    agent_id        VARCHAR(128) NOT NULL,
                    user_id         VARCHAR(128),
                    session_id      VARCHAR(128),
                    room_id         VARCHAR(256),
                    crew_id         VARCHAR(128),

                    situation       TEXT NOT NULL,
                    action_taken    TEXT NOT NULL,
                    outcome         VARCHAR(16) NOT NULL,
                    outcome_details TEXT,
                    error_type      VARCHAR(128),
                    error_message   TEXT,

                    reflection      TEXT,
                    lesson_learned  VARCHAR(512),
                    suggested_action TEXT,

                    category        VARCHAR(32) NOT NULL DEFAULT 'tool_execution',
                    importance      SMALLINT NOT NULL DEFAULT 5,
                    is_failure      BOOLEAN NOT NULL DEFAULT FALSE,
                    related_tools   VARCHAR[],
                    related_entities VARCHAR[],

                    embedding       vector(384),

                    metadata        JSONB DEFAULT '{{}}'::jsonb
                )
            """)

            # Create indexes
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_episodes_agent_user
                ON {self._fqtn} (tenant_id, agent_id, user_id)
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_episodes_agent_room
                ON {self._fqtn} (tenant_id, agent_id, room_id)
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_episodes_crew
                ON {self._fqtn} (tenant_id, crew_id)
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_episodes_failures
                ON {self._fqtn} (agent_id, is_failure)
                WHERE is_failure = TRUE
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_episodes_expires
                ON {self._fqtn} (expires_at)
                WHERE expires_at IS NOT NULL
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_episodes_importance
                ON {self._fqtn} (agent_id, importance DESC)
            """)

            # IVFFlat index for vector search (only if table has rows,
            # otherwise ivfflat fails; use ON EMPTY to skip gracefully)
            try:
                await conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_episodes_embedding
                    ON {self._fqtn}
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                """)
            except asyncpg.exceptions.InvalidParameterValueError:
                # IVFFlat requires rows; will be created later or use flat scan
                logger.debug(
                    "Skipping IVFFlat index creation (table may be empty). "
                    "Flat scan will be used until index is built."
                )

        # Add tsvector column and GIN index for hybrid search (idempotent)
        await self._add_tsvector_column()

        logger.info(
            "PgVectorBackend configured: %s.%s", self._schema, self._table
        )

    async def _add_tsvector_column(self) -> None:
        """Add tsvector column for full-text search (idempotent migration helper).

        Adds ``searchable_text tsvector`` column to the episodes table if it
        does not exist, creates a GIN index on it, and backfills existing rows.

        This method is called automatically by ``configure()`` and is safe to
        call on an existing table without data loss.
        """
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            # Add column (idempotent)
            await conn.execute(f"""
                ALTER TABLE {self._fqtn}
                ADD COLUMN IF NOT EXISTS searchable_text tsvector
            """)

            # Create GIN index (idempotent)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_episodes_searchable_text
                ON {self._fqtn}
                USING GIN(searchable_text)
            """)

            # Backfill existing rows where searchable_text is NULL
            await conn.execute(f"""
                UPDATE {self._fqtn}
                SET searchable_text = to_tsvector(
                    'english',
                    situation || ' ' || action_taken ||
                    ' ' || COALESCE(lesson_learned, '')
                )
                WHERE searchable_text IS NULL
            """)

        logger.debug(
            "tsvector column ensured on %s (GIN index + backfill complete)",
            self._fqtn,
        )

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def __aenter__(self) -> PgVectorBackend:
        await self.configure()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    def _ensure_pool(self) -> asyncpg.Pool:
        """Raise if pool is not initialized."""
        if self._pool is None:
            raise RuntimeError(
                "PgVectorBackend not configured. Call configure() first."
            )
        return self._pool

    async def store(self, episode: EpisodicMemory) -> str:
        """Store an episode. Returns episode_id.

        Uses INSERT ... ON CONFLICT DO NOTHING for idempotency.
        """
        pool = self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self._fqtn} (
                    episode_id, created_at, updated_at, expires_at,
                    tenant_id, agent_id, user_id, session_id, room_id, crew_id,
                    situation, action_taken, outcome, outcome_details,
                    error_type, error_message,
                    reflection, lesson_learned, suggested_action,
                    category, importance, is_failure,
                    related_tools, related_entities,
                    embedding, metadata,
                    searchable_text
                ) VALUES (
                    $1::uuid, $2, $3, $4,
                    $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14,
                    $15, $16,
                    $17, $18, $19,
                    $20, $21, $22,
                    $23, $24,
                    $25, $26::jsonb,
                    to_tsvector('english',
                        $11 || ' ' || $12 || ' ' || COALESCE($18, '')
                    )
                )
                ON CONFLICT (episode_id) DO NOTHING
                """,
                episode.episode_id,
                episode.created_at,
                episode.updated_at,
                episode.expires_at,
                episode.tenant_id,
                episode.agent_id,
                episode.user_id,
                episode.session_id,
                episode.room_id,
                episode.crew_id,
                episode.situation,
                episode.action_taken,
                episode.outcome.value,
                episode.outcome_details,
                episode.error_type,
                episode.error_message,
                episode.reflection,
                episode.lesson_learned,
                episode.suggested_action,
                episode.category.value,
                episode.importance,
                episode.is_failure,
                episode.related_tools or None,
                episode.related_entities or None,
                str(episode.embedding) if episode.embedding else None,
                json.dumps(episode.metadata),
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
        """Search episodes by cosine similarity with dimensional filters.

        Score threshold is applied post-query.
        """
        pool = self._ensure_pool()

        # Build dynamic WHERE clause from namespace filter
        conditions = []
        params: list[Any] = [str(embedding)]  # $1 = embedding vector
        param_idx = 2

        for field, value in namespace_filter.items():
            conditions.append(f"{field} = ${param_idx}")
            params.append(value)
            param_idx += 1

        if include_failures_only:
            conditions.append("is_failure = TRUE")

        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        query = f"""
            SELECT {_COLUMNS},
                   1 - (embedding <=> $1::vector) AS score
            FROM {self._fqtn}
            WHERE {where_clause}
              AND embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT ${param_idx}
        """
        params.append(top_k)

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        results = []
        for row in rows:
            score = float(row["score"])
            if score >= score_threshold:
                ep = _row_to_episode(row)
                results.append(
                    EpisodeSearchResult(
                        **ep.model_dump(),
                        embedding=ep.embedding,
                        score=score,
                    )
                )
        return results

    async def get_recent(
        self,
        namespace_filter: dict[str, Any],
        limit: int = 10,
        since: datetime | None = None,
    ) -> list[EpisodicMemory]:
        """Get recent episodes ordered by created_at DESC."""
        pool = self._ensure_pool()

        conditions = []
        params: list[Any] = []
        param_idx = 1

        for field, value in namespace_filter.items():
            conditions.append(f"{field} = ${param_idx}")
            params.append(value)
            param_idx += 1

        if since is not None:
            conditions.append(f"created_at > ${param_idx}")
            params.append(since)
            param_idx += 1

        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        query = f"""
            SELECT {_COLUMNS}
            FROM {self._fqtn}
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_idx}
        """
        params.append(limit)

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [_row_to_episode(row) for row in rows]

    async def get_failures(
        self,
        agent_id: str,
        tenant_id: str = "default",
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        """Get recent failure episodes for an agent.

        Uses the partial index on (agent_id, is_failure) WHERE is_failure = TRUE.
        """
        pool = self._ensure_pool()
        query = f"""
            SELECT {_COLUMNS}
            FROM {self._fqtn}
            WHERE tenant_id = $1
              AND agent_id = $2
              AND is_failure = TRUE
            ORDER BY created_at DESC
            LIMIT $3
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, tenant_id, agent_id, limit)

        return [_row_to_episode(row) for row in rows]

    async def delete_expired(self) -> int:
        """Delete episodes past their expires_at. Returns count deleted."""
        pool = self._ensure_pool()
        now = datetime.now(timezone.utc)
        query = f"""
            DELETE FROM {self._fqtn}
            WHERE expires_at IS NOT NULL AND expires_at < $1
        """
        async with pool.acquire() as conn:
            result = await conn.execute(query, now)

        # asyncpg returns "DELETE N"
        count = int(result.split()[-1])
        if count > 0:
            logger.info("Deleted %d expired episodes", count)
        return count

    async def count(self, namespace_filter: dict[str, Any]) -> int:
        """Count episodes matching a namespace filter."""
        pool = self._ensure_pool()

        conditions = []
        params: list[Any] = []
        param_idx = 1

        for field, value in namespace_filter.items():
            conditions.append(f"{field} = ${param_idx}")
            params.append(value)
            param_idx += 1

        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        query = f"""
            SELECT COUNT(*) FROM {self._fqtn}
            WHERE {where_clause}
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)

        return int(row[0]) if row else 0

    async def search_hybrid(
        self,
        embedding: list[float],
        query_text: str,
        namespace_filter: dict[str, Any],
        top_k: int = 5,
        semantic_weight: float = 0.6,
        text_weight: float = 0.4,
        score_threshold: float = 0.1,
    ) -> list[EpisodeSearchResult]:
        """Search episodes using tsvector full-text + cosine vector fusion.

        Combines PostgreSQL ``ts_rank`` (BM25-like full-text scoring) with
        pgvector cosine distance for hybrid retrieval. Scores are fused as::

            hybrid_score = semantic_weight * semantic_score
                         + text_weight * ts_rank_score

        Both terms are normalized: semantic score is ``1 - cosine_distance``
        (clipped to [0, 1]), ts_rank is an unbounded float that PostgreSQL
        returns (typically [0, 1] for most queries).

        Args:
            embedding: Query embedding vector.
            query_text: Raw query text for full-text search (plainto_tsquery).
            namespace_filter: Dict of field_name -> value for WHERE filtering.
            top_k: Maximum results to return.
            semantic_weight: Weight for cosine similarity component. Default 0.6.
            text_weight: Weight for ts_rank component. Default 0.4.
            score_threshold: Minimum hybrid score to include. Default 0.1.

        Returns:
            List of episodes ranked by hybrid score (highest first).
        """
        pool = self._ensure_pool()

        conditions = []
        params: list[Any] = [
            str(embedding),   # $1 = embedding vector
            query_text,       # $2 = query text for tsquery
        ]
        param_idx = 3

        for field, value in namespace_filter.items():
            conditions.append(f"{field} = ${param_idx}")
            params.append(value)
            param_idx += 1

        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        query = f"""
            SELECT {_COLUMNS},
                   ({semantic_weight} * GREATEST(0.0, 1.0 - (embedding <=> $1::vector))
                    + {text_weight} * ts_rank(
                        searchable_text,
                        plainto_tsquery('english', $2)
                    )
                   ) AS hybrid_score
            FROM {self._fqtn}
            WHERE {where_clause}
              AND embedding IS NOT NULL
              AND (
                  searchable_text @@ plainto_tsquery('english', $2)
                  OR embedding IS NOT NULL
              )
            ORDER BY hybrid_score DESC
            LIMIT ${param_idx}
        """
        params.append(top_k)

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        results = []
        for row in rows:
            score = float(row["hybrid_score"])
            if score >= score_threshold:
                ep = _row_to_episode(row)
                results.append(
                    EpisodeSearchResult(
                        **ep.model_dump(),
                        embedding=ep.embedding,
                        score=min(score, 1.0),
                    )
                )
        return results
