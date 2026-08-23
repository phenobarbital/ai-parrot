# TASK-2381: `/note` sticky mode and capture-intent routing

**Feature**: FEAT-452 — Audio Notes → Obsidian + LLM Wiki
**Spec**: `sdd/specs/audio-notes-obsidian.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2377, TASK-2380
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of the spec (Goal G3).

LLM intent detection decides when a message is a note rather than a question.
It is probabilistic and will occasionally get it wrong in both directions — so
`/note` is the deterministic escape hatch. It arms **exactly one** capture:
the next message in that chat is captured with no intent guessing, then the
mode clears (consume-on-next-message). A forgotten toggle can therefore never
silently swallow a later question.

Capture is **transport-neutral**: intent routing applies to typed messages as
well as voice transcripts — *voice is only the vehicle* (spec §8, resolved).

`/note` needs to know which chat invoked it, which is why TASK-2377 must land first.

---

## Scope

- Add `_note_mode: dict[str, bool]` to `FirefliesWikiAgent.__init__`, keyed by
  chat id **as a `str`**.
- Add an `@telegram_command("note", ...)`-decorated public method that arms the
  current chat and returns a short confirmation.
- Consume-on-next-message: the next message in an armed chat routes to
  `capture_audio_note` and clears the flag — whether or not capture succeeds.
- Extend the agent's system prompt / tool guidance so the LLM calls
  `capture_audio_note` on capture intent ("note to self…", "remember that…",
  "idea:…") for both voice transcripts and typed text.
- A question without intent and without an armed mode must still be answered
  normally, creating no note.
- Add unit tests.

**NOT in scope**: the capture tool itself (TASK-2380); the wrapper chat-scope
fix (TASK-2377); a `/note off` command or a time-boxed mode (spec chose
consume-on-next-message); persisting mode across restarts.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/fireflies_wiki.py` | MODIFY | `_note_mode`, the `/note` command, intent routing/prompt guidance |
| `tests/test_fireflies_wiki_agent.py` | MODIFY | Unit tests for arming, consuming, per-chat isolation |

> ⚠️ `agents/` is **gitignored** (`.gitignore:287`). Commit with `git add -f agents/fireflies_wiki.py`.

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-23 against `dev`.

### Verified Imports

```python
from parrot.integrations.telegram.decorators import telegram_command
#   ^ verified: packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py:5
from parrot.integrations.telegram.context import get_current_telegram_chat_id
#   ^ verified: packages/ai-parrot-integrations/src/parrot/integrations/telegram/context.py:30
```

> **Import guard**: `ai-parrot-integrations` is a separate distribution from the
> core the agent otherwise depends on. Import these inside a `try/except
> ImportError` (or function-locally) so the agent still boots where the Telegram
> integration is not installed — the same defensive posture `_build_wiki_toolkit`
> uses for optional planes.

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py
def telegram_command(command: str,
                     description: str = "",
                     parse_mode: str = "keyword") -> Callable: ...   # line 5
    """Mark an agent method as a Telegram slash command.

    parse_mode:                                                       # lines 19-21
        - "keyword":    /cmd key=val key2=val2  -> method(**kwargs)
        - "positional": /cmd arg1 arg2          -> method(*args)
        - "raw":        /cmd <everything>       -> method(text)
    """
    # sets fn._telegram_command = {command, description, parse_mode}  # line 25

def discover_telegram_commands(agent: Any) -> List[Dict[str, Any]]: ...  # line 35
    # SKIPS attributes starting with "_"                              # line 49
    # -> the /note method MUST be PUBLIC (no leading underscore)

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/context.py
current_telegram_chat_id: ContextVar[Optional[str]]      # line 14 — default None
def get_current_telegram_chat_id() -> Optional[str]: ... # line 30
#   *** RETURNS A STRING (context.py:22 stores str(chat_id)), or None ***

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
#   _register_agent_commands()                            # line 742
#   inner agent_cmd_handler                               # line 749
#   registered via self.router.message.register(agent_cmd_handler, Command(cmd_name))  # line 794
#   *** TASK-2377 adds `with telegram_chat_scope(chat_id):` here.
#       WITHOUT that task, get_current_telegram_chat_id() returns None
#       inside /note and this task cannot work. ***

# agents/fireflies_wiki.py — created by earlier tasks in this feature
class FirefliesWikiAgent(FirefliesObsidianAgent):         # line 165
    notes_folder: str          # TASK-2379
    _notes_wiki: Optional[Any] # TASK-2379
    # AudioNoteCaptureToolkit.capture_audio_note(transcript, language=None)  # TASK-2380
