# TASK-3406: `CommandContext` protocol for slash commands + `/resume`

**Feature**: FEAT-573 — Agent Terminal Workspace for `parrot agent`
**Spec**: `sdd/specs/new-ui-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3401, TASK-3404
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. Every slash-command handler today takes the concrete
`AgentREPL` (`commands.py:95`, `:173-319`) and reaches into `repl.config`,
`repl.history`, `repl.renderer` and `repl.bot`. The Textual workspace cannot
hand a Textual app to those handlers unchanged, and `/create_agent` builds a
`CLIHumanChannel` from the renderer's console (`commands.py:373`), which needs
the screen released first.

This task types the handler contract as a `Protocol` both hosts implement —
`AgentREPL` (TASK-3407) and `TUICommandContext` (TASK-3411) — routes session
mutation through `TurnRunner` (TASK-3404), and adds `/resume` (spec G5). Codex
suggestion S5 (CONFIRM partial): the `/quit` → `SystemExit(0)` contract is
deliberately **kept** (hosts catch it) so agentd's handlers and the FEAT-168
tests keep working.

---

## Scope

- Add `RendererProtocol` and `CommandContext` (`typing.Protocol`) per the spec
  §3 Module 7 skeleton; drop the `TYPE_CHECKING` import of `AgentREPL`.
- Rename the handler/dispatcher parameter `repl` → `ctx` everywhere in
  `commands.py` (9 occurrences of `repl: "AgentREPL"`) and type it
  `"CommandContext"`.
- `/clear` → `ctx.runner.reset_session()`; print the same message shape.
- Add `/resume <session_id|last>`: `last` resolves through
  `load_session_pointer(ctx.config.agent_name)` (TASK-3401); when
  `ctx.runner.capabilities.resume` is False print an explicit error; otherwise
  `turns = await ctx.runner.load_history(id)` then
  `ctx.renderer.render_history(turns, session_id=id)`.
- Wrap the body of `_cmd_create_agent` in `with ctx.suspend():`.
- Keep `/quit` raising `SystemExit(0)`, `/export` JSON keys, `/stream`, `/tools`,
  `/info`, `/help` behaviour.
- Tests in `packages/ai-parrot/tests/cli/test_commands_context.py` using a
  minimal stub context (no `AgentREPL`).

**NOT in scope**: `AgentREPL` implementing the protocol (TASK-3407), the TUI
adapter (TASK-3411), agentd handler retyping (TASK-3415), `session.py`
(TASK-3404), `modes.py` (TASK-3401).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/commands.py` | MODIFY | protocols, `ctx` rename, `/clear` via runner, `/resume`, `suspend()` around `/create_agent` |
| `packages/ai-parrot/tests/cli/test_commands_context.py` | CREATE | stub-context tests for dispatch, `/clear`, `/resume`, `/export` contract |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio, json, logging                                        # verified: commands.py:10-12
from dataclasses import dataclass, field                             # verified: commands.py:13
from datetime import datetime                                        # verified: commands.py:14
from pathlib import Path                                             # verified: commands.py:15
from typing import TYPE_CHECKING, Any, Callable, Dict, List          # verified: commands.py:16  (extend with Awaitable, ContextManager, Optional, Protocol)
from uuid import uuid4                                               # verified: commands.py:17
from parrot.cli.modes import load_session_pointer                    # provided by TASK-3401 (cli/modes.py)
# TYPE_CHECKING only:
from parrot.cli.repl import REPLConfig                               # verified: repl.py:61
from parrot.cli.session import TurnRunner                            # provided by TASK-3404 (cli/session.py)
# tests only:
from parrot.cli.commands import SlashCommandDispatcher, ConversationTurn   # verified: commands.py:70, :38
from parrot.cli.events import BackendCapabilities                   # provided by TASK-3403
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/commands.py  (408 lines)
if TYPE_CHECKING:                                    # line 19  (occurrences: 1)
    from parrot.cli.repl import AgentREPL            # line 20  (occurrences: 1 — TO BE REPLACED)
