# TASK-2816: Bot-side callers — render history, pass `history=`, single writer, drop ids

**Feature**: FEAT-524 — Conversation History Ownership
**Spec**: `sdd/specs/conversation-history-ownership.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2810, TASK-2811, TASK-2815
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. This is where the feature closes the loop: every bot
entry point loads history under the unified key, renders it with
`render_history`, passes it to the client as `history=`, stops passing
`user_id`/`session_id` to the client, and persists exactly one turn via
`save_conversation_turn`. TASK-2808's regression tests turn green here.

---

## Scope

`bots/base.py` — four entry points (`conversation` `:156`, `invoke` `:600`,
`ask` `:932`, `ask_stream` `:1597`):
- History load: `memory.get_history(user_id, session_id)` / `create_history(...)` at `:326`, `:684`, `:1099`, `:1690` → add `chatbot_id=self.memory_key_id`.
- Replace the TASK-2811 stop-gap `conversation_context = ""` with `rendered = render_history(conversation_history, max_turns=self.max_context_turns, current_chatbot_id=self.memory_key_id)`.
- `llm_kwargs` (`:445-446`, `:705-706`, `:1285-1286`, `:1776`): remove `"user_id"`, `"session_id"`; add `"history": rendered`.
- Feed `response.set_conversation_context_info(used=bool(rendered), context_length=len(rendered))` where it is called today (e.g. `:722-725`).
- Turn writes (`:525-539`, `:743-757`, `:1335-1349`, `:1841-1853`): replace `ConversationTurn(...)` + `memory.add_turn(user_id, session_id, turn)` with `turn = ConversationTurn.from_ai_message(user_message=question, response=response, user_id=user_id, chatbot_id=self.memory_key_id, context_used=vector_context if use_vector_context else None)` + `await self.save_conversation_turn(user_id, session_id, turn)`. `ask_stream` partial save: use `from_ai_message(..., assistant_text=full_response)` with the synthesized/fallback `AIMessage`, or build the turn directly when no `AIMessage` exists — the accumulated text must still be persisted on error.
- Remove the `ConversationTurn`/`uuid` imports from `base.py` if they become unused.

Other bots:
- `bots/data.py` `ask` (`:1294`): `llm_kwargs` `:1471` drop ids/add history; `client.ask(**llm_kwargs)` `:1541`; turn write `:2088-2102` → `from_ai_message` + `save_conversation_turn`; its `get_history` calls get `chatbot_id=self.memory_key_id`. Also `invoke` `:941-952` if it passes ids (it uses `**kwargs` — verify).
- `bots/database/agent.py` `ask` (`:362`): `call_kwargs` `:501` drop `"user_id"`/`"session_id"` (and add `history` if it loads one); `self._llm.ask(**call_kwargs)` `:534`.
- `bots/voice.py`: `ask_voice` `:697` (`client.ask(...)` `:724`), `ask` `:750` (`:828`) drop ids; `ask_stream` `:486` turn writes `:636-645`, `:683` → build `ConversationTurn(..., chatbot_id=self.memory_key_id)` from transcripts and call `save_conversation_turn(user_id, session_id, turn)`.
- `bots/flows/core/storage/synthesis.py`: `_synthesize_results` `:49` (`client.ask` `:112`), module-level `synthesize_results` `:139` (`:205`) — drop ids.
- `bots/abstract.py` `get_infographic` — already done in TASK-2811; verify.
- `packages/ai-parrot-tools/src/parrot_tools/security/summarizer.py:272`, `:416`: delete `stateless=True`.
- Final sweep: `grep -rn "\"user_id\": user_id\|user_id=user_id" packages/*/src` and inspect every hit that flows into a **client** call (bot `ask()` signatures legitimately keep ids).
- Tests: `packages/ai-parrot/tests/unit/bots/test_bot_history_wiring.py` (rows M6 in spec §4) and turn TASK-2808's tests green.

**NOT in scope**: the broad test-suite sweep (TASK-2817), docs (TASK-2818).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | 4 entry points |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `ask` kwargs + turn write |
| `packages/ai-parrot/src/parrot/bots/database/agent.py` | MODIFY | `call_kwargs` |
| `packages/ai-parrot/src/parrot/bots/voice.py` | MODIFY | ids + turn writes |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/synthesis.py` | MODIFY | ids |
| `packages/ai-parrot-tools/src/parrot_tools/security/summarizer.py` | MODIFY | delete `stateless=True` ×2 |
| `packages/ai-parrot/tests/unit/bots/test_bot_history_wiring.py` | CREATE | M6 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.memory import ConversationTurn, InMemoryConversation, HistoryMessage, render_history  # memory/__init__.py (render exports added by TASK-2809)
from parrot.bots.base import BaseBot                 # bots/base.py:71
from parrot.bots.mixins.model_switching import ModelSwitchingMixin, ModelSwitchMode  # bots/mixins/model_switching.py:57, :50
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/base.py (pre-task numbers; re-grep)
class BaseBot(AbstractBot):                                     # line 71
    async def conversation(...)  # :156 | memory :323 | get_history :326 | ctx (stop-gap) :329 | llm_kwargs ids :445-446 | ConversationTurn :525 | add_turn :539
    async def invoke(...)        # :600 | :681 | :684 | :687 | :705-706 | set_conversation_context_info :722-725 | :743 | :757
    async def ask(...)           # :932 | :1095 | :1099 | :1102 | :1285-1286 | execute_llm_call :1317 | :1335 | :1349
    async def ask_stream(...)    # :1597 | :1687 | :1690 | :1693 | :1776 | client.ask_stream(**llm_kwargs) :1804 | partial save :1841-1853 | fallback AIMessage :1856+
# AbstractBot (post-TASK-2811)
    memory_key_id -> str ; async def save_conversation_turn(self, user_id, session_id, turn) -> None ; self.max_context_turns (:590)
    async def execute_llm_call(self, client, method="ask", **llm_kwargs)     # abstract.py:1239 (kwargs pass-through)
# ConversationTurn.from_ai_message(*, user_message, response, user_id, chatbot_id, context_used=None, turn_id=None, assistant_text=None)  # TASK-2809
# AbstractClient.ask(..., history: Optional[Sequence[HistoryMessage]] = None, ...)   # TASK-2812
# bots/data.py: ask :1294 | llm_kwargs "user_id": user_id :1471 | client.ask(**llm_kwargs) :1541 | turn write :2088-2102
# bots/database/agent.py: ask :362 | call_kwargs "user_id": user_id :501 | self._llm.ask(**call_kwargs) :534
# bots/voice.py: ask_stream :486 (add_turn :642-645, :683) | ask_voice :697 (client.ask :724) | ask :750 (client.ask :828)
# bots/flows/core/storage/synthesis.py: _synthesize_results :49 (client.ask :112) | synthesize_results :139 (client.ask :205)
# parrot_tools/security/summarizer.py: self._llm.ask(prompt, structured_output=_Executive, stateless=True)  :272, :416
```

### Does NOT Exist
- ~~`build_conversation_context`~~, ~~`conversation_context=`~~ — removed by TASK-2811.
- ~~`memory.add_turn(user_id, session_id, turn)` without `chatbot_id` from a bot~~ — forbidden after this task (acceptance criterion).
- ~~`user_id`/`session_id` on any client `ask`~~ — removed; passing them raises `TypeError`.
- ~~`stateless` on `ask`~~ — removed by TASK-2812.

---

## Implementation Notes

### Pattern to Follow
```python
memory = memory or self.conversation_memory
conversation_history = None
rendered: list[HistoryMessage] = []
if use_conversation_history and memory:
    conversation_history = (await memory.get_history(user_id, session_id, chatbot_id=self.memory_key_id)
                            or await memory.create_history(user_id, session_id, chatbot_id=self.memory_key_id))
    rendered = render_history(conversation_history, max_turns=self.max_context_turns,
                              current_chatbot_id=self.memory_key_id)
...
llm_kwargs = {"prompt": prompt_for_llm, "system_prompt": system_prompt, "temperature": ...,
              "history": rendered or None, "use_tools": use_tools}
response = await self.execute_llm_call(client, "ask", **llm_kwargs)
response.set_conversation_context_info(used=bool(rendered), context_length=len(rendered))
...
if use_conversation_history and memory:
    turn = ConversationTurn.from_ai_message(user_message=question, response=response, user_id=user_id,
                                            chatbot_id=self.memory_key_id,
                                            context_used=vector_context if use_vector_context else None)
    await self.save_conversation_turn(user_id, session_id, turn)
```

### Key Constraints
- Exactly one write per round on every path, including `ModelSwitchingMixin` `fallback`/`contrastive` (write happens after `execute_llm_call` returns the merged/selected `AIMessage`; add `test_model_switching_contrastive_single_turn`).
- `ask_stream` partial-on-error persistence preserved (`test_ask_stream_partial_save_on_error`).
- Do not change bot `ask()` public signatures — bots keep `user_id`/`session_id`.

---

## Acceptance Criteria

- [ ] TASK-2808's three tests are green.
- [ ] `test_basebot_llm_kwargs_carry_history_not_ids` (all four entry points), `test_basebot_reads_history_with_key_id`, `test_ask_stream_partial_save_on_error`, `test_voicebot_turn_key_uses_memory_key_id`, `test_model_switching_contrastive_single_turn`, `test_two_agents_same_session_are_isolated`, `test_restart_keeps_history_for_unnamed_id_bot` green.
- [ ] `grep -rn "add_turn(" packages/ai-parrot/src/parrot/bots/` → only inside `save_conversation_turn`.
- [ ] `grep -rn "stateless=True" packages/ai-parrot-tools/src` → empty.
- [ ] `MessageAddedEvent` emitted once per round (spy on `bot.events.emit`).
- [ ] `timeout -s KILL 600 pytest packages/ai-parrot/tests/unit packages/ai-parrot/tests/bots tests/unit -q` — no new failures beyond those catalogued for TASK-2817; `ruff check` clean on touched files.

---

## Test Specification

```python
@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["conversation", "invoke", "ask"])
async def test_basebot_llm_kwargs_carry_history_not_ids(bot, entry):
    await getattr(bot, entry)("hello", user_id="u", session_id="s")
    kw = bot.get_client().calls[-1]["kw"]
    assert "history" in kw and "user_id" not in kw and "session_id" not in kw

@pytest.mark.asyncio
async def test_two_agents_same_session_are_isolated(memory):
    a, b = make_bot("alpha", memory), make_bot("beta", memory)
    await a.ask("hi", user_id="u", session_id="s"); await b.ask("yo", user_id="u", session_id="s")
    assert len((await memory.get_history("u", "s", chatbot_id="alpha")).turns) == 1
    assert len((await memory.get_history("u", "s", chatbot_id="beta")).turns) == 1
```

---

## Agent Instructions

1. Read spec §2 (Overview, Storage key), §3 M6, §4 M6 rows, §7 risks. 2. Re-grep every line number.
3. Work `base.py` first, then the other bots, then the sweep grep. 4. One commit per file.
5. Move to `completed/`, update index, fill note (list every caller found by the sweep).

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
