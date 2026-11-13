# TASK-5568: Correctness fixes (P0) — AgentTalk memory injection, ask_stream commit, hot-tier delete_turn, hot TTL setting

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: `sdd/specs/durable-conversation-memory.spec.md` (Module 1)
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 ("Piece 0 — Correctness fixes"). Four independent production defects that have no
dependency on the rest of FEAT-886 and land first on the feature branch:

1. `AgentTalk` builds a throw-away `RedisConversation()` per request and passes it as `memory=`; the bot reads
   history from it but `save_conversation_turn` writes to `self.conversation_memory`, so a default
   `memory_type="memory"` agent over HTTP never sees its previous turns (Problem Statement item 2).
2. `ask_stream` saves its turn without `compaction=` (`bots/base.py:2297`), so streamed rounds never update
   `metadata.compaction` (item 6).
3. `ChatStorage.delete_turn` deletes only from the cold tier (item 6).
4. `HOT_TTL_HOURS = 48` (`storage/chat.py:20`) is never used; it becomes the `CHAT_HOT_TTL_HOURS` setting passed as
   `history_ttl` to the hot-tier `RedisConversation` (spec §3 M1 (d), §8 Q10).

---

## Scope

- (a) Remove the per-request `RedisConversation()` in `handlers/agent.py`: no `memory` local, no `memory=`
  argument on `bot.ask` / `bot.ask_stream` / `bot.followup` / `_handle_stream_response`, no `memory` parameter on
  `_handle_stream_response`, and drop the now-unused `RedisConversation` import.
- (b) `ask_stream` builds `commit = self.build_compaction_commit(...)` and passes `compaction=commit` on the save at
  `bots/base.py:2297` when the stream completed; when the stream died (`stream_error`), keep `compaction=None`.
- (c) `ChatStorage.delete_turn` also removes the turn from the hot tier (`self._redis`, keyed by `chatbot_id=agent_id`).
  A hot-tier failure is logged and never reported as success on its own; the return value stays "the cold tier deleted it".
- (d) `parrot.conf.CHAT_HOT_TTL_HOURS` (default `48`, `0` disables) replaces the unused `HOT_TTL_HOURS`; `ChatStorage.initialize`
  passes `history_ttl=CHAT_HOT_TTL_HOURS * 3600` (or `None` when `0`) to `RedisConversation(key_prefix="chat")`.
- Write the three test files in the table below.

**NOT in scope**: removing `chat_storage.save_turn(` from `handlers/agent.py` and the whole persistence-free handler
(TASK-5584); tombstone-first deletion and the cleanup retry path (TASK-5579); `ChatStorage.store_turn` (TASK-5579);
`REDIS_HISTORY_EXPLICIT` / the `"auto"` memory type (TASK-5571); hydration; any change to `parrot/clients/base.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | `ask_stream` builds and passes the compaction commit |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | drop the throw-away `RedisConversation()` and every `memory=` pass-through |
| `packages/ai-parrot/src/parrot/storage/chat.py` | MODIFY | hot-tier `delete_turn`; `history_ttl` from `CHAT_HOT_TTL_HOURS` |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | add `CHAT_HOT_TTL_HOURS` |
| `packages/ai-parrot/tests/unit/bots/test_ask_stream_compaction_commit.py` | CREATE | `test_ask_stream_commits_compaction` |
| `packages/ai-parrot/tests/unit/storage/test_delete_turn_hot_tier.py` | CREATE | `test_delete_turn_clears_hot_tier` (+ TTL wiring) |
| `packages/ai-parrot-server/tests/handlers/test_agenttalk_memory_injection.py` | CREATE | `test_agenttalk_does_not_inject_memory` |

---

## Codebase Contract (Anti-Hallucination)

Re-verified against the tree at `6d564b36a2` (branch `dev`).

### Verified Imports
```python
from parrot.bots.base import BaseBot                                  # verified: tests/unit/bots/test_bot_history_wiring.py:17
from parrot.clients.base import AbstractClient                        # verified: tests/unit/bots/test_bot_history_wiring.py:18
from parrot.memory import ConversationTurn, InMemoryConversation      # verified: test_bot_history_wiring.py:19 (memory/__init__.py:3)
from parrot.memory.compaction.models import ContextBudget, CompactionCommit  # verified: memory/compaction/models.py:161 (ContextBudget); tests/unit/bots/test_context_budget.py:9
from parrot.models import AIMessage                                   # verified: test_bot_history_wiring.py:20
from parrot.models.responses import CompletionUsage                   # verified: test_bot_history_wiring.py:21
from parrot.storage.chat import ChatStorage                           # verified: storage/chat.py:25
from parrot.conf import CHAT_HOT_TTL_HOURS                            # NEW — added by THIS task in conf.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/base.py
async def ask_stream(...)                                              # :1943
_turn_id = str(uuid.uuid4())                                           # :2013
rendered_history = []                                                  # :2067
compaction_result = None                                               # :2068
memory = memory or self.conversation_memory                            # :2069  (also :431, :830, :1326 — NOT touched here)
rendered_history, compaction_result = await self.render_context_history(conversation_history)  # :2083
stream_error: Optional[Exception] = None                               # :2203  set at :2267 when the client stream raised
await self.save_conversation_turn(user_id, session_id, turn)           # :2297  ← the ask_stream save (1 occurrence)
# ask() reference for the commit (the exact shape to mirror):          # :1599-1613
#   commit = None
#   if compaction_result is not None:
#       commit = self.build_compaction_commit(
#           compaction_result,
#           self.estimate_prompt_tokens(rendered_history, system_prompt, question),
#       )
#   await self.save_conversation_turn(user_id, session_id, turn, compaction=commit)

