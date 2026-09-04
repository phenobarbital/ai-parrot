# TASK-2825: `current_memory_key_id` ContextVar + bind-after-defaulting in every bot entry point

**Feature**: FEAT-525 — Per-Turn Conversation Compaction
**Spec**: `sdd/specs/per-turn-conversation-compaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none *(external prerequisite: FEAT-524 merged to `dev` — see banner)*
**Assigned-to**: unassigned

> ⚠️ **FEAT-524 prerequisite (spec C14).** This task relies on
> `AbstractBot.memory_key_id` (FEAT-524 TASK-2811) and on the four
> `bots/base.py` entry points as rewritten by FEAT-524 TASK-2816 (which was
> still `in-progress`, uncommitted, in the FEAT-524 worktree on 2026-09-04).
> Line numbers marked *(FEAT-524 branch)* were read from
> `.claude/worktrees/feat-FEAT-524-conversation-history-ownership` and WILL
> shift; re-verify every one on the merged `dev` before editing.

---

## Context

Spec §3 Module 10, constraint C12 and the "Binding-order hazard" in §7.
`read_omitted_content` (TASK-2829) resolves its omission-store key from three
ContextVars: `current_memory_key_id` (new), `current_user_id`,
`current_session_id`. Today every `BaseBot` entry point binds user/session
**before** defaulting them (`user_id or "anonymous"`, `session_id or
uuid4()`), so a call without ids would store omissions under the generated
ids while the tool reads `None`. This task adds the ContextVar and moves the
binding after the defaults, everywhere a history is rendered.

---

## Scope

- `observability/context.py`: add
  `current_memory_key_id: ContextVar[Optional[str]] = ContextVar("parrot_current_memory_key_id", default=None)`;
  add a `memory_key_id: Optional[str] = None` kwarg to `invocation_context`
  (set/reset with its own token, LIFO like the other three); add
  `"current_memory_key_id"` to `__all__`.
- `bots/base.py` — in each of `conversation`, `invoke`, `ask`, `ask_stream`:
  move the `current_user_id.set(...)` / `current_session_id.set(...)` lines
  to **immediately after** the `session_id = session_id or …` /
  `user_id = user_id or "anonymous"` defaults, and add
  `_memkey_token = current_memory_key_id.set(self.memory_key_id)` in the
  same place; reset the new token in the existing `finally` (reset order:
  memory_key → session → user → agent). `current_agent_name.set(self.name)`
  may stay where it is.
- `bots/data.py` (`ask`, FEAT-524 branch :1295, defaults at :1335-1336) and
  `bots/voice.py` (`ask_stream` :480 defaults :514-515; `ask` :739 defaults
  :760-761): these entry points do **not** bind any ContextVar today. Add
  the same three-variable binding (`current_user_id`, `current_session_id`,
  `current_memory_key_id`) after their defaults with token reset in a
  `try/finally` — only in the methods that render history / save turns;
  methods that delegate to `super().ask(...)` need nothing.
- Tests: `tests/unit/observability/test_memory_key_contextvar.py` (ContextVar
  + `invocation_context` restore) and
  `tests/unit/bots/test_bind_after_defaulting.py` (×4 `BaseBot` entry
  points: a call **without** `user_id`/`session_id` reaches
  `conversation_memory.add_turn` with all three ContextVars equal to the
  turn's `user_id`, `session_id` and the bot's `memory_key_id`).

**NOT in scope**: the recovery tool (TASK-2829); the budget branch in the
same entry points (TASK-2831); `AbstractBot` changes (TASK-2830).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/context.py` | MODIFY | new ContextVar, `invocation_context(memory_key_id=)`, `__all__` |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | four entry points: bind after defaulting + new token + reset |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `ask`: bind three ContextVars after defaults |
| `packages/ai-parrot/src/parrot/bots/voice.py` | MODIFY | `ask`, `ask_stream`: bind three ContextVars after defaults |
| `packages/ai-parrot/tests/unit/observability/test_memory_key_contextvar.py` | CREATE | ContextVar + context manager tests |
| `packages/ai-parrot/tests/unit/bots/test_bind_after_defaulting.py` | CREATE | ×4 entry-point binding tests with a recording memory + stub client |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use only what is listed here. Verify anything else before using it.

