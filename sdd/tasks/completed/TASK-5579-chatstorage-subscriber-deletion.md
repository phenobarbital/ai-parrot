# TASK-5579: ChatStorage subscriber, `store_turn` and tombstone-first deletion protocol

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: `sdd/specs/durable-conversation-memory.spec.md` (Module 9)
**Status**: done
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-5568, TASK-5573, TASK-5570, TASK-5574
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 and §2 "Piece 1" / "Deletion". `ChatStorage` stops being a write API called by AgentTalk and becomes
the **subscriber** of the turn bus: `save_turn` (fire-and-forget DynamoDB task, swallowed errors) is replaced by
`store_turn(ChatStorageTurn)` (both tiers, idempotent by `turn_id`, every failure raised), plus the bus handlers and a
**tombstone-first** deletion protocol so a delayed write, a DLQ replay or a hydration can never resurrect a deleted
conversation or turn. The ack / retry / tombstone ordering here is the core correctness logic of FEAT-886, which is why the
task is not delegation-eligible. It also adds the hot-tier primitive `RedisConversation.upsert_turn` (CAS replace-or-append)
because `add_turn` appends and is not idempotent under at-least-once delivery.

Coordinator requirement (added): two public read-only properties, `ChatStorage.cold_backend` and
`ChatStorage.hot_redis_client`, so TASK-5584 (server wiring) and TASK-5582 never read private attributes.

---

## Scope

- `storage/chat.py`: remove `save_turn` / `_save_to_dynamodb` / `_safe_serialize_value` (hard cut, no shim); add
  `store_turn`, `handle_turn_completed`, `delete_conversation` (tombstone-first), `delete_turn` (turn-scoped tombstone),
  `register_memory_cleaner`, `handle_conversation_deleted`, `attach_deletion_publisher`, the `cold_backend` /
  `hot_redis_client` properties; read cold rows in `load_conversation` through `ChatStorageTurn.from_row`.
- `memory/redis.py`: `RedisConversation.upsert_turn` (+ a TEMPORARY private `_prepare_turn`, see Notes).
- `tests/test_chat_storage.py`: drop `TestChatStorageSaveTurn`, adapt the delete tests and the `mock_dynamo` fixture.
- New test file with real SQLite + small real subclasses (no `Mock` for the cold tier).

**NOT in scope**: the bus itself and subscriptions (TASK-5581); `ChatStorageTurn` (TASK-5573); backend `put_tombstone` /
`is_deleted` / `put_turn` guard implementations (TASK-5570/5574..5577); hydration / `install_history` (TASK-5580); removing
`chat_storage.save_turn(` from `handlers/agent.py` (TASK-5584); the hot-tier `delete_turn` removal block and
`CHAT_HOT_TTL_HOURS` (TASK-5568 — reuse its code, do not redo it).

### Orphan tests now OWNED by this task (coordinator decision)
The hard cut breaks three other test files that call `ChatStorage.save_turn`. This task ports them (MODIFY, no shim, no `save_turn` resurrected):
`packages/ai-parrot/tests/unit/storage/test_chat_hot_tier_metadata.py`, `tests/storage/test_chat_storage_dynamodb.py` (`TestSaveTurn`) and
`tests/storage/test_integration_artifact_persistence.py` (`test_save_turn_and_fire_dynamodb`). Port rule: build a `ChatStorageTurn` and `await storage.store_turn(turn)`.
Gotchas common to all three: their hot-tier double is an `AsyncMock` with `add_turn` — `store_turn` calls `upsert_turn`, so give it `upsert_turn = AsyncMock()`;
their cold double is an `AsyncMock` whose `is_deleted` would return a truthy mock and trip `_fence_after_write` — set `is_deleted = AsyncMock(return_value=False)`
(and `put_tombstone = AsyncMock()`); `store_turn` is awaited to completion, so the `asyncio.sleep(0.05)` "background task" waits are dropped.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/chat.py` | MODIFY | `store_turn`, handlers, tombstone-first deletes, cleaners, public properties; remove `save_turn` |
| `packages/ai-parrot/src/parrot/memory/redis.py` | MODIFY | `RedisConversation.upsert_turn` (CAS replace-or-append) |
| `packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py` | CREATE | idempotency, error routing, deletion races, properties |
| `packages/ai-parrot/tests/test_chat_storage.py` | MODIFY | remove `save_turn` tests (hard cut); adapt delete tests |
| `packages/ai-parrot/tests/unit/storage/test_chat_hot_tier_metadata.py` | MODIFY | port to `store_turn`; hot-tier metadata via `upsert_turn` |
| `tests/storage/test_chat_storage_dynamodb.py` | MODIFY | port `TestSaveTurn` to `store_turn` |
| `tests/storage/test_integration_artifact_persistence.py` | MODIFY | port the `save_turn` lifecycle test to `store_turn` |

---

## Codebase Contract (Anti-Hallucination)

Re-verified against `6d564b36a2` (`dev`). Paths relative to `packages/ai-parrot/src/parrot/` unless starting with `packages/`.
Line numbers shift after TASK-5568 — anchor on verbatim text.

### Verified Imports
```python
from navconfig.logging import logging                         # verified: storage/chat.py:12
from ..memory.render import render_history                    # verified: storage/chat.py:16 (keep)
from .models import MessageRole                               # verified: storage/chat.py:17 (ChatMessage, ToolCall, Source become unused: remove)
from redis.exceptions import WatchError                       # verified: memory/redis.py:7
from parrot.memory.abstract import ConversationTurn, ConversationHistory   # verified: memory/abstract.py:102,274
from parrot.storage.backends.sqlite import ConversationSQLiteBackend       # verified: storage/backends/sqlite.py:35 (tests)
from navigator_eventbus import EventEnvelope                  # verified: installed navigator_eventbus/__init__.py (tests; type hint only in chat.py)
```

### Provided by dependency tasks (NOT in the tree yet — re-grep after each lands)
```python
from .errors import (StorageError, StorageUnavailableError, StorageWriteError,
                     ConversationDeletedError, InvalidTurnPayloadError)      # TASK-5570 (storage/errors.py)
from .models import ChatStorageTurn   # TASK-5573: from_event_payload(dict) / from_row(dict) / to_row() / to_conversation_turn() / to_messages();
                                      #   fields turn_id,user_id,session_id,agent_id,chatbot_id,timestamp,sequence,presentation(TurnPresentation),...
from ..memory.persistence import CONVERSATION_DELETED_TOPIC   # TASK-5569 ("conversation.deleted")
# ConversationBackend (TASK-5570): put_turn raises StorageUnavailableError/StorageWriteError/ConversationDeletedError;
#   put_tombstone(user_id, agent_id, session_id, turn_id=None); is_deleted(user_id, agent_id, session_id, turn_id=None) -> bool
# TASK-5568 (chat.py): hot-tier removal inside delete_turn + history_ttl wiring in initialize()
```

### Existing Signatures to Use
```python
# storage/chat.py
class ChatStorage:                                                         # :25
    def __init__(self, redis_conversation=None, dynamodb=None, document_db=None)   # :28
    self._redis  # hot tier: RedisConversation(key_prefix="chat"), keyed chatbot_id=<agent NAME>      # :35
    self._dynamo # cold tier: ConversationBackend                                                      # :36
    async def save_turn(...)  # :106 REMOVED          async def _save_to_dynamodb(...) # :215 REMOVED
    async def load_conversation(self, user_id, session_id, agent_id=None, limit=50)   # :281 (cold fallback block "# Fallback: DynamoDB")
    async def delete_conversation(self, user_id, session_id, agent_id=None) -> bool   # :533
    async def delete_turn(self, session_id, turn_id, user_id=None, agent_id=None) -> bool   # :578
    # existing delete: redis.delete_history(user, session, chatbot_id=agent_id); gather(delete_thread_cascade(user, agent or "", session),
    #   delete_session_artifacts(user, agent or "", session)); update_thread(...) after a turn delete
