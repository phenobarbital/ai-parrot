# TASK-4806: Deferred suggestions in `ask_stream` (`defer_suggestions=True` → `AIMessage._suggestions_task`)

**Feature**: FEAT-752 — Follow-up Suggestion Chips
**Spec**: `sdd/specs/followup-suggestion-chips.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4794, TASK-4800
**Assigned-to**: unassigned

---

## Context

Spec rev 0.3, §3 Module 8 (bot half), G8, Q1. TASK-4800 awaits `_attach_suggestions` right before `yield ai_message`
in `ask_stream`, so a stream client waits for the LLM chip call before the final envelope arrives. This task adds an
opt-in path: when the caller passes `defer_suggestions=True`, the attach runs as an `asyncio.Task` started right
before the yield and parked on the message, so the handler (TASK-4807) can write the envelope first and the chips
later. **No extra item is yielded** — ~15 other `ask_stream` consumers would mis-handle one.

---

## Scope

- `AIMessage`: private attribute `_suggestions_task` (pydantic `PrivateAttr`, default `None`, never serialised).
- `BaseBot.ask_stream`: pop `defer_suggestions` from `kwargs`; at the TASK-4800 attach site, branch:
  deferred → `ai_message._suggestions_task = asyncio.create_task(self._attach_suggestions(...))`; else unchanged.
- Tests in `tests/bots/test_suggestion_stream_deferred.py`.

**NOT in scope**: the handler (TASK-4807); `ask()` (no stream, nothing to defer); other `ask_stream` overrides
(`bots/abstract.py:4793`, `bots/voice.py:527`, `bots/database/agent.py:693`, tools agents) — they ignore the kwarg.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/responses.py` | MODIFY | `_suggestions_task` private attr |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | Pop flag + deferred branch |
| `packages/ai-parrot/tests/bots/test_suggestion_stream_deferred.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# responses.py:7  from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator  ← add PrivateAttr
# base.py:13      import asyncio   (already imported)
from parrot.models import AIMessage                       # verified: models/__init__.py
from parrot.models.basic import CompletionUsage           # verified: models/basic.py:48
from parrot.models.outputs import OutputMode              # verified: models/outputs.py:23
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/base.py
async def ask_stream(self, question: str, session_id=None, user_id=None, ..., output_mode: OutputMode = OutputMode.DEFAULT,
                     ..., tenant: Optional[str] = None, **kwargs)                          # :1867-1888
#   _skill_scope = enter_active_skill_scope()                                             # :1911 (reset in finally)
#   # Maintain turn identifier generation for parity with ask()                           # :1938 (1 occurrence)
#   _turn_id = str(uuid.uuid4())                                                          # :1939
#   _trusted_source = kwargs.pop("_trusted_source", False)                                # :1940 (3 occurrences in file)
#   kwargs are NOT forwarded wholesale to the client: llm_kwargs is an explicit dict      # :2091-2098
#   yield ai_message                                                                      # :2303 (1 occurrence)
# After TASK-4800 the lines right above `yield ai_message` are:
#                     # FEAT-752: chips travel only in the final AIMessage (final stream envelope), never in text chunks.
#                     ai_message = await self._attach_suggestions(
#                         question, ai_message, output_mode=output_mode, user_id=user_id, session_id=session_id
#                     )
# AbstractBot._attach_suggestions(question, response, *, output_mode, user_id=None, session_id=None) -> AIMessage
#   — TASK-4800: never raises, mutates and returns the same instance.
# packages/ai-parrot/src/parrot/models/responses.py — class AIMessage(BaseModel); `a2ui_envelope` field at :212;
#   `suggestions` field added after it by TASK-4794.
```

### Does NOT Exist
- ~~`AIMessage._suggestions_task`~~ / ~~`defer_suggestions`~~ — created here.
- ~~a yielded `SuggestionBatch` / second item after the final `AIMessage`~~ — forbidden by design (spec Module 8).
- ~~`asyncio.create_task(..., context=...)` needed~~ — `create_task` already copies the current context; the turn
  skill / tenant ContextVars are still set at the yield point.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/models/responses.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/test_suggestion_stream_deferred.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask_stream"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `PrivateAttr` to the pydantic import and the private attr on `AIMessage` — *why*: the handler needs a handle
   on the running task without changing the wire (private attrs are excluded from `model_dump`).
2. Pop the flag in `ask_stream` — *why*: an explicit, documented consumer; it must never reach a client call.
3. Replace TASK-4800's awaited attach with the branch — *why*: deferred callers get the envelope immediately.
4. Tests; run Validation Commands (TASK-4800's wiring test must stay green — it counts `_attach_suggestions(` once
   per method; keep exactly one textual call in `ask_stream` by building the coroutine once, see block).

