# TASK-2811: `AbstractBot` — `memory_key_id`, single writer, drop the system-prompt digest

**Feature**: FEAT-524 — Conversation History Ownership
**Spec**: `sdd/specs/conversation-history-ownership.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2809
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. `AbstractBot` becomes the sole owner of conversation
history: it gets a stable per-agent key identity (`memory_key_id`), its
existing-but-unused `save_conversation_turn` becomes the single writer,
the text digest of history injected into the system prompt is removed, and
the bot stops injecting its memory into the LLM client. `BaseBot` call
sites are migrated later (TASK-2816); this task only changes `abstract.py`
and must keep `bots/base.py` importing and its current tests passing
(base.py still calls `build_conversation_context` until TASK-2816 — so
**keep a temporary shim**? NO: hard cut policy. Instead, TASK-2811 and
TASK-2816 remove/replace in lock-step: this task removes the digest
machinery, and the `bots/base.py` references at `:329/:687/:1102/:1693` must
be updated in the same commit to compute `conversation_context = ""` — a
two-line stop-gap that TASK-2816 then replaces with `render_history`).

---

## Scope

- ADD `AbstractBot.memory_key_id -> str` property: `str(self.chatbot_id)` if
  an explicit `chatbot_id` was supplied (kwarg at `abstract.py:353`, or set by
  `Chatbot` from the DB record) else `self.name`. Implement by recording a
  private flag `self._chatbot_id_explicit: bool` where `chatbot_id` is
  assigned (`:353-359`); `Chatbot` DB load (`bots/chatbot.py:150-161`,
  `:287-289`) must set the flag when it assigns `self.chatbot_id` — grep
  every `self.chatbot_id =` in `bots/` and set the flag there.
- MODIFY `save_conversation_turn` (`:1836`): signature
  `(self, user_id, session_id, turn) -> None`; key by `self.memory_key_id`;
  `raise ValueError` if `turn.chatbot_id != self.memory_key_id`; keep the
  `MessageAddedEvent` emission (`:1857+`).
- MODIFY read helpers to pass `chatbot_id=self.memory_key_id`:
  `get_conversation_history` (`:1798`), `create_conversation_history`
  (`:1816`), `clear_conversation_history` (`:1873`),
  `delete_conversation_history` (`:1897`).
- REMOVE `build_conversation_context` (`:2912`, incl. its `print()` debug
  lines) and the `conversation_context` kwarg from `_build_prompt`
  (`:1382`, kwarg `:1386`, `"chat_history"` slot `:1440`) and
  `create_system_prompt` (`:3072`, kwarg `:3076`, pass-through `:3116`,
  `## Conversation Context:` block `:3162-3163`). Grep the prompt templates
  for `$chat_history` / `{chat_history}` and remove the placeholder.
- MODIFY `_create_llm_client` (`:1028`): drop the `conversation_memory`
  parameter and the injection (`:1035-1036`, `:1055`); update the call at
  `:1534`.
- MODIFY `get_infographic` (`:4330`): remove `session_id=`/`user_id=` from
  the `client.ask(...)` call at `:4412` (this call has no history; nothing
  replaces them).
- Stop-gap in `bots/base.py` (see Context): replace the four
  `conversation_context = self.build_conversation_context(conversation_history)`
  lines with `conversation_context = ""` and remove `conversation_context=`
  from the four `create_system_prompt(...)` calls. TASK-2816 finishes the job.
- Tests in `packages/ai-parrot/tests/unit/bots/test_memory_key_id.py`.