@dataclass class SlashCommand: name: str; description: str; handler: Callable   # lines 23-34
@dataclass class ConversationTurn: query: str; response: Any; timestamp: datetime; def to_dict()   # lines 38-67
class SlashCommandDispatcher:                        # line 70
    async def dispatch_async(self, input_text: str, repl: "AgentREPL") -> bool   # line 95 (uses repl.renderer.print :117, repl.renderer.render_error :127)
    def get_completions(self) -> List[str]           # line 130
    def _register_builtins(self) -> None             # line 142; SlashCommand("clear", ...) at line 147; SlashCommand("help", ...) line 161
async def _cmd_tools(repl, args)     # line 173 — repl.bot.get_available_tools()/get_tools_count(); repl.renderer.render_table
async def _cmd_info(repl, args)      # line 193 — repl.bot, repl.config.{agent_name,session_id,user_id,streaming,server_url}; repl.renderer.render_info
async def _cmd_clear(repl, args)     # line 221 — repl.config.session_id = str(uuid4()) :229; repl.history.clear() :230; message :231-235
async def _cmd_export(repl, args)    # line 238 — repl.history, repl.config; payload keys session_id/agent_name/user_id/exported_at/turns :258-264
async def _cmd_stream(repl, args)    # line 279 — repl.config.streaming toggle
async def _cmd_help(repl, args)      # line 291 — repl.dispatcher._commands
async def _cmd_quit(repl, args)      # line 308 — raise SystemExit(0) :319  (KEEP)
def _parse_create_agent_args(args)   # line 322
async def _cmd_create_agent(repl, args)   # line 347 — body starts `parsed = _parse_create_agent_args(args)` :354; CLIHumanChannel(console=getattr(repl.renderer, "console", None)) :373
# `repl: "AgentREPL"` occurs 9 times (dispatch_async + 8 handlers); `repl.renderer` 21 times; `repl.history` 3 times.

# TASK-3404 TurnRunner: history: list[ConversationTurn]; capabilities: BackendCapabilities (.resume bool);
#   async load_history(session_id) -> list[ConversationTurn]; reset_session() -> str
# TASK-3401: load_session_pointer(agent_name) -> Optional[SessionPointer]  (.last_session_id)
# TASK-3405 renderer: render_history(turns, *, session_id: str)

# tests/cli/test_integration.py::TestSlashCommandsAsync (lines 360-440) calls dispatch_async(text, repl) POSITIONALLY with an AgentREPL —
# TASK-3407 makes AgentREPL satisfy CommandContext; this task must not break positional calls.
```

### Does NOT Exist
- ~~`CommandContext`, `RendererProtocol`~~ — created by THIS task.
- ~~`ctx.runner` on today's `AgentREPL`~~ — added by TASK-3407; tests here use a stub.
- ~~`ResponseRenderer.render_history`~~ — added by TASK-3405; the stub renderer in tests records the call.
- ~~`ConversationMemory.list_sessions()`~~ — `last` comes from the pointer file, never from memory enumeration.
- ~~changing `/quit` to return a value~~ — REJECTED (spec §9 S5); it raises `SystemExit(0)`.
- ~~`repl.renderer.console` guaranteed~~ — `_cmd_create_agent` already uses `getattr(..., "console", None)`; keep that (the TUI renderer has no console).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/cli/commands.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/cli/test_commands_context.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#SlashCommand",
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#ConversationTurn",
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#SlashCommandDispatcher",
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#SlashCommandDispatcher.dispatch_async",
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#_cmd_clear",
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#_cmd_export",
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#_cmd_quit",
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#_cmd_create_agent"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Handler signature stays `(ctx, args)`; the dispatcher still passes the context positionally (`cmd.handler(ctx, args)`, commands.py:123).
- Protocols are structural: do not make `AgentREPL` inherit anything; do not import `AgentREPL` at runtime (circular import — `repl.py:22` imports this module).
- `/export` payload keys and the path-traversal guard (`commands.py:249-256`) are unchanged (AC20).
- `/clear` must still print "Session cleared." with the new and old ids (test_integration.py:380-394 asserts history is emptied).
- Inside a worktree run tests with `PYTHONPATH=packages/ai-parrot/src pytest …`; never `uv sync` there.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/agentd/proxy.py:258-390` — external handlers that only use `renderer.print/render_table/render_info` and `config` (must keep working via the protocol).
- `packages/ai-parrot/tests/cli/test_integration.py:360-490` — existing dispatcher tests.

