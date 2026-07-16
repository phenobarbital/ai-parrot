---
type: Wiki Overview
title: 'Brainstorm: Agent Artifact Persistency'
id: doc:sdd-proposals-agent-artifact-persistency-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Every time a user interacts with an AI agent, the system generates valuable
  artifacts — charts, canvas tabs, infographics, DataFrames — that live exclusively
  in frontend memory and disappear on page reload. Hours of curatorial work vanish
  when the browser tab closes.
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.handlers
  rel: mentions
- concept: mod:parrot.interfaces
  rel: mentions
- concept: mod:parrot.interfaces.aws
  rel: mentions
- concept: mod:parrot.interfaces.documentdb
  rel: mentions
- concept: mod:parrot.interfaces.file.s3
  rel: mentions
- concept: mod:parrot.memory
  rel: mentions
- concept: mod:parrot.models.infographic
  rel: mentions
- concept: mod:parrot.storage
  rel: mentions
- concept: mod:parrot.storage.dynamodb
  rel: mentions
- concept: mod:parrot.storage.models
  rel: mentions
---

# Brainstorm: Agent Artifact Persistency

**Date**: 2025-04-16
**Author**: Jesus
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

Every time a user interacts with an AI agent, the system generates valuable artifacts — charts, canvas tabs, infographics, DataFrames — that live exclusively in frontend memory and disappear on page reload. Hours of curatorial work vanish when the browser tab closes.

Additionally, the current conversation persistence architecture has structural inefficiencies:

1. **No artifact model**: The backend has no concept of "artifact." Charts, canvas tabs, and infographics never touch the server.
2. **Multi-round-trip loading**: Opening a chat requires 3-4 separate DocumentDB queries (list sessions → load thread → load turns → load large data). The access pattern is pure key-value, but we're paying the overhead of a semi-relational engine.
3. **Cost inefficiency**: A dedicated DocumentDB cluster (~$400/month) serves a workload that DynamoDB can handle for ~$23/month — a 95% reduction.

**Who is affected:**
- **End users**: lose generated artifacts on page reload; slow conversation loading.
- **Frontend developers**: no backend API for saving/loading artifacts; all state is ephemeral React/Svelte state.
- **Ops/Finance**: paying for an over-provisioned DocumentDB cluster.

**Why now:** The infographic and canvas features are maturing. Users are creating complex multi-tab compositions that take significant effort. Without persistence, these features remain demos rather than production tools.

## Constraints & Requirements

- **DynamoDB is the target store** — hard decision, not negotiable.
- **Redis hot cache stays untouched** — `ConversationMemory` / `RedisConversation` continue to serve the LLM context window. This feature replaces only the cold-storage layer (DocumentDB → DynamoDB).
- **No backward compatibility** — complete replacement of the DocumentDB persistence, not a migration shim.
- **Graceful degradation** — if DynamoDB is unreachable, the bot continues working (Redis handles the session). Turns don't persist, user gets a warning log. No backfill queue for missed turns.
- **Artifacts are per-thread** — no cross-thread artifact references. Charts are per-turn. Canvas, infographics, and chats are per-thread.
- **No versioning** — artifact updates replace the previous version in-place. No undo history.
- **No collaboration** — canvas tabs belong to one user in one thread. Future sharing means read-only copies.
- **TTL: 6 months** — user data (threads, turns, artifacts) expires after 6 months of inactivity.
- **S3 overflow is automated** — items > 200KB are transparently stored in S3 with a reference in DynamoDB. Configuration via `parrot.conf` variables.
- **Artifact saves happen from both sides**: agent auto-saves on `ask()` / `get_infographic()`, and frontend POSTs when users edit artifacts.
- **Infrastructure provisioning is out of scope** — DynamoDB tables and S3 buckets are assumed to exist.
- **No quotas in v1** — future consideration (e.g., 10 canvases, 4 infographics per thread).

---

## Options Explored

### Option A: Two-Table Design — Conversations+Turns / Artifacts (Recommended)

