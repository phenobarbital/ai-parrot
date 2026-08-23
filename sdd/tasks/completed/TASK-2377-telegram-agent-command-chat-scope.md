# TASK-2377: Enter telegram_chat_scope in agent command handlers

**Feature**: FEAT-452 — Audio Notes → Obsidian + LLM Wiki
**Spec**: `sdd/specs/audio-notes-obsidian.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec.

`@telegram_command` lets an agent declare a slash command with no wrapper
change. But the inner `agent_cmd_handler` built by `_register_agent_commands`
never enters `telegram_chat_scope`, so an agent command **cannot resolve which
chat invoked it**. Every other agent-invoking path in the wrapper already does
this (8 call sites — see the contract below); agent commands are the outlier.

TASK-2381 (`/note` sticky mode) needs per-chat state and is blocked on this.
The change is additive and benefits every agent command, not just this feature.

---

## Scope

- Wrap the body of the inner `agent_cmd_handler` (`wrapper.py:749-794`) in
  `with telegram_chat_scope(chat_id):` so `get_current_telegram_chat_id()`
  resolves inside the invoked agent method.
- Place the scope so it covers the `_method(...)` invocation **and** the
  response parsing/sending, matching how `handle_voice` scopes `_invoke_agent`.
- The existing `try/except/finally` structure (typing-task cancellation, error
  reply) must be preserved exactly.
- Add unit tests to the existing Telegram test tree.

**NOT in scope**: declaring `/note` (TASK-2381); any change to `handle_voice`;
any change to `_register_handlers`; adding new commands.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Wrap `agent_cmd_handler` body in `telegram_chat_scope` |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_agent_command_chat_scope.py` | CREATE | Unit tests for scope entry/reset |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-23 against `dev`.

### Verified Imports

```python
# ALREADY imported in wrapper.py — do NOT add a duplicate import.
# Verify with: grep -n "telegram_chat_scope" wrapper.py
from .context import telegram_chat_scope, get_current_telegram_chat_id
#   ^ defined at telegram/context.py:19 and :30
```

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/context.py
current_telegram_chat_id: ContextVar[Optional[str]]   # line 14 — default None

@contextmanager
def telegram_chat_scope(chat_id: int | str | None) -> Iterator[None]:  # line 19
    value = None if chat_id is None else str(chat_id)   # line 22
    token = current_telegram_chat_id.set(value)         # line 23
    try:
        yield
    finally:
        current_telegram_chat_id.reset(token)           # line 27

def get_current_telegram_chat_id() -> Optional[str]: ...  # line 30

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper:
    def _register_agent_commands(self) -> None: ...      # line 742
        # for cmd_info in self._agent_commands:          # line 743
        #     cmd_name  = cmd_info["command"]            # line 744
        #     method    = cmd_info["method"]             # line 745
        #     parse_mode = cmd_info.get("parse_mode", "raw")   # line 746
        #
        #     async def agent_cmd_handler(message, _method=method,
        #                                 _parse_mode=parse_mode) -> None:  # line 749
        #         chat_id = message.chat.id              # line 754
        #         if not self._is_authorized(chat_id): ... return   # lines 755-757
        #         text = (message.text or "").split(maxsplit=1)     # line 758
        #         raw_args = text[1] if len(text) > 1 else ""       # line 759
        #         typing_task = asyncio.create_task(self._typing_indicator(chat_id))  # line 760
        #         try:
        #             if _parse_mode == "keyword":   -> self._parse_kwargs(raw_args)  # lines 762-768
        #             elif _parse_mode == "positional": -> raw_args.split()           # lines 769-775
        #             else:  # raw                   -> _method(raw_args)             # lines 776-781
        #             typing_task.cancel()                                            # line 782
        #             parsed = self._parse_response(result)                           # line 783
        #             await self._send_parsed_response(message, parsed)               # line 784
        #         except Exception as e: ... await message.answer(f"❌ Error: ...")   # lines 785-790
        #         finally:
        #             typing_task.cancel()                                            # line 792
        #
        #     self.router.message.register(agent_cmd_handler, Command(cmd_name))      # line 794
