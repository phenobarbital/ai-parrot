---
type: Wiki Overview
title: 'TASK-1134: Slash Commands'
id: doc:sdd-tasks-completed-task-1134-slash-commands-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: returns `True` if input was a slash command, `False` otherwise
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.cli.commands
  rel: mentions
- concept: mod:parrot.cli.repl
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
---

# TASK-1134: Slash Commands

**Feature**: FEAT-168 — Console CLI Agents
**Spec**: `sdd/specs/console-cli-agents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1131, TASK-1132
**Assigned-to**: unassigned

---

## Context

> Implements Module 4 from the spec: the `SlashCommandDispatcher` and all
> built-in slash commands (`/tools`, `/info`, `/clear`, `/export`, `/stream`,
> `/help`, `/quit`).  Uses the `ResponseRenderer` (TASK-1132) for output.

---

## Scope

- Create `packages/ai-parrot/src/parrot/cli/commands.py`
- Implement `SlashCommandDispatcher`:
  - `register(cmd: SlashCommand)` — register a slash command
  - `dispatch(input: str, repl: AgentREPL) -> bool` — parse and execute;
    returns `True` if input was a slash command, `False` otherwise
  - `get_completions() -> List[str]` — return command names for tab completion
- Implement built-in commands (each as an async handler function):
  - `/tools` — call `bot.get_available_tools()`, render as Rich table
  - `/info` — show agent name, class name, LLM, model, session_id, tool count
  - `/clear` — reset session_id (generate new UUID), print confirmation
  - `/export [path]` — serialize conversation history to JSON file
  - `/stream` — toggle `config.streaming` flag, print new state
  - `/help` — list all registered commands with descriptions
  - `/quit` (alias `/exit`) — raise `SystemExit` (or return a sentinel)
- Define the `SlashCommand` dataclass and `ConversationTurn` dataclass

**NOT in scope**: REPL loop, agent loading, the prompt_toolkit integration

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/commands.py` | CREATE | SlashCommandDispatcher + built-in commands |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.abstract import AbstractBot       # bots/abstract.py:146
from parrot.models.responses import AIMessage      # responses.py:72
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:  # line 146
    name: str  # set in __init__ at line 237
    def get_available_tools(self) -> List[str]:  # line 3290
    def get_tools_count(self) -> int:  # line 3281
    def has_tools(self) -> bool:  # line 3286
```

### Does NOT Exist
- ~~`AbstractBot.history`~~ — no history attribute; the REPL tracks conversation turns
- ~~`AbstractBot.repl()`~~ — no REPL method
- ~~`AbstractBot.get_info()`~~ — no info method; extract attributes manually

---

## Implementation Notes

### Pattern to Follow
```python
from dataclasses import dataclass
from typing import Callable, List, Optional, TYPE_CHECKING
import json

if TYPE_CHECKING:
    from parrot.cli.repl import AgentREPL

@dataclass
class SlashCommand:
    name: str
    description: str
    handler: Callable  # async def handler(repl: AgentREPL, args: str) -> None

class SlashCommandDispatcher:
    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}
        self._register_builtins()

    def dispatch(self, input_text: str, repl: "AgentREPL") -> bool:
        if not input_text.startswith("/"):
            return False
        parts = input_text[1:].split(maxsplit=1)
        cmd_name = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        ...
```

### Key Constraints
- `/export` writes JSON using `json.dump()` with `ConversationTurn` serialization
- `/export` default path: `conversation_{session_id}.json` in current directory
- `/clear` must generate a new `uuid4()` session_id on the REPLConfig
- `/quit` and `/exit` are aliases
- Unknown commands: print help message listing available commands

---

## Acceptance Criteria

- [ ] `SlashCommandDispatcher` parses `/command [args]` format
- [ ] All 7 built-in commands implemented: `/tools`, `/info`, `/clear`, `/export`, `/stream`, `/help`, `/quit`
- [ ] `/exit` works as alias for `/quit`
- [ ] Unknown commands show help
- [ ] `/export` writes valid JSON with conversation turns
- [ ] `/clear` generates new session_id
- [ ] `/stream` toggles and reports new state
- [ ] `get_completions()` returns all command names
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/cli/commands.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/test_commands.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.cli.commands import SlashCommandDispatcher


class TestSlashCommandDispatcher:
    def test_dispatch_recognizes_slash(self):
        dispatcher = SlashCommandDispatcher()
        assert dispatcher.dispatch("/help", mock_repl) is True

    def test_dispatch_ignores_non_slash(self):
        dispatcher = SlashCommandDispatcher()
        assert dispatcher.dispatch("hello", mock_repl) is False

    def test_unknown_command(self):
        dispatcher = SlashCommandDispatcher()
        # Should not raise, should print help
        dispatcher.dispatch("/nonexistent", mock_repl)

    def test_completions_list(self):
        dispatcher = SlashCommandDispatcher()
        completions = dispatcher.get_completions()
        assert "/tools" in completions
        assert "/help" in completions

    async def test_export_writes_json(self, tmp_path):
        # Add conversation turns, then /export
        ...

    async def test_clear_new_session(self):
        # /clear should change session_id
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/console-cli-agents.spec.md` §2 (Data Models)
2. **Read `packages/ai-parrot/src/parrot/bots/abstract.py`** around lines 3281-3290
3. **Implement** the dispatcher and all built-in commands
4. **Use TYPE_CHECKING** for the `AgentREPL` forward reference to avoid circular imports

---

## Completion Note

Completed 2026-05-13. Implemented `SlashCommandDispatcher` with `register()`,
`dispatch()`, `dispatch_async()`, and `get_completions()` methods. All 7 built-in
commands implemented: `/tools`, `/info`, `/clear`, `/export`, `/stream`, `/help`,
`/quit` (with `/exit` alias). `SlashCommand` and `ConversationTurn` dataclasses
defined. `TYPE_CHECKING` guard used for `AgentREPL` forward reference. All linting passed.