```

### Does NOT Exist

- ~~`agent_cmd_handler` passes `chat_id` to the decorated method~~ — **it does
  not.** The method receives only the parsed args. The chat id is available
  **only** through `get_current_telegram_chat_id()`, and **only after TASK-2377**.
- ~~`get_current_telegram_chat_id()` returns an `int`~~ — it returns a **`str`**
  or `None` (`context.py:22`, `:30`). Keying `_note_mode` by `int` will
  silently never match. This is the single most likely bug in this task.
- ~~`telegram_command` registers the command at decoration time~~ — it does not;
  it only stamps `fn._telegram_command`. Registration happens at bot startup
  via `discover_telegram_commands` + `_register_agent_commands`.
- ~~a private (`_`-prefixed) method can be a `@telegram_command`~~ — **false.**
  `discover_telegram_commands` skips attributes starting with `_`
  (`decorators.py:49`). The handler must be public.
- ~~`VoiceConfig.note_mode`~~ / ~~`TelegramAgentWrapper.handle_note()`~~ /
  ~~`TelegramAgentWrapper.note_mode`~~ — no note-mode concept exists in the
  Telegram integration, and this task does **not** add one there.
- ~~`FirefliesWikiAgent._note_mode`~~ — does not exist yet; this task creates it.
- ~~a `/note off` command or a mode timeout~~ — explicitly NOT the chosen design.
  The spec selected consume-on-next-message.

---

## Implementation Notes

### Key Constraints

- **Key `_note_mode` by `str`.** `get_current_telegram_chat_id()` returns a
  string. An `int` key silently never matches.
- The `/note` handler must be **public** or `discover_telegram_commands` will
  skip it (`decorators.py:49`).
- `get_current_telegram_chat_id()` may return `None` (non-Telegram channel, or
  TASK-2377 not yet landed). Handle it gracefully — reply with a clear message
  rather than raising or arming a `None` key.
- **Clear the flag whether or not capture succeeds**, so a failing capture
  cannot leave the chat permanently armed.
- Per-chat isolation: arming chat A must not arm chat B.
- Intent routing must not regress ordinary Q&A — a question with no intent and
  no armed mode is answered normally and creates no note.

### References in Codebase

- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py:5` — the decorator
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/context.py:30` — chat-id accessor
- `agents/fireflies_wiki.py:243` — the optional-dependency `try/except` posture to imitate

---

## Acceptance Criteria

- [ ] `/note` arms the invoking chat and replies with a short confirmation
- [ ] The next message in an armed chat is captured with no intent guessing
- [ ] The mode clears after one message, **including when capture fails**
- [ ] Arming chat A does not arm chat B
- [ ] `_note_mode` is keyed by `str`
- [ ] The `/note` handler is public and is discovered by `discover_telegram_commands`
- [ ] `get_current_telegram_chat_id() is None` is handled without raising
- [ ] Capture intent in a **typed** message routes to `capture_audio_note`
- [ ] A question with no intent and no armed mode is answered normally, no note created
- [ ] The agent still boots when `parrot.integrations.telegram` is not installed
- [ ] Tests pass: `pytest tests/test_fireflies_wiki_agent.py -v`
- [ ] No linting errors: `ruff check agents/fireflies_wiki.py`
- [ ] Committed with `git add -f agents/fireflies_wiki.py`

---

## Test Specification

```python
# tests/test_fireflies_wiki_agent.py  (EXTEND the existing module)
# Reuse the existing _load_agent_module() path-import helper and skipif guard.

from parrot.integrations.telegram.context import telegram_chat_scope

class TestNoteMode:
    async def test_note_arms_current_chat(self, agent):
        """/note arms the invoking chat, keyed by STRING chat id."""
        with telegram_chat_scope(12345):
            await agent.arm_note_mode("")
        assert agent._note_mode["12345"] is True     # str key, not int

    async def test_next_message_captured_then_cleared(self, agent):
        """Consume-on-next-message: one capture, then disarmed."""
        assert agent._note_mode.get("12345") in (False, None)

    async def test_mode_cleared_even_when_capture_fails(self, agent):
        """A failing capture must not leave the chat permanently armed."""

    async def test_per_chat_isolation(self, agent):
        """Arming chat A leaves chat B unarmed."""
        assert not agent._note_mode.get("67890")

    async def test_no_chat_scope_handled(self, agent):
        """get_current_telegram_chat_id() -> None does not raise."""

    async def test_typed_intent_routes_to_capture(self, agent):
        """Capture intent in typed text calls capture_audio_note."""

    async def test_question_not_captured(self, agent):
        """No intent + not armed -> answered normally, no note."""

    def test_note_command_is_public_and_discovered(self, agent):
        """discover_telegram_commands finds /note (it skips _-prefixed attrs)."""
        cmds = discover_telegram_commands(agent)
        assert any(c["command"] == "note" for c in cmds)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 "Two triggers", §2 "`/note` and the chat-scope gap", §3 Module 4