**NOT in scope**: `render_history` wiring, `history=` in `llm_kwargs`,
replacing bot-side `ConversationTurn(...)` sites (TASK-2816); client changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | property, writer, removals, `_create_llm_client` |
| `packages/ai-parrot/src/parrot/bots/chatbot.py` | MODIFY | set `_chatbot_id_explicit` on DB load |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY (stop-gap) | 4× `conversation_context = ""` |
| `packages/ai-parrot/tests/unit/bots/test_memory_key_id.py` | CREATE | tests below |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.abstract import AbstractBot       # bots/abstract.py:187
from parrot.memory import ConversationTurn, InMemoryConversation   # memory/__init__.py:3,11
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(...):                                                  # line 187
    self.chatbot_id: uuid.UUID = kwargs.get('chatbot_id', str(uuid.uuid4().hex))   # line 353-356
    if self.chatbot_id is None: self.chatbot_id = str(uuid.uuid4().hex)  # line 357-358
    self.name: str = name                                                # line 361
    self.conversation_memory: Optional[ConversationMemory] = None        # line 585
    self.max_context_turns: int = kwargs.get('max_context_turns', 50)    # line 590
    def _create_llm_client(self, config: LLMConfig, conversation_memory=None) -> AbstractClient  # line 1028
        # config.client_instance.conversation_memory = conversation_memory   :1035-1036
        # client = config.client_class(..., conversation_memory=conversation_memory, ...)  :1055
    self._llm = self._create_llm_client(config, self.conversation_memory)   # line 1534
    def _build_prompt(self, ..., conversation_context: str = "", ...)    # line 1382 (kwarg :1386, "chat_history": conversation_context :1440)
    async def get_conversation_history(...)                              # line 1798
    async def create_conversation_history(...)                           # line 1816
    async def save_conversation_turn(self, user_id, session_id, turn, chatbot_id=None) -> None  # line 1836
        # chatbot_key = chatbot_id or getattr(self, 'chatbot_id', None)  :1847  ← remove
        # await self.conversation_memory.add_turn(user_id, session_id, turn, chatbot_id=chatbot_key)  :1849
        # MessageAddedEvent emission                                       :1857-1870 keep
    async def clear_conversation_history(...) / delete_conversation_history(...)  # lines 1873 / 1897
    def build_conversation_context(self, history, max_chars_per_message=200, max_total_chars=1500, ...)  # line 2912 ← remove
    async def create_system_prompt(self, user_context="", vector_context="", conversation_context="", ...)  # line 3072
        # conversation_context passthrough :3116 ; "## Conversation Context:" :3162-3163
    async def get_infographic(...)   # line 4330 ; client.ask(..., session_id=session_id, user_id=user_id) :4412-4416

# packages/ai-parrot/src/parrot/bots/base.py — stop-gap sites
    conversation_context = self.build_conversation_context(conversation_history)   # lines 329, 687, 1102, 1693
    system_prompt = await self.create_system_prompt(..., conversation_context=conversation_context, ...)  # ~:1218-1227 and siblings

# packages/ai-parrot/src/parrot/bots/chatbot.py
    bot = await self.bot_exists(name=self.name, uuid=self.chatbot_id)   # line 150
    # assignments of self.chatbot_id from BotModel around :161, :287-289, :333 — grep "self.chatbot_id =" bots/chatbot.py
