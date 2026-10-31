# TASK-4975: MCPToolAdapter routes through AbstractTool.execute with a ToolExecutionContext + auth-required envelope

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (S1, S2, AC-7, AC-8): stdio toolkit servers bypass the FEAT-264 credential gate because
`MCPToolAdapter.execute` calls the tool's private `_execute` (adapter.py:79). This task adds a process-scoped
`ToolExecutionContext` and routes calls through `AbstractTool.execute`, so permission checks, lifecycle hooks and the
broker gate run; `AuthorizationRequired` / `CredentialRequired` become one MCP envelope (`isError: true`, one text item,
`structuredContent = AuthRequiredPayload.model_dump(exclude_none=True)`). Binding a real context at process start is
TASK-4976.

---

## Scope

- `adapter.py`: `ToolExecutionContext` (frozen dataclass, `exec_kwargs()`), `auth_required_result(payload)`,
  `MCPToolAdapter.__init__(tool, *, execution_context=None)`, `execute()` → `self.tool.execute(**arguments,
  **exec_kwargs)`, auth exceptions → envelope.
- `server_base.py`: `MCPServerBase.__init__(config, *, execution_context=None)`; `register_tool` passes it.
- Tests; keep `test_adapter.py`, `test_adapter_confirm.py`, `test_server_base.py` green.

**NOT in scope**: resolving a principal or broker (TASK-4976); `local_server.py` / `toolkit_server.py`; the HTTP MCP server (FEAT-477, out of scope).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/adapter.py` | MODIFY | ToolExecutionContext, execute route, envelope |
| `packages/ai-parrot/src/parrot/mcp/server_base.py` | MODIFY | execution_context plumbing |
| `packages/ai-parrot/tests/mcp/test_adapter_execution_context.py` | CREATE | S1/S2 tests |
| `packages/ai-parrot/tests/mcp/test_adapter_confirm.py` | MODIFY | give `_EchoTool` an `args_schema` (execute() validates args) |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
from parrot.tools.abstract import AbstractTool, ToolResult           # adapter.py:5 (already)
from parrot.auth.credentials import AuthRequiredPayload, CredentialRequired   # credentials.py:114, :128
from parrot.auth.exceptions import AuthorizationRequired             # exceptions.py:15
from dataclasses import dataclass                                     # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/adapter.py (imports: json, logging, typing.Any, AbstractTool, ToolResult)
class MCPToolAdapter:
    def __init__(self, tool: AbstractTool):                           # :19
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:   # :59 ; confirm guard :61-76 ; `result = await self.tool._execute(**arguments)` :79
    def _toolresult_to_mcp(self, result: ToolResult) -> dict[str, Any]      # :108 (success → isError False, else True)
# packages/ai-parrot/src/parrot/tools/abstract.py
    async def execute(self, *args, **kwargs) -> ToolResult            # :916 — pops _permission_context (:939), _resolver (:940),
    #   _broker/_cred_channel/_cred_user_id (:950-952); gate active only if credential_provider AND _broker (:1023);
    #   empty _cred_user_id with gate active → ValueError (:1025); NeedsAuth → raise CredentialRequired (:1040);
    #   re-raises AuthorizationRequired (:1188) and CredentialRequired (:1196); other errors → ToolResult(error)
# packages/ai-parrot/src/parrot/auth/exceptions.py
class AuthorizationRequired(Exception): def to_payload(self) -> AuthRequiredPayload    # :58 — NO tool_name kwarg (carries self.tool_name)
# packages/ai-parrot/src/parrot/auth/credentials.py
class CredentialRequired(Exception): def to_payload(self, *, tool_name: Optional[str] = None) -> AuthRequiredPayload   # :171
# packages/ai-parrot/src/parrot/mcp/server_base.py
class MCPServerBase(ABC):
    def __init__(self, config: LocalServerConfig):                    # :60 ; self.tools: dict[str, MCPToolAdapter]
    def register_tool(self, tool: AbstractTool):                      # :68 ; `adapter = MCPToolAdapter(tool)` :71
# PermissionContext.session.user_id (permission.py:81/:21) → _cred_user_id
```

### Does NOT Exist
- ~~`ToolExecutionContext`, `auth_required_result`, `structuredContent` in adapter.py~~ — added here.
- ~~`AuthorizationRequired.to_payload(tool_name=...)`~~ — **spec §3 M5 drift**: only `CredentialRequired.to_payload`
  accepts `tool_name`; call `exc.to_payload()` for `AuthorizationRequired` and `exc.to_payload(tool_name=self.tool.name)`
  for `CredentialRequired`.