# packages/ai-parrot/src/parrot/bots/abstract.py
def build_compaction_commit(self, result: Optional[CompactionResult], prompt_estimate: int) -> Optional[CompactionCommit]  # :2209 (returns None when result is None)
async def save_conversation_turn(self, user_id, session_id, turn, *, compaction: Optional[CompactionCommit] = None) -> None  # :2685
def estimate_prompt_tokens(...)                                        # used at base.py:1608 — signature (rendered_history, system_prompt, question)

# packages/ai-parrot/src/parrot/storage/chat.py
HOT_TTL_HOURS = 48                                                     # :20 (unused)
class ChatStorage:                                                     # :25
    def __init__(self, redis_conversation=None, dynamodb=None, document_db=None)  # :28
    self._redis = RedisConversation(key_prefix="chat")                 # :55 (inside initialize :46; lazy import from parrot.memory at :53)
    async def delete_turn(self, session_id, turn_id, user_id=None, agent_id=None) -> bool  # :578
    # hot-tier key used by save_turn: self._redis.get_history(user_id, session_id, chatbot_id=agent_id)  # :190

# packages/ai-parrot/src/parrot/memory/abstract.py
class ConversationHistory:                                             # :274  .turns: List[ConversationTurn]
class ConversationMemory(ABC):                                         # :335
    async def get_history(self, user_id, session_id, chatbot_id=None) -> Optional[ConversationHistory]  # :429
    async def update_history(self, history) -> None                    # :436 (abstract; InMemoryConversation.update_history mem.py:71, RedisConversation.update_history redis.py:291)
# packages/ai-parrot/src/parrot/memory/redis.py
class RedisConversation: def __init__(..., history_ttl: Optional[int] = None)  # :47 (seconds; <=0/None -> no TTL)

