# TASK-2215: MCP stdio proxy — expose the daemon to external LLMs

**Feature**: FEAT-422 — Agent CLI Daemon
**Spec**: `sdd/specs/agent-cli-daemon.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2213
**Assigned-to**: unassigned

---

## Context

Spec Module 8. An MCP client (Claude Code, another LLM) launches
`parrot mcp-serve <name>` as a stdio server; internally it is a thin proxy:
MCP tool call → `AgentDaemonClient` → daemon. Built on the CORE
`StdioMCPServer` (NOT the integrations `mcp/` dir, which only holds OAuth).

---

## Scope

- Implement `mcp_server.py` in `parrot/integrations/agentd/`:
  - `AbstractTool` subclasses wrapping the client:
    - `AskAgentTool` — `ask_agent(prompt: str) -> str` (non-stream
      `chat.send`; one MCP process = one daemon connection = one
      conversation session, so consecutive calls share history).
    - `AgentInfoTool`, `ListSchedulesTool`, `DaemonStatusTool`.
    - `InvokeMethodTool` — `invoke_method(method: str, kwargs: dict)`;
      **constructed/registered ONLY when the daemon's `exposed_methods`
      (fetched via `agent.info`) is non-empty**, and validates the method
      against that list client-side too (defense in depth; daemon enforces
      anyway).
  - `async run_mcp_proxy(name_or_socket: str) -> None`: connect client
    (reuse `resolve_socket`), fetch `agent.info`, build the tool set,
    configure `LocalServerConfig`, register tools on `StdioMCPServer`,
    `await server.start()`; on daemon disconnect, exit non-zero with a
    stderr message.
  - ALL logging to stderr (stdout is the MCP JSON-RPC channel) — follow
    `LocalMCPServerBase` precedent.
- Tests: tool registration matrix (invoke tool present/absent per
  exposed_methods); `handle_tools_call` for `ask_agent` against the
  scripted fake daemon; stdio smoke test (initialize + tools/list) driving
  `StdioMCPServer` handlers directly (no subprocess needed).

**NOT in scope**: the `parrot mcp-serve` Click command (TASK-2216), any
changes to core `parrot.mcp.*`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/mcp_server.py` | CREATE | Proxy tools + run_mcp_proxy |
| `packages/ai-parrot-integrations/tests/agentd/test_mcp_proxy.py` | CREATE | Tool matrix + handler tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.agentd.client import AgentDaemonClient, resolve_socket  # TASK-2213
from parrot.mcp.local_server import StdioMCPServer, LocalMCPServerBase
# verified: packages/ai-parrot/src/parrot/mcp/local_server.py:36,18
from parrot.mcp.server_base import MCPServerBase, LocalServerConfig
# verified: packages/ai-parrot/src/parrot/mcp/server_base.py:27,18
from parrot.tools.abstract import AbstractTool
# verified: packages/ai-parrot/src/parrot/tools/abstract.py:234 — confirm the canonical
# import path re-export (parrot.tools) before use
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/server_base.py
class MCPServerBase(ABC):                                  # line 27
    def __init__(self, config: LocalServerConfig)          # line 30
    def register_tool(self, tool: AbstractTool)            # line 38
    def register_tools(self, tools: list[AbstractTool])    # line 45
    async def handle_initialize(self, params) -> dict      # line 50
    async def handle_tools_list(self, params) -> dict      # line 68
    async def handle_tools_call(self, params) -> dict      # line 79
# packages/ai-parrot/src/parrot/mcp/local_server.py
class StdioMCPServer(LocalMCPServerBase):                  # line 36
    async def start(self)                                  # line 44 — blocking stdio loop
# LocalMCPServerBase.__init__ routes logging to stderr     # line 18-33
```

### Does NOT Exist
- ~~`parrot.integrations.mcp` stdio server helpers~~ — `packages/ai-parrot-integrations/src/parrot/integrations/mcp/` holds ONLY `auth/` + `state.py` (OAuth). The stdio server is in CORE `parrot.mcp.local_server`.
- ~~the `mcp` pip SDK as a required dependency~~ — not needed; core `StdioMCPServer` is self-contained JSON-RPC.
- ~~streaming over MCP~~ — v1 `ask_agent` is non-streaming by design (spec Non-Goals context).
- ~~`invoke_method` without allowlist~~ — MUST NOT be registered when `exposed_methods` is empty (spec §7 hard requirement).

---

## Implementation Notes

### Key Constraints
- Read `AbstractTool` (tools/abstract.py:234 onward) for the exact
  subclass contract (`name`, `description`, input schema, `_execute` or
  equivalent) before writing tools — FEAT-391 reserves `_open/_close/
  _ensure_open/auto_open/_opened/_open_lock`; do NOT redefine those.
- Tool docstrings become the LLM-facing descriptions — write them for an
  external model (what the agent is, what asking it does).
- Never write to stdout except via StdioMCPServer.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/local_server.py` — server to reuse.
- Spec §2 CLI surface + §7 Known Risks (invoke gating).

---

## Acceptance Criteria

- [ ] With empty `exposed_methods`: tools/list shows ask_agent, agent_info, list_schedules, daemon_status — NO invoke_method.
- [ ] With non-empty allowlist: invoke_method present and validates method names.
- [ ] `ask_agent` returns the daemon response text via handle_tools_call.
- [ ] No stdout pollution from logging (stderr only), asserted in test via capsys.
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/agentd/test_mcp_proxy.py -v`; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/agentd/test_mcp_proxy.py
import pytest
from parrot.integrations.agentd.mcp_server import build_proxy_tools

@pytest.mark.asyncio
class TestToolMatrix:
    async def test_invoke_absent_without_allowlist(self, scripted_server): ...
    async def test_invoke_present_with_allowlist(self, scripted_server): ...

@pytest.mark.asyncio
class TestAskAgent:
    async def test_tools_call_ask_agent(self, scripted_server): ...
    async def test_stderr_only_logging(self, scripted_server, capsys): ...
```

---

## Agent Instructions

1. Read the spec; 2. verify TASK-2213 completed; 3. verify contract — read
AbstractTool + local_server.py first; 4. index → in-progress; 5. implement;
6. verify criteria; 7. move to completed/; 8. index → done; 9. Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
