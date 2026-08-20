---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Claude Agent Tool Bridge — expose ai-parrot toolkits to Claude Code

**Feature ID**: FEAT-434
**Date**: 2026-08-20
**Author**: Jesus Lara
**Status**: draft
**Target version**: ai-parrot 0.27.x / ai-parrot-integrations next minor

> Input: `sdd/proposals/claude-agent-tool-bridge.brainstorm.md`
> (Recommended Option B, all 16 open questions resolved before this spec).

---

## 1. Motivation & Business Requirements

### Problem Statement

`ClaudeAgentClient` lets an ai-parrot Agent delegate a whole turn to a local
Claude Code sub-agent — file-aware, bash-capable, and servable as a daemon via
`parrot.agents.claude_code:make_agent` (FEAT-434's immediate predecessor,
committed 2026-08-20 in 575e00245). But the delegation is **one-way and lossy**:
the sub-agent sees Claude Code's *native* tools (Read, Write, Bash, Edit, Glob,
Grep, WebSearch…) and is completely blind to the agent's own tools and toolkits.

The cause is explicit, not incidental — the client discards the tool arguments
it is handed:

```python
# packages/ai-parrot/src/parrot/clients/claude_agent.py:459
del max_tokens, files, tools, use_tools  # not used by SDK
```

`ask_stream` (:605) and `invoke` (:763) do the same. So an agent carrying a
`JiraToolkit`, a PgVector search tool, or a `DatabaseAgent`'s multi-toolkit
stack loses every one of them the moment its LLM is `claude-agent:*`. The
sub-agent can read the filesystem but cannot query the warehouse, file the
ticket, or search the vector store the agent was built around.

Affected parties:

- **Agent authors** — must choose between Claude Code's harness and their own
  tools; they cannot have both.
- **Daemon operators** — `parrot serve` with a `claude-agent` LLM exposes a
  capable coding agent with none of the org's domain capabilities.
- **The framework's premise** — CLAUDE.md calls ai-parrot "tool-centric". A
  client that silently drops the tool surface contradicts that.

### Goals

- Expose the live `ToolManager`'s tools to the delegated Claude Code sub-agent
  as an **in-process** SDK-MCP server, so tools keep their open connections,
  auth context, `working_memory` and toolkit lifecycle.
- Route every bridged call through `ToolManager.execute_tool()` so the existing
  TOOL_CALL guardrails (FEAT-406) → `GrantGuard` (FEAT-211) →
  `ConfirmationGuard` (FEAT-235) → `tool.execute()` chain applies unchanged,
  including the tool-result compression pipeline (FEAT-380).
- Give bridged tools a real human-in-the-loop path through the daemon's own
  channel instead of a self-granted `confirm` argument.
- Derive caller identity from the environment (OS user of the UDS peer) so
  confirmation windows and grants are keyed per real human, never `"anonymous"`.
- Bound the exposed tool set from the parrot side, since Claude Code performs no
  narrowing of its own (measured — see §7).
- Keep `claude_agent_sdk` an optional extra; nothing may import it at module
  scope.
- Preserve today's behaviour exactly for agents with no tools registered.

### Non-Goals (explicitly out of scope)

- **Parrot keeping the tool loop.** Rejected in brainstorm — see
  `proposals/claude-agent-tool-bridge.brainstorm.md` Option C. The sub-agent is
  the loop; parrot records `tool_calls` as telemetry and never re-executes them.
- **A stdio-subprocess MCP server for this path.** Rejected — see brainstorm
  Option A. It puts tools in a different process from the agent that owns them
  and has no HITL channel. The existing `parrot mcp-serve` stdio proxy keeps
  working unchanged for external clients.
- **Agent-level delegation between daemons** (exposing `agent.invoke` /
  `chat.send` to the sub-agent). Rejected — see brainstorm Option D; re-entrancy
  risk and the wrong granularity. May become its own feature later.
- Exposing Claude Code's native tools *as* parrot tools (the reverse direction).
- Changing `ClaudeAgentClient.batch_ask`, `ask_to_image` or the analytic helpers
  — they raise `NotImplementedError` and are not bridge surfaces.

---

## 2. Architectural Design

### Overview

A new bridge module converts the agent's registered tools into
`claude_agent_sdk.SdkMcpTool` objects and groups them into a single
`McpSdkServerConfig` created with `create_sdk_mcp_server()`. Each tool's schema
comes from the existing `MCPToolAdapter.to_mcp_tool_definition()`; each handler
is a closure that awaits `ToolManager.execute_tool()` **inside the daemon's own
event loop** and converts the returned `ToolResult` back through the adapter's
result path.

`ClaudeAgentClient._build_options()` injects that server as
`ClaudeAgentOptions.mcp_servers` and reconciles `allowed_tools`. All four
conversational surfaces (`ask`, `ask_stream`, `resume`, `invoke`) get the
bridge, because `_build_options()` is the single funnel they share.

Four decisions from the brainstorm shape the design and are load-bearing:

1. **Exposure is automatic.** If the agent has tools registered, they are
   exposed — no opt-in list. What the primary LLM would see is what the
   sub-agent gets, subject only to the narrowing budget below.
2. **The parrot toolkit governs permission.** The CLI's `permission_mode` does
   not apply to bridged tools; `execute_tool()`'s chain does. The
   `confirm: boolean` property that `MCPToolAdapter` injects for confirming
   tools is **stripped** on this path, so the sub-agent is never handed a
   switch it can flip itself.
3. **Identity comes from the environment.** `agentd`'s UDS server reads
   `SO_PEERCRED` to get the connecting peer's `(pid, uid, gid)`, resolves the
   uid to a username via `pwd`, and carries it on the `Session` so
   `execute_tool()` receives a real `PermissionContext`. When peer credentials
   are unavailable, an env-configured service identity is used — and that
   identity never holds a confirmation window.
