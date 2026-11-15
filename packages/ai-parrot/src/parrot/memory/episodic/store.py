"""EpisodicMemoryStore — main orchestrator for episodic memory.

Coordinates backend storage, embedding, reflection, and caching to provide
a unified API for recording, recalling, and maintaining agent episodes.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from parrot.memory.dynamics.grade import select_grade
from parrot.memory.dynamics.models import MemoryCitation, MemoryRef, ReviewCommand, ReviewReceipt, ReviewSignal

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
from .recall import HybridBM25Strategy, RecallStrategy, rank_episodes
from .reflection import ReflectionEngine
from .scoring import ImportanceScorer

logger = logging.getLogger(__name__)

_EXPLICIT_LESSON_KEY = "_parrot_explicit_lesson"
_EXPLICIT_REFLECTION_KEY = "_parrot_explicit_reflection"

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
        self._citations: dict[str, MemoryCitation] = {}
        self._review_revisions: dict[str, int] = {}
        self._review_expected_revisions: dict[str, int] = {}

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

        episode_metadata = dict(metadata or {})
        explicit_lesson = episode_metadata.pop(_EXPLICIT_LESSON_KEY, None)
        explicit_reflection = episode_metadata.pop(_EXPLICIT_REFLECTION_KEY, None)

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

        if explicit_lesson is not None:
            lesson_learned = str(explicit_lesson)
        if explicit_reflection is not None:
            reflection = str(explicit_reflection)

        # Build episode
        episode = EpisodicMemory(
            tenant_id=namespace.tenant_id,
            agent_id=namespace.agent_id,
            model_id=namespace.model_id,
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
            metadata=episode_metadata,
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
        self._invalidate_recall_index(namespace)

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

    def _invalidate_recall_index(self, namespace: MemoryNamespace) -> None:
        """Discard the hybrid lexical index after a committed scope mutation."""
        if isinstance(self._recall_strategy, HybridBM25Strategy):
            self._recall_strategy.invalidate(namespace.build_filter())

    async def _invalidate_scope_cache(self, namespace: MemoryNamespace) -> None:
        """Invalidate derived recall state after a committed review mutation."""
        self._invalidate_recall_index(namespace)
        if self._cache is not None:
            await self._cache.invalidate(namespace)

    async def _get_scoped_recent(
        self,
        namespace: MemoryNamespace,
        *,
        limit: int,
    ) -> list[EpisodicMemory]:
        """Read recent episodes from the full-scope cache or backend."""
        if self._cache is not None:
            cached = await self._cache.get_recent(namespace, limit=limit)
            if cached is not None:
                return cached
        return await self._backend.get_recent(namespace.build_filter(), limit=limit)

    async def _fallback_lexical_search(
        self,
        query: str,
        namespace: MemoryNamespace,
        *,
        top_k: int,
        score_threshold: float,
        include_failures_only: bool,
    ) -> list[EpisodeSearchResult]:
        """Provide bounded local recall when no embedding provider is configured."""
        terms = tuple(term for term in query.casefold().split() if term)
        if not terms or top_k == 0:
            return []
        namespace_filter = namespace.build_filter()
        count = await self._backend.count(namespace_filter)
        episodes = await self._backend.get_recent(namespace_filter, limit=count)
        matches: list[EpisodeSearchResult] = []
        for episode in episodes:
            if include_failures_only and not episode.is_failure:
                continue
            searchable = episode.searchable_text().casefold()
            score = sum(term in searchable for term in terms) / len(terms)
            if score >= score_threshold:
                matches.append(EpisodeSearchResult(**episode.model_dump(), embedding=episode.embedding, score=score))
        return matches[:top_k]

    async def cite(
        self,
        memory_ids: list[str],
        *,
        namespace: MemoryNamespace,
        exposure_id: str,
    ) -> MemoryCitation:
        """Bind in-scope episode versions to one delivered runtime exposure.

        Citation is intentionally bookkeeping-only: it does not call the
        review backend and therefore cannot change earned dynamics state.

        Args:
            memory_ids: Episode identifiers cited from the delivered context.
            namespace: Trusted runtime namespace for the delivery.
            exposure_id: Runtime-minted final-delivery identifier.

        Returns:
            The validated citation for the requested episode versions.

        Raises:
            ValueError: If the exposure, cardinality, or any reference is unavailable.
        """
        if not exposure_id.strip():
            raise ValueError("exposure_id must be non-blank")
        unique_ids = list(dict.fromkeys(memory_ids))
        if not unique_ids or len(unique_ids) > 64:
            raise ValueError("citation must contain between 1 and 64 memory references")

        episodes = await self._resolve_episodes(unique_ids, namespace=namespace)
        refs = tuple(self._episode_ref(episodes[memory_id], namespace=namespace) for memory_id in unique_ids)
        citation = MemoryCitation(exposure_id=exposure_id, refs=refs)

        previous = self._citations.get(exposure_id)
        if previous is not None:
            previous_namespace = previous.refs[0].namespace
            if previous_namespace != namespace:
                raise ValueError("one or more memory references are unavailable")
            combined = list(previous.refs)
            known = {ref.canonical_key for ref in combined}
            combined.extend(ref for ref in refs if ref.canonical_key not in known)
            if len(combined) > 64:
                raise ValueError("citation must contain at most 64 memory references")
            self._citations[exposure_id] = MemoryCitation(exposure_id=exposure_id, refs=tuple(combined))
        else:
            self._citations[exposure_id] = citation
        return citation

    async def review(
        self,
        memory_ids: list[str],
        signal: ReviewSignal,
        *,
        namespace: MemoryNamespace,
        exposure_id: str,
    ) -> list[ReviewReceipt]:
        """Admit cited evidence and apply each review durably at most once.

        Args:
            memory_ids: Episode identifiers attributed to the verified outcome.
            signal: Trusted runtime or coder outcome evidence.
            namespace: Trusted runtime namespace for the reviewed episodes.
            exposure_id: Final-delivery exposure previously bound by :meth:`cite`.

        Returns:
            One durable or explicitly ignored receipt per distinct episode.

        Raises:
            ValueError: If scope, exposure, or delivered-version admission fails.
        """
        unique_ids = list(dict.fromkeys(memory_ids))
        if not unique_ids:
            return []
        if not self._signal_matches_namespace(signal, namespace):
            raise ValueError("review scope or delivered exposure is unavailable")

        citation = self._citations.get(exposure_id)
        if citation is None or citation.exposure_id != exposure_id:
            raise ValueError("review scope or delivered exposure is unavailable")
        cited_refs = {ref.memory_id: ref for ref in citation.refs if ref.namespace == namespace}
        if any(memory_id not in cited_refs for memory_id in unique_ids):
            raise ValueError("review scope or delivered exposure is unavailable")
        if not signal.can_review:
            return []

        episodes = await self._resolve_episodes(unique_ids, namespace=namespace)
        apply_review = getattr(self._backend, "apply_review", None)
        if not callable(apply_review):
            return [
                self._unavailable_receipt(cited_refs[memory_id], signal, reason="backend has no review capability")
                for memory_id in unique_ids
            ]

        receipts: list[ReviewReceipt] = []
        state_changed = False
        for memory_id in unique_ids:
            ref = cited_refs[memory_id]
            episode = episodes[memory_id]
            grade = select_grade(
                signal,
                attribution="cited",
                memory_error_signature=episode.error_message or episode.error_type,
                verified_recovery=bool(signal.recovery_refs),
            )
            provisional = ReviewCommand(
                ref=ref,
                signal=signal,
                exposure_id=exposure_id,
                expected_revision=0,
            )
            if grade is None:
                receipts.append(
                    ReviewReceipt(
                        status="ignored",
                        dedupe_key=provisional.dedupe_key,
                        outcome_id=signal.outcome_id,
                        ref_key=ref.canonical_key,
                        reason="verified evidence selected no review grade",
                    )
                )
                continue

            expected_revision = self._review_expected_revisions.get(
                provisional.dedupe_key,
                self._review_revisions.get(ref.canonical_key, 0),
            )
            command = provisional.model_copy(update={"expected_revision": expected_revision})
            try:
                receipt, command = await self._apply_review_with_current_revision(apply_review, command)
            except Exception as exc:
                logger.warning("Review application failed for %s: %s", ref.canonical_key, exc)
                receipts.append(self._unavailable_receipt(ref, signal, reason="review storage is unavailable"))
                continue

            self._review_expected_revisions[command.dedupe_key] = command.expected_revision
            if receipt.apply_revision is not None:
                self._review_revisions[ref.canonical_key] = max(
                    receipt.apply_revision,
                    self._review_revisions.get(ref.canonical_key, 0),
                )
            if receipt.status == "applied":
                state_changed = True
            receipts.append(receipt)
        if state_changed:
            await self._invalidate_scope_cache(namespace)
        return receipts

    async def _apply_review_with_current_revision(
        self,
        apply_review: Any,
        command: ReviewCommand,
    ) -> tuple[ReviewReceipt, ReviewCommand]:
        """Retry only a compare-and-swap miss using the backend's committed revision."""
        current_command = command
        for _ in range(3):
            receipt = await apply_review(current_command)
            expected_miss = (
                receipt.status == "stale_revision"
                and receipt.apply_revision is not None
                and receipt.reason is not None
                and receipt.reason.startswith("expected apply_revision=")
            )
            if not expected_miss:
                return receipt, current_command
            current_command = current_command.model_copy(update={"expected_revision": receipt.apply_revision})
        return receipt, current_command

    async def _resolve_episodes(
        self,
        memory_ids: list[str],
        *,
        namespace: MemoryNamespace,
    ) -> dict[str, EpisodicMemory]:
        """Resolve exact-scope episodes without distinguishing missing from cross-scope IDs."""
        namespace_filter = namespace.build_filter()
        count = await self._backend.count(namespace_filter)
        episodes = await self._backend.get_recent(namespace_filter=namespace_filter, limit=max(1, count))
        resolved = {
            episode.episode_id: episode
            for episode in episodes
            if episode.episode_id in memory_ids and self._episode_matches_namespace(episode, namespace)
        }
        if any(memory_id not in resolved for memory_id in memory_ids):
            raise ValueError("one or more memory references are unavailable")
        return resolved

    @staticmethod
    def _episode_ref(episode: EpisodicMemory, *, namespace: MemoryNamespace) -> MemoryRef:
        """Create the immutable write-once version reference for one episode."""
        return MemoryRef(namespace=namespace, kind="episode", memory_id=episode.episode_id, content_version="v1")

    @staticmethod
    def _episode_matches_namespace(episode: EpisodicMemory, namespace: MemoryNamespace) -> bool:
        """Require every namespace dimension, including absent values, to match."""
        return (
            episode.tenant_id,
            episode.agent_id,
            episode.user_id,
            episode.session_id,
            episode.room_id,
            episode.crew_id,
            episode.model_id,
        ) == (
            namespace.tenant_id,
            namespace.agent_id,
            namespace.user_id,
            namespace.session_id,
            namespace.room_id,
            namespace.crew_id,
            namespace.model_id,
        )

    @staticmethod
    def _signal_matches_namespace(signal: ReviewSignal, namespace: MemoryNamespace) -> bool:
        """Compare the outcome's trusted scope with every episodic namespace dimension."""
        return (
            signal.scope.tenant_id,
            signal.scope.agent_id,
            signal.scope.user_id,
            signal.scope.session_id,
            signal.scope.room_id,
            signal.scope.crew_id,
            signal.scope.model_id,
        ) == (
            namespace.tenant_id,
            namespace.agent_id,
            namespace.user_id,
            namespace.session_id,
            namespace.room_id,
            namespace.crew_id,
            namespace.model_id,
        )

    @staticmethod
    def _unavailable_receipt(ref: MemoryRef, signal: ReviewSignal, *, reason: str) -> ReviewReceipt:
        """Return a failure receipt without claiming an applied or durable pending write."""
        command = ReviewCommand(ref=ref, signal=signal, exposure_id="unavailable", expected_revision=0)
        return ReviewReceipt(
            status="storage_unavailable",
            dedupe_key=command.dedupe_key,
            outcome_id=signal.outcome_id,
            ref_key=ref.canonical_key,
            reason=reason,
        )

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
            action_taken="Ran crew workflow with agents",
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
                    action_taken="Executed assigned task in crew workflow",
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
        ns_filter = namespace.build_filter()
        effective_top_k = top_k * 2 if category else top_k  # over-fetch for post-filter
        if self._embedding is None:
            logger.info("No embedding provider; using local lexical recall fallback")
            results = await self._fallback_lexical_search(
                query,
                namespace,
                top_k=effective_top_k,
                score_threshold=score_threshold,
                include_failures_only=include_failures_only,
            )
        else:
            embedding = await self._embedding.embed(query)
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

        ranked = rank_episodes(results, namespace=namespace)
        return [result for result in ranked if isinstance(result, EpisodeSearchResult)][:top_k]

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

        # Full-scope cached failures fall back to full-scope recent retrieval.
        try:
            recent_failures: list[EpisodicMemory] | None = None
            if self._cache is not None:
                recent_failures = await self._cache.get_failures(namespace, limit=max_warnings)
            if recent_failures is None:
                count = await self._backend.count(namespace.build_filter())
                recent_failures = await self._backend.get_recent(namespace.build_filter(), limit=count)
            for ep in recent_failures:
                if ep.is_failure and ep.episode_id not in failures:
                    failures[ep.episode_id] = ep
        except Exception as e:
            logger.warning("get_failures failed: %s", e)

        if not failures:
            return ""

        sorted_failures = rank_episodes(list(failures.values()), namespace=namespace)[:max_warnings]

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
        count = await self._backend.count(namespace.build_filter())
        episodes = await self._get_scoped_recent(namespace, limit=count)
        preferences = [episode for episode in episodes if episode.category == EpisodeCategory.USER_PREFERENCE]
        return rank_episodes(preferences, namespace=namespace)[:limit]

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
        count = await self._backend.count(namespace.build_filter())
        episodes = await self._get_scoped_recent(namespace, limit=count)

        if categories:
            cat_values = {c.value for c in categories}
            episodes = [
                ep for ep in episodes if ep.category.value in cat_values
            ]

        return rank_episodes(episodes, namespace=namespace)[:limit]

    # ── Maintenance API ──

    async def mark_consolidated(
        self,
        episode_ids: list[str],
        page_id: str,
    ) -> int:
        """Mark episodes as consolidated into a dream-cycle brain wiki page.

        Thin passthrough over ``backend.update_metadata()`` (FEAT-390).
        Never deletes episodes — existing TTL/compaction keeps pruning.
        Backends that do not implement ``update_metadata`` are tolerated
        (watermark-only mode): this returns 0 with a WARNING logged.

        Args:
            episode_ids: Episode ids to mark as consolidated.
            page_id: Brain wiki page id the episodes were distilled into.

        Returns:
            Number of episodes actually updated.
        """
        if not hasattr(self._backend, "update_metadata"):
            logger.warning(
                "Backend %s has no update_metadata(); mark_consolidated() "
                "is a no-op (watermark-only mode)",
                type(self._backend).__name__,
            )
            return 0

        return await self._backend.update_metadata(
            episode_ids, {"consolidated_into": page_id}
        )

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
