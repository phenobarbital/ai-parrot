# TASK-2214: DaemonAgentProxy + daemon slash commands for AgentREPL

**Feature**: FEAT-422 — Agent CLI Daemon
**Spec**: `sdd/specs/agent-cli-daemon.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2213
**Assigned-to**: unassigned

---

## Context

Spec Module 7. The Rich console is the EXISTING `AgentREPL` — this task
only supplies a third loader strategy (daemon over UDS) mirroring
`ServerAgentProxy`, plus daemon-only slash commands and queued job-event
display.

---

## Scope

- Implement `proxy.py` in `parrot/integrations/agentd/`:
  - `_DaemonBotProxy(client: AgentDaemonClient)` mirroring `_ServerBotProxy`
    duck type EXACTLY (see contract): `configure`, `ask`, `ask_stream`
    (async generator yielding text chunks from `client.stream()`),
    `get_available_tools`, `get_tools_count`, `has_tools` (backed by
    `tools.list` / `agent.info`, cached after first fetch).
  - `DaemonAgentProxy(name_or_socket)` mirroring `ServerAgentProxy`:
    `async load(name) -> _DaemonBotProxy`, `async list_agents()` (single
    entry from `agent.info`), `async close()`.
  - Event queue: proxy registers `client.subscribe_events(cb)`; events are
    appended to an internal deque; expose `drain_events() -> list[str]`
    (formatted lines like `⏱ job daily_report ejecutado ✓`).
  - Slash commands (functions taking `(repl, args)` per existing pattern):
    `/status` (daemon.status pretty table via repl renderer/console),
    `/schedules` (+ `add|pause|resume|remove` subargs), `/invoke <method>
    [json-kwargs]`. Registered onto an `AgentREPL` instance via its
    `register_command()` — provide `register_daemon_commands(repl, proxy)`.
  - Event lines are flushed between turns only (hook after send/send_stream
    completes — never mid-stream; use `drain_events()` from the REPL flow
    in TASK-2216's attach wiring, but the drain/format logic lives here).
- Tests: interface-parity checklist against `_ServerBotProxy` attributes;
  proxy behaviour against the scripted fake server from TASK-2213 fixtures;
  slash command handlers with a stubbed repl (records console output).

**NOT in scope**: `parrot attach` CLI wiring (TASK-2216), changes to
`parrot.cli.repl` / `parrot.cli.commands` in core (none are needed —
`register_command` is the extension point).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/proxy.py` | CREATE | DaemonAgentProxy, _DaemonBotProxy, slash cmds, event queue |
| `packages/ai-parrot-integrations/tests/agentd/test_proxy.py` | CREATE | Parity + behaviour tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.agentd.client import AgentDaemonClient   # TASK-2213
from parrot.cli.repl import AgentREPL, REPLConfig    # verified: packages/ai-parrot/src/parrot/cli/repl.py:58,27
from parrot.cli.commands import SlashCommand         # verified: packages/ai-parrot/src/parrot/cli/commands.py (class near top; dispatcher line 70)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/loaders.py — the duck type to MIRROR:
class _ServerBotProxy:                                  # line 129
    async def configure(self, app: Any = None) -> None  # line 162
    async def ask(self, question, session_id=None, user_id=None, output_mode=None, **kwargs) -> Any   # line 169
    async def ask_stream(self, question, session_id=None, user_id=None, output_mode=None, **kwargs)   # line 211 — async generator
    # plus: get_available_tools() -> list, get_tools_count() -> int, has_tools() -> bool
class ServerAgentProxy:                                 # line 301
    async def load(self, name: str) -> _ServerBotProxy  # line 339
    async def list_agents(self)                         # line 374
    async def close(self) -> None                       # line 421

# packages/ai-parrot/src/parrot/cli/repl.py
class AgentREPL:                                        # line 58
    def register_command(self, cmd: SlashCommand) -> None  # line 248
    async def send(self, query: str) -> AIMessage       # line 160
    async def send_stream(self, query: str) -> None     # line 188
```

### Does NOT Exist
- ~~`DaemonAgentProxy` / daemon mode in `parrot.cli.loaders`~~ — new, lives in agentd, NOT in core loaders.
- ~~modifying core `parrot.cli.commands` builtins~~ — daemon commands register at runtime via `register_command`; core files untouched.
- ~~an events API on AgentREPL~~ — no such hook exists; drain-between-turns is orchestrated by the attach command (TASK-2216) calling `drain_events()`.

---

## Implementation Notes

### Key Constraints
- Read `parrot/cli/loaders.py` and `parrot/cli/commands.py` FULLY before
  coding — mirror return shapes (`_ServerResponse`-like wrapper if the REPL
  expects `.output`/attributes; verify what `AgentREPL.send` does with the
  returned object).
- Read `SlashCommand` dataclass fields (name, handler, help?) from
  commands.py and construct instances accordingly — do not guess fields.
- `/invoke` parses optional JSON kwargs (`/invoke refresh_cache {"force": true}`);
  invalid JSON → friendly console error, no exception.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/loaders.py:129-430` — the pattern.
- `packages/ai-parrot/src/parrot/cli/commands.py` — SlashCommand construction + builtin handler style.
- `packages/ai-parrot/src/parrot/cli/renderer.py` — rendering helpers used by handlers.

---

## Acceptance Criteria

- [ ] Parity test: every public attr/method of `_ServerBotProxy` exists on `_DaemonBotProxy` with compatible signature.
- [ ] `ask_stream` yields text chunks and terminates on complete/error.
- [ ] `/status`, `/schedules`, `/invoke` handlers produce expected console output against stubbed client.
- [ ] Events are queued, formatted, and only surfaced via `drain_events()`.
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/agentd/test_proxy.py -v`; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/agentd/test_proxy.py
import pytest
from parrot.integrations.agentd.proxy import DaemonAgentProxy, _DaemonBotProxy

def test_duck_type_parity_with_server_bot_proxy(): ...

@pytest.mark.asyncio
class TestProxy:
    async def test_ask_and_stream(self, scripted_server): ...
    async def test_tools_cached(self, scripted_server): ...
    async def test_event_queue_and_drain(self, scripted_server): ...

@pytest.mark.asyncio
class TestSlashCommands:
    async def test_status_command(self): ...
    async def test_invoke_bad_json_friendly(self): ...
```

---

## Agent Instructions

1. Read the spec; 2. verify TASK-2213 completed; 3. verify contract — READ
loaders.py/commands.py before coding; 4. index → in-progress; 5. implement;
6. verify criteria; 7. move to completed/; 8. index → done; 9. Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
