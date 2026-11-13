---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server]
tags: [memory, conversation-history, chat-storage, event-bus, hydration, composer]
docs:
  policy: required
  pages:
    - wiki/memory/durable-conversation-memory.md
    - wiki/memory/conversation-history-ownership.md
    - wiki/memory/per-turn-conversation-compaction.md
    - wiki/stores/storage-backends.md
  api_modules:
    - parrot.memory.persistence
    - parrot.memory.hydration
    - parrot.memory.parts
    - parrot.storage.errors
    - parrot.storage.turn_bus
    - parrot.storage.hydration
    - parrot.storage.backfill
---

# Feature Specification: Durable Conversation Memory — Event-Driven Turn Persistence, Hydration and Rich History

**Feature ID**: FEAT-886
**Date**: 2026-11-13
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.2.0

---

## 1. Motivation & Business Requirements

### Problem Statement

A user looks at a conversation in the UI and keeps talking to the agent. Today there is
no guarantee that the agent remembers any of what the user is looking at.

1. **Two stores, two lifetimes, two purposes — but no bridge.**
   - **ChatStorage** (`storage/chat.py:25`) is the eternal audit/persistence store: a hot
     tier (`RedisConversation(key_prefix="chat")`, no TTL) and a cold tier (a pluggable
     `ConversationBackend`, 180-day TTL in production). Only AgentTalk writes it, via
     `save_turn`, as a background task. It stores conversations for reconstruction at any
     point in time, without summarizing anything.
   - **ConversationHistory** (`memory/abstract.py:274`) is the agent's active thread for
     the current session: what gets summarized, limited, compacted and sent to the LLM.
   - **No hydration exists.** `ChatStorage.get_context_for_agent` (`storage/chat.py:613`)
     has no caller outside tests. After a restart or on a new pod the agent starts with
     an empty history even though ChatStorage holds the full transcript.
2. **AgentTalk reads from one store and writes to another.** On every request with a
   `session_id`, `handlers/agent.py:1736` creates a fresh `RedisConversation()` and passes
   it as `memory=`. The bot reads history from it (`bots/base.py:431`, `:830`, `:1326`,
   `:2069`) but `save_conversation_turn` writes to `self.conversation_memory`. A default
   `memory_type="memory"` agent called over HTTP therefore sees no prior turns at all.
3. **ChatStorage stores a degraded version of turns.** The handler serializes tool calls
   with `getattr(t, "status", "completed")` / `getattr(t, "output", None)`
   (`handlers/agent.py:2830-2831`, `:3083-3084`), but `parrot.models.ToolCall` has
   `result`, `error`, `execution_time` — so every persisted tool call is
   `status="completed"`, `output=None`. FEAT-525 fields (`tool_invocations`, `error`,
   `token_count`, `state`) never reach the cold tier.
4. **Old turns are silently forgotten.** FEAT-525 compaction is deterministic only; past
   the budget, older turns drop out of the prompt. Stage 2 (LLM summaries) is reserved.
5. **HistoryMessage is text-only.** `render_history` (`memory/render.py:143`) emits
   `role` + `content`; tool activity travels as a text suffix with no structure.
6. **Smaller defects.** `ask_stream` saves turns without `compaction=`
   (`bots/base.py:2297`); `HOT_TTL_HOURS = 48` (`storage/chat.py:20`) is never used;
   `ChatStorage.delete_turn` deletes only from the cold tier.

### Goals

- **G1 — Stores stay separate.** ChatStorage is the audit log (never summarized, always
  reconstructable); ConversationHistory is the working thread. They are connected by
  events and hydration only.
- **G2 — Event-driven persistence.** The bot publishes a turn-completed event after every
  saved turn; ChatStorage subscribes when present. Conversation-less agents (CLI,
  sub-agents, SDD workers) skip persistence with no flag.
- **G3 — Reliable delivery.** At-least-once delivery over Redis Streams with retry,
  backoff, DLQ and a durable outbox; backends raise on failed writes; the subscriber
  upserts by `turn_id`.
- **G4 — Emitter-owned ordering.** The bot stamps each turn with a UTC timestamp and a
  shared monotonic sequence; no store overrides them.
- **G5 — Hydration on miss, once.** On a ConversationHistory miss the bot hydrates a
  budget-sized newest window from ChatStorage and installs it atomically (NX).
- **G6 — Automatic memory default.** `memory_type="auto"` selects Redis only with explicit
  history configuration or a host-injected connection; otherwise in-memory.
- **G7 — Deletion wins.** Durable tombstones fence writes, reads, hydration, retries and
  DLQ replay.
- **G8 — Rich turns.** ChatStorage persists the full turn: tool invocations with results,
  LLM usage, presentation fields, tenant.
- **G9 — Structured history.** `HistoryMessage` carries optional budgeted `parts`; every
  client still receives one canonical text rendering (Phase 1).
- **G10 — Fix the production defects** listed in Problem Statement items 2, 3 and 6.
- **G11 — Keep FEAT-524 / FEAT-525 contracts**: the bot owns history, clients stay
  memory-less, `add_turn` is the single write path, `metadata.compaction` is written
  atomically with the turn, and the disabled-compaction path is byte-identical.

### Non-Goals (explicitly out of scope)

- **Stage 2 compaction (LLM summarizer).** Follow-up spec. Summaries will live in
  ConversationHistory only, never in ChatStorage. No `TurnState.SUMMARIZED` producer and
  no `Stage2CompactionNeededEvent` subscriber is added here.
- **Native provider tool blocks.** Emitting `tool_use` / `tool_result` blocks from
  `HistoryMessage.parts` in `_format_history` is a follow-up (needs a `tool_call_id` on
  `ToolInvocation`).
- **Durable omission store.** A cold-tier `OmissionStore` is a follow-up.
- **Merging the two stores, or a direct ChatStorage write from the bot.** Both were
  rejected in the brainstorm — see `sdd/proposals/durable-conversation-memory.brainstorm.md`
  Options B and C.
- **Re-keying ChatStorage.** ChatStorage stays keyed by agent name (see §2 "Identity").

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:eff9af9a20d1f217511a6bff64834d5dd8732f23f0aa59747e9c293c2f437a82 evaluation_digest=sha256:b879dc9f650d1978b52dc24c973236dd34f2ac310cee13832998b362d10e495a rules_version=1 status=pass -->

No eligible decisions govern subsystems: auth, bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools

## 2. Architectural Design

### Overview

Option A of the brainstorm, delivered as four coordinated pieces plus the correctness
fixes. All of it ships in this one spec; the correctness fixes are Module 1 and have no
dependencies, so they land first.

**User-facing behavior**

- A retained, non-deleted conversation continues with its newest budget-sized context
  after a restart, a deploy or a change of pod, once its chronological index is ready.
  Older dropped turns are not summarized in this phase.
- Conversations show richer detail: tool calls with results, LLM usage, response times.
- Agents that need no persistence (CLI, code, sub-agents) work unchanged, unconfigured.

**Piece 0 — Correctness fixes.** AgentTalk stops injecting a throw-away
`RedisConversation()`; `ask_stream` passes `compaction=`; `ChatStorage.delete_turn` also
deletes from the hot tier. The degraded tool-call serialization disappears with the
handler's `save_turn` calls (Piece 1), because the stored turn is then built from
`ToolInvocation` objects.

**Piece 1 — Event-driven turn persistence.** After `add_turn` succeeds,
`save_conversation_turn` hands the **raw, pre-normalization** turn to an optional
`TurnPublisher`. The publisher wraps a `navigator_eventbus` bus and publishes one
envelope on topic `conversation.turn.completed`. It is **not** emitted through
`self.events` (`EventRegistry`): the payload contains conversation content and must not
reach the observability fan-out.

- The bus is a `navigator_eventbus.EventBus(transport="streams", outbox=...)`, built the
  way `observability/fanout.py:97` builds its bus but with a consumer (not
  `publish_only`). `**bus_options` reach `BusCore.__init__`, which provides retry with
  exponential backoff (3 attempts), `on_dlq`, and the relay.
- **Backpressure: durable outbox + `block`.** Publish writes to the `SqliteOutbox` first,
  so the request path is not slowed by the queue and an in-flight turn survives a pod
  crash; `block` applies only to the relay. Each pod needs a writable outbox directory.
- The bus exists only where ChatStorage does. With no publisher the bot does nothing
  extra — no event object is even built.
- ChatStorage subscribes at application level. Its handler builds a `ChatStorageTurn` and
  upserts it by `turn_id` in the cold tier, then in the hot tier. It acknowledges only
  after both writes; any failure propagates to the bus (retry → DLQ). A permanent payload
  error is routed to terminal failure handling, never swallowed.
- **Backend failure contract.** `put_turn` returns only after a durable write or raises a
  typed `StorageError`; a disconnected backend raises. `ConversationDynamoDB.put_turn`
  today returns silently when disconnected and swallows `ClientError` /
  `BotoCoreError`; the SQLite, Postgres and Mongo backends return silently when
  disconnected. All four change.
- AgentTalk's direct `save_turn` calls are removed, and `ChatStorage.save_turn` is
  replaced by `ChatStorage.store_turn(ChatStorageTurn)` (hard cut).
- **AgentTalk owns no persistence (hard cut).** The HTTP handler never writes to
  ChatStorage or to any `ConversationMemory`, and never serializes turns or tool calls —
  on the success, error and streaming paths alike. The bot is the only writer of
  conversation state (`add_turn`) and the only emitter of the turn event; a partial turn
  from a stream disconnect is saved by the bot. The server keeps only UI reads and
  deletion through the `ChatStorage` API (`chat_interaction` / `threads`) and the bus
  lifecycle in `BotManager`.

**Piece 2 — Automatic memory default and hydration.**

- `get_conversation_memory` gains `"auto"`, the new default `memory_type`. Resolution: a
  host-injected history Redis connection, or an **explicitly configured**
  `REDIS_HISTORY_URL`, selects `RedisConversation`; otherwise `InMemoryConversation`. An
  explicit `memory_type` still wins. `parrot.conf` always synthesizes `REDIS_HISTORY_URL`
  from host/port defaults, so a separate signal, `REDIS_HISTORY_EXPLICIT`, is captured
  before defaults apply. The factory never probes a connection and never infers from URL
  truthiness. Once Redis is selected, a connection failure surfaces instead of silently
  splitting history into local memory.
- On a history miss the bot consults an optional injected `HydrationSource`. The bot
  never imports `ChatStorage`. `None` means "an active session with no retained turns";
  backend failure, deleted session and index-not-ready are distinct typed errors and are
  never converted to `None` or an empty list.
- **Chronological query contract.** A dedicated backend operation selects by
  emitter-owned UTC timestamp, then sequence, then `turn_id` as the deterministic
  tie-breaker; applies `limit` in descending order **at the backend**; and returns the
  window ascending. SQL backends get a composite index and `ORDER BY ... DESC LIMIT`;
  Mongo an equivalent indexed query; DynamoDB a chronological companion item per turn in
  the same partition, written transactionally with the canonical ID-addressed turn and
  the deletion guard.
- **Legacy backfill** runs as a separate, resumable, batched tool. It uses stored
  timestamps, sequence `0` when missing, and `turn_id` for ties; it never invents
  chronology. A session with missing or invalid timestamps stays unready. Until a
  session's index is ready, reads return an explicit not-ready outcome.
- **Guarded install.** Hydration stages the imported turns through the `add_turn`
  normalization / count / offload steps, then installs the complete history atomically
  and only if absent (NX). Of two racing first requests, the loser reads the winner's
  history. File and in-memory backends get the same guarded initialization within their
  own concurrency scope.
- **Sequence allocation.** The bot obtains a monotonic sequence per
  `(agent, user, session)` from a shared atomic allocator before publishing. After Redis
  loss the allocator recovers from the durable maximum. Timestamp and sequence are
  immutable across retries; gaps are allowed.

**Piece 3 — Rich ChatStorage turn model.** `ChatStorageTurn` (Pydantic v2) carries the
full `ConversationTurn` plus a `TurnPresentation` and usage. **The bot builds the
presentation from the `AIMessage` it already holds** (output, data, code, sources, model,
provider, usage, cost) plus the bound request tenant and its own response timer; the
handler passes only `output_mode` and the client `turn_id` into `ask()`.
`ConversationTurn` itself stays lean, so working memory never stores rendered output. A
tolerant reader fills missing fields on old rows and marks them `schema_version=1`.

**Piece 4 — Composer: structured parts.** `MessagePart` lives in a neutral memory
module. `TurnView` gains immutable optional `parts`; `compact_history` and the prune
policies produce the already-budgeted parts together with their canonical text. The
renderer never recovers raw invocations after the budget decision.

- **RAW**: parts keep only the tool content allowed by existing activity limits and
  write-time offload rules.