```

### Does NOT Exist
- ~~`AbstractBot.memory_key_id`~~, ~~`AbstractBot._chatbot_id_explicit`~~ — you create them.
- ~~`AbstractBot._record_turn` / `_save_turn`~~ — do not exist; the writer is `save_conversation_turn`.
- ~~callers of `save_conversation_turn`~~ — zero today in `packages/*/src`; changing its signature breaks nothing.
- ~~`render_history` use in bots~~ — TASK-2816.

---

## Implementation Notes

### Pattern to Follow
```python
@property
def memory_key_id(self) -> str:
    if getattr(self, "_chatbot_id_explicit", False) and self.chatbot_id:
        return str(self.chatbot_id)
    return str(self.name)

async def save_conversation_turn(self, user_id: str, session_id: str, turn: ConversationTurn) -> None:
    if not self.conversation_memory:
        return
    key_id = self.memory_key_id
    if turn.chatbot_id != key_id:
        raise ValueError(f"turn.chatbot_id={turn.chatbot_id!r} != memory_key_id={key_id!r}")
    await self.conversation_memory.add_turn(user_id, session_id, turn, chatbot_id=key_id)
    ...  # existing MessageAddedEvent emission unchanged
```

### Key Constraints
- `'chatbot_id' in kwargs and kwargs['chatbot_id'] is not None` is the explicitness test at `:353`.
- Keep `AIMessage.set_conversation_context_info()` calls in base.py untouched (TASK-2816 feeds them from `len(rendered)`).
- After this task `grep -rn "build_conversation_context\|conversation_context=" packages/ai-parrot/src` must return zero lines.

---

## Acceptance Criteria

- [ ] `memory_key_id`: explicit id ⇒ that id; no id ⇒ `name`; `chatbot_id=None` explicitly ⇒ `name`.
- [ ] `save_conversation_turn` keys by `memory_key_id`; mismatch ⇒ `ValueError`; emits `MessageAddedEvent` once.
- [ ] `_create_llm_client` result has no `conversation_memory` injected (check with a client instance lacking the attribute — after TASK-2812 the attribute is gone; until then assert it is not *set* by the bot).
- [ ] No `build_conversation_context` / `conversation_context` references remain in `packages/ai-parrot/src`.
- [ ] Existing bot tests still pass: `timeout -s KILL 600 pytest packages/ai-parrot/tests/bots tests/unit -q`.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/abstract.py packages/ai-parrot/src/parrot/bots/base.py` clean.

---

## Test Specification

```python
def test_memory_key_id_explicit_vs_name():
    assert AbstractBotStub(name="x", chatbot_id="abc").memory_key_id == "abc"
    assert AbstractBotStub(name="x").memory_key_id == "x"
    a, b = AbstractBotStub(name="x"), AbstractBotStub(name="x")
    assert a.memory_key_id == b.memory_key_id            # stable across "restarts"

@pytest.mark.asyncio
async def test_save_conversation_turn_keys_by_memory_key_id():
    bot = AbstractBotStub(name="x"); bot.conversation_memory = InMemoryConversation()
    await bot.conversation_memory.create_history("u", "s", chatbot_id="x")
    await bot.save_conversation_turn("u", "s", ConversationTurn("t", "u", "q", "a", chatbot_id="x"))
    assert len((await bot.conversation_memory.get_history("u", "s", chatbot_id="x")).turns) == 1
    with pytest.raises(ValueError):
        await bot.save_conversation_turn("u", "s", ConversationTurn("t2", "u", "q", "a", chatbot_id="other"))
```
(`AbstractBotStub`: minimal concrete subclass; see how `tests/bots/test_voicebot_contract.py` or `tests/unit/bots/` instantiate bots without LLM config.)

---

## Agent Instructions

1. Read spec §2 Storage key + §3 M3 + §7 risks. 2. Verify contract lines (they may have shifted).
3. Tests first. 4. Commit only listed files. 5. Move to `completed/`, update index, fill note (list any `self.chatbot_id =` sites you flagged as explicit).

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-04
**Notes**:
- `AbstractBot._chatbot_id_explicit` set at `abstract.py:353-364` from
  `kwargs.get('chatbot_id') is not None`; `memory_key_id` property added next to the
  conversation helpers.
- `save_conversation_turn(user_id, session_id, turn)` — `chatbot_id` parameter removed,
  keys by `self.memory_key_id`, raises `ValueError` on attribution mismatch **before**
  writing or emitting, `MessageAddedEvent` emission unchanged.
- All six read/write helpers (`get_/create_/clear_/delete_conversation_history`,
  `list_user_conversations`, `save_conversation_turn`) now resolve
  `str(chatbot_id) if chatbot_id else self.memory_key_id`, replacing the old
  `chatbot_id or getattr(self, 'chatbot_id', None)` fallback that resolved to the
  random uuid.
- Removed `build_conversation_context` (with its three `print()` debug lines) and the
  entire `conversation_context` plumbing: the kwarg on both `_build_prompt` and
  `create_system_prompt`, their docstring lines, the `"chat_history"` template slot,
  the `## Conversation Context:` section, and the `conversation_context` entry in the
  dynamic-value provider context. `chat_history=""` is now passed to the template so
  the placeholder resolves empty instead of leaking a literal `$chat_history`.
- `_create_llm_client(self, config)` — parameter and both injection sites gone.
- Verified AC: `grep -rn "build_conversation_context\|conversation_context=" packages/ai-parrot/src`
  returns **zero** lines.
- Tests: `test_memory_key_id.py`, 20 passed. Regression check against `dev` (same
  command run in both trees):
  * `packages/ai-parrot/tests/unit/bots`: worktree 263 passed / 5 failed vs dev 243
    passed / 5 failed — **identical failure set**, all pre-existing
    (`test_flex_dashboard_agent`, `test_infographic_authoring_mixin`, 3×
    `test_pandasagent_stale_data_variables`; the first two pass in isolation and fail
    only under whole-directory pollution, on `dev` too).
  * `packages/ai-parrot/tests/bots`: worktree 70 failed / 1429 passed vs dev 71 failed /
    1428 passed. Set diff shows **zero real regressions** — the only worktree-only
    failures are 3 `test_porygon_identity_migration` tests that read `agents/porygon.py`
    and `agents/porygon/identity/role.md`; `/agents/` is gitignored (`.gitignore:294`) so
    those files simply do not exist in a worktree. 4 `test_chrome_runner` tests are
    flaky in the opposite direction (fail on dev, pass here).
  * `packages/ai-parrot/tests/unit/memory`: TASK-2808's 3 tests still red as designed —
    now failing on `'ConversationHistory' object has no attribute 'get_messages_for_api'`
    from `clients/base.py:2322`, which TASK-2812 deletes.

**Deviations from spec**:
1. **`get_infographic` needed no change — the task's contract is wrong.** It states
   `get_infographic` calls `client.ask(..., session_id=, user_id=)` at `:4412`. The call
   is actually `self.ask(...)` — the BOT's own entry point, which legitimately keeps
   `user_id`/`session_id` (only the CLIENT loses them). Verified: `get_infographic`'s
   body contains no direct client call. Removing the ids there would have disabled
   history for infographics entirely.
2. **`_create_llm_client` has 5 call sites and an override, not the 1 the task lists.**
   Changing the signature forced updating all of them in lock-step, three of which are
   outside this task's declared file list:
   `bots/voice.py` (the `VoiceCapable` override + 2 calls + 2 client-constructor
   `conversation_memory=` kwargs), `interfaces/tools.py:321` (`configure_llm`), and
   `packages/ai-parrot-integrations/.../voice/handler.py:1692`. Leaving any of them would
   be a hard `TypeError` at runtime.
3. **The digest stop-gap needed 7 sites, not the 4 the task lists.** `bots/base.py` ×4
   (as specified) plus `bots/data.py:1352` and `bots/voice.py:569/803`. Same reason: the
   method being removed had callers the task did not enumerate. All are now
   `conversation_context = ""` with a `FEAT-524 stop-gap (TASK-2811)` comment pointing at
   TASK-2816.
4. **10 new transitional `ruff F841` warnings** (`conversation_history` /
   `conversation_context` assigned but unused) across `base.py`, `data.py`, `voice.py`.
   They exist precisely because the digest is gone but `render_history` is not yet wired;
   TASK-2816 consumes both variables again. Deliberately NOT silenced with `# noqa` —
   adding markers only to delete them one task later is churn. Baseline note: these files
   already carried 28 ruff errors on `dev`, so "ruff clean" was never true for them.
5. `_smart_truncate` / `_simple_truncate` are now unreferenced (they existed only for
   `build_conversation_context`). Left in place — removing them is outside this task's
   scope and they are harmless generic helpers.
