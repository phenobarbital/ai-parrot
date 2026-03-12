# Feature Specification: Episodic Memory Store v2

**Feature ID**: FEAT-045
**Date**: 2026-03-11
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.6.0
**Brainstorm**: `sdd/proposals/episodicstore.brainstorm.md`

---

## 1. Motivation & Business Requirements

> Give AI-Parrot agents long-term experiential memory: what they did, what happened, and what they learned — scoped per user, per room, per crew, and per agent.

### Problem Statement

AI-Parrot agents currently have conversation memory (`ConversationMemory` backends) and vector-based RAG, but no **episodic memory** — the ability to remember past experiences, failures, and learned lessons across sessions.

Specific gaps:

1. **No failure memory**: When a tool call fails (e.g., `get_schema` on a non-existent schema), the agent has no way to remember this and avoid the same mistake next time.
2. **No per-user preference tracking**: An agent can't remember that "@jesus prefers Spanish responses" or "@carlos is a technical user who doesn't need basic explanations."
3. **No per-room context**: In Matrix/Telegram/Slack rooms, agents can't recall room-level decisions (e.g., "this room uses the 3-step workflow for P1 tickets").
4. **No cross-agent learning**: In a crew, when the Research Agent discovers an API rate limit, other agents can't access that knowledge.
5. **No reflection**: Agents don't analyze outcomes to extract reusable lessons.

**Existing foundation** (ready to build on):
- `ConversationMemory` (abstract.py) — session-based turn storage (Redis, file, in-memory).
- `AgentCoreMemory` (core.py) — hybrid Redis hot + PgVector cold with BM25 + semantic search (framework only, not wired into agents).
- `PgVectorStore` (stores/postgres.py) — async SQLAlchemy + pgvector with dynamic table definition.
- `AbstractBot.ask()` — accepts a `memory` callable for injecting context before LLM inference.
- `@tool` decorator and `AbstractToolkit` — for exposing episodic memory as agent-usable tools.
- `ToolResult` — standardized tool output format with `success`, `status`, `error` fields.

### Goals

- Implement `EpisodicMemoryStore` with pluggable backends (PgVector for production, FAISS for local dev).
- Support hierarchical namespace scoping: tenant → agent → user/room/session/crew.
- Auto-record significant tool executions and conversation outcomes.
- Generate reflections (lesson learned, suggested action) via LLM with heuristic fallback.
- Provide semantic recall with dimensional filters (by user, room, crew, failure-only).
- Inject failure warnings and learned context into the system prompt before LLM calls.
- Expose episodic memory as agent-usable tools (search, record, get warnings).
- Cache hot episodes in Redis for fast access.
- Support TTL-based expiration and namespace compaction.

### Non-Goals (explicitly out of scope)

- Replacing `ConversationMemory` — episodic memory complements it, not replaces it.
- Real-time streaming of episodes to external systems (future: event bus integration).
- Graph-based episode relationships (future: ArangoDB backend).
- Multi-tenant schema isolation at the PostgreSQL level (uses column-based tenant_id filtering).
- Automatic importance calibration via reinforcement learning.

---

## 2. Architectural Design

### Overview

Create a `parrot/memory/episodic/` subpackage implementing a strategy-pattern store with pluggable backends, a reflection engine, an embedding provider, and a Redis hot cache. Integrate into `AbstractBot` via a mixin that auto-records episodes and injects episodic context into prompts.

### Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│                  EpisodicMemoryStore                     │
│  (orchestrates backend, reflection, embedding, cache)    │
└───────────────────────────┬─────────────────────────────┘
                            │
      ┌─────────────────────┼──────────────────────┐
      │                     │                      │
      ▼                     ▼                      ▼