- **PRUNED**: parts hold the approved preview / omission notices and preserved errors.
- **Dropped**: no view, message, parts or summary is emitted.

Phase 1 (this spec) is a neutral text render: one canonical formatter renders the parts
into the assistant content during compaction, the token counter measures exactly that
text, and `render_history` carries `parts` alongside the already-rendered `content`.
Every `_format_history` implementation consumes `content` once and must not append parts
again. With compaction disabled the output is byte-identical to today and `parts` is
unset.

**Identity (resolves brainstorm Q9).** The two stores use different agent keys, and they
are not always equal: AgentTalk keys ChatStorage by `agent.name`
(`handlers/agent.py:1593`), while the bot keys history by `memory_key_id`, which is the
explicit `chatbot_id` when one exists (`bots/abstract.py:2258`) — a UUID for a DB-loaded
`Chatbot`. The event therefore carries **both** `agent_name` and `chatbot_id`.
ChatStorage stays keyed by `agent_name` (UI contract and existing rows unchanged).
Hydration queries by `agent_name` and installs under `memory_key_id`.

**Deletion.** ChatStorage commits a durable tombstone for the canonical conversation
identity before acknowledging a delete, then clears turns, chronological companions and
every configured working-memory backend (omission data included). A delete event is
published for idempotent cleanup retries; the event is not the deletion authority.
Tombstones live outside transcript TTL and cascade deletion, are retained indefinitely,
and session IDs are not reused. Cold upserts and tombstone creation are serialized
transactionally per conversation. Subscribers, DLQ replay, backfill and hydration reject
tombstoned identities. Hydration rechecks the guard after installation. If the guard
cannot be checked the bot fails closed. Individual turn deletion uses turn-scoped
tombstones.

### Component Diagram

```
                    ask() / ask_stream()
                           │
        ┌──────────────────┴───────────────────┐
        ▼ round start                          ▼ round end
 _load_or_hydrate_history            save_conversation_turn
        │                                      │
        │ hit ──────────────► render           ├─► ConversationMemory.add_turn   (awaited, unchanged)
        │                                      │
        │ miss                                 └─► TurnPublisher.publish         (optional)
        ▼                                                │  SqliteOutbox → Redis Streams
 HydrationSource (optional)                              ▼
        │  guard check · ordered window        ChatStorage.handle_turn_completed
        ▼                                                │  retry · backoff · DLQ
 ConversationMemory.install_history (NX)                 ├─► ConversationBackend.put_turn   (fenced upsert)
                                                         └─► RedisConversation.upsert_turn  (hot tier)

 ChatStorageHydrationSource ──► ConversationBackend.query_turn_window / is_deleted / get_index_state
 parrot.storage.backfill     ──► ConversationBackend.backfill_batch / mark_index_ready
 chat_interaction / threads handlers ──► ChatStorage (reads, delete_conversation, delete_turn)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/core/events/lifecycle/events/memory.py` | extends | new `TurnCompletedEvent` payload type |
| `parrot/memory/abstract.py` | extends | `ConversationTurn.sequence`, `install_history`, UTC timestamps |
| `parrot/memory/redis.py`, `mem.py`, `file.py` | modifies | guarded atomic install, `upsert_turn` (Redis) |
| `parrot/memory/render.py` | modifies | `HistoryMessage.parts` |
| `parrot/memory/compaction/models.py`, `compact.py`, `policies.py` | modifies | `TurnView.parts`, canonical text, token accounting |
| `parrot/conf.py` | modifies | `REDIS_HISTORY_EXPLICIT`, turn-bus settings |
| `parrot/bots/abstract.py` | modifies | `"auto"` memory, publisher / hydration injection, publish after save |
| `parrot/bots/base.py` | modifies | hydration on miss at four call sites; `ask_stream` commit |
| `parrot/storage/chat.py` | modifies | `store_turn`, subscriber, deletion protocol |
| `parrot/storage/backends/*` | modifies | raise on failed writes, ordered window, tombstones, index state |
| `parrot/storage/instrumented.py` | modifies | delegate the new backend operations |
| `parrot/clients/base.py` and the bedrock / google / jev `_format_history` overrides | validates | tests only — consume canonical `content` exactly once |
| `ai-parrot-server` `handlers/agent.py` | modifies | drop `RedisConversation()` injection and `save_turn` calls |
| `ai-parrot-server` `manager/manager.py` | modifies | bus setup in `on_startup` and `setup_registry_only`; injection in `add_bot` |
| `ai-parrot-server` `handlers/chat_interaction.py`, `threads.py` | uses | unchanged call sites; new deletion semantics behind `ChatStorage` |
| Agent Studio (other repo) | depends on | consumes the bus subscriber instead of `save_turn` |

### Data Models

```python
# parrot/memory/parts.py
@dataclass(frozen=True)
class MessagePart:
    kind: Literal["text", "tool_use", "tool_result"]
    content: str
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None      # always None in Phase 1

# parrot/memory/persistence.py
class TurnPresentation(BaseModel):
    output: Any = None
    output_mode: Optional[str] = None
    data: Any = None
    code: Optional[str] = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    response_time_ms: Optional[int] = None
    tenant: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    cost_usd: Optional[float] = None

# parrot/storage/models.py
class ChatStorageTurn(BaseModel):
    schema_version: int = 2                 # 1 = legacy row read by the tolerant reader
    turn_id: str
    user_id: str
    session_id: str
    agent_id: str                           # agent NAME — the ChatStorage key
    chatbot_id: Optional[str] = None        # the bot's memory_key_id
    timestamp: datetime                     # emitter-owned, UTC-aware
    sequence: int = 0
    user_message: str
    assistant_response: str
    context_used: Optional[str] = None
    tools_used: List[str] = Field(default_factory=list)
    tool_invocations: List[Dict[str, Any]] = Field(default_factory=list)   # ToolInvocation.to_dict()
    error: Optional[str] = None
    token_count: Optional[Dict[str, Any]] = None
    state: str = "raw"
    norm_version: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)                 # incl. "compaction"
    presentation: TurnPresentation = Field(default_factory=TurnPresentation)
```

### New Public Interfaces

```python
# parrot/memory/persistence.py
class TurnPublisher(Protocol):
    async def publish(self, event: TurnCompletedEvent) -> None: ...

# parrot/memory/hydration.py
class HydrationSource(ABC):
    async def load_turns(self, agent_name: str, user_id: str, session_id: str, max_turns: int
                         ) -> Optional[List[ConversationTurn]]: ...
    async def is_deleted(self, agent_name: str, user_id: str, session_id: str) -> bool: ...
    async def max_sequence(self, agent_name: str, user_id: str, session_id: str) -> int: ...

# parrot/storage/turn_bus.py
async def setup_turn_persistence(chat_storage: ChatStorage, *, bus: Any = None) -> TurnPersistence: ...
async def shutdown_turn_persistence(handle: TurnPersistence) -> None: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Correctness fixes | yes | three exact edit sites, behavior fixed below | — |
| M2: Turn event and publisher | yes | models, topic and publisher signatures fixed | — |
| M3: `ChatStorageTurn` model | yes | field list and tolerant-reader rules fixed | — |
| M4: Backend contract | yes | ABC signatures and error types fixed | — |
| M5: SQLite backend | yes | columns, index and SQL ordering fixed | — |
| M6: Postgres backend | yes | same contract as M5 in asyncpg | — |
| M7: Mongo backend | yes | index keys and transaction rule fixed | — |
| M8: DynamoDB backend | no | — | companion-item key layout and `TransactWriteItems` composition need a design pass against table limits |
| M9: ChatStorage subscriber and deletion | no | — | ack / retry / tombstone ordering is the core correctness logic |
| M10: Turn bus setup | yes | mirrors `observability/fanout.py`; settings fixed | — |
| M11: Backfill tool | yes | batch contract fixed by M4 | — |
| M12: Auto memory default | yes | resolution table fixed | — |
| M13: Hydration core | no | — | staged install + pending-state merge is a design-sensitive protocol |
| M14: `ChatStorageHydrationSource` | yes | pure translation of M4 errors to M13 errors | — |
| M15: Bot integration | no | — | touches the hottest path and four entry points |
| M16: Rich parts | no | — | budget accounting and byte-identity constraints |
| M17: Server wiring | yes | hook points and call shapes fixed | — |
| M18: Documentation | yes | page list fixed in §10 | — |

### Module 1: Correctness fixes (P0)
- **Path**: `packages/ai-parrot/src/parrot/bots/base.py`,
  `packages/ai-parrot-server/src/parrot/handlers/agent.py`,
  `packages/ai-parrot/src/parrot/storage/chat.py`
- **Responsibility**:
  (a) Remove the per-request `RedisConversation()` at `handlers/agent.py:1736`; the
  handler passes no `memory=`, so the bot reads and writes the same store.
  (b) `ask_stream` builds its commit with `build_compaction_commit` and passes
  `compaction=commit` on the successful save at `bots/base.py:2297` (the partial-save
  on error keeps `compaction=None`).
  (c) `ChatStorage.delete_turn` also removes the turn from the hot tier.
  (d) `HOT_TTL_HOURS` is read from the new setting `CHAT_HOT_TTL_HOURS` and passed as
  `history_ttl` to the hot-tier `RedisConversation`; the default is `48` hours (§8 Q10),
  and `0` disables the TTL.
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/storage/chat.py  (modifies :578)
  async def delete_turn(
      self, session_id: str, turn_id: str,
      user_id: Optional[str] = None, agent_id: Optional[str] = None,
  ) -> bool:  # verified: storage/chat.py:578
      """Delete one turn from the cold tier AND the hot tier.

      Returns True when the cold tier deleted it; a hot-tier failure is logged and retried
      by the M9 cleanup path, never reported as success on its own.
      """
  ```

### Module 2: Turn event, ordering fields and publisher
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/events/memory.py`,
  `packages/ai-parrot/src/parrot/memory/abstract.py`,
  `packages/ai-parrot/src/parrot/memory/persistence.py` (new)
- **Responsibility**: the event payload, the emitter-owned ordering fields on the turn,
  and the publisher that turns an event into a bus envelope.
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/memory/abstract.py  (modifies :102)
  @dataclass
  class ConversationTurn:  # verified: memory/abstract.py:102
      sequence: Optional[int] = None
      """Emitter-owned monotonic sequence within (agent, user, session); None on legacy turns.
      Round-trips through to_dict()/from_dict(); from_dict() tolerates its absence."""

  # packages/ai-parrot/src/parrot/core/events/lifecycle/events/memory.py  (modifies)
  @dataclass(frozen=True)
  class TurnCompletedEvent(LifecycleEvent):  # LifecycleEvent verified: navigator_eventbus/lifecycle/base.py
      """One saved conversation turn, raw and pre-normalization.

      Published to the turn bus only; never passed to EventRegistry.emit().
      """
      agent_name: str = ""
      chatbot_id: str = ""
      user_id: str = ""
      session_id: str = ""
      turn: Dict[str, Any] = field(default_factory=dict)          # ConversationTurn.to_dict()
      presentation: Dict[str, Any] = field(default_factory=dict)  # TurnPresentation.model_dump()

  # packages/ai-parrot/src/parrot/memory/persistence.py  (new)
  TURN_COMPLETED_TOPIC: str = "conversation.turn.completed"
  CONVERSATION_DELETED_TOPIC: str = "conversation.deleted"

  class TurnPresentation(BaseModel):
      """Presentation and usage fields the bot derives from the AIMessage (see §2 Data Models)."""
      @classmethod
      def from_ai_message(cls, response: "AIMessage", *, output_mode: Optional[str],
                          response_time_ms: Optional[int], tenant: Optional[str]) -> "TurnPresentation":
          """Build from a round's AIMessage. Never raises on a missing attribute; absent → None."""

  class TurnPublisher(Protocol):
      async def publish(self, event: TurnCompletedEvent) -> None:
          """Hand the event to the bus. Raises only when the outbox rejects the write."""

  class BusTurnPublisher:
      """TurnPublisher over a navigator_eventbus.EventBus."""
      def __init__(self, bus: Any) -> None: ...
      async def publish(self, event: TurnCompletedEvent) -> None:
          """Emit one envelope on TURN_COMPLETED_TOPIC with event_id == turn_id."""
  ```

### Module 3: `ChatStorageTurn` model and tolerant reader
- **Path**: `packages/ai-parrot/src/parrot/storage/models.py`
- **Responsibility**: the stored turn shape, its (de)serialization to the backend `dict`
  payload, and the reader for pre-FEAT-886 rows.