# memory/redis.py
class RedisConversation(ConversationMemory):     # :42   self.redis (redis.asyncio.Redis) :85; _get_key :117; _get_user_sessions_key; _serialize_data/_deserialize_data
_MERGE_MAX_ATTEMPTS = 16; async def _merge_backoff(attempt); def _supports_cas(self)     # :20, :34, :103
async def _append_turn(...)   # :493  WATCH/MULTI/EXEC pattern to copy
async def _refresh_ttl(self, user_id, session_id, chatbot_id)   # :475
# memory/abstract.py  ConversationMemory.add_turn body :479-:503 = the normalize/count/offload steps upsert_turn must mirror
```
Real private names for the new public properties (verified): cold backend = `self._dynamo` (`ConversationBackend | None`, chat.py:36);
hot tier object = `self._redis` (`RedisConversation | None`, chat.py:35); the Redis client the sequence allocator needs = `self._redis.redis`
(`RedisConversation.redis`, redis.py:85, a `redis.asyncio.Redis`).

### Does NOT Exist
- ~~`ChatStorage.store_turn`~~, ~~`handle_turn_completed`~~, ~~`handle_conversation_deleted`~~, ~~`register_memory_cleaner`~~, ~~`attach_deletion_publisher`~~, ~~`cold_backend`~~, ~~`hot_redis_client`~~ — created here.
- ~~`RedisConversation.upsert_turn`~~, ~~`RedisConversation.delete_turn`~~ — no such methods (`upsert_turn` is created here; the single-turn hot removal is TASK-5568's code inside `ChatStorage.delete_turn`).
- ~~`create_history` writing the hash in hash mode~~ — it does NOT (builds `mapping`, never `hset`; fixed in TASK-5580). `upsert_turn` must therefore create the hash itself and never rely on `create_history`.
- ~~Any bus / publisher inside `ChatStorage`~~ — the spec gives it no route to the bus; `attach_deletion_publisher` is the minimal addition (see TASK-5581 "Cross-task contract", written identically).
- ~~A caller of `save_turn` in `handlers/`~~ after TASK-5584 — until then `handlers/agent.py:2813,:3066` still call it (that task removes them).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/storage/chat.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/redis.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/test_chat_storage.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/storage/test_chat_hot_tier_metadata.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/storage/test_chat_storage_dynamodb.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/storage/test_integration_artifact_persistence.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/storage/chat.py#ChatStorage",
    "sym:packages/ai-parrot/src/parrot/memory/redis.py#RedisConversation",
    "sym:packages/ai-parrot/src/parrot/memory/abstract.py#ConversationTurn",
    "sym:packages/ai-parrot/src/parrot/storage/backends/sqlite.py#ConversationSQLiteBackend"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Ack discipline** (spec §2): `handle_turn_completed` lets every retryable `StorageError` propagate (bus retries, then DLQ);
  `ConversationDeletedError` and `InvalidTurnPayloadError` are terminal — log at WARNING with the `turn_id` and RETURN (acknowledge). Nothing else is swallowed.
- **`store_turn` returns only when both configured tiers hold the turn**: cold `put_turn` -> `update_thread` -> hot `upsert_turn` ->
  post-write fence. A tier that is `None` is skipped; both `None` raises `StorageUnavailableError`. A non-`StorageError` exception from a tier is wrapped in `StorageWriteError` (`from exc`) so the bus retries it.
- **Post-write fence** (G7 "Deletion wins"): after both writes re-read `is_deleted` for the session and for the turn. If tombstoned (a delete landed between the cold write and the hot/thread writes), clean the resurrected hot copy / thread row (session: `_cleanup_conversation`; turn: hot removal) and raise `ConversationDeletedError`. Two point reads per stored turn; subscriber path only, never the request path.
- **Tombstone first** in both deletes: `put_tombstone` BEFORE any clearing; a tombstone failure raises (the delete is NOT acknowledged, nothing cleared). After the tombstone, cleanup failures are collected, logged at ERROR, and the deletion event is published so `handle_conversation_deleted` retries; they never turn the delete into an error.
- Deletion event payload: `{"user_id","agent_id","session_id"}` (+ `"turn_id"` for a turn). `handle_conversation_deleted` re-runs cleanup and RAISES `StorageWriteError` if any step still fails (bus retry/DLQ); a malformed payload is logged and acknowledged.
- Memory cleaners receive the agent NAME (the ChatStorage key), `(user_id, agent_name, session_id)`; each registered cleaner decides whether the name is its bot (TASK-5584 maps name -> `memory_key_id`). Cleaner errors are collected like any other cleanup error.
- `delete_conversation` return value stays "something was deleted" (hot result, or cascade/artifact counts > 0); `delete_turn` returns `True` when the cold OR hot tier removed the turn. Both keep today's "agent_id is required" semantic for `delete_turn` (`not user_id or not agent_id` -> `False`).
- Delete with a falsy `agent_id` (`threads.py:364` can pass `""`) tombstones the `""` identity (today's `agent_id or ""` rule); log a WARNING — it does not fence turns stored under a real agent name. Out of scope to fix here; mention in the Completion Note.
- Public properties are READ-ONLY (`@property`, no setters): `cold_backend -> Optional[ConversationBackend]` returns `self._dynamo`; `hot_redis_client -> Optional[Any]` returns `getattr(self._redis, "redis", None)`.
- Hot-tier turn = `turn.to_conversation_turn()` with a slim JSON-safe subset of the presentation merged into `metadata`
  (`output_mode`, `model`, `provider`, `response_time_ms` always; `usage`, `tenant`, `cost_usd` when not `None`). NOT `output` / `data` / `code` / `sources` (the hot tier is a cache; the cold row has everything). This preserves what `test_chat_hot_tier_metadata.py` asserted.
- Thread metadata (`update_thread`): `updated_at=turn.timestamp`, `last_user_message[:200]`, `last_assistant_message[:200]`, `model`, `provider` (from `presentation`), as `_save_to_dynamodb` did.
- `load_conversation` cold path: `ChatStorageTurn.from_row({"user_id": user_id, "session_id": session_id, "agent_id": agent, **row}).to_messages()`; a row that raises `InvalidTurnPayloadError` is skipped with a WARNING (UI listing). Do NOT change its ordering/limit semantics (`query_turns(..., newest_first=False)`) — that is a separate concern.
- `RedisConversation.upsert_turn`: one CAS write; replace the stored turn with the same `turn_id` (keeping the existing `timestamp`/`sequence` — ordering fields of an existing turn never change) or insert a new one in `(timestamp, sequence or 0, turn_id)` order (naive = UTC; append when a stored timestamp cannot be parsed); create the hash (`session_id`, `user_id`, `created_at`, `metadata`) when absent; refresh TTL; add the session to the user-sessions set; raise `RuntimeError` after `_MERGE_MAX_ATTEMPTS` (never fall back to a non-CAS write: the bus retries). `_supports_cas()` False -> unguarded read-modify-write.
- **Temporary duplication, deliberate**: `upsert_turn` must run the `add_turn` normalize/count/offload steps, but the shared helper `ConversationMemory._prepare_turn` is created by TASK-5580 (it owns `abstract.py` after TASK-5569). Here, add a private `RedisConversation._prepare_turn(self, user_id, session_id, turn, chatbot_id=None) -> ConversationTurn` that mirrors `abstract.py:479-503` verbatim, with the same name/signature. TASK-5580 moves it to the base class and DELETES this copy.
- Complexity: each method <= 60 lines, cyclomatic <= 10; keep the cleanup helpers separate from the public methods. `ruff check` clean (remove the now-unused `uuid`, `timedelta`, `ChatMessage`, `ToolCall`, `Source` imports).

### References in Codebase
- `memory/redis.py:493-640` (`_append_turn`), `:332-420` (`merge_metadata`) — CAS loop and `RuntimeError` style.
- `storage/chat.py` `delete_conversation` / `delete_turn` — the cleanup bodies to move into `_cleanup_*` helpers.

---

## Implementation Blueprint

### Steps (in order)
1. Re-grep the dependency symbols and every anchor below (`grep -c`) — *why*: TASK-5568/5570/5573 change this file's neighbourhood.
2. `redis.py`: `_prepare_turn` (temporary) + `upsert_turn` — *why*: `store_turn` needs it; testable alone against real Redis.
3. `chat.py`: imports, `__init__` state, properties, `register_memory_cleaner`, `attach_deletion_publisher` — *why*: small, dependency-free.
4. `chat.py`: `store_turn` + helpers, `handle_turn_completed` — *why*: the write path.
5. `chat.py`: deletion protocol (`_commit_tombstone`, `_cleanup_conversation`, the two deletes, `handle_conversation_deleted`) — *why*: the race-sensitive half.
6. `chat.py`: `load_conversation` cold path; delete `save_turn`, `_save_to_dynamodb`, `_safe_serialize_value` — *why*: hard cut last, once replacements pass.
7. Update `tests/test_chat_storage.py`; write the new test file; run the mutation checks.

### `packages/ai-parrot/src/parrot/memory/redis.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'async def _append_turn(' packages/ai-parrot/src/parrot/memory/redis.py)
# AFTER — add these methods ABOVE `_append_turn` (verified: redis.py:493), plus one module-level pure helper below `_merge_backoff`:

def _upsert_turn_dict(turns: List[Dict[str, Any]], new: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Replace the dict with ``new['turn_id']`` (keeping its ``timestamp``/``sequence``) or insert ``new`` chronologically."""
    # FILL IN: same turn_id -> return a copy with `{**new, "timestamp": old["timestamp"], "sequence": old.get("sequence")}` at that index;
    #   otherwise insert after the last stored turn whose (UTC timestamp, sequence or 0, turn_id) <= new's (datetime.fromisoformat; naive = UTC);
    #   any unparseable stored timestamp -> append — bounded by "ordering fields of an existing turn never change".
    raise NotImplementedError

    async def upsert_turn(
        self, user_id: str, session_id: str, turn: ConversationTurn, chatbot_id: Optional[str] = None
    ) -> None:
        """Replace the stored turn with the same ``turn_id``, or insert it, in ONE compare-and-swap write.

        Creates the history when absent. Runs the ``add_turn`` normalize / count / offload steps. Idempotent: replaying the
        same turn leaves one copy.

        Raises:
            RuntimeError: the CAS still conflicts after ``_MERGE_MAX_ATTEMPTS`` (the caller's bus retries).
        """
        prepared = await self._prepare_turn(user_id, session_id, turn, chatbot_id)
        key = self._get_key(user_id, session_id, chatbot_id)
        for attempt in range(_MERGE_MAX_ATTEMPTS if self._supports_cas() else 1):
            # FILL IN: with a pipeline when self._supports_cas() (WATCH key; hash mode: EXISTS + HGET turns -> _upsert_turn_dict ->
            #   mapping {turns, updated_at, chatbot_id?} plus {session_id, user_id, created_at, metadata:"{}"} when the key was absent ->
            #   MULTI/HSET/EXEC; string mode: GET -> ConversationHistory.from_dict (or a new ConversationHistory) -> replace/insert in .turns -> SET);
            #   on success `await self._refresh_ttl(...)`, `await self.redis.sadd(self._get_user_sessions_key(user_id, chatbot_id), session_id)`, return;
            #   WatchError -> `await _merge_backoff(attempt)` and retry; non-CAS client -> the same read-modify-write without a pipeline —
            #   bounded by the `_append_turn` pattern and "one CAS write".
            raise NotImplementedError
        raise RuntimeError(f"turn upsert for {key} still conflicting after {_MERGE_MAX_ATTEMPTS} attempts")

    async def _prepare_turn(
        self, user_id: str, session_id: str, turn: ConversationTurn, chatbot_id: Optional[str] = None
    ) -> ConversationTurn:
        """TEMPORARY mirror of the ``add_turn`` steps (TASK-5580 moves this to ``ConversationMemory`` and deletes this copy)."""
        # FILL IN: copy memory/abstract.py:479-503 verbatim (normalize_turn when self._normalize, needs_recount/count_turn,
        #   oversize offload via self.omission_store.put, recount, turn.schema_version = 2) and `return turn`.
        raise NotImplementedError
```
**Why**: `upsert_turn` is the idempotent hot-tier write `add_turn` cannot be (it appends). Do NOT call `create_history` (hash mode writes nothing), do NOT fall back to a non-CAS write after exhaustion.

### `packages/ai-parrot/src/parrot/storage/chat.py` (MODIFY) — imports, state, properties, registration
```python
# occurrences: 1 (verified: grep -c -F 'from .models import ChatMessage, MessageRole, ToolCall, Source' packages/ai-parrot/src/parrot/storage/chat.py)
# BEFORE: from .models import ChatMessage, MessageRole, ToolCall, Source
# AFTER:
from ..memory.persistence import CONVERSATION_DELETED_TOPIC
from .errors import (
    ConversationDeletedError,
    InvalidTurnPayloadError,
    StorageError,
    StorageUnavailableError,
    StorageWriteError,
)
from .models import ChatStorageTurn, MessageRole
# also: typing -> add Awaitable, Callable, Tuple, TYPE_CHECKING; `if TYPE_CHECKING: from navigator_eventbus import EventEnvelope`;
# remove the now-unused `import uuid` and `timedelta` (grep confirms 1 occurrence each) once save_turn is gone.

# occurrences: 1 (verified: grep -c -F '        self._initialized = False' packages/ai-parrot/src/parrot/storage/chat.py)
# AFTER — insert below `self._initialized = False` (verified: chat.py:~39):
        self._memory_cleaners: List[Callable[[str, str, str], Awaitable[None]]] = []
        self._deletion_publisher: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None

# AFTER `_backend_label` property (anchor: grep -c -F 'def _backend_label(self) -> str:' == 1), add:
    @property
    def cold_backend(self) -> Optional[Any]:
        """The cold-tier ``ConversationBackend`` (read-only), or ``None`` when no backend is configured."""
        return self._dynamo

    @property
    def hot_redis_client(self) -> Optional[Any]:
        """The Redis client behind the hot tier (read-only), or ``None`` when there is no Redis hot tier."""
        return getattr(self._redis, "redis", None)

    def register_memory_cleaner(self, cleaner: Callable[[str, str, str], Awaitable[None]]) -> None:
        """Register a ``(user_id, agent_name, session_id)`` cleaner for one working-memory backend.

        Called after the tombstone is committed, once per delete and again on every cleanup retry, so it MUST be idempotent.
        """
        self._memory_cleaners.append(cleaner)

    def attach_deletion_publisher(
        self, publisher: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]]
    ) -> None:
        """Set (or clear with ``None``) the callable that publishes deletion events: ``await publisher(topic, payload)``."""
        self._deletion_publisher = publisher
```

### `packages/ai-parrot/src/parrot/storage/chat.py` (MODIFY) — write path
```python
# occurrences: 1 (verified: grep -c -F 'async def save_turn(' packages/ai-parrot/src/parrot/storage/chat.py)
# REPLACE the whole `save_turn` method AND `_save_to_dynamodb` (verified: chat.py:106-:278, i.e. up to the "# Read operations" banner;
# occurrences of 'async def _save_to_dynamodb(' == 1) with:

    async def store_turn(self, turn: ChatStorageTurn) -> None:
        """Upsert ``turn`` in the cold tier, update thread metadata, then upsert the hot tier.

        Returns only when both configured tiers hold the turn.

        Raises:
            StorageError: any tier failed (retryable) — nothing is swallowed, nothing is backgrounded.
            ConversationDeletedError: the session or the turn is tombstoned (terminal).
        """
        if self._dynamo is None and self._redis is None:
            raise StorageUnavailableError("no storage tier is configured")
        try:
            if self._dynamo is not None:
                await self._store_cold(turn)
            if self._redis is not None:
                await self._redis.upsert_turn(turn.user_id, turn.session_id, self._hot_tier_turn(turn), chatbot_id=turn.agent_id)
            await self._fence_after_write(turn)
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001 — a foreign exception must still reach the bus as retryable
            raise StorageWriteError(f"store_turn failed for turn {turn.turn_id}: {exc}") from exc

    async def _store_cold(self, turn: ChatStorageTurn) -> None:
        """``put_turn`` (guarded + idempotent in the backend) then ``update_thread``."""
        # FILL IN: await self._dynamo.put_turn(turn.user_id, turn.agent_id, turn.session_id, turn.turn_id, turn.to_row()); then
        #   await self._dynamo.update_thread(user_id=..., agent_id=..., session_id=..., updated_at=turn.timestamp,
        #   last_user_message=turn.user_message[:200], last_assistant_message=turn.assistant_response[:200],
        #   model=turn.presentation.model, provider=turn.presentation.provider) — bounded by Key Constraints (thread metadata).
        raise NotImplementedError

    @staticmethod
    def _hot_tier_turn(turn: ChatStorageTurn) -> "ConversationTurn":
        """Working-memory projection of ``turn`` with the slim presentation subset in ``metadata`` (see Key Constraints)."""
        # FILL IN: ct = turn.to_conversation_turn(); ct.metadata = {**ct.metadata, "output_mode":..., "model":..., "provider":...,
        #   "response_time_ms":..., plus "usage"/"tenant"/"cost_usd" when not None}; return ct — never output/data/code/sources.
        raise NotImplementedError

    async def _fence_after_write(self, turn: ChatStorageTurn) -> None:
        """Re-check the tombstones; if a delete landed meanwhile, undo the resurrected copy and raise (deletion wins)."""
        if self._dynamo is None:
            return
        # FILL IN: session = await self._dynamo.is_deleted(user, agent, session); scoped = await self._dynamo.is_deleted(user, agent, session, turn.turn_id);
        #   session -> `_, errors = await self._cleanup_conversation(...)` (log errors) ; scoped -> remove the turn from the hot tier (TASK-5568 block);
        #   then raise ConversationDeletedError — bounded by G7 and AC "Deletion races".
        raise NotImplementedError

    async def handle_turn_completed(self, envelope: "EventEnvelope") -> None:
        """Bus handler for ``TURN_COMPLETED_TOPIC``.

        Retryable ``StorageError`` propagates (the bus retries, then dead-letters). ``ConversationDeletedError`` and
        ``InvalidTurnPayloadError`` are terminal: logged at WARNING with the turn id and acknowledged.
        """
        try:
            await self.store_turn(ChatStorageTurn.from_event_payload(envelope.payload))
        except (ConversationDeletedError, InvalidTurnPayloadError) as exc:
            self.logger.warning("turn %s not stored (terminal %s): %s", envelope.event_id, type(exc).__name__, exc)
```
**Why**: the ack/propagate split is the whole delivery contract; `envelope.event_id` is the `turn_id` (TASK-5569 sets `event_id == turn_id`). Do NOT catch `StorageError` here; do NOT background anything.

### `packages/ai-parrot/src/parrot/storage/chat.py` (MODIFY) — deletion protocol
```python
# occurrences: 1 (verified: grep -c -F 'async def delete_conversation(' packages/ai-parrot/src/parrot/storage/chat.py)
# REPLACE `delete_conversation` and `delete_turn` (verified: chat.py:533-:611; occurrences of 'async def delete_turn(' == 1; after TASK-5568
# `delete_turn` already removes the hot copy — keep that block, move it into `_delete_hot_turn`) with:

    async def delete_conversation(self, user_id: str, session_id: str, agent_id: Optional[str] = None) -> bool:
        """Tombstone first, then clear cold turns, companions, artifacts and the hot tier, run the cleaners, publish the event.

        Raises:
            StorageError: the tombstone could not be committed — the delete is NOT acknowledged and nothing is cleared.
        """
        agent = agent_id or ""
        await self._commit_tombstone(user_id, agent, session_id)
        deleted, errors = await self._cleanup_conversation(user_id, agent_id, session_id)
        for exc in errors:
            self.logger.error("post-tombstone cleanup failed for session %s (retried via event): %s", session_id, exc)
        await self._publish_deletion({"user_id": user_id, "agent_id": agent, "session_id": session_id})
        return deleted

    async def delete_turn(self, session_id: str, turn_id: str, user_id: Optional[str] = None, agent_id: Optional[str] = None) -> bool:
        """Turn-scoped tombstone first, then delete from the cold and hot tiers; True if either tier removed the turn."""
        if not user_id or not agent_id:
            return False
        await self._commit_tombstone(user_id, agent_id, session_id, turn_id)
        # FILL IN: cold = await self._dynamo.delete_turn(...) (collect exceptions, do not raise) then update_thread(updated_at=now) when True;
        #   hot = await self._delete_hot_turn(user_id, session_id, turn_id, agent_id) (TASK-5568's removal block, extracted; collect exceptions);
        #   log collected errors at ERROR; `await self._publish_deletion({..., "turn_id": turn_id})`; return cold or hot —
        #   bounded by Key Constraints and AC "a deleted individual turn".
        raise NotImplementedError

    async def _commit_tombstone(self, user_id: str, agent: str, session_id: str, turn_id: Optional[str] = None) -> None:
        """Durably record the deletion; raise ``StorageError`` (never swallow) when it cannot be committed."""
        if self._dynamo is None:
            return  # no durable store: nothing can resurrect, nothing to fence
        # FILL IN: await self._dynamo.put_tombstone(user_id, agent, session_id, turn_id) — StorageError re-raised; any other
        #   Exception -> StorageWriteError(...) from exc; WARNING when `agent == ""` (see Key Constraints).
        raise NotImplementedError

    async def _cleanup_conversation(
        self, user_id: str, agent_id: Optional[str], session_id: str
    ) -> Tuple[bool, List[BaseException]]:
        """Idempotent post-tombstone cleanup. Returns ``(something_deleted, errors)``; never raises."""
        # FILL IN: hot: self._redis.delete_history(user_id, session_id, chatbot_id=agent_id); cold: asyncio.gather(delete_thread_cascade(user, agent or "", session),
        #   delete_session_artifacts(...)) (counts > 0 -> deleted); then every cleaner in self._memory_cleaners with (user_id, agent_id or "", session_id);
        #   each step in its own try/except collecting the exception — bounded by "cleanup failures after the tombstone are logged and retried".
        raise NotImplementedError

    async def _delete_hot_turn(self, user_id: str, session_id: str, turn_id: str, agent_id: str) -> bool:
        """Remove one turn from the hot tier (extracted from TASK-5568's ``delete_turn`` block)."""
        raise NotImplementedError  # FILL IN: move TASK-5568's hot-tier removal here unchanged

    async def _publish_deletion(self, payload: Dict[str, Any]) -> None:
        """Publish the deletion event for idempotent cleanup retries; a failure is logged, never raised."""
        # FILL IN: no publisher -> return; try await self._deletion_publisher(CONVERSATION_DELETED_TOPIC, payload) except Exception -> logger.error.
        raise NotImplementedError

    async def handle_conversation_deleted(self, envelope: "EventEnvelope") -> None:
        """Idempotent cleanup retry for ``CONVERSATION_DELETED_TOPIC``; raises ``StorageWriteError`` while any step still fails."""
        # FILL IN: payload keys user_id/agent_id/session_id (+ optional turn_id); malformed -> WARNING + return (acknowledged);
        #   turn_id -> `_delete_hot_turn` + cold `delete_turn`, else `_cleanup_conversation`; any collected error -> raise StorageWriteError
        #   (the bus retries) — bounded by Key Constraints. Do NOT republish the event (loop).
        raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/storage/chat.py` (MODIFY) — read path and removals
```python
# occurrences: 1 (verified: grep -c -F '        # Fallback: DynamoDB' packages/ai-parrot/src/parrot/storage/chat.py)
# In the cold-tier block of `load_conversation` (verified: chat.py:335-:385) replace the hand-built per-turn dicts with
# `messages.extend(ChatStorageTurn.from_row({"user_id": user_id, "session_id": session_id, "agent_id": agent, **row}).to_messages())`
# per row, skipping (WARNING) a row that raises InvalidTurnPayloadError. Keep the call `query_turns(..., newest_first=False)` and the Redis-first path untouched.
# occurrences: 1 (verified: grep -c -F 'def _safe_serialize_value(obj: Any) -> Any:' packages/ai-parrot/src/parrot/storage/chat.py)
# DELETE `_safe_serialize_value` (verified: chat.py:647-:657; grep over packages/ and tests/ finds no other user).
```

### `packages/ai-parrot/tests/test_chat_storage.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'class TestChatStorageSaveTurn:' packages/ai-parrot/tests/test_chat_storage.py)
# DELETE the whole class `TestChatStorageSaveTurn` (verified: test_chat_storage.py:152-:239, 5 tests) — save_turn no longer exists.
# In fixture `mock_dynamo` (verified: :41-:55) ADD:  dynamo.put_tombstone = AsyncMock()  and  dynamo.is_deleted = AsyncMock(return_value=False)
# `TestChatStorageDeleteConversation` (:277-:284): keep, and add `mock_dynamo.put_tombstone.assert_awaited_once()`.
# Update the module docstring: "save_turn" is replaced by store_turn (covered in unit/storage/test_chat_storage_subscriber.py).
```

### `packages/ai-parrot/tests/unit/storage/test_chat_hot_tier_metadata.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'turn_id = await storage.save_turn(' packages/ai-parrot/tests/unit/storage/test_chat_hot_tier_metadata.py)
# REPLACE the `save_turn(...)` call (verified: lines ~26-33, kwargs user_id/session_id/agent_id/user_message/assistant_response/metadata={"usage":..., "tenant":"t1"}) with:
#     await storage.store_turn(ChatStorageTurn(turn_id="t-1", user_id="user1", session_id="session1", agent_id="agent1",
#         timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), sequence=1, user_message="Hello", assistant_response="Hi there",
#         presentation=TurnPresentation(usage={"total_tokens": 3}, tenant="t1")))
# In the `mock_redis` stub: replace `add_turn = AsyncMock()` with `upsert_turn = AsyncMock()` (drop get_history/create_history).
# `dynamodb=None` stays (cold tier skipped; the fence is a no-op). The assertions read the turn from `mock_redis.upsert_turn.call_args.args[2]`
# (signature upsert_turn(user_id, session_id, turn, chatbot_id=...)); `usage == {"total_tokens": 3}` and `tenant == "t1"` stay (now sourced from the
# presentation subset, Key Constraints "Hot-tier turn"). The four fixed keys (output_mode, model, provider, response_time_ms) are present and None.
# DELETE the old "caller metadata keys win/lose" comments: there is no caller `metadata` argument any more.
# FILL IN: imports (`from datetime import datetime, timezone`; `from parrot.storage.models import ChatStorageTurn`; `from parrot.memory.persistence import TurnPresentation`;
#   remove the unused ChatMessage/MessageRole import if ruff flags it) — bounded by TASK-5569/5573 names.
```
**Why**: this test pins that usage and tenant reach the hot tier; the contract moved from `save_turn(metadata=...)` to the presentation subset.

### `tests/storage/test_chat_storage_dynamodb.py` (MODIFY)
```python
# occurrences: 3 (verified: grep -c -F 'await storage.save_turn(' tests/storage/test_chat_storage_dynamodb.py) — all three inside `class TestSaveTurn:`
#   (test_returns_turn_id, test_uses_provided_turn_id, test_fires_dynamodb_background_task). Quote 2-3 surrounding lines when editing each.
# Fixtures (verified: lines ~13-40): `mock_redis`: add `redis.upsert_turn = AsyncMock()`; `mock_dynamo`: add `dynamo.is_deleted = AsyncMock(return_value=False)`
#   and `dynamo.put_tombstone = AsyncMock()`.
# REWRITE the class as `TestStoreTurn`:
#   test_stores_turn_in_both_tiers   — await storage.store_turn(<turn "t-1", agent "bot1", session "sess1">); mock_dynamo.put_turn awaited once with
#                                      user_id="u1"/agent_id="bot1"/session_id="sess1"/turn_id="t-1" and data["user_message"]=="hello", data["assistant_response"]=="hi";
#                                      mock_redis.upsert_turn awaited once.   (replaces test_returns_turn_id + test_fires_dynamodb_background_task; no asyncio.sleep)
#   test_uses_provided_turn_id       — the stored turn_id equals the one on the ChatStorageTurn ("custom-123").
#   test_cold_write_is_awaited_not_backgrounded — put_turn is already awaited when store_turn returns (replaces the sleep(0.05)).
# `put_turn` is called with keyword args today's backend ABC uses (positional in store_turn: user_id, agent_id, session_id, turn_id, data) — assert via `call_args`
#   accordingly (read how store_turn passes them; do not assert `.kwargs` if it passes positionally).
# FILL IN: a small module-level `_turn(...)` helper building the ChatStorageTurn (UTC timestamp, sequence=1) — bounded by TASK-5573's field list.
```
**Why**: keeps the DynamoDB-shaped suite meaningful for the new write path; the "fire and forget" assertion becomes its opposite.

### `tests/storage/test_integration_artifact_persistence.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'await chat_storage.save_turn(' tests/storage/test_integration_artifact_persistence.py) at line ~131 inside
#   `test_save_turn_and_fire_dynamodb`.
# Fixtures (verified: lines ~85-105): the `mock_redis` / `mock_dynamo` used by `chat_storage` get `upsert_turn = AsyncMock()`, `is_deleted = AsyncMock(return_value=False)`,
#   `put_tombstone = AsyncMock()` respectively.
# REWRITE the test as `test_store_turn_writes_dynamodb`: build ChatStorageTurn(turn_id=..., user_id="u1", session_id="sess1", agent_id="bot1",
#   user_message="What are Q4 sales?", assistant_response="Q4 sales were $2.5M", UTC timestamp, sequence=1); `await chat_storage.store_turn(turn)`;
#   REMOVE `turn_id is not None` and the `await asyncio.sleep(0.05)`; keep `mock_dynamo.put_turn.assert_called_once()`.
# Leave every other test in the file untouched (create_thread, list, load, delete). If the delete test asserts on `delete_thread_cascade` only, also add
#   `mock_dynamo.put_tombstone` to the mock so tombstone-first deletion does not hit an unconfigured attribute.
# FILL IN: whether `import asyncio` becomes unused (ruff) — bounded by the rest of the file.
```
**Why**: same hard cut; this one is the end-to-end lifecycle smoke test over mocked tiers.

### FILL IN checklist
- [ ] `redis.py::_upsert_turn_dict`, `upsert_turn`, `_prepare_turn` — bounded by "ordering fields never change" and the `_append_turn` pattern.
- [ ] `chat.py::_store_cold`, `_hot_tier_turn`, `_fence_after_write` — bounded by Key Constraints and G7.
- [ ] `chat.py::delete_turn`, `_commit_tombstone`, `_cleanup_conversation`, `_delete_hot_turn`, `_publish_deletion`, `handle_conversation_deleted` — bounded by "tombstone first".
- [ ] `chat.py::load_conversation` cold path — bounded by TASK-5573 `from_row`/`to_messages` (read them after they land).
- [ ] Tests: `ChatStorageTurn` construction helper — bounded by TASK-5573's field list.
- [ ] The three ported orphan test files — bounded by their Blueprint blocks above.

---

## Acceptance Criteria

- [ ] **Idempotent across tiers**: cold success + hot failure raises; replaying leaves exactly one turn in each tier (spec §4 `test_store_turn_idempotent_both_tiers`; spec §5 "Failure propagation and retries").
- [ ] Retryable `StorageError` reaches the bus; deleted / invalid-payload are acknowledged with a WARNING carrying the turn id (spec §4 `test_handler_propagates_retryable`).
- [ ] Tombstone first: a failing `put_tombstone` raises and clears nothing; call order is tombstone then clears (spec §4 `test_delete_conversation_tombstone_first`).
- [ ] After a delete, a replayed / delayed `store_turn` raises `ConversationDeletedError` and nothing becomes visible in either tier; a deleted individual turn stays deleted while its siblings remain (spec §5 "Deletion races").
- [ ] Delete landing between the cold and hot writes: the post-write fence removes the resurrected hot copy and thread row (spec §5 "while hydration is installing a key, with hot-tier failure").
- [ ] Cleanup failure after the tombstone is not raised by `delete_conversation`, publishes the event, and `handle_conversation_deleted` raises until cleanup succeeds; registered cleaners run on both paths.
- [ ] `ChatStorage.cold_backend is the configured backend`, `hot_redis_client is hot.redis`, both `None` when absent, both read-only (`AttributeError` on assignment).
- [ ] The three ported files pass and contain no `save_turn` (grep clean over `packages/` and `tests/`, except TASK-5584's handler until it lands).
- [ ] `ChatStorage` has no `save_turn`; `load_conversation` returns tool calls / usage for new rows and still reads a legacy row (spec §5 "Rich turns … schema_version=1").
- [ ] Real Redis (`TEST_REDIS_URL`): `upsert_turn` replaces by `turn_id`, inserts chronologically, creates the hash, survives a concurrent `gather` (no duplicate, no lost turn).
- [ ] **Mutation checks** (revert, see RED, restore by re-applying — never `git checkout`): (1) move `_commit_tombstone` after `_cleanup_conversation` -> `test_delete_conversation_tombstone_first` RED; (2) make `handle_turn_completed` catch `StorageError` -> `test_handler_propagates_retryable` RED; (3) drop `_fence_after_write` -> `test_delete_between_cold_and_hot_write_is_fenced` RED; (4) swallow the hot-tier error in `store_turn` -> `test_store_turn_idempotent_both_tiers` RED; (5) make `upsert_turn` always append -> the real-Redis replace test RED; (6) make `cold_backend` return a copy/None -> the properties test RED.
- [ ] `ruff check` clean on the four touched files; `from parrot.storage.chat import ChatStorage` works and `ChatStorage.store_turn` exists.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py -q`
- `pytest packages/ai-parrot/tests/test_chat_storage.py -q`
- `pytest packages/ai-parrot/tests/unit/storage/test_chat_hot_tier_metadata.py -q`
- `pytest tests/storage/test_chat_storage_dynamodb.py -q`
- `pytest tests/storage/test_integration_artifact_persistence.py -q`