┌──────────────┐   ┌────────────────┐   ┌──────────────────┐
│ Backend      │   │ Reflection     │   │ Embedding        │
│ (Strategy)   │   │ Engine         │   │ Provider         │
│              │   │ (LLM +         │   │ (sentence-       │
│ ┌──────────┐ │   │  heuristic     │   │  transformers)   │
│ │ PgVector │ │   │  fallback)     │   │                  │
│ │ Backend  │ │   └────────────────┘   └──────────────────┘
│ ├──────────┤ │
│ │ FAISS    │ │   ┌────────────────┐
│ │ Backend  │ │   │ Redis Hot      │
│ └──────────┘ │   │ Cache          │
└──────────────┘   │ (recent +      │
                   │  failures)     │
                   └────────────────┘
```

### Data Model — Episode Table

```sql
parrot_episodic_memory
├── episode_id: UUID (PK)
├── created_at: TIMESTAMPTZ
├── updated_at: TIMESTAMPTZ
├── expires_at: TIMESTAMPTZ (nullable, for TTL)
│
├── ── Namespace Dimensions ──
├── tenant_id: VARCHAR(64)
├── agent_id: VARCHAR(128)
├── user_id: VARCHAR(128) (nullable)
├── session_id: VARCHAR(128) (nullable)
├── room_id: VARCHAR(256) (nullable)
├── crew_id: VARCHAR(128) (nullable)
│
├── ── Episode Content ──
├── situation: TEXT
├── action_taken: TEXT
├── outcome: VARCHAR(16)          -- success | failure | partial | timeout
├── outcome_details: TEXT
├── error_type: VARCHAR(128) (nullable)
├── error_message: TEXT (nullable)
│
├── ── Reflection (LLM-generated) ──
├── reflection: TEXT
├── lesson_learned: VARCHAR(512)
├── suggested_action: TEXT
│
├── ── Classification ──
├── category: VARCHAR(32)         -- tool_execution | query_resolution |
│                                 -- error_recovery | user_preference |
│                                 -- workflow_pattern | decision | handoff
├── importance: SMALLINT          -- 1-10
├── is_failure: BOOLEAN
├── related_tools: VARCHAR[]
├── related_entities: VARCHAR[]
│
├── ── Vector Embedding ──
├── embedding: VECTOR(384)        -- all-MiniLM-L6-v2 (configurable)
│
└── metadata: JSONB
```

### Indexes

```sql
-- Similarity search with dimensional filter
CREATE INDEX idx_episodes_embedding ON parrot_episodic_memory
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Namespace queries (most common)
CREATE INDEX idx_episodes_agent_user ON parrot_episodic_memory (tenant_id, agent_id, user_id);
CREATE INDEX idx_episodes_agent_room ON parrot_episodic_memory (tenant_id, agent_id, room_id);
CREATE INDEX idx_episodes_crew ON parrot_episodic_memory (tenant_id, crew_id);

-- Failure filter for fast warnings
CREATE INDEX idx_episodes_failures ON parrot_episodic_memory (agent_id, is_failure)
  WHERE is_failure = TRUE;

-- TTL cleanup
CREATE INDEX idx_episodes_expires ON parrot_episodic_memory (expires_at)
  WHERE expires_at IS NOT NULL;

-- Importance for prioritization
CREATE INDEX idx_episodes_importance ON parrot_episodic_memory (agent_id, importance DESC);
```

### MemoryNamespace — Hierarchical Scoping

```python
class MemoryNamespace(BaseModel):
    """Hierarchical namespace for isolating episodes.

    Supports queries at different granularity levels:
    - Global agent: (tenant_id, agent_id) → "everything this agent knows"
    - Per-user: (tenant_id, agent_id, user_id) → "episodes with this user"
    - Per-room: (tenant_id, agent_id, room_id) → "episodes in this room"
    - Per-session: (tenant_id, agent_id, user_id, session_id) → "this conversation"
    - Per-crew: (tenant_id, crew_id) → "shared crew episodes"
    """
    tenant_id: str = "default"
    agent_id: str
    user_id: str | None = None
    session_id: str | None = None
    room_id: str | None = None
    crew_id: str | None = None

    def build_filter(self) -> dict[str, Any]: ...
    @property
    def scope_label(self) -> str: ...
    @property
    def redis_prefix(self) -> str: ...
