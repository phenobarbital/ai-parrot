# TASK-2830: `AbstractBot` budget integration — `context_budget`, `render_context_history`, `save_conversation_turn(compaction=)`, recovery-tool registration, Stage-2 event

**Feature**: FEAT-525 — Per-Turn Conversation Compaction
**Spec**: `sdd/specs/per-turn-conversation-compaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2823, TASK-2824, TASK-2826, TASK-2828, TASK-2829
**Assigned-to**: unassigned

> ✅ **FEAT-524 merged** (PR #1310, merge `729ef7367`, 2026-09-04). Every
> FEAT-524 anchor below was re-verified on `dev` @ `198e6fecd` (after the
> post-merge `black` reformat `4831528a4`); `memory/render.py`,
> `ConversationTurn.from_ai_message` and `AbstractBot.memory_key_id` exist.

---

## Context

Spec §2 "Component Diagram" (read path), §3 Module 12 (the `AbstractBot`
half) and the `Stage2CompactionNeededEvent` half of Module 13, goals
G3/G11/G13. The bot owns the budget (auto-built from `MODEL_WINDOWS`, kill
switch `context_budget=False` / `PARROT_COMPACTION_DISABLED=1`), runs the
pure pre-pass, flushes omissions, renders, and after the round hands the
memory a `CompactionCommit` so turn + boundary + EWMA land in one write.
This task builds those helpers on `AbstractBot`; TASK-2831 switches the
entry points over to them.

---

## Scope

- `bots/abstract.py` — `__init__`:
  - `self._context_budget_raw: Optional[ContextBudget | bool] = kwargs.get('context_budget')` (set **before**
    `configure_conversation_memory()` is called at `:1408`).
  - `self.max_context_turns: Optional[int] = kwargs.get('max_context_turns')` — default `None` (was `50` at `:541`). That is the only read of `max_context_turns` left in `abstract.py` (FEAT-524 removed `build_conversation_context`; verified 2026-09-04) — grep once more before editing.
  - `self._budget_window_logged: bool = False`.
- `@property context_budget(self) -> Optional[ContextBudget]`:
  `raw is False or compaction_disabled_by_env()` ⇒ `None`; `isinstance(raw, ContextBudget)` ⇒
  `replace(raw, max_turns=self.max_context_turns) if self.max_context_turns else raw`;
  `raw is None/True` ⇒ `build_default_budget(self._llm_model, max_turns=self.max_context_turns)`, logging **once per bot**
  (`self._budget_window_logged`) at INFO when `resolve_window(self._llm_model) == FALLBACK_WINDOW`.
- `async def render_context_history(self, history: Optional[ConversationHistory]) -> Tuple[List[HistoryMessage], Optional[CompactionResult]]`:
  `budget = self.context_budget`; if `None` or `history is None` or no `conversation_memory` ⇒
  `(render_history(history, max_turns=self.max_context_turns or 30, current_chatbot_id=self.memory_key_id), None)`
  — **byte-identical to FEAT-524's plain path**. Otherwise: `state = history.metadata.get("compaction") or {}`;
  `result = compact_history(history, budget, boundary_turn_id=state.get("boundary_turn_id"),
  calibration=state.get("calibration", 1.0), counter=memory.token_counter, current_chatbot_id=self.memory_key_id)`;
  `try: await memory.omission_store.put_many(memory.omission_key(history.user_id, history.session_id, self.memory_key_id), result.omissions)`
  `except Exception: self.logger.warning(...)` and return the plain path with `None` (boundary untouched);
  else `(render_history(result.views, current_chatbot_id=self.memory_key_id), result)`.
- `def estimate_prompt_tokens(self, rendered: Sequence[HistoryMessage], system_prompt: Optional[str], prompt: str) -> int`:
  `counter = memory.token_counter` (or `get_default_counter()`); sum of `counter.count(m.content)` + `counter.count(system_prompt or "")` + `counter.count(prompt or "")`.
- `def build_compaction_commit(self, result: Optional[CompactionResult], prompt_estimate: int) -> Optional[CompactionCommit]`:
  `None` when `result is None`; else `CompactionCommit(prompt_estimate=prompt_estimate, boundary_turn_id=result.boundary_turn_id,
  stage2_needed=result.stage2_needed, history_estimate=result.history_estimate, dropped_turns=len(result.dropped_turn_ids))`
  (the two telemetry fields were added to `CompactionCommit` by TASK-2819 with defaults `0`).
- `async def save_conversation_turn(self, user_id, session_id, turn, *, compaction: Optional[CompactionCommit] = None) -> None`:
  keep the FEAT-524 body (early return without memory; `memory_key_id` check raising `ValueError`); when
  `compaction is not None and compaction.stage2_needed`, read the persisted flag first
  (`prev = (await memory.get_history(user_id, session_id, chatbot_id=key)); was = bool((prev.metadata.get("compaction") or {}).get("stage2_needed"))`);
  `await memory.add_turn(user_id, session_id, turn, chatbot_id=key, compaction=compaction)`; emit `MessageAddedEvent`
  as today; then if `compaction and compaction.stage2_needed and not was`: `await self.events.emit(Stage2CompactionNeededEvent(
  trace_context=trace_ctx, agent_name=self.name, session_id=session_id, history_estimate=compaction.history_estimate,
  available=(self.context_budget.available if self.context_budget else 0), dropped_turns=compaction.dropped_turns,
  source_type="agent", source_name=self.name))`.
- `def _register_recovery_tool(self) -> None`: if `self.conversation_memory` is set, `self.context_budget is not None`
  and `"read_omitted_content" not in self.tool_manager.list_tools()`:
  `self.tool_manager.register_tool(name=READ_OMITTED_CONTENT_NAME, description=READ_OMITTED_CONTENT_DESCRIPTION,
  input_schema=READ_OMITTED_CONTENT_SCHEMA, function=bind_read_omitted_content(self.conversation_memory))`.
  Call it at the end of `configure_conversation_memory()` (both the success and the in-memory fallback branch).
- New `core/events/lifecycle/events/memory.py` with `@dataclass(frozen=True) class Stage2CompactionNeededEvent(LifecycleEvent)`:
  `agent_name: str = ""; session_id: str = ""; history_estimate: int = 0; available: int = 0; dropped_turns: int = 0`
  (module docstring in the style of `message.py`); export from `events/__init__.py` (import + `__all__`).
- Tests: `tests/unit/bots/test_context_budget.py` (budget resolution, kill switches, ceiling override, flush-failure
  fallback, calibration pairing, stage-2 event once, recovery tool registered) and add the new event to
  `tests/unit/events/lifecycle/test_concrete_events.py`'s parametrized list (or a sibling file if that list is closed).

**NOT in scope**: switching the entry points in `bots/base.py`/`data.py`/`voice.py`/`chatbot.py` (TASK-2831);
`memory/__init__.py` exports and docs (TASK-2832).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | kwargs, `context_budget` property, `render_context_history`, `estimate_prompt_tokens`, `build_compaction_commit`, `save_conversation_turn(compaction=)`, `_register_recovery_tool`, Stage-2 emission |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/memory.py` | CREATE | `Stage2CompactionNeededEvent` |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/__init__.py` | MODIFY | import + `__all__` entry |
| `packages/ai-parrot/tests/unit/bots/test_context_budget.py` | CREATE | see Acceptance Criteria |
| `packages/ai-parrot/tests/unit/events/lifecycle/test_concrete_events.py` | MODIFY | add the event to the parametrized class list |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use only what is listed here. Verify anything else before using it.

### Verified Imports
```python
from parrot.memory import ConversationMemory, ConversationTurn, ConversationHistory     # dev 198e6fecd: bots/abstract.py:38-45 already imports these (NOT render_history/HistoryMessage — add those)
from parrot.memory import HistoryMessage, render_history                                 # dev: memory/__init__.py:13
from parrot.memory.compaction.models import ContextBudget, CompactionCommit, CompactionResult, FALLBACK_WINDOW   # TASK-2819
from parrot.memory.compaction.budget import build_default_budget, compaction_disabled_by_env, resolve_window       # TASK-2823
from parrot.memory.compaction.compact import compact_history                             # TASK-2828
from parrot.memory.compaction.tokens import get_default_counter                          # TASK-2821
from parrot.memory.compaction.recover import (READ_OMITTED_CONTENT_NAME, READ_OMITTED_CONTENT_DESCRIPTION,
                                              READ_OMITTED_CONTENT_SCHEMA, bind_read_omitted_content)             # TASK-2829