---

## Test Specification

Cold tier = real `ConversationSQLiteBackend` (TASK-5574). Hot tier = `DictHotTier(RedisConversation)`, a real subclass overriding ONLY the I/O methods
with an in-process dict plus failure injection (constructing `RedisConversation` opens no connection); the real-Redis behavior of `upsert_turn`
is covered by the `TEST_REDIS_URL` tests. Failure injection on the cold tier is also a real subclass. No `Mock` for storage.

```python
# packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py
import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from navigator_eventbus import EventEnvelope
from redis.asyncio import Redis

from parrot.memory import ConversationTurn, RedisConversation
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.chat import ChatStorage
from parrot.storage.errors import ConversationDeletedError, StorageWriteError
from parrot.storage.models import ChatStorageTurn

REDIS_URL = os.environ.get("TEST_REDIS_URL", "")
USER, AGENT, SESSION = "u1", "agent-a", "s1"
T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


class DictHotTier(RedisConversation):
    """Real subclass: only the I/O methods are replaced by a dict; `fail_next` injects failures."""

    def __init__(self):
        super().__init__(redis_url="redis://localhost:1/0")       # lazy client, never connected
        self.store: dict = {}
        self.fail_next = 0
        self.calls: list = []

    async def upsert_turn(self, user_id, session_id, turn, chatbot_id=None):
        if self.fail_next:
            self.fail_next -= 1
            raise ConnectionError("hot tier down")
        self.store.setdefault((user_id, session_id, chatbot_id), {})[turn.turn_id] = turn

    async def delete_history(self, user_id, session_id, chatbot_id=None):
        self.calls.append("hot-delete")
        return self.store.pop((user_id, session_id, chatbot_id), None) is not None

    async def get_history(self, *a, **k):
        return None

    async def close(self):
        return None


class RecordingBackend(ConversationSQLiteBackend):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.calls: list = []

    async def put_tombstone(self, *a, **k):
        self.calls.append("tombstone")
        return await super().put_tombstone(*a, **k)

    async def delete_thread_cascade(self, *a, **k):
        self.calls.append("cascade")
        return await super().delete_thread_cascade(*a, **k)


@pytest.fixture
async def backend(tmp_path):
    b = RecordingBackend(path=str(tmp_path / "cold.db"))
    await b.initialize()
    yield b
    await b.close()


@pytest.fixture
def hot():
    return DictHotTier()


@pytest.fixture
def storage(backend, hot):
    s = ChatStorage(redis_conversation=hot, dynamodb=backend)
    s._initialized = True
    return s


def _turn(i=0, session=SESSION, **kw) -> ChatStorageTurn:
    return ChatStorageTurn(turn_id=f"turn-{i}", user_id=USER, session_id=session, agent_id=AGENT, chatbot_id="uuid-1",
                           timestamp=T0 + timedelta(minutes=i), sequence=i + 1, user_message=f"q{i}",
                           assistant_response=f"a{i}", **kw)


def _envelope(turn: ChatStorageTurn) -> EventEnvelope:
    # FILL IN: payload = TASK-5569's TurnCompletedEvent(...).to_dict() built from `turn` (the shape from_event_payload reads) —
    #   bounded by TASK-5569/5573; event_id == turn.turn_id.
    raise NotImplementedError


async def _cold_count(backend, session=SESSION):
    return len(await backend.query_turns(USER, AGENT, session, limit=50))


async def test_store_turn_idempotent_both_tiers(storage, backend, hot):
    hot.fail_next = 1
    with pytest.raises(StorageWriteError):
        await storage.store_turn(_turn())
    assert await _cold_count(backend) == 1 and not hot.store         # cold succeeded, hot did not
    await storage.store_turn(_turn())                                 # replay
    await storage.store_turn(_turn())                                 # duplicate delivery
    assert await _cold_count(backend) == 1
    assert list(hot.store[(USER, SESSION, AGENT)]) == ["turn-0"]      # hot keyed by agent NAME, one copy


async def test_hot_tier_keeps_usage_and_tenant(storage, hot):
    # FILL IN: store a turn whose presentation has usage={"total_tokens": 3}, tenant="t1", model="m" and assert the hot ConversationTurn.metadata
    #   contains them (and NOT output/data/code/sources) — bounded by Key Constraints (hot-tier turn).
    ...


async def test_handler_propagates_retryable(storage, backend, caplog):
    class Down(RecordingBackend):
        async def put_turn(self, *a, **k):
            raise StorageWriteError("disk full")
    down = Down(path=backend._path + ".down")
    await down.initialize()
    failing = ChatStorage(redis_conversation=None, dynamodb=down)
    failing._initialized = True
    with pytest.raises(StorageWriteError):
        await failing.handle_turn_completed(_envelope(_turn()))
    await down.close()
    # terminal: tombstoned session and a malformed payload are acknowledged (no raise) with a WARNING naming the turn id
    await backend.put_tombstone(USER, AGENT, SESSION)
    with caplog.at_level(logging.WARNING):
        await storage.handle_turn_completed(_envelope(_turn()))
        await storage.handle_turn_completed(EventEnvelope(topic="conversation.turn.completed", payload={}, event_id="bad-1"))
    assert "turn-0" in caplog.text and "bad-1" in caplog.text
    assert await _cold_count(backend) == 0


async def test_delete_conversation_tombstone_first(storage, backend, hot):
    await storage.store_turn(_turn())
    backend.calls.clear()
    assert await storage.delete_conversation(USER, SESSION, agent_id=AGENT) is True
    assert backend.calls.index("tombstone") < backend.calls.index("cascade")

    class NoTombstone(RecordingBackend):
        async def put_tombstone(self, *a, **k):
            raise StorageWriteError("cannot commit")
    nt = NoTombstone(path=backend._path + ".nt")
    await nt.initialize()
    s2 = ChatStorage(redis_conversation=hot, dynamodb=nt)
    s2._initialized = True
    await nt.put_turn(USER, AGENT, "s2", "x", _turn(1, session="s2").to_row())
    with pytest.raises(StorageWriteError):
        await s2.delete_conversation(USER, "s2", agent_id=AGENT)
    assert len(await nt.query_turns(USER, AGENT, "s2", limit=5)) == 1   # nothing cleared
    await nt.close()


async def test_delayed_write_after_delete_never_becomes_visible(storage, backend, hot):
    gate = asyncio.Event()

    async def paused_subscriber():
        await gate.wait()                                             # the subscriber is paused before its write
        await storage.handle_turn_completed(_envelope(_turn()))

    task = asyncio.create_task(paused_subscriber())
    await storage.delete_conversation(USER, SESSION, agent_id=AGENT)
    gate.set()
    await task                                                        # terminal: acknowledged, not raised
    assert await _cold_count(backend) == 0 and not hot.store
    assert await storage.load_conversation(USER, SESSION, agent_id=AGENT) == []


async def test_deleted_turn_stays_deleted(storage, backend):
    await storage.store_turn(_turn(0))
    await storage.store_turn(_turn(1))
    assert await storage.delete_turn(SESSION, "turn-0", user_id=USER, agent_id=AGENT) is True
    with pytest.raises(ConversationDeletedError):
        await storage.store_turn(_turn(0))                            # a delayed upsert cannot undo the deletion
    await storage.store_turn(_turn(1))                                # sibling unaffected
    assert await _cold_count(backend) == 1


async def test_delete_between_cold_and_hot_write_is_fenced(backend, hot):
    class DeletesAfterColdWrite(RecordingBackend):
        storage = None
        async def put_turn(self, *a, **k):
            await super().put_turn(*a, **k)
            await self.storage.delete_conversation(USER, SESSION, agent_id=AGENT)   # the delete lands mid-store_turn
    b = DeletesAfterColdWrite(path=backend._path + ".race")
    await b.initialize()
    s = ChatStorage(redis_conversation=hot, dynamodb=b)
    s._initialized = True
    b.storage = s
    with pytest.raises(ConversationDeletedError):
        await s.store_turn(_turn())
    assert not hot.store.get((USER, SESSION, AGENT)) and await b.query_threads(USER, AGENT) == []
    await b.close()


async def test_cleanup_failure_after_tombstone_retried_by_event(storage, hot):
    published, cleaned = [], []

    async def publisher(topic, payload):
        published.append((topic, payload))

    async def cleaner(user_id, agent_name, session_id):
        cleaned.append((user_id, agent_name, session_id))
    storage.attach_deletion_publisher(publisher)
    storage.register_memory_cleaner(cleaner)

    async def boom(*a, **k):
        raise ConnectionError("hot down")
    hot.delete_history = boom
    assert await storage.delete_conversation(USER, SESSION, agent_id=AGENT) in (True, False)   # no raise
    assert published and published[0][1]["session_id"] == SESSION and cleaned
    envelope = EventEnvelope(topic=published[0][0], payload=published[0][1], event_id="d1")
    with pytest.raises(StorageWriteError):
        await storage.handle_conversation_deleted(envelope)           # still failing -> bus retries
    hot.delete_history = DictHotTier.delete_history.__get__(hot)
    await storage.handle_conversation_deleted(envelope)               # fixed -> acknowledged


async def test_public_properties(storage, backend, hot):
    assert storage.cold_backend is backend and storage.hot_redis_client is hot.redis
    with pytest.raises(AttributeError):
        storage.cold_backend = None
    with pytest.raises(AttributeError):
        storage.hot_redis_client = None
    empty = ChatStorage(redis_conversation=None, dynamodb=None)
    assert empty.cold_backend is None and empty.hot_redis_client is None


def test_save_turn_is_removed():
    assert not hasattr(ChatStorage, "save_turn")


async def test_load_conversation_reads_legacy_and_rich_rows(storage, backend):
    # FILL IN: seed one legacy row via backend.put_turn(..., {"user_message","assistant_response","timestamp","tool_calls":[{"name":"x"}]}) and one
    #   store_turn row with tool_invocations/usage; with the hot tier empty assert load_conversation returns both (legacy mapped, rich fields present) —
    #   bounded by TASK-5573 from_row/to_messages.
    ...


@pytest.fixture
async def real_hot():
    if not REDIS_URL:
        pytest.skip("TEST_REDIS_URL not set")
    prefix = f"upsert{uuid.uuid4().hex[:8]}"
    mem = RedisConversation(redis_url=REDIS_URL, key_prefix=prefix)
    yield mem
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    keys = [k async for k in client.scan_iter(match=f"{prefix}*")]
    if keys:
        await client.delete(*keys)
    await client.aclose()
    await mem.close()


async def test_upsert_turn_real_redis(real_hot):
    def ct(i, text):
        return ConversationTurn(turn_id=f"t{i}", user_id=USER, user_message=text, assistant_response="a",
                                timestamp=T0 + timedelta(minutes=i), sequence=i)
    await real_hot.upsert_turn(USER, SESSION, ct(2, "second"), chatbot_id=AGENT)          # creates the history
    await real_hot.upsert_turn(USER, SESSION, ct(1, "first"), chatbot_id=AGENT)           # inserted chronologically
    await real_hot.upsert_turn(USER, SESSION, ct(2, "second-again"), chatbot_id=AGENT)    # replaced, not appended
    history = await real_hot.get_history(USER, SESSION, chatbot_id=AGENT)
    assert [t.turn_id for t in history.turns] == ["t1", "t2"]
    assert history.turns[1].user_message == "second-again"
    await asyncio.gather(*(real_hot.upsert_turn(USER, SESSION, ct(i, "x"), chatbot_id=AGENT) for i in range(3, 13)))
    assert len((await real_hot.get_history(USER, SESSION, chatbot_id=AGENT)).turns) == 12   # concurrent CAS: no lost / duplicate turn
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`).
2. **Read the spec** (`sdd/specs/durable-conversation-memory.spec.md`, §2 "Piece 1" and "Deletion", Modules 3, 4, 9; §5 "Deletion races").
3. **Check dependencies** — TASK-5568, TASK-5573, TASK-5570, TASK-5574 must be `"done"` in `sdd/tasks/index/durable-conversation-memory.json`.
4. **Verify the Codebase Contract** — re-read `chat.py` as TASK-5568 left it (the hot-tier `delete_turn` block), TASK-5573's `ChatStorageTurn`, TASK-5570's error names.
5. **Update status** in the per-spec index -> `"in-progress"` and commit only that file.
6. **Implement** in the Steps order; keep `save_turn` until step 6 so the suite stays runnable; run the Validation Commands, then all six mutation checks (real Redis: `TEST_REDIS_URL=redis://localhost:6379/15`, scratch DB only).
7. **Commit only the seven listed files**; close with `parrot sdd task close TASK-5579 durable-conversation-memory verified`; fill the Completion Note (the falsy-`agent_id` delete caveat).

