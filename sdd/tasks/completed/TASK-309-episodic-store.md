# TASK-309 — EpisodicMemoryStore Main Orchestrator

**Feature**: FEAT-045 (Episodic Memory Store v2)
**Spec**: `sdd/specs/episodicmemorystore.spec.md`
**Status**: pending
**Priority**: high
**Effort**: L
**Depends on**: TASK-304, TASK-305, TASK-306, TASK-307, TASK-308
**Parallel**: false
**Parallelism notes**: Central orchestrator importing all prior modules: models, backends, embedding, reflection, and cache.

---

## Objective

Implement `EpisodicMemoryStore` — the main API class that orchestrates the backend, reflection engine, embedding provider, and Redis cache to provide recording, recall, and maintenance operations.

## Files to Create/Modify

- `parrot/memory/episodic/store.py` — new file

## Implementation Details

### EpisodicMemoryStore

Per spec section 3.8 and brainstorm section 4:

```python
class EpisodicMemoryStore:
    def __init__(
        self,
        backend: AbstractEpisodeBackend,
        embedding_provider: EpisodeEmbeddingProvider | None = None,
        reflection_engine: ReflectionEngine | None = None,
        redis_cache: EpisodeRedisCache | None = None,
        default_ttl_days: int = 90,
    ) -> None: ...
```

### Recording API

**record_episode(namespace, situation, action_taken, outcome, ...)**:
1. Auto-compute importance if not provided (failures: base 7, success: base 3, +2 for known error_type).
2. If reflection_engine and generate_reflection: `await reflection_engine.reflect(...)`.
3. If embedding_provider: `await embedding_provider.embed(searchable_text)`.
4. Set `expires_at = now + ttl_days` if ttl provided.
5. `await backend.store(episode)`.
6. If redis_cache: `await redis_cache.cache_episode(namespace, episode)`.
7. Return complete EpisodicMemory.

**record_tool_episode(namespace, tool_name, tool_args, tool_result, user_query)**:
- Extract: situation from user_query, action from `"Called {tool_name} with {summarized_args}"`.
- Map tool_result.status → EpisodeOutcome.
- Extract error_type/error_message from tool_result.
- Set category=TOOL_EXECUTION, related_tools=[tool_name].
- Delegate to `record_episode()`.

**record_crew_episode(namespace, crew_result, flow_description, per_agent=True)**:
- Create one crew-level episode with crew_id.
- If per_agent: create one episode per agent that participated.
- Return list of all created episodes.

### Recall API

**recall_similar(query, namespace, top_k, score_threshold, ...)**:
- Embed query via embedding_provider.
- Build namespace filter via namespace.build_filter().
- Call backend.search_similar().
- Apply optional category filter post-search.
- Return list[EpisodeSearchResult].

**get_failure_warnings(namespace, current_query, max_warnings)**:
- Recall similar failures (include_failures_only=True).
- Also get recent failures from backend.get_failures().
- Deduplicate and rank by relevance.
- Format as injectable text:
  ```
  MISTAKES TO AVOID:
  - Tool 'get_schema' failed for schema 'analytics' — verify schema exists first
  SUCCESSFUL APPROACHES:
  - For database questions, always run schema discovery first
  ```

**get_user_preferences(namespace)**:
- Call backend.get_recent() with category filter = USER_PREFERENCE.

**get_room_context(namespace, limit, categories)**:
- Call backend.get_recent() with room_id in namespace filter.

### Maintenance API

**cleanup_expired()**:
- Call backend.delete_expired(), return count.

**compact_namespace(namespace, keep_top_n, keep_all_failures)**:
- Get all episodes in namespace, sort by importance DESC.
- Keep top N + all failures.
- Delete the rest via backend.

**export_episodes(namespace, format)**:
- Get all episodes in namespace.
- Return as JSONL string.

### Factory Methods

```python
@classmethod
async def create_pgvector(cls, dsn: str, **kwargs) -> "EpisodicMemoryStore":
    """Create store with PgVector backend."""
    ...

@classmethod
def create_faiss(cls, persistence_path: str | None = None, **kwargs) -> "EpisodicMemoryStore":
    """Create store with FAISS backend."""
    ...
```

## Acceptance Criteria

- [ ] `record_episode()` auto-computes importance, generates reflection, embeds, stores, and caches.
- [ ] `record_tool_episode()` extracts fields from ToolResult correctly.
- [ ] `record_crew_episode()` creates crew-level + per-agent episodes.
- [ ] `recall_similar()` returns semantically similar episodes with namespace filtering.
- [ ] `get_failure_warnings()` produces formatted warning text for system prompt injection.
- [ ] `get_user_preferences()` returns USER_PREFERENCE category episodes.
- [ ] `get_room_context()` returns room-scoped recent episodes.
- [ ] `cleanup_expired()` delegates to backend.
- [ ] `compact_namespace()` keeps top-N + failures, deletes rest.
- [ ] Factory methods create fully configured stores.
