# TASK-2810: Lazy legacy re-key in Redis and File backends

**Feature**: FEAT-524 — Conversation History Ownership
**Spec**: `sdd/specs/conversation-history-ownership.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2809
**Assigned-to**: unassigned

---

## Context

Spec §2 "Storage key" + §3 Module 2b. The storage key is unified to
`(chatbot, user, session)`. Today `BaseBot` writes the **un-segmented** key
(`conversation:{user}:{session}`), and Redis history keys have **no TTL**
(`memory/redis.py:490` is commented out), so every live conversation would be
orphaned when TASK-2816 starts keying by `memory_key_id`. This task makes
`get_history()` fall back to the legacy key once and copy the record under
the new key. The legacy record is left in place (rollback safety).

---

## Scope

- MODIFY `RedisConversation.get_history` (`memory/redis.py:126`): when
  `chatbot_id` is truthy and the segmented key is missing, read
  `self._get_key(user_id, session_id, None)`; if present, deserialize, set
  `history.chatbot_id = str(chatbot_id)`, persist under the segmented key
  (reuse `update_history`/the hash-write path), `self.logger.info` once,
  return it. Legacy key untouched.
- MODIFY `FileConversationMemory.get_history` (`memory/file.py:52`): same
  contract with `_get_file_path(user_id, session_id, None)` vs
  `_get_file_path(user_id, session_id, chatbot_id)`.
- `InMemoryConversation`: no change (process-local).
- Turns copied keep `turn.chatbot_id = None` (they predate attribution;
  `render_history` treats `None` as own-agent).
- Tests with `fakeredis` (check it is available: `grep -n fakeredis packages/ai-parrot/pyproject.toml pyproject.toml`; if absent, mark the Redis test with the repo's existing redis marker and test the File backend unconditionally).

**NOT in scope**: offline migration script, TTL, deleting legacy keys, bot code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/redis.py` | MODIFY | legacy fallback in `get_history` |
| `packages/ai-parrot/src/parrot/memory/file.py` | MODIFY | legacy fallback in `get_history` |
| `packages/ai-parrot/tests/unit/memory/test_legacy_rekey.py` | CREATE | three tests below |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.memory import RedisConversation, FileConversationMemory, ConversationHistory, ConversationTurn  # memory/__init__.py:3,10,12
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/redis.py
class RedisConversation(ConversationMemory):                       # line 10
    def __init__(..., key_prefix: str = "conversation", ...)        # line 13-20 (self.key_prefix :20; self.use_hash_storage exists — see add_turn :199)
    def _get_key(self, user_id, session_id, chatbot_id=None) -> str # line 31  → "conversation[:chatbot]:user:session" (segment only if truthy, :39-40)
    async def create_history(...)                                   # line 82
    async def get_history(self, user_id, session_id, chatbot_id=None) -> Optional[ConversationHistory]  # line 126
    async def update_history(self, history) -> None                 # (abstract :167; concrete impl — grep "async def update_history" in redis.py)
    async def add_turn(...)                                         # line 193 (hash mode: hget/hset 'turns')
    # await self.redis.expire(...) is COMMENTED OUT                 # line 490 → no TTL on histories

# packages/ai-parrot/src/parrot/memory/file.py
class FileConversationMemory(ConversationMemory):                  # line 9
    def _get_file_path(self, user_id, session_id, chatbot_id=None)  # line 17 → user_dir[/chatbot]/{session}.json (:25-28)
    async def create_history(...)                                   # line 30
    async def get_history(self, user_id, session_id, chatbot_id=None)  # line 52
    async def add_turn(...)                                         # line 83

# packages/ai-parrot/src/parrot/memory/abstract.py
class ConversationHistory:  chatbot_id: Optional[str] = None       # line 54 ; to_dict/from_dict :105/:118
```

### Does NOT Exist
- ~~legacy fallback in any `get_history`~~ — both return `None` when the exact key/path is missing; you add it.
- ~~`RedisConversation.migrate_key` / `rekey`~~ — do not exist; keep the logic inside `get_history`.
- ~~history TTL~~ — none; do not add one.

---

## Implementation Notes

### Pattern to Follow
```python
async def get_history(self, user_id, session_id, chatbot_id=None):
    history = await self._load(self._get_key(user_id, session_id, chatbot_id))
    if history is None and chatbot_id:
        legacy = await self._load(self._get_key(user_id, session_id, None))
        if legacy is not None:
            legacy.chatbot_id = str(chatbot_id)
            await self.update_history(legacy)          # writes under the segmented key
            self.logger.info("Re-keyed legacy conversation %s/%s under chatbot %s", user_id, session_id, chatbot_id)
            return legacy
    return history
```
Extract the existing read body into a `_load(key)` helper rather than
duplicating deserialization. Make sure `update_history` derives the key from
`history.chatbot_id` (check its current implementation first).

### Key Constraints
- Idempotent and race-benign: two concurrent first reads both copy the same content; no locking.
- Legacy record is never deleted or modified.

---

## Acceptance Criteria

- [ ] `test_legacy_key_rekey_redis`: history exists only under `conversation:u:s`; `get_history("u","s","bot")` returns it, `conversation:bot:u:s` now exists, legacy key still exists; second call does not touch the legacy key (spy/mocked `hget`/`get` count).
- [ ] `test_legacy_key_rekey_file`: same on the file backend (tmp_path).
- [ ] `test_legacy_rekey_noop_when_segmented_exists`: segmented present ⇒ legacy never read.
- [ ] `timeout -s KILL 300 pytest packages/ai-parrot/tests/unit/memory/test_legacy_rekey.py -v` green; `ruff check` clean.

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_legacy_key_rekey_file(tmp_path):
    mem = FileConversationMemory(base_path=tmp_path)      # verify ctor kwarg name in file.py:9-16
    await mem.create_history("u", "s")                    # legacy, un-segmented
    await mem.add_turn("u", "s", ConversationTurn("t1", "u", "q", "a"))
    h = await mem.get_history("u", "s", chatbot_id="bot")
    assert h is not None and h.chatbot_id == "bot" and len(h.turns) == 1
    assert mem._get_file_path("u", "s", "bot").exists()
    assert mem._get_file_path("u", "s", None).exists()     # legacy untouched
```

---

## Agent Instructions

1. Read spec §2 Storage key, §3 M2b, §7 risks "Key unification…" and "Re-key race".
2. Verify contract lines; read `update_history` in both backends before relying on it.
3. Tests first; commit only listed files; move to `completed/`; update index; fill note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
