# HITL Tool-Call Confirmation (FEAT-235)

**Version**: 0.26.0 | **Module**: `parrot.auth.confirmation`

## Overview

AI-Parrot agents can now pause before executing side-effecting or irreversible
tools and ask the human operator to **approve, cancel, or edit** the call.

This is the _confirm-before-execute_ mode: a declarative per-tool gate that runs
**after** the authorization grant check (FEAT-211) and **before** `tool.execute()`.

```
LLM tool call
     │
     ▼
ToolManager.execute_tool()
     │ 1. GrantGuard.authorize()      (FEAT-211) ── deny ─→ ToolResult(forbidden)
     │ 2. ConfirmationGuard.confirm() (FEAT-235)
     │        ── deny ─→ ToolResult(cancelled|timeout)
     ▼
tool.execute(**decision.parameters)
```

---

## Quick Start

### 1. Mark a tool for confirmation

**Via `routing_meta` (AbstractTool subclass)**:

```python
class WorkdayCheckinTool(AbstractTool):
    name = "workday_checkin"

    def __init__(self, **kwargs):
        super().__init__(
            routing_meta={
                "requires_confirmation": True,
                "confirm_template": "Check in employee {employee_id} at {time}?",
                "confirm_window_seconds": 60,
                "allow_edit": True,
            },
            **kwargs,
        )

    async def _execute(self, employee_id: int, time: str, **kwargs) -> ToolResult:
        ...
```

**Via `@tool` decorator**:

```python
from parrot.tools.decorators import tool

@tool(
    requires_confirmation=True,
    confirm_template="Register check-in for employee {employee_id} at {time}?",
    confirm_window_seconds=60,
    allow_edit=True,
)
def workday_checkin(employee_id: int, time: str) -> str:
    """Register a check-in in Workday."""
    ...
```

**Via toolkit `confirming_tools` class attribute**:

```python
class WorkdayToolkit(AbstractToolkit):
    confirming_tools: frozenset = frozenset({"checkin", "checkout"})

    async def checkin(self, employee_id: int, time: str) -> str:
        """Register a check-in (requires confirmation)."""
        ...
```

### 2. Wire the ConfirmationGuard into ToolManager

```python
from parrot.auth.confirmation import (
    ConfirmationConfig,
    ConfirmationGuard,
    InMemoryConfirmationWindowStore,
)
from parrot.tools.manager import ToolManager

store = InMemoryConfirmationWindowStore()
config = ConfirmationConfig(
    approval_timeout=120.0,      # seconds to wait for the human
    default_channel="telegram",  # fallback HITL channel
    max_edit_retries=1,          # re-ask once on invalid edit, then cancel
)
guard = ConfirmationGuard(
    store=store,
    human_manager=my_human_manager,  # HumanInteractionManager instance
    config=config,
)

tool_manager = ToolManager()
tool_manager.set_confirmation_guard(guard)
```

### 3. Execute normally

```python
result = await tool_manager.execute_tool(
    "workday_checkin",
    {"employee_id": 42, "time": "09:00"},
)
# If approved → result is the tool's normal ToolResult.
# If cancelled → ToolResult(success=False, status="cancelled").
# If timed out → ToolResult(success=False, status="timeout").
```

---

## routing_meta Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `requires_confirmation` | `bool` | `False` | Enable the confirmation gate for this tool. |
| `confirm_template` | `str \| None` | `None` | Python format string for the briefing. Placeholders: `{tool}`, `{params}`, `{<param_name>}`. Falls back to raw `tool with: k=v` listing on error. |
| `confirm_window_seconds` | `int` | `0` | Seconds during which identical calls (same args hash) skip re-asking. `0` = always re-ask (safest default). |
| `allow_edit` | `bool` | `False` | Present a FORM interaction so the human can edit parameter values. Edited values are re-validated against the tool's `args_schema`. |
| `wait_strategy` | `str` | `"block"` | `"block"` or `"suspend"`. BLOCK awaits in-process; SUSPEND persists to Redis and raises `HumanInteractionInterrupt`. |

---

## Wait Strategies

### BLOCK (default)

The guard calls `HumanInteractionManager.request_human_input()` and awaits the
result. Suitable for live-channel deployments (Telegram, WebSocket long-poll).

```python
# Default — no extra config needed
tool.routing_meta["wait_strategy"] = "block"
```

### SUSPEND

The guard calls `request_human_input_async()`, immediately raises
`HumanInteractionInterrupt`, and the HTTP handler serialises state + returns a
`paused` envelope. Suitable for stateless REST deployments.

```python
tool.routing_meta["wait_strategy"] = "suspend"
# Caller must catch HumanInteractionInterrupt and persist agent state.
```

---

## Edit-Before-Execute

When `allow_edit=True`, the guard presents an `InteractionType.FORM` interaction
pre-filled with the current parameters. The human can modify any values.

Edited values are re-validated against the tool's `args_schema` (Pydantic model).
If validation fails, the guard re-asks up to `max_edit_retries` times, then
auto-cancels (never executes with invalid params).

```python
# In the guard config:
config = ConfirmationConfig(max_edit_retries=1)  # one retry on bad edit
```

> **Note**: FORM editing requires a form-capable channel (web, Teams).
> On text-only channels (CLI, Telegram) the interaction falls back to
> APPROVAL (approve/cancel only).

---