from parrot.core.events.lifecycle import EventEmitterMixin, TraceContext                 # dev: bots/abstract.py:122
from parrot.core.events.lifecycle.events import MessageAddedEvent                        # dev: events/__init__.py:39 ; imported in abstract.py:128
from navigator_eventbus.lifecycle.base import LifecycleEvent                             # dev: events/message.py:8
from dataclasses import replace
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py  (dev @ 198e6fecd — FEAT-524 merged, black-formatted)
self._chatbot_id_explicit: bool = kwargs.get("chatbot_id") is not None     # :334
self.tool_manager: ToolManager = ToolManager(...)                          # :358
self._llm_model = _explicit_llm_model or self.default_model                # :458   ← model name for MODEL_WINDOWS
self.conversation_memory: Optional[ConversationMemory] = None              # :536
self.max_context_turns: int = kwargs.get("max_context_turns", 50)          # :541   ← becomes Optional, default None
def configure_conversation_memory(self) -> None                            # :1197  (success branch + in-memory fallback)
            self.configure_conversation_memory()                           # :1408  (inside __init__ configuration; after tool_manager :358 and _llm_model :458)
self._llm_model = config.model                                             # :1436  (model may change after init → do not cache the budget by model)
@property def memory_key_id(self) -> str                                   # :1676-1700
async def get_conversation_history(self, user_id, session_id, ...)         # :1703 ; create_conversation_history :1712
async def save_conversation_turn(self, user_id, session_id, turn) -> None  # :1721-1773  (add_turn call :1754; MessageAddedEvent emit :1763-1773):
#     if not self.conversation_memory: return
#     chatbot_key = self.memory_key_id ; if turn.chatbot_id != chatbot_key: raise ValueError(...)
#     await self.conversation_memory.add_turn(user_id, session_id, turn, chatbot_id=chatbot_key)
#     trace_ctx = getattr(self, '_current_trace_context', None) or TraceContext.new_root()
#     await self.events.emit(MessageAddedEvent(trace_context=trace_ctx, agent_name=self.name, role="turn",
#                            content_length=..., has_tool_calls=..., source_type="agent", source_name=self.name))   ← emission shape to copy