# packages/ai-parrot-server/src/parrot/handlers/agent.py
from ..memory import RedisConversation                                 # :42  (only used at :1736)
memory = None / memory = RedisConversation()                           # :1733-1738 (inside `if user_id and session_id:` with try/except)
memory=memory,                                                         # :1840 (_handle_stream_response call), :1861 (bot.followup), :1880 (bot.ask)
memory: Optional[Any],                                                 # :2684 (_handle_stream_response parameter)
memory=memory,                                                         # :2738 (bot.ask_stream call inside _handle_stream_response)
```

### Does NOT Exist
- ~~`ChatStorage.delete_turn_hot`~~ / ~~`ConversationMemory.delete_turn`~~ / ~~`ConversationMemory.remove_turn`~~ — no per-turn delete exists on any memory backend; the hot-tier delete is read-modify-write through `get_history` + `update_history`.
- ~~`parrot.conf.CHAT_HOT_TTL_HOURS`~~ — created by THIS task.
- ~~`from parrot.storage.chat import HOT_TTL_HOURS` as a live symbol~~ — nothing imports it (`grep -rn HOT_TTL_HOURS packages tests` → only `storage/chat.py:20`); it is removed.
- ~~`ChatStorage.store_turn`~~, ~~`put_tombstone`~~ — TASK-5579 / TASK-5570; do not call or stub them here.
- ~~`ToolCall.status` / `ToolCall.output`~~ on `parrot.models.basic.ToolCall` (unrelated here, do not touch the handler's tool-call serialization — TASK-5584).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/agent.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/storage/chat.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/conf.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/bots/test_ask_stream_compaction_commit.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/storage/test_delete_turn_hot_tier.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_agenttalk_memory_injection.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask_stream",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.build_compaction_commit",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.save_conversation_turn",
    "sym:packages/ai-parrot/src/parrot/storage/chat.py#ChatStorage",
    "sym:packages/ai-parrot/src/parrot/storage/chat.py#ChatStorage.delete_turn",
    "sym:packages/ai-parrot/src/parrot/memory/redis.py#RedisConversation",
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk._handle_stream_response"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `ask()` already builds the commit; `ask_stream` copies that exact shape — do not invent a different estimate.
- A stream that raised (`stream_error is not None`) saves with `compaction=None` (spec §3 M1 (b)): the round did not
  complete, so it must not move the boundary or feed the calibration EWMA.
- Hot-tier delete failure: log at WARNING with the `turn_id`, do not raise, do not change the return value. TASK-5579
  adds the retry (tombstone-first protocol); this task only makes the delete reach both tiers.
- The handler keeps `session_id`/`user_id` logic untouched; only the memory construction and pass-through go.
- Settings through `parrot.conf` (`config.get`), never `os.environ` (spec §7).
- `self.logger` only; no prints. Google-style docstrings on anything new.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/base.py:1599-1613` — the commit pattern to mirror.
- `packages/ai-parrot/tests/unit/bots/test_bot_history_wiring.py:30-110` — `RecordingClient`, `_make_bot()`; copy the
  pattern into the new test file (do not import from another test module).
- `packages/ai-parrot/tests/unit/bots/test_context_budget.py` — how `context_budget` / `CompactionCommit` assertions read.
- `packages/ai-parrot-server/tests/handlers/test_agenttalk_tenant_metadata.py:13` — `_AGENT_SRC` path idiom for source scans.

---

## Implementation Blueprint

### Steps (in order)
1. Add `CHAT_HOT_TTL_HOURS` to `conf.py` — *why*: `chat.py` imports it; nothing else depends on it.
2. Edit `storage/chat.py`: remove `HOT_TTL_HOURS`, pass `history_ttl`, add the hot-tier delete — *why*: (c) and (d).
3. Edit `bots/base.py` `ask_stream` — *why*: (b).
4. Edit `handlers/agent.py` — *why*: (a).
5. Write the three tests, then run each against the pre-change code with `git stash` of the source edits (or revert by
   hand) to see it RED — *why*: AC mutation check.

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'REDIS_DATASET_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DATASET_DB}"' packages/ai-parrot/src/parrot/conf.py)
# AFTER — insert below `REDIS_DATASET_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DATASET_DB}"` (verified: conf.py:335)
# NOTE: do NOT anchor on the REDIS_HISTORY_URL line (conf.py:332) — TASK-5571 edits around it.

# FEAT-886: hot-tier (ChatStorage Redis) history TTL in hours. 0 disables the TTL.
CHAT_HOT_TTL_HOURS = int(config.get("CHAT_HOT_TTL_HOURS", fallback=48))
```
**Why**: spec §3 M1 (d) / §8 Q10 — 48h default, `0` disables. `int(config.get(...))` mirrors the `FLOW_CHECKPOINT_*` lines at `conf.py:325-329`.

### `packages/ai-parrot/src/parrot/storage/chat.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'HOT_TTL_HOURS = 48' packages/ai-parrot/src/parrot/storage/chat.py)
# REMOVE the line `HOT_TTL_HOURS = 48` (chat.py:20) and add below the `from .models import ...` import (chat.py:16):
from ..conf import CHAT_HOT_TTL_HOURS
# FILL IN: import placement — keep the relative-import group order; bounded by ruff isort (`ruff check packages/ai-parrot/src/parrot/storage/chat.py`)