2. **Check dependencies** — TASK-2377 **and** TASK-2380 must both be in
   `sdd/tasks/completed/`. Without TASK-2377 this task cannot work at all.
3. **Verify the Codebase Contract** — confirm TASK-2377's `telegram_chat_scope`
   wrapper is actually present in `wrapper.py:749-794` before implementing
4. **Update status** in `sdd/tasks/index/audio-notes-obsidian.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2381-note-mode-and-intent-routing.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude session 2026-08-23)
**Date**: 2026-08-23
**Notes**: Added a defensive `try/except ImportError` guard around
`telegram_command`/`get_current_telegram_chat_id` (module-level fallback
no-op decorator + `None`-returning accessor) so the agent still boots
without `ai-parrot-integrations` installed — mirrors `_build_wiki_toolkit`'s
optional-dependency posture. Added `_note_mode: Dict[str, bool]` and
`_capture_toolkit: Optional[AudioNoteCaptureToolkit]` (captured from
`configure()`) to `__init__`. `arm_note_mode` is `@telegram_command("note",
...)`-decorated, public, reads `get_current_telegram_chat_id()`, arms by
**string** chat id, and replies with a clear message (no raise, no arming a
`None` key) when the chat cannot be resolved. Overrode `ask(self, question,
*args, **kwargs)`: when the current chat is armed, clears the flag
*before* running the capture (so a failing capture never leaves the chat
stuck armed) and calls `capture_audio_note` directly via
`self._capture_toolkit` — bypassing LLM tool-selection entirely, per spec.
Otherwise forwards `*args, **kwargs` unchanged to `super().ask(...)` — no
hardcoded parameter names, so this doesn't depend on (or risk drifting
from) `BasicAgent.ask()`'s full ~20-parameter signature, and ordinary Q&A
is byte-identical to before (G7). Also folded a short capture-intent
nudge into `instructions` (`kwargs.setdefault("instructions", ...)` →
`self.goal` via `BasicAgent.__init__`, alongside the existing
`llm`-pinning `setdefault`) as the "system prompt" extension the scope
asked for — supplementary to the primary, already-verified guidance
mechanism: `capture_audio_note`'s own tool docstring (TASK-2380), which is
what actually drives LLM tool-selection.

Added `TestNoteMode` (10 tests: arm + string-key, no-chat-scope handling,
consume-on-next-message + capture, mode-cleared-on-capture-failure,
per-chat isolation, unarmed passthrough via a located-by-MRO parent `ask`
mock, no-note-on-plain-question, `discover_telegram_commands` finds
`/note`, module boots either way re: Telegram availability). Full suite:
`pytest tests/test_fireflies_wiki_agent.py -v` → 58 passed. `ruff check
agents/fireflies_wiki.py` / test file: no findings beyond the file's
pre-existing baseline categories (verified against `dev`'s copy and the
TASK-2380 commit — same categories, same lines, only shifted). Committed
with `git add -f agents/fireflies_wiki.py`.

**Deviations from spec**: (1) The scope's "extend the agent's system
prompt" is implemented via the verified `instructions` constructor kwarg
(`BasicAgent.__init__` → `self.goal`) rather than mutating
`system_prompt_template`/`PromptBuilder` internals directly — those looked
more deeply coupled to a composable-prompt subsystem
(`PromptBuilder.agent()`) not covered by this task's Codebase Contract,
and a wrong guess there risked silently breaking prompt composition for
every existing FirefliesWikiAgent behavior. `instructions` is a
documented, narrow extension point verified by direct source read
(`packages/ai-parrot/src/parrot/bots/agent.py:69-95`) precisely for this
kind of free-text agent guidance, and is additive-only (`kwargs.setdefault`
— a caller-supplied `instructions` still wins). (2) `ask()`'s exact
upstream signature (`packages/ai-parrot/src/parrot/bots/base.py:946`,
~20 parameters) is not in this task's Codebase Contract; verified it by
direct source read, then deliberately avoided replicating any of it —
`*args, **kwargs` passthrough is the safe choice precisely because this
task did not anchor that signature.
