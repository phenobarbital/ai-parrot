---
title: "Durable Conversation Memory"
---

# Durable Conversation Memory

**FEAT-886** · design: [`sdd/specs/durable-conversation-memory.spec.md`](https://github.com/phenobarbital/ai-parrot/blob/main/sdd/specs/durable-conversation-memory.spec.md)

A user looks at a conversation in the UI and keeps talking to the agent. Before this feature there was no
guarantee that the agent remembered anything the user was looking at: the audit store (`ChatStorage`) and the
agent's working thread (`ConversationHistory`) had no bridge, a restart or a new pod started the agent with an
empty history, and the HTTP handler persisted turns itself in a degraded shape. This page describes the bridge:
event-driven turn persistence, hydration of the working thread, and durable deletion.

---

## Two stores, one bridge

| | `ChatStorage` | `ConversationHistory` |
|---|---|---|
| Purpose | Eternal audit log; reconstruct a conversation at any point in time | The agent's active thread for the current session |
| Content | Every turn in full, never summarized | Summarized, limited and compacted for the LLM |
| Tiers | Hot (`RedisConversation`, TTL `CHAT_HOT_TTL_HOURS`) + cold (`ConversationBackend`) | In-memory, file or Redis |
| Key | agent **name** | `memory_key_id` |

The two are connected by **events and hydration only**. The bot package never imports `ChatStorage`; the server
never writes conversation state. `AbstractBot` stays the only writer of the working thread and the only emitter
of the turn event.

## Event flow

```
                    ask() / ask_stream()
                           |
        +------------------+-------------------+
        v round start                          v round end
 _load_or_hydrate_history            save_conversation_turn   (one save at a time per session)
        |                                      |
        | hit -> render                        +--> TurnPublisher.publish            (optional, first)
        |                                      |         |  SqliteOutbox -> Redis Streams
        | miss                                 +--> ConversationMemory.add_turn      (awaited, after the append)
        v                                                |
 HydrationSource (optional)                              v
        |  guard check, ordered window         ChatStorage.handle_turn_completed
        v                                                |  retry, backoff, DLQ
 ConversationMemory.install_history (NX)                 +--> ConversationBackend.put_turn   (fenced upsert)
                                                         +--> RedisConversation.upsert_turn  (hot tier, chat:)
```

`AbstractBot.save_conversation_turn` first hands the **raw, pre-normalization** turn, wrapped in a
`TurnCompletedEvent`, to the optional `TurnPublisher` (`BusTurnPublisher` over a `navigator_eventbus.EventBus`), which publishes one envelope on
`TURN_COMPLETED_TOPIC` (`"conversation.turn.completed"`) with `event_id == turn_id`. That outbox append comes
before the working-memory write (`ConversationMemory.add_turn`): the durable tier is the source of truth. The
snapshot is still taken before `add_turn` normalizes the turn. The event is **not** emitted
through `EventRegistry`: its payload holds conversation content and must not reach the observability fan-out.
With no publisher configured the bot does nothing extra, and no event object is even built.

Failures of the two writes:

- A rejected append fails the round (the outbox raised: overflow, an unwritable SQLite file). Working memory is not
  touched, so neither tier keeps the turn.
- A working-memory failure after a successful append also fails the round. The durable tier already has the turn,
  and nothing on the bus writes the bot's working memory: `ChatStorage`'s hot tier is its own store (`chat:` keys by
  agent name), not the bot's `conversation:` history keyed by `memory_key_id`. When the bot has a
  `hydration_source`, the session's working memory is dropped (best effort) so the next request rehydrates it from
  the durable tier. A request that arrives before the subscriber stored the turn rehydrates a window without it.
  Without a `hydration_source` working memory is left as it is.

Saves run one save at a time per session in a process: an in-process lock keyed by
`(memory_key_id, user_id, session_id)`, shared by every bot instance with that `memory_key_id`, covers the order
stamp, the outbox append and the working-memory write. Answers are still generated concurrently; only the save
waits, and different sessions never wait for each other. Across pods, ordering rests on the shared sequence
allocator and the `(timestamp, sequence, turn_id)` order of every reader.

`ChatStorage.handle_turn_completed` builds a `ChatStorageTurn` and upserts it by `turn_id` in the cold tier, then in
the hot tier, and acknowledges only after both writes. Delivery is at-least-once, and both tiers are idempotent.
A retryable `StorageError` propagates to the bus (three attempts with exponential backoff, then the dead-letter
store); `ConversationDeletedError` and `InvalidTurnPayloadError` are terminal: they are logged and acknowledged,
never retried. Inside the bot, a rejected append fails the round (see the failure rules above).

Publishing writes to a durable `SqliteOutbox` first (so an in-flight turn survives a pod crash) and only then
relays to Redis Streams with back-pressure `block`.

## Typed storage errors

All storage failures derive from `StorageError`. `StorageUnavailableError` (disconnected or transport failure) and
`StorageWriteError` (the durable write failed) are retryable. `ConversationDeletedError` (the identity is
tombstoned) and `InvalidTurnPayloadError` (a permanent payload defect) are terminal. `IndexNotReadyError` means
the chronological index of a session is not backfilled yet. Backends never return silently on a failed write.

## Ordering fields

The emitter owns ordering. The bot stamps each turn with a UTC-aware timestamp and a monotonic **sequence** per
`(agent, user, session)` obtained from a `SequenceAllocator`: `RedisSequenceAllocator` (`INCR`, shared by every
worker) when a Redis connection exists, `LocalSequenceAllocator` otherwise. After counter loss the allocator
recovers from the durable maximum (`HydrationSource.max_sequence`). Timestamp and sequence are immutable across
retries, gaps are allowed, and no store overrides them. Stores order by `(timestamp, sequence, turn_id)`.

## Identity: agent name vs chatbot id

ChatStorage is keyed by the agent **name** (UI contract and existing rows unchanged), while the working thread is
keyed by `memory_key_id` (the explicit `chatbot_id`, a UUID for a DB-loaded bot, else the name). The event
carries both (`agent_name`, `chatbot_id`). Hydration queries by name and installs under `memory_key_id`.

## Hydration

On a working-memory miss, `AbstractBot._load_or_hydrate_history` consults the injected `HydrationSource`
(`ChatStorageHydrationSource` over the cold backend):

1. `is_deleted` guard first (a guard that cannot be checked fails closed).
2. `load_turns`: the newest budget-sized window, `limit` applied **descending at the backend**, returned
   ascending.
3. `install_history`: stages the turns through the same normalize / count / offload steps as `add_turn`, then
   installs the complete history atomically and only if absent (NX); of two racing first requests, the loser reads
   the winner's history. Never a partial history.
4. The guard is rechecked after installation; a session deleted meanwhile has its installed history removed.

| Source outcome | Meaning | Bot behaviour |
|---|---|---|
| `None` | active session with no retained turns | empty history installed |
| `HydrationNotReadyError` | the chronological index is not backfilled | a `pending` history; retried and merged on a later round |
| `HydrationUnavailableError` | the source could not be read | a `pending` history; retried on a later round |
| `SessionDeletedError` | the identity is tombstoned | raised; nothing is created |

The three errors derive from `HydrationError`. A backend failure, a deleted session and a not-ready index are never converted into `None` or an empty list.

## Deletion protocol

`ChatStorage.delete_conversation` commits a durable **tombstone** for the conversation before acknowledging the
delete, then clears cold turns, chronological companions, artifacts, the hot tier and every working-memory cleaner
registered with `register_memory_cleaner` (omission data included), and publishes
`CONVERSATION_DELETED_TOPIC` (`"conversation.deleted"`) so `handle_conversation_deleted` can retry the cleanup
idempotently. The event is not the deletion authority; the tombstone is. Tombstones live outside transcript TTL
and `delete_thread_cascade`, are retained indefinitely, and session ids are not reused. `delete_turn` writes a
turn-scoped tombstone. Backend writes, subscribers, DLQ replay, backfill and hydration all reject tombstoned
identities, and `store_turn` re-checks the tombstones after writing so a delete that lands mid-write wins.

## What a stored turn contains

`ChatStorageTurn` (`schema_version` 2) carries the full `ConversationTurn` plus a `TurnPresentation`: tool
invocations with output, error and elapsed time, LLM usage and cost, model, provider, `output_mode`, `data`,
`code`, `sources`, `response_time_ms` and the request tenant. The bot builds the presentation from the
`AIMessage` it already holds. A tolerant reader (`ChatStorageTurn.from_row`) fills missing fields on rows written
before this feature and reports them as `schema_version` 1.

## Structured history parts

`MessagePart` (`parrot.memory.parts`) and `render_parts_text` give the compaction layer one canonical formatter.
`TurnView.parts` and `PrunedInvocation.parts` carry the already-budgeted parts together with their canonical text
(RAW parts keep the allowed tool content, PRUNED parts hold the approved preview or omission notice, dropped turns
emit nothing), and `HistoryMessage.parts` carries them next to the rendered `content`. In this release every
client still receives `content` exactly once; `parts` is informational. With compaction disabled the output is
byte-identical to before and `parts` is unset. Native provider tool blocks are not part of this feature.

## Operator settings

| Setting | Default | Meaning |
|---|---|---|
| `memory_type` (bot kwarg) | `"auto"` | `"auto"` selects Redis only with `REDIS_HISTORY_EXPLICIT` or an injected `redis_url`; else in-memory |
| `REDIS_HISTORY_URL` | host/port default | when set by the operator it is used as-is; `REDIS_HISTORY_EXPLICIT` records that it was set |
| `CHAT_HOT_TTL_HOURS` | `48` | hot-tier TTL; `0` disables it |
| `PARROT_TURN_BUS_REDIS_URL` | unset (required) | Redis for the turn bus |
| `PARROT_TURN_BUS_OUTBOX_DIR` | unset (required) | writable directory; one SQLite outbox per pod/pid |
| `PARROT_TURN_BUS_CHANNEL_PREFIX` | `parrot:turns:` | Redis stream prefix |
| `PARROT_TURN_BUS_DLQ_DSN` | unset | optional Postgres dead-letter store |

Enable persistence in a host with `BotManager.setup_registry_only(app, turn_persistence=True)` (the standard
`on_startup` path starts it too); the handle lives in `app["turn_persistence"]`. A bus that fails to start is
logged at ERROR and the server runs without persistence. Hosts that own their bus call
`setup_turn_persistence(chat_storage, bus=...)` (it returns a `TurnPersistence` handle) and
`shutdown_turn_persistence(handle)` themselves.
Agents without conversations (CLI, code, sub-agents) work unchanged and unconfigured.

Without `PARROT_TURN_BUS_DLQ_DSN`, envelopes that exhausted their retries are retained as dead letters in a local
SQLite store next to the outbox, never dropped; `replay_dead_letters(handle)` republishes them through the same
handlers (a tombstoned identity is acknowledged and dropped, never resurrected). Agent Studio consumes the bus
subscriber from its own repository.

## Backfill runbook (legacy rows)

Rows written before this feature carry random turn ids and no sequence, so they cannot be selected
chronologically. A session whose index is not ready reads as **not ready**, never as empty. Run the resumable,
batched driver offline (never from a request path):

```bash
python -m parrot.storage.backfill --batch-size 500 --cursor-file ~/.parrot/conversation-backfill-cursor.json
```

The cursor is persisted after every batch; exit code `0` means complete with no invalid sessions, `2` complete
with invalid sessions (a missing or unparseable timestamp; they stay unready and are never repaired by guessing),
`3` stopped by `--max-batches`. `run_backfill(backend, ...)` returns a `BackfillReport`.

## Migration notes

- `memory_type` now defaults to `"auto"`. A host that relied on the host/port default for Redis must set
  `REDIS_HISTORY_URL`, inject a connection, or keep `memory_type="redis"`. Once Redis is selected, a connection
  failure surfaces instead of silently falling back to local memory.
- `ChatStorage.save_turn` is gone (hard cut). Use `store_turn(ChatStorageTurn)` or the bus subscriber; the HTTP
  handler no longer persists anything.
- Backends now raise typed errors on a failed or disconnected write (`StorageUnavailableError`,
  `StorageWriteError`) instead of returning silently. Custom `ConversationBackend` subclasses must implement
  `query_turn_window`, `max_sequence`, `put_tombstone`, `is_deleted`, `get_index_state` and `backfill_batch`;
  custom `ConversationMemory` subclasses must implement `_install_history`.
- The outbox directory must be on a volume that survives a container restart for crash recovery to hold.
- Not part of this feature: LLM summaries (Stage 2 compaction), native provider tool blocks, a durable omission
  store, and re-keying ChatStorage.
