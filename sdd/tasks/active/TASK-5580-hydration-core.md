# TASK-5580: Hydration core — source interface, sequence allocator, guarded atomic install

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: `sdd/specs/durable-conversation-memory.spec.md` (Module 13)
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-5569, TASK-5579, TASK-5572
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 13 and §2 "Piece 2". After a restart or on a new pod the agent's working memory
(`ConversationHistory`) is empty although ChatStorage holds the transcript. This task builds the
**protocol pieces** the bot (TASK-5583) and the storage adapter (TASK-5582) both depend on, without
touching either:

1. `HydrationSource` (ABC) and its typed outcomes — a failure, a deleted session and an unready index
   are three distinct errors, never `None`/`[]`.
2. `SequenceAllocator` (+ `LocalSequenceAllocator`, `RedisSequenceAllocator`) — the emitter-owned
   monotonic sequence per `(agent, user, session)`, recoverable from the durable maximum after counter loss.
3. `ConversationMemory.install_history` — stage imported turns through the same normalize / count / offload
   steps as `add_turn`, then install the complete history **atomically and only if absent (NX)**; a history
   marked `metadata["hydration"]["state"] == "pending"` counts as absent and gets older turns prepended
   atomically. `RedisConversation`, `InMemoryConversation` and `FileConversationMemory` each implement the
   backend primitive `_install_history`.