# occurrences: 1 (verified: grep -c 'self._redis = RedisConversation(key_prefix="chat")' packages/ai-parrot/src/parrot/storage/chat.py)
# REPLACE chat.py:55
                self._redis = RedisConversation(
                    key_prefix="chat",
                    history_ttl=CHAT_HOT_TTL_HOURS * 3600 if CHAT_HOT_TTL_HOURS > 0 else None,
                )

# occurrences: 1 (verified: grep -c 'async def delete_turn(' packages/ai-parrot/src/parrot/storage/chat.py)
# MODIFY `delete_turn` (chat.py:578-610). After the `update_thread(...)` call and BEFORE `self.logger.debug("Deleted turn ...")`
# insert the hot-tier call; add the helper method directly above `get_context_for_agent` (chat.py:613):
            await self._delete_turn_from_hot_tier(user_id, session_id, turn_id, agent_id)

    async def _delete_turn_from_hot_tier(
        self, user_id: str, session_id: str, turn_id: str, agent_id: str
    ) -> bool:
        """Remove ``turn_id`` from the hot-tier history, if it holds one.

        Args:
            user_id: Conversation owner.
            session_id: Conversation session.
            turn_id: The turn to drop.
            agent_id: ChatStorage key (agent NAME); the hot tier stores it as ``chatbot_id``.

        Returns:
            True when the hot tier no longer holds the turn (including "never held it" and
            "no hot tier configured"); False when the hot tier could not be updated. A failure is
            logged, never raised — the cold-tier result stays the method's return value.
        """
        if not self._redis:
            return True
        try:
            history = await self._redis.get_history(user_id, session_id, chatbot_id=agent_id)
            if history is None:
                return True
            kept = [t for t in history.turns if t.turn_id != turn_id]
            if len(kept) == len(history.turns):
                return True
            history.turns = kept
            await self._redis.update_history(history)
            return True
        except Exception as exc:  # hot tier is a cache; the M9 cleanup path retries
            self.logger.warning("hot-tier delete_turn failed for %s in %s: %s", turn_id, session_id, exc)
            return False
```
**Why**: the hot tier has no per-turn delete API, so it is a read-modify-write on the same key `save_turn` used
(`chatbot_id=agent_id`, `chat.py:190`). The return value of `delete_turn` is deliberately unchanged (spec §3 M1 skeleton:
"a hot-tier failure is logged and retried by the M9 cleanup path, never reported as success on its own"). Keep
`delete_turn` under the 60-line budget; if it grows past it, move the cold-tier block into `_delete_turn_from_cold_tier`.

### `packages/ai-parrot/src/parrot/bots/base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'await self.save_conversation_turn(user_id, session_id, turn)' packages/ai-parrot/src/parrot/bots/base.py)
# Context to disambiguate (the ask_stream site, base.py:2295-2297):
#                            tool_invocations=self.observed_tool_invocations() or [],
#                        )
#                        await self.save_conversation_turn(user_id, session_id, turn)
# REPLACE the last line (base.py:2297) with:
                        commit = None
                        if compaction_result is not None and stream_error is None:
                            commit = self.build_compaction_commit(
                                compaction_result,
                                self.estimate_prompt_tokens(rendered_history, system_prompt, question),
                            )
                        await self.save_conversation_turn(user_id, session_id, turn, compaction=commit)