### Verified Imports
```python
from parrot.observability.context import (current_agent_name, current_user_id,
                                          current_session_id, invocation_context)   # dev: context.py:56, 58, 60, 91
from parrot.bots.base import BaseBot                                                # dev: bots/base.py
from parrot.memory import InMemoryConversation, ConversationTurn                    # dev: memory/__init__.py
from parrot.clients.base import AbstractClient                                       # stub-client base (FEAT-524 test precedent)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/context.py  (dev, verified 2026-09-04)
__all__ = ["current_agent_name", "current_user_id", "current_session_id", "agent_identity",
           "invocation_context", "current_run_id", "current_seat", "usage_attribution"]   # :45-54
current_agent_name: ContextVar[Optional[str]] = ContextVar("parrot_current_agent_name", default=None)   # :56
current_user_id:    ContextVar[Optional[str]] = ContextVar("parrot_current_user_id", default=None)      # :58
current_session_id: ContextVar[Optional[str]] = ContextVar("parrot_current_session_id", default=None)   # :60
@contextmanager
def invocation_context(agent_name, user_id=None, session_id=None) -> Iterator[None]   # :91-121  tok_* set; finally reset LIFO

# packages/ai-parrot/src/parrot/bots/base.py  (dev @ f3a5fe7ea)          | (FEAT-524 branch, TASK-2816 WIP)
async def conversation(...)          # :156  binds :206-208, finally :231-234, defaults :282-283   | :154 binds :205-206, defaults :281
async def invoke(...)                # :600  binds :627-629, defaults :634-635, finally :775        | :598 binds :626-627, defaults :632-633
async def ask(...)                   # :932  binds :989-991, defaults :1016-1017, finally :1590     | :932 binds :990-991, defaults :1016-1017
async def ask_stream(...)            # :1597 binds :1621-1623, defaults :1631-1632, finally :1965   | :1597 binds :1622-1623, defaults :1631-1632
#   binding shape (dev :206-208):
#     _agent_token = current_agent_name.set(self.name)
#     _user_token = current_user_id.set(user_id)
#     _session_token = current_session_id.set(session_id)
#   finally (dev :231-234): current_session_id.reset(_session_token); current_user_id.reset(_user_token); current_agent_name.reset(_agent_token)

# packages/ai-parrot/src/parrot/bots/abstract.py (FEAT-524 branch)
@property def memory_key_id(self) -> str        # :1807  explicit chatbot_id (self._chatbot_id_explicit, :363) else self.name
async def save_conversation_turn(self, user_id, session_id, turn) -> None   # :1868  → self.conversation_memory.add_turn(user_id, session_id, turn, chatbot_id=self.memory_key_id)

# packages/ai-parrot/src/parrot/bots/data.py (FEAT-524 branch): async def ask(...) :1295; defaults :1335-1337; render_history :1354; save :2103
# packages/ai-parrot/src/parrot/bots/voice.py (FEAT-524 branch): ask_stream :480 (defaults :514-515); ask :739 (defaults :760-761); render_history :798; save :634, :675

# Test precedent: FEAT-524 branch packages/ai-parrot/tests/unit/memory/test_history_ownership.py
#   class RecordingClient(AbstractClient) :43 ; @pytest.fixture async def bot() -> BaseBot :137-153 (BaseBot(...) with InMemoryConversation)
# Existing ContextVar test: packages/ai-parrot/tests/unit/bots/test_agent_identity_binding.py
```

### Does NOT Exist
- ~~`current_memory_key_id`~~ — does not exist yet (`context.py` defines exactly `current_agent_name`, `current_user_id`, `current_session_id`, `current_run_id`, `current_seat`); this task creates it.
- ~~`invocation_context(..., memory_key_id=)`~~ — kwarg added here.
- ~~ContextVar binding in `bots/data.py` / `bots/voice.py`~~ — none today (grep confirmed on dev and on the FEAT-524 branch); add it.
- ~~`AbstractBot.memory_key_id` on dev~~ — FEAT-524 only; if absent on your branch, STOP (banner).
- ~~`RequestContext` / `_current_ctx` (`utils/helpers.py`) as the scoping mechanism~~ — unrelated; use the observability ContextVars.

---

## Implementation Notes