- **Depends on**: M2 (`TurnPresentation`)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/storage/models.py  (modifies)
  class ChatStorageTurn(BaseModel):
      """Full audit record of one turn (fields in §2 Data Models)."""
      @classmethod
      def from_event_payload(cls, payload: Dict[str, Any]) -> "ChatStorageTurn":
          """Build from a TurnCompletedEvent payload.

          Raises InvalidTurnPayloadError (permanent) when turn_id, user_id, session_id,
          agent_name or a parseable UTC timestamp is missing.
          """
      @classmethod
      def from_row(cls, row: Dict[str, Any]) -> "ChatStorageTurn":
          """Tolerant reader. A row without schema_version is legacy: missing fields default,
          legacy tool_calls map to tool_invocations, schema_version is reported as 1."""
      def to_row(self) -> Dict[str, Any]:
          """JSON-safe dict for ConversationBackend.put_turn; timestamp as ISO-8601 UTC."""
      def to_conversation_turn(self) -> ConversationTurn:  # verified: memory/abstract.py:102
          """Project onto the working-memory turn; presentation is dropped."""
      def to_messages(self) -> List[Dict[str, Any]]:
          """The user + assistant message dicts ChatStorage.load_conversation returns today."""
  ```

### Module 4: Backend contract — errors, ordered window, tombstones, index state
- **Path**: `packages/ai-parrot/src/parrot/storage/errors.py` (new),
  `packages/ai-parrot/src/parrot/storage/backends/base.py`,
  `packages/ai-parrot/src/parrot/storage/instrumented.py`
- **Responsibility**: the typed error hierarchy and the new abstract operations every
  backend implements. `InstrumentedBackend` delegates each of them.
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/storage/errors.py  (new)
  class StorageError(ParrotError): ...                 # ParrotError verified: parrot/exceptions.py:12
  class StorageUnavailableError(StorageError): ...     # disconnected / transport failure — retryable
  class StorageWriteError(StorageError): ...           # the durable write failed — retryable
  class ConversationDeletedError(StorageError): ...    # identity is tombstoned — terminal
  class IndexNotReadyError(StorageError): ...          # chronological index not backfilled
  class InvalidTurnPayloadError(StorageError): ...     # permanent payload defect — terminal

  # packages/ai-parrot/src/parrot/storage/backends/base.py  (modifies :15)
  class ConversationBackend(ABC):  # verified: storage/backends/base.py:15
      @abstractmethod
      async def put_turn(self, user_id: str, agent_id: str, session_id: str,
                         turn_id: str, data: dict) -> None:  # verified: base.py:82
          """Idempotent upsert by turn_id, atomic with the deletion guard and the
          chronological entry. Ordering fields of an existing turn are never changed.

          Raises StorageUnavailableError when disconnected, StorageWriteError when the write
          fails, ConversationDeletedError when the session or the turn is tombstoned.
          """
      @abstractmethod
      async def query_turn_window(self, user_id: str, agent_id: str, session_id: str,
                                  limit: int) -> List[dict]:
          """The newest `limit` turns by (timestamp, sequence, turn_id), limit applied
          descending at the backend, returned ascending.

          Raises StorageUnavailableError, ConversationDeletedError, IndexNotReadyError.
          An active session with no turns returns [].
          """
      @abstractmethod
      async def max_sequence(self, user_id: str, agent_id: str, session_id: str) -> int:
          """Highest stored sequence for the session, 0 when none."""
      @abstractmethod
      async def put_tombstone(self, user_id: str, agent_id: str, session_id: str,
                              turn_id: Optional[str] = None) -> None:
          """Durably record a session (turn_id=None) or turn deletion. Idempotent.
          Not subject to transcript TTL or delete_thread_cascade."""
      @abstractmethod
      async def is_deleted(self, user_id: str, agent_id: str, session_id: str,
                           turn_id: Optional[str] = None) -> bool:
          """Whether the identity is tombstoned. Raises StorageUnavailableError if it
          cannot be determined — never returns False on failure."""
      @abstractmethod
      async def get_index_state(self, user_id: str, agent_id: str, session_id: str) -> str:
          """'ready' | 'pending' | 'invalid'. Sessions created after FEAT-886 are 'ready'."""
      @abstractmethod
      async def backfill_batch(self, cursor: Optional[str], batch_size: int) -> BackfillBatch:
          """Index up to batch_size legacy turns after `cursor`; resumable and safe alongside
          new writes. Marks a session 'ready' once all its turns are indexed, 'invalid' when
          a turn has a missing or unparseable timestamp."""

  @dataclass(frozen=True)
  class BackfillBatch:
      processed: int
      next_cursor: Optional[str]      # None when the scan is complete
      invalid_sessions: Tuple[str, ...]
  ```
  `query_turns` (`base.py:93`) and `delete_turn` (`base.py:104`) keep their signatures.
  `query_turns` raises `StorageUnavailableError` instead of returning `[]` when
  disconnected or failing.

### Module 5: SQLite backend
- **Path**: `packages/ai-parrot/src/parrot/storage/backends/sqlite.py`
- **Responsibility**: implement M4. Add `ts_utc REAL`, `seq INTEGER` and `turn_id TEXT`
  columns to `conversations` (additive migration in `initialize`), a composite index
  `(user_id, agent_id, session_id, kind, ts_utc DESC, seq DESC, turn_id DESC)`, a
  `conversation_tombstones` table and a `conversation_index_state` table. `put_turn`
  runs the tombstone check and the upsert in one transaction.
- **Depends on**: M4
- **Interface Skeleton**: the M4 abstract methods, on
  `class ConversationSQLiteBackend(ConversationBackend)` (`put_turn` verified:
  `storage/backends/sqlite.py:258`).

### Module 6: Postgres backend
- **Path**: `packages/ai-parrot/src/parrot/storage/backends/postgres.py`
- **Responsibility**: implement M4 on `parrot_conversations` with the same columns,
  index and tables as M5 (`TIMESTAMPTZ` for `ts_utc`); the tombstone check and upsert
  share one transaction holding a per-conversation advisory lock.
- **Depends on**: M4
- **Interface Skeleton**: the M4 abstract methods (`put_turn` verified:
  `storage/backends/postgres.py:280`).

### Module 7: Mongo backend
- **Path**: `packages/ai-parrot/src/parrot/storage/backends/mongodb.py`
- **Responsibility**: implement M4 with a compound index on
  `(user_id, agent_id, session_id, kind, ts_utc, seq, turn_id)`, tombstones and index
  state as documents in dedicated collections, and a conditional upsert that fails when
  a tombstone document exists (transaction where the deployment supports it, otherwise
  a guarded two-phase write that re-checks the tombstone and deletes on conflict).
- **Depends on**: M4
- **Interface Skeleton**: the M4 abstract methods (`put_turn` verified:
  `storage/backends/mongodb.py:226`).

### Module 8: DynamoDB backend
- **Path**: `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py`
- **Responsibility**: implement M4. Each turn keeps its canonical item
  `THREAD#<session>#TURN#<turn_id>` and gains a chronological companion item
  `THREAD#<session>#CHRONO#<ts-fixed-width>#<seq-fixed-width>#<turn_id>` in the same
  partition. Canonical item, companion and a `ConditionCheck` on the tombstone item are
  written in one `TransactWriteItems`. `query_turn_window` queries the companion prefix
  with a consistent descending read. Tombstone items carry no `ttl` attribute.
  `put_turn` no longer returns silently when disconnected and no longer swallows
  `ClientError` / `BotoCoreError`.
- **Depends on**: M4
- **Interface Skeleton**: the M4 abstract methods (`put_turn` verified:
  `storage/backends/dynamodb.py:276`; `query_turns` verified: `:313`).

### Module 9: ChatStorage subscriber and deletion protocol
- **Path**: `packages/ai-parrot/src/parrot/storage/chat.py`,
  `packages/ai-parrot/src/parrot/memory/redis.py`
- **Responsibility**: replace `save_turn` with `store_turn`; the bus handler; idempotent
  two-tier writes; the tombstone-first deletion protocol for sessions and turns; reads
  through the tolerant reader. `load_conversation` keeps its return shape and gains the
  richer fields.
- **Depends on**: M3, M4
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/memory/redis.py  (modifies :42)
  class RedisConversation(ConversationMemory):  # verified: memory/redis.py:42
      async def upsert_turn(self, user_id: str, session_id: str, turn: ConversationTurn,
                            chatbot_id: Optional[str] = None) -> None:
          """Replace the stored turn with the same turn_id, or append it, in one CAS write.
          Creates the history when absent. Runs the add_turn normalize/count/offload steps."""

  # packages/ai-parrot/src/parrot/storage/chat.py  (modifies :25; removes save_turn :106)
  class ChatStorage:  # verified: storage/chat.py:25
      async def store_turn(self, turn: ChatStorageTurn) -> None:
          """Upsert `turn` in the cold tier, update thread metadata, then upsert the hot tier.

          Returns only when both tiers hold the turn. Raises StorageError on any tier
          failure — nothing is swallowed and nothing is backgrounded.
          Raises ConversationDeletedError when the session or turn is tombstoned.
          """
      async def handle_turn_completed(self, envelope: "EventEnvelope") -> None:
          """Bus handler for TURN_COMPLETED_TOPIC.

          Retryable StorageError propagates (bus retries, then DLQ). ConversationDeletedError
          and InvalidTurnPayloadError are terminal: logged at WARNING with the turn_id and
          acknowledged, never retried.
          """
      async def delete_conversation(self, user_id: str, session_id: str,
                                    agent_id: Optional[str] = None) -> bool:  # verified: chat.py:533
          """Tombstone first, then clear cold turns, companions, artifacts and the hot tier,
          then run registered working-memory cleaners and publish CONVERSATION_DELETED_TOPIC.

          Raises StorageError when the tombstone cannot be committed — the delete is then
          NOT acknowledged. Cleanup failures after the tombstone are logged and retried by
          the delete-event handler.
          """
      async def delete_turn(self, session_id: str, turn_id: str, user_id: Optional[str] = None,
                            agent_id: Optional[str] = None) -> bool:  # verified: chat.py:578
          """Turn-scoped tombstone first, then delete from the cold and hot tiers."""
      def register_memory_cleaner(
          self, cleaner: Callable[[str, str, str], Awaitable[None]]
      ) -> None:
          """Register a (user_id, agent_id, session_id) cleaner for a working-memory backend."""
      async def handle_conversation_deleted(self, envelope: "EventEnvelope") -> None:
          """Idempotent cleanup retry for CONVERSATION_DELETED_TOPIC."""
  ```

### Module 10: Turn bus setup
- **Path**: `packages/ai-parrot/src/parrot/storage/turn_bus.py` (new),
  `packages/ai-parrot/src/parrot/conf.py`
- **Responsibility**: build the Streams bus with its outbox and DLQ callback, subscribe
  the ChatStorage handlers, and tear it down. Settings: `PARROT_TURN_BUS_REDIS_URL`,
  `PARROT_TURN_BUS_OUTBOX_DIR` (required, writable), `PARROT_TURN_BUS_CHANNEL_PREFIX`
  (default `parrot:turns:`), `PARROT_TURN_BUS_DLQ_DSN` (optional; without it exhausted
  envelopes are retained as dead letters in the SQLite outbox, never dropped — §8 Q15).
- **Depends on**: M2, M9
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/storage/turn_bus.py  (new)
  @dataclass
  class TurnPersistence:
      bus: Any
      publisher: BusTurnPublisher
      subscription_ids: List[str]
      dlq: Optional[Any] = None

  async def setup_turn_persistence(chat_storage: ChatStorage, *, bus: Any = None) -> TurnPersistence:
      """Build (or accept) the turn bus and subscribe ChatStorage.

      Builds EventBus(transport="streams", outbox=<dir>/<host>-<pid>.db,
      default_backpressure="block", ...) when `bus` is None.
      Raises RuntimeError when the outbox directory is unset or not writable.
      """
  async def shutdown_turn_persistence(handle: TurnPersistence) -> None:
      """Unsubscribe and close the bus, preserving the outbox."""
  async def replay_dead_letters(handle: TurnPersistence, *, since: Optional[datetime] = None) -> int:
      """Replay DLQ envelopes through the same handlers; the deletion guard is rechecked
      by store_turn, so a tombstoned identity is never resurrected."""
  ```

### Module 11: Backfill tool
- **Path**: `packages/ai-parrot/src/parrot/storage/backfill.py` (new)
- **Responsibility**: a resumable, batched driver over `backfill_batch`, runnable as
  `python -m parrot.storage.backfill`. Persists its cursor between runs and reports
  invalid sessions. Never invoked from a request path.