4. **Narrowing is parrot's job, and needs a real ranker.** Claude Code loads
   every exposed MCP tool eagerly, so a new relevance ranker on `ToolManager`
   selects which tools to hand over, ranked against the turn's prompt.
   `search_tools()` is refactored into a formatting wrapper over that ranker.

### Component Diagram

```
Agent.ask(prompt)
   │
   ▼
ClaudeAgentClient.ask/ask_stream/resume/invoke
   │  (prompt threaded through)
   ▼
_build_options(prompt=…, run_options=…)
   │
   ├──→ ToolManager.rank_tools(prompt, limit)      ← NEW ranker
   │        │
   │        ▼
   │    ClaudeAgentToolBridge.build_server(tools)  ← NEW module
   │        │   per tool: MCPToolAdapter.to_mcp_tool_definition()
   │        │             + strip `confirm` property
   │        │             + handler closure
   │        ▼
   │    create_sdk_mcp_server(name="parrot", tools=[SdkMcpTool…])
   │        │
   │        ▼
   │    ClaudeAgentOptions.mcp_servers  +  allowed_tools reconciliation
   │
   ▼
claude_agent_sdk.query()  ──spawns──→  `claude` CLI (Node subprocess)
                                            │
                          sub-agent calls mcp__parrot__<tool>
                                            │
                              ┌─────────────┘  (back in-process)
                              ▼
                     handler closure
                              │
                              ▼
        ToolManager.execute_tool(name, params, permission_context)
                              │
          TOOL_CALL guardrails (FEAT-406)
                    → GrantGuard (FEAT-211)
                    → ConfirmationGuard (FEAT-235) ──→ HITL: agentd console
                    → tool.execute()
                    → compression pipeline (FEAT-380)
                              │
                              ▼
              MCPToolAdapter._toolresult_to_mcp()  →  sub-agent


agentd UDS server (identity source)
   _handle_connection(reader, writer)
        │  SO_PEERCRED → (pid, uid, gid) → pwd → username
        ▼
   Session.identity ──→ PermissionContext(UserSession(user_id=…))
        │
        └─ unavailable → env-configured service identity (window_seconds pinned 0)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ClaudeAgentRunOptions` | extends | new fields for MCP servers, narrowing budget, per-call tool timeout |
| `ClaudeAgentClient._build_options()` | modifies | builds + injects the server; reconciles `allowed_tools`; gains a `prompt` parameter (it has none today) |
| `ClaudeAgentClient.ask/ask_stream/invoke` | modifies | stop discarding `tools`/`use_tools`; thread the prompt into `_build_options()` |
| `ClaudeAgentClient.resume()` | modifies | threads `user_input` as the ranking query |
| `MCPToolAdapter` | uses | schema + result conversion, reused verbatim; the `confirm` property is post-processed out on this path only |
| `ToolManager.execute_tool()` | calls | the dispatch seam — carries guardrails, grants, confirmation and compression |
| `ToolManager` (ranker) | extends | new relevance ranker; `search_tools()` becomes a wrapper over it |
| `agentd` UDS server | modifies | `_handle_connection` reads `SO_PEERCRED`; identity travels on `Session` |
| `PermissionContext` / `UserSession` | uses | constructed from the resolved OS user or the service identity |
| `ConfirmationConfig` | uses | HITL channel overridden away from the `"telegram"` default; `window_seconds` pinned to 0 for the service identity |
| `parrot.agents.claude_code` | extends | reference integration for the daemon path |
| `parrot mcp-serve` stdio proxy | unaffected | keeps `MCPToolAdapter`'s `confirm` shim; no behaviour change |

### Data Models

```python
# New fields on the existing ClaudeAgentRunOptions (parrot/clients/claude_agent.py:80).
# NOTE: none of these exist today — see §6 "Does NOT Exist".
class ClaudeAgentRunOptions(BaseModel):
    # ... existing 17 fields unchanged ...
    mcp_servers: Optional[Dict[str, Any]] = None
    """Explicit MCP server configs forwarded as ClaudeAgentOptions.mcp_servers.
    The bridge merges its generated server into this mapping rather than
    replacing it, so a caller-supplied server survives."""

    expose_parrot_tools: bool = True
    """Whether to bridge the agent's ToolManager tools to the sub-agent."""

    max_exposed_tools: int = 15
    """Narrowing budget: at most this many ranked tools are handed over.
    Default matches ToolManager.search_tools()'s existing `limit` default."""

    tool_timeout: Optional[float] = None
    """Per-bridged-call timeout in seconds. On expiry a recoverable error
    result is returned; the turn is never aborted. None = no per-call cap."""


# New — the ranked-tool result the bridge consumes.
class RankedTool(BaseModel):
    score: float
    name: str
    tool: Any            # AbstractTool | ToolDefinition


# New — service-identity fallback, populated from environment variables.
class ServiceIdentityConfig(BaseModel):
    display_name: str = "parrot agent server"
    user_id: str = "1001"
    tenant_id: str = "default"
    roles: frozenset[str] = frozenset()
    # window_seconds for this identity is pinned to 0 and is NOT configurable.
```

### New Public Interfaces