---

## Completion Note

Replaced ChatStorage.save_turn with store_turn/handle_turn_completed (retryable StorageError propagates, ConversationDeletedError/InvalidTurnPayloadError acknowledged), tombstone-first delete_conversation/delete_turn with post-tombstone cleanup, cleaners, deletion publisher hook, handle_conversation_deleted, cold_backend/hot_redis_client properties, tolerant-reader load_conversation; added RedisConversation.upsert_turn (CAS replace-or-append, both storage modes) + temporary _prepare_turn mirror.

**Completed by**: sdd-worker (sequential fallback)
**Date**: 2026-11-13
**Tests**: new test_chat_storage_subscriber 13 passed — real SQLite cold tier + real RedisConversation against a throw-away `redis-server` subprocess (hash mode and string mode were also checked by a one-off script); ported suites pass: tests/test_chat_storage.py (17), unit/storage/test_chat_hot_tier_metadata + test_delete_turn_hot_tier (4), root tests/storage/test_chat_storage_dynamodb.py + test_integration_artifact_persistence.py (36). ruff clean.
**Mutation evidence**: no tombstone -> RED (3); no post-write fence -> RED; swallow retryable StorageError -> RED; append instead of replace -> RED; hot-tier ordering fields overwritten -> RED after adding the hot-tier assertion (it survived the first time). Restored by re-applying edits.
**Notes / decisions**: (1) test_integration_artifact_persistence.py had a SECOND save_turn caller (test_no_dynamo_save_turn_still_works) not listed in the task; ported too. (2) TASK-5568's `_delete_turn_from_hot_tier` became `_delete_hot_turn`: it now RAISES (callers collect errors and retry through the deletion event) and returns True only when it removed a turn; test_delete_turn_hot_tier's failure test now accepts WARNING-or-higher log. (3) Deleting with an empty agent id tombstones the "" identity and logs a WARNING; it does not fence turns stored under a real agent name (out of scope). (4) handlers/agent.py still calls save_turn until TASK-5584 removes it.

**Deviations from spec**: none