- **Depends on**: M4
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/storage/backfill.py  (new)
  async def run_backfill(backend: ConversationBackend, *, batch_size: int = 500,
                         max_batches: Optional[int] = None,
                         cursor_path: Optional[Path] = None) -> BackfillReport:
      """Drive backfill_batch until complete or max_batches is reached; resumes from cursor_path."""

  @dataclass(frozen=True)
  class BackfillReport:
      processed: int
      complete: bool
      invalid_sessions: Tuple[str, ...]
  ```

### Module 12: Auto memory default
- **Path**: `packages/ai-parrot/src/parrot/conf.py`,
  `packages/ai-parrot/src/parrot/bots/abstract.py`
- **Responsibility**: the explicit-configuration signal and the `"auto"` storage type.
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/conf.py  (modifies :332)
  REDIS_HISTORY_EXPLICIT: bool
  """True only when REDIS_HISTORY_URL was set by the operator. Captured before the
  host/port default is synthesized. REDIS_HISTORY_URL keeps its current value either way."""

  # packages/ai-parrot/src/parrot/bots/abstract.py  (modifies :2081)
  def get_conversation_memory(self, storage_type: str = "auto", **kwargs) -> ConversationMemory:
      """Factory. 'memory' | 'file' | 'redis' behave as today.

      'auto' → RedisConversation when kwargs carries `redis_url` / `redis` (host-injected)
      or REDIS_HISTORY_EXPLICIT is True; otherwise InMemoryConversation. Performs no I/O.
      Raises ValueError for an unknown storage type.
      """
  ```
  `self.memory_type` defaults to `"auto"` (`bots/abstract.py:616`). When Redis was
  selected, `configure_conversation_memory` (`bots/abstract.py:1432`) no longer falls
  back to in-memory on error; it re-raises.

### Module 13: Hydration core
- **Path**: `packages/ai-parrot/src/parrot/memory/hydration.py` (new),
  `packages/ai-parrot/src/parrot/memory/abstract.py`,
  `packages/ai-parrot/src/parrot/memory/redis.py`,
  `packages/ai-parrot/src/parrot/memory/mem.py`,
  `packages/ai-parrot/src/parrot/memory/file.py`
- **Responsibility**: the source interface and its typed outcomes, the sequence
  allocator, and the guarded atomic install on every memory backend.
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/memory/hydration.py  (new)
  class HydrationError(Exception): ...
  class HydrationUnavailableError(HydrationError): ...   # source could not be read
  class HydrationNotReadyError(HydrationError): ...      # index not backfilled yet
  class SessionDeletedError(HydrationError): ...         # identity is tombstoned

  class HydrationSource(ABC):
      @abstractmethod
      async def load_turns(self, agent_name: str, user_id: str, session_id: str,
                           max_turns: int) -> Optional[List[ConversationTurn]]:
          """Newest `max_turns` turns, ascending. None = active session with no retained
          turns. Raises the three HydrationError subclasses; never returns [] or None for
          a failure, a deleted session or an unready index."""
      @abstractmethod
      async def is_deleted(self, agent_name: str, user_id: str, session_id: str) -> bool:
          """Authoritative deletion guard. Raises HydrationUnavailableError if unknown."""
      @abstractmethod
      async def max_sequence(self, agent_name: str, user_id: str, session_id: str) -> int:
          """Durable maximum sequence, for allocator recovery."""

  class SequenceAllocator(ABC):
      @abstractmethod
      async def next(self, agent_name: str, user_id: str, session_id: str, *,
                     floor: Optional[Callable[[], Awaitable[int]]] = None) -> int:
          """Next sequence, strictly greater than every value issued before. When the
          counter does not exist, it is initialized from `floor()` (the durable maximum)."""

  class LocalSequenceAllocator(SequenceAllocator): ...   # per-process, for in-memory / file
  class RedisSequenceAllocator(SequenceAllocator):       # INCR, shared across workers
      def __init__(self, redis_client: Any, *, key_prefix: str = "conversation") -> None: ...

  # packages/ai-parrot/src/parrot/memory/abstract.py  (modifies :335)
  class ConversationMemory(ABC):  # verified: memory/abstract.py:335
      async def install_history(self, user_id: str, session_id: str,
                                turns: Sequence[ConversationTurn], chatbot_id: Optional[str] = None,
                                *, metadata: Optional[Dict[str, Any]] = None) -> bool:
          """Stage `turns` through the add_turn normalize/count/offload steps, then install
          the complete history only if none exists.

          Returns True when this call installed it, False when a history already existed
          (the caller then reads the existing one). Never exposes a partial history.
          A history whose metadata['hydration']['state'] == 'pending' counts as absent for
          this purpose: staged turns older than its first turn are prepended atomically.
          """
      @abstractmethod
      async def _install_history(self, history: ConversationHistory) -> bool:
          """Backend primitive: write `history` iff the key is absent (or pending). One write."""
  ```
  `RedisConversation._install_history` uses a single atomic script (`HSETNX`-guarded);
  `InMemoryConversation` and `FileConversationMemory` guard with an in-process lock.

### Module 14: `ChatStorageHydrationSource`
- **Path**: `packages/ai-parrot/src/parrot/storage/hydration.py` (new)
- **Responsibility**: implement `HydrationSource` over a `ConversationBackend`,
  translating M4 errors to M13 errors and stored rows to `ConversationTurn` through the
  tolerant reader.
- **Depends on**: M3, M4, M13
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/storage/hydration.py  (new)
  class ChatStorageHydrationSource(HydrationSource):
      def __init__(self, backend: ConversationBackend) -> None: ...
      """load_turns: get_index_state != 'ready' → HydrationNotReadyError;
      ConversationDeletedError → SessionDeletedError; StorageUnavailableError →
      HydrationUnavailableError; [] → None; rows → ChatStorageTurn.from_row().to_conversation_turn()."""
  ```

### Module 15: Bot integration
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py`,
  `packages/ai-parrot/src/parrot/bots/base.py`
- **Responsibility**: injection points, hydration on miss at the four history-load
  sites, sequence and UTC stamping, publish after save, the caller-supplied `turn_id`.
- **Depends on**: M2, M12, M13
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/bots/abstract.py  (modifies)
  class AbstractBot:
      turn_publisher: Optional[TurnPublisher] = None
      hydration_source: Optional[HydrationSource] = None
      sequence_allocator: Optional[SequenceAllocator] = None
      """All three default to None and are also accepted as constructor kwargs."""

      async def _load_or_hydrate_history(self, memory: ConversationMemory, user_id: str,
                                         session_id: str) -> ConversationHistory:
          """Replace `get_history(...) or create_history(...)`.

          No hydration_source → today's behavior exactly.
          With a source: check is_deleted first (SessionDeletedError propagates; a guard that
          cannot be checked raises HydrationUnavailableError — fail closed). On a hit return
          it. On a miss call load_turns(self.name, ..., max_turns=<budget max_turns or
          max_context_turns or 30>), install_history under self.memory_key_id, recheck
          is_deleted, and return the installed history.
          HydrationNotReadyError / HydrationUnavailableError from load_turns → create the
          history with metadata['hydration'] = {'state': 'pending'} so a later round retries.
          """

      async def save_conversation_turn(self, user_id: str, session_id: str, turn: ConversationTurn,
                                       *, compaction: Optional[CompactionCommit] = None,
                                       presentation: Optional[TurnPresentation] = None,
                                       ) -> None:  # verified: bots/abstract.py:2685
          """As today, plus: stamps turn.timestamp (UTC-aware) and turn.sequence before
          add_turn when they are unset, snapshots the raw turn, and — after add_turn
          succeeds and only when self.turn_publisher is set — publishes TurnCompletedEvent.
          A publish failure is logged at ERROR and never fails the round."""
  ```
  `ask`, `ask_stream`, `invoke` and `conversation` (`bots/base.py:1136`, `:1943`, `:734`,
  `:237`) honor a caller-supplied `turn_id` kwarg instead of always generating one, and
  pass a `TurnPresentation` built from their `AIMessage`, the resolved `output_mode`,
  the elapsed time and `current_tenant.get()`.

### Module 16: Rich parts — model, compaction, render
- **Path**: `packages/ai-parrot/src/parrot/memory/parts.py` (new),
  `packages/ai-parrot/src/parrot/memory/compaction/models.py`,
  `packages/ai-parrot/src/parrot/memory/compaction/compact.py`,
  `packages/ai-parrot/src/parrot/memory/compaction/policies.py`,
  `packages/ai-parrot/src/parrot/memory/render.py`,
  `packages/ai-parrot/src/parrot/memory/__init__.py`
- **Responsibility**: the shared part model, budgeted parts on views, one canonical
  formatter, parts carried through the renderer; tests for all four `_format_history`
  implementations.
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/memory/parts.py  (new)
  @dataclass(frozen=True)
  class MessagePart: ...                       # fields in §2 Data Models

  def render_parts_text(parts: Sequence[MessagePart]) -> str:
      """The ONE canonical text rendering of tool parts. For the same invocations it returns
      exactly the string assistant_suffix holds today."""

  # packages/ai-parrot/src/parrot/memory/compaction/models.py  (modifies :283)
  @dataclass(frozen=True)
  class TurnView:  # verified: memory/compaction/models.py:283
      parts: Optional[Tuple[MessagePart, ...]] = None
      """Already-budgeted parts for the assistant message; None when compaction is disabled
      or the turn has no tool activity. assistant_suffix == render_parts_text(tool parts)."""

  # packages/ai-parrot/src/parrot/memory/compaction/policies.py  (modifies :33)
  @dataclass(frozen=True)
  class PrunedInvocation:  # verified: memory/compaction/policies.py:33
      parts: Tuple[MessagePart, ...] = ()
      """tool_use + tool_result parts matching this invocation's pruned line."""

  # packages/ai-parrot/src/parrot/memory/render.py  (modifies :54)
  @dataclass(frozen=True)
  class HistoryMessage:  # verified: memory/render.py:54
      role: Literal["user", "assistant"]
      content: str
      chatbot_id: Optional[str] = None
      turn_id: Optional[str] = None
      parts: Optional[Tuple[MessagePart, ...]] = None
      """Structured view of `content`. Informational in Phase 1: clients send `content`
      only. Merged messages concatenate their parts in order."""
  ```
  `PrunePolicy.prune` (`policies.py:45`) keeps its signature; a custom policy that
  returns no `parts` yields a single `text` part holding its rendered line.

### Module 17: Server wiring
- **Path**: `packages/ai-parrot-server/src/parrot/manager/manager.py`,
  `packages/ai-parrot-server/src/parrot/handlers/agent.py`
- **Responsibility**: start and stop turn persistence at application level; attach the
  publisher, hydration source and Redis sequence allocator to every bot the manager
  registers; register a working-memory cleaner per registered bot; remove the handler's
  `save_turn` calls; pass `output_mode` and `turn_id=client_message_id` into the bot.
- **Depends on**: M1, M10, M14, M15
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/manager/manager.py  (modifies)
  class BotManager:
      def setup_registry_only(self, app: web.Application, *, import_modules: bool = False,
                              load_definitions: bool = False,
                              turn_persistence: bool = False) -> None:  # verified: manager.py:3130
          """`turn_persistence=True` also initializes ChatStorage and the turn bus at startup."""
      def _attach_durable_memory(self, bot: AbstractBot) -> None:
          """Set bot.turn_publisher / hydration_source / sequence_allocator from app state.
          No-op when turn persistence is not running. Called from add_bot and add_agent."""
  ```
  `on_startup` (`manager.py:3194`) calls `setup_turn_persistence` right after
  `chat_storage.initialize()` and stores the handle in `app["turn_persistence"]`;
  `on_shutdown` (`manager.py:3264`) calls `shutdown_turn_persistence` before closing
  ChatStorage. A failure to start the bus is logged at ERROR and leaves the server
  running without persistence — it does not block startup.

### Module 18: Documentation
- **Path**: `wiki/memory/durable-conversation-memory.md` (new) and the three pages in §10
- **Responsibility**: architecture page, operator migration notes (auto memory opt-in,
  outbox directory, backfill runbook, deletion semantics), and updates to the FEAT-524 /
  FEAT-525 pages.