## Confirmation Window

Setting `confirm_window_seconds > 0` caches a confirmed call for that duration.
Identical calls (same tool name + same args hash) within the window are allowed
without re-asking.

The window is keyed by `(owner_id, tool_name, args_hash)` where `args_hash`
is a SHA-256 over sorted JSON parameters. Different arguments always re-ask.

```python
routing_meta = {
    "requires_confirmation": True,
    "confirm_window_seconds": 300,  # approved for 5 minutes per arg-set
}
```

---

## Response Semantics

| Human Response | Decision | `ToolResult` |
|----------------|----------|-------------|
| Approved (Yes) | `allowed=True, status="confirmed"` | Normal tool result |
| Rejected (No) | `allowed=False, status="cancelled"` | `ToolResult(success=False, status="cancelled")` |
| Timeout | `allowed=False, status="timeout"` | `ToolResult(success=False, status="timeout")` |
| No manager | `allowed=False, status="cancelled"` | `ToolResult(success=False, status="cancelled")` |

The agent run is **NOT aborted** on rejection or timeout — the `ToolResult` is
returned to the LLM like any other tool result, and the conversation continues.

---

## Fail-Closed

If a tool has `requires_confirmation=True` but no `HumanInteractionManager` is
configured on the guard, the call is **denied** with status `"cancelled"` and a
descriptive error. This mirrors `GrantGuard`'s fail-closed stance.

---

## Bridged tools (Claude Code sub-agents, FEAT-434)

A confirming tool called by a delegated Claude Code sub-agent
(`ClaudeAgentToolBridge`, see [`docs/tools.md`](tools.md) "Claude Agent
Tool Bridge") goes through this exact same `ConfirmationGuard` — never a
self-granted switch:

- **The `confirm: boolean` schema property is absent** on this path. The
  stdio MCP proxy (`parrot mcp-serve`) still injects it (no HITL channel
  of its own there), but `ClaudeAgentToolBridge.build_server()` strips it
  before the sub-agent ever sees the schema — a self-granted "trust me"
  argument is security theatre in-process, since the sub-agent would be
  setting it itself.
- **The channel is the agentd console, never `"telegram"`.** `agentd`
  (`AgentDaemon._configure_hitl`) wires a `ConfirmationGuard` with
  `ConfirmationConfig(default_channel="agentd")` onto the served agent's
  `ToolManager`. In practice the channel used is `PermissionContext.
  channel` (set to `"agentd"` by the daemon's identity resolution — see
  below) — `_request_confirmation()` prefers it over `default_channel`
  whenever it is set, so this is belt-and-braces, not the primary
  mechanism.
- **The caller's identity is real, never `"anonymous"`.** `agentd`
  resolves the UDS peer's OS user via `SO_PEERCRED` -> `pwd` (falling
  back to an env-configured service identity —
  `AGENTD_SERVICE_IDENTITY_*`) and forwards the resulting
  `PermissionContext` all the way to `execute_tool()`, so the
  confirmation window is keyed on the real human, not a shared bucket.
- **The service identity always re-confirms.** The daemon's guard pins
  `ConfirmationConfig(window_seconds=0)` for every caller through this
  `ToolManager` — belt-and-braces with the service identity's own fixed
  `window_seconds=0` (`ServiceIdentityConfig`, `parrot.integrations.
  agentd.config`), since `ConfirmationGuard.confirm()` has no per-caller
  window override to hook (window resolution is `tool.routing_meta` OR
  the guard's own config, never `permission_context` — verified against
  FEAT-235, unmodified here).
- **A bridged confirming tool is exempt from the bridge's own
  `tool_timeout`.** The HITL wait is bounded by `approval_timeout`
  (default 120s) instead — a human actively answering must never be cut
  off by a shorter per-call tool timeout meant for ordinary execution.
- Denial, timeout, and a missing `human_manager` (fail-closed) all map to
  a **recoverable MCP error result** — the sub-agent's turn continues,
  it never aborts.

See `docs/agentd.md` "Claude Code sub-agent tool bridge" for the daemon
config surface.

---

## Relationship to GrantGuard (FEAT-211)

`ConfirmationGuard` is a **sibling** of `GrantGuard`, not a replacement:

- **GrantGuard** (FEAT-211): _Prior authorization_ — "Can this user ever call this tool?"
  Creates a bounded time-window grant on approval.
- **ConfirmationGuard** (FEAT-235): _In-the-moment review_ — "Execute THIS specific call with THESE values?"

Both can coexist on the same ToolManager. The dispatch order is locked:
**grant → confirm**. A tool may require one, both, or neither.

See also: `docs/grants.md` (or search for `GrantGuard` in the codebase).

---

## Public API

```python
from parrot.auth import (
    ConfirmationConfig,
    ConfirmationDecision,
    ConfirmationWindowStore,
    InMemoryConfirmationWindowStore,
    ConfirmationGuard,
)
from parrot.tools.manager import ToolManager

# ToolManager methods:
tool_manager.set_confirmation_guard(guard: ConfirmationGuard) -> None
tool_manager.confirmation_guard  # -> Optional[ConfirmationGuard]
```

---

## Example

See `packages/ai-parrot/examples/workday_checkin.py` for a complete working
example showing `WorkdayCheckinTool`, `ConfirmationGuard` setup, and how the
ToolManager handles approve / cancel paths.