```

### Data Flow — Recording an Episode

```
1. Agent executes tool (e.g., get_schema("analytics"))
2. Tool returns ToolResult(success=False, error="schema not found")
3. EpisodicMemoryMixin._record_post_tool() fires:
   a. Skip if tool is in trivial_tools set
   b. Auto-compute importance (failure → base 7, success → base 3)
   c. If reflection enabled → ReflectionEngine.reflect() via LLM
   d. EmbeddingProvider.embed(situation + action + lesson)
   e. Backend.store(episode) → INSERT into PgVector
   f. Redis cache invalidated for this namespace
4. Episode stored with full dimensional context
```

### Data Flow — Injecting Episodic Context

```
1. User sends query: "Show me the analytics schema"
2. AbstractBot.ask() calls EpisodicMemoryMixin._build_episodic_context()
3. Mixin performs:
   a. recall_similar(query, namespace) → past episodes about schemas
   b. get_failure_warnings(namespace, query) → relevant past failures
   c. get_user_preferences(namespace) → user-specific preferences
   d. get_room_context(namespace) → room-level decisions
4. Assembled context injected into system prompt:
   ⚠️ MISTAKES TO AVOID:
   - Tool 'get_schema' failed for schema 'analytics' — verify schema exists first
   ✓ SUCCESSFUL APPROACHES:
   - For database questions, always run schema discovery first
5. LLM now has experiential context to avoid repeating mistakes
```

---

## 3. Detailed Module Design

### 3.1 `parrot/memory/episodic/models.py` — Data Models and Enums

**Enums:**
- `EpisodeOutcome`: `SUCCESS`, `FAILURE`, `PARTIAL`, `TIMEOUT`
- `EpisodeCategory`: `TOOL_EXECUTION`, `QUERY_RESOLUTION`, `ERROR_RECOVERY`, `USER_PREFERENCE`, `WORKFLOW_PATTERN`, `DECISION`, `HANDOFF`

**Models:**
- `EpisodicMemory` — Pydantic model matching the table schema (all fields).
- `MemoryNamespace` — Hierarchical scoping with `build_filter()`, `scope_label`, `redis_prefix`.
- `EpisodeSearchResult` — `EpisodicMemory` + `score: float` for search results.
- `ReflectionResult` — `reflection`, `lesson_learned`, `suggested_action`.

### 3.2 `parrot/memory/episodic/backends/abstract.py` — Backend Protocol

```python
class AbstractEpisodeBackend(Protocol):
    async def store(self, episode: EpisodicMemory) -> str: ...
    async def search_similar(
        self, embedding: list[float], namespace_filter: dict[str, Any],
        top_k: int = 5, score_threshold: float = 0.3,
        include_failures_only: bool = False,
    ) -> list[EpisodeSearchResult]: ...
    async def get_recent(
        self, namespace_filter: dict[str, Any],
        limit: int = 10, since: datetime | None = None,
    ) -> list[EpisodicMemory]: ...
    async def get_failures(
        self, agent_id: str, tenant_id: str = "default", limit: int = 5,
    ) -> list[EpisodicMemory]: ...
    async def delete_expired(self) -> int: ...
    async def count(self, namespace_filter: dict[str, Any]) -> int: ...