### `packages/ai-parrot/src/parrot/models/responses.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator' responses.py)
# REPLACE that import line (responses.py:7) with:
from pydantic import BaseModel, Field, ConfigDict, PrivateAttr, field_validator, model_validator

# FILL IN: insert inside `class AIMessage(BaseModel)`, directly below the `suggestions` field added by TASK-4794
#          (locate it with grep -n 'suggestions:' responses.py; quote 2 lines of context in your commit message):
    # FEAT-752 rev 0.3: running chip task for the stream trailer (set by ask_stream(defer_suggestions=True)).
    # Private — never serialised, never part of the wire.
    _suggestions_task: Any = PrivateAttr(default=None)
```
**Why**: `Any` is already imported in `responses.py` (verify; if not, add it to the existing `typing` import).

### `packages/ai-parrot/src/parrot/bots/base.py` (MODIFY — flag)
```python
# occurrences: 3 for the bare `_trusted_source = kwargs.pop(...)` line — disambiguate by context: the one preceded by
#   `            # Maintain turn identifier generation for parity with ask()` / `            _turn_id = str(uuid.uuid4())`
#   (base.py:1938-1940; the comment occurs once).
# AFTER — insert below that `_trusted_source` line (base.py:1940)
            # FEAT-752 rev 0.3: stream trailer — compute chips after the final envelope (handler opt-in).
            _defer_suggestions = bool(kwargs.pop("defer_suggestions", False))
```

### `packages/ai-parrot/src/parrot/bots/base.py` (MODIFY — attach site)
```python
# occurrences: 1 (verified after TASK-4800: grep -c '                    ai_message = await self._attach_suggestions(' base.py)
# REPLACE the TASK-4800 block (comment + 3-line awaited call) right above `                    yield ai_message` with:
                    # FEAT-752: chips travel only in the final AIMessage (final stream envelope), never in text
                    # chunks. With defer_suggestions the handler sends them later as a trailer frame (rev 0.3).
                    _attach = self._attach_suggestions(
                        question, ai_message, output_mode=output_mode, user_id=user_id, session_id=session_id
                    )
                    if _defer_suggestions:
                        # create_task copies the current context: turn skill + tenant ContextVars stay bound.
                        ai_message._suggestions_task = asyncio.create_task(_attach)
                    else:
                        ai_message = await _attach
```
**Why**: one textual `_attach_suggestions(` call keeps TASK-4800's source-level test valid; the coroutine is created
once and either awaited or scheduled — never both.

### FILL IN checklist
- [ ] Private attr placement below `suggestions`.
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] `ask_stream(..., defer_suggestions=True)` yields the final `AIMessage` without awaiting the chips; its
      `_suggestions_task` resolves to the same message with `suggestions` filled.
- [ ] Without the flag, behaviour is TASK-4800's (chips on the yielded message, `_suggestions_task is None`).
- [ ] `defer_suggestions` never reaches `llm_kwargs`; `AIMessage.model_dump()` has no `_suggestions_task` key.
- [ ] `test_suggestion_bot_wiring.py` stays green; `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_suggestion_stream_deferred.py -q`
- `pytest packages/ai-parrot/tests/bots/test_linked_surface_lifting.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_suggestion_stream_deferred.py
import inspect
import pytest
from parrot.models import AIMessage
from parrot.models.basic import CompletionUsage


def _base_bot_cls():
    try:
        from parrot.bots.base import BaseBot
    except Exception as exc:  # noqa: BLE001 — same guard as test_linked_surface_lifting.py
        pytest.skip(f"cannot import parrot.bots.base: {exc}")
    return BaseBot


def test_private_task_attr_not_serialised():
    msg = AIMessage(input="q", output="a", model="m", provider="p", usage=CompletionUsage())
    assert msg._suggestions_task is None
    assert "_suggestions_task" not in msg.model_dump()


def test_ask_stream_source_has_deferred_branch():
    src = inspect.getsource(_base_bot_cls().ask_stream)
    assert 'kwargs.pop("defer_suggestions", False)' in src
    assert src.count("_attach_suggestions(") == 1
    assert "asyncio.create_task(_attach)" in src
    assert src.index("asyncio.create_task(_attach)") < src.index("yield ai_message")


async def test_deferred_task_keeps_turn_skill_context():
    # FILL IN: set a turn skill via parrot.skills.tenancy (set_active_skill inside enter/exit scope), create a task
    #          from a coroutine that reads current_turn_skill(), exit the scope, then await the task and assert it
    #          saw the skill — documents why create_task is safe after the generator's finally (spec Module 8).
    ...
```

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions (worktree via `ensure_worktree --slug followup-suggestion-chips
--feature-id FEAT-752`, `PYTHONPATH=packages/ai-parrot/src`, commit only listed files,
`scripts/sdd/close_task.sh TASK-4806 followup-suggestion-chips verified`).

---

## Completion Note

*(Agent fills this in when done)*
