# TASK-2822: Omission store (`OmissionStore` ABC + InMemory / Redis / File backends)

**Feature**: FEAT-525 — Per-Turn Conversation Compaction
**Spec**: `sdd/specs/per-turn-conversation-compaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2819
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 and constraint C6 (lossless pruning) plus the resolved
decisions "Who owns the OmissionStore" (the memory backend), "Linking
omissions to `turn_id`" (secondary index), and "`omission_ttl` default"
(`None`). Everything pruned or offloaded lands here, content-addressed, and
is read back by `read_omitted_content` (TASK-2829). This task delivers the
store only; ownership wiring into `ConversationMemory` is TASK-2826.

---

## Scope

- Create `parrot/memory/compaction/omission.py` with:
  - `def content_id(content: str) -> str`: `"om_" + hashlib.blake2b(content.encode("utf-8"), digest_size=8).hexdigest()` (16 hex chars).
  - `EXPIRED_MESSAGE: str` — `"Omitted content {content_id} is unknown or may have expired — re-run the tool to regenerate it."` (format with the id).
  - `class OmissionStore(ABC)` with `ttl: Optional[int]` (seconds, default `None`) and the abstract coroutines `put(session_key, content, *, turn_id=None) -> str`, `get(session_key, content_id) -> Optional[str]`, `list_by_turn(session_key, turn_id) -> List[str]`, `clear(session_key) -> None`; concrete `put_many(session_key, omissions: Sequence[Omission]) -> None` looping over `put(..., turn_id=o.turn_id)`.
  - `class InMemoryOmissionStore`: `dict[session_key][content_id] = content`, `dict[session_key]["__turns__"][turn_id] = [ids]` (or two dicts).
  - `class RedisOmissionStore(redis_client, *, key_prefix="conversation", ttl=None)`: content hash at `f"{key_prefix}_omitted:{session_key}"` (`hset field=content_id value=content`, `hget`), turn index hash at `f"{key_prefix}_omitted_turns:{session_key}"` (`hget/hset` of a JSON list, append without duplicates); `expire` on both keys **only** when `ttl` is set; `clear` deletes both keys. Accept an already-constructed async Redis client (the one `RedisConversation` owns) — never open a second connection.
  - `class FileOmissionStore(base_path, *, ttl=None)`: `{base_path}/_omitted/{safe(session_key)}/{content_id}.txt` plus `index.json` mapping `turn_id → [ids]`; `safe()` replaces `:`/`/` with `__`; `ttl` ignored with a debug log (file backend has no expiry).
  - `put` is idempotent: same content ⇒ same id, no duplicate index entries.
- Tests for all three backends (parametrized), Redis skipped when unreachable.

**NOT in scope**: constructing the store inside the memory backends and the clear/delete cascade (TASK-2826); the recovery tool (TASK-2829).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/compaction/omission.py` | CREATE | ABC + three backends + `content_id` + `EXPIRED_MESSAGE` |
| `packages/ai-parrot/tests/unit/memory/compaction/test_omission_store.py` | CREATE | parametrized backend tests, ttl behavior, cross-session isolation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.memory.compaction.models import Omission                     # created by TASK-2819
import hashlib, json, asyncio                                             # stdlib (blake2b, index JSON, file lock)
from pathlib import Path
from redis.asyncio import Redis                                           # verified: memory/redis.py imports `Redis` and calls Redis.from_url(..., decode_responses=True) at :22-28
from parrot.memory.redis import RedisConversation                         # verified: memory/redis.py:10 (tests: reuse its .redis client)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/redis.py  (dev a824f6535)
class RedisConversation(ConversationMemory):                              # 10
    def __init__(self, redis_url=None, key_prefix="conversation", use_hash_storage=True)   # 13-28
    self.redis = Redis.from_url(self.redis_url, decode_responses=True, encoding="utf-8", ...)   # 22-28  ← the client to share
    self.key_prefix = key_prefix                                          # 20
    def _get_key(self, user_id, session_id, chatbot_id=None) -> str      # 31-42  "{prefix}[:{chatbot_id}]:{user}:{session}"
    await self.redis.hset(key, mapping=mapping)                           # 222 (hash usage precedent)
    # :490 — commented-out `expire` on an index key; NO expire on history keys anywhere

# packages/ai-parrot/src/parrot/memory/file.py
class FileConversationMemory(ConversationMemory):                         # 9
    def __init__(self, base_path: str = "./conversations")                # 12  self.base_path = Path(base_path); self._lock = asyncio.Lock()
    def _get_file_path(...)                                               # 17