---

## Implementation Blueprint

### Steps (in order)
1. Replace the `TYPE_CHECKING` block and extend the `typing` import — *why*: the runtime type of the first handler argument becomes the protocol, not `AgentREPL`.
2. Insert `RendererProtocol` and `CommandContext` before `SlashCommand` — *why*: `SlashCommand.handler`'s comment and `dispatch_async`'s annotation reference them.
3. Rename all 9 `repl: "AgentREPL"` parameters to `ctx: "CommandContext"` and every `repl.` use to `ctx.` — *why*: one mechanical sweep; the body semantics do not change.
4. Rewrite `_cmd_clear` to use `ctx.runner.reset_session()` — *why*: session identity is owned by the runner (spec M5), so both presenters observe the same reset.
5. Add `_cmd_resume` and register it after `"clear"` — *why*: spec G5/AC9.
6. Wrap `_cmd_create_agent`'s body in `with ctx.suspend():` — *why*: HITL prompts need the screen (spec §7 "One writer at a time").
7. Write tests — *why*: spec §4 rows `test_dispatcher_uses_command_context`, `test_cmd_resume_last_and_missing_capability`, `test_cmd_export_contract_unchanged`.

### `packages/ai-parrot/src/parrot/cli/commands.py` (MODIFY — imports + protocols)
```python
# occurrences: 1 (verified: grep -c 'from typing import TYPE_CHECKING, Any, Callable, Dict, List' packages/ai-parrot/src/parrot/cli/commands.py)
# REPLACE — line 16
from typing import TYPE_CHECKING, Any, Awaitable, Callable, ContextManager, Dict, List, Optional, Protocol

# occurrences: 1 (verified: grep -c 'from parrot.cli.repl import AgentREPL' packages/ai-parrot/src/parrot/cli/commands.py)
# REPLACE — lines 19-20 (`if TYPE_CHECKING:` / `    from parrot.cli.repl import AgentREPL`)
from parrot.cli.modes import load_session_pointer            # provided by TASK-3401

if TYPE_CHECKING:
    from parrot.cli.repl import REPLConfig                   # verified: repl.py:61
    from parrot.cli.session import TurnRunner                # provided by TASK-3404


class RendererProtocol(Protocol):
    """What a slash-command handler may call on ``ctx.renderer`` (inline ResponseRenderer or the TUI adapter)."""

    def print(self, *args: Any, **kwargs: Any) -> None: ...
    def render(self, response: Any) -> None: ...
    def render_error(self, error: Exception) -> None: ...
    def render_table(self, headers: List[str], rows: List[List[str]], title: Optional[str] = None) -> None: ...
    def render_info(self, lines: List[tuple[str, str]]) -> None: ...
    def render_history(self, turns: List["ConversationTurn"], *, session_id: str) -> None: ...


class CommandContext(Protocol):
    """Host surface a handler may touch. Implemented by ``AgentREPL`` (inline) and ``TUICommandContext`` (tui/adapter.py)."""

    bot: Any
    config: "REPLConfig"
    renderer: RendererProtocol
    dispatcher: "SlashCommandDispatcher"
    runner: "TurnRunner"

    @property
    def history(self) -> List["ConversationTurn"]: ...

    def suspend(self) -> ContextManager[None]:
        """Yield the terminal to a foreign prompt (HITL, device code): inline → ``LiveRegion.modal()``; TUI → ``App.suspend()``."""
        ...
```
**Why**: structural typing lets `AgentREPL` and the TUI adapter satisfy the contract without a shared base class; importing `REPLConfig`/`TurnRunner` only under `TYPE_CHECKING` avoids the `repl.py:22` ↔ `commands.py` cycle.

