"""EpisodicMemoryStore — main orchestrator for episodic memory.

Coordinates backend storage, embedding, reflection, and caching to provide
a unified API for recording, recalling, and maintaining agent episodes.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .backends.abstract import AbstractEpisodeBackend
from .cache import EpisodeRedisCache
from .embedding import EpisodeEmbeddingProvider
from .models import (
    EpisodeCategory,
    EpisodeOutcome,
    EpisodeSearchResult,
    EpisodicMemory,
    MemoryNamespace,
)
from .recall import RecallStrategy
from .reflection import ReflectionEngine
from .scoring import ImportanceScorer

logger = logging.getLogger(__name__)

# Known error types that boost importance
_KNOWN_ERROR_TYPES = {
    "timeout",
    "rate_limit",
    "permission",
    "connection",
    "validation",
}


def _auto_importance(
    outcome: EpisodeOutcome,
    error_type: str | None = None,
) -> int:
    """Compute default importance score based on outcome and error type."""
    if outcome in (EpisodeOutcome.FAILURE, EpisodeOutcome.TIMEOUT):
        base = 7
    elif outcome == EpisodeOutcome.PARTIAL:
        base = 5
    else:
        base = 3

    if error_type and error_type.lower() in _KNOWN_ERROR_TYPES:
        base = min(base + 2, 10)

    return base


class EpisodicMemoryStore:
    """Main orchestrator for episodic memory operations.

    Coordinates a backend (PgVector, FAISS, or RedisVector), an optional
    embedding provider (sentence-transformers), an optional reflection engine
    (LLM + heuristic), and an optional Redis cache for fast recent/failure
    lookups.

    Pluggable strategies:
    - ``importance_scorer``: When provided, used to compute episode importance
      in ``record_episode()`` instead of the inline heuristic. Must satisfy
      the ``ImportanceScorer`` protocol.
    - ``recall_strategy``: When provided, used in ``recall_similar()`` instead
      of calling ``backend.search_similar()`` directly. Must satisfy the
      ``RecallStrategy`` protocol.

    When neither is provided, behavior is identical to the pre-FEAT-075
    implementation (no breaking changes).

    Args:
        backend: Storage backend (PgVector, FAISS, or RedisVector).
        embedding_provider: Optional embedding provider for semantic search.
        reflection_engine: Optional reflection engine for lesson extraction.
        redis_cache: Optional Redis cache for hot episodes.
        default_ttl_days: Default time-to-live for episodes (0 = no expiry).
        importance_scorer: Optional pluggable importance scorer.
        recall_strategy: Optional pluggable recall strategy.
    """

    def __init__(
        self,
        backend: AbstractEpisodeBackend,
        embedding_provider: EpisodeEmbeddingProvider | None = None,
        reflection_engine: ReflectionEngine | None = None,
        redis_cache: EpisodeRedisCache | None = None,
        default_ttl_days: int = 90,
        importance_scorer: ImportanceScorer | None = None,
        recall_strategy: RecallStrategy | None = None,
    ) -> None:
        self._backend = backend
        self._embedding = embedding_provider
        self._reflection = reflection_engine
        self._cache = redis_cache
        self._default_ttl_days = default_ttl_days
        self._importance_scorer = importance_scorer
        self._recall_strategy = recall_strategy

    # ── Recording API ──

    async def record_episode(
        self,
        namespace: MemoryNamespace,
        situation: str,
        action_taken: str,
        outcome: EpisodeOutcome,
        outcome_details: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        category: EpisodeCategory = EpisodeCategory.TOOL_EXECUTION,
        importance: int | None = None,
        related_tools: list[str] | None = None,
        related_entities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        generate_reflection: bool = True,
        ttl_days: int | None = None,
    ) -> EpisodicMemory:
        """Record a new episode with auto-enrichment.

        Auto-computes importance, generates reflection (if engine available),
        embeds text for similarity search, stores in backend, and caches.

        Args:
            namespace: Scoping dimensions for this episode.
            situation: What the agent was trying to do.
            action_taken: What action was executed.
            outcome: The result classification.
            outcome_details: Additional outcome description.
            error_type: Error category if applicable.
            error_message: Detailed error message.
            category: Episode classification.
            importance: Override auto-computed importance (1-10).
            related_tools: Tools involved in this episode.
            related_entities: Entities referenced.
            metadata: Additional key-value metadata.
            generate_reflection: Whether to generate reflection via engine.
            ttl_days: Override default TTL. 0 = no expiry.

        Returns:
            The stored EpisodicMemory with all enrichments.
        """
        # Auto-compute importance (deferred until after episode is built if scorer)
        if importance is None and self._importance_scorer is None:
            importance = _auto_importance(outcome, error_type)
        elif importance is None:
            # Use inline heuristic as default; scorer overrides after build
            importance = _auto_importance(outcome, error_type)

        is_failure = outcome in (EpisodeOutcome.FAILURE, EpisodeOutcome.TIMEOUT)

        # Compute TTL
        effective_ttl = ttl_days if ttl_days is not None else self._default_ttl_days
        expires_at = None
        if effective_ttl > 0:
            expires_at = datetime.now(timezone.utc) + timedelta(days=effective_ttl)

        # Generate reflection
        reflection = None
        lesson_learned = None
        suggested_action = None
        if generate_reflection and self._reflection is not None:
            try:
                result = await self._reflection.reflect(
                    situation, action_taken, outcome, error_message
                )
                reflection = result.reflection
                lesson_learned = result.lesson_learned
                suggested_action = result.suggested_action
            except Exception as e:
                logger.warning("Reflection generation failed: %s", e)

        # Build episode
        episode = EpisodicMemory(
            tenant_id=namespace.tenant_id,
            agent_id=namespace.agent_id,
            user_id=namespace.user_id,
            session_id=namespace.session_id,
            room_id=namespace.room_id,
            crew_id=namespace.crew_id,
            situation=situation,
            action_taken=action_taken,
            outcome=outcome,
            outcome_details=outcome_details,
            error_type=error_type,
            error_message=error_message,
            reflection=reflection,
            lesson_learned=lesson_learned,
            suggested_action=suggested_action,
            category=category,
            importance=importance,
            is_failure=is_failure,
            related_tools=related_tools or [],
            related_entities=related_entities or [],
            expires_at=expires_at,
            metadata=metadata or {},
        )

        # Apply importance scorer if provided (overrides inline heuristic)
        if self._importance_scorer is not None:
            try:
                raw_score = self._importance_scorer.score(episode)
                # Normalize [0.0, 1.0] → [1, 10] integer scale
                episode.importance = max(1, min(10, round(raw_score * 10)))
            except Exception as e:
                logger.warning("ImportanceScorer.score() failed: %s", e)

        # Generate embedding
        if self._embedding is not None:
            try:
                text = EpisodeEmbeddingProvider.get_searchable_text(episode)
                episode.embedding = await self._embedding.embed(text)
            except Exception as e:
                logger.warning("Embedding generation failed: %s", e)

        # Store in backend
        await self._backend.store(episode)

        # Cache in Redis
        if self._cache is not None:
            await self._cache.cache_episode(namespace, episode)

        logger.debug(
            "Recorded episode %s: %s → %s",
            episode.episode_id,
            category.value,
            outcome.value,
        )
        return episode

    async def record_tool_episode(
        self,
        namespace: MemoryNamespace,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: Any,
        user_query: str | None = None,
    ) -> EpisodicMemory:
        """Record an episode from a tool execution.

        Extracts episode fields from a ToolResult and delegates to
        record_episode().

        Args:
            namespace: Scoping dimensions.
            tool_name: Name of the tool that was called.
            tool_args: Arguments passed to the tool.
            tool_result: The ToolResult from the tool execution.
            user_query: The original user query that triggered the tool.

        Returns:
            The stored episode.
        """
        # Build situation
        situation = user_query or f"Tool execution: {tool_name}"

        # Summarize args (truncate long values)
        summarized = {
            k: str(v)[:100] for k, v in (tool_args or {}).items()
        }
        action_taken = f"Called {tool_name}({json.dumps(summarized)})"

        # Map outcome
        success = getattr(tool_result, "success", True)
        error = getattr(tool_result, "error", None)
        status = getattr(tool_result, "status", "success")

        if not success:
            outcome = EpisodeOutcome.FAILURE
        elif status == "timeout":
            outcome = EpisodeOutcome.TIMEOUT
        elif status == "partial":
            outcome = EpisodeOutcome.PARTIAL
        else:
            outcome = EpisodeOutcome.SUCCESS

        # Extract error details
        error_type = None
        error_message = None
        if error:
            error_message = str(error)[:500]
            # Try to classify error type
            error_lower = error_message.lower()
            for etype in _KNOWN_ERROR_TYPES:
                if etype in error_lower:
                    error_type = etype
                    break

        outcome_details = None
        result_val = getattr(tool_result, "result", None)
        if result_val is not None:
            outcome_details = str(result_val)[:200]

        return await self.record_episode(
            namespace=namespace,
            situation=situation,
            action_taken=action_taken,
            outcome=outcome,
            outcome_details=outcome_details,
            error_type=error_type,
            error_message=error_message,
            category=EpisodeCategory.TOOL_EXECUTION,
            related_tools=[tool_name],
        )

    async def record_crew_episode(
        self,
        namespace: MemoryNamespace,
        crew_result: Any,
        flow_description: str,
        per_agent: bool = True,
    ) -> list[EpisodicMemory]:
        """Record episodes from a crew execution.

        Creates a crew-level episode and optionally per-agent episodes.

        Args:
            namespace: Scoping dimensions (should include crew_id).
            crew_result: The result from AgentCrew execution.
            flow_description: Description of the workflow.
            per_agent: If True, create one episode per participating agent.

        Returns:
            List of all created episodes.
        """
        episodes = []

        # Crew-level episode
        success = getattr(crew_result, "success", True)
        outcome = EpisodeOutcome.SUCCESS if success else EpisodeOutcome.FAILURE
        error = getattr(crew_result, "error", None)

        crew_ep = await self.record_episode(
            namespace=namespace,
            situation=f"Crew execution: {flow_description}",
            action_taken=f"Ran crew workflow with agents",
            outcome=outcome,
            error_message=str(error)[:500] if error else None,
            category=EpisodeCategory.WORKFLOW_PATTERN,
            importance=6,
        )
        episodes.append(crew_ep)

        # Per-agent episodes
        if per_agent:
            agent_results = getattr(crew_result, "agent_results", None) or {}
            for agent_id, agent_result in agent_results.items():
                agent_success = getattr(agent_result, "success", True)
                agent_outcome = (
                    EpisodeOutcome.SUCCESS if agent_success else EpisodeOutcome.FAILURE
                )
                agent_ns = MemoryNamespace(
                    tenant_id=namespace.tenant_id,
                    agent_id=agent_id,
                    crew_id=namespace.crew_id,
                )
                agent_error = getattr(agent_result, "error", None)
                agent_ep = await self.record_episode(
                    namespace=agent_ns,
                    situation=f"Agent participation in crew: {flow_description}",
                    action_taken=f"Executed assigned task in crew workflow",
                    outcome=agent_outcome,
                    error_message=str(agent_error)[:500] if agent_error else None,
                    category=EpisodeCategory.WORKFLOW_PATTERN,
                    importance=5,
                )
                episodes.append(agent_ep)

        return episodes

    # ── Recall API ──

    async def recall_similar(
        self,
        query: str,
        namespace: MemoryNamespace,
        top_k: int = 5,
        score_threshold: float = 0.3,
        category: EpisodeCategory | None = None,
        include_failures_only: bool = False,
    ) -> list[EpisodeSearchResult]:
        """Recall episodes similar to a query.

        Embeds the query and performs vector similarity search with
        namespace filtering.

        Args:
            query: Natural language query to search for.
            namespace: Scoping dimensions for filtering.
            top_k: Maximum results.
            score_threshold: Minimum similarity score (0-1).
            category: Optional category filter (applied post-search).
            include_failures_only: If True, only return failure episodes.

        Returns:
            List of episodes ranked by similarity score.
        """
        if self._embedding is None:
            logger.warning("No embedding provider; recall_similar unavailable")
            return []

        embedding = await self._embedding.embed(query)
        ns_filter = namespace.build_filter()
        effective_top_k = top_k * 2 if category else top_k  # over-fetch for post-filter

        if self._recall_strategy is not None:
            # Use pluggable recall strategy
            results = await self._recall_strategy.search(
                query=query,
                query_embedding=embedding,
                backend=self._backend,
                namespace_filter=ns_filter,
                top_k=effective_top_k,
                score_threshold=score_threshold,
                include_failures_only=include_failures_only,
            )
        else:
            # Default: direct backend call (unchanged behavior)
            results = await self._backend.search_similar(
                embedding=embedding,
                namespace_filter=ns_filter,
                top_k=effective_top_k,
                score_threshold=score_threshold,
                include_failures_only=include_failures_only,
            )

        if category is not None:
            results = [r for r in results if r.category == category]

        return results[:top_k]

    async def get_failure_warnings(
        self,
        namespace: MemoryNamespace,
        current_query: str | None = None,
        max_warnings: int = 5,
    ) -> str:
        """Generate injectable warning text from past failures.

        Combines semantically similar failures (if query provided)
        with recent failures, deduplicates, and formats as text
        suitable for system prompt injection.

        Args:
            namespace: Scoping dimensions.
            current_query: Current user query for semantic matching.
            max_warnings: Maximum number of warnings.

        Returns:
            Formatted warning text (empty string if no failures found).
        """
        failures: dict[str, EpisodicMemory] = {}

        # Semantic search for similar failures
        if current_query and self._embedding is not None:
            try:
                similar = await self.recall_similar(
                    query=current_query,
                    namespace=namespace,
                    top_k=max_warnings,
                    include_failures_only=True,
                )
                for ep in similar:
                    failures[ep.episode_id] = ep
            except Exception as e:
                logger.warning("Failure recall failed: %s", e)

        # Recent failures from backend
        try:
            recent_failures = await self._backend.get_failures(
                agent_id=namespace.agent_id,
                tenant_id=namespace.tenant_id,
                limit=max_warnings,
            )
            for ep in recent_failures:
                if ep.episode_id not in failures:
                    failures[ep.episode_id] = ep
        except Exception as e:
            logger.warning("get_failures failed: %s", e)

        if not failures:
            return ""

        # Sort by importance DESC, then recency
        sorted_failures = sorted(
            failures.values(),
            key=lambda ep: (ep.importance, ep.created_at.timestamp()),
            reverse=True,
        )[:max_warnings]

        # Format warnings
        lines_mistakes = []
        lines_success = []

        for ep in sorted_failures:
            tool_info = f" (tool: {', '.join(ep.related_tools)})" if ep.related_tools else ""
            if ep.lesson_learned:
                lines_mistakes.append(
                    f"- {ep.situation[:100]}{tool_info} — {ep.lesson_learned}"
                )
            elif ep.error_message:
                lines_mistakes.append(
                    f"- {ep.situation[:100]}{tool_info} — {ep.error_message[:100]}"
                )
            if ep.suggested_action:
                lines_success.append(f"- {ep.suggested_action}")

        parts = []
        if lines_mistakes:
            parts.append("MISTAKES TO AVOID:")
            parts.extend(lines_mistakes)
        if lines_success:
            parts.append("SUGGESTED APPROACHES:")
            parts.extend(lines_success)

        return "\n".join(parts)

    async def get_user_preferences(
        self,
        namespace: MemoryNamespace,
        limit: int = 10,
    ) -> list[EpisodicMemory]:
        """Get user preference episodes.

        Args:
            namespace: Must include user_id for meaningful results.
            limit: Maximum preferences to return.

        Returns:
            List of USER_PREFERENCE category episodes.
        """
        ns_filter = namespace.build_filter()
        ns_filter["category"] = EpisodeCategory.USER_PREFERENCE.value

        return await self._backend.get_recent(
            namespace_filter=ns_filter,
            limit=limit,
        )

    async def get_room_context(
        self,
        namespace: MemoryNamespace,
        limit: int = 10,
        categories: list[EpisodeCategory] | None = None,
    ) -> list[EpisodicMemory]:
        """Get recent episodes for a room.

        Args:
            namespace: Must include room_id for room scoping.
            limit: Maximum episodes to return.
            categories: Optional category filter (applied post-retrieval).

        Returns:
            List of recent room-scoped episodes.
        """
        ns_filter = namespace.build_filter()

        episodes = await self._backend.get_recent(
            namespace_filter=ns_filter,
            limit=limit * 2 if categories else limit,
        )

        if categories:
            cat_values = {c.value for c in categories}
            episodes = [
                ep for ep in episodes if ep.category.value in cat_values
            ]

        return episodes[:limit]

    # ── Maintenance API ──

    async def cleanup_expired(self) -> int:
        """Delete expired episodes from the backend.

        Returns:
            Number of episodes deleted.
        """
        count = await self._backend.delete_expired()
        if count > 0:
            logger.info("Cleaned up %d expired episodes", count)
        return count

    async def compact_namespace(
        self,
        namespace: MemoryNamespace,
        keep_top_n: int = 100,
        keep_all_failures: bool = True,
    ) -> int:
        """Compact a namespace by keeping only the most important episodes.

        Retains the top-N episodes by importance score, plus all failure
        episodes if keep_all_failures is True. Deletes the rest.

        Args:
            namespace: The namespace to compact.
            keep_top_n: Number of top episodes to retain.
            keep_all_failures: If True, retain all failure episodes.

        Returns:
            Number of episodes deleted.
        """
        ns_filter = namespace.build_filter()

        # Get all episodes in namespace
        total = await self._backend.count(ns_filter)
        if total <= keep_top_n:
            return 0

        # Get all episodes sorted by importance
        all_episodes = await self._backend.get_recent(
            namespace_filter=ns_filter,
            limit=total,
        )

        # Sort by importance DESC
        all_episodes.sort(key=lambda ep: ep.importance, reverse=True)

        # Determine which to keep
        keep_ids = set()
        for ep in all_episodes[:keep_top_n]:
            keep_ids.add(ep.episode_id)

        if keep_all_failures:
            for ep in all_episodes:
                if ep.is_failure:
                    keep_ids.add(ep.episode_id)

        # Delete the rest (not directly supported by backend protocol,
        # so we rebuild by deleting individually if the backend supports it,
        # or log a warning)
        deleted = 0
        for ep in all_episodes:
            if ep.episode_id not in keep_ids:
                # Mark as expired for next cleanup
                ep.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                deleted += 1

        # Trigger cleanup to remove the newly-expired episodes
        if deleted > 0:
            actual = await self._backend.delete_expired()
            logger.info(
                "Compacted namespace %s: marked %d for deletion, cleaned %d",
                namespace.scope_label,
                deleted,
                actual,
            )

        # Invalidate cache for this namespace
        if self._cache is not None:
            await self._cache.invalidate(namespace)

        return deleted

    async def export_episodes(
        self,
        namespace: MemoryNamespace,
        limit: int = 1000,
    ) -> str:
        """Export episodes as JSONL string.

        Args:
            namespace: The namespace to export.
            limit: Maximum episodes to export.

        Returns:
            JSONL-formatted string of episodes.
        """
        ns_filter = namespace.build_filter()
        episodes = await self._backend.get_recent(
            namespace_filter=ns_filter,
            limit=limit,
        )

        lines = [json.dumps(ep.to_dict()) for ep in episodes]
        return "\n".join(lines)

    # ── Factory Methods ──

    @classmethod
    async def create_pgvector(
        cls,
        dsn: str,
        schema: str = "parrot_memory",
        table: str = "episodic_memory",
        embedding_provider: EpisodeEmbeddingProvider | None = None,
        reflection_engine: ReflectionEngine | None = None,
        redis_cache: EpisodeRedisCache | None = None,
        recall_strategy: RecallStrategy | None = None,
        importance_scorer: ImportanceScorer | None = None,
        **kwargs: Any,
    ) -> "EpisodicMemoryStore":
        """Create a store with PgVector backend.

        Args:
            dsn: PostgreSQL connection string.
            schema: PostgreSQL schema name.
            table: Table name.
            embedding_provider: Optional embedding provider.
            reflection_engine: Optional reflection engine.
            redis_cache: Optional Redis cache.
            recall_strategy: Optional recall strategy.
            importance_scorer: Optional importance scorer.
            **kwargs: Additional kwargs for EpisodicMemoryStore.

        Returns:
            Configured EpisodicMemoryStore with PgVector backend.
        """
        from .backends.pgvector import PgVectorBackend

        backend = PgVectorBackend(dsn=dsn, schema=schema, table=table)
        await backend.configure()

        return cls(
            backend=backend,
            embedding_provider=embedding_provider,
            reflection_engine=reflection_engine,
            redis_cache=redis_cache,
            recall_strategy=recall_strategy,
            importance_scorer=importance_scorer,
            **kwargs,
        )

    @classmethod
    async def create_redis_vector(
        cls,
        redis_url: str,
        index_name: str = "idx:episodes",
        embedding_dim: int = 384,
        namespace: MemoryNamespace | None = None,
        embedding_provider: EpisodeEmbeddingProvider | None = None,
        reflection_engine: ReflectionEngine | None = None,
        redis_cache: EpisodeRedisCache | None = None,
        recall_strategy: RecallStrategy | None = None,
        importance_scorer: ImportanceScorer | None = None,
        **kwargs: Any,
    ) -> "EpisodicMemoryStore":
        """Create a store with RedisVectorBackend.

        Requires Redis Stack with RediSearch module enabled.

        Args:
            redis_url: Redis connection URL (e.g., ``redis://localhost:6379``).
            index_name: RediSearch index name.
            embedding_dim: Dimension of embedding vectors.
            namespace: Optional namespace for default scoping.
            embedding_provider: Optional embedding provider.
            reflection_engine: Optional reflection engine.
            redis_cache: Optional Redis cache (separate from vector backend).
            recall_strategy: Optional recall strategy.
            importance_scorer: Optional importance scorer.
            **kwargs: Additional kwargs for EpisodicMemoryStore.

        Returns:
            Configured EpisodicMemoryStore with RedisVectorBackend.
        """
        from .backends.redis_vector import RedisVectorBackend

        backend = RedisVectorBackend(
            redis_url=redis_url,
            index_name=index_name,
            embedding_dim=embedding_dim,
        )
        await backend.configure()

        return cls(
            backend=backend,
            embedding_provider=embedding_provider,
            reflection_engine=reflection_engine,
            redis_cache=redis_cache,
            recall_strategy=recall_strategy,
            importance_scorer=importance_scorer,
            **kwargs,
        )

    @classmethod
    async def create_faiss(
        cls,
        persistence_path: str | None = None,
        dimension: int = 384,
        max_episodes: int = 10000,
        embedding_provider: EpisodeEmbeddingProvider | None = None,
        reflection_engine: ReflectionEngine | None = None,
        redis_cache: EpisodeRedisCache | None = None,
        **kwargs: Any,
    ) -> "EpisodicMemoryStore":
        """Create a store with FAISS backend.

        Args:
            persistence_path: Directory for disk persistence (None = in-memory only).
            dimension: Embedding vector dimension.
            max_episodes: Maximum episodes in the FAISS index.
            embedding_provider: Optional embedding provider.
            reflection_engine: Optional reflection engine.
            redis_cache: Optional Redis cache.
            **kwargs: Additional kwargs for EpisodicMemoryStore.

        Returns:
            Configured EpisodicMemoryStore with FAISS backend.
        """
        from .backends.faiss import FAISSBackend

        backend = FAISSBackend(
            dimension=dimension,
            persistence_path=persistence_path,
            max_episodes=max_episodes,
        )
        await backend.configure()

        return cls(
            backend=backend,
            embedding_provider=embedding_provider,
            reflection_engine=reflection_engine,
            redis_cache=redis_cache,
            **kwargs,
        )