```

### 3.3 `parrot/memory/episodic/backends/pgvector.py` — PgVector Backend

Uses `asyncpg` directly (not SQLAlchemy) for maximum control. Auto-creates schema, table, and indexes on `configure()`. Similarity search uses cosine distance with dimensional WHERE filters.

### 3.4 `parrot/memory/episodic/backends/faiss.py` — FAISS Backend

In-memory FAISS index + dict storage for local development. Optional persistence to disk (`episodes.faiss` + `episodes.jsonl`). Namespace filters applied post-search (no SQL).

### 3.5 `parrot/memory/episodic/embedding.py` — Embedding Provider

Lazy-loading `sentence-transformers` provider. Default model: `all-MiniLM-L6-v2` (384d). Uses `asyncio.to_thread()` for non-blocking embedding. Supports batch embedding.

### 3.6 `parrot/memory/episodic/reflection.py` — Reflection Engine

LLM-powered reflection with structured output. Prompt analyzes situation + action + outcome and extracts: reflection, lesson_learned, suggested_action. Heuristic fallback for known patterns (timeout → "add delay", rate_limit → "throttle calls", permission_denied → "check permissions first").

### 3.7 `parrot/memory/episodic/cache.py` — Redis Hot Cache

Redis cache for recent episodes per namespace. Keys: `episodic:{tenant}:{agent}:recent` (ZSET by timestamp), `episodic:{tenant}:{agent}:{episode_id}` (HASH), `episodic:{tenant}:{agent}:failures` (LIST). TTL: 1 hour default. Invalidated on write.

### 3.8 `parrot/memory/episodic/store.py` — EpisodicMemoryStore (Main Orchestrator)

Central class orchestrating backend, reflection, embedding, and cache.

**Recording API:**
- `record_episode(namespace, situation, action_taken, outcome, ...)` — full episode recording with auto-importance, reflection, embedding, and caching.
- `record_tool_episode(namespace, tool_name, tool_args, tool_result, user_query)` — convenience wrapper extracting episode fields from ToolResult.
- `record_crew_episode(namespace, crew_result, flow_description)` — records crew-level episode + optional per-agent episodes.

**Recall API:**
- `recall_similar(query, namespace, top_k, score_threshold, ...)` — semantic search with dimensional filters.
- `get_failure_warnings(namespace, current_query, max_warnings)` — generates injectable warning text for system prompt.
- `get_user_preferences(namespace)` — retrieves USER_PREFERENCE category episodes.
- `get_room_context(namespace, limit, categories)` — retrieves recent room episodes.

**Maintenance API:**
- `cleanup_expired()` — deletes expired episodes (for cron/scheduler).
- `compact_namespace(namespace, keep_top_n, keep_all_failures)` — retains top-N by importance.
- `export_episodes(namespace, format)` — exports for debugging/audit.

### 3.9 `parrot/memory/episodic/tools.py` — Agent-Usable Tools

Tools exposed via `AbstractToolkit` so agents can explicitly interact with episodic memory:
- `EpisodicMemorySearchTool` — search past episodes by semantic query.
- `EpisodicMemoryRecordTool` — explicitly record a lesson or preference.
- `GetFailureWarningsTool` — retrieve warnings about past failures.

### 3.10 `parrot/memory/episodic/mixin.py` — EpisodicMemoryMixin

Mixin for `AbstractBot` that:
- Auto-configures during `configure()`.
- Provides `_build_episodic_context(query, user_id, room_id)` for system prompt injection.
- Provides `_record_post_tool(...)` and `_record_post_ask(...)` hooks.
- Configurable: `enable_episodic_memory`, `episodic_backend` ("pgvector"/"faiss"), `episodic_reflection_enabled`, `episodic_inject_warnings`, `episodic_trivial_tools` set.

---

## 4. Integration Points

### 4.1 AbstractBot.ask() Integration

The `EpisodicMemoryMixin` hooks into the existing `ask()` flow:
1. **Pre-LLM**: `_build_episodic_context()` assembles warnings + preferences + room context, injected into system prompt.
2. **Post-tool**: `_record_post_tool()` fires after each tool execution, recording significant episodes.
3. **Post-ask**: `_record_post_ask()` fires after the full ask cycle, recording conversation-level episodes.

### 4.2 AgentCrew Integration

When agents run as part of a crew (`AgentCrew`), the `crew_id` dimension enables shared episodic memory:
- `record_crew_episode()` records the overall crew execution result.
- Individual agents record their episodes with both `agent_id` and `crew_id`.
- Any agent in the crew can query `crew_id`-scoped episodes to learn from peers.

### 4.3 Matrix/Telegram/Slack Room Integration

Integration wrappers pass `room_id` through to the agent's `ask()` call. The mixin automatically scopes episodes to the room, enabling room-level context recall.

### 4.4 AgentCoreMemory Relationship

`AgentCoreMemory` (existing) handles hybrid Redis/PgVector for general agent memory with BM25. `EpisodicMemoryStore` is a separate, purpose-built system for experiential memory. They can coexist — `AgentCoreMemory` for factual recall, `EpisodicMemoryStore` for experiential recall.

---

## 5. Configuration & Dependencies

### New Dependencies

- `asyncpg` — already in project (used by Navigator ORM).
- `sentence-transformers` — already in project (used by vectorstores).
- `faiss-cpu` — optional, for local development backend.
- No new external dependencies required.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `EPISODIC_DSN` | PostgreSQL connection string for PgVector backend | Falls back to default project DSN |
| `EPISODIC_SCHEMA` | PostgreSQL schema name | `parrot_memory` |
| `EPISODIC_EMBEDDING_MODEL` | Sentence-transformers model | `all-MiniLM-L6-v2` |
| `EPISODIC_EMBEDDING_DIM` | Embedding vector dimension | `384` |
| `EPISODIC_TTL_DAYS` | Default episode TTL | `90` |

### Files Created/Modified

**New files** (`parrot/memory/episodic/`):

| File | Purpose | Effort |
|------|---------|--------|
| `__init__.py` | Public exports | S |
| `models.py` | EpisodicMemory, MemoryNamespace, enums, search results | M |
| `backends/__init__.py` | Backend exports | S |
| `backends/abstract.py` | AbstractEpisodeBackend Protocol | S |
| `backends/pgvector.py` | PgVector backend with asyncpg | L |
| `backends/faiss.py` | FAISS local backend | M |
| `embedding.py` | EpisodeEmbeddingProvider (lazy sentence-transformers) | S |
| `reflection.py` | ReflectionEngine (LLM + heuristic fallback) | M |
| `cache.py` | EpisodeRedisCache | M |
| `store.py` | EpisodicMemoryStore (main orchestrator) | L |
| `tools.py` | Agent-usable episodic memory tools | M |
| `mixin.py` | EpisodicMemoryMixin for AbstractBot | L |

**Modified files:**

| File | Change | Effort |
|------|--------|--------|
| `parrot/memory/__init__.py` | Add episodic subpackage exports | S |

---

## 6. Acceptance Criteria

1. **PgVector backend**: Episodes are stored and retrieved from PostgreSQL with pgvector similarity search and dimensional WHERE filters.
2. **FAISS backend**: Local development works without PostgreSQL using in-memory FAISS with optional disk persistence.
3. **Namespace scoping**: Queries can be scoped to agent, user, room, session, or crew level.
4. **Auto-recording**: Significant tool executions are automatically recorded (trivial tools filtered out).
5. **Reflection**: Episodes include LLM-generated reflection with heuristic fallback when no LLM is available.
6. **Failure warnings**: `get_failure_warnings()` produces injectable text for system prompts listing past mistakes and successful approaches.
7. **User preferences**: Per-user preference episodes can be stored and recalled.
8. **Room context**: Per-room episodes provide context when agents enter rooms.
9. **Crew sharing**: Episodes scoped to `crew_id` are accessible by all agents in the crew.
10. **Redis cache**: Recent episodes and failures are cached in Redis for fast access.
11. **TTL & compaction**: Expired episodes are cleaned up; namespaces can be compacted to top-N by importance.
12. **Agent tools**: Agents can explicitly search, record, and retrieve warnings via tool calls.
13. **Mixin integration**: `EpisodicMemoryMixin` injects context pre-LLM and records episodes post-tool/post-ask.
14. **Tests**: Unit tests for models, backends, embedding, reflection; integration tests for store and mixin.

---

## 7. Testing Strategy

### Unit Tests

| Test | Validates |
|------|-----------|
| `test_models_episode_creation` | EpisodicMemory field validation, defaults |
| `test_models_namespace_filter` | MemoryNamespace.build_filter() produces correct SQL WHERE |
| `test_models_enums` | EpisodeOutcome, EpisodeCategory string values |
| `test_pgvector_store_retrieve` | Store + search_similar round-trip (requires test PostgreSQL) |
| `test_pgvector_namespace_filter` | Dimensional filtering (user_id, room_id, crew_id) |
| `test_pgvector_failure_index` | get_failures() uses partial index |
| `test_pgvector_ttl_cleanup` | delete_expired() removes old episodes |
| `test_faiss_store_retrieve` | Store + search_similar round-trip (in-memory) |
| `test_faiss_persistence` | Save/load to disk |
| `test_faiss_post_filter` | Namespace filtering applied post-search |
| `test_embedding_lazy_load` | Model loads only on first embed() call |
| `test_embedding_dimension` | Output vector has correct dimension |
| `test_reflection_llm` | LLM-generated reflection with mocked client |
| `test_reflection_heuristic` | Heuristic fallback for known error patterns |
| `test_redis_cache_hit` | Cached episodes returned without backend call |
| `test_redis_cache_invalidation` | Cache invalidated on new episode write |

### Integration Tests

| Test | Validates |
|------|-----------|
| `test_store_record_and_recall` | Full flow: record → embed → store → recall_similar |
| `test_store_failure_warnings` | Record failures → get_failure_warnings() produces text |
| `test_store_tool_episode` | record_tool_episode() extracts fields from ToolResult |
| `test_mixin_pre_llm_injection` | _build_episodic_context() returns formatted text |
| `test_mixin_post_tool_recording` | _record_post_tool() stores episode after tool call |
| `test_store_namespace_scoping` | Episodes scoped to user/room/crew are isolated |

### Test Fixtures

- Mock `asyncpg` pool for PgVector tests without real database.
- In-memory FAISS backend for integration tests.
- Mock `AbstractClient` for reflection engine tests.
- Mock Redis for cache tests.

---

## 8. Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Reason**: Tasks build on shared models and the same `parrot/memory/episodic/` package. Each task imports from prior tasks.
- **Cross-feature dependencies**: None — uses existing `asyncpg`, `sentence-transformers`, and Redis infrastructure.

---

## 9. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary backend | PgVector (asyncpg) | Already used for RAG; persists; supports complex SQL filters |
| Secondary backend | FAISS | For local dev without PostgreSQL |
| Embedding model | all-MiniLM-L6-v2 (384d) | Fast, good quality for short texts (situation + action + lesson) |
| Reflection | LLM + heuristic fallback | Don't depend 100% on LLM availability |
| Cache | Redis ZSET + HASH | Already in infrastructure; fast for recent/failure lookups |
| Tenant isolation | Column-based (tenant_id) | Simpler than schema-per-tenant; sufficient for current scale |
| Score threshold | 0.3 default | Sentence-transformers with cosine works well with low thresholds |
| Trivial tool filter | Configurable set | Prevents filling DB with irrelevant episodes (get_time, etc.) |
| Default TTL | 90 days | Balance between retention and database size |
| Asyncpg vs SQLAlchemy | asyncpg directly | Maximum control for pgvector queries; existing PgVectorStore uses SQLAlchemy — this avoids coupling |

---

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| High episode volume (chatty agents) | DB bloat | Trivial tool filter + importance threshold + TTL + compaction |
| Reflection LLM adds latency | Slower recording | Async fire-and-forget reflection; record episode immediately, update reflection later |
| Embedding model memory usage | High RSS on startup | Lazy loading — model only loaded on first embed() call |
| FAISS index too large for memory | OOM on dev machines | Cap FAISS index size; compact old episodes |
| Namespace filter not selective enough | Slow queries | Composite indexes on (tenant_id, agent_id, user_id/room_id) |
| Redis cache inconsistency | Stale data | Short TTL (1h) + invalidate-on-write pattern |