```
**Why**: mirrors `ask()` (`base.py:1599-1613`). `compaction_result` / `rendered_history` / `system_prompt` / `question` are all
in scope at this point of `ask_stream` (`:2068`, `:2083`, `:2128`, signature). `stream_error is None` keeps the partial-save
on error uncommitted (spec M1 (b)). Do NOT touch the four `memory = memory or self.conversation_memory` lines — TASK-5583 edits them.

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from ..memory import RedisConversation' agent.py)  -> DELETE the import line (agent.py:42)
# occurrences: 1 (verified: grep -c 'memory = RedisConversation()' agent.py)
# DELETE the whole block agent.py:1732-1738:
#        # Use RedisConversation for history management if session_id is present
#        memory = None
#        if user_id and session_id:
#            try:
#                memory = RedisConversation()
#            except Exception as ex:
#                self.logger.warning(f"Failed to initialize RedisConversation: {ex}")
# occurrences: 4 (verified: grep -c 'memory=memory,' agent.py)  -> DELETE every `memory=memory,` line:
#   :1840 inside `return await self._handle_stream_response(`
#   :1861 inside `bot.followup(`   (context: `format_kwargs=format_kwargs,` above, `**data,` below)
#   :1880 inside `bot.ask(`        (context: `format_kwargs=format_kwargs,` above, `llm=llm,` below)
#   :2738 inside `bot.ask_stream(` in _handle_stream_response (context: `output_mode=output_mode,` above, `llm=llm,` below)
# occurrences: 1 (verified: grep -c '        memory: Optional\[Any\],' agent.py)
# DELETE the parameter `        memory: Optional[Any],` from `_handle_stream_response` (agent.py:2684)
```
**Why**: (a) — the bot then reads and writes the one store it owns (`self.conversation_memory`). `grep -c 'memory=memory,'` is
**4**, not 1 — every occurrence goes. Removing the `_handle_stream_response` parameter is safe: its only caller is `:1840`;
the existing `test_agenttalk_tenant_metadata.py` still passes `memory=None` to it, which now lands in `**kwargs` and is
forwarded harmlessly to the fake bot (that test is rewritten by TASK-5584 — do not edit it here).

### `packages/ai-parrot/tests/unit/bots/test_ask_stream_compaction_commit.py` (CREATE)
```python
"""FEAT-886 M1 — ask_stream commits compaction state like ask() does."""
from __future__ import annotations

# FILL IN: RecordingClient + _make_bot — copy the pattern from tests/unit/bots/test_bot_history_wiring.py:30-102
#   (BaseBot(name=..., llm=client, memory_type="memory", injection_detection=False,
#   context_budget=ContextBudget(window=<small but valid>)) ; await bot.configure()).
#   Bounded by: the bot must have an ACTIVE context_budget so render_context_history returns a CompactionResult.

import pytest

from parrot.bots.base import BaseBot  # noqa: F401  (used by _make_bot)


async def test_ask_stream_commits_compaction():
    """A completed streamed round writes metadata['compaction'] (boundary + calibration)."""
    # FILL IN: bot = await _make_bot(); stream one round with user_id="u", session_id="s", use_vector_context=False;
    #   history = await bot.conversation_memory.get_history("u", "s", chatbot_id=bot.memory_key_id)
    #   assert "compaction" in history.metadata and "boundary_turn_id" in history.metadata["compaction"]
    #   Bounded by AC-1. Mutation: revert the `compaction=commit` argument -> this assertion fails (RED).


async def test_ask_stream_partial_save_does_not_commit():
    """A stream that raised keeps compaction=None (spec M1 (b))."""
    # FILL IN: ExplodingClient as in test_bot_history_wiring.py:240-262 (yield "partial text " then raise);
    #   assert the partial turn is stored but history.metadata.get("compaction") is None. Bounded by AC-1.
```
**Why this shape**: real `BaseBot` + real `InMemoryConversation`; only the LLM client is a fake (external service).

### `packages/ai-parrot/tests/unit/storage/test_delete_turn_hot_tier.py` (CREATE)
```python
"""FEAT-886 M1 — ChatStorage.delete_turn clears the hot tier; hot TTL comes from CHAT_HOT_TTL_HOURS."""
from __future__ import annotations

import pytest

from parrot.memory import ConversationTurn, InMemoryConversation
from parrot.storage.chat import ChatStorage


class _ColdBackend:
    """Duck-typed cold tier recording deletes (ChatStorage only calls these two methods here)."""

    def __init__(self) -> None:
        self.deleted: list[tuple[str, str, str, str]] = []

    async def delete_turn(self, user_id, agent_id, session_id, turn_id) -> bool:
        self.deleted.append((user_id, agent_id, session_id, turn_id))
        return True

    async def update_thread(self, **kwargs) -> None:
        return None


async def test_delete_turn_clears_hot_tier():
    """The turn is gone from the hot tier AND the cold tier."""
    # FILL IN: hot = InMemoryConversation(); seed two turns under chatbot_id="agent-1" via hot.add_turn(...);
    #   storage = ChatStorage(redis_conversation=hot, dynamodb=_ColdBackend());
    #   assert await storage.delete_turn("s", "t1", user_id="u", agent_id="agent-1") is True
    #   history = await hot.get_history("u", "s", chatbot_id="agent-1"); assert [t.turn_id for t in history.turns] == ["t2"]
    #   Bounded by AC-3. Mutation: delete the _delete_turn_from_hot_tier call -> history still holds t1 (RED).


async def test_delete_turn_hot_failure_is_logged_not_raised(caplog):
    """A failing hot tier does not change the return value and does not raise."""
    # FILL IN: subclass InMemoryConversation whose update_history raises RuntimeError; assert delete_turn still
    #   returns True (cold deleted) and a WARNING mentioning the turn id was logged. Bounded by AC-3.


async def test_initialize_passes_history_ttl(monkeypatch):
    """CHAT_HOT_TTL_HOURS drives RedisConversation(history_ttl=...); 0 disables it."""
    # FILL IN: monkeypatch parrot.storage.chat.CHAT_HOT_TTL_HOURS to 2 then 0; monkeypatch parrot.memory.RedisConversation
    #   with a recording class (it is a lazy import inside ChatStorage.initialize, chat.py:53) and a no-op
    #   build_conversation_backend; assert history_ttl == 7200 then None. Bounded by AC-4.
```
**Why this shape**: the hot tier is a real `ConversationMemory` (`InMemoryConversation`), never a `Mock`; the cold backend is
a duck-typed recorder because only two calls matter and the real backends change abstract surface in TASK-5570.

### `packages/ai-parrot-server/tests/handlers/test_agenttalk_memory_injection.py` (CREATE)
```python
"""FEAT-886 M1 — AgentTalk passes no memory= to the bot (read and write hit one store)."""
from __future__ import annotations

import ast
from pathlib import Path

_AGENT_SRC = Path(__file__).resolve().parents[2] / "src" / "parrot" / "handlers" / "agent.py"


def _tree() -> ast.Module:
    return ast.parse(_AGENT_SRC.read_text(encoding="utf-8"))


def test_agenttalk_does_not_inject_memory():
    """No RedisConversation reference and no memory= keyword anywhere in the handler."""
    tree = _tree()
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "RedisConversation" not in names | imported
    # FILL IN: assert no ast.keyword(arg="memory") in any ast.Call, and no ast.arg named "memory" in
    #   AgentTalk._handle_stream_response. Bounded by AC-2.


async def test_http_style_rounds_share_one_store():
    """A memory_type='memory' bot called twice WITHOUT memory= sees the first turn on the second call."""
    # FILL IN: build a BaseBot(memory_type="memory", llm=<small in-file AbstractClient stub recording kwargs>) the way
    #   packages/ai-parrot/tests/unit/bots/test_bot_history_wiring.py:30-102 does (define the stub inline — do not import
    #   across packages); call bot.ask twice with the same user_id/session_id and NO memory kwarg;
    #   assert the second call's `history=` holds the first round. Bounded by AC-2 (spec §5 "AgentTalk mismatch fixed").
```
**Why this shape**: the handler is too heavy to instantiate; the AST scan pins the source-level fix and the bot-level test
pins the behaviour the fix restores. (R6: no Mock-built request — none is needed here.)

### FILL IN checklist
- [ ] `conf.py`: nothing to decide beyond the anchor — place after `REDIS_DATASET_URL`.
- [ ] `chat.py::delete_turn` — placement of the hot-tier call (after cold success, before the debug log); bounded by spec M1 skeleton.
- [ ] `chat.py` import ordering of `CHAT_HOT_TTL_HOURS`; bounded by `ruff check`.
- [ ] `base.py::ask_stream` — nothing left open; verify `system_prompt`/`question` names at the edit site.
- [ ] `test_ask_stream_compaction_commit.py` — client stub + budget window; bounded by AC-1.
- [ ] `test_delete_turn_hot_tier.py` — three test bodies; bounded by AC-3, AC-4.
- [ ] `test_agenttalk_memory_injection.py` — the keyword/arg AST asserts and the two-round behaviour test; bounded by AC-2.

---

## Acceptance Criteria

- [ ] AC-1 (spec §5 "Streaming commits compaction"): `ask_stream` rounds update `metadata.compaction`; an errored stream does not. `test_ask_stream_commits_compaction` passes.
- [ ] AC-2 (spec §5 "AgentTalk mismatch fixed"): `handlers/agent.py` has no `RedisConversation` and no `memory=` keyword / parameter; two bot rounds without `memory=` share one store. `test_agenttalk_does_not_inject_memory` passes.
- [ ] AC-3: `ChatStorage.delete_turn` removes the turn from the hot tier and the cold tier; a hot failure is logged and does not flip the result. `test_delete_turn_clears_hot_tier` passes.
- [ ] AC-4: `CHAT_HOT_TTL_HOURS` defaults to 48, `0` disables; `ChatStorage.initialize` passes `history_ttl` accordingly; `HOT_TTL_HOURS` no longer exists.
- [ ] Mutation checks (record the evidence in the Completion Note): (1) revert `compaction=commit` in `ask_stream` -> `test_ask_stream_commits_compaction` goes RED; (2) remove the `_delete_turn_from_hot_tier` call -> `test_delete_turn_clears_hot_tier` goes RED; (3) re-add `RedisConversation()` to the handler -> `test_agenttalk_does_not_inject_memory` goes RED.
- [ ] No behaviour change when `compaction_result is None` (compaction disabled) — `ask_stream` still calls `save_conversation_turn(..., compaction=None)`.
- [ ] `ruff check` clean on all seven files; existing `tests/unit/bots/test_bot_history_wiring.py` and `tests/test_chat_storage.py` still pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/bots/test_ask_stream_compaction_commit.py -q`
- `pytest packages/ai-parrot/tests/unit/storage/test_delete_turn_hot_tier.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_agenttalk_memory_injection.py -q`
- `pytest packages/ai-parrot/tests/unit/bots/test_bot_history_wiring.py -q`
- `pytest packages/ai-parrot/tests/test_chat_storage.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_agenttalk_tenant_metadata.py -q`

---

## Test Specification

Spec §4 rows for M1 (fixtures are written inside each test file — no shared conftest edits):

```python
# test_ask_stream_compaction_commit.py
async def test_ask_stream_commits_compaction(): ...          # spec §4 `test_ask_stream_commits_compaction`
async def test_ask_stream_partial_save_does_not_commit(): ... # M1 (b) error path

# test_delete_turn_hot_tier.py
async def test_delete_turn_clears_hot_tier(): ...            # spec §4 `test_delete_turn_clears_hot_tier`
async def test_delete_turn_hot_failure_is_logged_not_raised(caplog): ...
async def test_initialize_passes_history_ttl(monkeypatch): ...   # M1 (d)

# test_agenttalk_memory_injection.py
def test_agenttalk_does_not_inject_memory(): ...             # spec §4 `test_agenttalk_does_not_inject_memory`
async def test_http_style_rounds_share_one_store(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — re-run every `grep -c` above (note `memory=memory,` is **4**); update the contract first if anything moved
5. **Update status** in `sdd/tasks/index/durable-conversation-memory.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** all acceptance criteria — run the Validation Commands and the three mutation checks
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5568 durable-conversation-memory verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Implemented all four fixes (handler memory injection removed; ask_stream commits compaction unless the stream errored; delete_turn clears the hot tier; CHAT_HOT_TTL_HOURS drives history_ttl).

**Completed by**: sdd-worker (sequential fallback; parrot-sdd-coder MCP unavailable)
**Date**: 2026-11-12
**Tests**: 47 passed (new 3 files + test_bot_history_wiring + test_chat_storage + test_agenttalk_tenant_metadata); ruff clean. No skips.
**Mutation evidence**: revert `compaction=commit` -> test_ask_stream_commits_compaction RED; drop hot-tier call -> test_delete_turn_clears_hot_tier RED; re-add RedisConversation import to handler -> test_agenttalk_does_not_inject_memory RED. All restored by re-applying the edit.

**Deviations from spec**: none. Note: InMemoryConversation.add_turn needs create_history first, so the hot-tier test seeds via create_history.