### Pattern to Follow
```python
# bots/base.py — each entry point, AFTER the defaults
session_id = session_id or str(uuid.uuid4())
user_id = user_id or "anonymous"
_user_token = current_user_id.set(user_id)
_session_token = current_session_id.set(session_id)
_memkey_token = current_memory_key_id.set(self.memory_key_id)
...
finally:
    current_memory_key_id.reset(_memkey_token)
    current_session_id.reset(_session_token)
    current_user_id.reset(_user_token)
    current_agent_name.reset(_agent_token)
```
Take care that the tokens are assigned *before* the `try:` whose `finally`
resets them (or guard the reset with `if _memkey_token is not None`) —
`conversation()` on dev defaults the ids *outside* the `try` (:282-283) while
`invoke/ask/ask_stream` default them *inside* (:634, :1016, :1631); keep each
method's structure and put the binding right after its defaults.

### Key Constraints
- Do not change what the entry points do with the ids beyond binding order.
- `ContextVar.reset(token)` must run in the same task that called `set()` — keep everything inside the entry-point coroutine.
- The `BaseBot` test must not hit a network: stub client returning a fixed `AIMessage`; recording memory subclassing `InMemoryConversation` whose `add_turn` captures the three `.get()` values.

### References in Codebase
- `packages/ai-parrot/src/parrot/observability/context.py:63-121` — token set/reset pattern.
- `packages/ai-parrot/tests/unit/bots/test_agent_identity_binding.py` — existing ContextVar binding test for bots.

---

## Acceptance Criteria

- [ ] `from parrot.observability.context import current_memory_key_id` works; `invocation_context("a", memory_key_id="k")` sets it inside and restores the prior value on exit (nested case included).
- [ ] For each of `conversation`, `invoke`, `ask`, `ask_stream` on `BaseBot`: a call with **no** `user_id`/`session_id` reaches `conversation_memory.add_turn` with `current_user_id.get() == turn.user_id == "anonymous"`, `current_session_id.get() == session_id` (a uuid string) and `current_memory_key_id.get() == bot.memory_key_id`; all three are `None` again after the call returns.
- [ ] `bots/data.py` `ask` and `bots/voice.py` `ask`/`ask_stream` bind the same three variables after their defaults (assert by source inspection or a targeted test).
- [ ] All tests pass: `timeout -s KILL 300 pytest packages/ai-parrot/tests/unit/observability/test_memory_key_contextvar.py packages/ai-parrot/tests/unit/bots/test_bind_after_defaulting.py packages/ai-parrot/tests/unit/bots/test_agent_identity_binding.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/observability/context.py packages/ai-parrot/src/parrot/bots/base.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/observability/test_memory_key_contextvar.py
from parrot.observability.context import current_memory_key_id, invocation_context


def test_contextvar_default_and_restore():
    assert current_memory_key_id.get() is None
    with invocation_context("a", user_id="u", session_id="s", memory_key_id="k"):
        assert current_memory_key_id.get() == "k"
        with invocation_context("b", memory_key_id="k2"):
            assert current_memory_key_id.get() == "k2"
        assert current_memory_key_id.get() == "k"
    assert current_memory_key_id.get() is None


# packages/ai-parrot/tests/unit/bots/test_bind_after_defaulting.py
import pytest
from parrot.memory import InMemoryConversation
from parrot.observability.context import current_memory_key_id, current_session_id, current_user_id


class RecordingMemory(InMemoryConversation):
    def __init__(self):
        super().__init__(); self.seen = []
    async def add_turn(self, user_id, session_id, turn, chatbot_id=None, **kw):
        self.seen.append((user_id, session_id, current_user_id.get(), current_session_id.get(), current_memory_key_id.get()))
        await super().add_turn(user_id, session_id, turn, chatbot_id=chatbot_id, **kw)


@pytest.mark.parametrize("entry", ["conversation", "invoke", "ask", "ask_stream"])
async def test_bind_after_defaulting(bot_with_recording_memory, entry):
    bot, mem = bot_with_recording_memory                      # fixture: BaseBot + stub client, memory=RecordingMemory()
    call = getattr(bot, entry)
    if entry == "ask_stream":
        async for _ in call("hello"): pass
    else:
        await call("hello")
    (user_id, session_id, cv_user, cv_session, cv_key), = mem.seen
    assert cv_user == user_id == "anonymous" and cv_session == session_id and cv_key == bot.memory_key_id
    assert current_user_id.get() is None and current_session_id.get() is None and current_memory_key_id.get() is None
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — FEAT-524 merged (banner); no in-feature dependency
3. **Verify the Codebase Contract** before writing any code; update it first if anything changed (line numbers WILL differ after the FEAT-524 merge)
4. **Update status** in `sdd/tasks/index/per-turn-conversation-compaction.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2825-memory-key-contextvar-binding-order.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