# packages/ai-parrot/src/parrot/core/events/lifecycle/events/message.py (dev)
@dataclass(frozen=True) class MessageAddedEvent(LifecycleEvent): agent_name: str = ""; role: str = ""; content_length: int = 0; has_tool_calls: bool = False   # :11-31
# events/__init__.py: from ...events.message import MessageAddedEvent :39 ; "MessageAddedEvent" in __all__ :74 ; existing files: agent, client, flow, invoke, message, tool
# tests/unit/events/lifecycle/test_concrete_events.py: parametrized over every concrete event class (instantiate defaults, frozen, to_dict json) — add the new class

# TASK-2826: ConversationMemory.add_turn(user_id, session_id, turn, chatbot_id=None, *, compaction=None) ; .token_counter ; .omission_store ; .omission_key(...)
# TASK-2828: compact_history(history, budget, *, policies=None, boundary_turn_id=None, counter=None, calibration=1.0, current_chatbot_id=None, include_other_agents=True) -> CompactionResult
# TASK-2824: render_history(history_or_views, *, max_turns=None, current_chatbot_id=None, ...) -> List[HistoryMessage]
# TASK-2823: build_default_budget(model, *, max_turns=None) ; compaction_disabled_by_env() ; resolve_window(model)
# TASK-2819: CompactionCommit(prompt_estimate, boundary_turn_id, stage2_needed, history_estimate=0, dropped_turns=0)
# Test precedent for a bot + stub client: tests/unit/memory/test_history_ownership.py (RecordingClient :43, bot fixture :136)
```

### Does NOT Exist
- ~~`AbstractBot.context_budget` / `render_context_history` / `estimate_prompt_tokens` / `build_compaction_commit` / `_register_recovery_tool`~~ — new here.
- ~~`save_conversation_turn(..., chatbot_id=)`~~ — removed by FEAT-524; extend the 3-parameter form with a kw-only `compaction`.
- ~~`Stage2CompactionNeededEvent`, `core/events/lifecycle/events/memory.py`~~ — new here.
- ~~`AbstractBot.build_conversation_context` / `conversation_context`~~ — removed by FEAT-524 (only a NOTE comment remains at `:2724-2728`).
- ~~A per-model window table in `parrot/clients/*`~~ — none; use `build_default_budget` (TASK-2823).
- ~~Any change under `parrot/clients/`~~ — forbidden (C11; verified by `git diff --stat -- packages/ai-parrot/src/parrot/clients` being empty).
- ~~`PARROT_COMPRESSION_DISABLED` as the kill switch~~ — FEAT-380's variable; ours is `PARROT_COMPACTION_DISABLED` via `compaction_disabled_by_env()`.

---

## Implementation Notes

### Pattern to Follow
```python
async def render_context_history(self, history):
    memory = self.conversation_memory
    budget = self.context_budget
    plain = lambda: render_history(history, max_turns=self.max_context_turns or 30, current_chatbot_id=self.memory_key_id)
    if budget is None or history is None or memory is None:
        return plain(), None
    state = history.metadata.get("compaction") or {}
    result = compact_history(history, budget, boundary_turn_id=state.get("boundary_turn_id"),
                             calibration=float(state.get("calibration", 1.0)), counter=memory.token_counter,
                             current_chatbot_id=self.memory_key_id)
    try:
        await memory.omission_store.put_many(memory.omission_key(history.user_id, history.session_id, self.memory_key_id), result.omissions)
    except Exception as exc:  # noqa: BLE001 — degrade, never fail the round
        self.logger.warning("[%s] omission flush failed (%s); rendering plain history this round", self.name, exc)
        return plain(), None
    return render_history(result.views, current_chatbot_id=self.memory_key_id), result
```

### Key Constraints
- The kill-switch path must produce the **same object list** FEAT-524 produced (`test_kill_switch_byte_equality` lives in TASK-2831 but this helper is what it exercises).
- Flush failure ⇒ plain render **and** `None` result ⇒ no commit ⇒ boundary unchanged (spec §5 bullet).
- Stage-2 event: exactly once per session on the first `False → True` flip, decided on the **persisted** flag read before the write.
- `_register_recovery_tool` must run after `self.tool_manager` exists (`:358` precedes the `configure_conversation_memory()` call at `:1408` — verified).
- Google-style docstrings; `self.logger`; no `print`.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/abstract.py:1721-1773` — body to extend.
- `packages/ai-parrot/src/parrot/core/events/lifecycle/events/message.py` — event file template.

---

## Acceptance Criteria

- [ ] `test_default_budget_from_model`: bot with `_llm_model="claude-sonnet-5"` ⇒ `context_budget.window == 200_000`; unknown model ⇒ `32_000` and exactly one INFO log across two property reads.
- [ ] `context_budget=False` ⇒ property is `None`; `PARROT_COMPACTION_DISABLED=1` ⇒ `None`; `ContextBudget(window=50_000)` + `max_context_turns=12` ⇒ `.max_turns == 12`; default `max_turns == 30`; `bot.max_context_turns is None` by default.
- [ ] `render_context_history` with budget `None` returns `(render_history(history, max_turns=30, current_chatbot_id=key), None)` — equal lists.
- [ ] `test_flush_failure_falls_back_to_plain`: `put_many` raising ⇒ plain list, `None` result, one warning, `history.metadata` untouched.
- [ ] `test_calibration_pairing_in_save_turn`: `save_conversation_turn(..., compaction=CompactionCommit(100, "t1", False))` on a turn whose `metadata["usage"]["input_tokens"] == 150` ⇒ stored `metadata["compaction"]["calibration"] == 1.5`, `boundary_turn_id == "t1"`, written in the same `add_turn` call (spy: one call, `compaction` kwarg present).
- [ ] `test_stage2_event_emitted_once`: two saves with `stage2_needed=True` ⇒ one `Stage2CompactionNeededEvent` (captured via `bot.events` subscription or a spy on `emit`), fields populated.
- [ ] `test_recovery_tool_registered`: after `configure_conversation_memory()` with a budget, `"read_omitted_content" in bot.tool_manager.list_tools()`; with `context_budget=False` it is absent; registering twice does not duplicate.
- [ ] `git diff --stat -- packages/ai-parrot/src/parrot/clients` is empty.
- [ ] All tests pass: `timeout -s KILL 300 pytest packages/ai-parrot/tests/unit/bots/test_context_budget.py packages/ai-parrot/tests/unit/events/lifecycle -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/abstract.py packages/ai-parrot/src/parrot/core/events/lifecycle/events`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_context_budget.py
import pytest
from parrot.core.events.lifecycle.events import Stage2CompactionNeededEvent
from parrot.memory import InMemoryConversation
from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import CompactionCommit, ContextBudget


@pytest.fixture
def bot(make_bot):            # conftest helper: BaseBot with stub client + InMemoryConversation, accepts kwargs
    return make_bot(llm_model="claude-sonnet-5")


def test_default_budget_from_model(make_bot, caplog):
    assert make_bot(llm_model="claude-sonnet-5").context_budget.window == 200_000
    b = make_bot(llm_model="mystery-1"); b.context_budget; b.context_budget
    assert b.context_budget.window == 32_000 and sum("32" in r.message for r in caplog.records if r.levelname == "INFO") == 1


def test_kill_switches_and_ceiling(make_bot, monkeypatch):
    assert make_bot(context_budget=False).context_budget is None
    monkeypatch.setenv("PARROT_COMPACTION_DISABLED", "1"); assert make_bot().context_budget is None
    monkeypatch.delenv("PARROT_COMPACTION_DISABLED")
    b = make_bot(context_budget=ContextBudget(window=50_000), max_context_turns=12)
    assert b.context_budget.max_turns == 12 and make_bot().context_budget.max_turns == 30 and make_bot().max_context_turns is None


async def test_calibration_pairing_in_save_turn(bot):
    mem = bot.conversation_memory; await mem.create_history("u", "s", chatbot_id=bot.memory_key_id)
    turn = ConversationTurn(turn_id="t1", user_id="u", user_message="q", assistant_response="a", chatbot_id=bot.memory_key_id,
                            metadata={"usage": {"input_tokens": 150, "output_tokens": 5}})
    await bot.save_conversation_turn("u", "s", turn, compaction=CompactionCommit(100, "t1", False))
    comp = (await mem.get_history("u", "s", chatbot_id=bot.memory_key_id)).metadata["compaction"]
    assert comp["calibration"] == pytest.approx(1.5) and comp["boundary_turn_id"] == "t1"


async def test_stage2_event_emitted_once(bot, event_recorder):
    ...  # two saves with CompactionCommit(100, "t1", True, history_estimate=20_000, dropped_turns=3)
    assert [type(e) for e in event_recorder if isinstance(e, Stage2CompactionNeededEvent)].count(Stage2CompactionNeededEvent) == 1


async def test_flush_failure_falls_back_to_plain(bot, database_history, monkeypatch, caplog):
    async def boom(*a, **k): raise RuntimeError("redis down")
    monkeypatch.setattr(bot.conversation_memory.omission_store, "put_many", boom)
    rendered, result = await bot.render_context_history(database_history)
    assert result is None and any("omission flush failed" in r.message for r in caplog.records)
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2823, 2824, 2826, 2828, 2829 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code; update it first if anything changed
4. **Update status** in `sdd/tasks/index/per-turn-conversation-compaction.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2830-abstractbot-budget-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: `Stage2CompactionNeededEvent` is created here (spec lists it under Module 13) because this task is its emitter; `CompactionCommit` carries two telemetry fields (`history_estimate`, `dropped_turns`, default 0) beyond the spec's three so the event can report real numbers. | describe others if any