```python
# New module: packages/ai-parrot/src/parrot/clients/claude_agent_bridge.py
class ClaudeAgentToolBridge:
    """Builds an in-process SDK-MCP server from a live ToolManager."""

    def __init__(
        self,
        tool_manager: "ToolManager",
        *,
        namespace: str = "parrot",
        tool_timeout: float | None = None,
    ) -> None: ...

    def select(self, query: str, limit: int) -> list["AbstractTool"]:
        """Rank and bound the tools to expose for this turn."""

    def build_server(self, tools: list["AbstractTool"]) -> Any:
        """Return an McpSdkServerConfig. Imports the SDK lazily."""

    def exposed_names(self) -> list[str]:
        """`mcp__<namespace>__<tool>` names, for allowed_tools reconciliation."""


# New on ToolManager (parrot/tools/manager.py)
def rank_tools(self, query: str, limit: int = 15) -> list[tuple[float, Any]]:
    """Rank registered tools by relevance to `query`, best first.

    Replaces the substring-match + alphabetical-sort behaviour that
    `search_tools()` implemented inline; `search_tools()` now formats this
    method's output as JSON for LLM consumption.
    """
```

---

## 3. Module Breakdown

### Module 1: `claude-agent-tool-bridge` (new)
**Path**: `packages/ai-parrot/src/parrot/clients/claude_agent_bridge.py`

Owns the conversion from parrot tools to `SdkMcpTool` objects and the
in-process handler closures. Responsibilities:

- Per tool: name, description, and `input_schema` from
  `MCPToolAdapter.to_mcp_tool_definition()`, with the `confirm` property
  removed from the schema.
- Handler closure: `await tool_manager.execute_tool(name, params, ctx)`,
  wrapped in the per-call timeout, converting both success and failure into MCP
  content via `MCPToolAdapter._toolresult_to_mcp()` / an error result.
- `create_sdk_mcp_server()` assembly and `mcp__ns__name` enumeration.
- Strictly lazy SDK import (inside methods, never at module scope).

### Module 2: `tool-relevance-ranker` (new capability on an existing class)
**Path**: `packages/ai-parrot/src/parrot/tools/manager.py`

Adds `rank_tools()` — a genuine relevance ranker returning scored tool objects
— and refactors `search_tools()` into a thin JSON formatter over it. This is a
behaviour change for every existing `search_tools()` caller (results become
relevance-ordered instead of alphabetical) and must be called out in the
changelog.

### Module 3: `claude-agent-client-plumbing`
**Path**: `packages/ai-parrot/src/parrot/clients/claude_agent.py`

New `ClaudeAgentRunOptions` fields; `_build_options()` gains a `prompt`
parameter and performs server injection plus `allowed_tools` reconciliation;
`ask`, `ask_stream`, `invoke` stop discarding `tools`/`use_tools`; `resume`
threads `user_input` as the ranking query.

### Module 4: `agentd-caller-identity`
**Path**: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py`
(plus `config.py` for the service-identity env config)

Reads `SO_PEERCRED` in `_handle_connection`, resolves the uid via `pwd`, stores
the identity on the `Session`, and builds the `PermissionContext` handed down to
tool execution. Falls back to the env-configured service identity, whose
confirmation window is pinned to 0.

### Module 5: `bridge-hitl-wiring`
**Path**: `packages/ai-parrot/src/parrot/agents/claude_code.py` + daemon glue

Ensures the daemon's `ConfirmationGuard` is reachable from bridged calls and
that its HITL channel targets the agentd console rather than the
`"telegram"` default.

---

## 4. Test Specification

### Unit Tests

`packages/ai-parrot/tests/clients/test_claude_agent_bridge.py`

```python
def test_no_tool_manager_injects_no_server(): ...
def test_empty_registry_injects_no_server(): ...
def test_tool_becomes_sdk_mcp_tool_with_adapter_schema(): ...
def test_confirm_property_stripped_from_schema(): ...
def test_handler_dispatches_through_execute_tool(): ...      # NOT tool.execute()
def test_handler_maps_toolresult_to_mcp_content(): ...
def test_tool_error_becomes_recoverable_error_result(): ...
def test_timeout_becomes_recoverable_error_result(): ...
def test_hitl_denial_becomes_recoverable_error_result(): ...
def test_schema_extraction_failure_skips_only_that_tool(): ...
def test_sdk_missing_does_not_break_module_import(): ...
def test_exposed_names_use_mcp_ns_prefix(): ...
```

`packages/ai-parrot/tests/clients/test_claude_agent.py` (extend the existing 20)

```python
def test_allowed_tools_gains_exposed_parrot_names(): ...
def test_allowed_tools_unset_stays_unset(): ...
def test_caller_supplied_mcp_servers_survive_merge(): ...
def test_prompt_threaded_into_build_options_from_all_four_surfaces(): ...
def test_expose_parrot_tools_false_disables_bridge(): ...
```

`packages/ai-parrot/tests/tools/test_tool_ranker.py`

```python
def test_rank_tools_orders_by_relevance_not_alphabetically(): ...
def test_rank_tools_respects_limit(): ...
def test_rank_tools_excludes_search_tools_itself(): ...
def test_search_tools_still_returns_json_string(): ...        # shape compat
def test_search_tools_no_match_message_preserved(): ...
```

`packages/ai-parrot-integrations/tests/agentd/test_caller_identity.py`

```python
def test_peercred_resolves_os_user(): ...
def test_unresolvable_uid_falls_back_to_service_identity(): ...
def test_service_identity_read_from_environment(): ...
def test_service_identity_never_holds_confirmation_window(): ...
def test_permission_context_reaches_execute_tool(): ...
```

### Integration Tests

`packages/ai-parrot/tests/integration/test_claude_agent_tool_bridge.py`
(marked `@pytest.mark.live`, skipped without the `[claude-agent]` extra and an
authenticated CLI — mirrors the existing `test_claude_agent_live_smoke` guard)

```python
async def test_subagent_invokes_parrot_tool_end_to_end(): ...
async def test_guardrail_block_surfaces_to_subagent(): ...
async def test_confirming_tool_parks_until_human_responds(): ...
async def test_narrowing_budget_caps_exposed_tools(): ...
```

### Test Data / Fixtures

```python
# A minimal AbstractTool with a known args_schema, plus a toolkit whose
# confirming_tools marks one method destructive.
@pytest.fixture
def bridged_tool_manager() -> ToolManager: ...

