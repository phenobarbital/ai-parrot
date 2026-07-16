---
type: Wiki Overview
title: 'TASK-1135: REPL Engine'
id: doc:sdd-tasks-completed-task-1135-repl-engine-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: user_id, `output_mode=OutputMode.TERMINAL`
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.cli.commands
  rel: mentions
- concept: mod:parrot.cli.renderer
  rel: mentions
- concept: mod:parrot.cli.repl
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
---

# TASK-1135: REPL Engine

**Feature**: FEAT-168 — Console CLI Agents
**Spec**: `sdd/specs/console-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1131, TASK-1132, TASK-1134
**Assigned-to**: unassigned

---

## Context

> Implements Module 3 from the spec: the core `AgentREPL` class.  This is the
> heart of the feature — a `prompt_toolkit`-based async REPL that reads user
> input, dispatches slash commands or agent queries, handles streaming and batch
> responses, and manages the session lifecycle.

---

## Scope

- Create `packages/ai-parrot/src/parrot/cli/repl.py`
- Implement `AgentREPL`:
  - `__init__(bot: AbstractBot, config: REPLConfig, renderer: ResponseRenderer)`
  - `async run()` — main REPL loop:
    - Create `prompt_toolkit.PromptSession` with `InMemoryHistory`
    - Custom `WordCompleter` for slash commands
    - Wrap output in `prompt_toolkit.patch_stdout.patch_stdout()`
    - Loop: `prompt_async()` → dispatch slash or query → render
  - `async send(query: str) -> AIMessage` — call `bot.ask()` with session_id,
    user_id, `output_mode=OutputMode.TERMINAL`
  - `async send_stream(query: str)` — call `bot.ask_stream()` and render
    chunks via `ResponseRenderer`
  - `register_command(cmd: SlashCommand)` — delegate to `SlashCommandDispatcher`
- Implement `REPLConfig` dataclass
- Handle:
  - `Ctrl+C` during response → cancel and return to prompt
  - `Ctrl+D` at prompt → clean exit
  - Empty input → skip
  - `EOFError` from prompt_toolkit → exit
  - `KeyboardInterrupt` during prompt → print hint, continue

**NOT in scope**: Click command wiring (TASK-1136), agent loading (TASK-1133)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/repl.py` | CREATE | AgentREPL + REPLConfig |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.abstract import AbstractBot       # bots/abstract.py:146
from parrot.models.outputs import OutputMode       # outputs.py:39
from parrot.models.responses import AIMessage      # responses.py:72
from parrot.cli.renderer import ResponseRenderer   # NEW (TASK-1132)
from parrot.cli.commands import SlashCommandDispatcher, ConversationTurn  # NEW (TASK-1134)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/base.py
class BaseBot(AbstractBot):  # line 31
    async def ask(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        output_mode: OutputMode = OutputMode.DEFAULT,
        **kwargs
    ) -> AIMessage:  # line 717

    async def ask_stream(self, ...) -> AsyncIterator:  # line 1233

# packages/ai-parrot/src/parrot/models/outputs.py
class OutputMode(str, Enum):  # line 39
    TERMINAL = "terminal"  # USE THIS
```

### Does NOT Exist
- ~~`AbstractBot.stream()`~~ — the method is `ask_stream()`, not `stream()`
- ~~`OutputMode.CONSOLE`~~ — use `TERMINAL`
- ~~`OutputMode.CLI`~~ — does not exist
- ~~`AbstractBot.history`~~ — conversation history tracked by this REPL, not the bot

---

## Implementation Notes

### Pattern to Follow
```python
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console

class AgentREPL:
    def __init__(self, bot: AbstractBot, config: REPLConfig,
                 renderer: ResponseRenderer) -> None:
        self.bot = bot
        self.config = config
        self.renderer = renderer
        self.dispatcher = SlashCommandDispatcher()
        self.history: list[ConversationTurn] = []
        self.console = Console()

    async def run(self) -> None:
        completions = self.dispatcher.get_completions()
        completer = WordCompleter(completions, sentence=True)
        session = PromptSession(
            history=InMemoryHistory(),
            completer=completer,
        )
        prompt = f"{self.bot.name}> "
        with patch_stdout():
            while True:
                try:
                    text = await session.prompt_async(prompt)
                except EOFError:
                    break  # Ctrl+D
                except KeyboardInterrupt:
                    continue
                text = text.strip()
                if not text:
                    continue
                if self.dispatcher.dispatch(text, self):
                    continue
                # Agent query
                try:
                    if self.config.streaming:
                        await self.send_stream(text)
                    else:
                        response = await self.send(text)
                        self.renderer.render(response)
                except KeyboardInterrupt:
                    self.console.print()  # newline after ^C
```

### Key Constraints
- `patch_stdout()` is REQUIRED to prevent Rich output from corrupting the
  prompt_toolkit prompt line
- `prompt_async()` is the native async method — do NOT use `prompt()` with
  `asyncio.to_thread()`
- Track conversation in `self.history: list[ConversationTurn]` for `/export`
- `session_id` must be passed to every `ask()` call for conversation continuity
- `user_id` defaults to `"cli-user"`

---

## Acceptance Criteria

- [ ] REPL loop starts and shows `<agent_name>> ` prompt
- [ ] User input sent to `bot.ask()` with `output_mode=OutputMode.TERMINAL`
- [ ] Streaming mode renders tokens incrementally
- [ ] Batch mode renders full response via `ResponseRenderer`
- [ ] Slash commands dispatched before agent query
- [ ] `Ctrl+C` during response cancels and returns to prompt
- [ ] `Ctrl+D` exits cleanly
- [ ] Empty input skipped (no API call)
- [ ] Conversation turns tracked in `self.history`
- [ ] `session_id` passed to all `ask()` calls
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/cli/repl.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/test_repl.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.cli.repl import AgentREPL, REPLConfig


class TestAgentREPL:
    def test_config_defaults(self):
        config = REPLConfig(agent_name="test")
        assert config.streaming is True
        assert config.user_id == "cli-user"

    async def test_send_calls_ask(self, mock_agent):
        config = REPLConfig(agent_name="test", streaming=False)
        renderer = MagicMock()
        repl = AgentREPL(mock_agent, config, renderer)
        response = await repl.send("hello")
        mock_agent.ask.assert_called_once()

    async def test_empty_input_skipped(self):
        # Simulate empty input — should not call ask()
        ...

    async def test_history_tracked(self, mock_agent):
        config = REPLConfig(agent_name="test", streaming=False)
        renderer = MagicMock()
        repl = AgentREPL(mock_agent, config, renderer)
        await repl.send("hello")
        assert len(repl.history) == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/console-cli-agents.spec.md` §2 (Overview, Component Diagram)
2. **Verify TASK-1132 (renderer) and TASK-1134 (commands) are completed**
3. **Read those implementations** to understand the interfaces
4. **Implement** `AgentREPL` with full REPL loop
5. **Test** with mocked bot and renderer

---

## Completion Note

Completed 2026-05-13. Implemented `AgentREPL` with full async REPL loop using
`prompt_toolkit.PromptSession.prompt_async()`, `InMemoryHistory`, slash-command
`WordCompleter`, and `patch_stdout()` context. `send()` calls `bot.ask()` with
`OutputMode.TERMINAL` and tracks history. `send_stream()` calls `bot.ask_stream()`
with streaming renderer. `REPLConfig` is a Pydantic v2 BaseModel. Handles Ctrl+C
(cancel), Ctrl+D (exit), and empty input. All linting passed.