# Redis-fixture precedent for tests: packages/ai-parrot/tests/test_chat_storage.py (uses RedisConversation)
```

### Does NOT Exist
- ~~`parrot.memory.compaction.omission`~~ — this task creates it.
- ~~`OmissionStore` / any omission or "tombstone" store under `parrot/`~~ — none.
- ~~`WorkingMemoryToolkit` as the omission surface~~ — rejected (brainstorm Option D); FEAT-380's tee (`tools/compression/tee.py`) is process-local and not turn-keyed; do not import it here.
- ~~A TTL on `RedisConversation` history keys~~ — none exists; `ttl` here is independent and defaults to `None`.
- ~~`ConversationMemory.omission_store`~~ — added by TASK-2826, not here.
- ~~`fakeredis` in dev dependencies~~ — not verified; follow `tests/test_chat_storage.py`'s approach and `pytest.skip` when Redis is unreachable.

---

## Implementation Notes

### Pattern to Follow
```python
class RedisOmissionStore(OmissionStore):
    def __init__(self, redis: "Redis", *, key_prefix: str = "conversation", ttl: Optional[int] = None) -> None:
        self._redis = redis; self._prefix = key_prefix; self.ttl = ttl
    def _ckey(self, session_key: str) -> str: return f"{self._prefix}_omitted:{session_key}"
    def _tkey(self, session_key: str) -> str: return f"{self._prefix}_omitted_turns:{session_key}"
    async def put(self, session_key, content, *, turn_id=None) -> str:
        cid = content_id(content)
        await self._redis.hset(self._ckey(session_key), cid, content)
        if turn_id: ...append cid to the JSON list under turn_id if missing...
        if self.ttl is not None:
            await self._redis.expire(self._ckey(session_key), self.ttl); await self._redis.expire(self._tkey(session_key), self.ttl)
        return cid
```

### Key Constraints
- Async throughout; the file backend guards writes with an `asyncio.Lock` like `FileConversationMemory`.
- `session_key` is opaque here (`"{memory_key_id}:{user}:{session}"` is composed by the memory in TASK-2826).
- `get` for an unknown id returns `None` — the caller formats `EXPIRED_MESSAGE`.
- Logging via `logging.getLogger(__name__)`; no `print`.

### References in Codebase
- `packages/ai-parrot/src/parrot/memory/redis.py:193-228` — hash write pattern.
- `packages/ai-parrot/src/parrot/memory/file.py:12-30` — file layout + lock pattern.

---

## Acceptance Criteria

- [ ] `content_id("x")` starts with `om_` and has 16 hex chars; equal content ⇒ equal id.
- [ ] For each backend: `put` → `get` returns the bytes; unknown id ⇒ `None`; `list_by_turn` returns ids in insertion order without duplicates after a repeated `put`; `clear` empties both content and index; a different `session_key` cannot see the id.
- [ ] Redis backend calls `expire` on neither key when `ttl is None`, and on both when `ttl=60` (assert with a recording fake client).
- [ ] `put_many` stores every `Omission` under its `turn_id`.
- [ ] All tests pass: `timeout -s KILL 300 pytest packages/ai-parrot/tests/unit/memory/compaction/test_omission_store.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/compaction/omission.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/memory/compaction/test_omission_store.py
import pytest
from parrot.memory.compaction.models import Omission
from parrot.memory.compaction.omission import (
    FileOmissionStore, InMemoryOmissionStore, RedisOmissionStore, content_id,
)


class _RecordingRedis:
    """Minimal async fake: hset/hget/hdel/delete/expire over dicts; records expire calls."""
    ...


@pytest.fixture(params=["memory", "file", "redis"])
def store(request, tmp_path):
    if request.param == "memory": return InMemoryOmissionStore()
    if request.param == "file": return FileOmissionStore(tmp_path)
    return RedisOmissionStore(_RecordingRedis(), key_prefix="conversation")


async def test_put_get_list_clear_isolated(store):
    cid = await store.put("bot:u:s", "payload", turn_id="t1")
    assert cid == content_id("payload") and await store.get("bot:u:s", cid) == "payload"
    assert await store.put("bot:u:s", "payload", turn_id="t1") == cid
    assert await store.list_by_turn("bot:u:s", "t1") == [cid]
    assert await store.get("bot:u:other", cid) is None
    await store.clear("bot:u:s")
    assert await store.get("bot:u:s", cid) is None and await store.list_by_turn("bot:u:s", "t1") == []


async def test_redis_ttl_none_default_no_expire():
    fake = _RecordingRedis()
    await RedisOmissionStore(fake).put("k", "c", turn_id="t")
    assert fake.expire_calls == []
    await RedisOmissionStore(fake, ttl=60).put("k", "c", turn_id="t")
    assert len(fake.expire_calls) == 2


async def test_put_many(store):
    await store.put_many("k", [Omission(content_id("a"), "a", "t1", "q", "output"),
                               Omission(content_id("b"), "b", "t1", "q", "output")])
    assert await store.list_by_turn("k", "t1") == [content_id("a"), content_id("b")]
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2819 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code; update it first if anything changed
4. **Update status** in `sdd/tasks/index/per-turn-conversation-compaction.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2822-omission-store.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