# A ToolManager with a recording ConfirmationGuard, to assert the chain ran.
@pytest.fixture
def guarded_tool_manager() -> ToolManager: ...

# A fake asyncio UDS peer for SO_PEERCRED assertions.
@pytest.fixture
async def uds_peer(): ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] An agent with `llm="claude-agent:*"` and registered tools exposes them to
      the sub-agent, verified by an `AIMessage.tool_calls` entry named
      `mcp__parrot__<tool>` and by the parrot tool's side effect having run.
- [ ] Every bridged call dispatches through `ToolManager.execute_tool()` —
      asserted by test, not by inspection — so TOOL_CALL guardrails, `GrantGuard`,
      `ConfirmationGuard` and the FEAT-380 compression pipeline all apply. No
      code path calls `tool.execute()` directly.
- [ ] A tool error, a per-call timeout, a HITL denial and a HITL timeout each
      return a **recoverable MCP error result**; none aborts the turn.
- [ ] The `confirm` property injected by
      `MCPToolAdapter.to_mcp_tool_definition()` is absent from every schema the
      sub-agent receives, while the stdio proxy's schemas still contain it.
- [ ] `allowed_tools`, when set by the caller, is extended with the exposed
      `mcp__parrot__*` names; when unset it stays unset.
- [ ] A caller-supplied `mcp_servers` mapping is merged with, not replaced by,
      the generated server.
- [ ] `PermissionContext.user_id` reaching `execute_tool()` is the OS user of the
      UDS peer (`SO_PEERCRED` → uid → `pwd`); the literal `"anonymous"` never
      appears on this path.
- [ ] When peer credentials are unavailable, the env-configured service identity
      is used, and its effective `window_seconds` is `0` regardless of
      deployment configuration — asserted by test.
- [ ] The HITL request for a bridged confirming tool reaches the agentd console,
      not the `"telegram"` default channel.
- [ ] At most `max_exposed_tools` tools are handed over, chosen by
      `ToolManager.rank_tools()` against the turn's prompt; what was dropped is
      logged rather than silently truncated.
- [ ] `rank_tools()` returns relevance-ordered scored tool objects, and
      `search_tools()` still returns a JSON string with its existing no-match
      message — its ordering change is documented in the changelog.
- [ ] All four surfaces (`ask`, `ask_stream`, `resume`, `invoke`) bridge tools.
- [ ] An agent with no tools registered, or with `expose_parrot_tools=False`,
      behaves byte-identically to today.
- [ ] `import parrot.clients.claude_agent` and
      `import parrot.clients.claude_agent_bridge` both succeed without
      `claude_agent_sdk` installed; the failure surfaces only on use.
- [ ] Parrot never re-executes the sub-agent's `tool_calls` — they are telemetry
      only.
- [ ] `pytest packages/ai-parrot/tests/clients/ packages/ai-parrot/tests/tools/
      packages/ai-parrot-integrations/tests/agentd/ -v` passes; the pre-existing
      `dev` failure count in the wider suite is not increased.
- [ ] `ruff check` introduces no new findings in the touched files.
- [ ] Documentation updated: `docs/agentd.md`, `docs/tools.md`, and
      `docs/hitl-confirmation.md` (bridged-tool HITL behaviour).
- [ ] No new hard dependency: `claude-agent-sdk` remains an optional extra.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Carried forward from the brainstorm's Code Context and **re-verified against
> `dev` at commit `eeec8be3f` on 2026-08-20**: all 14 anchor references checked,
> **zero drift**.

### Verified Imports

