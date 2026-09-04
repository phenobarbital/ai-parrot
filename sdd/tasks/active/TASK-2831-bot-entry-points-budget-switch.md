# TASK-2831: Switch every bot entry point to `render_context_history` + commit; `max_context_turns` ceiling semantics in `Chatbot`

**Feature**: FEAT-525 — Per-Turn Conversation Compaction
**Spec**: `sdd/specs/per-turn-conversation-compaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2825, TASK-2830 *(external prerequisite: FEAT-524 merged — see banner)*
**Assigned-to**: unassigned

> ⚠️ **FEAT-524 prerequisite (spec C14).** The render sites this task
> rewrites are created by FEAT-524 TASK-2816 (`rendered_history =
> render_history(conversation_history, max_turns=self.max_context_turns,
> current_chatbot_id=self.memory_key_id)`), which was still uncommitted in the
> FEAT-524 worktree on 2026-09-04. All line numbers below marked
> *(FEAT-524 branch)* WILL shift; locate each site by grepping for
> `render_history(` and `save_conversation_turn(` on the merged `dev`.

---

## Context

Spec §3 Module 12 (entry-point half), goal G3 (default-on) and G10
(`Chatbot` DB value is a ceiling override; absent ⇒ `ContextBudget.max_turns`
= 30) plus the §2 "Derived decision" on `chatbot.py:406`. After TASK-2830 the
bot has `render_context_history()`, `estimate_prompt_tokens()`,
`build_compaction_commit()` and `save_conversation_turn(compaction=)`. This
task makes every stateful round use them, and closes the calibration loop
(prompt estimate ↔ provider `usage.input_tokens`) inside the single writer.

---

## Scope

- `bots/base.py` — in each of `conversation`, `invoke`, `ask`, `ask_stream`
  (FEAT-524 branch render sites `:333`, `:691`, `:1108`, `:1699`; save sites `:537`, `:757`, `:1349`, `:1866`):
  - replace `rendered_history = render_history(conversation_history, max_turns=self.max_context_turns, current_chatbot_id=self.memory_key_id)`
    with `rendered_history, compaction_result = await self.render_context_history(conversation_history)`
    (initialise `compaction_result = None` where the history branch is optional so the save path always sees the name);
    `history=rendered_history` to the client and the `set_conversation_context_info(... len(rendered_history) ...)` feed stay as FEAT-524 left them.
  - at the save site: `prompt_estimate = self.estimate_prompt_tokens(rendered_history, system_prompt, question)` when
    `compaction_result is not None` (use the local names each method actually passes to the client — the system prompt
    variable is `system_prompt` in all four on the FEAT-524 branch, `:410/:698/:1228/:1748`);
    `await self.save_conversation_turn(user_id, session_id, turn, compaction=self.build_compaction_commit(compaction_result, prompt_estimate))`.
  - `ask_stream` partial-save-on-error path (FEAT-524 branch `:1849-1866`, the `ConversationTurn(...)` built from `full_response`):
    keep `compaction=None` (no estimate to pair — spec §7).
  - remove the now-unused `render_history` import from `bots/base.py` if nothing else uses it (ruff F401).
- `bots/data.py` (FEAT-524 branch render `:1354`, save `:2103`) and `bots/voice.py` (render `:798`; saves `:634`, `:675`):
  same switch. Voice transcript saves (`:634`, `:675`) have no rendered prompt ⇒ `compaction=None`.
- `bots/chatbot.py`: `:236` → `getattr(self, 'max_context_turns', None)`; `:406` (FEAT-524 branch `:414`) →
  `self._from_db(bot, 'max_context_turns', default=None)`; `:578`, `:626` (`:586`, `:634`) → `getattr(self, 'max_context_turns', None)`
  (serializers must accept `None`). Note `_from_db` (`:182`) returns `value or default`, so a DB `0` also means "no override" — acceptable, document it.
- Tests: `tests/unit/bots/test_entry_points_budget.py` — kill-switch byte equality across the four `BaseBot` entry points,
  commit reaches `add_turn`, `ask_stream` partial save passes no commit, `Chatbot` ceiling override; `tests/unit/bots/test_chatbot_max_context_turns.py`
  if a `Chatbot` fixture without a DB is feasible (else cover via `_from_db` + property unit tests).

**NOT in scope**: `AbstractBot` helpers (TASK-2830); ContextVar binding (TASK-2825 — already in these methods; keep it intact); docs/exports (TASK-2832).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | four render sites + four save sites; partial-save keeps `compaction=None`; drop unused import |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | render + save site |
| `packages/ai-parrot/src/parrot/bots/voice.py` | MODIFY | render site; transcript saves pass `compaction=None` explicitly (or rely on the default) |
| `packages/ai-parrot/src/parrot/bots/chatbot.py` | MODIFY | `max_context_turns` default `None` at four sites |
| `packages/ai-parrot/tests/unit/bots/test_entry_points_budget.py` | CREATE | byte equality, commit propagation, partial save, ceiling |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use only what is listed here. Verify anything else before using it.

### Verified Imports
```python
from parrot.memory import ConversationTurn, render_history        # FEAT-524 branch: bots/base.py:17 (render_history import may become unused here)
from parrot.memory.render import render_history                    # FEAT-524 branch: bots/data.py:36
from parrot.memory import ConversationTurn, render_history        # FEAT-524 branch: bots/voice.py:37
from parrot.memory.compaction.models import CompactionCommit, ContextBudget   # TASK-2819 (tests)
from parrot.bots.base import BaseBot ; from parrot.bots.chatbot import Chatbot   # dev
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/base.py  (FEAT-524 branch @ 89acaeaab + TASK-2816 WIP — re-verify)
async def conversation(...)  :154   render :333-337   save :530-537 (ConversationTurn.from_ai_message(...); await self.save_conversation_turn(user_id, session_id, turn))
async def invoke(...)        :598   render :691-695   save :750-757
async def ask(...)           :932   render :1108-1112 save :1342-1349 ; system_prompt = await self.create_system_prompt(...) :1228 ; client call passes system_prompt=system_prompt :1247, history=rendered_history
async def ask_stream(...)    :1597  render :1699-1703 ; partial save :1849-1866 builds ConversationTurn(turn_id=_turn_id, ..., assistant_response=full_response, tools_used=[], chatbot_id=self.memory_key_id)
#   render shape at every site:
#       rendered_history = render_history(conversation_history, max_turns=self.max_context_turns, current_chatbot_id=self.memory_key_id)

# packages/ai-parrot/src/parrot/bots/data.py (FEAT-524 branch): render :1354-1358 ; save :2093-2103 (from_ai_message(..., assistant_text=answer_text or ""))
# packages/ai-parrot/src/parrot/bots/voice.py (FEAT-524 branch): render :798-802 → history=rendered_history :823 ; transcript saves :634-636, :675

# packages/ai-parrot/src/parrot/bots/chatbot.py (dev | FEAT-524 branch)
def _from_db(self, botobj, key, default: str = None) -> Any: value = getattr(botobj, key, default); return value or default   # :182-184
self.max_context_turns = getattr(self, 'max_context_turns', 5)                # :236 | :236
self.max_context_turns = self._from_db(bot, 'max_context_turns', default=5)   # :406 | :414
'max_context_turns': getattr(self, 'max_context_turns', 5),                   # :578, :626 | :586, :634  (serialization dicts)

# TASK-2830 (AbstractBot):
#   async def render_context_history(self, history) -> Tuple[List[HistoryMessage], Optional[CompactionResult]]
#   def estimate_prompt_tokens(self, rendered, system_prompt, prompt) -> int
#   def build_compaction_commit(self, result, prompt_estimate) -> Optional[CompactionCommit]
#   async def save_conversation_turn(self, user_id, session_id, turn, *, compaction=None) -> None
#   self.max_context_turns: Optional[int] (default None) ; property context_budget
# Test precedent: FEAT-524 branch tests/unit/memory/test_history_ownership.py — RecordingClient captures history=/system_prompt= per call (:43-135)
```

### Does NOT Exist
- ~~`render_history(..., budget=…)`~~ — no; the budget path is `self.render_context_history(history)`.
- ~~`save_conversation_turn(user_id, session_id, turn, chatbot_id=…)`~~ — FEAT-524 removed `chatbot_id`; the only new kwarg is `compaction`.
- ~~Hand-rolled `memory.add_turn(...)` in bots~~ — dev `base.py:539, :757, :1349, :1853`, `data.py:2102`, `voice.py:642, :683` are rewritten by FEAT-524 to `save_conversation_turn`; if any survive on the merged branch, route them through `save_conversation_turn` (never call `add_turn` from a bot).
- ~~`Chatbot.max_context_turns` default 5 after this task~~ — becomes `None` (ceiling from `ContextBudget.max_turns`); a DB record with a value keeps overriding.
- ~~A stream-time estimate for `ask_stream`'s partial save~~ — none; it passes `compaction=None` by design.

---

## Implementation Notes

### Pattern to Follow
```python
# each entry point — render
compaction_result = None
if use_conversation_history and memory:
    conversation_history = await self.get_conversation_history(...) or await self.create_conversation_history(...)
    rendered_history, compaction_result = await self.render_context_history(conversation_history)
...
# each entry point — save (happy path)
turn = ConversationTurn.from_ai_message(user_message=question, response=response, user_id=user_id,
                                        chatbot_id=self.memory_key_id, turn_id=response.turn_id or turn_id)
commit = None
if compaction_result is not None:
    commit = self.build_compaction_commit(
        compaction_result, self.estimate_prompt_tokens(rendered_history, system_prompt, question))
await self.save_conversation_turn(user_id, session_id, turn, compaction=commit)
```

### Key Constraints
- Kill-switch byte equality: with `context_budget=False` the `history=` list the stub client receives must `==` `render_history(history, max_turns=30, current_chatbot_id=key)`; with the env var likewise; with a real budget and a text-only history it must **also** be equal (text-only views ≡ plain render, TASK-2824).
- Do not reorder the ContextVar binding TASK-2825 placed after the id defaults.
- Keep each method's existing error handling; the commit is built only when a result exists.
- `ruff` must not flag an unused `render_history` import; remove it where it becomes unused.

### References in Codebase
- FEAT-524 branch `bots/base.py` `ask()` `:1100-1125` and `:1342-1349` — the two shapes to modify.
- `packages/ai-parrot/tests/unit/memory/test_history_ownership.py` (FEAT-524) — `RecordingClient` to assert on `history=`.

---

## Acceptance Criteria

- [ ] `test_kill_switch_byte_equality` (×4 entry points): `context_budget=False` and `PARROT_COMPACTION_DISABLED=1` ⇒ client receives `history ==` FEAT-524 plain render; default budget on a text-only history ⇒ same list.
- [ ] `test_commit_reaches_add_turn` (×4): a spy memory sees `add_turn(..., compaction=CompactionCommit(...))` with `prompt_estimate > 0`, `boundary_turn_id`/`stage2_needed` from the result.
- [ ] `test_ask_stream_partial_save_no_commit`: client raising mid-stream after some text ⇒ `add_turn` called once with `compaction=None` and the partial text.
- [ ] `test_max_context_turns_ceiling_override`: `Chatbot` with a DB value `12` ⇒ `context_budget.max_turns == 12`; without a value ⇒ `30` and `max_context_turns is None`; serialization dicts carry `None`.
- [ ] `data.py`/`voice.py` render sites use `render_context_history`; voice transcript saves pass no commit (source assertion or targeted test).
- [ ] `git diff --stat -- packages/ai-parrot/src/parrot/clients` is empty.
- [ ] All tests pass: `timeout -s KILL 600 pytest packages/ai-parrot/tests/unit/bots packages/ai-parrot/tests/unit/memory -q`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/base.py packages/ai-parrot/src/parrot/bots/data.py packages/ai-parrot/src/parrot/bots/voice.py packages/ai-parrot/src/parrot/bots/chatbot.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_entry_points_budget.py
import pytest
from parrot.memory import render_history
from parrot.memory.compaction.models import CompactionCommit


@pytest.mark.parametrize("entry", ["conversation", "invoke", "ask", "ask_stream"])
@pytest.mark.parametrize("mode", ["kwarg_false", "env", "default_text_only"])
async def test_kill_switch_byte_equality(make_bot, seeded_history, entry, mode, monkeypatch):
    kwargs = {"context_budget": False} if mode == "kwarg_false" else {}
    if mode == "env": monkeypatch.setenv("PARROT_COMPACTION_DISABLED", "1")
    bot, client, mem = make_bot(**kwargs)                     # stub client records history= per call
    await seeded_history(mem, bot.memory_key_id, "u", "s", turns=5)   # text-only turns
    await run_entry(bot, entry, "hello", user_id="u", session_id="s")
    expected = render_history(await mem.get_history("u", "s", chatbot_id=bot.memory_key_id), max_turns=30, current_chatbot_id=bot.memory_key_id)
    assert client.calls[-1]["history"][: len(expected)] == expected


@pytest.mark.parametrize("entry", ["conversation", "invoke", "ask", "ask_stream"])
async def test_commit_reaches_add_turn(make_bot, spy_memory, entry):
    bot, client, mem = make_bot(memory=spy_memory)
    await run_entry(bot, entry, "hello", user_id="u", session_id="s")
    (call,) = mem.add_turn_calls
    assert isinstance(call["compaction"], CompactionCommit) and call["compaction"].prompt_estimate > 0


async def test_ask_stream_partial_save_no_commit(make_bot, spy_memory, failing_stream_client):
    bot, _, mem = make_bot(memory=spy_memory, client=failing_stream_client)   # yields "par", "tial" then raises
    with pytest.raises(Exception):
        async for _ in bot.ask_stream("q", user_id="u", session_id="s"): pass
    (call,) = mem.add_turn_calls
    assert call["compaction"] is None and call["turn"].assistant_response == "partial"


def test_max_context_turns_ceiling_override(make_chatbot):
    assert make_chatbot(db_max_context_turns=12).context_budget.max_turns == 12
    b = make_chatbot(db_max_context_turns=None)
    assert b.max_context_turns is None and b.context_budget.max_turns == 30
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2825 and TASK-2830 in `sdd/tasks/completed/`; FEAT-524 merged (banner)
3. **Verify the Codebase Contract** before writing any code; grep every render/save site on the merged branch first
4. **Update status** in `sdd/tasks/index/per-turn-conversation-compaction.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2831-bot-entry-points-budget-switch.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