Use two DynamoDB tables: one for conversations (thread metadata + turns) and one for artifacts. Both share the same PK pattern, but serve different read/write profiles and can be queried in parallel.

**Rationale for two tables instead of one:** The frontend has three distinct read operations, not one mega-read:

1. **Sidebar load** (page open): list conversation sessions for an agent — returns only session_id + title + updated_at. No turns, no artifacts.
2. **Thread load** (user clicks a conversation): load the last N turns (default 10) for that session.
3. **Artifacts load** (parallel with #2): load all artifacts for that session.

Reads #2 and #3 happen in parallel. The frontend renders the chat immediately from #2 while artifacts arrive from #3. Mixing turns and artifacts in one table means the thread-load query returns items the frontend doesn't need yet (artifacts), wasting RCUs and adding latency. Two tables let each query return exactly what's needed.

**How it works:**

```
Table 1: parrot-conversations (thread metadata + turns)
┌───────────────────────────────┬──────────────────────────────────┐
│  PK                           │  SK                              │
├───────────────────────────────┼──────────────────────────────────┤
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-abc                 │ ← metadata
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-abc#TURN#001        │ ← turn
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-abc#TURN#002        │ ← turn
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-def                 │ ← another thread
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-def#TURN#001        │ ← turn
└───────────────────────────────┴──────────────────────────────────┘

Table 2: parrot-artifacts
┌───────────────────────────────┬──────────────────────────────────┐
│  PK                           │  SK                              │
├───────────────────────────────┼──────────────────────────────────┤
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-abc#chart-x1        │ ← chart
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-abc#canvas-main     │ ← canvas tab
│  USER#u123#AGENT#sales-bot    │  THREAD#sess-abc#infog-r1        │ ← infographic
└───────────────────────────────┴──────────────────────────────────┘
```

**Access patterns:**

| Operation | Table | DynamoDB Query | Items returned |
|-----------|-------|----------------|----------------|
| List conversations (sidebar) | conversations | `PK=USER#u#AGENT#a`, `SK begins_with "THREAD#"`, `FilterExpression: type="thread"` | Thread metadata only (session_id, title, updated_at) |
| Load thread turns (on click) | conversations | `PK=...`, `SK begins_with "THREAD#sess#TURN#"`, `Limit=10`, `ScanIndexForward=false` | Last 10 turns |
| Load artifacts (parallel) | artifacts | `PK=...`, `SK begins_with "THREAD#sess"` | All artifacts for session |
| Save turn | conversations | `PutItem` + `UpdateItem` on thread metadata | Atomic |
| Save/update artifact | artifacts | `PutItem` | Atomic |
| Delete thread | both | `Query` + `BatchWriteItem` on each table (parallel) | Cascade delete |

- A `DynamoDBBackend` class replaces `DocumentDb()` inside `ChatStorage`.
- An `ArtifactStore` class handles artifact CRUD against the artifacts table.
- S3 overflow is handled by a small `S3OverflowManager` that decides inline vs S3 based on a 200KB threshold.
- New Pydantic models for artifacts (`Artifact`, `ArtifactSummary`, `ThreadMetadata`, `CanvasDefinition`, etc.).
- New aiohttp endpoints for artifact CRUD (`/api/v1/threads/{id}/artifacts/...`).

**Pros:**
- Each read returns exactly what's needed — no wasted RCUs on items the frontend won't use yet
- Thread load and artifact load run in parallel — wall-clock time is `max(query1, query2)` not `sum()`
- Sidebar listing query hits only the conversations table — clean, no artifact items to filter out
- Independent provisioning: artifacts table can scale independently (large writes from infographics) vs conversations table (high-frequency small writes from turns)
- Independent TTL policies per table if needed in future
- Thread metadata + turns naturally belong together (always read together on click)
- Atomic writes per item — no contention
- 95% cost reduction vs DocumentDB

**Cons:**
- Two tables instead of one — 2x IAM policies, 2x CloudWatch alarms, 2x backup configs (but far simpler than 3 tables or DocumentDB)
- Thread deletion requires parallel cleanup of both tables
- Query patterns must be planned upfront — ad-hoc queries are expensive/impossible

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aioboto3` | Async AWS SDK for DynamoDB + S3 | Already a dependency (used by `S3FileManager`) |
| `boto3` | Sync fallback / type stubs | Transitive via aioboto3 |
| `pydantic` v2 | Artifact and thread models | Already a core dependency |

**Existing Code to Reuse:**
- `parrot/storage/chat.py` — `ChatStorage` class: the main integration point. Replace its `_docdb` backend with DynamoDB.
- `parrot/storage/models.py` — `ChatMessage`, `Conversation`, `MessageRole`: existing models to extend with artifact types.
- `parrot/interfaces/file/s3.py` — `S3FileManager`: reuse for S3 overflow (upload/download large artifacts).
- `parrot/interfaces/aws.py` — `AWSInterface`: base class for AWS credential management.
- `parrot/models/infographic.py` — `InfographicResponse`: the artifact payload for infographic type.
- `parrot/conf.py` — `AWS_CREDENTIALS` dict: extend with DynamoDB-specific config.

---

### Option B: DynamoDB Single-Table Design — Everything in One Table

All record types (thread metadata, turns, artifacts) live in a single DynamoDB table, discriminated by SK prefix patterns.

**How it works:**
- One DynamoDB table (`parrot-conversations`) with composite keys:
  - `PK = USER#{user_id}#AGENT#{agent_id}`
  - `SK = THREAD#{session_id}` (thread metadata)
  - `SK = THREAD#{session_id}#TURN#{turn_id}` (individual turns)
  - `SK = THREAD#{session_id}#ARTIFACT#{artifact_id}` (artifacts)
- A single `Query(PK=..., SK begins_with "THREAD#sess-abc")` returns the entire thread (metadata + turns + artifacts).
- Loading just turns or just artifacts requires SK filtering.

**Pros:**
- Minimal tables to manage (one table + one GSI)
- One query can load everything for a thread
- Well-established AWS pattern (Rick Houlihan's single-table design)
- Atomic writes per item — no contention

**Cons:**
- Thread listing returns turns and artifacts too — requires `FilterExpression: type="thread"` to exclude them, wasting RCUs
- Cannot parallelize turn loading and artifact loading — they come from the same query
- All item types share provisioned capacity — a burst of artifact writes affects turn read latency
- Loading just turns (the most common read) pulls artifact items into the query result set unnecessarily
- Frontend rendering is sequential (chat first, artifacts second), but the single query forces waiting for everything

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aioboto3` | Async AWS SDK for DynamoDB + S3 | Already a dependency |
| `pydantic` v2 | Models | Already a core dependency |

**Existing Code to Reuse:**
- Same as Option A (ChatStorage, S3FileManager, AWSInterface, models)

---

### Option C: DynamoDB Single-Table with Adaptive Document Bundling

A hybrid approach: small/medium threads (< 100 turns) are stored as "fat documents" — a single DynamoDB item containing the thread metadata, all turns, and all artifact summaries inline. When a thread grows beyond a size threshold (e.g., 300KB or 100 turns), the system automatically "unbundles" it into individual items (like Option A).

**How it works:**
- For new/small threads: one item per thread with turns and artifact summaries embedded as lists.
- A background job or write-time check monitors item size. When approaching 350KB (safety margin for 400KB limit), the thread is decomposed into individual items.
- Artifact full definitions always stored separately (individual items or S3) since they can be large.
- Read path: `GetItem` for small threads (1 RCU), `Query` for unbundled threads (N RCUs).

**Pros:**
- Optimized for the common case: most conversations are short (< 20 turns), so one `GetItem` (1 RCU) is cheaper than one `Query` (N RCUs)
- Lower read costs for typical usage patterns
- Simpler initial implementation (just store a JSON blob)

**Cons:**
- Two code paths for reads and writes — complexity doubles
- The unbundling migration is a complex, error-prone operation
- Concurrent writes to the same fat document cause contention (DynamoDB conditional writes needed)
- When a thread grows past the threshold, there's a latency spike during unbundling
- Harder to query for specific turns or artifacts without loading the entire document
- The 400KB limit means threads with large `data` payloads on turns could unbundle very early, negating the benefit
- Significantly harder to maintain and debug

**Effort:** Very High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aioboto3` | Async AWS SDK | Already a dependency |
| `pydantic` v2 | Models | Already a core dependency |

**Existing Code to Reuse:**
- Same as Option A

---

## Recommendation

**Option A (Two-Table Design)** is recommended because:

1. **Matches the actual frontend access pattern.** The frontend performs three distinct reads, not one mega-read: (1) list conversations for sidebar, (2) load last 10 turns on click, (3) load artifacts in parallel. Two tables let reads #2 and #3 execute concurrently — the chat renders immediately while artifacts load in the background. A single table (Option B) forces everything into one query, delaying the chat render until artifacts are also fetched.

2. **No wasted reads.** Sidebar listing hits only the conversations table — clean query, no artifact items to filter out. In Option B, `begins_with("THREAD#")` returns thread + turn + artifact items, and `FilterExpression` discards the extras after consuming RCUs.

3. **Independent scaling.** Conversations table handles high-frequency small writes (every `ask()` call). Artifacts table handles low-frequency large writes (infographics, canvas saves). Different write profiles benefit from independent provisioning.

4. **Natural fit for `ChatStorage`.** The existing class already abstracts the cold-storage backend. The conversations table replaces `DocumentDb`, and a new `ArtifactStore` handles the artifacts table. Clean separation of concerns.

5. **Minimal operational overhead.** Two tables is a modest increase over one, and far simpler than three (Option B originally proposed) or the dual code-path complexity of Option C. Two IAM policies, two backup configs — manageable.

**What we trade off:** Loading a complete thread (turns + artifacts) requires two parallel queries instead of one. In practice this is faster (parallel execution, each query returns only what's needed) and cheaper (no wasted RCUs on FilterExpression discards). Ad-hoc querying is also lost vs DocumentDB, but our access patterns are well-defined and stable.

---

## Feature Description

### User-Facing Behavior

1. **Conversation persistence is invisible.** The user's chat threads, including all turns and metadata, persist across page reloads and sessions. Opening a previous conversation loads instantly with full history.

2. **Artifact persistence is automatic for agent-generated content.** When the agent generates an infographic via `get_infographic()` or returns data via `ask()`, the artifact is automatically saved. The user sees the same infographic/chart/data when they return to the conversation.

3. **User-edited artifacts save via explicit action.** When the user modifies an infographic in the frontend editor, the frontend POSTs the updated definition to `/api/v1/threads/{session_id}/artifacts/{id}`. The artifact is replaced in-place (no versioning).

4. **Canvas tabs persist per-thread.** Each canvas tab (including the default `main` tab) is saved as an artifact. Blocks within the canvas reference other artifacts (charts, infographics) and turns (data tables, agent responses) by ID.

5. **Conversation sidebar loads fast.** The sidebar shows only session_id + title + updated_at — no turns, no artifacts. A lightweight query against the conversations table.

6. **6-month TTL.** Threads, turns, and artifacts that haven't been updated in 6 months are automatically cleaned up.

### Internal Behavior

**Write flow (turn saved):**
```
ask() / conversation()
  ├── Redis: add_turn() (hot cache, unchanged)
  └── ChatStorage.save_turn()
        └── [conversations table] DynamoDBBackend.put_item(
              PK=USER#u#AGENT#a, SK=THREAD#s#TURN#t,
              type="turn", ...turn data...
            )
            + DynamoDBBackend.update_item(
                PK=USER#u#AGENT#a, SK=THREAD#s,
                SET turn_count = turn_count + 1, updated_at = now
              )
```

**Write flow (artifact saved by agent):**
```
get_infographic() → InfographicResponse
  └── ArtifactStore.save_artifact(
        artifact_type="infographic",
        definition=infographic_response.model_dump(),
        source_turn_id=turn_id
      )
      └── S3OverflowManager.maybe_offload(definition)
            ├── if < 200KB → inline in DynamoDB item
            └── if >= 200KB → upload to S3, store reference
      └── [artifacts table] DynamoDBBackend.put_item(
            PK=USER#u#AGENT#a, SK=THREAD#s#infog-r1,
            definition=... or definition_ref=s3://...
          )
```

**Write flow (artifact updated by frontend):**
```
PUT /api/v1/threads/{session_id}/artifacts/{id}
  └── ArtifactStore.update_artifact(session_id, artifact_id, new_definition)
      └── [artifacts table] DynamoDBBackend.put_item(
            PK=..., SK=THREAD#s#id,
            definition=new_definition, updated_at=now
          )
```

**Read flow — 3 distinct reads matching frontend rendering:**

```
READ 1: List conversations (sidebar — on page open)
GET /api/v1/threads?agent_id=X
  └── [conversations table] DynamoDBBackend.query(
        PK=USER#u#AGENT#a,
        SK begins_with "THREAD#",
        FilterExpression: type = "thread"
      )
      → returns: list of {session_id, title, updated_at} — lightweight metadata only

READ 2: Load thread turns (on conversation click)
GET /api/v1/threads/{session_id}
  └── [conversations table] DynamoDBBackend.query(
        PK=USER#u#AGENT#a,
        SK begins_with "THREAD#{session_id}#TURN#",
        Limit=10, ScanIndexForward=false
      )
      → returns: last 10 turns, sorted newest-first
      → frontend renders chat immediately

READ 3: Load artifacts (parallel with READ 2)
GET /api/v1/threads/{session_id}/artifacts
  └── [artifacts table] DynamoDBBackend.query(
        PK=USER#u#AGENT#a,
        SK begins_with "THREAD#{session_id}"
      )
      → returns: all artifacts for session (definitions inline or S3 refs)
      → frontend renders artifacts as they arrive

READs 2 and 3 are fired concurrently by the frontend (or by a
single backend endpoint that runs both queries with asyncio.gather).
Wall-clock time = max(read2, read3), not sum.
```

**Graceful degradation:**
- If DynamoDB is unreachable during `save_turn()`, log a warning and continue. The turn exists in Redis hot cache. It will NOT be backfilled.
- If DynamoDB is unreachable during `load_conversation()`, return empty and let Redis serve what it has.
- If DynamoDB is unreachable during artifact save/load, log a warning and return None/empty. The frontend shows a "could not save" notification.

### Edge Cases & Error Handling

1. **DynamoDB item size limit (400KB):** The `S3OverflowManager` prevents this by offloading artifacts > 200KB to S3. Turn data (the `data` field) also goes through overflow check.

2. **Concurrent artifact updates:** DynamoDB `PutItem` is last-writer-wins. Since there's no collaboration and artifacts are per-user, this is acceptable. No optimistic locking needed.

3. **Thread deletion cascade:** Deleting a thread must delete items from both tables: conversations table (`SK begins_with THREAD#{session_id}` — metadata + turns) and artifacts table (`SK begins_with THREAD#{session_id}` — all artifacts). Both are `Query` + `BatchWriteItem` deletes, executed in parallel. S3 objects referenced by `definition_ref` must also be cleaned up.

4. **S3 object orphaning:** If a DynamoDB write succeeds but the S3 upload fails (or vice versa), we get orphaned data. Mitigation: write S3 first, then DynamoDB. If DynamoDB fails, the S3 object is orphaned but harmless (cleaned up by S3 lifecycle policy).

5. **Large DataFrames:** Always go to S3 as Parquet files. The DynamoDB item stores only a preview (first 5 rows, column names, shape, dtypes) and the S3 reference.

6. **TTL implementation:** DynamoDB TTL attribute on each item, set to `updated_at + 6 months`. TTL deletes are eventually consistent (items may linger up to 48h after expiry). S3 objects use a matching lifecycle policy.

7. **Missing artifact references in canvas:** If a canvas block references an artifact that's been deleted (e.g., via TTL), the frontend renders a "deleted artifact" placeholder. The canvas definition is not modified.

---

## Capabilities

### New Capabilities
- `artifact-persistence`: CRUD operations for conversation artifacts (charts, canvas, infographics, dataframes, exports) in DynamoDB + S3.
- `dynamodb-conversation-store`: DynamoDB backend (two tables: `parrot-conversations` for threads+turns, `parrot-artifacts` for artifacts) replacing DocumentDB for persistent storage.
- `s3-overflow-manager`: Transparent large-item offloading to S3 with automated threshold-based routing.
- `artifact-api-endpoints`: REST endpoints for frontend artifact CRUD operations.
- `thread-management-api`: REST endpoints for thread listing, loading, updating, and deletion.

### Modified Capabilities
- `chat-storage`: `ChatStorage` class modified to use `DynamoDBBackend` instead of `DocumentDb`.
- `agent-talk-handler`: `AgentTalk` handler extended to save artifacts after `ask()` and `get_infographic()` calls.
- `infographic-handler`: `InfographicTalk` handler extended to auto-persist generated infographics.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/storage/chat.py` | modifies | Replace `DocumentDb` backend with `DynamoDBBackend` |
| `parrot/storage/models.py` | extends | Add `Artifact`, `ArtifactSummary`, `ThreadMetadata`, `CanvasDefinition` models |
| `parrot/storage/__init__.py` | extends | Export new models and classes |
| `parrot/interfaces/aws.py` | extends | May need DynamoDB-specific client method |
| `parrot/interfaces/file/s3.py` | reuses | S3 overflow uses existing `S3FileManager` |
| `parrot/conf.py` | extends | Add `DYNAMODB_CONVERSATIONS_TABLE`, `DYNAMODB_ARTIFACTS_TABLE`, `DYNAMODB_REGION`, `S3_ARTIFACT_BUCKET` config vars |
| `parrot/handlers/agent.py` | modifies | Wire artifact saving into `ask()` response flow |
| `parrot/handlers/infographic.py` | modifies | Wire artifact saving into `get_infographic()` response flow |
| `parrot/bots/abstract.py` | extends | Add `save_conversation_artifact()`, `get_conversation_artifacts()` convenience methods |
| `parrot/handlers/` (new views) | new | New aiohttp views for thread and artifact CRUD endpoints |
| `parrot/interfaces/documentdb.py` | deprecates | No longer used for chat persistence after migration |

---

## Code Context

### User-Provided Code

```python
# Source: sdd/proposals/sdd-brainstorm-artifact-persistence.md (user-authored proposal)
# DynamoDB two-table key design:
#
# Table: parrot-conversations (threads + turns)
#   PK = "USER#{user_id}#AGENT#{agent_id}"
#   SK = "THREAD#{session_id}"                        → thread metadata
#   SK = "THREAD#{session_id}#TURN#{turn_id}"         → individual turn
#
# Table: parrot-artifacts
#   PK = "USER#{user_id}#AGENT#{agent_id}"
#   SK = "THREAD#{session_id}#{artifact_id}"          → artifact item
```

### Verified Codebase References

#### Classes & Signatures

```python
# From parrot/storage/chat.py:27
class ChatStorage:
    def __init__(self, redis_conversation=None, document_db=None):  # line 30
        self._redis = redis_conversation          # line 35
        self._docdb = document_db                 # line 36

    async def initialize(self) -> None:           # line 44
    async def save_turn(self, *, turn_id, user_id, session_id, agent_id,
                        user_message, assistant_response, output=None,
                        output_mode=None, data=None, code=None,
                        model=None, provider=None, response_time_ms=None,
                        tool_calls=None, sources=None, metadata=None) -> str:  # line 126

…(truncated)…