- **Depends on**: M1–M17
- **Interface Skeleton**: none (documentation).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_agenttalk_does_not_inject_memory` | M1 | the handler passes no `memory=`; read and write hit the same store |
| `test_ask_stream_commits_compaction` | M1 | a streamed round updates boundary, calibration and `stage2_needed` |
| `test_delete_turn_clears_hot_tier` | M1 | the turn is gone from Redis and the cold tier |
| `test_turn_sequence_round_trip` | M2 | `sequence` survives `to_dict` / `from_dict`; legacy dicts load |
| `test_presentation_from_ai_message` | M2 | all fields map; absent attributes become `None` |
| `test_publisher_envelope_shape` | M2 | topic, `event_id == turn_id`, raw pre-normalization turn |
| `test_chat_storage_turn_tolerant_reader` | M3 | pre-FEAT-886 rows load with `schema_version=1` and mapped tool calls |
| `test_chat_storage_turn_invalid_payload` | M3 | missing identity or timestamp raises `InvalidTurnPayloadError` |
| `test_backend_contract_<backend>` | M5–M8 | one parametrized contract suite run against every backend (below) |
| `test_store_turn_idempotent_both_tiers` | M9 | cold success + hot failure, then replay → exactly one turn per tier |
| `test_handler_propagates_retryable` | M9 | `StorageWriteError` reaches the bus; terminal errors are acknowledged |
| `test_delete_conversation_tombstone_first` | M9 | tombstone failure → delete not acknowledged |
| `test_setup_requires_writable_outbox` | M10 | unset or unwritable outbox dir raises `RuntimeError` |
| `test_backfill_resumable` | M11 | interrupted run resumes from its cursor; concurrent writes are safe |
| `test_auto_memory_resolution` | M12 | synthesized defaults → in-memory, no Redis I/O; explicit URL / injected connection → Redis; explicit types win |
| `test_auto_redis_failure_surfaces` | M12 | a configured Redis failure raises, no in-memory fallback |
| `test_install_history_nx_<backend>` | M13 | concurrent installs: one wins, the loser reads the winner's history; never partial |
| `test_install_merges_pending` | M13 | a `pending` history gets older hydrated turns prepended atomically |
| `test_sequence_allocator_recovers_floor` | M13 | after counter loss the next value exceeds the durable maximum |
| `test_hydration_source_error_mapping` | M14 | each M4 error maps to its M13 error; `[]` → `None` |
| `test_load_or_hydrate_paths` | M15 | no source; hit; miss + install; deleted; guard unavailable; not-ready → pending |
| `test_publish_failure_does_not_fail_round` | M15 | publisher raises, the round still returns |
| `test_no_publisher_builds_no_event` | M15 | conversation-less bot: no event object, no extra awaits |
| `test_parts_raw_pruned_dropped` | M16 | RAW, PRUNED, oversized/offloaded and dropped turns produce the specified parts |
| `test_suffix_equals_rendered_parts` | M16 | `assistant_suffix == render_parts_text(parts)` and the token count measures that text |
| `test_disabled_compaction_byte_identical` | M16 | plain path output unchanged, `parts is None` |
| `test_format_history_consumes_content_once` | M16 | base, bedrock, google and jev emit `content` once, never parts |
| `test_custom_policy_without_parts` | M16 | a policy returning no parts yields one text part |
| `test_registry_only_turn_persistence` | M17 | opt-in flag starts and stops the bus |
| `test_agenttalk_has_no_persistence_writes` | M17 | AST scan of `handlers/agent.py`: no ChatStorage / ConversationMemory write calls, no memory construction |
| `test_add_bot_attaches_durable_memory` | M17 | publisher, source and allocator are set on registered bots |

**Backend contract suite (M5–M8, one file, parametrized).** For each backend: a
disconnected backend raises on `put_turn` / `query_turn_window` / `is_deleted`; a failed
durable write raises `StorageWriteError`; a repeated `put_turn` with the same `turn_id`
leaves one turn and unchanged ordering fields; `query_turn_window` with random and
reverse-lexical IDs, equal timestamps and more rows than the limit returns the same
newest window ascending; `put_turn` after `put_tombstone` raises
`ConversationDeletedError`; tombstones survive `delete_thread_cascade` and TTL expiry;
`get_index_state` reports `pending` for legacy sessions and `invalid` for a bad
timestamp; `query_turn_window` on a non-ready session raises `IndexNotReadyError`
without a full scan.

### Integration Tests

| Test | Description |
|---|---|
| `test_turn_round_trip_bus_to_storage` | bot round → outbox → Streams → ChatStorage; the stored turn has tool results, usage and tenant |
| `test_retry_then_dlq` | failing backend: three attempts, then the envelope is in the DLQ; replay stores exactly one turn |
| `test_hydrate_after_restart` | a new bot instance with empty working memory continues with the newest budget window |
| `test_hydration_race_two_workers` | two concurrent first requests, one installed history |
| `test_delete_during_delayed_write` | pause the subscriber, delete the session, resume, replay the DLQ: nothing becomes visible or hydrates |
| `test_delete_during_hydration_install` | the post-install guard recheck rejects the session |
| `test_deleted_turn_stays_deleted` | a delayed upsert cannot undo a turn deletion |
| `test_guard_unavailable_fails_closed` | no stale history is served and no session is initialized |
| `test_stream_disconnect_stores_partial_turn` | a mid-stream disconnect stores a partial turn with error state |

### Validation Contract

tests:
- packages/ai-parrot/tests/unit/memory/test_render_history.py
- packages/ai-parrot/tests/unit/memory/test_history_ownership.py
- packages/ai-parrot/tests/unit/memory/test_conversation_turn_attribution.py
- packages/ai-parrot/tests/unit/memory/test_redis_history_ttl.py
- packages/ai-parrot/tests/unit/memory/compaction/test_compact.py
- packages/ai-parrot/tests/unit/memory/compaction/test_render_views.py
- packages/ai-parrot/tests/unit/memory/compaction/test_policies.py
- packages/ai-parrot/tests/unit/memory/compaction/test_memory_template.py
- packages/ai-parrot/tests/unit/memory/compaction/test_integration_round_trip.py
- packages/ai-parrot/tests/unit/storage/test_chat_hot_tier_metadata.py
- packages/ai-parrot/tests/unit/clients/test_abstract_client_memoryless.py
- packages/ai-parrot/tests/test_chat_storage.py
- tests/storage/test_chat_storage_dynamodb.py
- tests/storage/test_dynamodb_backend.py
- packages/ai-parrot-server/tests/manager/test_registry_only.py
- packages/ai-parrot-server/tests/handlers/test_agenttalk_tenant_metadata.py
- packages/ai-parrot/tests/unit/bots/test_ask_stream_compaction_commit.py
- packages/ai-parrot/tests/unit/storage/test_delete_turn_hot_tier.py
- packages/ai-parrot-server/tests/handlers/test_agenttalk_memory_injection.py
- packages/ai-parrot/tests/unit/bots/test_bot_history_wiring.py
- packages/ai-parrot/tests/unit/memory/test_turn_persistence_event.py
- packages/ai-parrot/tests/storage/test_storage_errors.py
- packages/ai-parrot/tests/storage/test_instrumented_backend.py
- packages/ai-parrot/tests/storage/backends/test_base_abc.py
- packages/ai-parrot/tests/unit/bots/test_auto_memory_resolution.py
- packages/ai-parrot/tests/unit/bots/test_context_budget.py
- packages/ai-parrot/tests/unit/memory/compaction/test_history_parts.py
- packages/ai-parrot/tests/unit/clients/test_format_history_consumes_content_once.py
- packages/ai-parrot/tests/unit/storage/test_chat_storage_turn.py
- packages/ai-parrot/tests/storage/backends/test_sqlite_durable_contract.py
- packages/ai-parrot/tests/storage/backends/test_sqlite_backend.py
- packages/ai-parrot/tests/storage/test_backend_contract.py
- packages/ai-parrot/tests/storage/backends/test_postgres_durable_contract.py
- packages/ai-parrot/tests/storage/backends/test_postgres_backend.py
- packages/ai-parrot/tests/storage/backends/test_mongo_durable_contract.py
- packages/ai-parrot/tests/storage/backends/test_mongo_backend.py
- packages/ai-parrot/tests/storage/backends/test_dynamodb_durable_contract.py
- packages/ai-parrot/tests/storage/backends/test_dynamodb_backend.py
- packages/ai-parrot/tests/unit/storage/test_backfill.py
- packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py
- tests/storage/test_integration_artifact_persistence.py
- packages/ai-parrot/tests/unit/memory/test_hydration_core.py
- packages/ai-parrot/tests/unit/storage/test_turn_bus_setup.py
- packages/ai-parrot/tests/unit/storage/test_chat_storage_hydration_source.py
- packages/ai-parrot/tests/unit/bots/test_load_or_hydrate_history.py
- packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py
- packages/ai-parrot/tests/unit/bots/test_memory_key_id.py
- packages/ai-parrot-server/tests/manager/test_turn_persistence_wiring.py
- packages/ai-parrot-server/tests/handlers/test_agenttalk_no_persistence_writes.py
- packages/ai-parrot/tests/integration/test_durable_conversation_memory.py
- packages/ai-parrot/tests/docs/test_durable_memory_docs.py
markers: none

### Test Data / Fixtures

```python
@pytest.fixture
def failing_backend():
    """A ConversationBackend double whose put_turn fails N times, then succeeds."""

@pytest.fixture(params=["sqlite", "postgres", "mongo", "dynamodb"])
def backend(request):
    """Contract-suite backend; sqlite is in-process, the others use the repo's existing
    fakes/moto fixtures and skip when their driver is unavailable."""

@pytest.fixture
def memory_bus():
    """EventBus(transport="memory") — same retry/DLQ core, no Redis."""

@pytest.fixture
def legacy_rows():
    """Pre-FEAT-886 turn rows: random IDs, no sequence, one with an invalid timestamp."""
```

---

## 5. Acceptance Criteria

- [ ] **Stores separate**: no code path summarizes or mutates ChatStorage turns; the bot
  package has no import of `parrot.storage.chat`.
- [ ] **AgentTalk mismatch fixed**: a `memory_type="memory"` agent called twice over HTTP
  with the same `session_id` sees the first turn on the second call.
- [ ] **AgentTalk persistence-free**: `handlers/agent.py` calls no write method of
  `ChatStorage` (`store_turn`, `save_turn`, thread/turn writes) and no `ConversationMemory`
  write (`add_turn`, `install_history`, `upsert_turn`) and constructs no
  `ConversationMemory`; enforced by a test that inspects the module (AST), so a
  regression fails CI.
- [ ] **Streaming commits compaction**: `ask_stream` rounds update `metadata.compaction`.
- [ ] **Failure propagation and retries**: with a disconnected backend and with a failed
  durable write, in every supported backend, the subscriber fails, the bus retries, and
  exhaustion lands in the DLQ. Cold success followed by hot failure, then replay, leaves
  exactly one turn in each tier. Successful writes are not retried.
- [ ] **No silent backend writes**: no `put_turn` implementation returns without a durable
  write; a disconnected backend raises.
- [ ] **Outbox durability**: a turn published before a simulated process kill is delivered
  after restart.
- [ ] **Conversation-less agents unchanged**: with no publisher and no hydration source,
  a bot round performs no additional awaits and builds no event.
- [ ] **Automatic selection**: with only synthesized defaults, `auto` selects in-memory
  with no Redis I/O. An explicit history URL and a host-injected connection select Redis.
  Explicit `memory` / `file` / `redis` stay authoritative. A configured Redis failure
  surfaces and does not fall back.
- [ ] **Chronological hydration**: with random and reverse-lexical IDs, equal timestamps,
  concurrent workers and more rows than the limit, every backend selects the same newest
  window before applying the limit and returns it ascending. Retry ordering is stable.
  Sequence allocation continues above the durable maximum after a restart.
- [ ] **Backfill**: resumable, batched, safe alongside concurrent writes; invalid
  timestamps leave the session unready; no request path performs a full-table scan;
  not-ready is never reported as an empty history.
- [ ] **Hydration once**: a session that already has data is never re-hydrated; two racing
  first requests produce one installed history.
- [ ] **Key alignment**: for a bot whose `memory_key_id` differs from its name, the stored
  turn is keyed by agent name and the hydrated history is installed under `memory_key_id`.
- [ ] **Deletion races**: pause a subscriber before its write, delete the session, resume
  and replay its DLQ entry — no turn becomes visible or hydrates again. The same holds
  while hydration is installing a key, with hot-tier failure, during backfill, and for a
  deleted individual turn. A guard failure fails closed. Tombstones survive transcript
  cleanup, TTL expiry, worker restart and repeated deletion.
- [ ] **Rich turns**: a stored turn carries tool invocations with output / error / elapsed
  time, usage, cost, model, provider, output mode, data, code, sources, response time and
  tenant. Pre-existing rows still load, reported as `schema_version=1`.
- [ ] **Composer and budgets**: RAW, PRUNED, oversized/offloaded and dropped turns produce
  the specified parts. The token count measures exactly the text sent to each client.
  Omission notices, errors and role alternation are preserved. Parts are never appended
  twice. Dropped turns produce no summaries. With compaction disabled the output is
  byte-identical to today. All four `_format_history` implementations and custom prune
  policies are covered.
- [ ] `parrot.clients.base` is not modified.
- [ ] `ruff check` passes on every touched file; the Validation Contract tests pass.
- [ ] Documentation pages declared in §10 exist under `wiki/` (`parrot sdd techwiki check`).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Implementation agents MUST NOT reference imports, attributes, or methods not listed
> here without first verifying they exist via `grep` or `read`.
> Paths below are relative to `packages/ai-parrot/src/parrot/` unless they start with
> `packages/`.

### Verified Imports

```python
from parrot.memory import (ConversationHistory, ConversationMemory, ConversationTurn,
    RedisConversation, InMemoryConversation, FileConversationMemory, HistoryMessage,
    render_history, TurnView, ToolInvocation, CompactionCommit, compact_history)  # memory/__init__.py:3-27