- ~~a principal in `handle_tools_call`~~ — it only passes `arguments` (`server_base.py:124`); the context lives on the adapter.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/mcp/adapter.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/mcp/server_base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/mcp/test_adapter_execution_context.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/adapter.py#MCPToolAdapter",
    "sym:packages/ai-parrot/src/parrot/mcp/server_base.py#MCPServerBase",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool"
  ]
}
```

---

## Implementation Notes

- `exec_kwargs()` returns `{}` when `permission_context` is None (no identity → today's behaviour, AC-4). Otherwise
  `{"_permission_context": pc, "_broker": broker, "_cred_channel": channel, "_cred_user_id": pc.session.user_id}`
  (omit `_broker` when None).
- `execution_context` is a **mutable attribute** on both the adapter and the server: TASK-4976 resolves it in
  `start()` *after* tools were registered and assigns it to every adapter.
- `execute()` always goes through `self.tool.execute` (S1). That call returns a `ToolResult` and already converts
  ordinary exceptions to an error `ToolResult` — keep `_toolresult_to_mcp` for it. Run the three existing MCP test files:
  their stub tools define `_execute` and must still pass through `execute()` (arg validation via `args_schema` included).
  If one only passes because it relied on the bypass, fix the stub, not the adapter, and say so in the Completion Note.
- Envelope: text `f"{payload.provider} authorization required — run `parrot connect {payload.provider}`" + (f" or open
  {payload.auth_url}" if auth_url)`. No stdout writes anywhere (FEAT-485).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add `ToolExecutionContext` and `auth_required_result` to adapter.py — *why*: §2 Data Models fixes both shapes.
2. Route `execute()` through `AbstractTool.execute` and catch the two auth exceptions — *why*: S1/S2.
3. Plumb `execution_context` through `MCPServerBase` — *why*: TASK-4976 sets it once per process.
4. Write the new tests; run them plus the three existing MCP adapter/server tests.

### `packages/ai-parrot/src/parrot/mcp/adapter.py` (MODIFY — module level)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.abstract import AbstractTool, ToolResult' mcp/adapter.py)
# AFTER — insert below `from parrot.tools.abstract import AbstractTool, ToolResult` (verified: adapter.py:5);
# also add `from dataclasses import dataclass` and `from typing import Dict, Optional` to the stdlib imports.
from parrot.auth.credentials import AuthRequiredPayload, CredentialRequired
from parrot.auth.exceptions import AuthorizationRequired


@dataclass(frozen=True)
class ToolExecutionContext:
    """Process-scoped identity for stdio servers; ``None`` on the adapter keeps today's behaviour."""

    permission_context: Optional[Any] = None   # parrot.auth.permission.PermissionContext
    broker: Optional[Any] = None               # parrot.auth.broker.CredentialBroker
    channel: str = "cli"

    def exec_kwargs(self) -> Dict[str, Any]:
        """Kwargs for ``AbstractTool.execute`` (never LLM-visible)."""
        if self.permission_context is None:
            return {}
        kwargs: Dict[str, Any] = {
            "_permission_context": self.permission_context,
            "_cred_channel": self.channel,
            "_cred_user_id": self.permission_context.session.user_id,
        }
        if self.broker is not None:
            kwargs["_broker"] = self.broker
        return kwargs


def auth_required_result(payload: AuthRequiredPayload) -> Dict[str, Any]:
    """MCP auth-required envelope (S2): isError + one text item + structuredContent; never writes stdout."""
    # FILL IN: text per Implementation Notes; return {"isError": True, "content": [{"type": "text", "text": text}],
    #          "structuredContent": payload.model_dump(exclude_none=True)} — AC-8
    raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/mcp/adapter.py` (MODIFY — __init__ and execute)
```python
# occurrences: 1 (verified: grep -c '    def __init__(self, tool: AbstractTool):' mcp/adapter.py)
# REPLACE `    def __init__(self, tool: AbstractTool):` (verified: adapter.py:19) and its 2-line body with:
    def __init__(self, tool: AbstractTool, *, execution_context: Optional[ToolExecutionContext] = None):
        self.tool = tool
        self.execution_context = execution_context
        self.logger = logging.getLogger(f"MCPToolAdapter.{tool.name}")

# occurrences: 1 (verified: grep -c '            result = await self.tool._execute(\*\*arguments)' mcp/adapter.py)
# REPLACE `            result = await self.tool._execute(**arguments)` (verified: adapter.py:79) with:
            ctx_kwargs = self.execution_context.exec_kwargs() if self.execution_context else {}
            result = await self.tool.execute(**arguments, **ctx_kwargs)
# and INSERT, before the existing `except Exception as e:` of that try (verified: adapter.py:96):
        except AuthorizationRequired as exc:
            return auth_required_result(exc.to_payload())
        except CredentialRequired as exc:
            return auth_required_result(exc.to_payload(tool_name=self.tool.name))
```

### `packages/ai-parrot/src/parrot/mcp/server_base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    def __init__(self, config: LocalServerConfig):' mcp/server_base.py)
# REPLACE the signature line (verified: server_base.py:60) with the line below and add, as the first body line,
# `self.execution_context = execution_context`; change the import (:13) to
# `from parrot.mcp.adapter import MCPToolAdapter, ToolExecutionContext` and add `from typing import Any, Optional`.
    def __init__(self, config: LocalServerConfig, *, execution_context: Optional[ToolExecutionContext] = None):

# occurrences: 1 (verified: grep -c '        adapter = MCPToolAdapter(tool)' mcp/server_base.py)
# REPLACE `        adapter = MCPToolAdapter(tool)` (verified: server_base.py:71) with:
        adapter = MCPToolAdapter(tool, execution_context=self.execution_context)
```
**Why**: subclasses (`StdioMCPServer.__init__(config)`, local_server.py:63) keep calling `super().__init__(config)`; the
keyword default keeps them unchanged and TASK-4976 assigns the attribute later.

### `packages/ai-parrot/tests/mcp/test_adapter_execution_context.py` (CREATE)
```python
"""MCPToolAdapter execution context + auth envelope (FEAT-774 M5, AC-7, AC-8)."""
import pytest

from parrot.auth.credentials import AuthRequiredPayload, CredentialRequired
from parrot.mcp.adapter import MCPToolAdapter, ToolExecutionContext, auth_required_result


async def test_adapter_routes_through_abstract_tool_execute():
    # FILL IN: stub AbstractTool whose execute() is spied; _permission_context/_broker/_cred_channel="cli"/_cred_user_id
    #          reach it; a credential_provider tool with a fake broker receives current_credential() inside _execute
    ...

async def test_adapter_auth_required_envelope_fields_survive(capsys):
    # FILL IN: tool raising CredentialRequired(provider, auth_url, "oauth2", user_code=..., verification_uri=..., expires_in=...)
    #          → isError True, one text item, structuredContent == payload.model_dump(exclude_none=True); capsys.out == ""
    ...

async def test_no_context_keeps_today_behaviour():
    # FILL IN: execution_context None → tool.execute called without any _-prefixed kwargs
    ...
```

### FILL IN checklist
- [ ] `auth_required_result` — text + envelope; bounded by AC-8
- [ ] tests — spy execute, broker stub, capsys stdout purity

---

## Acceptance Criteria

- [ ] With a context, the tool runs via `AbstractTool.execute` with `_permission_context`, `_broker`, `_cred_channel="cli"`, `_cred_user_id`, and reads its token via `current_credential()` (AC-7)
- [ ] `AuthorizationRequired` / `CredentialRequired` → `isError: true`, one text item, `structuredContent` with every `AuthRequiredPayload` field; nothing on stdout (AC-8)
- [ ] Without a context no `_`-kwargs are passed (AC-4); existing MCP adapter/server tests stay green; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_adapter_execution_context.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_adapter.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_adapter_confirm.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_server_base.py -q`
- `pytest packages/ai-parrot/tests/unit/test_tool_credential_seam.py -q`

---

## Test Specification

```python
# see packages/ai-parrot/tests/mcp/test_adapter_execution_context.py block in the blueprint
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug connections-cli-local-mcp --feature-id FEAT-774 --spec sdd/specs/connections-cli-local-mcp.spec.md --index sdd/tasks/index/connections-cli-local-mcp.json`)
2. **Read the spec** at the path listed above for full context (§2 Overview, §3 for this module, §7 gotchas)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-cli-local-mcp.json`
4. **Verify the Codebase Contract** — before writing ANY code re-run each `grep -c` in the blueprint;
   if a count differs, fix the anchor in this file first. Never use anything under "Does NOT Exist".
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker,
   never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` (plus one entry per other
   changed package, e.g. `packages/ai-parrot-server/src`) and `ruff check` the touched files
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> connections-cli-local-mcp verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