### `packages/ai-parrot/src/parrot/cli/commands.py` (MODIFY — dispatcher, `/clear`, `/resume`, `/create_agent`)
```python
# occurrences: 9 (verified: grep -c 'repl: "AgentREPL"' packages/ai-parrot/src/parrot/cli/commands.py)
# REPLACE ALL — every `repl: "AgentREPL"` → `ctx: "CommandContext"`, then every `repl.` → `ctx.` inside commands.py
#   (`repl.renderer` ×21, `repl.history` ×3, plus repl.bot/repl.config/repl.dispatcher). No other file is touched.

# occurrences: 1 (verified: grep -c 'SlashCommand("clear", "Reset conversation session (new session_id).", _cmd_clear),' packages/ai-parrot/src/parrot/cli/commands.py)
# AFTER — insert below that line (verified: commands.py:147)
            SlashCommand("resume", "Resume a prior conversation. Usage: /resume <session_id|last>", _cmd_resume),

# occurrences: 1 (verified: grep -c 'repl.config.session_id = str(uuid4())' packages/ai-parrot/src/parrot/cli/commands.py)
# REPLACE — lines 228-230 inside _cmd_clear (`old_id = ...` / `... = str(uuid4())` / `repl.history.clear()`)
    old_id = ctx.config.session_id
    new_id = ctx.runner.reset_session()          # owns session identity + history (TASK-3404)
    # keep the existing "Session cleared." print below, using new_id / old_id

# occurrences: 1 (verified: grep -c 'async def _cmd_create_agent(repl: "AgentREPL", args: str) -> None:' packages/ai-parrot/src/parrot/cli/commands.py)
# AFTER — insert a new handler ABOVE `def _parse_create_agent_args(args: str)` (verified: commands.py:322)
async def _cmd_resume(ctx: "CommandContext", args: str) -> None:
    """Handle ``/resume <session_id|last>`` — re-render a prior session from bot-owned memory (spec G5/AC9).

    Args:
        ctx: The command context.
        args: Session id, or ``last`` to use the per-agent pointer written after each completed turn.
    """
    target = args.strip()
    if not target:
        ctx.renderer.print("[yellow]Usage:[/yellow] /resume <session_id|last>")
        return
    if not ctx.runner.capabilities.resume:
        ctx.renderer.print("[red]This backend cannot resume conversations (no history read path).[/red]")
        return
    if target == "last":
        pointer = load_session_pointer(ctx.config.agent_name)
        if pointer is None:
            ctx.renderer.print("[yellow]No previous session recorded for this agent.[/yellow]")
            return
        target = pointer.last_session_id
    turns = await ctx.runner.load_history(target)
    # FILL IN: empty result → yellow "No stored turns for session <id>"; else ctx.renderer.render_history(turns, session_id=target)
    #   — bounded by AC9

# occurrences: 1 (verified: grep -c 'parsed = _parse_create_agent_args(args)' packages/ai-parrot/src/parrot/cli/commands.py)
# WRAP — indent the whole body of _cmd_create_agent (from `parsed = _parse_create_agent_args(args)` :354 to the end of the
#   function :408) one level under:
    with ctx.suspend():
        parsed = _parse_create_agent_args(args)
        # ... existing body unchanged, including CLIHumanChannel(console=getattr(ctx.renderer, "console", None))
```
**Why**: `/clear` keeps its user-visible message but no longer mutates config/history directly, so the TUI transcript reset and the REPL share one implementation. `/resume` is host-agnostic: it only uses protocol members. `suspend()` is a no-op-ish `LiveRegion.modal()` inline and `App.suspend()` in the TUI, which is exactly what the HITL `CLIHumanChannel` prompts need.