```python
# All confirmed to resolve in this venv (2026-08-20):
from parrot.mcp.adapter import MCPToolAdapter
from parrot.tools.manager import ToolManager
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.toolkit import AbstractToolkit
from parrot.auth import ConfirmationGuard                       # parrot/auth/__init__.py:77
from parrot.auth.confirmation import ConfirmationDecision, InMemoryConfirmationWindowStore
from parrot.auth.permission import PermissionContext, UserSession
from claude_agent_sdk import create_sdk_mcp_server, tool, SdkMcpTool, McpSdkServerConfig
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/mcp/adapter.py
class MCPToolAdapter:                                          # line 8
    def __init__(self, tool: AbstractTool): ...                # line 19
    def _requires_confirmation(self) -> bool: ...              # line 23
    def to_mcp_tool_definition(self) -> dict[str, Any]: ...    # line 27
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]: ...  # line 59
    def _toolresult_to_mcp(self, result: ToolResult) -> dict[str, Any]: ...    # line 108
# to_mcp_tool_definition() injects a REQUIRED `confirm: boolean` into the input
# schema when routing_meta["requires_confirmation"] is set, and rejects the call
# unless confirm=true. This feature strips that property on the SDK-MCP path only.

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    def search_tools(self, query: str, limit: int = 15) -> str: ...   # line 524
    #   substring match on name/description, sort by name (ALPHABETICAL),
    #   returns json.dumps(matches, indent=2) — a STRING, not tool objects.
    def get_tool(self, tool_name: str) -> Optional[Any]: ...          # line 1127
    def list_categories(self) -> List[str]: ...                       # line 1139
    def get_tools_by_category(self, category: str) -> List[str]: ...   # line 1143
    def list_tools(self) -> List[str]: ...                            # line 1147
    def get_all_tools(self) -> List[Union[ToolDefinition, AbstractTool]]: ...  # line 1155
    def all_tools(self) -> Generator[Any, Any, Any]: ...              # line 1159
    def set_confirmation_guard(self, guard: "ConfirmationGuard") -> None: ...  # line 496
    async def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        permission_context: Optional["PermissionContext"] = None,
    ) -> Any: ...                                                     # line 1431
    # Pipeline inside execute_tool: TOOL_CALL guardrails (FEAT-406)
    #   -> GrantGuard (FEAT-211) -> ConfirmationGuard (FEAT-235)
    #   -> tool.execute() -> compression (FEAT-380)
    async def execute_tool_call(self, content_block: Dict[str, Any]) -> Dict[str, Any]: ...  # line 1781

# packages/ai-parrot/src/parrot/tools/abstract.py
class ToolResult(BaseModel):                                   # line 199
    success: bool = True; status: str = "success"; result: Any
    error: Optional[str] = None; metadata: Dict[str, Any] = {}
    timestamp: str; files: Optional[list] = []; images: Optional[list] = []
    voice_text: Optional[str] = None; display_data: Optional[Dict[str, Any]] = None
class AbstractTool(EventEmitterMixin, ABC):                    # line 234
    name: str = None                                           # line 249
    description: str = None                                    # line 250
    args_schema: Type[BaseModel] = AbstractToolArgsSchema       # line 251
    routing_meta: Dict = None   # per-instance in __init__      # line 253
    async def _execute(self, **kwargs) -> Any: ...             # line 472 (abstract)
    async def execute(self, *args, **kwargs) -> ToolResult: ...  # line 778

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    confirming_tools: frozenset = frozenset()                  # line 285
    async def _open(self) -> None: ...                         # line 388
    async def _close(self) -> None: ...                        # line 404
    async def _ensure_open(self) -> None: ...                   # line 417
    def get_tools(self, ...): ...                              # line 484
    async def get_tools_filtered(self, ...): ...               # line 574
    def get_tools_sync(self, ...): ...                         # line 594
    # line 681: methods in confirming_tools get
    #   tool.routing_meta["requires_confirmation"] = True

# packages/ai-parrot/src/parrot/auth/confirmation.py
class ConfirmationConfig(BaseModel):                           # line 66
    window_seconds: int = Field(0, ge=0)      # 0 = "always re-ask"  # line 83
    approval_timeout: float = Field(120.0, gt=0)               # line 84
    default_channel: str = "telegram"                          # line 85
    max_edit_retries: int = Field(1, ge=0)                     # line 86
class ConfirmationGuard:                                       # line 378
    def __init__(self, store: ConfirmationWindowStore,
                 human_manager: Optional["HumanInteractionManager"] = None,
                 config: Optional[ConfirmationConfig] = None) -> None: ...  # line 399
    async def confirm(self, *, tool: "AbstractTool", parameters: dict,
                      permission_context: Optional["PermissionContext"] = None,
                      ) -> ConfirmationDecision: ...           # line 417
# Window key = (owner_id, tool_name, args_hash)                # line 116
# owner_id derives from permission_context.user_id, "anonymous" when None.
# Fail-closed: human_manager=None -> DENY with status "cancelled".
# Helpers: compute_args_hash (46), render_briefing (251),
#          build_form_schema (291), revalidate_edit (352).

# packages/ai-parrot/src/parrot/auth/permission.py
@dataclass
class UserSession:                                             # line 21
    user_id: str; tenant_id: str; roles: frozenset[str]
@dataclass
class PermissionContext:                                       # line 81
    session: UserSession                                       # line 123
    request_id: Optional[str] = None                           # line 124
    channel: Optional[str] = None                              # line 125
    trace_context: "Optional[TraceContext]" = None             # line 126
    extra: dict[str, Any] = field(default_factory=dict)        # line 127
    @property
    def user_id(self) -> str: ...        # -> session.user_id  # line 130
    @property
    def tenant_id(self) -> str: ...                            # line 135
    @property
    def roles(self) -> frozenset[str]: ...                     # line 140
    def has_role(self, role: str) -> bool: ...                 # line 144

# packages/ai-parrot/src/parrot/clients/claude_agent.py
class ClaudeAgentRunOptions(BaseModel):                        # line 80
    # 17 existing fields: allowed_tools, disallowed_tools, permission_mode,
    # cwd, cli_path, system_prompt, max_turns, max_budget_usd, model,
    # fallback_model, add_dirs, env, extra_options, agents, setting_sources,
    # strict_mcp_config, extra_args
class ClaudeAgentClient(AbstractClient):                       # line 231
    client_name: str = "claude-agent"                          # line 248
    _default_model: str = "claude-sonnet-4-6"                  # line 250
    _lightweight_model: str = "claude-haiku-4-5-20251001"      # line 251
    def __init__(self, cli_path=None, cwd=None, permission_mode=None,
                 run_options=None, **kwargs) -> None: ...       # line 253
    def _build_options(self, *, run_options=None, model=None, system_prompt=None,
                       session_id=None, resume_id=None,
                       permission_mode=None) -> Any: ...        # line 286
    #   ^ NOTE: no `prompt` parameter today. This feature adds one.
    async def _collect_messages(self, prompt: str, *, options: Any) -> List[Any]: ...  # line 377
    async def ask(...) -> AIMessage: ...                        # line 417 (del tools :459)
    async def ask_stream(...): ...                              # line 560 (del tools :605)
    async def resume(self, session_id, user_input, state=None) -> AIMessage: ...  # line 682
    async def invoke(...) -> InvokeResult: ...                  # line 716 (del tools :763)

# claude-agent-sdk 0.2.140 — verified signatures
create_sdk_mcp_server(name: str, version: str = '1.0.0',
                      tools: list[SdkMcpTool[Any]] | None = None) -> McpSdkServerConfig
tool(name: str, description: str, input_schema: type | dict[str, Any],
     annotations: ToolAnnotations | None = None
     ) -> Callable[[Callable[[Any], Awaitable[dict[str, Any]]]], SdkMcpTool[Any]]
SdkMcpTool fields: name, description, input_schema, handler, annotations
McpSdkServerConfig = TypedDict{type: Literal['sdk'], name: str, instance: McpServer}
ClaudeAgentOptions.mcp_servers: dict[str, McpStdio|SSE|Http|SdkServerConfig] | str | Path
```