This is the design-sensitive part of the feature (spec §3: "staged install + pending-state merge is a
design-sensitive protocol"), which is why it is not delegation-eligible.

---

## Scope

- Create `parrot/memory/hydration.py`: `HydrationError` + 3 subclasses, `HydrationSource`, `SequenceAllocator`,
  `LocalSequenceAllocator`, `RedisSequenceAllocator`.
- `memory/abstract.py`: extract `ConversationMemory._prepare_turn` from `add_turn` (behavior unchanged); add the
  concrete template `install_history`, the abstract `_install_history`, and the shared helpers
  `turn_order_key`, `is_hydration_pending`, `merge_pending_history`.
- `memory/redis.py`: `_install_history` (single atomic Lua script, EXISTS-guarded; CAS merge for the pending case),
  `_history_mapping`, **fix `create_history` so hash mode actually persists** (see "Finding"), delete the
  temporary `_prepare_turn` copy TASK-5579 added.
- `memory/mem.py`, `memory/file.py`: `_install_history` under their in-process lock.
- `memory/__init__.py`: export the new public names.
- Unit tests (real in-memory and file backends; real Redis when `TEST_REDIS_URL` is set).

**NOT in scope**: `ChatStorageHydrationSource` (TASK-5582); `AbstractBot._load_or_hydrate_history`, hydration on the
four call sites, stamping `sequence` on turns (TASK-5583); `RedisConversation.upsert_turn` (TASK-5579); `parts` /
`MessagePart` exports (TASK-5572); the `ConversationTurn.sequence` field itself (TASK-5569).

### Finding the task must act on (verified) — `RedisConversation.create_history` persists nothing in hash mode
`memory/redis.py:159-195`: in the `use_hash_storage` branch `create_history` builds `mapping` but never calls
`redis.hset(key, mapping=mapping)` (only the string-mode branch writes). Consequence today: `get_history()` right after
`create_history()` returns `None`, and `metadata` passed to `create_history` is lost until a turn is appended (and
`_append_turn` only writes `metadata` when a compaction state is given). That silently destroys the
`metadata["hydration"]["state"] = "pending"` marker the bot relies on (spec §3 M15 / §8 Q14) on every Redis-backed bot in
the default hash mode. Fix it here (`await self.redis.hset(key, mapping=mapping)` through the new `_history_mapping`),
and cover it with a test. Report it in the Completion Note (the Redis hash layout is otherwise unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/hydration.py` | CREATE | source ABC, hydration errors, sequence allocators |
| `packages/ai-parrot/src/parrot/memory/abstract.py` | MODIFY | `_prepare_turn` extraction, `install_history`, `_install_history`, merge helpers |
| `packages/ai-parrot/src/parrot/memory/redis.py` | MODIFY | atomic `_install_history`, `_history_mapping`, `create_history` fix, drop the duplicate `_prepare_turn` |
| `packages/ai-parrot/src/parrot/memory/mem.py` | MODIFY | `_install_history` |
| `packages/ai-parrot/src/parrot/memory/file.py` | MODIFY | `_install_history` |
| `packages/ai-parrot/src/parrot/memory/__init__.py` | MODIFY | export hydration public names |
| `packages/ai-parrot/tests/unit/memory/test_hydration_core.py` | CREATE | NX install, pending merge, allocator recovery |

---

## Codebase Contract (Anti-Hallucination)

Re-verified against the tree at `6d564b36a2` (branch `dev`). Paths relative to `packages/ai-parrot/src/parrot/memory/`
unless they start with `packages/`. Line numbers shift once TASK-5569 / 5579 / 5572 land — anchor on the verbatim text.

### Verified Imports
```python
from .abstract import ConversationMemory, ConversationHistory, ConversationTurn   # verified: memory/redis.py:9, mem.py:2, file.py:6
from .compaction.omission import OmissionStore                                    # verified: memory/redis.py:10
from redis.asyncio import Redis                                                   # verified: memory/redis.py:6
from redis.exceptions import WatchError                                           # verified: memory/redis.py:7
from datamodel.parsers.json import json_encoder, json_decoder                     # verified: memory/redis.py:8 (existing serializer imports)
from parrot.memory import ConversationHistory, ConversationTurn, InMemoryConversation, FileConversationMemory, RedisConversation   # verified: memory/__init__.py:3-27 (tests)
from parrot.memory.compaction.models import ToolInvocation                         # verified: memory/compaction/models.py:46 (tests)
```

### Provided by dependency tasks (NOT in the tree yet — re-grep after each lands)
```python
# TASK-5569: ConversationTurn.sequence: Optional[int] = None  (memory/abstract.py, round-trips through to_dict/from_dict)
# TASK-5579: RedisConversation.upsert_turn(...) and a TEMPORARY private RedisConversation._prepare_turn(self, user_id, session_id, turn, chatbot_id=None)
#            that mirrors add_turn's steps — THIS task moves that logic to ConversationMemory and deletes the redis.py copy.
# TASK-5572: memory/__init__.py gains parts exports (anchor edits here must not collide: see Blueprint)
```

### Existing Signatures to Use
```python
# memory/abstract.py
def _provider_prompt_tokens(turn) -> Optional[int]                      # :78
def _preview(text: str, max_chars: int = 200) -> str                    # :61
class ConversationHistory:                                              # :274  session_id, user_id, chatbot_id, turns, created_at, updated_at, metadata
class ConversationMemory(ABC):                                          # :335
    async def add_turn(self, user_id, session_id, turn, chatbot_id=None, *, compaction=None) -> None   # :440
        # body :479-:514 = normalize (Stage 0) -> needs_recount/count_turn -> offload oversize tool outputs ->
        #                  turn.schema_version = 2 -> [compaction state] -> self._store_turn(...)
    async def _store_turn(...)                                          # :516 abstract
    async def get_history / create_history / update_history             # abstract
    self.token_counter, self._normalize, self._oversize_tool_tokens, self.omission_store, self.omission_key(...)

# memory/redis.py
_MERGE_MAX_ATTEMPTS: int = 16                                           # :20
async def _merge_backoff(attempt: int) -> None                          # :34
class RedisConversation(ConversationMemory):                            # :42
    self.redis (redis.asyncio.Redis, decode_responses=True)             # :85
    def _get_key(self, user_id, session_id, chatbot_id=None) -> str     # :117
    def _get_user_sessions_key(self, user_id, chatbot_id=None) -> str
    def _serialize_data(self, data) -> str ; def _deserialize_data(self, data)
    def _supports_cas(self) -> bool                                     # :103
    async def create_history(...)                                       # :159  hash branch builds `mapping` and DOES NOT WRITE IT
    async def _load_history(self, user_id, session_id, chatbot_id=None) -> Optional[ConversationHistory]   # exact key, no fallback
    async def get_history(...)                                          # legacy re-key fallback (FEAT-524)
    async def update_history(self, history) -> None                     # :291
    async def _refresh_ttl(self, user_id, session_id, chatbot_id) -> None   # :475
    async def _append_turn(...)                                         # :493 WATCH/MULTI/EXEC pattern to copy for the pending merge

# memory/mem.py   InMemoryConversation: self._histories[user][chatbot_key][session]; _get_chatbot_key(chatbot_id); update_history stores by key
# memory/file.py  FileConversationMemory: self._lock (asyncio.Lock, NOT reentrant); _read_history/_write_history "caller must hold _lock"
```

### Does NOT Exist
- ~~`parrot.memory.hydration`~~, ~~`ConversationMemory.install_history`~~, ~~`ConversationMemory._install_history`~~, ~~`_prepare_turn` on `ConversationMemory`~~ — created by THIS task.
- ~~`HydrationSource`~~, ~~`SequenceAllocator`~~, ~~`LocalSequenceAllocator`~~, ~~`RedisSequenceAllocator`~~ — created by THIS task.
- ~~Any other subclass of `ConversationMemory`~~ in the repo besides `InMemoryConversation`, `FileConversationMemory`, `RedisConversation` (grep `(ConversationMemory)` over `packages/` and `tests/` is empty otherwise) — making `_install_history` abstract breaks no in-tree subclass. It DOES break out-of-tree custom backends: say so in the docstring.
- ~~`HSETNX` as an NX guard for the whole hash~~ — `_append_turn` creates hashes WITHOUT `session_id` (it writes `turns`/`updated_at`/`chatbot_id` only), so a `session_id`-sentinel `HSETNX` would succeed on an existing key and overwrite its turns. Guard with `EXISTS` inside the Lua script (spec §3 M13 says "HSETNX-guarded"; the NX guarantee is what matters, and this is the form that is correct).
- ~~A way for `parrot.memory` to import `parrot.storage`~~ — memory must stay storage-free (spec §5 "Stores separate").

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/hydration.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/redis.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/mem.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/file.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/memory/test_hydration_core.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/abstract.py#ConversationMemory",
    "sym:packages/ai-parrot/src/parrot/memory/abstract.py#ConversationHistory",
    "sym:packages/ai-parrot/src/parrot/memory/abstract.py#ConversationTurn",
    "sym:packages/ai-parrot/src/parrot/memory/redis.py#RedisConversation",
    "sym:packages/ai-parrot/src/parrot/memory/mem.py#InMemoryConversation",
    "sym:packages/ai-parrot/src/parrot/memory/file.py#FileConversationMemory"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
FEAT-525 template-method pattern: concrete public method on the ABC, abstract private primitive per backend
(`add_turn` / `_store_turn`). WATCH/MULTI/EXEC loop with jittered backoff exactly as `RedisConversation._append_turn`
and `merge_metadata` do (`_MERGE_MAX_ATTEMPTS`, `_merge_backoff`).

### Key Constraints
- **`add_turn` must stay byte-identical in behavior.** `_prepare_turn` is a pure move of the existing steps
  (normalize -> count -> offload -> `schema_version = 2`) including the "does not mutate the caller's turn when
  `normalize=True`" contract. `add_turn` keeps `counter = self.token_counter` for `apply_commit`.
- **Never expose a partial history**: every install is ONE write (Lua `HSET` with all fields / one `SET NX` / one dict
  assignment / one file write). A reader sees `None` or the complete history.
- **Pending = absent, and only pending.** A history with any other state (or no `hydration` key) is "exists" -> return
  `False`; the caller reads the existing one. This marker is the only reason a session with data is hydrated again (spec §6).
- **Merge rule** (`merge_pending_history`): prepend hydrated turns that are strictly older than the existing history's first
  turn by `turn_order_key` AND whose `turn_id` is not already present; keep every other existing metadata key (e.g.
  `compaction`), drop `metadata["hydration"]`; bump `updated_at`. Idempotent: merging twice changes nothing.
- **`turn_order_key`** = `(timestamp as UTC-aware, sequence or 0, turn_id)`; a naive timestamp is treated as UTC (spec §7
  "Timestamps"). It must never raise on mixed naive/aware input.
- Allocators: no TTL on Redis counters (an expiring counter could re-issue a sequence still sitting in the outbox); a counter
  is initialised from `floor()` with `SET NX` then `INCR`, so racing workers converge and stay strictly increasing; the value
  returned is always `> every value issued before` for that key. Floor recovery covers PERSISTED turns only — sequences issued
  but still in the outbox at the moment of counter loss may repeat; `(timestamp, sequence, turn_id)` ordering tolerates that.
- Hot path: `RedisSequenceAllocator.next` is one `EXISTS` + one `INCR` in the steady state, never a scan (spec §7 "Hottest path").
- Do NOT import `parrot.storage` or `parrot.bots` from these modules. Use `self.logger` (exists on `ConversationMemory`).

### References in Codebase
- `memory/redis.py:493-640` (`_append_turn`) — CAS loop shape.
- `memory/redis.py:332-420` (`merge_metadata`) — pure-mutate-function style and `RuntimeError` after exhausted attempts.
- `memory/abstract.py:440-514` — the code being moved.

---

## Implementation Blueprint

### Steps (in order)
1. Re-grep every "Provided by dependency tasks" item and the anchors below — *why*: three upstream tasks touch these files.
2. `abstract.py`: extract `_prepare_turn`, run the existing memory tests unchanged — *why*: prove the refactor is behavior-neutral before adding anything.
3. `abstract.py`: add helpers, `install_history`, abstract `_install_history` — *why*: the template other backends plug into.
4. `mem.py` / `file.py`: `_install_history` — *why*: smallest backends first; they pin the semantics.
5. `redis.py`: `_history_mapping`, `create_history` fix, `_install_history` (+ `_merge_pending`), delete the duplicate `_prepare_turn` — *why*: the atomic one.
6. `hydration.py` + `__init__.py` exports — *why*: independent of 3-5 but consumed by 5583 / 5582.
7. Tests + mutation checks.

### `packages/ai-parrot/src/parrot/memory/abstract.py` (MODIFY) — imports
```python
# occurrences: 1 (verified: grep -c -F 'from datetime import datetime' packages/ai-parrot/src/parrot/memory/abstract.py)
# BEFORE:  from datetime import datetime
# AFTER:   from datetime import datetime, timezone
# occurrences: 1 (verified: grep -c -F 'from typing import TYPE_CHECKING, List, Dict, Any, Optional' packages/ai-parrot/src/parrot/memory/abstract.py)
# AFTER:   from typing import TYPE_CHECKING, List, Dict, Any, Optional, Sequence, Tuple
```
(TASK-5569 may already have edited these two lines — keep whatever it added and only ensure `timezone`, `Sequence`, `Tuple` are present.)

### `packages/ai-parrot/src/parrot/memory/abstract.py` (MODIFY) — module-level helpers
```python
# occurrences: 1 (verified: grep -c -F 'class ConversationMemory(ABC):' packages/ai-parrot/src/parrot/memory/abstract.py)
# AFTER — insert the helpers immediately ABOVE `class ConversationMemory(ABC):` (verified: abstract.py:335)

def turn_order_key(turn: "ConversationTurn") -> Tuple[datetime, int, str]:
    """Chronological sort key: ``(UTC timestamp, sequence or 0, turn_id)``.

    A naive timestamp is treated as UTC (spec FEAT-886 §7). Never raises on mixed naive/aware input.
    """
    stamp = turn.timestamp
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (stamp, turn.sequence if turn.sequence is not None else 0, turn.turn_id)


def is_hydration_pending(metadata: Optional[Dict[str, Any]]) -> bool:
    """``True`` when ``metadata['hydration']['state'] == 'pending'`` (an install may still merge into it)."""
    hydration = (metadata or {}).get("hydration")
    return isinstance(hydration, dict) and hydration.get("state") == "pending"


def merge_pending_history(existing: "ConversationHistory", hydrated: "ConversationHistory") -> "ConversationHistory":
    """Prepend the hydrated turns older than ``existing``'s first turn; clear the pending marker.

    Pure and idempotent. Hydrated turns whose ``turn_id`` already exists, or that are not strictly older than the first
    existing turn, are dropped. Other metadata keys of ``existing`` (e.g. ``compaction``) are preserved.
    """
    # FILL IN: first = turn_order_key(existing.turns[0]) if existing.turns else None; known = {t.turn_id for t in existing.turns};
    #   older = [t for t in hydrated.turns if t.turn_id not in known and (first is None or turn_order_key(t) < first)];
    #   return a NEW ConversationHistory(session_id/user_id/chatbot_id from existing, turns=older + existing.turns,
    #   created_at=existing.created_at, updated_at=datetime.now(), metadata={k: v for k, v in existing.metadata.items() if k != "hydration"})
    #   — bounded by "Merge rule" in Key Constraints (never mutate `existing` or `hydrated`).
    raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/memory/abstract.py` (MODIFY) — `_prepare_turn`, `install_history`, `_install_history`
```python
# occurrences: 1 (verified: grep -c -F '        from .compaction.tokens import count_turn, needs_recount' packages/ai-parrot/src/parrot/memory/abstract.py)
# CHANGE inside `add_turn` (verified: abstract.py:479): MOVE the block from that import line through `turn.schema_version = 2`
# (abstract.py:479-:503) into the new `_prepare_turn` below, and replace it in add_turn with:
#     turn = await self._prepare_turn(user_id, session_id, turn, chatbot_id)
#     counter = self.token_counter
# The rest of add_turn (compaction state via apply_commit(..., counter.name, ...), self._store_turn) is unchanged.

    async def _prepare_turn(
        self, user_id: str, session_id: str, turn: ConversationTurn, chatbot_id: Optional[str] = None
    ) -> ConversationTurn:
        """Stage 0 normalize, Stage 0.5 count, oversize offload, ``schema_version = 2`` — no write.

        Shared by :meth:`add_turn`, :meth:`install_history` and ``RedisConversation.upsert_turn`` so every writer gets the
        same treatment. Returns the (possibly rebound, normalized) turn; the caller's object is untouched when
        ``normalize=True``.
        """
        # FILL IN: the moved body verbatim (the local import of count_turn / needs_recount, normalize_turn when self._normalize,
        #   counting, the offload loop over turn.tool_invocations with self.omission_store.put, the recount after offload,
        #   turn.schema_version = 2) and `return turn` — bounded by "add_turn must stay byte-identical in behavior".
        raise NotImplementedError

    async def install_history(
        self,
        user_id: str,
        session_id: str,
        turns: Sequence[ConversationTurn],
        chatbot_id: Optional[str] = None,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Stage ``turns`` through the ``add_turn`` steps, then install the complete history only if none exists.

        Returns ``True`` when this call installed it, ``False`` when a history already existed (the caller then reads the
        existing one). Never exposes a partial history. A history whose ``metadata['hydration']['state'] == 'pending'``
        counts as absent: staged turns older than its first turn are prepended atomically.

        Custom ``ConversationMemory`` subclasses must now implement :meth:`_install_history`.
        """
        staged: List[ConversationTurn] = []
        for turn in turns:
            staged.append(await self._prepare_turn(user_id, session_id, turn, chatbot_id))
        history = ConversationHistory(
            session_id=session_id, user_id=user_id, chatbot_id=chatbot_id, turns=staged, metadata=dict(metadata or {})
        )
        return await self._install_history(history)

    @abstractmethod
    async def _install_history(self, history: ConversationHistory) -> bool:
        """Backend primitive: write ``history`` iff the key is absent (or its hydration state is pending). ONE write.

        Returns ``True`` when written (fresh install or pending merge), ``False`` when a non-pending history exists.
        """
```
**Why**: `_prepare_turn` is the single definition of "what write-time treatment a turn gets"; `install_history` is concrete so
custom backends implement only the private primitive (spec §7 "Template method"). Do NOT change `add_turn`'s signature or docstring contract.

### `packages/ai-parrot/src/parrot/memory/mem.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'from typing import Dict, List, Optional, Any, TYPE_CHECKING' packages/ai-parrot/src/parrot/memory/mem.py)
# BEFORE: from typing import Dict, List, Optional, Any, TYPE_CHECKING   AFTER: add a line above it:  import asyncio
# occurrences: 1 (verified: grep -c -F '        self._histories: Dict[str, Dict[str, Dict[str, ConversationHistory]]] = {}' packages/ai-parrot/src/parrot/memory/mem.py)
# AFTER — insert below it (inside __init__):
        self._install_lock = asyncio.Lock()
# occurrences: 1 (verified: grep -c -F 'async def _store_turn(' packages/ai-parrot/src/parrot/memory/mem.py)
# AFTER — add as a new method below `_store_turn` (verified: mem.py:78):

    async def _install_history(self, history: ConversationHistory) -> bool:
        """Install ``history`` iff absent (or pending) — one dict assignment under an in-process lock."""
        async with self._install_lock:
            existing = await self.get_history(history.user_id, history.session_id, history.chatbot_id)
            # FILL IN: existing is None -> `await self.update_history(history)`; return True. Pending
            #   (is_hydration_pending(existing.metadata)) -> `await self.update_history(merge_pending_history(existing, history))`; return True.
            #   Otherwise return False — bounded by "Pending = absent, and only pending". Import the two helpers from .abstract.
            raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/memory/file.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'async def _store_turn(' packages/ai-parrot/src/parrot/memory/file.py)
# AFTER — add as a new method below `_store_turn` (verified: file.py:144). `self._lock` is NOT reentrant: use the inlined
# _read_history / _write_history (caller holds the lock), never get_history / update_history.

    async def _install_history(self, history: ConversationHistory) -> bool:
        """Install ``history`` iff absent (or pending) — one file write under ``self._lock``."""
        async with self._lock:
            existing = await self._read_history(history.user_id, history.session_id, history.chatbot_id)
            if existing is None and history.chatbot_id:
                if await self._read_history(history.user_id, history.session_id, None) is not None:
                    return False  # a legacy un-segmented history exists; get_history() re-keys it on the next read
            # FILL IN: existing is None -> `await self._write_history(history)`; return True. Pending -> write
            #   merge_pending_history(existing, history); return True. Otherwise return False — bounded by "Pending = absent, and only pending".
            raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/memory/redis.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F '_MERGE_MAX_ATTEMPTS: int = 16' packages/ai-parrot/src/parrot/memory/redis.py)
# AFTER — add below the `_merge_backoff` function (verified: redis.py:34-41), module level:
_INSTALL_NX_LUA = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
redis.call('HSET', KEYS[1], unpack(ARGV))
return 1
"""

# occurrences: 1 (verified: grep -c -F 'async def create_history(' packages/ai-parrot/src/parrot/memory/redis.py)
# CHANGE (verified: redis.py:159-195): in the `use_hash_storage` branch, build `mapping = self._history_mapping(history)` and ADD
#     await self.redis.hset(key, mapping=mapping)
# (the string-mode branch already writes). Keep the sadd + _refresh_ttl calls that follow.

# occurrences: 1 (verified: grep -c -F 'async def update_history(self, history: ConversationHistory) -> None:' packages/ai-parrot/src/parrot/memory/redis.py)
# AFTER — add these methods ABOVE `update_history` (verified: redis.py:291):

    def _history_mapping(self, history: ConversationHistory) -> Dict[str, str]:
        """The hash fields of one history (single source for create / install / merge)."""
        data = history.to_dict()
        mapping = {
            "session_id": str(data["session_id"]),
            "user_id": str(data["user_id"]),
            "turns": self._serialize_data(data["turns"]),
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
            "metadata": self._serialize_data(data["metadata"]),
        }
        if data.get("chatbot_id") is not None:
            mapping["chatbot_id"] = str(data["chatbot_id"])
        return mapping

    async def _install_history(self, history: ConversationHistory) -> bool:
        """Atomic NX install (single Lua script in hash mode, ``SET NX`` in string mode); pending histories merge by CAS."""
        key = self._get_key(history.user_id, history.session_id, history.chatbot_id)
        # FILL IN: (a) when history.chatbot_id is set, the segmented key is absent and the LEGACY un-segmented key exists, call
        #   `await self.get_history(...)` (FEAT-524 re-key) and return False — never shadow a legacy history.
        #   (b) hash mode: flat = [x for item in self._history_mapping(history).items() for x in item];
        #   installed = bool(await self.redis.eval(_INSTALL_NX_LUA, 1, key, *flat)); string mode:
        #   installed = bool(await self.redis.set(key, self._serialize_data(history.to_dict()), nx=True)).
        #   (c) installed -> sadd the user-sessions set, `await self._refresh_ttl(...)`, return True; else
        #   `return await self._merge_pending(key, history)` — bounded by "Never expose a partial history".
        raise NotImplementedError

    async def _merge_pending(self, key: str, history: ConversationHistory) -> bool:
        """CAS-merge ``history`` into an existing PENDING history; ``False`` when the existing one is not pending."""
        for attempt in range(_MERGE_MAX_ATTEMPTS):
            async with self.redis.pipeline() as pipe:
                try:
                    await pipe.watch(key)
                    existing = await self._load_history(history.user_id, history.session_id, history.chatbot_id)
                    # FILL IN: existing None -> merged = history; existing pending -> merged = merge_pending_history(existing, history);
                    #   else `await pipe.unwatch()` and return False. pipe.multi(); hash mode `pipe.hset(key, mapping=self._history_mapping(merged))`
                    #   / string mode `pipe.set(key, self._serialize_data(merged.to_dict()))`; `await pipe.execute()`;
                    #   `await self._refresh_ttl(...)`; return True — bounded by "Pending = absent, and only pending".
                    raise NotImplementedError
                except WatchError:
                    pass
            await _merge_backoff(attempt)
        raise RuntimeError(f"history install for {key} still conflicting after {_MERGE_MAX_ATTEMPTS} attempts")

# CHANGE (cross-task): DELETE the temporary `RedisConversation._prepare_turn` that TASK-5579 added (it is now inherited from
# ConversationMemory with the same signature). Re-run `grep -n "_prepare_turn" packages/ai-parrot/src/parrot/memory/redis.py`:
# the only remaining hits must be call sites (e.g. inside upsert_turn).
```
`_supports_cas()` False (non-transactional test doubles): `_merge_pending` must fall back to an unguarded read-merge-write, as `_merge_metadata_unguarded` does — FILL IN, small.

### `packages/ai-parrot/src/parrot/memory/hydration.py` (CREATE)
```python
"""Hydration protocol: source interface, typed outcomes and sequence allocation (FEAT-886 M13).

The bot consults an injected :class:`HydrationSource` on a history miss and never imports ``ChatStorage``.
This module defines no storage logic; ``parrot.storage.hydration.ChatStorageHydrationSource`` implements it.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from .abstract import ConversationTurn


class HydrationError(Exception):
    """Base class for hydration outcomes that are neither a hit nor an empty history."""


class HydrationUnavailableError(HydrationError):
    """The source could not be read (transport / backend failure). Retryable on a later round."""


class HydrationNotReadyError(HydrationError):
    """The chronological index is not backfilled yet. Retryable once the backfill completes."""


class SessionDeletedError(HydrationError):
    """The conversation identity is tombstoned. Terminal: never hydrate, never retry."""


class HydrationSource(ABC):
    """Where a bot fetches a budget-sized window of past turns on a history miss."""

    @abstractmethod
    async def load_turns(
        self, agent_name: str, user_id: str, session_id: str, max_turns: int
    ) -> Optional[List[ConversationTurn]]:
        """Newest ``max_turns`` turns, ascending. ``None`` = active session with no retained turns.

        Raises one of the three :class:`HydrationError` subclasses; never returns ``[]`` or ``None`` for a failure,
        a deleted session or an unready index.
        """

    @abstractmethod
    async def is_deleted(self, agent_name: str, user_id: str, session_id: str) -> bool:
        """Authoritative deletion guard. Raises :class:`HydrationUnavailableError` if it cannot be determined."""

    @abstractmethod
    async def max_sequence(self, agent_name: str, user_id: str, session_id: str) -> int:
        """Durable maximum sequence for the session (0 when none), for allocator recovery."""


class SequenceAllocator(ABC):
    """Monotonic per-``(agent, user, session)`` sequence shared by every worker."""

    @abstractmethod
    async def next(
        self,
        agent_name: str,
        user_id: str,
        session_id: str,
        *,
        floor: Optional[Callable[[], Awaitable[int]]] = None,
    ) -> int:
        """Next sequence, strictly greater than every value issued before.

        When the counter does not exist it is initialised from ``floor()`` (the durable maximum).
        """


class LocalSequenceAllocator(SequenceAllocator):
    """Per-process allocator for in-memory / file memory (no cross-worker guarantee)."""

    def __init__(self) -> None:
        self._counters: Dict[Tuple[str, str, str], int] = {}
        self._locks: Dict[Tuple[str, str, str], asyncio.Lock] = {}

    async def next(self, agent_name, user_id, session_id, *, floor=None) -> int:
        # FILL IN: per-key asyncio.Lock (setdefault); under it, initialise the counter from `max(0, await floor())` (or 0) only when
        #   absent, then increment and return — bounded by "strictly greater than every value issued before" and AC floor recovery.
        raise NotImplementedError


class RedisSequenceAllocator(SequenceAllocator):
    """``INCR``-based allocator shared across workers; recovers from the durable maximum after counter loss."""

    def __init__(self, redis_client: Any, *, key_prefix: str = "conversation") -> None:
        self._redis = redis_client
        self._key_prefix = key_prefix

    def _key(self, agent_name: str, user_id: str, session_id: str) -> str:
        return f"{self._key_prefix}:seq:{agent_name}:{user_id}:{session_id}"

    async def next(self, agent_name, user_id, session_id, *, floor=None) -> int:
        # FILL IN: key = self._key(...); when `floor is not None and not await self._redis.exists(key)`: base = max(0, int(await floor()));
        #   `await self._redis.set(key, base, nx=True)`; then `return int(await self._redis.incr(key))`. NO TTL — bounded by Key Constraints
        #   (steady state = one EXISTS + one INCR).
        raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/memory/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'from .redis import RedisConversation' packages/ai-parrot/src/parrot/memory/__init__.py)
# AFTER — insert below `from .redis import RedisConversation` (verified: __init__.py:26) (anchored here, NOT on the `.render` line TASK-5572 edits):
from .hydration import (
    HydrationError,
    HydrationNotReadyError,
    HydrationSource,
    HydrationUnavailableError,
    LocalSequenceAllocator,
    RedisSequenceAllocator,
    SequenceAllocator,
    SessionDeletedError,
)
# occurrences: 1 (verified: grep -c -F '    "HistoryMessage",' packages/ai-parrot/src/parrot/memory/__init__.py)
# AFTER — insert below `    "HistoryMessage",` in __all__ (verified: __init__.py:~99) the eight names above as quoted strings.
```
**Why this shape**: signatures/names are fixed by spec §3 M13. The Lua script is the only construct that makes "check absent + write
all fields" atomic on the Redis hash layout; the pending merge cannot be a script because it must decode and re-encode JSON, so it
is a WATCH/MULTI/EXEC loop like the rest of the file. Do NOT make `install_history` abstract, do NOT write a history in more than one
command, do NOT let `merge_pending_history` mutate its inputs.

### FILL IN checklist
- [ ] `abstract.py::merge_pending_history` — the merge rule; bounded by Key Constraints and `test_install_merges_pending`.
- [ ] `abstract.py::_prepare_turn` — verbatim move; bounded by "add_turn must stay byte-identical".
- [ ] `mem.py::_install_history` / `file.py::_install_history` — three-way branch; bounded by "Pending = absent, and only pending".
- [ ] `redis.py::_install_history` — legacy re-key check, hash vs string mode, post-install bookkeeping; bounded by "Never expose a partial history".
- [ ] `redis.py::_merge_pending` — CAS body incl. the `_supports_cas()` False fallback; bounded by `_append_turn` pattern.
- [ ] `redis.py::create_history` — the missing `hset`; bounded by the "Finding".
- [ ] `hydration.py::LocalSequenceAllocator.next`, `RedisSequenceAllocator.next` — floor recovery; bounded by AC `test_sequence_allocator_recovers_floor`.
- [ ] Tests: the Redis-marked cases need `TEST_REDIS_URL`; the in-process cases must always run.

---

## Acceptance Criteria

- [ ] Concurrent installs: exactly one `True`, the rest `False`; the stored history equals the winner's turns in full; a concurrent reader only ever sees `None` or the complete history (spec §4 `test_install_history_nx_<backend>`; spec §5 "Hydration once").
- [ ] A `pending` history gets older hydrated turns prepended atomically, `metadata['hydration']` removed, other metadata kept, duplicates by `turn_id` and newer turns excluded (spec §4 `test_install_merges_pending`).
- [ ] Installed turns carry the same write-time treatment as `add_turn` (normalized, token-counted, oversize output offloaded, `schema_version == 2`) (spec §3 M13 "stage … through the add_turn steps").
- [ ] `add_turn` behavior is unchanged: the existing memory suites pass untouched (Validation Commands).
- [ ] `create_history` + `get_history` round-trips the metadata in hash mode (the "Finding"); string mode unchanged.
- [ ] `LocalSequenceAllocator` / `RedisSequenceAllocator`: strictly increasing and unique under concurrency; after counter loss the next value exceeds the durable maximum (spec §4 `test_sequence_allocator_recovers_floor`; spec §5 "Sequence allocation continues above the durable maximum after a restart").
- [ ] The three `HydrationError` subclasses derive from `HydrationError`; `HydrationSource` and `SequenceAllocator` are not instantiable; a `ConversationMemory` subclass without `_install_history` is not instantiable.
- [ ] `parrot.memory` imports nothing from `parrot.storage` / `parrot.bots` (grep clean).
- [ ] **Mutation checks** (revert, see RED, restore by re-applying — never `git checkout`): (1) make `InMemoryConversation._install_history` always write -> `test_install_history_nx_inmemory` goes RED; (2) make `merge_pending_history` ignore the `turn_id` dedupe -> `test_install_merges_pending` goes RED; (3) in `RedisConversation._install_history` replace `EXISTS` with an unconditional `HSET` (or `SET` without `nx=True`) -> the Redis NX test goes RED; (4) ignore `floor` in `LocalSequenceAllocator.next` -> `test_sequence_allocator_recovers_floor` goes RED; (5) remove the new `hset` in `create_history` -> `test_create_history_persists_metadata_hash_mode` goes RED.
- [ ] `ruff check` is clean on every touched file; `from parrot.memory import HydrationSource, SequenceAllocator, SessionDeletedError` works.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/memory/test_hydration_core.py -q`
- `pytest packages/ai-parrot/tests/unit/memory/test_history_ownership.py -q`
- `pytest packages/ai-parrot/tests/unit/memory/test_redis_history_ttl.py -q`
- `pytest packages/ai-parrot/tests/unit/memory/compaction/test_integration_round_trip.py -q`

---

## Test Specification

Real `InMemoryConversation`, `FileConversationMemory(tmp_path)` and, when `TEST_REDIS_URL` is set, a real `RedisConversation`
(prefix-scoped cleanup, as in `tests/unit/memory/test_redis_history_ttl.py`). No `Mock` for the memory backends.

```python
# packages/ai-parrot/tests/unit/memory/test_hydration_core.py
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from redis.asyncio import Redis

from parrot.memory import (
    ConversationHistory, ConversationMemory, ConversationTurn, FileConversationMemory, HydrationError,
    HydrationNotReadyError, HydrationSource, HydrationUnavailableError, InMemoryConversation, LocalSequenceAllocator,
    RedisConversation, RedisSequenceAllocator, SequenceAllocator, SessionDeletedError)
from parrot.memory.compaction.models import ToolInvocation

REDIS_URL = os.environ.get("TEST_REDIS_URL", "")
T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
U, S, BOT = "u1", "s1", "bot-1"


def _turn(i: int, **kw) -> ConversationTurn:
    return ConversationTurn(turn_id=f"t{i:03d}", user_id=U, user_message=f"q{i}", assistant_response=f"a{i}",
                            timestamp=T0 + timedelta(minutes=i), chatbot_id=BOT, sequence=i, **kw)


@pytest.fixture(params=["memory", "file", "redis"])
async def memory(request, tmp_path):
    if request.param == "memory":
        yield InMemoryConversation()
    elif request.param == "file":
        yield FileConversationMemory(base_path=str(tmp_path / "conv"))
    else:
        if not REDIS_URL:
            pytest.skip("TEST_REDIS_URL not set")
        prefix = f"hyd{uuid.uuid4().hex[:8]}"
        mem = RedisConversation(redis_url=REDIS_URL, key_prefix=prefix)
        yield mem
        client = Redis.from_url(REDIS_URL, decode_responses=True)
        keys = [k async for k in client.scan_iter(match=f"{prefix}*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()
        await mem.close()


async def test_install_history_installs_once(memory):
    assert await memory.install_history(U, S, [_turn(0), _turn(1)], chatbot_id=BOT) is True
    history = await memory.get_history(U, S, chatbot_id=BOT)
    assert [t.turn_id for t in history.turns] == ["t000", "t001"]
    assert all(t.schema_version == 2 and t.token_count is not None for t in history.turns)   # add_turn treatment
    assert await memory.install_history(U, S, [_turn(9)], chatbot_id=BOT) is False
    assert [t.turn_id for t in (await memory.get_history(U, S, chatbot_id=BOT)).turns] == ["t000", "t001"]


async def test_install_history_nx_concurrent(memory):                 # spec test_install_history_nx_<backend>
    candidates = [[_turn(i * 10 + j) for j in range(4)] for i in range(8)]
    seen = set()

    async def reader():
        for _ in range(200):
            h = await memory.get_history(U, S, chatbot_id=BOT)
            seen.add(None if h is None else len(h.turns))
            await asyncio.sleep(0)

    results, _ = await asyncio.gather(
        asyncio.gather(*(memory.install_history(U, S, turns, chatbot_id=BOT) for turns in candidates)), reader())
    assert results.count(True) == 1
    stored = [t.turn_id for t in (await memory.get_history(U, S, chatbot_id=BOT)).turns]
    assert stored in [[t.turn_id for t in c] for c in candidates]    # the winner's history, complete
    assert seen <= {None, 4}                                         # never partial


async def test_install_stages_like_add_turn(memory):
    big = ToolInvocation(tool_name="sql", input={}, output="x" * 200_000)
    await memory.install_history(U, S, [_turn(0, tool_invocations=[big])], chatbot_id=BOT)
    stored = (await memory.get_history(U, S, chatbot_id=BOT)).turns[0].tool_invocations[0]
    # FILL IN: assert the oversize output was offloaded exactly as add_turn does (stored.omitted has "output",
    #   output_chars == 200_000, output is the short preview) — bounded by spec §3 M13.
    assert "output" in stored.omitted


async def test_install_merges_pending(memory):                        # spec test_install_merges_pending
    await memory.create_history(U, S, metadata={"hydration": {"state": "pending"}, "compaction": {"k": 1}}, chatbot_id=BOT)
    await memory.add_turn(U, S, _turn(5), chatbot_id=BOT)             # a round that ran while hydration was unavailable
    window = [_turn(2), _turn(3), _turn(4), _turn(5), _turn(8)]        # 5 is a duplicate, 8 is newer than the first existing turn
    assert await memory.install_history(U, S, window, chatbot_id=BOT) is True
    history = await memory.get_history(U, S, chatbot_id=BOT)
    assert [t.turn_id for t in history.turns] == ["t002", "t003", "t004", "t005"]
    assert "hydration" not in history.metadata and history.metadata.get("compaction") == {"k": 1}
    assert await memory.install_history(U, S, window, chatbot_id=BOT) is False   # no longer pending


async def test_create_history_persists_metadata_hash_mode(memory):    # the "Finding" (hash mode); trivially true elsewhere
    await memory.create_history(U, "s-meta", metadata={"hydration": {"state": "pending"}}, chatbot_id=BOT)
    history = await memory.get_history(U, "s-meta", chatbot_id=BOT)
    assert history is not None and history.metadata == {"hydration": {"state": "pending"}}


async def test_pending_merge_is_atomic_against_a_concurrent_turn():
    if not REDIS_URL:
        pytest.skip("TEST_REDIS_URL not set")
    # FILL IN: Redis only — create a pending history, then gather(install_history(window), add_turn(new_turn)); assert both the
    #   window and the new turn survive in order (the CAS loop retried instead of clobbering) — bounded by "Never expose a partial history".


@pytest.mark.parametrize("make", [LocalSequenceAllocator, "redis"])
async def test_sequence_allocator_recovers_floor(make):               # spec test_sequence_allocator_recovers_floor
    if make == "redis":
        if not REDIS_URL:
            pytest.skip("TEST_REDIS_URL not set")
        client = Redis.from_url(REDIS_URL, decode_responses=True)
        alloc: SequenceAllocator = RedisSequenceAllocator(client, key_prefix=f"seq{uuid.uuid4().hex[:8]}")
    else:
        alloc = make()
    calls = []

    async def floor() -> int:
        calls.append(1)
        return 41

    first = await alloc.next("agent", U, S, floor=floor)
    assert first == 42                                                # exceeds the durable maximum
    assert await alloc.next("agent", U, S, floor=floor) == 43
    assert len(calls) == 1                                            # floor only consulted when the counter is absent
    values = await asyncio.gather(*(alloc.next("agent", U, S) for _ in range(25)))
    assert len(set(values)) == 25 and min(values) > 43                # unique, strictly above everything issued
    # FILL IN: simulate counter loss with a NEW allocator (Local) / a deleted key (Redis) and a floor of 100 -> next == 101 —
    #   bounded by spec §5 "Sequence allocation continues above the durable maximum after a restart".


def test_hydration_contract_types():
    assert all(issubclass(c, HydrationError) for c in (HydrationUnavailableError, HydrationNotReadyError, SessionDeletedError))
    with pytest.raises(TypeError):
        HydrationSource()
    with pytest.raises(TypeError):
        SequenceAllocator()

    class NoInstall(ConversationMemory):                              # implements everything EXCEPT _install_history
        async def create_history(self, *a, **k): ...
        async def get_history(self, *a, **k): ...
        async def update_history(self, *a, **k): ...
        async def _store_turn(self, *a, **k): ...
        async def clear_history(self, *a, **k): ...
        async def list_sessions(self, *a, **k): ...
        async def delete_history(self, *a, **k): ...
    with pytest.raises(TypeError):
        NoInstall()
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`).
2. **Read the spec** (`sdd/specs/durable-conversation-memory.spec.md`, Modules 9, 13, 15; §6 "Hydration while the source is unavailable"; §8 Q14).
3. **Check dependencies** — TASK-5569, TASK-5579, TASK-5572 must be `"done"` in `sdd/tasks/index/durable-conversation-memory.json`.
4. **Verify the Codebase Contract** — re-read `abstract.py` (`add_turn`), `redis.py` (`create_history`, TASK-5579's `_prepare_turn`/`upsert_turn`) and `__init__.py` as merged; if any anchor count is not 1, stop and update the task first.
5. **Update status** in the per-spec index -> `"in-progress"` and commit only that file.
6. **Implement** in the Steps order, run the existing memory suites after step 2 (refactor must be neutral), then the Validation Commands and all five mutation checks. Real Redis: `TEST_REDIS_URL=redis://localhost:6379/15 pytest ...` on a scratch database only.
7. **Commit only the seven listed files**; close with `parrot sdd task close TASK-5580 durable-conversation-memory verified`; fill the Completion Note (mention the `create_history` finding).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
