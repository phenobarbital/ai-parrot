---
type: Wiki Overview
title: 'TASK-1136: CLI Command Wiring'
id: doc:sdd-tasks-completed-task-1136-cli-command-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: full Click command implementation
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.cli
  rel: mentions
- concept: mod:parrot.cli.agent_repl
  rel: mentions
- concept: mod:parrot.cli.loaders
  rel: mentions
- concept: mod:parrot.cli.renderer
  rel: mentions
- concept: mod:parrot.cli.repl
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
---

# TASK-1136: CLI Command Wiring

**Feature**: FEAT-168 — Console CLI Agents
**Spec**: `sdd/specs/console-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1131, TASK-1132, TASK-1133, TASK-1134, TASK-1135
**Assigned-to**: unassigned

---

## Context

> Implements Module 1 from the spec: the Click command that ties everything
> together.  Replaces the stub from TASK-1131 with the full `parrot agent`
> command — parses flags, loads the agent (standalone or server), builds
> the REPL config, and launches the REPL loop.

---

## Scope

- Replace the stub in `packages/ai-parrot/src/parrot/cli/agent_repl.py` with the
  full Click command implementation
- Click command `parrot agent` with:
  - Positional argument: `name` (optional)
  - `--list` flag → display agent table and exit
  - `--server URL` flag → use `ServerAgentProxy` instead of standalone
  - `--no-stream` flag → disable streaming
- Flow:
  1. If `--list`: list agents (standalone or server), render table, exit
  2. If no `name`: use `questionary.select()` via loader's `select_agent()`
  3. Load agent via `StandaloneAgentLoader` or `ServerAgentProxy`
  4. Print agent info banner (name, class, LLM, tool count)
  5. Build `REPLConfig` and `AgentREPL`, call `await repl.run()`
- Wrap async code with `asyncio.run()` at the Click boundary
- Handle `AgentLoadError` with Rich error panel and exit code 1
- Update `__init__.py` exports if needed

**NOT in scope**: the REPL loop itself (TASK-1135), loader logic (TASK-1133),
renderer (TASK-1132), commands (TASK-1134)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/agent_repl.py` | MODIFY | Replace stub with full Click command |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | Export key classes if needed |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.cli import cli                         # parrot/cli.py:28
from parrot.registry import agent_registry         # parrot/registry/__init__.py:7
from parrot.bots.abstract import AbstractBot       # bots/abstract.py:146
from parrot.models.outputs import OutputMode       # outputs.py:39
# NEW modules from prior tasks:
from parrot.cli.loaders import StandaloneAgentLoader, ServerAgentProxy, AgentLoadError
from parrot.cli.repl import AgentREPL, REPLConfig
from parrot.cli.renderer import ResponseRenderer
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli.py — LazyGroup pattern
# The "agent" entry was added in TASK-1131:
#   "agent": "parrot.cli.agent_repl"
# This module must export a `cli` Click command/group for LazyGroup to import.
```

### Does NOT Exist
- ~~`parrot.cli.agent`~~ — the module is `parrot.cli.agent_repl`
- ~~`AgentRegistry.list_agents()`~~ — iterate `_registered_agents` via loaders

---

## Implementation Notes

### Pattern to Follow
```python
import asyncio
import click
from rich.console import Console

console = Console()

@click.command("agent")
@click.argument("name", required=False)
@click.option("--list", "list_agents", is_flag=True, help="List registered agents")
@click.option("--server", default=None, help="Connect to running server URL")
@click.option("--no-stream", is_flag=True, help="Disable streaming output")
def cli(name, list_agents, server, no_stream):
    """Interactive REPL for AI-Parrot agents."""
    asyncio.run(_run(name, list_agents, server, no_stream))

async def _run(name, list_agents, server, no_stream):
    loader = ServerAgentProxy(server) if server else StandaloneAgentLoader()
    renderer = ResponseRenderer()

    if list_agents:
        agents = await loader.list_agents()
        # render table via renderer.render_table(...)
        return

    if name is None:
        name = await loader.select_agent()

    try:
        bot = await loader.load(name)
    except AgentLoadError as e:
        console.print(f"[red]Agent not found: {e}[/red]")
        raise SystemExit(1)

    config = REPLConfig(agent_name=name, streaming=not no_stream, server_url=server)
    repl = AgentREPL(bot, config, renderer)
    await repl.run()
```

### Key Constraints
- The Click command function MUST be named `cli` — the LazyGroup imports
  `parrot.cli.agent_repl:cli` by convention
- Use `asyncio.run()` to bridge sync Click → async REPL
- Print a welcome banner after loading: agent name, class, LLM, tool count
- Exit code 1 on load failure, 0 on normal exit

---

## Acceptance Criteria

- [ ] `parrot agent security_agent` loads and starts REPL
- [ ] `parrot agent --list` shows agent table and exits
- [ ] `parrot agent` (no name) triggers `questionary.select()` picker
- [ ] `parrot agent --server http://localhost:8080 agent_name` uses server proxy
- [ ] `parrot agent --no-stream agent_name` starts REPL in batch mode
- [ ] Agent load failure shows error with suggestions, exits with code 1
- [ ] Welcome banner printed after agent loads
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/cli/agent_repl.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/test_agent_repl.py
import pytest
from click.testing import CliRunner
from unittest.mock import AsyncMock, patch
from parrot.cli.agent_repl import cli


class TestAgentCommand:
    def test_list_flag(self):
        runner = CliRunner()
        with patch("parrot.cli.agent_repl.StandaloneAgentLoader") as mock:
            mock.return_value.list_agents = AsyncMock(return_value=[])
            result = runner.invoke(cli, ["--list"])
            assert result.exit_code == 0

    def test_unknown_agent(self):
        runner = CliRunner()
        with patch("parrot.cli.agent_repl.StandaloneAgentLoader") as mock:
            from parrot.cli.loaders import AgentLoadError
            mock.return_value.load = AsyncMock(
                side_effect=AgentLoadError("unknown")
            )
            result = runner.invoke(cli, ["unknown_agent"])
            assert result.exit_code == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/console-cli-agents.spec.md` §2 (Component Diagram)
2. **Verify all prior tasks (TASK-1131 through TASK-1135) are completed**
3. **Read their implementations** to understand exact class interfaces
4. **Replace** the stub in `agent_repl.py` with the full wiring
5. **Test** with Click's `CliRunner`

---

## Completion Note

Completed 2026-05-13. Replaced stub `agent_repl.py` with full `agent` Click command
(named `agent` to match LazyGroup's `getattr(mod, "agent")` convention). Implemented
`_run()` async function with `--list`, standalone/server loader selection, agent loading
with `AgentLoadError` handling, welcome banner, and `AgentREPL` launch. `_handle_list()`
renders agent table for both BotMetadata (standalone) and dict (server) formats.
All linting passed.