### Verified Behavioural Measurements

```python
# SO_PEERCRED on an asyncio UDS server — verified live (Linux 6.11, py3.12):
sock = writer.get_extra_info("socket")
raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
pid, uid, gid = struct.unpack("3i", raw)
user = pwd.getpwuid(uid).pw_name
# observed: {'pid': 882139, 'uid': 1000, 'gid': 1000, 'user': 'jesuslara'}; uid == os.getuid()
```

Claude Code tool loading, measured against `claude-agent-sdk 0.2.140` by
attaching an SDK-MCP server with N probe tools and reading the `init` message:

| parrot tools exposed | tools at `init` | of which `mcp__parrot__*` | `ToolSearch` present |
|---|---|---|---|
| 1 | 33 | 1 | yes |
| 25 | 57 | 25 | yes |

Claude Code loads **every** exposed MCP tool eagerly — no deferral, no
narrowing. `ToolSearch` is always available and the sub-agent reaches for it
unprompted (it appeared in `tool_calls` even with one tool exposed), but it
searches an already-loaded set. Narrowing must come from parrot.

Compression selection (relevant to bridged results — no new code needed):

```toml
# packages/ai-parrot/src/parrot/tools/compression/compressors.toml
[compressor."dq_execute_database_query"]
codec = "columnar"; level = "normal"; tee = true
[compressor."dq_execute_database_query".params]
min_rows = 20              # data-shape sensitivity lives in codec params
[compressor."*"]
codec = "json_compact"; level = "minimal"
```
`CompressorRegistry.load()` precedence (registry.py:36): project
`.parrot/compressors.toml` > package manifest > core default.
`CompressorRegistry.resolve(tool_name)` → `CompressorEntry | None`
(registry.py:174), exact key > longest glob. The pipeline is constructed in
`ToolManager.__init__` (manager.py:303-313) and bound lazily inside
`execute_tool()` via `_bind_compression_tee()`.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ClaudeAgentToolBridge.build_server()` | `MCPToolAdapter.to_mcp_tool_definition()` | method call | `parrot/mcp/adapter.py:27` |
| bridge handler closure | `ToolManager.execute_tool()` | awaited call | `parrot/tools/manager.py:1431` |
| bridge handler closure | `MCPToolAdapter._toolresult_to_mcp()` | method call | `parrot/mcp/adapter.py:108` |
| `ClaudeAgentToolBridge.select()` | `ToolManager.rank_tools()` | method call | NEW — does not exist yet |
| `_build_options()` | `ClaudeAgentOptions.mcp_servers` | kwarg | SDK 0.2.140 field, verified |
| agentd `_handle_connection` | `SO_PEERCRED` | `getsockopt` on `writer.get_extra_info("socket")` | verified live probe |
| agentd `Session` identity | `PermissionContext(UserSession(...))` | construction | `parrot/auth/permission.py:21,81` |
| bridged confirming tool | `ConfirmationGuard.confirm()` | via `execute_tool()` | `parrot/auth/confirmation.py:417` |

### Does NOT Exist (Anti-Hallucination)

Verified absent by introspection on 2026-08-20 — do not assume any of these:

- ~~`ClaudeAgentRunOptions.mcp_servers`~~ — no such field. Today the only route
  is `extra_options={"mcp_servers": {...}}`. This feature adds the field.
- ~~`ClaudeAgentRunOptions.expose_tools`~~ / ~~`.exclude_tools`~~ /
  ~~`.expose_tool_categories`~~ / ~~`.tool_manager`~~ / ~~`.timeout`~~ /
  ~~`.tool_timeout`~~ / ~~`.max_exposed_tools`~~ — none exist. `max_turns` and
  `max_budget_usd` are the only run ceilings today.
- ~~`ToolManager.rank_tools()`~~ — **does not exist yet**; it is a deliverable
  of this feature, not something to import.
- ~~`ToolManager.to_sdk_mcp_server()`~~ / ~~`.as_mcp_server()`~~ /
  ~~`.to_mcp_server()`~~ / ~~`.sdk_mcp_server`~~ — no ToolManager→MCP factory
  of any name exists.
- ~~`ToolManager.search_tools()` returns ranked tools~~ — it returns a JSON
  **string**, substring-matched and **alphabetically** sorted (manager.py:524).
  There is no relevance ranking anywhere in `ToolManager`.
- **`ToolManager.get_tools()` is mis-annotated.** Declared `-> Dict[str, Any]`
  at manager.py:1151 but it `return self._tools.values()` — a values view, not
  a dict. Use `get_all_tools()` (:1155) or `all_tools()` (:1159). Never write
  `for name, tool in manager.get_tools().items()`.
- ~~`parrot.mcp.adapter.MCPToolkitAdapter`~~ — only the per-tool
  `MCPToolAdapter` exists; there is no toolkit-level adapter.
- `MCPToolAdapter` and `create_sdk_mcp_server` are **not referenced anywhere**
  in `parrot/clients/claude_agent.py` (grep count: 0). Nothing is wired today.
- ~~`ClaudeAgentClient` honours `tools`/`use_tools`~~ — explicitly discarded in
  `ask` (:459), `ask_stream` (:605), `invoke` (:763).
- ~~`ClaudeAgentClient._build_options(prompt=...)`~~ — `_build_options` has **no
  prompt parameter** today (manager of options only: `run_options`, `model`,
  `system_prompt`, `session_id`, `resume_id`, `permission_mode`).
- ~~`ConfirmationConfig.confirm_window_seconds`~~ — the real field is
  **`window_seconds`** (confirmation.py:83, default `0`). The
  `confirm_window_seconds` name appears only in the `ConfirmationGuard` class
  docstring and is stale.
- ~~A shape-detecting codec selector~~ — codec choice is declarative per tool
  name in `compressors.toml`; shape sensitivity lives in codec *params*.
- **agentd captures no caller identity today.** No `SO_PEERCRED`, `getsockopt`,
  `getpeername` or `ucred` anywhere under `parrot/integrations/agentd/` (grep: 0
  hits), and `server.py` has no `user_id` / `permission_context` /
  `PermissionContext` at all. This is new work, not a wiring change.
- ~~Claude Code defers or narrows MCP tools automatically~~ — it does not; see
  the measurement table above.
- `ClaudeAgentClient.batch_ask`, `ask_to_image`, `summarize_text`,
  `translate_text`, `analyze_sentiment`, `analyze_product_review`,
  `extract_key_points` all raise `NotImplementedError` (claude_agent.py:822-882)
  — not bridge surfaces.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Strictly lazy SDK import.** `parrot/clients/claude_agent.py` performs
  `_import_sdk()` inside every method that needs it; the new bridge module must
  do the same. `import parrot.clients.claude_agent_bridge` has to succeed
  without the `[claude-agent]` extra.
- **Dispatch only through `ToolManager.execute_tool()`.** Never `tool.execute()`.
  This single rule is what makes guardrails, grants, confirmation and compression
  apply for free.
- **Reuse `MCPToolAdapter`, do not fork it.** Schema and result conversion stay
  in one place so the stdio proxy and the SDK-MCP path cannot drift. The
  `confirm`-property removal is post-processing on the bridge side, leaving the
  adapter's stdio behaviour untouched.
- async/await throughout; `asyncio.to_thread` for any genuinely blocking tool.
- Pydantic models for the new option fields and the service-identity config.
- `self.logger` for everything, especially the dropped-tools log.
- Google-style docstrings and strict type hints (CLAUDE.md).

### Known Risks / Gotchas

- **A blocking tool stalls the daemon's event loop.** In-process execution is
  the whole point, but it means a slow tool holds the turn. Mitigation:
  `tool_timeout` per call plus `asyncio.to_thread` for blocking work. This is
  the same exposure the primary LLM's tool loop already carries — a wider door,
  not a new class of risk.
- **`search_tools()` is LLM-visible.** It is itself a registered tool (it skips
  its own name at manager.py:530), so refactoring it changes what models see:
  relevance order instead of alphabetical. Keep the return type and the
  no-match message identical, and flag the ordering change in the changelog.
- **HITL parks the turn.** A destructive bridged call blocks until a human
  answers in `parrot attach`. Operators need to understand this, and
  `approval_timeout` (default 120 s) bounds it.
- **`ConfirmationConfig.default_channel` is `"telegram"`.** If the daemon path
  does not override the channel, a bridged tool's approval request goes to
  Telegram and the operator in `parrot attach` never sees it. The HITL would
  "work" and be invisible.
- **Shared-identity window leak.** The service identity's `owner_id` is shared
  by construction, and the window key is `(owner_id, tool_name, args_hash)`. If
  a deployment raised `window_seconds`, one human's approval could clear a later
  destructive call made for somebody else. Pin it to 0 for that identity.
- **Context and cost grow linearly with exposed tools**, because Claude Code
  loads them all eagerly. `max_exposed_tools` is the control; log what was
  dropped so "covered everything" is never implied when it wasn't.
- **Name collisions.** A parrot tool literally named `Read` is disambiguated for
  the model by the `mcp__parrot__` prefix, but the reconciliation step must
  append only prefixed names to `allowed_tools`, never a bare colliding one.
- **`ClaudeAgentClient._default_model` is `claude-sonnet-4-6` and
  `_lightweight_model` is the date-suffixed `claude-haiku-4-5-20251001`.** Both
  are stale relative to the current family (Opus 5 / Sonnet 5 / `claude-haiku-4-5`
  without a date suffix). Out of scope here — tracked separately — but do not
  copy those strings into new code.
- **`tests/clients/test_claude_agent.py` sits at 20 passing** after the
  2026-08-20 fixes (`73a2c19d6`). Do not regress it. The wider
  `packages/ai-parrot/tests/bots` + `tests/clients` run has a pre-existing
  baseline of 101 failed / 1381 passed / 9 skipped / 3 errors on `dev`; the bar
  is not increasing that count.
- **`dev` is shared between sessions.** Stage explicit paths, never
  `git add -A`; a concurrent `commit -a` elsewhere has already swept
  uncommitted work once during this initiative.

### External Dependencies

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `claude-agent-sdk` | 0.2.140 (installed) | `create_sdk_mcp_server`, `SdkMcpTool`, `McpSdkServerConfig`, `ClaudeAgentOptions.mcp_servers` | Stays an **optional** extra (`ai-parrot[claude-agent]`); bundles the `claude` CLI |
| `mcp` | transitive via the SDK | `ToolAnnotations` type on `tool()` | Only needed if annotations are used |
| stdlib `socket` / `struct` / `pwd` | — | `SO_PEERCRED` peer-credential read and uid→name resolution | Linux-specific; guard for non-Linux and non-UDS transports |

No new hard dependency is added.

---

## 8. Open Questions

All questions from the brainstorm were resolved before this spec was written.
Echoed here for the audit trail:

- [x] Which tools get exposed, and who decides? — *Resolved in brainstorm*:
  automatic — the whole `ToolManager`; no opt-in list, matching what the primary
  LLM sees.
- [x] What governs permission when the sub-agent calls a parrot tool? —
  *Resolved in brainstorm*: the parrot toolkit. Tools run in-process and inherit
  their `AbstractToolkit` lifecycle, auth and HITL; the CLI's `permission_mode`
  does not apply.
- [x] Does `allowed_tools` block `mcp__parrot__*`? — *Resolved in brainstorm*:
  auto-append the exposed names, so the whitelist bounds native tools only.
- [x] Reuse `MCPToolAdapter`'s self-granted `confirm`, or real HITL? —
  *Resolved in brainstorm*: real HITL via the daemon's human channel. `confirm`
  is security theatre in-process because the sub-agent sets it itself.
- [x] Does parrot's ReAct loop re-execute the sub-agent's `tool_calls`? —
  *Resolved in brainstorm*: no. Full delegation; `tool_calls` are telemetry.
- [x] Which client surfaces get the bridge? — *Resolved in brainstorm*: all
  four — `ask`, `ask_stream`, `resume`, `invoke`.
- [x] Per-call timeout behaviour? — *Resolved in brainstorm*: return a
  recoverable error result; never abort the turn. Same for tool errors, HITL
  denial and HITL timeout.
- [x] Strip, refactor, or keep the adapter's `confirm` property? — *Resolved in
  brainstorm*: strip it on the SDK-MCP path; the stdio proxy keeps it unchanged.
- [x] Where does the sub-agent's identity come from? — *Resolved in brainstorm*:
  the OS user of the UDS peer via `SO_PEERCRED` → uid → `pwd`, falling back to
  an env-configured service identity. `"anonymous"` is not acceptable.
- [x] Should exposure honour narrowing? — *Resolved in brainstorm*: yes, and it
  is parrot's job — Claude Code loads every exposed MCP tool eagerly (measured).
- [x] Size ceiling on results? — *Resolved in brainstorm*: no ceiling; apply the
  existing compression codecs.
- [x] Which codec, on what signal? — *Resolved in brainstorm*: whatever
  `compressors.toml` already declares per tool name, with shape sensitivity in
  codec params. **No bridge-side work** — dispatching through `execute_tool()`
  inherits the pipeline.
- [x] What is the fallback service identity? — *Resolved in brainstorm*: built
  from environment variables with defaults (display name along the lines of
  `"parrot agent server"`, `user_id` defaulting to `1001`).
- [x] Is `agentd/server.py` in scope? — *Resolved in brainstorm*: yes, in scope
  for this feature.
- [x] Can the service identity hold a confirmation window? — *Resolved in
  brainstorm*: never — always re-confirms. `window_seconds` stays `0` for it
  regardless of deployment settings.
- [x] What drives the narrowing signal? — *Resolved in brainstorm*: a new real
  relevance ranker on `ToolManager` returning scored `AbstractTool` objects,
  called by the bridge with the turn's prompt; `search_tools()` becomes a
  formatting wrapper over it.

Newly opened during spec authoring (non-blocking; decide during implementation):

- [ ] Is `max_exposed_tools = 15` the right default? It mirrors
  `search_tools()`'s existing `limit`, but the right number depends on observed
  definition-block token cost. Calibrate against telemetry once the bridge
  ships. — *Owner: Jesus*
- [ ] Should `rank_tools()` scoring be lexical (token overlap over name +
  description) or embedding-based? Lexical is dependency-free and adequate for
  v1; embeddings would need `ai-parrot-embeddings` at the core layer, which the
  package boundaries discourage. — *Owner: Jesus*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree.
- **Rationale**: the centre of gravity is `parrot/clients/claude_agent.py`
  (Module 3) plus the new bridge module (Module 1) that it drives. Splitting
  those into parallel worktrees would mostly generate merge conflicts. Modules 2
  (`tools/manager.py`) and 4 (`agentd/server.py`) touch different files and are
  nominally parallelizable, but both are consumed by Module 3's plumbing and by
  the same acceptance criteria, so keeping the `allowed_tools`, identity and HITL
  semantics consistent as they land is worth more than the wall-clock saving.
- **Cross-feature dependencies / conflict watch**:
  - `parrot/tools/manager.py` is high-traffic and shared with the guardrails and
    grants work. In-flight worktrees that may touch it:
    `.claude/worktrees/feat-396-guardrails-infrastructure` and
    `.claude/worktrees/feat-426-research-tools-for-agents`. Check for conflicts
    before starting Module 2.
  - `sdd/specs/hitl-confirmation.spec.md` (FEAT-235) territory is **read-only**
    for this feature — `ConfirmationGuard` is consumed, never modified.
  - `parrot/clients/claude_agent.py` and `parrot/bots/abstract.py` were both
    changed on `dev` on 2026-08-20 (`cf7547187`, `575e00245`, `73a2c19d6`).
    Base the worktree on current `dev`, not on an older branch point.
- **Worktree creation** (after `/sdd-task`):
  ```bash
  git worktree add -b feat-434-claude-agent-tool-bridge \
    .claude/worktrees/feat-434-claude-agent-tool-bridge HEAD
  ```

---

## Revision History

| Date | Author | Change |
|---|---|---|
| 2026-08-20 | Jesus Lara | Initial spec from `claude-agent-tool-bridge.brainstorm.md` (Option B); all 16 brainstorm questions carried forward as resolved; Code Context re-verified against `dev` @ `eeec8be3f` with zero drift |