### `packages/ai-parrot/tests/cli/test_commands_context.py` (CREATE)
```python
"""CommandContext-based dispatcher tests (FEAT-573 TASK-3406, spec §4) — no AgentREPL involved."""
from __future__ import annotations

import contextlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.cli.commands import ConversationTurn, SlashCommandDispatcher   # verified: commands.py:38, :70
from parrot.cli.events import BackendCapabilities                          # provided by TASK-3403


class _StubCtx:
    """Minimal CommandContext (structural) for tests."""

    def __init__(self, *, resume: bool = True) -> None:
        self.bot = MagicMock(get_available_tools=MagicMock(return_value=["T"]), get_tools_count=MagicMock(return_value=1))
        self.config = SimpleNamespace(agent_name="a", session_id="s-1", user_id="u", streaming=True, server_url=None)
        self.renderer = MagicMock()
        self.dispatcher = SlashCommandDispatcher()
        self.runner = MagicMock()
        self.runner.history = []
        self.runner.capabilities = BackendCapabilities(resume=resume)
        self.runner.reset_session = MagicMock(side_effect=self._reset)
        self.runner.load_history = AsyncMock(return_value=[ConversationTurn(query="q", response=SimpleNamespace(output="o"))])
        self.suspended = 0

    def _reset(self) -> str:
        self.config.session_id = "s-2"
        self.runner.history.clear()
        return "s-2"

    @property
    def history(self):
        return self.runner.history

    @contextlib.contextmanager
    def suspend(self):
        self.suspended += 1
        yield


@pytest.mark.asyncio
async def test_dispatcher_uses_command_context():
    ctx = _StubCtx()
    for text in ("/tools", "/info", "/help"):
        assert await ctx.dispatcher.dispatch_async(text, ctx) is True
    assert await ctx.dispatcher.dispatch_async("/clear", ctx) is True
    ctx.runner.reset_session.assert_called_once()
    assert ctx.config.session_id == "s-2"


@pytest.mark.asyncio
async def test_cmd_resume_last_and_missing_capability(monkeypatch, tmp_path):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    # FILL IN: (a) resume=False → renderer.print called with a message containing "cannot resume", load_history not awaited;
    # (b) write a pointer via parrot.cli.modes.save_session_pointer("a", "s-9") then "/resume last" →
    #     runner.load_history awaited with "s-9" and renderer.render_history called with session_id="s-9" — AC9


@pytest.mark.asyncio
async def test_cmd_export_contract_unchanged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx = _StubCtx()
    ctx.runner.history.append(ConversationTurn(query="hi", response=SimpleNamespace(output="yo", response="yo")))
    assert await ctx.dispatcher.dispatch_async("/export out.json", ctx) is True
    data = json.loads((tmp_path / "out.json").read_text())
    assert set(data) == {"session_id", "agent_name", "user_id", "exported_at", "turns"}


@pytest.mark.asyncio
async def test_quit_raises_system_exit():
    ctx = _StubCtx()
    with pytest.raises(SystemExit):
        await ctx.dispatcher.dispatch_async("/quit", ctx)
    # FILL IN: also assert "/exit" alias raises SystemExit — AC20


@pytest.mark.asyncio
async def test_create_agent_usage_runs_inside_suspend():
    ctx = _StubCtx()
    await ctx.dispatcher.dispatch_async("/create_agent", ctx)   # no description → usage message, no factory import
    assert ctx.suspended == 1
```
**Why**: the stub proves handlers need nothing beyond the protocol (spec AC20, S5); the `/export` key-set assertion is the literal data contract; the usage-path `/create_agent` test exercises `suspend()` without importing the factory.

### FILL IN checklist
- [ ] `commands.py::_cmd_resume` — empty-history message and `render_history` call; bounded by AC9.
- [ ] `commands.py` — the mechanical `repl`→`ctx` sweep must leave zero `repl.` references (`grep -c 'repl\.' commands.py` → 0).
- [ ] `test_commands_context.py::test_cmd_resume_last_and_missing_capability` — both branches; bounded by AC9.
- [ ] `test_commands_context.py::test_quit_raises_system_exit` — `/exit` alias.

---

## Acceptance Criteria

- [ ] `from parrot.cli.commands import CommandContext, RendererProtocol` works; no runtime import of `parrot.cli.repl` in `commands.py`.
- [ ] `grep -c 'AgentREPL' packages/ai-parrot/src/parrot/cli/commands.py` → 0.
- [ ] `/clear` issues a new session id through the runner; `/export` keys unchanged; `/quit` and `/exit` raise `SystemExit(0)` (spec AC20).
- [ ] `/resume last` resolves the pointer; `resume=False` backends get an explicit error (spec AC9).
- [ ] `/create_agent` body runs inside `ctx.suspend()`.
- [ ] `ruff check packages/ai-parrot/src/parrot/cli/commands.py` clean; tests pass.

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/test_commands_context.py -q`

---

## Test Specification

See the CREATE block above; required names: `test_dispatcher_uses_command_context`,
`test_cmd_resume_last_and_missing_capability`, `test_cmd_export_contract_unchanged`,
`test_quit_raises_system_exit`, `test_create_agent_usage_runs_inside_suspend`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3406-command-context-and-resume.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
