---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server]
tags: [memory, conversation-history, chat-storage, event-bus, hydration, composer]
---

# Brainstorm: Durable Conversation Memory — Event-Driven Turn Persistence, Hydration and Rich History

**Date**: 2026-11-12
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: A

> **Rethink note (2026-11-12).** This document replaces the 2026-11-11 version. The
> original brainstorm conflated ChatStorage with agent memory; this version corrects the
> model: **ChatStorage is the eternal audit/persistence tier** (not the agent's working
> memory) and **ConversationHistory is the agent's active conversation thread** (the one
> that gets summarized, bounded and sent to the LLM). They stay separate, connected by
> events and hydration — never merged.

---

## Problem Statement

A user looks at a conversation in the UI and keeps talking to the agent. Today there is
no guarantee that the agent remembers any of what the user is looking at.

1. **Two stores, two lifetimes, two purposes — but no bridge.**
   - **ChatStorage** (`storage/chat.py:25`): the eternal audit/persistence store. Its hot
     tier is a `RedisConversation` with `key_prefix="chat"` and no TTL. Its cold tier is
     a pluggable `ConversationBackend` (sqlite/dynamodb/mongo/postgres), 180-day TTL in
     production. Only AgentTalk writes it, via `save_turn`, as a background task
     (`handlers/agent.py:2807-2846`, `:3060-3097`). **ChatStorage stores conversations
     for reconstruction at any point in time, without summarizing anything.**
   - **ConversationHistory** (`memory/abstract.py:274`): the agent's active conversation
     thread for the current session. It is what gets summarized, limited, compacted and
     sent to the LLM via `render_history`. It lives in whatever `ConversationMemory`
     backend the bot uses (memory/file/redis).
   - **No hydration exists.** `ChatStorage.get_context_for_agent` (`storage/chat.py:613`)
     has no caller outside tests. When a new session starts or a pod restarts, the agent
     starts with an empty ConversationHistory, even though ChatStorage holds the full
     transcript.
2. **AgentTalk reads from one store and writes to another.**
   - On every request with a `session_id`, `handlers/agent.py:1736` creates a fresh
     `RedisConversation()` (prefix `"conversation"`) and passes it as `memory=`.
   - The bot reads history from it: `memory = memory or self.conversation_memory` at
     `bots/base.py:431`, `:830`, `:1326`, `:2069`.
   - But `save_conversation_turn` writes to `self.conversation_memory`
     (`abstract.py:2685`).
   - So a default `memory_type="memory"` agent called over HTTP reads an empty Redis key
     every round. It sees **no prior turns at all**, even inside one pod's lifetime.
3. **ChatStorage stores a degraded version of turns.**
   - The cold tier's `tool_calls` use `getattr(t, "status", "completed")` /
     `getattr(t, "output", None)` (`handlers/agent.py:2827-2834`, `:3077-3085`). But
     `parrot.models.ToolCall` has `result`, `error`, `execution_time`
     (`models/basic.py:23-30`), so every persisted tool call is
     `status="completed"` with `output=None`.
   - FEAT-525 fields (`tool_invocations`, `error`, `token_count`, `state`) are not
     persisted to the cold tier.
   - **We need richer turns in ChatStorage**: full tool-call results, LLM usage stats,
     HTTP call metadata — everything needed to rebuild the conversation exactly.
4. **Old turns are silently forgotten.**
   - FEAT-525 compaction is deterministic only (Stages 0, 0.5 and 1). Past the budget or
     `max_turns`, older turns drop out of the prompt.
   - Stage 2 (LLM summary turns) is reserved and not implemented: `TurnState.SUMMARIZED`
     is never produced (`memory/compaction/models.py:31`), `Stage2CompactionNeededEvent`
     (`events/memory.py:14`) has no subscribers.
5. **HistoryMessage is text-only.**
   - `render_history` (`memory/render.py:143`) produces `HistoryMessage` with
     `role` and `content` (text). Tool calls are appended as text suffixes by compaction
     views. No structured tool_use / tool_result blocks travel to the LLM. This limits
     the agent's ability to recall what tools it used and with what results.
6. **Smaller defects found.**
   - `ask_stream` saves turns without `compaction=` (`bots/base.py:2297`), so streamed
     rounds never update boundary, calibration or `stage2_needed`.
   - `HOT_TTL_HOURS = 48` (`storage/chat.py:20`) is defined and never used.
   - `ChatStorage.delete_turn` deletes only from the cold tier.