from parrot.memory.compaction.models import TurnState, ToolStatus, CompactionState  # compaction/models.py:24,31,228
from parrot.memory.compaction.policies import PrunePolicy, PrunedInvocation        # compaction/policies.py:33,40
from parrot.storage import ChatStorage, ConversationBackend, build_conversation_backend  # storage/__init__.py:3,18,22
from parrot.storage.models import ChatMessage, ToolCall, Source                    # storage/models.py:26,54,73
from parrot.exceptions import ParrotError                                          # exceptions.py:12
from parrot.conf import REDIS_HISTORY_URL                                          # conf.py:332
from parrot.models.basic import ToolCall                                           # models/basic.py:23
from navigator_eventbus import EventBus, BusCore, DLQHandler, EventEnvelope, SqliteOutbox  # installed 0.4.0
from navigator_eventbus.lifecycle.base import LifecycleEvent                       # used at core/events/lifecycle/events/memory.py:10
```

### Existing Class Signatures

```python
# memory/abstract.py
@dataclass
class ConversationTurn:                                    # :102
    turn_id: str; user_id: str; user_message: str; assistant_response: str
    context_used: Optional[str] = None
    tools_used: List[str]
    timestamp: datetime = field(default_factory=datetime.now)   # NAIVE local time today
    metadata: Dict[str, Any]
    chatbot_id: Optional[str] = None
    tool_invocations: List[ToolInvocation]
    error: Optional[str] = None
    token_count: Optional[TokenCount] = None
    state: TurnState = TurnState.RAW
    schema_version: int = 1
    norm_version: Optional[str] = None
    def to_dict(self) -> Dict[str, Any]                    # :134
    @classmethod
    def from_dict(cls, data) -> "ConversationTurn"         # :155
    @classmethod
    def from_ai_message(cls, *, user_message, response, user_id, chatbot_id, context_used=None,
                        turn_id=None, assistant_text=None, error=None, tool_invocations=None)  # :178
class ConversationHistory:                                 # :274
class ConversationMemory(ABC):                             # :335
    async def create_history(self, user_id, session_id, metadata=None, chatbot_id=None)  # :422 abstract
    async def get_history(self, user_id, session_id, chatbot_id=None) -> Optional[ConversationHistory]  # :429 abstract
    async def update_history(self, history) -> None        # :436 abstract
    async def add_turn(self, user_id, session_id, turn, chatbot_id=None, *, compaction=None) -> None  # :440 template
    async def _store_turn(self, user_id, session_id, turn, chatbot_id=None, *, compaction_state=None)  # :516 abstract
    async def delete_history(self, user_id, session_id, chatbot_id=None) -> bool  # :606

# memory/redis.py
class RedisConversation(ConversationMemory):               # :42
    def __init__(self, redis_url=None, key_prefix="conversation", use_hash_storage=True, *,
                 token_counter=None, omission_store=None, normalize=True,
                 omission_ttl=None, history_ttl=None)       # :47
    self.redis                                             # :85  redis.asyncio client
    def _get_key(self, user_id, session_id, chatbot_id=None) -> str  # :117
    async def create_history(...)                          # :159
    async def _append_turn(...)                            # :493  CAS append
# memory/mem.py   class InMemoryConversation(ConversationMemory)     # :9
# memory/file.py  class FileConversationMemory(ConversationMemory)   # :13

# memory/render.py
@dataclass(frozen=True)
class HistoryMessage:                                      # :54  role, content, chatbot_id, turn_id
def render_history(history, *, max_turns=None, current_chatbot_id=None,
                   include_other_agents=True, other_agent_label="[agent:{chatbot_id}]") -> List[HistoryMessage]  # :143

# memory/compaction/models.py
@dataclass
class ToolInvocation:                                      # :46
    tool_name: str; input: Dict[str, Any]; output: Optional[str] = None
    status: ToolStatus = ToolStatus.COMPLETED; error: Optional[str] = None
    elapsed_ms: Optional[int] = None; output_chars: Optional[int] = None
    omitted: Dict[str, str]; wm_key: Optional[str] = None
    def to_dict(self)                                      # :78
@dataclass(frozen=True)
class TurnView:                                            # :283
    turn_id: str; chatbot_id: Optional[str]; user_text: str; assistant_text: str
    assistant_suffix: str; state: TurnState; estimated_tokens: int
# memory/compaction/compact.py
def render_tool_activity(turn, limit) -> str               # :120
def compact_history(history, budget, *, policies=None, boundary_turn_id=None, counter=None,
                    calibration=1.0, current_chatbot_id=None, include_other_agents=True) -> CompactionResult  # :143
# memory/compaction/policies.py
class PrunedInvocation                                     # :33
class PrunePolicy(Protocol):                               # :40
    def prune(self, inv, *, turn_id, limit) -> PrunedInvocation  # :45
def format_invocation_line(inv, *, limit, body) -> str     # :60
def omission_notice(inv, content_id_, chars) -> str        # :88
def prune_turn(...)                                        # :320

# storage/chat.py
HOT_TTL_HOURS = 48                                         # :20  unused
class ChatStorage:                                         # :25
    def __init__(self, redis_conversation=None, dynamodb=None, document_db=None)  # :28
    self._redis; self._dynamo                              # :35-36  hot tier / cold backend
    async def initialize(self) -> None                     # :46
    async def save_turn(self, *, turn_id=None, user_id, session_id, agent_id, user_message,
                        assistant_response, output=None, output_mode=None, data=None, code=None,
                        model=None, provider=None, response_time_ms=None, tool_calls=None,
                        sources=None, metadata=None) -> str  # :106
    async def _save_to_dynamodb(self, user_msg, assistant_msg, agent_id, now)  # :215
    async def load_conversation(self, user_id, session_id, agent_id=None, limit=50) -> List[Dict]  # :281
    async def delete_conversation(self, user_id, session_id, agent_id=None) -> bool  # :533
    async def delete_turn(self, session_id, turn_id, user_id=None, agent_id=None) -> bool  # :578
    async def get_context_for_agent(...)                   # :613  no callers outside tests

# storage/backends/base.py
class ConversationBackend(ABC):                            # :15
    async def put_turn(self, user_id, agent_id, session_id, turn_id, data: dict) -> None  # :82
    async def query_turns(self, user_id, agent_id, session_id, limit=10, newest_first=True) -> List[dict]  # :93
    async def delete_turn(self, user_id, agent_id, session_id, turn_id) -> bool  # :104
    async def delete_thread_cascade(self, user_id, agent_id, session_id) -> int  # :118
# storage/backends/dynamodb.py  put_turn :276 (returns silently at :285-286; swallows at :307)
#                               query_turns :313 (SK prefix THREAD#<session>#TURN#, lexical order)
# storage/backends/sqlite.py    conversations DDL :52-64, PK (user_id, agent_id, session_id, kind, sort_key);
#                               put_turn :258 (returns silently at :267-268); query_turns :286 ORDER BY sort_key
# storage/backends/postgres.py  parrot_conversations DDL :56; put_turn :280; query_turns :305
# storage/backends/mongodb.py   put_turn :226; query_turns :259 sort("sort_key")
# storage/instrumented.py       put_turn :80, query_turns :83, delete_turn :86 — thin *a/**kw delegates

# core/events/lifecycle/events/memory.py
@dataclass(frozen=True)
class Stage2CompactionNeededEvent(LifecycleEvent):         # :14

# bots/abstract.py
event_bus: Optional[Any] = None                            # :309  ctor param → _init_events (:469)
self.memory_type: str = kwargs.get("memory_type", "memory")  # :616
def configure_conversation_memory(self) -> None            # :1432  falls back to in-memory on error
def get_conversation_memory(self, storage_type="memory", **kwargs) -> ConversationMemory  # :2081
async def render_context_history(...)                      # :2132
def build_compaction_commit(...)                           # :2209
@property
def memory_key_id(self) -> str                             # :2258  explicit chatbot_id, else self.name
def observed_tool_invocations(self) -> Optional[List[ToolInvocation]]  # :2641
async def save_conversation_turn(self, user_id, session_id, turn, *, compaction=None) -> None  # :2685

