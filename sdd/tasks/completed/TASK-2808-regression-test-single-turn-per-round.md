# TASK-2808: Regression test — one turn per round, history reaches provider once

**Feature**: FEAT-524 — Conversation History Ownership
**Spec**: `sdd/specs/conversation-history-ownership.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1 documents (by code reading) that a stateful bot round persists **two**
`ConversationTurn`s — one from `AbstractClient._update_conversation_memory`
(`clients/base.py:2375-2407`), one from the bot (`bots/base.py:539/757/1349/1853`) —
and sends the history to the provider **twice** (replayed messages from the
client + a text digest in the system prompt from the bot). This task turns
that claim into a test (spec §3 Module 1, §4 M1 rows). It must be committed
**red** against the current code and becomes green when TASK-2816 lands.

---

## Scope

- Create `packages/ai-parrot/tests/unit/memory/test_history_ownership.py`.
- Implement a `RecordingClient(AbstractClient)` stub that records the
  kwargs it receives (`prompt`, `system_prompt`, `history`, `messages` it
  would send) and returns a canned `AIMessage`. No network.
- Wire a `BaseBot` to `InMemoryConversation` and the stub.
- Assertions (all `pytest.mark.asyncio`):
  1. `test_bot_round_persists_exactly_one_turn` — two `bot.ask()` rounds with
     the same `user_id`/`session_id` ⇒ exactly 2 turns in the history.
  2. `test_history_reaches_provider_once` — round-2 provider payload contains
     round-1 user text exactly once.
  3. `test_system_prompt_has_no_history_digest` — `"## Conversation Context"`
     not in the captured system prompt.
- Mark the three tests `@pytest.mark.xfail(strict=True, reason="FEAT-524 pending")`
  **only if** the repo's CI would otherwise block; preferred: commit them
  plain-red and record the red run in `artifacts/logs/feat-524-task-2808-red.log`.
  Decide with the repo's CI policy; document the choice in the completion note.

**NOT in scope**: any production code change. Do not touch `bots/` or `clients/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/unit/memory/test_history_ownership.py` | CREATE | Regression tests + `RecordingClient` stub + fixtures |
| `packages/ai-parrot/tests/unit/memory/__init__.py` | CREATE (if missing) | package marker |
| `artifacts/logs/feat-524-task-2808-red.log` | CREATE | evidence of the red run |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.memory import ConversationHistory, ConversationMemory, ConversationTurn  # parrot/memory/__init__.py:3
from parrot.memory import InMemoryConversation     # parrot/memory/__init__.py:11
from parrot.models import AIMessage                # parrot/models/__init__.py:9
from parrot.clients.base import AbstractClient     # parrot/clients/base.py:230
from parrot.bots.base import BaseBot               # parrot/bots/base.py:71
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):                       # line 230
    def __init__(self, conversation_memory=None, preset=None, tools=None,
                 use_tools=False, debug=True, tool_manager=None, **kwargs)   # line 360
    async def ask(self, prompt, model, max_tokens=None, temperature=0.7, files=None,
                  system_prompt=None, structured_output=None, user_id=None, session_id=None,
                  tools=None, use_tools=None, deep_research=False, background=False,
                  lazy_loading=False) -> MessageResponse                     # line 1638
    async def ask_stream(...)                                                # line 1679
    async def _prepare_conversation_context(self, prompt, files, user_id, session_id,
                  system_prompt, stateless=False)                            # line 2269 (loads + replays history)
    async def _update_conversation_memory(...)                               # line 2375 (client-side write — the bug)

# packages/ai-parrot/src/parrot/bots/base.py
class BaseBot(AbstractBot):                                                 # line 71
    async def ask(self, question, ...)                                       # line 932
    # memory = memory or self.conversation_memory                            # line 1095
    # llm_kwargs = {"prompt", "system_prompt", "temperature", "user_id", "session_id", "use_tools"}  # line 1282-1289
    # response = await self.execute_llm_call(client, "ask", **llm_kwargs)    # line 1317
    # bot-side ConversationTurn(...) + memory.add_turn(user_id, session_id, turn)  # lines 1335-1349

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(...):                                                     # line 187
    self.conversation_memory: Optional[ConversationMemory] = None            # line 585
    def _create_llm_client(self, config, conversation_memory=None)           # line 1028 (injects memory into client :1035-1036/:1055)
    def configure_conversation_memory(self) -> None                          # line 1263
    async def create_system_prompt(..., conversation_context: str = "", ...) # line 3072 ("## Conversation Context:" at :3162)

# packages/ai-parrot/src/parrot/memory/mem.py
class InMemoryConversation(ConversationMemory):                             # line 5
    def _get_chatbot_key(self, chatbot_id) -> str   # line 12 → "_default" when None
    async def get_history(user_id, session_id, chatbot_id=None)             # line 37

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):   # line 72 — required: input:str, output:Any, model:str, provider:str, usage:CompletionUsage
    turn_id: Optional[str]    # line 163
```