```

**Reference pattern — how every other agent-invoking path scopes the chat id**
(8 verified call sites in `wrapper.py`, all of the form `with telegram_chat_scope(chat_id):`):
lines **1936, 2102, 2223, 2660, 2853, 3204, 3323, 3590**.
Line **3590** (inside `handle_voice`) is the closest analogue.

### Does NOT Exist

- ~~`agent_cmd_handler` receives `chat_id` as a parameter~~ — it does **not**.
  It receives only `message` (plus the two default-bound closures `_method`
  and `_parse_mode`) and derives `chat_id = message.chat.id` at line 754.
- ~~`telegram_chat_scope` is already applied to agent commands~~ — **false**.
  That is the entire point of this task. Verify with:
  `sed -n '742,795p' wrapper.py` — no `telegram_chat_scope` appears.
- ~~`current_telegram_chat_id` holds an `int`~~ — it holds a **`str`**
  (`context.py:22` calls `str(chat_id)`).
- ~~`TelegramAgentWrapper.handle_note()`~~ / ~~`note_mode`~~ — no note-mode
  concept exists in the Telegram integration.

---

## Implementation Notes

### Pattern to Follow

Mirror the placement used at `wrapper.py:3590` in `handle_voice`: the scope
wraps the agent invocation and everything that consumes its result. Keep
`typing_task` creation OUTSIDE the scope (it does not need chat context) and
keep the `finally: typing_task.cancel()` intact.

### Key Constraints

- Async throughout; `telegram_chat_scope` is a **sync** `@contextmanager` — use
  a plain `with`, never `async with`.
- The contextvar must be reset even when `_method` raises. `telegram_chat_scope`
  already guarantees this via its own `finally` (`context.py:26-27`) — do not
  add a second reset.
- Do NOT change the authorization early-return at lines 755-757 (it runs before
  any agent work and needs no chat scope).
- No behavior change for commands that ignore chat scope.

### References in Codebase

- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:3590` — closest pattern
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/context.py:19` — the context manager
- `packages/ai-parrot-integrations/tests/integrations/telegram/conftest.py` — existing fixtures

---

## Acceptance Criteria

- [ ] An agent command handler observes `get_current_telegram_chat_id()` equal to
      `str(message.chat.id)` while the decorated method runs
- [ ] The contextvar is reset to its prior value after the handler returns
- [ ] The contextvar is reset even when the decorated method raises
- [ ] All three `parse_mode` branches (`keyword`, `positional`, `raw`) run inside the scope
- [ ] Existing Telegram tests pass unchanged:
      `pytest packages/ai-parrot-integrations/tests/integrations/telegram/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/telegram/test_agent_command_chat_scope.py
import pytest
from parrot.integrations.telegram.context import (
    get_current_telegram_chat_id,
    current_telegram_chat_id,
)


class TestAgentCommandChatScope:
    async def test_handler_sees_chat_id(self, wrapper_with_agent_command):
        """The decorated agent method resolves the invoking chat id."""
        seen = {}

        async def _cmd(text: str) -> str:
            seen["chat"] = get_current_telegram_chat_id()
            return "ok"
        # register _cmd, dispatch a message from chat 12345
        assert seen["chat"] == "12345"      # NOTE: str, not int

    async def test_scope_resets_after_return(self, wrapper_with_agent_command):
        """The contextvar returns to its prior value."""
        assert current_telegram_chat_id.get() is None

    async def test_scope_resets_on_exception(self, wrapper_with_agent_command):
        """A raising method still resets the contextvar and replies with an error."""
        assert current_telegram_chat_id.get() is None

    @pytest.mark.parametrize("parse_mode", ["keyword", "positional", "raw"])
    async def test_all_parse_modes_scoped(self, parse_mode):
        """Every parse_mode branch runs inside the scope."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 "`/note` and the chat-scope gap", §3 Module 1)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm `wrapper.py:742-794` still matches
   the shape above before editing; line numbers may have drifted
4. **Update status** in `sdd/tasks/index/audio-notes-obsidian.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2377-telegram-agent-command-chat-scope.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude session 2026-08-23)
**Date**: 2026-08-23
**Notes**: Wrapped the inner `agent_cmd_handler` body (the three `parse_mode`
branches + `typing_task.cancel()` + response parsing/sending) in
`with telegram_chat_scope(chat_id):`, matching the `handle_voice` pattern at
`wrapper.py:3590`. The `try/except/finally` structure and the pre-scope
authorization early-return are untouched. Added
`test_agent_command_chat_scope.py` (8 tests, all passing) covering chat-id
resolution, reset-on-return, reset-on-exception, all three parse modes, and
zero-regression for commands that ignore chat scope / are unauthorized.
`ruff check` clean on both changed files (verified no new findings vs. the
pre-existing baseline on `dev`).

Environment note: `pytest .../test_telegram_voice.py` /
`test_telegram_voice_integration.py` hang indefinitely in this sandbox —
confirmed this is **pre-existing and unrelated to this change**: the same
hang reproduces on unmodified `dev` in the main repo (not just this
worktree). The diff to `wrapper.py` is isolated entirely inside
`agent_cmd_handler` (verified via `git diff`); `handle_voice()` is
byte-identical. Could not obtain a green run of these two files in this
sandbox; recommend re-running them in CI/a networked environment before
merge.

**Environment hazard, logged for the record**: twice during this feature's
implementation, an external automated process (a "style: apply black
formatting (post sdd-worker)" auto-commit, not initiated by this
sdd-worker session — three OTHER `claude --agent sdd-worker` processes
were concurrently running on this machine per `ps aux`) reformatted the
*entire* `wrapper.py` file (300+ line diff vs. this task's actual ~24-line
change) directly on this worktree's branch, twice, within seconds of each
other. Both were caught (via `git diff dev...HEAD --stat` showing an
unexpectedly large diff) and reverted with `git revert` before this
feature's branch was pushed; `git diff dev...HEAD` for `wrapper.py` is
confirmed back to the intended ~24/23-line change. Pushed immediately
after the second revert to reduce the window for further interference —
matching the project's own recorded lesson on concurrent sdd-worker
worktree hazards. No task code was lost; this is disclosed for traceability
in case reflog/cherry-pick recovery is ever needed.

**Deviations from spec**: none