## Constraints & Requirements

- **ChatStorage and ConversationHistory stay separate.** ChatStorage is the audit log
  (never summarized, always reconstructable). ConversationHistory is the active working
  thread (summarized, bounded, sent to the LLM).
- **Keep FEAT-524 / FEAT-525 contracts.**
  - The bot owns history; clients stay memory-less.
  - `add_turn` stays the single write path (Stage 0 normalize, 0.5 count, offload).
  - `metadata.compaction` is written atomically with the turn.
  - `PARROT_COMPACTION_DISABLED` / `context_budget=False` keep the plain path.
- **Event-driven persistence.** The bot always emits a turn-completed event. ChatStorage
  subscribes when present. Conversation-less agents (CLI, sub-agents, SDD workers)
  naturally skip persistence when no subscriber exists.
- **Turn timestamps owned by the emitter.** The bot stamps each turn; the receiving store
  never overrides the timestamp. Ordered by timestamp + sequence number, the conversation
  is reconstructable.
- **Hydration on miss, once.** When ConversationHistory has no data for a session,
  hydrate from ChatStorage atomically (only if not already present in Redis). Never
  re-hydrate a session that already has data.
- **Default memory resolves automatically.** Redis when configured (`REDIS_HISTORY_URL`
  is set), in-memory when not. No flag needed per agent.
- **Backend-agnostic.** Uses FEAT-116 `ConversationBackend` (sqlite/postgres/mongo/
  dynamodb).
- **Bounded cost.** Hydration reads at most a budget-sized window. The event bus uses
  Redis Streams when ChatStorage is present.
- **Backwards-safe rollout.** Existing `memory`/`file`/`redis` users keep working.
- **Stage 2 compaction (LLM summarizer) is a follow-up spec.** This brainstorm defines
  where summaries would live (ConversationHistory only, never ChatStorage) and leaves the
  hook points ready.

---

## Options Explored

### Option A: Event-driven turn persistence + hydration + rich history messages (recommended)

Four coordinated pieces, each independently useful:

**Piece 1 — Event-driven turn persistence.**
The bot emits a `TurnCompletedEvent` (new, in `core/events/lifecycle/events/memory.py`)
after every `save_conversation_turn`. The event carries the **raw, pre-normalization**
`ConversationTurn` with all fields. It is published to a `BusCore` instance (not
`EventRegistry.emit`) using the existing `navigator_eventbus` infrastructure:

- **O(1) publish** via `BusCore.publish()` — fire-and-forget from the bot's perspective.
- **Retry with exponential backoff** (3 attempts by default, `retry_base_delay * 2^(n-1)`).
- **DLQ** via `DLQHandler` for terminally failed envelopes (persisted, replayable).
- **Redis Streams backend** (`transport="streams"`) when ChatStorage is configured; the
  bus is not created when no ChatStorage exists (CLI, code, sub-agents).

ChatStorage subscribes to topic `conversation.turn.completed`. Its handler does an
**upsert by `turn_id`** (at-least-once delivery means duplicates). AgentTalk's direct
`save_turn` calls and the injected `RedisConversation()` are removed.

A new `ChatStorageTurn` model replaces the current dict-based turn payload. It carries the
full `ConversationTurn` fields plus handler-side metadata (output_mode, data, code,
sources, tenant). Fields the bot doesn't have today are either moved to the turn (preferred)
or injected into the event by a middleware layer before publish.

**Piece 2 — Automatic memory default and hydration.**
`get_conversation_memory` (`abstract.py:2081`) gains a `"auto"` storage type (the new
default). Resolution: check if `REDIS_HISTORY_URL` (or a Redis connection) is available →
`RedisConversation`; otherwise → `InMemoryConversation`. Explicit `memory_type` overrides.

On a ConversationHistory miss (`get_history` returns None at `bots/base.py:431`, `:830`,
`:1326`, `:2069`), a pluggable `HydrationSource` interface is consulted:

```python
class HydrationSource(ABC):
    async def load_turns(
        self, agent_id: str, user_id: str, session_id: str, max_turns: int
    ) -> Optional[List[ConversationTurn]]:
        ...
```

`ChatStorageHydrationSource` implements it. The bot never imports `ChatStorage` — it
receives an optional `HydrationSource` via dependency injection. CLI and code get `None`.

