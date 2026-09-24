---
id: F022
query_id: Q022
type: read
intent: EpisodicMemoryStore.record_episode / recall_similar signatures; kind/type enum extensibility
executed_at: 2026-09-24T23:21:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F022 — record_episode takes closed EpisodeOutcome/EpisodeCategory enums plus free-form metadata

## Summary
The signature is `record_episode(namespace: MemoryNamespace, situation, action_taken, outcome: EpisodeOutcome, outcome_details=None, error_type=None, error_message=None, category: EpisodeCategory = TOOL_EXECUTION, importance=None, related_tools=None, related_entities=None, metadata=None, generate_reflection=True, ttl_days=None) -> EpisodicMemory`. There is no `kind` field. The episode type is `EpisodeCategory`, a `str, Enum` with 7 members, and the outcome is `EpisodeOutcome` with 4 members. Both are closed Python enums, but the pgvector column is plain `VARCHAR(32)`, so adding a member such as `PROCEDURE_STEP` needs no DB migration. `recall_similar(query, namespace, top_k=5, score_threshold=0.3, category=None, include_failures_only=False)` filters on namespace and, optionally, category.

## Citations
- path: `packages/ai-parrot/src/parrot/memory/episodic/store.py`
  lines: 106-122
  symbol: `EpisodicMemoryStore.record_episode`
  excerpt: |
    async def record_episode(self, namespace: MemoryNamespace, situation: str, action_taken: str,
        outcome: EpisodeOutcome, outcome_details: str | None = None, error_type: str | None = None,
        error_message: str | None = None, category: EpisodeCategory = EpisodeCategory.TOOL_EXECUTION,
        importance: int | None = None, related_tools: list[str] | None = None,
        related_entities: list[str] | None = None, metadata: dict[str, Any] | None = None,
        generate_reflection: bool = True, ttl_days: int | None = None) -> EpisodicMemory:
- path: `packages/ai-parrot/src/parrot/memory/episodic/store.py`
  lines: 146-153
  symbol: `record_episode` (importance/failure)
  excerpt: |
    if importance is None and self._importance_scorer is None:
        importance = _auto_importance(outcome, error_type)
    is_failure = outcome in (EpisodeOutcome.FAILURE, EpisodeOutcome.TIMEOUT)
- path: `packages/ai-parrot/src/parrot/memory/episodic/store.py`
  lines: 377-385
  symbol: `EpisodicMemoryStore.recall_similar`
  excerpt: |
    async def recall_similar(self, query: str, namespace: MemoryNamespace, top_k: int = 5,
        score_threshold: float = 0.3, category: EpisodeCategory | None = None,
        include_failures_only: bool = False) -> list[EpisodeSearchResult]:
- path: `packages/ai-parrot/src/parrot/memory/episodic/store.py`
  lines: 235-310
  symbol: `record_tool_episode`, `record_crew_episode`
  excerpt: |
    235: async def record_tool_episode(
    310: async def record_crew_episode(
- path: `packages/ai-parrot/src/parrot/memory/episodic/models.py`
  lines: 20-38
  symbol: `EpisodeOutcome`, `EpisodeCategory`
  excerpt: |
    class EpisodeOutcome(str, Enum):
        SUCCESS = "success"; FAILURE = "failure"; PARTIAL = "partial"; TIMEOUT = "timeout"
    class EpisodeCategory(str, Enum):
        TOOL_EXECUTION = "tool_execution"; QUERY_RESOLUTION = "query_resolution"
        ERROR_RECOVERY = "error_recovery"; USER_PREFERENCE = "user_preference"
        WORKFLOW_PATTERN = "workflow_pattern"; DECISION = "decision"; HANDOFF = "handoff"
- path: `packages/ai-parrot/src/parrot/memory/episodic/models.py`
  lines: 214-240
  symbol: `MemoryNamespace`
  excerpt: |
    - Per-session: (tenant_id, agent_id, user_id, session_id)
    tenant_id: str; agent_id: str; user_id: str | None; session_id: str | None; room_id: str | None
- path: `packages/ai-parrot/src/parrot/memory/episodic/backends/pgvector.py`
  lines: 143-143
  symbol: `pgvector schema (category)`
  excerpt: |
    category        VARCHAR(32) NOT NULL DEFAULT 'tool_execution',

## Notes
- Extending `EpisodeCategory` is a core-package change to `parrot/memory/episodic/models.py`. Two lighter options that avoid touching the enum: use `WORKFLOW_PATTERN` or `ERROR_RECOVERY` with `metadata={"procedure_id":..., "step":...}` and `related_entities`.
- I did not verify whether other backends (redis, faiss) use a CHECK constraint on category.