### Does NOT Exist
- ~~`parrot/clients/abstract_client.py`~~ — `AbstractClient` is in `parrot/clients/base.py`.
- ~~`history=` kwarg on `ask()`~~ — does not exist yet (TASK-2812). The stub must accept `**kwargs` so it survives both before and after.
- ~~`AbstractBot.memory_key_id`~~ — TASK-2811.
- ~~`parrot.memory.render`~~ — TASK-2809.

---

## Implementation Notes

### Pattern to Follow
```python
class RecordingClient(AbstractClient):
    client_type = "recording"
    def __init__(self, reply: str = "ok", **kw):
        super().__init__(**kw)
        self.calls: list[dict] = []
        self.reply = reply
    async def ask(self, prompt, model=None, *, system_prompt=None, **kw):
        # Pre-FEAT-524 the base class replays history via _prepare_conversation_context;
        # call it when user_id/session_id are present so the test observes today's
        # payload; post-FEAT-524 use kw.get("history").
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt, "kw": dict(kw)})
        return AIMessage(input=prompt, output=self.reply, model="stub", provider="stub",
                         usage=CompletionUsage(), turn_id=str(uuid.uuid4()))
```
Look at `packages/ai-parrot/tests/bots/test_vector_context_integration.py` for
how existing tests construct a `BaseBot` with a stub client and in-memory
conversation; copy its fixture style. Check which abstract methods
`AbstractClient` requires (`grep -n "@abstractmethod" packages/ai-parrot/src/parrot/clients/base.py`)
and stub them minimally.

### Key Constraints
- Async tests; `pytest-asyncio` is configured in the repo.
- Wrap suite runs in `timeout -s KILL 600 …` — the unit suite hangs after the summary in this environment.
- Do not "fix" the test to pass against current code; red is the deliverable.

---

## Acceptance Criteria

- [ ] File exists with the three tests and the stub.
- [ ] Red run recorded: `timeout -s KILL 300 pytest packages/ai-parrot/tests/unit/memory/test_history_ownership.py -v 2>&1 | tee artifacts/logs/feat-524-task-2808-red.log` shows 3 failures (or 3 strict xfails, per the documented choice).
- [ ] `ruff check packages/ai-parrot/tests/unit/memory/test_history_ownership.py` clean.

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_bot_round_persists_exactly_one_turn(bot, memory):
    await bot.ask("first", user_id="u", session_id="s")
    await bot.ask("second", user_id="u", session_id="s")
    history = await memory.get_history("u", "s")  # post-FEAT-524: chatbot_id=bot.memory_key_id
    assert len(history.turns) == 2

@pytest.mark.asyncio
async def test_history_reaches_provider_once(bot):
    await bot.ask("first", user_id="u", session_id="s")
    await bot.ask("second", user_id="u", session_id="s")
    payload = json.dumps(bot.get_client().calls[-1], default=str)
    assert payload.count("first") == 1

@pytest.mark.asyncio
async def test_system_prompt_has_no_history_digest(bot):
    await bot.ask("first", user_id="u", session_id="s")
    await bot.ask("second", user_id="u", session_id="s")
    assert "## Conversation Context" not in (bot.get_client().calls[-1]["system_prompt"] or "")
```

---

## Agent Instructions

1. Read the spec §1 and §4 (M1 rows).
2. Verify the Codebase Contract lines still match before writing.
3. Write the test, run it, capture the red log, commit **only** the new files and the log.
4. Move this file to `sdd/tasks/completed/`, update `sdd/tasks/index/conversation-history-ownership.json` → `done`, fill the completion note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-04
**Notes**:
- Created `packages/ai-parrot/tests/unit/memory/test_history_ownership.py` with the
  three spec'd tests plus a `RecordingClient(AbstractClient)` stub and an async
  `bot` fixture (`BaseBot` + `InMemoryConversation`, `injection_detection=False`
  to skip the HF detector load).
- **Committed plain-red** (not xfail). Repo CI policy: `.github/workflows` does not
  gate on this path with a strict-xfail requirement, and the spec's AC explicitly
  asks for a red run recorded in `artifacts/logs/`. Red evidence:
  `artifacts/logs/feat-524-task-2808-red.log` — 3 failed, with the expected reasons:
    * `assert 4 == 2` — four turns persisted for two rounds (client + bot both write)
    * `assert 5 == 1` — round-1 text reaches the provider five times on round 2
      (replayed provider messages + the `## Conversation Context:` system-prompt digest)
    * `'## Conversation Context' not in <system prompt>` — digest present today
- The stub is written to survive the cut: it probes for the pre-FEAT-524 helpers
  (`_prepare_conversation_context` / `_update_conversation_memory`) with `getattr`
  and falls back to the post-FEAT-524 `_build_messages` / `history=` path. The same
  file therefore measures the same three properties before and after TASK-2816
  instead of being rewritten mid-feature.
- `ruff check` clean on the new file.
- No production code touched.

**Deviations from spec**:
- `artifacts/logs/feat-524-task-2808-red.log` was written but **not committed**:
  `.gitignore:283` ignores `artifacts/`. The log exists on disk in the worktree as
  evidence; force-adding it would fight a deliberate repo-wide rule.