Hydration writes to Redis atomically (NX — only if key doesn't exist). Two concurrent
first requests race safely: the loser's NX fails, it reads what the winner wrote, and
proceeds. A sequence number per `(agent_id, user_id, session_id)` is assigned by the bot
at turn creation time, monotonically incrementing, stored in the turn. This is the
desambiguator for same-millisecond timestamps.

**Piece 3 — Rich ChatStorage turn model (breaking change).**
`ChatStorageTurn` replaces the current `save_turn` parameter soup:

- Full `ConversationTurn` fields: `tool_invocations` (with `ToolInvocation` objects
  carrying `tool_name`, `input`, `output`, `status`, `error`, `execution_time`),
  `token_count`, `state`, `schema_version`, `metadata.compaction`.
- Handler-enriched fields: `output` (rendered response), `output_mode`, `data`
  (structured payload), `code` (generated code), `sources` (source documents),
  `response_time_ms`, `tenant` (resolved request tenant, FEAT-707).
  Verified fields the handler passes today that the bot does NOT have:
  `output`, `output_mode`, `data`, `code`, `sources`, `response_time_ms`,
  `metadata.tenant`, `metadata.usage`, `metadata.cost_usd`
  (source: `handlers/agent.py:2808-2862` streaming, `:3061-3101` non-streaming).
- LLM usage: `model`, `provider`, `input_tokens`, `output_tokens`, `total_tokens`,
  `cost_usd` (from observability's `CostCalculator`).

A tolerant reader handles old-shape rows (missing fields default to None, `schema_version`
discriminates). The cold-tier `ConversationBackend.put_turn` already takes a `dict`, so
the schema change is in the serialization, not the ABC.

**Piece 4 — Composer: HistoryMessage with structured parts.**
`HistoryMessage` (`memory/render.py:54`) gains an optional `parts` field:

```python
@dataclass(frozen=True)
class MessagePart:
    kind: Literal["text", "tool_use", "tool_result"]
    content: str
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None

@dataclass(frozen=True)
class HistoryMessage:
    role: Literal["user", "assistant"]
    content: str                          # text-only fallback (unchanged contract)
    parts: Optional[List[MessagePart]] = None  # structured when available
    chatbot_id: Optional[str] = None
    turn_id: Optional[str] = None
```

`render_history` populates `parts` from `TurnView.tool_invocations` when present, using
three rendering tiers by turn age (reusing FEAT-525's existing turn states):

- **Recent** (VERBATIM): full tool_use + tool_result parts with complete output.
- **Intermediate** (PRUNED): tool_use + tool_result with preview-only output (the full
  output is recoverable via `read_omitted_content`).
- **Old** (DROPPED): no parts, text-only summary. (With the follow-up Stage 2 spec, these
  become a single `SUMMARIZED` turn.)

**Phase 1 (this spec): neutral text render for all clients.** `_format_history`
(`clients/base.py:1863`) renders `parts` as a text representation:
`[Tool: name(args) → output_preview]`. This is backwards-compatible — every provider sees
well-formed text messages. The `content` field stays the primary contract.

**Phase 2 (follow-up): native provider mapping.** Anthropic, OpenAI and Google clients
override `_format_history` to emit native `tool_use`/`tool_result` blocks from `parts`.
This requires adding a `tool_call_id` to `ToolInvocation` (or synthesizing one).

✅ **Pros:**
- ChatStorage and ConversationHistory stay cleanly separated — each does what it was
  designed for.
- Event-driven: conversation-less agents naturally skip persistence. No flags needed.
- BusCore gives retry+backoff+DLQ for free — better than AgentTalk's current
  fire-and-forget `create_task`.
- Hydration is one-shot and atomic — no repeated reads, no state drift.
- Auto-default memory means most agents get Redis when available without config changes.
- Rich turns in ChatStorage enable full conversation reconstruction including tool results.
- Structured HistoryMessage lets the LLM see what tools were used and with what results,
  while remaining backwards-compatible (text fallback).
- The bot never imports ChatStorage or AgentTalk-specific code.

❌ **Cons:**
- Touches the hottest path (every bot round emits an event, even if nobody listens).
- At-least-once delivery means the ChatStorage subscriber must be idempotent (upsert).
- The in-memory bus queue doesn't survive process death; turns in flight during a deploy
  are lost. Redis Streams covers transient DB failures but not pod crashes.
- Breaking change to ChatStorage turn schema — old rows need a tolerant reader.
- `HistoryMessage.parts` adds complexity to every `_format_history` override (4 clients).
- Needs the `BusCore` bus wired into bot construction via dependency injection.
- Tools that no longer exist in the agent's tool list may cause some providers to reject
  the history — the text fallback handles this.

📊 **Effort:** High (phased; see Recommendation)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-eventbus` ≥ current | `BusCore` with Redis Streams, retry, DLQ | already a dependency |

🔗 **Existing Code to Reuse:**
- `parrot/storage/chat.py` — `ChatStorage` hot/cold wiring, `load_conversation`.
- `parrot/memory/redis.py` — `RedisConversation` (hash layout, CAS append).
- `parrot/storage/backends/*` — `ConversationBackend.put_turn` / `query_turns`.
- `parrot/memory/abstract.py:440-516` — `add_turn` template + `_store_turn`.
- `parrot/memory/compaction/*` — budget, boundary, `stage2_needed`, omission stores.
- `parrot/core/events/lifecycle/events/memory.py` — `Stage2CompactionNeededEvent` (pattern for new event).
- `parrot/memory/render.py:143` — `render_history` (extend with parts).
- `parrot/observability/fanout.py:90` — `setup_event_fanout` (pattern for bus wiring with Redis Streams).
- `parrot/bots/abstract.py:469` — `_init_events(event_bus=)` (bus injection path).

---

### Option B: Direct ChatStorage write from the bot (one write path, no bus)

Make `save_conversation_turn` also write to ChatStorage directly, as a second store. The
bot imports a `PersistenceAdapter` (not ChatStorage itself) that wraps the cold-tier write.
No event bus. Hydration and auto-default memory as in Option A. Rich turns as in Option A.

✅ **Pros:**
- Simpler than an event bus — direct write, guaranteed delivery (or error).
- No DLQ or replay complexity.
- Write ordering is trivial (sequential in the bot's own flow).

❌ **Cons:**
- Every bot round now has TWO awaited writes (ConversationHistory + ChatStorage), adding
  latency to the response path. Making the ChatStorage write fire-and-forget (create_task)
  is exactly what AgentTalk does today and has the same loss problem.
- Conversation-less agents need an explicit flag to skip the ChatStorage write, defeating
  the "no flags needed" goal.
- The bot takes a hard dependency on the persistence adapter being available — CLI and code
  agents would get import errors or need a stub.
- Couples the bot's hot path to cold-tier availability: a DynamoDB timeout slows the
  response (or, if backgrounded, loses the turn).

📊 **Effort:** Medium

🔗 **Existing Code to Reuse:**
- Same as Option A minus the bus infrastructure.

---

### Option C: Keep two stores, bridge read-only (original Option B from v1)

Leave writes as they are. On a miss in the agent's memory, seed from
`ChatStorage.load_conversation`. Fix the AgentTalk mismatch separately. No rich turns.

✅ **Pros:**
- Smallest change; leaves the hot path's write untouched.
- Matches the FEAT-525 follow-up literally.

❌ **Cons:**
- Two write paths stay (bot + AgentTalk), with drift by design.
- Rehydrated history is lossy — ChatStorage lacks tool outputs, errors and FEAT-525 fields.
- Default `memory_type="memory"` agents still lose context per pod.
- No path to rich turn storage.

📊 **Effort:** Low–Medium

🔗 **Existing Code to Reuse:**
- `ChatStorage.get_context_for_agent` / `load_conversation`.

---

## Recommendation

**Option A** is recommended, delivered in phases:

| Phase | Content | Standalone value |
|---|---|---|
| **P0 — Correctness fixes** | (a) AgentTalk stops injecting throw-away `RedisConversation()`. (b) Tool-call serialization uses `ToolCall.result`/`error`/`execution_time`. (c) `ask_stream` passes `compaction=`. (d) Use or remove `HOT_TTL_HOURS`; `delete_turn` also deletes from hot tier. | Bugs in production today |
| **P1 — Event-driven turn persistence** | `TurnCompletedEvent`, `BusCore` wiring, ChatStorage subscriber with upsert, `ChatStorageTurn` model, AgentTalk's `save_turn` removed. | Single source of truth for audit; decoupled |
| **P2 — Auto-default memory + hydration** | `"auto"` memory type, `HydrationSource` interface, `ChatStorageHydrationSource`, atomic NX write, per-session sequence numbers. | Agents survive restarts and multi-pod |
| **P3 — Rich history messages** | `HistoryMessage.parts`, `MessagePart`, `render_history` extension, neutral text render in all `_format_history` overrides. | LLM sees structured tool activity |

**Follow-up specs (out of scope):**
- **Stage 2 compaction (LLM summarizer):** summaries live in ConversationHistory only, never in ChatStorage. The event hook (`Stage2CompactionNeededEvent`) and the `TurnState.SUMMARIZED` enum are already in place.
- **Native provider tool blocks:** Anthropic/OpenAI/Google `_format_history` emits native `tool_use`/`tool_result` from `HistoryMessage.parts`.
- **Durable omission store:** cold-tier `OmissionStore` so `read_omitted_content` survives Redis expiry.

Trade-offs accepted:
- At-least-once delivery (bus) requires idempotent writes — acceptable for an audit store.
- In-memory bus queue may lose turns on pod crash — Redis Streams covers transient failures; a crash during deploy loses at most the in-flight turn, which is the same as today's `create_task` behavior in AgentTalk.
- Breaking change to ChatStorage turn schema — mitigated by a tolerant reader with `schema_version`.

---

## Feature Description

### User-Facing Behavior

- Any conversation the history sidebar lists can be continued with full context. This
  holds after a restart, a deploy, on another pod, and days later (within the cold tier's
  retention).
- Conversations show richer detail: tool calls with their results, LLM usage stats,
  response times.
- Agents that don't need conversation persistence (CLI, code, sub-agents) work unchanged
  — no configuration needed.

### Internal Behavior

1. **Round start.**
   - The bot asks its ConversationMemory for `(chatbot_id, user, session)`.
   - Hit: same as today.
   - Miss AND HydrationSource present: load the most recent turns from ChatStorage (up to
     the agent's budget/max_turns), write them to Redis atomically (NX — only if the key
     doesn't already exist), return the hydrated history.
   - Miss AND no HydrationSource: `create_history` (empty), same as today.
   - A change of `session_id` is a new key, so it naturally triggers hydration.
2. **Render.** `render_context_history` calls `render_history` as today. When
   `TurnView.tool_invocations` are present, `HistoryMessage.parts` is populated with
   structured tool_use/tool_result. `_format_history` renders parts as text (Phase 1).
3. **Round end.**
   - `save_conversation_turn` calls `add_turn(compaction=)` on the ConversationMemory
     (direct, awaited — no change).
   - After the save, the bot publishes `TurnCompletedEvent` to the `BusCore`. The event
     carries the raw turn + handler metadata. This is O(1) and returns immediately.
   - ChatStorage's subscriber receives the event (with retry+backoff), builds the
     `ChatStorageTurn` model, and calls `put_turn` on the cold tier + `save_to_hot` on
     the hot tier. Upsert by `turn_id`.
4. **UI reads.** The chat_interaction / threads handlers keep reading `ChatStorage`. They
   now see richer turns (tool results, usage stats).
5. **Deletion.** Deleting a conversation in the UI deletes both the ChatStorage records
   and the ConversationHistory Redis keys. The delete event propagates through the bus.

### Edge Cases & Error Handling

- **Bus not available (CLI, code, sub-agents).** No `BusCore` is created; no
  `TurnCompletedEvent` is published. The bot works exactly as today.
- **ChatStorage subscriber fails.** Retry with backoff (3 attempts). On exhaustion, the
  envelope goes to the DLQ. The user's response is NOT delayed — the bus is fully
  asynchronous.
- **Cold tier unavailable.** The subscriber logs a warning and the DLQ catches the turn.
  `DLQHandler.replay()` reprocesses when the tier comes back.
- **Hydration race (two first requests for same session).** Both try NX-write to Redis.
  The loser's NX fails silently; it reads what the winner wrote. No data loss.
- **Old-shape cold rows (pre-P1).** The tolerant reader fills missing fields with defaults
  and marks them `schema_version=1`.
- **Multi-worker with in-memory default.** Workers without Redis still lose context on
  restart — this is the same as today. The auto-default gives them Redis when available.
- **Turn still in bus queue at pod crash.** Lost, same as today's `create_task`. Redis
  Streams' consumer groups cover transient backend failures, not process death.
- **Streaming and cancellation.** On client disconnect mid-stream, a partial turn with
  error state is emitted. The subscriber stores it; the next round picks up cleanly.
- **Studio and registry-only hosts.** The bus subscriber is registered at the application
  level (`BotManager.on_startup` or equivalent), not per-bot. `setup_registry_only` gains
  optional bus setup.
- **Backpressure policy.** The bus defaults to `block` (slows the bot when the queue is
  full). For the audit use case, `drop_oldest` is preferable — losing the oldest
  in-flight turn is better than adding latency. This is a config decision.

---

## Capabilities

### New Capabilities
- `event-driven-turn-persistence`: `TurnCompletedEvent` + `BusCore` wiring + ChatStorage
  subscriber with upsert.
- `conversation-hydration`: `HydrationSource` interface + `ChatStorageHydrationSource` +
  atomic NX write to Redis + per-session sequence numbers.
- `auto-memory-default`: `"auto"` storage type that resolves Redis/memory automatically.
- `rich-history-messages`: `HistoryMessage.parts` + `MessagePart` + structured tool
  rendering in `render_history`.
- `chat-storage-turn-model`: `ChatStorageTurn` Pydantic model with full turn payload +
  handler metadata + LLM usage.

### Modified Capabilities
- `conversation-history-ownership` (FEAT-524): hydration path added; ConversationHistory
  remains the sole owner of the active thread.
- `per-turn-conversation-compaction` (FEAT-525): streaming path commits compaction;
  `render_history` populates `parts` from `TurnView.tool_invocations`.
- AgentTalk (`handlers/agent.py`): injected `RedisConversation()` removed; direct
  `save_turn` calls removed; handler-side metadata routed through the event.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/core/events/lifecycle/events/memory.py` | extends | new `TurnCompletedEvent` |
| `parrot/memory/render.py` | modifies | `HistoryMessage.parts`, `MessagePart` |
| `parrot/memory/abstract.py` | extends | `ConversationTurn` gains sequence number |
| `parrot/bots/abstract.py` | modifies | auto-default memory, bus publish, `HydrationSource` injection |
| `parrot/bots/base.py` | modifies | hydration on miss in `get_history or create_history` |
| `parrot/storage/chat.py` | modifies | new `ChatStorageTurn` model; subscriber mode |
| `parrot/storage/backends/*` | unchanged | `put_turn` already takes a dict |
| `parrot/clients/base.py` | modifies | `_format_history` handles `parts` (text render) |
| `ai-parrot-server/handlers/agent.py` | modifies | remove `RedisConversation()` injection and `save_turn` |
| `ai-parrot-server/manager/manager.py` | modifies | bus setup in `on_startup` and `setup_registry_only` |
| All `_format_history` overrides (bedrock, google, jev) | modifies | handle `parts` text fallback |
| Agent Studio (navigator-agent-studio) | depends on | bus subscriber replaces direct `save_turn` |

---

## Code Context

### Verified Codebase References (dev @ `a09aa93def`, 2026-11-12)

#### Classes & Signatures
```python
# packages/ai-parrot/src/parrot/memory/abstract.py
class ConversationTurn:                    # :102
class ConversationHistory:                 # :274
class ConversationMemory(ABC):             # :335
    async def add_turn(...)                # :440 (template method)
    async def _store_turn(...)             # :516 (abstract, custom backends implement this)
    async def get_history(...)             # :428
    async def create_history(...)          # :421

# packages/ai-parrot/src/parrot/memory/redis.py
class RedisConversation(ConversationMemory):  # :42

# packages/ai-parrot/src/parrot/memory/mem.py
class InMemoryConversation(ConversationMemory):  # :9

# packages/ai-parrot/src/parrot/memory/file.py
class FileConversationMemory(ConversationMemory):  # :13

# packages/ai-parrot/src/parrot/memory/render.py
class HistoryMessage:                       # :54 — role, content, chatbot_id, turn_id (text-only)
def render_history(history, *, max_turns=None, current_chatbot_id=None,
                   include_other_agents=True, other_agent_label="[agent:{chatbot_id}]"
                   ) -> List[HistoryMessage]   # :143

# packages/ai-parrot/src/parrot/memory/compaction/models.py
class TurnState(str, Enum):                 # :31 — RAW, PRUNED, SUMMARIZED (SUMMARIZED never produced)
class ToolInvocation:                       # :46 — tool_name, input, output, status, error, execution_time
class CompactionState:                      # :228 — boundary_turn_id, stage2_needed

# packages/ai-parrot/src/parrot/storage/chat.py
HOT_TTL_HOURS = 48                          # :20 (unused)
class ChatStorage:                          # :25
    async def save_turn(self, *, turn_id, user_id, session_id, agent_id, ...)  # :106
    async def load_conversation(self, user_id, session_id, agent_id=None, limit=50)  # :281
    async def get_context_for_agent(self, user_id, session_id, agent_id=None, max_turns=10, model="claude")  # :613 (no callers)

# packages/ai-parrot/src/parrot/storage/backends/base.py
class ConversationBackend(ABC):             # :15
    async def put_turn(self, user_id, agent_id, session_id, turn_id, data: dict)  # :82
    async def query_turns(self, user_id, agent_id, session_id, ...)               # :93

# packages/ai-parrot/src/parrot/models/basic.py
class ToolCall(BaseModel):                  # :23 — id, name, arguments, result=None, error=None, execution_time=None

# packages/ai-parrot/src/parrot/core/events/lifecycle/events/memory.py
class Stage2CompactionNeededEvent(LifecycleEvent):  # :14 (no subscribers)

# packages/ai-parrot/src/parrot/bots/abstract.py
self.memory_type: str = kwargs.get("memory_type", "memory")          # :616
def get_conversation_memory(self, storage_type="memory", **kwargs)   # :2081 — memory | file | redis
async def save_conversation_turn(self, user_id, session_id, turn, *, compaction=None)  # :2685
self._init_events(event_bus=event_bus, forward_to_global=True)       # :469

# packages/ai-parrot/src/parrot/bots/base.py
memory = memory or self.conversation_memory     # :431, :830, :1326, :2069
await self.save_conversation_turn(user_id, session_id, turn)  # :2297 (ask_stream, no compaction=)

# packages/ai-parrot-server/src/parrot/handlers/agent.py
memory = RedisConversation()   # :1736 (per request, prefix "conversation")
# save_turn background tasks: :2807-2846 (stream), :3060-3097 (json)
# tool_calls via getattr(t,"status"/"output") :2827-2834, :3077-3085

# packages/ai-parrot-server/src/parrot/manager/manager.py
def setup_registry_only(...)   # :3130 (no ChatStorage, no bus)

# packages/ai-parrot/src/parrot/clients/base.py
def _format_history(self, history: Sequence[HistoryMessage]) -> List[Dict[str, Any]]  # :1863
```

#### Verified Imports
```python
from navigator_eventbus.lifecycle.registry import EventRegistry  # installed dep (not in git)
from navigator_eventbus.core import BusCore                      # installed dep — retry, backoff, DLQ
from navigator_eventbus.dlq import DLQHandler                    # installed dep — persistent dead-letter
from navigator_eventbus import EventBus                          # installed dep — high-level wrapper
from parrot.conf import REDIS_HISTORY_URL                        # parrot/conf.py
```

#### Key Attributes & Constants
- `ChatStorage._redis` = `RedisConversation(key_prefix="chat")` — hot tier
- `REDIS_HISTORY_URL` — Redis connection for conversation memory (`parrot/conf.py`)
- `PARROT_STORAGE_BACKEND` — cold tier selection (default `sqlite`; `dynamodb` in prod)
- `DYNAMODB_CONVERSATIONS_TABLE` — default `parrot-conversations`, 180-day item TTL
- `PARROT_EVENT_FANOUT_REDIS_URL` — existing config for the observability fan-out bus
- `EventBus(transport="streams", publish_only=True, ...)` — pattern in `fanout.py:97`
- Backpressure policies: `block` (default), `drop_oldest`, `reject`

### Does NOT Exist (Anti-Hallucination)
- ~~A `chat_storage` or `auto` `memory_type`~~. The factory at `:2081` knows only `memory`, `file`, `redis`.
- ~~`TurnCompletedEvent`~~. Does not exist in `core/events/`.
- ~~Any producer of `TurnState.SUMMARIZED`~~ or subscriber of `Stage2CompactionNeededEvent`.
- ~~Any caller of `ChatStorage.get_context_for_agent`~~ outside tests.
- ~~`ToolCall.status` / `ToolCall.output`~~ on `parrot.models.ToolCall` (fields are `result`, `error`).
- ~~A `HydrationSource` interface~~. Does not exist.
- ~~A `ChatStorageTurn` model~~. Does not exist.
- ~~`HistoryMessage.parts`~~. The dataclass has only `role`, `content`, `chatbot_id`, `turn_id`.
- ~~A `BusCore` instance wired to regular bots~~. Only the autonomous orchestrator and
  observability fan-out use `EventBus` today; AgentTalk bots have no bus.
- ~~A global env var for `memory_type`~~.
- ~~A spec, proposal or active task for this feature~~ (searched `sdd/`, task indexes and
  remote branches on 2026-11-12).

---

## Parallelism Assessment

- **Internal parallelism:** P0 items (a)–(d) are independent small fixes. P1–P4 have
  dependencies: P1 (event bus) is the foundation; P2 (hydration) depends on P1 for the
  ChatStorage turn model; P3 (rich turns) is independent of P1/P2 but shares
  `render_history`; P4 (composer parts) depends on P3.
  In practice: P0 can be a brief; P1 and P2 are sequential; P3 can run in parallel with
  P2 if `render_history` changes are coordinated.
- **Cross-feature independence:**
  - FEAT-571 (memory-dynamics) explicitly excludes history/compaction; no overlap.
  - FEAT-538 task recall touches `_maybe_inject_task_recall`; P3/P4 must coexist with it.
  - FEAT-525 Stage 2 follow-up builds on this spec's hooks.
  - Agent Studio FEAT-013 (other repo) consumes P1.
- **Recommended isolation:** per-spec. P0 can be its own brief ahead of the rest.
- **Rationale:** P0 fixes live bugs and should not wait. P1–P4 share enough surface that
  sequential execution in one worktree avoids merge conflicts.

---

## Open Questions

- [x] Q1 — Should ChatStorage become the agent's memory, or stay separate? — *Owner: Jesus Lara*: **Stay separate.** ChatStorage is the eternal audit log; ConversationHistory is the active working thread. Connected by events and hydration, never merged.
- [x] Q2 — Who persists turns to ChatStorage? — *Owner: Jesus Lara*: **Event-driven.** The bot emits a `TurnCompletedEvent` to a `BusCore`; ChatStorage subscribes. No flags needed for conversation-less agents.
- [x] Q3 — How does the composer build the history for the LLM? — *Owner: Jesus Lara*: **Conversation stays as messages (`history=`, FEAT-524).** HistoryMessage gains structured `parts` for tool calls. Phase 1: neutral text render. Phase 2 (follow-up): native provider blocks.
- [x] Q4 — How much is re-hydrated from ChatStorage on a miss? — *Owner: Jesus Lara*: **Budget-sized window**, only if the key doesn't already exist in Redis (NX). One-shot, at first access or session change.
- [x] Q5 — Does Stage 2 compaction (LLM summarizer) enter this spec? — *Owner: Jesus Lara*: **No — follow-up spec.** Summaries live in ConversationHistory only, never ChatStorage.
- [x] Q6 — How do we guarantee delivery to ChatStorage? — *Owner: Jesus Lara*: **BusCore with Redis Streams** when ChatStorage is present. Retry+backoff+DLQ. At-least-once; subscriber upserts by `turn_id`.
- [x] Q7 — What is the default `memory_type`? — *Owner: Jesus Lara*: **`"auto"`** — Redis when `REDIS_HISTORY_URL` is set, in-memory when not.
- [ ] Q8 — Should P0 ship first as an independent fix? Verify finding 2 at runtime first. — *Owner: Jesus Lara*
- [ ] Q9 — Key alignment: AgentTalk uses `agent_name` as `agent_id`, the bot uses `memory_key_id`. Are they always equal? — *Owner: Jesus Lara*
- [ ] Q10 — Hot-tier TTL: use `HOT_TTL_HOURS` (48h) once hydration exists, or keep no TTL? — *Owner: Jesus Lara*
- [ ] Q11 — Backpressure policy for the audit bus: `drop_oldest` (lose oldest in-flight, don't slow the bot) or `block` (guarantee delivery, add latency when full)? — *Owner: Jesus Lara*
- [ ] Q12 — Handler-side metadata (output_mode, data, code, sources, tenant): move into `ConversationTurn` (preferred) or inject via event middleware? — *Owner: Jesus Lara*
- [ ] Q13 — Stage 2 rendering: when the follow-up adds `SUMMARIZED` turns, should they render as an assistant-side context block, a system-adjacent block, or a pseudo user/assistant pair? Must not break FEAT-524's strict alternation. — *Owner: Jesus Lara*
