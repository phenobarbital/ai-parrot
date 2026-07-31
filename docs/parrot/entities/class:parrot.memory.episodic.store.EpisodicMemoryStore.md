---
type: Wiki Entity
title: EpisodicMemoryStore
id: class:parrot.memory.episodic.store.EpisodicMemoryStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Main orchestrator for episodic memory operations.
---

# EpisodicMemoryStore

Defined in [`parrot.memory.episodic.store`](../summaries/mod:parrot.memory.episodic.store.md).

```python
class EpisodicMemoryStore
```

Main orchestrator for episodic memory operations.

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

## Methods

- `async def record_episode(self, namespace: MemoryNamespace, situation: str, action_taken: str, outcome: EpisodeOutcome, outcome_details: str | None=None, error_type: str | None=None, error_message: str | None=None, category: EpisodeCategory=EpisodeCategory.TOOL_EXECUTION, importance: int | None=None, related_tools: list[str] | None=None, related_entities: list[str] | None=None, metadata: dict[str, Any] | None=None, generate_reflection: bool=True, ttl_days: int | None=None) -> EpisodicMemory` — Record a new episode with auto-enrichment.
- `async def record_tool_episode(self, namespace: MemoryNamespace, tool_name: str, tool_args: dict[str, Any], tool_result: Any, user_query: str | None=None) -> EpisodicMemory` — Record an episode from a tool execution.
- `async def record_crew_episode(self, namespace: MemoryNamespace, crew_result: Any, flow_description: str, per_agent: bool=True) -> list[EpisodicMemory]` — Record episodes from a crew execution.
- `async def recall_similar(self, query: str, namespace: MemoryNamespace, top_k: int=5, score_threshold: float=0.3, category: EpisodeCategory | None=None, include_failures_only: bool=False) -> list[EpisodeSearchResult]` — Recall episodes similar to a query.
- `async def get_failure_warnings(self, namespace: MemoryNamespace, current_query: str | None=None, max_warnings: int=5) -> str` — Generate injectable warning text from past failures.
- `async def get_user_preferences(self, namespace: MemoryNamespace, limit: int=10) -> list[EpisodicMemory]` — Get user preference episodes.
- `async def get_room_context(self, namespace: MemoryNamespace, limit: int=10, categories: list[EpisodeCategory] | None=None) -> list[EpisodicMemory]` — Get recent episodes for a room.
- `async def cleanup_expired(self) -> int` — Delete expired episodes from the backend.
- `async def compact_namespace(self, namespace: MemoryNamespace, keep_top_n: int=100, keep_all_failures: bool=True) -> int` — Compact a namespace by keeping only the most important episodes.
- `async def export_episodes(self, namespace: MemoryNamespace, limit: int=1000) -> str` — Export episodes as JSONL string.
- `async def create_pgvector(cls, dsn: str, schema: str='parrot_memory', table: str='episodic_memory', embedding_provider: EpisodeEmbeddingProvider | None=None, reflection_engine: ReflectionEngine | None=None, redis_cache: EpisodeRedisCache | None=None, recall_strategy: RecallStrategy | None=None, importance_scorer: ImportanceScorer | None=None, **kwargs: Any) -> 'EpisodicMemoryStore'` — Create a store with PgVector backend.
- `async def create_redis_vector(cls, redis_url: str, index_name: str='idx:episodes', embedding_dim: int=384, namespace: MemoryNamespace | None=None, embedding_provider: EpisodeEmbeddingProvider | None=None, reflection_engine: ReflectionEngine | None=None, redis_cache: EpisodeRedisCache | None=None, recall_strategy: RecallStrategy | None=None, importance_scorer: ImportanceScorer | None=None, **kwargs: Any) -> 'EpisodicMemoryStore'` — Create a store with RedisVectorBackend.
- `async def create_faiss(cls, persistence_path: str | None=None, dimension: int=384, max_episodes: int=10000, embedding_provider: EpisodeEmbeddingProvider | None=None, reflection_engine: ReflectionEngine | None=None, redis_cache: EpisodeRedisCache | None=None, **kwargs: Any) -> 'EpisodicMemoryStore'` — Create a store with FAISS backend.