# bots/base.py
async def conversation(...)                                # :237
async def invoke(...)                                      # :734
async def ask(...)                                         # :1136
async def ask_stream(...)                                  # :1943
memory = memory or self.conversation_memory                # :431, :830, :1326, :2069
turn_id = str(uuid.uuid4())                                # :385, :779, :1243;  _turn_id at :2013
ConversationTurn.from_ai_message(                          # :645, :898, :1598
await self.save_conversation_turn(user_id, session_id, turn, compaction=commit)  # :663, :913, :1613
await self.save_conversation_turn(user_id, session_id, turn)                     # :2297 (ask_stream)
current_tenant                                             # imported at :117 (ContextVar)

# clients/base.py
def _format_history(self, history: Sequence[HistoryMessage]) -> List[Dict[str, Any]]  # :1863
# overrides: packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py:705
#            packages/ai-parrot-client-google/src/parrot/clients/google/client.py:3241
#            packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py:348

# packages/ai-parrot-server/src/parrot/handlers/agent.py
from ..memory import RedisConversation                     # :42
agent_name = agent.name                                    # :1593
memory = RedisConversation()                               # :1736
chat_storage.save_turn(                                    # :2813 (stream), :3066 (json)
# packages/ai-parrot-server/src/parrot/handlers/chat_interaction.py
storage.delete_conversation(                               # :314
storage.delete_turn(                                       # :388
# packages/ai-parrot-server/src/parrot/handlers/threads.py
storage.delete_conversation(                               # :364

# packages/ai-parrot-server/src/parrot/manager/manager.py
def add_bot(self, bot: AbstractBot) -> None                # :817
def add_agent(self, agent: AbstractBot) -> None            # :1313
def setup_registry_only(self, app, *, import_modules=False, load_definitions=False) -> None  # :3130
async def on_startup(self, app) -> None                    # :3194
chat_storage = ChatStorage()                               # :3237;  app["chat_storage"] = chat_storage :3246
async def on_shutdown(self, app) -> None                   # :3264

# observability/fanout.py — pattern to mirror
def _outbox_path() -> Path                                 # :62  <dir>/<hostname>-<pid>.db, validates writability
def setup_event_fanout(bus: Any = None) -> None            # :90  EventBus(redis_url=, transport="streams",
                                                           #      publish_only=True, channel_prefix=, outbox=) :97

# navigator_eventbus 0.4.0 (installed dependency, pinned >=0.4.0 at packages/ai-parrot/pyproject.toml:201)
BusCore(*, workers=4, queue_size=1024, handler_timeout=30.0, retry_attempts=3, retry_base_delay=0.1,
        backpressure=None, default_backpressure="block", drain_timeout=5.0, on_dlq=None, backend=None,
        outbox=None, relay_interval=5.0, relay_batch=500, relay_max_backoff=300.0, publish_only=False)
BusCore.publish(envelope: EventEnvelope) -> None
BusCore.subscribe(pattern, handler: Callable[[EventEnvelope], Any], *, priority=0, filter_fn=None, min_severity=None) -> str
EventBus(redis_url=None, use_redis=False, *, channel_prefix=None, backend=None,
         transport: Literal["memory","pubsub","streams"]=None, publish_only=False, outbox=None, **bus_options)
         # **bus_options are merged into the BusCore constructor options
EventBus.emit(event_type: str, payload: Dict[str, Any], **kwargs) -> int
EventBus.subscribe(pattern, handler: Callable[[Event], Any], *, priority=0, filter_fn=None, min_severity=None) -> str
EventBus.close()
EventEnvelope(topic, payload, event_id=<factory>, timestamp=<factory>, source=None, severity=..., priority=...,
              correlation_id=None, trace_context=None, metadata=<factory>, schema_version=1)
SqliteOutbox(path, *, max_rows=1000000, max_age=timedelta(days=7), overflow="reject_new")
DLQHandler(bus: BusCore, *, dsn=None, driver="pg")  .ensure_table() .on_dlq(envelope, *, attempts, error, subscriber_id)
           .replay(event_id=None, since=None) -> int
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `BusTurnPublisher.publish` | `EventBus.emit` | method call | navigator_eventbus 0.4.0 |
| `AbstractBot.save_conversation_turn` | `TurnPublisher.publish` | awaited after `add_turn` | `bots/abstract.py:2735` |
| `AbstractBot._load_or_hydrate_history` | `memory.get_history(...) or memory.create_history(...)` | replaces the expression | `bots/base.py:434`, `:833`, `:1330`, `:2072` |
| `ChatStorage.store_turn` | `ConversationBackend.put_turn` / `update_thread` | method call | `storage/chat.py:251`, `:260` |
| `ChatStorage.store_turn` | `RedisConversation.upsert_turn` | method call on `self._redis` | `storage/chat.py:35` |
| `ChatStorageHydrationSource` | `ConversationBackend.query_turn_window` | method call | new in M4 |
| `setup_turn_persistence` | `EventBus(transport="streams", outbox=...)` | constructor, as in fan-out | `observability/fanout.py:97` |
| `BotManager.on_startup` | `setup_turn_persistence` | call after `chat_storage.initialize()` | `manager/manager.py:3239` |
| `BotManager._attach_durable_memory` | `add_bot` / `add_agent` | call | `manager/manager.py:817`, `:1313` |

### Does NOT Exist (Anti-Hallucination)

- ~~A `chat_storage` or `auto` `memory_type`~~ — the factory at `bots/abstract.py:2081` knows only `memory`, `file`, `redis`.
- ~~`TurnCompletedEvent`~~, ~~`parrot.memory.persistence`~~, ~~`parrot.memory.hydration`~~, ~~`parrot.memory.parts`~~ — none exists.
- ~~`HydrationSource`~~, ~~`SequenceAllocator`~~, ~~`ChatStorageTurn`~~, ~~`TurnPresentation`~~, ~~`MessagePart`~~ — none exists.
- ~~`HistoryMessage.parts`~~, ~~`TurnView.parts`~~, ~~`TurnView.tool_invocations`~~ — `TurnView` has only text, suffix, state, ids and `estimated_tokens`.
- ~~`ConversationTurn.sequence`~~ — not a field today.
- ~~`ConversationMemory.install_history`~~, ~~`RedisConversation.upsert_turn`~~ — no such methods.
- ~~`ConversationBackend.query_turn_window` / `put_tombstone` / `is_deleted` / `max_sequence` / `get_index_state` / `backfill_batch`~~ — no such methods.
- ~~`parrot.storage.errors`~~ or any `StorageError` type — the storage package defines only `ExportError` and subclasses (`storage/exports.py:31`).
- ~~`ToolCall.status` / `ToolCall.output`~~ on `parrot.models.basic.ToolCall` — the fields are `result`, `error`, `execution_time`. (`parrot.storage.models.ToolCall` at `storage/models.py:26` is a different class.)
- ~~`REDIS_HISTORY_EXPLICIT`~~ or any explicit-configuration signal in `parrot.conf`; ~~a global env var for `memory_type`~~.
- ~~A bus wired to regular bots~~ — only the autonomous orchestrator and the observability fan-out use `EventBus`. The `event_bus` constructor param feeds lifecycle events, not turn persistence.
- ~~Any producer of `TurnState.SUMMARIZED`~~ or subscriber of `Stage2CompactionNeededEvent`.
- ~~Any caller of `ChatStorage.get_context_for_agent`~~ outside tests; ~~any caller of `ChatStorage.save_turn`~~ other than `handlers/agent.py:2813` and `:3066`.
- ~~`ToolInvocation.tool_call_id`~~ — not a field; `MessagePart.tool_call_id` stays `None` in Phase 1.
- ~~A `DLQHandler` driver other than the default `"pg"`~~ was not verified — check `navigator_eventbus/dlq.py` before using another.

### Edit Sites (Blueprint Anchors)

Verified against: `2dddd6d2cc`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | `await self.save_conversation_turn(user_id, session_id, turn)` | `base.py:2297` | 1 |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | `memory = memory or self.conversation_memory` | `base.py:431`, `:830`, `:1326`, `:2069` | 4 — every occurrence is edited |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `self.memory_type: str = kwargs.get("memory_type", "memory")  # 'memory', 'file', 'redis'` | `abstract.py:616` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `def get_conversation_memory(self, storage_type: str = "memory", **kwargs) -> ConversationMemory:` | `abstract.py:2081` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `def configure_conversation_memory(self) -> None:` | `abstract.py:1432` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `async def save_conversation_turn(` | `abstract.py:2685` | 1 |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `REDIS_HISTORY_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_HISTORY_DB}"` | `conf.py:332` | 1 |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/memory.py` | MODIFY | `class Stage2CompactionNeededEvent(LifecycleEvent):` | `memory.py:14` | 1 |
| `packages/ai-parrot/src/parrot/memory/abstract.py` | MODIFY | `class ConversationTurn:` | `abstract.py:102` | 1 |
| `packages/ai-parrot/src/parrot/memory/abstract.py` | MODIFY | `class ConversationMemory(ABC):` | `abstract.py:335` | 1 |
| `packages/ai-parrot/src/parrot/memory/redis.py` | MODIFY | `class RedisConversation(ConversationMemory):` | `redis.py:42` | 1 |
| `packages/ai-parrot/src/parrot/memory/mem.py` | MODIFY | `class InMemoryConversation(ConversationMemory):` | `mem.py:9` | 1 |
| `packages/ai-parrot/src/parrot/memory/file.py` | MODIFY | `class FileConversationMemory(ConversationMemory):` | `file.py:13` | 1 |
| `packages/ai-parrot/src/parrot/memory/render.py` | MODIFY | `class HistoryMessage:` | `render.py:54` | 1 |
| `packages/ai-parrot/src/parrot/memory/compaction/models.py` | MODIFY | `class TurnView:` | `models.py:283` | 1 |
| `packages/ai-parrot/src/parrot/memory/compaction/compact.py` | MODIFY | `def compact_history(` | `compact.py:143` | 1 |
| `packages/ai-parrot/src/parrot/memory/compaction/policies.py` | MODIFY | `class PrunedInvocation:` | `policies.py:33` | 1 |
| `packages/ai-parrot/src/parrot/memory/__init__.py` | MODIFY | `from .render import HistoryMessage, render_history` | `__init__.py:27` | 1 |
| `packages/ai-parrot/src/parrot/memory/parts.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/memory/persistence.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/memory/hydration.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/storage/chat.py` | MODIFY | `HOT_TTL_HOURS = 48` | `chat.py:20` | 1 |
| `packages/ai-parrot/src/parrot/storage/chat.py` | MODIFY | `async def save_turn(` | `chat.py:106` | 1 |
| `packages/ai-parrot/src/parrot/storage/chat.py` | MODIFY | `async def delete_conversation(` | `chat.py:533` | 1 |
| `packages/ai-parrot/src/parrot/storage/chat.py` | MODIFY | `async def delete_turn(` | `chat.py:578` | 1 |
| `packages/ai-parrot/src/parrot/storage/models.py` | MODIFY | `class ChatMessage:` | `models.py:73` | 1 |
| `packages/ai-parrot/src/parrot/storage/__init__.py` | MODIFY | `from .chat import ChatStorage` | `__init__.py:3` | 1 |
| `packages/ai-parrot/src/parrot/storage/instrumented.py` | MODIFY | `async def put_turn(self, *a, **kw) -> None:` | `instrumented.py:80` | 1 |
| `packages/ai-parrot/src/parrot/storage/backends/base.py` | MODIFY | `async def put_turn(` | `base.py:82` | 1 |
| `packages/ai-parrot/src/parrot/storage/backends/sqlite.py` | MODIFY | `async def put_turn(` | `sqlite.py:258` | 1 |
| `packages/ai-parrot/src/parrot/storage/backends/postgres.py` | MODIFY | `async def put_turn(` | `postgres.py:280` | 1 |
| `packages/ai-parrot/src/parrot/storage/backends/mongodb.py` | MODIFY | `async def put_turn(` | `mongodb.py:226` | 1 |
| `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py` | MODIFY | `async def put_turn(` | `dynamodb.py:276` | 1 |
| `packages/ai-parrot/src/parrot/storage/errors.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/storage/turn_bus.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/storage/hydration.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/storage/backfill.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `memory = RedisConversation()` | `agent.py:1736` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `chat_storage.save_turn(` | `agent.py:2813`, `:3066` | 2 — both call blocks are removed |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `chat_storage = ChatStorage()` | `manager.py:3237` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `def add_bot(self, bot: AbstractBot) -> None:` | `manager.py:817` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `def add_agent(self, agent: AbstractBot) -> None:` | `manager.py:1313` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `def setup_registry_only(` | `manager.py:3130` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `async def on_shutdown(self, app: web.Application) -> None:` | `manager.py:3264` | 1 |
| `wiki/memory/durable-conversation-memory.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Bus wiring**: mirror `observability/fanout.py` (`_outbox_path`, `_config_value`,
  module-level handle, idempotent setup, shutdown that preserves the outbox). The turn
  bus is a **separate** bus instance from the fan-out bus and is not `publish_only`.
- **Template method**: `install_history` is concrete on `ConversationMemory` and
  delegates to an abstract `_install_history`, the same "concrete public, abstract
  private" pattern as `add_turn` / `_store_turn` (FEAT-525). Custom backends implement
  the private method only.
- **Raw turn snapshot**: `add_turn` rebinds to a normalized copy when `normalize=True`,
  so the caller's object stays raw. With `normalize=False` it mutates in place —
  `save_conversation_turn` must take `turn.to_dict()` **before** calling `add_turn`.
- **Rebind, never mutate** `llm_kwargs` or any caller-owned dict on the bot path.
- **Pydantic v2** for `ChatStorageTurn` and `TurnPresentation`; frozen dataclasses for
  `MessagePart`, `TurnView`, `HistoryMessage`, `BackfillBatch` (matching their modules).
- **Hard cut**: `ChatStorage.save_turn` is removed with no deprecation shim.
- **Timestamps**: every new timestamp is `datetime.now(timezone.utc)`. A naive stored
  timestamp is treated as UTC by the tolerant reader and by backfill.
- **Settings**: read through `parrot.conf` (`config.get(...)`), never `os.environ`.
- `parrot/clients/base.py` is not modified; client work in M16 is tests only.

### Known Risks / Gotchas

- **Hottest path.** Every round of a served bot now does one guard read
  (`is_deleted`), one sequence `INCR` and one outbox write. All three must be single
  point operations; none may scan. Conversation-less bots pay nothing.
- **At-least-once delivery.** Duplicates are normal; both tiers upsert by `turn_id`.
  `RedisConversation.add_turn` appends and is not idempotent — the hot tier must go
  through `upsert_turn`.
- **Outbox directory.** One SQLite file per `<hostname>-<pid>`. On Kubernetes it must be
  on a volume that survives a container restart for crash recovery to work; on an
  ephemeral volume the guarantee degrades to "survives a process restart, not a pod
  replacement". `SqliteOutbox(overflow="reject_new")` makes publish raise when full; the
  bot logs at ERROR and the round still succeeds.
- **DLQ without Postgres.** `DLQHandler` defaults to `driver="pg"`. Without
  `PARROT_TURN_BUS_DLQ_DSN`, exhausted envelopes are logged at ERROR with their
  `turn_id` and **retained as dead letters in the per-pod SQLite outbox, never dropped**
  (§8 Q15, M10); say so in the operator docs.
- **Bus not available (CLI, code, sub-agents).** No bus is created and no event is built.
- **Cold tier unavailable.** The backend raises, the subscriber propagates, the bus
  retries and routes exhaustion to the DLQ. A read failure is never a history miss.
- **Hydration while the source is unavailable or unready.** The round proceeds with an
  empty history marked `hydration.state = "pending"`, and a later round retries and
  merges. This marker is the only reason a session with data is hydrated again; see §8.
- **Hydration race.** The loser's install returns `False` and it reads the winner's
  history. No data loss.
- **Old-shape cold rows.** The tolerant reader defaults missing fields and reports
  `schema_version=1`. Legacy rows have random IDs and no sequence; they are not usable
  for hydration until backfilled.
- **Multi-worker with in-memory default.** Workers without Redis still lose context on
  restart, as today. `auto` selects Redis only with explicit configuration.
- **Migration for hosts using shared Redis host/port settings.** They get in-memory under
  `auto`. They must set `REDIS_HISTORY_URL` explicitly, inject a connection, or keep
  `memory_type="redis"`. Document it.
- **`configure_conversation_memory` fallback.** Today any error falls back to in-memory
  (`bots/abstract.py:1437-1441`). Under `auto` with Redis selected, and under explicit
  `redis`, that fallback would split history; it must re-raise. Explicit `file` /
  `memory` keep the fallback.
- **Key alignment.** Do not key ChatStorage by `memory_key_id`. The cold key is the agent
  name; `chatbot_id` is stored as a field.
- **Streaming and cancellation.** On a client disconnect mid-stream a partial turn with
  error state is saved and published; the next round picks up cleanly.
- **Studio and registry-only hosts.** The subscriber is registered at application level,
  not per bot. `setup_registry_only(turn_persistence=True)` opts in. Studio agents live
  in `StudioRuntimeCache`, not `BotManager._bots`, so `add_bot` never sees them; their
  wiring is consumed by Agent Studio in its own repo.
- **Tombstones and TTL.** DynamoDB tombstone items must not carry the `ttl` attribute;
  SQL tombstones live in their own table so `delete_thread_cascade` cannot remove them.
- **Tools that no longer exist.** Parts for removed tools are harmless in Phase 1: only
  text reaches the provider.
- **FEAT-538 task recall** injects a `HistoryMessage` at `bots/abstract.py:2498`; it has
  no parts and must keep working unchanged.
- **Test coupling.** `test_agenttalk_tenant_metadata.py` asserts the tenant passed to
  `save_turn`; it is rewritten against the event's presentation payload in M17.
- **Two test trees.** Root `tests/storage/` and `packages/ai-parrot/tests/` both cover
  storage; update both.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-eventbus` | `>=0.4.0` (already pinned) | `EventBus` Streams transport, `BusCore` retry / DLQ, `SqliteOutbox` |

No new dependency.

---

## Worktree Strategy

- **Isolation**: one feature worktree for the spec; the `sdd-coder` engine gives each
  task its own sub-worktree inside it.
- **Module dependency graph** (an edge means "imports a symbol the other module adds"):
  - M3 → M2 (`TurnPresentation`)
  - M5, M6, M7, M8 → M4 (abstract methods, `storage.errors`)
  - M9 → M3 (`ChatStorageTurn`), M4 (`StorageError` types, `put_tombstone`)
  - M10 → M2 (`BusTurnPublisher`, topics), M9 (`handle_turn_completed`)
  - M11 → M4 (`backfill_batch`)
  - M13 → M2 (`ConversationTurn.sequence`)
  - M14 → M3, M4, M13 (`HydrationSource`, error types)
  - M15 → M2 (`TurnPublisher`), M12 (`"auto"`), M13 (`install_history`, `SequenceAllocator`)
  - M17 → M1, M10, M14, M15
  - M18 → all
  - M1, M2, M4, M12 and M16 have no incoming dependency and start concurrently. M5–M8
    run concurrently with each other.
- **Shared files** (their tasks are serialized):
  - `bots/abstract.py` — M12, M15
  - `bots/base.py` — M1, M15
  - `memory/abstract.py` — M2, M13
  - `memory/redis.py` — M9, M13
  - `storage/chat.py` — M1, M9
  - `conf.py` — M10, M12
  - `handlers/agent.py` — M1, M17
  - `memory/__init__.py` / `storage/__init__.py` exports — M2, M3, M4, M13, M16
- **Exclusive resources**: none. No extension rebuild, lockfile change or migration
  runs at build time; backend schema changes are additive and applied by `initialize`.
- **Cross-feature dependencies**: none must merge first. FEAT-571 (memory-dynamics)
  excludes history and compaction. FEAT-538 task recall must keep working with M16.
  Agent Studio FEAT-013 (other repo) consumes M9 / M10 after this merges.

---

## Consequences

<!-- decision-audit: input_digest=sha256:eff9af9a20d1f217511a6bff64834d5dd8732f23f0aa59747e9c293c2f437a82 evaluation_digest=sha256:b879dc9f650d1978b52dc24c973236dd34f2ac310cee13832998b362d10e495a rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/durable-conversation-memory.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: auth, bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: chat-storage, composer, conversation-history, event-bus, hydration
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "auth",
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "server",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "chat-storage",
      "composer",
      "conversation-history",
      "event-bus",
      "hydration"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/durable-conversation-memory.spec.md"
    }
  ],
  "evaluation_digest": "sha256:b879dc9f650d1978b52dc24c973236dd34f2ac310cee13832998b362d10e495a",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:eff9af9a20d1f217511a6bff64834d5dd8732f23f0aa59747e9c293c2f437a82",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {},
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Q1 — Should ChatStorage become the agent's memory, or stay separate? — *Resolved in brainstorm*: **Stay separate.** ChatStorage is the eternal audit log; ConversationHistory is the active working thread. Connected by events and hydration, never merged.
- [x] Q2 — Who persists turns to ChatStorage? — *Resolved in brainstorm*: **Event-driven.** The bot emits a `TurnCompletedEvent` to a `BusCore`; ChatStorage subscribes. No flags needed for conversation-less agents.
- [x] Q3 — How does the composer build the history for the LLM? — *Resolved in brainstorm*: **Conversation stays as messages (`history=`, FEAT-524).** HistoryMessage gains structured `parts` for tool calls. Phase 1: neutral text render. Phase 2 (follow-up): native provider blocks.
- [x] Q4 — How much is re-hydrated from ChatStorage on a miss? — *Resolved in brainstorm*: **Budget-sized window**, only if the key doesn't already exist in Redis (NX). One-shot, at first access or session change.
- [x] Q5 — Does Stage 2 compaction (LLM summarizer) enter this spec? — *Resolved in brainstorm*: **No — follow-up spec.** Summaries live in ConversationHistory only, never ChatStorage.
- [x] Q6 — How do we guarantee delivery to ChatStorage? — *Resolved in brainstorm*: **BusCore with Redis Streams** when ChatStorage is present. Retry+backoff+DLQ. At-least-once; subscriber upserts by `turn_id`.
- [x] Q7 — What is the default `memory_type`? — *Resolved in brainstorm*: **`"auto"`** — Redis with an explicit history URL or host-injected connection; otherwise in-memory. Synthesized URL defaults do not opt in.
- [x] Q8 — Should P0 ship first as an independent fix? — *Resolved at spec time (Jesus Lara, 2026-11-13)*: **Inside this spec.** P0 is Module 1, with no dependencies, so it lands first on the same branch.
- [x] Q9 — Key alignment: AgentTalk uses `agent_name` as `agent_id`, the bot uses `memory_key_id`. Are they always equal? — *Resolved at spec time (Jesus Lara, 2026-11-13)*: **They are not** (`handlers/agent.py:1593` vs `bots/abstract.py:2258`). **The event carries both**; ChatStorage stays keyed by agent name; hydration queries by agent name and installs under `memory_key_id`.
- [x] Q11 — Backpressure policy for the audit bus? — *Resolved at spec time (Jesus Lara, 2026-11-13)*: **Durable outbox + `block`.** Publish goes to the SQLite outbox first; `block` applies to the relay only.
- [x] Q12 — Handler-side metadata: move into `ConversationTurn` or inject via middleware? — *Resolved at spec time (Jesus Lara, 2026-11-13)*: **Neither — the bot builds a separate `TurnPresentation` from the `AIMessage`** and the event carries it next to the raw turn. `ConversationTurn` stays lean. The handler passes only `output_mode` and the client `turn_id`.
- [x] Q10 — Hot-tier TTL? — *Resolved (Jesus Lara, 2026-11-13)*: **48h.** `CHAT_HOT_TTL_HOURS` defaults to `48`; the hot tier is a cache and hydration from the cold tier covers expired keys. Operators can set `0` to disable the TTL.
- [ ] Q13 — Stage 2 rendering: when the follow-up adds `SUMMARIZED` turns, should they render as an assistant-side context block, a system-adjacent block, or a pseudo user/assistant pair? — *Deferred to the Stage 2 follow-up spec (2026-11-13); not needed by any module here.* — *Owner: Jesus Lara*
- [x] Q14 — Hydration while the source is unavailable or the index is unready? — *Resolved (Jesus Lara, 2026-11-13)*: **Continue as `pending`.** The round proceeds with an empty history marked `metadata['hydration']['state'] = 'pending'` (never treated as an empty conversation) and the hydrated window is merged on a later round, as specified in M13 / M15. A deleted session and an unverifiable deletion guard still fail closed.
- [x] Q16 — Turn bus startup failure? — *Resolved (Jesus Lara, 2026-11-13)*: **Report and continue.** A bus that fails to start is logged at ERROR and the server keeps serving; agents operate without ChatStorage (no publisher, no hydration source attached). This tolerance does NOT extend to conversation history: when Redis history is selected (explicit `memory_type="redis"`, explicit `REDIS_HISTORY_URL` or a host-injected connection), a failure surfaces and never falls back to in-memory (M12). Agent Studio must still be coordinated as a consumer of the subscriber.
- [x] Q15 — DLQ persistence without a Postgres DSN? — *Resolved (Jesus Lara, 2026-11-13)*: **Keep them in the SQLite outbox.** With `PARROT_TURN_BUS_DLQ_DSN` set, exhausted envelopes go to the Postgres `DLQHandler`; without it they are retained in the per-pod SQLite outbox as dead letters (never dropped), and `replay_dead_letters` reads from whichever store holds them.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Status: skipped (the brainstorm's status is
> `exploration`, not `accepted`)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/memory/durable-conversation-memory.md` — create: architecture, event flow,
    hydration, deletion protocol, operator settings, backfill runbook, migration notes
  - `wiki/memory/conversation-history-ownership.md` — update: hydration path, `"auto"`
    memory default, emitter-owned ordering
  - `wiki/memory/per-turn-conversation-compaction.md` — update: streaming commit,
    `TurnView.parts`, canonical text
  - `wiki/stores/storage-backends.md` — update: failure contract, ordered window,
    tombstones, index state
- **API modules** (informational — docstring completeness expectation):
  - `parrot.memory.persistence`
  - `parrot.memory.hydration`
  - `parrot.memory.parts`
  - `parrot.storage.errors`
  - `parrot.storage.turn_bus`
  - `parrot.storage.hydration`
  - `parrot.storage.backfill`

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-13 | Jesus Lara (with Claude) | Initial draft from `sdd/proposals/durable-conversation-memory.brainstorm.md` |
| 0.2 | 2026-11-12 | Juan (for Jesus Lara) | Approved for decomposition: no open questions block a module (Q13 deferred to the Stage 2 follow-up) |
| 0.3 | 2026-11-12 | Juan (for Jesus Lara; open to revision) | Decisions taken while decomposing, all already reflected in the tasks: (1) §7 DLQ bullet aligned with Q15 — dead letters are retained in the SQLite outbox, not dropped (TASK-5581); (2) when `REDIS_HISTORY_EXPLICIT` is true, `REDIS_HISTORY_URL` is the operator's value, never the synthesized host/port one (TASK-5571); (3) a caller disconnect mid-stream saves the partial turn in the bot (TASK-5583); (4) Studio bots: Agent Studio FEAT-013 calls `BotManager._attach_durable_memory` under a contract test; exposing it publicly or calling it from `studio_builder` is a welcome follow-up |
| 0.4 | 2026-11-13 | Juan (for Jesus Lara; open to revision) | Decisions taken in review round 2: (1) `use_conversation_history` controls only what is sent to the LLM / hydrated; a turn is ALWAYS published when a turn publisher is attached (and the round has a user and session id), in `ask`, `ask_stream`, `conversation`, `invoke` and the PandasAgent path; the working-memory write stays conditional; (2) the stored `turn_id` stays the client's `message_id`, but the bus `event_id` (the dedup key) is derived deterministically from the storage key's scope — `(user_id, agent_name, session_id, turn_id)` via `parrot.memory.persistence.turn_event_id` — so a retry of the same turn dedups and two conversations reusing an id do not (this supersedes the literal `event_id == turn_id` of §3 M2); (3) a tombstoned conversation is refused on every read path (`load_conversation`, `get_context_for_agent`, thread listing, hydration, window) even before cleanup finishes, read failures are raised as typed errors (HTTP 410 / 503) instead of becoming an empty result, and post-tombstone cleanup is retried in-process until it succeeds in addition to the deletion event |
| 0.5 | 2026-11-13 | Juan (for Jesus Lara; open to revision) | Decisions taken in review rounds 3-4: (1) every entry point (`ask`, `invoke`, `conversation`, `ask_stream`, PandasAgent) persists through one shared "finalize then persist" step: the turn is built AFTER the output pipeline from the caller-visible text, and saved + published as one unit shielded from cancellation; a failure before that point leaves neither working memory nor the bus with the turn; (2) `ask_stream` stores what was streamed (a TRANSFORM at stream close cannot unsend chunks); (3) abandoned-outbox recovery delivers every pending row regardless of its retry deadline, in bounded batches, unlinks only an empty file under the outbox lock, and a failing or corrupt file is kept without aborting startup; (4) ONE manager-level working-memory cleaner resolves bots by agent name through weak references, isolates each bot and raises an aggregate; `delete_turn` also removes the turn from working memory; (5) a tombstoned turn is filtered on every read path with one batched lookup, `limit` applies after filtering; a deleted session cannot be revived through title/thread/create writes; message reads without an agent are refused (400); (6) the fallback sequence allocator starts above the durable floor, read once per session. Known limits left for the author: outbox recovery matches `<hostname>-<pid>.db` (a replacement pod with a new hostname does not drain it); reads fail closed when the cold tier is down; no transaction spans the working-memory write and the outbox append |
