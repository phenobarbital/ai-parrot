---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Claude Agent Tool Bridge — expose ai-parrot toolkits to Claude Code

**Date**: 2026-08-20
**Author**: Jesus (with Claude Opus 5)
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

`ClaudeAgentClient` lets an ai-parrot Agent delegate a whole turn to a local
Claude Code sub-agent — file-aware, bash-capable, and now servable as a daemon
(`parrot.agents.claude_code:make_agent`, committed 2026-08-20). But the
delegation is **one-way and lossy**: the sub-agent sees Claude Code's *native*
tools (Read, Write, Bash, Edit, Glob, Grep, WebSearch…) and is completely blind
to the agent's own tools and toolkits.

The cause is explicit, not incidental — `ClaudeAgentClient.ask()` discards the
tool arguments it is handed:

```python
# packages/ai-parrot/src/parrot/clients/claude_agent.py:459
del max_tokens, files, tools, use_tools  # not used by SDK
```

`ask_stream` (`:605`) and `invoke` (`:763`) do the same. So an agent carrying a
`JiraToolkit`, a `PgVector` search tool, or a `DatabaseAgent`'s multi-toolkit
stack loses every one of them the moment its LLM is `claude-agent:*`. The
sub-agent can read the filesystem but cannot query the warehouse, file the
ticket, or search the vector store the agent was built around.

Who is affected:

- **Agent authors** — must choose between Claude Code's harness and their own
  tools; they cannot have both.
- **Daemon operators** — `parrot serve` with a `claude-agent` LLM exposes a
  capable coding agent with none of the org's domain capabilities.
- **The framework's premise** — CLAUDE.md calls ai-parrot "tool-centric".
  A client that silently drops the tool surface contradicts that.

Why now: the daemon path was just verified end to end, and a working PoC proved
the bridge is a wiring job, not research (see Code Context → User-Provided Code).

## Constraints & Requirements

- **The sub-agent runs in a separate process.** The bundled `claude` CLI is a
  Node subprocess. Anything callable from it must cross a boundary; parrot tools
  hold live DB connections, HTTP sessions and `working_memory`, so they cannot
  be serialised and shipped over — they must execute **in-process** in the
  daemon and only their *results* may cross.
- **Policy must not be bypassed.** `ToolManager.execute_tool()` already runs the
  TOOL_CALL guardrail pipeline (FEAT-406) → `GrantGuard` (FEAT-211) →
  `ConfirmationGuard` (FEAT-235) → `tool.execute()`. Any bridge that calls
  `tool.execute()` directly silently defeats all three.
- **No new hard dependency.** `claude_agent_sdk` stays an optional extra
  (`ai-parrot[claude-agent]`); `import parrot.clients.claude_agent` must keep
  working without it, per the module's existing strict-lazy-import contract.
- **`AbstractToolkit` lifecycle must be honoured.** Tools with `auto_open=True`
  need `_ensure_open()` before use and participate in
  `ToolManager.cleanup_toolkits()`.
- **Backwards compatible.** Agents whose LLM is `claude-agent:*` and that have
  no tools registered must behave exactly as today.
- **Single tool loop.** Decided in discovery: the Claude Code sub-agent *is* the
  loop. Parrot records the resulting `tool_calls` as telemetry and never
  re-executes them, so double execution is structurally impossible.
- **Failures are recoverable, never fatal.** A tool error, a per-call timeout, a
  HITL denial and a HITL timeout all come back as MCP error results the
  sub-agent can reason about. None of them aborts the turn.
- **No self-granted confirmation.** The `confirm: boolean` property that
  `MCPToolAdapter` injects for confirming tools must be stripped from the schema
  on the in-process path — the sub-agent must not be handed a switch it can flip
  itself. The stdio proxy keeps it, unchanged.
- **Identity comes from the environment, not a placeholder.** The
  `PermissionContext` handed to `execute_tool()` carries the OS user of the UDS
  peer (`SO_PEERCRED` → uid → `pwd`), falling back to a fixed service identity.
  `"anonymous"` is not acceptable, because confirmation windows and grants are
  keyed on `user_id`.
- **Narrowing is parrot's job.** Claude Code loads every exposed MCP tool
  eagerly (measured), so the bridge — not the sub-agent — is responsible for
  bounding how many tools are handed over.
- **Results are compressed, not truncated.** The existing
  `parrot.tools.compression` codecs apply to bridged results; no size ceiling
  silently drops data.

---

## Options Explored

### Option A: stdio MCP server subprocess

Reuse the existing `parrot mcp-serve` stdio proxy
(`parrot/integrations/agentd/mcp_server.py`) and point the sub-agent at it via
`ClaudeAgentOptions.mcp_servers` as an `McpStdioServerConfig`. The sub-agent
talks MCP over a pipe to a *second* parrot process that owns the tools.

✅ **Pros:**
- Zero new adapter code — the stdio proxy already exists and is tested.
- Process isolation: a tool that segfaults or leaks cannot take the daemon down.
- The same server is reachable by *any* MCP client, not just Claude Code.

❌ **Cons:**
- **Wrong process.** The spawned proxy has its own `ToolManager`, so it does not
  share the live agent's toolkit state — open connections, `working_memory`,
  conversation context and the agent's `ConfirmationGuard` all live in the
  daemon, not in the proxy. Tools that depend on agent state break.
- No HITL: the stdio transport has no human channel, which is precisely why
  `MCPToolAdapter` degrades destructive tools to a `confirm: bool` argument the
  caller grants itself.
- Two extra process hops per tool call; startup cost per run.
- Requires a second socket/daemon to be running and healthy.

📊 **Effort:** Low (wiring) — but does not satisfy the in-process constraint.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `claude-agent-sdk` | `McpStdioServerConfig` transport | 0.2.140 installed |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-integrations/src/parrot/integrations/agentd/mcp_server.py` — the stdio proxy (`run_mcp_proxy`)
- `packages/ai-parrot/src/parrot/mcp/adapter.py` — `MCPToolAdapter`

---

### Option B: in-process SDK-MCP server built from the agent's ToolManager

Build an `McpSdkServerConfig` at call time from the live `ToolManager`, using
`claude_agent_sdk.create_sdk_mcp_server()`. Each registered parrot tool becomes
one `SdkMcpTool` whose handler runs **inside the daemon's event loop** and
dispatches through `ToolManager.execute_tool()`, so the full guardrail →
grant → confirmation → execute chain applies unchanged. The schema comes from
the existing `MCPToolAdapter.to_mcp_tool_definition()`; results come back
through `MCPToolAdapter._toolresult_to_mcp()`.

The server config is injected into `ClaudeAgentOptions.mcp_servers` and the
generated `mcp__parrot__*` names are appended to `allowed_tools` when the caller
set one, so a whitelist meant for native tools never silently blocks the agent's
own capabilities.

✅ **Pros:**
- **Same process, same state.** Tools keep their open connections, auth context,
  `working_memory` and toolkit lifecycle — no serialisation boundary.
- **Policy for free.** Routing through `ToolManager.execute_tool()` inherits
  FEAT-406 guardrails, FEAT-211 grants and FEAT-235 confirmation, including the
  real HITL channel the daemon already has (`parrot attach` /
  `HumanInteractionManager`) instead of the self-granted `confirm` argument.
- Reuses `MCPToolAdapter` for both schema and result conversion — one
  conversion path shared with the stdio proxy, so they cannot drift.
- No subprocess, no socket, no extra hop; nothing to keep alive.
- Symmetric with what the primary LLM sees: whatever is in the `ToolManager` is
  what the sub-agent gets.

❌ **Cons:**
- A slow or blocking tool stalls the daemon's loop — a genuinely blocking tool
  needs `asyncio.to_thread`, and HITL waits hold the turn open.
- Tool name collisions with native tools are possible; the `mcp__parrot__`
  prefix mitigates but the *bare* names still matter for `allowed_tools`.
- Requires new fields on `ClaudeAgentRunOptions` (`mcp_servers` does not exist
  today — only the `extra_options` escape hatch).
- Couples `ClaudeAgentClient` to `ToolManager`, which it currently ignores.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `claude-agent-sdk` | `create_sdk_mcp_server`, `SdkMcpTool`, `McpSdkServerConfig` | 0.2.140 installed; `input_schema` accepts a plain dict, so the adapter's JSON schema passes through unchanged |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/mcp/adapter.py:8` — `MCPToolAdapter` (schema + result conversion, `requires_confirmation` detection)
- `packages/ai-parrot/src/parrot/tools/manager.py:1431` — `ToolManager.execute_tool()` (the whole policy chain)
- `packages/ai-parrot/src/parrot/tools/manager.py:1155` — `get_all_tools()` for enumeration
- `packages/ai-parrot/src/parrot/clients/claude_agent.py:286` — `_build_options()`, the single place options are assembled

---

### Option C: native tool-use round-trip (parrot keeps the loop)

Do not expose anything as MCP. Instead pass the agent's tool schemas to the
sub-agent as ordinary tool definitions, have it emit `tool_use` blocks *without*
executing them, execute them in parrot's own ReAct loop, and feed results back
via `resume()`.

✅ **Pros:**
- Keeps parrot's telemetry, context compression and guardrails on the primary
  loop, exactly as with every other client.
- No MCP concepts introduced; the client looks like `AnthropicClient`.

❌ **Cons:**
- **Fights the harness.** The Claude Code SDK is built to execute tools itself;
  there is no supported way to make it propose-but-not-execute. This would mean
  reimplementing the agent loop the SDK exists to provide.
- Rejected in discovery: the decision was full delegation, one loop.
- Every turn becomes N round-trips through `resume()`, losing the sub-agent's
  own context and planning between steps.
- High risk of double execution if the SDK ever does run a tool.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `claude-agent-sdk` | `resume` / session continuation | 0.2.140 |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/clients/claude_agent.py:682` — `resume()`
- `packages/ai-parrot/src/parrot/tools/manager.py:1781` — `execute_tool_call()`

---

### Option D (unconventional): expose the agentd daemon to itself over MCP

Skip the client entirely. `parrot mcp-serve <name>` already exposes a running
daemon's methods to external LLMs; register *that* as an MCP server for the
sub-agent, so the sub-agent calls the daemon's RPC surface (`agent.invoke`,
`chat.send`, the `exposed_methods` allowlist) rather than individual tools.

✅ **Pros:**
- Uses only shipped machinery; nothing new to build.
- `exposed_methods` is already an explicit, auditable allowlist.
- Grants the sub-agent *agent-level* capabilities (a whole `sync_fireflies_transcripts`),
  not just leaf tools — a coarser, sometimes more useful granularity.

❌ **Cons:**
- **Re-entrancy.** The sub-agent calling back into the daemon that spawned it
  risks a loop: `chat.send` would invoke the same LLM again.
- Granularity is wrong for the stated goal — methods, not tools; the toolkits
  themselves stay invisible.
- Needs a live socket and a second process; same isolation problem as Option A.

📊 **Effort:** Low

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-integrations/src/parrot/integrations/agentd/mcp_server.py` — `run_mcp_proxy`
- `packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py` — `exposed_methods`

---

## Recommendation

**Option B** is recommended.

The deciding factor is state, not elegance. Options A and D both put the tools
in a *different process* from the agent that owns them, which breaks the tools
that matter most — the ones holding a database connection, an authenticated HTTP
session, or `working_memory` scoped to this conversation. A `PgVector` search
tool in a spawned proxy is a different object with a different pool than the one
the agent configured; a `JiraToolkit` there has no idea who the user is. In-process
execution is the only variant where "the agent's tools" means the agent's actual
tools.

The second factor is that Option B is the only one where the security model comes
along for free. Because the handler dispatches through
`ToolManager.execute_tool()`, the guardrail pipeline, grant check and
`ConfirmationGuard` all fire exactly as they do for the primary LLM — including
real HITL through the daemon's human channel. Options A and D degrade
confirmation to `MCPToolAdapter`'s `confirm: bool` argument, which the sub-agent
simply sets itself; that is a paper trail, not a control.

What we are trading off, honestly:

- **Isolation.** A crashing or blocking tool now takes the daemon's event loop
  with it. Option A's subprocess would have contained that. Mitigation is
  discipline (`asyncio.to_thread` for blocking work, timeouts per call) rather
  than architecture, and it is the same exposure the primary LLM's tool loop
  already carries — so this is not a *new* class of risk, just a wider door.
- **Coupling.** `ClaudeAgentClient` gains a dependency on `ToolManager` that it
  does not have today. Acceptable: every other client already receives a
  `tool_manager` in its constructor, so the client becomes *more* like its
  siblings, not less.
- **A blocked turn while HITL waits.** Correct behaviour, but operators need to
  understand that a destructive tool call parks the sub-agent until a human
  answers in `parrot attach`.

Option C is rejected on grounds already settled in discovery: it reimplements
the loop the SDK exists to provide, and full delegation was the chosen model.
Option D remains interesting as a *separate* future capability — agent-level
delegation between daemons — but it does not solve the toolkit-visibility problem.

---

## Feature Description

### User-Facing Behavior

An agent whose LLM is `claude-agent:*` (or `claude-code:*`) automatically offers
its registered tools to the Claude Code sub-agent. Nothing to configure:

```yaml
# examples/agents/claude_code_daemon.yaml
agent:
  target: "parrot.agents.claude_code:make_agent"
  kwargs:
    llm: "claude-agent:claude-sonnet-4-6"
    tools: [inventory, jira, pgvector]      # <- these become visible
```

```
$ parrot ask claude-code "How many units of ABC-123 are in stock?"
SKU ABC-123 has 137 units in stock at warehouse MIA-3.
```

The returned `AIMessage.tool_calls` records `mcp__parrot__inventory_level`
alongside any native tools the sub-agent used, so existing telemetry, cost
accounting and transcript rendering keep working unchanged.

When a tool marked `requires_confirmation` is called, the turn parks and a
human attached via `parrot attach` sees the briefing rendered by
`render_briefing()`; approving lets the call proceed, rejecting returns an error
result the sub-agent can reason about.

Opting out stays possible for the cases that need it (`invoke` used purely for
structured extraction, or an agent that deliberately wants only native tools).

### Internal Behavior

1. **Enumeration.** At option-build time, the client asks its `tool_manager`
   for the registered tools. Nothing is exposed when no manager is attached or
   the registry is empty — the current behaviour is preserved exactly.
2. **Adaptation.** Each tool is converted once into an `SdkMcpTool`: name and
   description from the tool, `input_schema` from
   `MCPToolAdapter.to_mcp_tool_definition()`, and a handler closure that
   dispatches to `ToolManager.execute_tool()` and converts the `ToolResult`
   back through the adapter's result path.
3. **Server assembly.** The adapted tools are grouped into one SDK-MCP server
   (`create_sdk_mcp_server`) under a single namespace, yielding
   `mcp__<namespace>__<tool>` names, and injected as
   `ClaudeAgentOptions.mcp_servers`.
4. **Allowlist reconciliation.** If the caller set `allowed_tools`, the exposed
   `mcp__*` names are appended so a whitelist scoped to native tools cannot
   silently blind the agent to its own capabilities.
5. **Invocation.** The sub-agent calls a tool; the handler runs in the daemon's
   loop; guardrails/grants/confirmation fire; the result crosses back as MCP
   content.
6. **Recording.** The sub-agent's tool activity lands in the `AIMessage` via
   the existing `AIMessageFactory.from_claude_agent`. Parrot does **not**
   re-execute anything.

All four surfaces get the treatment — `ask`, `ask_stream`, `resume` and
`invoke` — since `_build_options()` is the single funnel they share.

### Edge Cases & Error Handling

- **No tool manager / no tools** → no MCP server injected; byte-identical
  behaviour to today.
- **SDK missing** → the bridge must not break the module's strict-lazy-import
  contract; nothing may import `claude_agent_sdk` at module scope.
- **Schema extraction fails** for a tool → that tool is skipped with a warning
  rather than failing the whole run (`MCPToolAdapter` already degrades to
  `{"type": "object", "properties": {}}`).
- **Tool raises** → mapped to an MCP error result so the sub-agent can recover;
  the run continues.
- **Tool blocks the loop** → per-call timeout fires and returns a recoverable
  error result naming the tool and the elapsed budget; the turn continues.
  Blocking work belongs in `asyncio.to_thread`. Note there is no timeout field
  on `ClaudeAgentRunOptions` today — one has to be added.
- **HITL denies or times out** → recoverable error result describing the denial,
  not a crash. The sub-agent can explain to the user why it stopped.
- **Confirming tool exposed in-process** → the adapter's `confirm` property is
  stripped from the schema before the tool reaches the sub-agent, and the real
  `ConfirmationGuard` runs inside `execute_tool()` instead.
- **Peer credentials unavailable** (non-UDS transport, uid with no `pwd` entry)
  → fall back to the fixed service identity rather than `"anonymous"`, and log
  which identity was used so an operator can tell confirmations apart.
- **Many tools registered** → since Claude Code loads them all eagerly, the
  bridge narrows before exposing; the narrowing signal and budget are open
  questions.
- **Name collision** with a native tool (a parrot tool literally named `Read`)
  → the `mcp__ns__` prefix disambiguates for the model; the reconciliation step
  must not append a bare colliding name to `allowed_tools`.
- **Tool needs a toolkit opened** → `execute_tool()`/`ToolkitTool._execute()`
  already handle `auto_open`; nothing extra required.
- **Very large tool result** → subject to the existing compression codecs;
  worth measuring, since MCP content crosses into the sub-agent's context.

---

## Capabilities

### New Capabilities
- `claude-agent-tool-bridge`: expose a live `ToolManager`'s tools to a delegated
  Claude Code sub-agent as an in-process SDK-MCP server, dispatching through the
  existing guardrail/grant/confirmation chain.

### Modified Capabilities
- `claude-sdk-migration` (`sdd/specs/claude-sdk-migration.spec.md`) — the
  original spec documents `tools`/`use_tools` as accepted-but-ignored on
  `ClaudeAgentClient`; that contract changes.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/clients/claude_agent.py` | modifies | `ClaudeAgentRunOptions` gains fields; `_build_options()` injects the server; `ask`/`ask_stream`/`invoke` stop discarding `tools`/`use_tools` |
| `parrot/mcp/adapter.py` | depends on | `MCPToolAdapter` reused for schema + result conversion; may need a toolkit-aware variant |
| `parrot/tools/manager.py` | depends on | `execute_tool()` is the dispatch seam; `get_all_tools()` the enumeration seam. **Do not** use `get_tools()` — see Code Context |
| `parrot/auth/confirmation.py` | depends on | HITL arrives through `ToolManager`'s configured `ConfirmationGuard`; no direct call |
| `parrot/agents/claude_code.py` | extends | the daemon target becomes the reference integration |
| `parrot/integrations/agentd/server.py` | modifies | `_handle_connection` must read `SO_PEERCRED` and carry caller identity onto the `Session` — new work, nothing exists today |
| `parrot/auth/permission.py` | depends on | `PermissionContext` / `UserSession` built from the OS user |
| `parrot/tools/compression/` | depends on | codecs applied to bridged results |
| `examples/agents/claude_code_daemon.yaml` | extends | gains a `tools:` example |
| `tests/clients/test_claude_agent.py` | extends | currently 20 passing; add bridge coverage |
| `docs/agentd.md`, `docs/tools.md` | modifies | document the new visibility and its HITL behaviour |
| `pyproject.toml` | none | no new dependency; `claude-agent-sdk` stays an optional extra |

---

## Code Context

### User-Provided Code

Working PoC executed against this repo on 2026-08-20 — it proved a parrot `@tool`
is genuinely invoked in-process by the Claude Code sub-agent. Note it had to use
the `extra_options` escape hatch because `ClaudeAgentRunOptions.mcp_servers`
does not exist:

```python
# Source: user-provided (verified PoC, ran successfully)
from parrot.tools import tool as parrot_tool
from claude_agent_sdk import tool as sdk_tool, create_sdk_mcp_server
import parrot.clients.claude_agent as ca

@parrot_tool
def inventory_level(sku: str) -> str:
    """Return the current inventory level for a SKU."""
    return f"SKU {sku}: 137 units in stock (warehouse MIA-3)"

@sdk_tool("inventory_level", "Current inventory level for a SKU", {"sku": str})
async def _bridged(args):
    return {"content": [{"type": "text", "text": str(inventory_level(args["sku"]))}]}

server = create_sdk_mcp_server(name="parrot", version="0.1.0", tools=[_bridged])

ro = ca.ClaudeAgentRunOptions(
    permission_mode="bypassPermissions",
    max_turns=4,
    allowed_tools=["mcp__parrot__inventory_level"],
    extra_options={"mcp_servers": {"parrot": server}},   # no first-class field
)
r = await ca.ClaudeAgentClient(model="claude-sonnet-4-6").ask(
    "Use your inventory tool to report the stock for SKU ABC-123.", run_options=ro
)
```

Observed output:

```
OUTPUT: SKU ABC-123 currently has **137 units in stock** at warehouse MIA-3.
tool_calls: ['ToolSearch', 'mcp__parrot__inventory_level']
parrot tool invoked with: ['ABC-123']
```

The line that causes the problem, verbatim:

```python
# Source: packages/ai-parrot/src/parrot/clients/claude_agent.py:459
del max_tokens, files, tools, use_tools  # not used by SDK
```

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/mcp/adapter.py:8
class MCPToolAdapter:
    def __init__(self, tool: AbstractTool): ...                      # line 19
    def _requires_confirmation(self) -> bool: ...                    # line 23
    def to_mcp_tool_definition(self) -> dict[str, Any]: ...          # line 27
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]: ...   # line 59
    def _toolresult_to_mcp(self, result: ToolResult) -> dict[str, Any]: ...     # line 108
# Note: to_mcp_tool_definition() injects a required `confirm: boolean` into the
# input schema when routing_meta["requires_confirmation"] is set, and rejects
# the call unless confirm=true (stdio has no HITL channel).

# From packages/ai-parrot/src/parrot/tools/manager.py:1431
class ToolManager:
    async def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        permission_context: Optional["PermissionContext"] = None,
    ) -> Any: ...
    # Pipeline order inside execute_tool: TOOL_CALL guardrails (FEAT-406)
    # -> GrantGuard (FEAT-211) -> ConfirmationGuard (FEAT-235) -> tool.execute()
    def get_tool(self, tool_name: str) -> Optional[Any]: ...          # line 1127
    def list_categories(self) -> List[str]: ...                       # line 1139
    def get_tools_by_category(self, category: str) -> List[str]: ...   # line 1143
    def list_tools(self) -> List[str]: ...                            # line 1147
    def get_all_tools(self) -> List[Union[ToolDefinition, AbstractTool]]: ...  # line 1155
    def all_tools(self) -> Generator[Any, Any, Any]: ...              # line 1159
    def get_tool_schemas(self, ...): ...                              # line 1033
    def set_confirmation_guard(self, guard: "ConfirmationGuard") -> None: ...  # line 496
    @property
    def confirmation_guard(self) -> Optional["ConfirmationGuard"]: ...  # line 514

# From packages/ai-parrot/src/parrot/tools/abstract.py:234
class AbstractTool(EventEmitterMixin, ABC):
    name: str = None                                   # line 249
    description: str = None                            # line 250
    args_schema: Type[BaseModel] = AbstractToolArgsSchema   # line 251
    routing_meta: Dict = None   # per-instance in __init__  # line 253
    async def _execute(self, **kwargs) -> Any: ...     # line 472  (abstract)
    async def execute(self, *args, **kwargs) -> ToolResult: ...  # line 778

# From packages/ai-parrot/src/parrot/tools/abstract.py:199
class ToolResult(BaseModel):
    success: bool = True
    status: str = "success"
    result: Any
    error: Optional[str] = None
    metadata: Dict[str, Any] = {}
    timestamp: str
    files: Optional[list] = []
    images: Optional[list] = []
    voice_text: Optional[str] = None
    display_data: Optional[Dict[str, Any]] = None

# From packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    confirming_tools: frozenset = frozenset()          # line 285
    async def _open(self) -> None: ...                 # line 388
    async def _close(self) -> None: ...                # line 404
    async def _ensure_open(self) -> None: ...          # line 417
    def get_tools(self, ...): ...                      # line 484
    async def get_tools_filtered(self, ...): ...       # line 574
    def get_tools_sync(self, ...): ...                 # line 594
    # line 681: methods listed in confirming_tools get
    #   tool.routing_meta["requires_confirmation"] = True

# From packages/ai-parrot/src/parrot/auth/confirmation.py:378
class ConfirmationGuard:
    def __init__(
        self,
        store: ConfirmationWindowStore,
        human_manager: Optional["HumanInteractionManager"] = None,
        config: Optional[ConfirmationConfig] = None,
    ) -> None: ...                                     # line 399
    async def confirm(
        self, *, tool: "AbstractTool", parameters: dict,
        permission_context: Optional["PermissionContext"] = None,
    ) -> ConfirmationDecision: ...                     # line 417
# Also in that module: compute_args_hash (46), ConfirmationConfig (66),
# ConfirmationDecision (88), ConfirmationWindowStore (111),
# InMemoryConfirmationWindowStore (167), render_briefing (251),
# build_form_schema (291), revalidate_edit (352).
# Fail-closed: with human_manager=None the guard DENIES (status "cancelled").

# From packages/ai-parrot/src/parrot/clients/claude_agent.py
class ClaudeAgentRunOptions(BaseModel):                # line 80
    # existing fields only: allowed_tools, disallowed_tools, permission_mode,
    # cwd, cli_path, system_prompt, max_turns, max_budget_usd, model,
    # fallback_model, add_dirs, env, extra_options, agents, setting_sources,
    # strict_mcp_config, extra_args
class ClaudeAgentClient(AbstractClient):               # line 231
    client_name: str = "claude-agent"                  # line 248
    _default_model: str = "claude-sonnet-4-6"          # line 250
    _lightweight_model: str = "claude-haiku-4-5-20251001"   # line 251
    def __init__(self, cli_path=None, cwd=None, permission_mode=None,
                 run_options=None, **kwargs) -> None: ...   # line 253
    def _build_options(self, *, run_options=None, model=None, system_prompt=None,
                       session_id=None, resume_id=None, permission_mode=None) -> Any: ...  # line 286
    async def _collect_messages(self, prompt: str, *, options: Any) -> List[Any]: ...      # line 377
    async def ask(...) -> AIMessage: ...               # line 417  (del tools at 459)
    async def ask_stream(...): ...                     # line 560  (del tools at 605)
    async def resume(self, session_id, user_input, state=None) -> AIMessage: ...  # line 682
    async def invoke(...) -> InvokeResult: ...         # line 716  (del tools at 763)
```

#### claude-agent-sdk 0.2.140 — verified signatures

```python
create_sdk_mcp_server(
    name: str,
    version: str = '1.0.0',
    tools: list[SdkMcpTool[Any]] | None = None,
) -> McpSdkServerConfig

tool(
    name: str,
    description: str,
    input_schema: type | dict[str, Any],       # a plain dict works
    annotations: mcp.types.ToolAnnotations | None = None,
) -> Callable[[Callable[[Any], Awaitable[dict[str, Any]]]], SdkMcpTool[Any]]

SdkMcpTool fields: name, description, input_schema, handler, annotations
McpSdkServerConfig = TypedDict{type: Literal['sdk'], name: str, instance: McpServer}
ClaudeAgentOptions.mcp_servers: dict[str, McpStdioServerConfig | McpSSEServerConfig
                                      | McpHttpServerConfig | McpSdkServerConfig] | str | Path
```

#### Verified Imports

```python
# All confirmed to resolve in this venv (2026-08-20):
from parrot.mcp.adapter import MCPToolAdapter
from parrot.tools.manager import ToolManager
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.toolkit import AbstractToolkit
from parrot.auth import ConfirmationGuard                       # parrot/auth/__init__.py:77
from parrot.auth.confirmation import ConfirmationDecision, InMemoryConfirmationWindowStore
from claude_agent_sdk import create_sdk_mcp_server, tool, SdkMcpTool, McpSdkServerConfig
```

#### Key Attributes & Constants
- `MCPToolAdapter.tool` → `AbstractTool` (parrot/mcp/adapter.py:20)
- `AbstractTool.routing_meta["requires_confirmation"]` → `bool`, set by the
  toolkit from `confirming_tools` (parrot/tools/toolkit.py:681)
- `AbstractToolkit.confirming_tools` → `frozenset[str]` (parrot/tools/toolkit.py:285)
- `ToolManager._tools` → `Dict[str, AbstractTool | ToolDefinition]` (private; go through the accessors)
- `ClaudeAgentClient.client_name` → `"claude-agent"` (parrot/clients/claude_agent.py:248)
- MCP tool naming convention observed live: `mcp__<server_name>__<tool_name>`
- Installed: `claude-agent-sdk 0.2.140`; `claude` CLI at `~/.local/bin/claude`

#### OS-user identity (resolves Open Question 3)

`SO_PEERCRED` on the agentd Unix-domain socket yields the caller's OS identity.
Verified live on this machine (Linux 6.11, Python 3.12, asyncio UDS server):

```python
# Source: user-provided probe, ran successfully 2026-08-20
sock = writer.get_extra_info("socket")          # asyncio.StreamWriter
raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
pid, uid, gid = struct.unpack("3i", raw)
user = pwd.getpwuid(uid).pw_name
# observed: {'pid': 882139, 'uid': 1000, 'gid': 1000, 'user': 'jesuslara'}
# uid == os.getuid() -> True
```

Target of that identity — the context `ToolManager.execute_tool()` accepts:

```python
# From packages/ai-parrot/src/parrot/auth/permission.py:81
@dataclass
class PermissionContext:
    session: UserSession                                  # line 123
    request_id: Optional[str] = None                      # line 124
    channel: Optional[str] = None                         # line 125
    trace_context: "Optional[TraceContext]" = None        # line 126
    extra: dict[str, Any] = field(default_factory=dict)   # line 127
    @property
    def user_id(self) -> str: ...      # -> self.session.user_id   (line 130)
    @property
    def tenant_id(self) -> str: ...    # -> self.session.tenant_id (line 135)
    @property
    def roles(self) -> frozenset[str]: ...                        # line 140
    def has_role(self, role: str) -> bool: ...                    # line 144

# From packages/ai-parrot/src/parrot/auth/permission.py:21
@dataclass
class UserSession:
    user_id: str
    tenant_id: str
    roles: frozenset[str]      # e.g. frozenset({'jira.manage', 'github.read'})
```

`ConfirmationGuard.confirm()` keys its window on `permission_context.user_id`
and falls back to the literal `"anonymous"` when the context is `None`
(parrot/auth/confirmation.py:417) — which is exactly what the OS-user
derivation avoids.

#### Claude Code tool-loading behaviour (resolves Open Question 4)

Measured against `claude-agent-sdk 0.2.140` by attaching an SDK-MCP server with
N probe tools and reading the session `init` message:

| parrot tools exposed | tools listed at `init` | of which `mcp__parrot__*` | `ToolSearch` present |
|---|---|---|---|
| 1 | 33 | 1 | yes |
| 25 | 57 | 25 | yes |

Conclusions, both load-bearing for this feature:

1. **Claude Code loads every exposed MCP tool eagerly.** There is no automatic
   deferral or narrowing on its side — the available set, and therefore the
   context and cost footprint, grows one-for-one with what the bridge hands
   over. Any narrowing must come from parrot.
2. **`ToolSearch` is always available** and the sub-agent reaches for it
   unprompted — it appeared in `tool_calls` even in the single-tool PoC
   (`['ToolSearch', 'mcp__parrot__inventory_level']`). It searches an
   already-loaded set, so it complements parrot-side narrowing instead of
   replacing it.

#### Compression codecs (relevant to Open Question 5)

Registered at import time, observed in the daemon logs on every boot:

```
Registered compression codec 'columnar'     -> parrot.tools.compression.codecs.columnar.ColumnarCodec
Registered compression codec 'json_compact' -> parrot.tools.compression.codecs.json_compact.JsonCompactCodec
# registry: packages/ai-parrot/src/parrot/tools/compression/protocol.py:108
```

### Does NOT Exist (Anti-Hallucination)

Verified absent by introspection on 2026-08-20 — do not assume any of these:

- ~~`ClaudeAgentRunOptions.mcp_servers`~~ — **no such field.** Today the only
  way through is `extra_options={"mcp_servers": {...}}`. This feature adds it.
- ~~`ClaudeAgentRunOptions.expose_tools`~~ / ~~`.exclude_tools`~~ /
  ~~`.expose_tool_categories`~~ / ~~`.tool_manager`~~ — none exist.
- ~~`ToolManager.to_sdk_mcp_server()`~~ / ~~`.as_mcp_server()`~~ /
  ~~`.to_mcp_server()`~~ / ~~`.sdk_mcp_server`~~ — none exist; there is no
  ToolManager→MCP factory of any name.
- ~~`parrot.mcp.adapter.MCPToolkitAdapter`~~ — only the per-tool
  `MCPToolAdapter` exists; there is no toolkit-level adapter.
- `MCPToolAdapter` is **not referenced anywhere** in
  `parrot/clients/claude_agent.py` (grep count: 0) — nor is
  `create_sdk_mcp_server`. Nothing is wired today.
- ~~`ClaudeAgentClient` honours `tools`/`use_tools`~~ — it explicitly discards
  them in `ask` (:459), `ask_stream` (:605) and `invoke` (:763).
- **`ToolManager.get_tools()` is mis-annotated.** Declared
  `-> Dict[str, Any]` at manager.py:1151 but it `return self._tools.values()`
  — a values view, not a dict. Use `get_all_tools()` (:1155) or `all_tools()`
  (:1159). Do not write `for name, tool in manager.get_tools().items()`.
- `ClaudeAgentClient.batch_ask`, `ask_to_image`, `summarize_text`,
  `translate_text`, `analyze_sentiment`, `analyze_product_review`,
  `extract_key_points` all raise `NotImplementedError` (claude_agent.py:822-882)
  — they are not bridge surfaces.
- **agentd does not capture caller identity today.** No `SO_PEERCRED`,
  `getsockopt`, `getpeername` or `ucred` anywhere under
  `parrot/integrations/agentd/` (grep: 0 hits), and `server.py` has no
  `user_id` / `permission_context` / `PermissionContext` at all. The OS-user
  derivation is **new work**, not a wiring change.
- ~~Claude Code defers or narrows MCP tools automatically~~ — it does **not**.
  All exposed tools appear in the `init` list; see Code Context.
- ~~`ClaudeAgentRunOptions.timeout`~~ / ~~`.tool_timeout`~~ — no per-tool
  timeout field exists; `max_turns` and `max_budget_usd` are the only run
  ceilings today.

---

## Parallelism Assessment

- **Internal parallelism**: moderate. Three separable slices: (1) the
  tool→`SdkMcpTool` adaptation layer, (2) the `ClaudeAgentRunOptions` /
  `_build_options` plumbing plus `allowed_tools` reconciliation, (3) the HITL
  path and its tests. Slice 1 is a new module and could progress in its own
  worktree; slices 2 and 3 both edit `claude_agent.py` and would conflict.
- **Cross-feature independence**: `claude_agent.py` and `abstract.py` were both
  touched on `dev` today (cf7547187, 575e00245) — start from current `dev`.
  `parrot/tools/manager.py` is a high-traffic file shared with the guardrails
  and grants work; `sdd/specs/hitl-confirmation.spec.md` (FEAT-235) territory is
  read-only for us (we consume `ConfirmationGuard`, we do not modify it).
  Several in-flight worktrees exist (feat-396 guardrails-infrastructure,
  feat-426 research-tools-for-agents) that may also touch `manager.py` —
  worth a conflict check before starting.
- **Recommended isolation**: `per-spec`
- **Rationale**: the centre of gravity is one file (`claude_agent.py`), so
  splitting into parallel worktrees would mostly generate merge conflicts. The
  adaptation-layer slice is small enough that sequential execution in a single
  worktree costs little and keeps the `allowed_tools` and HITL semantics
  consistent as they land.

---

## Open Questions

- [x] Which tools get exposed, and who decides? — *Owner: Jesus*: automatic —
  the whole `ToolManager`. If the agent has tools registered they are all
  exposed; no opt-in list, matching what the primary LLM sees.
- [x] What governs permission when the sub-agent calls a parrot tool? —
  *Owner: Jesus*: the parrot toolkit, as always. Tools run in-process and
  inherit their `AbstractToolkit` lifecycle, auth and HITL. The CLI's
  `permission_mode` does not apply to them.
- [x] `allowed_tools` is a whitelist — does it block `mcp__parrot__*`? —
  *Owner: Jesus*: auto-append. When the caller sets `allowed_tools`, the
  exposed parrot names are added, so the whitelist bounds native tools only.
- [x] Reuse `MCPToolAdapter`'s self-granted `confirm: bool`, or real HITL? —
  *Owner: Jesus*: real HITL through the daemon's human channel. The `confirm`
  argument is security theatre in-process, since the sub-agent sets it itself.
- [x] Does parrot's ReAct loop re-execute the sub-agent's `tool_calls`? —
  *Owner: Jesus*: no. Full delegation — the sub-agent is the loop; `tool_calls`
  are telemetry only.
- [x] Which client surfaces get the bridge? — *Owner: Jesus*: all four —
  `ask`, `ask_stream`, `resume` and `invoke`.
- [x] What is the per-call timeout for a bridged tool, and does a timeout abort
  the turn or return an error result the sub-agent can retry? — *Owner: Jesus*:
  return a **recoverable error result**. A timeout (or any tool failure) is
  reported to the sub-agent as an MCP error it can reason about and retry or
  route around; it never aborts the turn. Same treatment for a HITL denial or
  HITL timeout.
- [x] `MCPToolAdapter.to_mcp_tool_definition()` injects the `confirm` property
  for confirming tools. In-process that field is redundant (real HITL runs
  instead) and misleading to the model. Do we strip it in the SDK-MCP path,
  refactor the adapter to make it transport-conditional, or leave it? —
  *Owner: Jesus*: **strip it in the SDK-MCP path.** The stdio proxy keeps the
  `confirm` shim unchanged (it has no human channel); the in-process path
  removes the property from the schema so the model is not offered a switch
  that does nothing, and the real `ConfirmationGuard` governs instead. The
  adapter is not refactored — the SDK-MCP path post-processes the schema — so
  the stdio transport's behaviour is untouched.
- [x] Does the sub-agent need a `PermissionContext` (for `user_id`-keyed
  confirmation windows and grant checks), and if so where does it come from —
  the daemon's session, the RPC caller, or a fixed service identity? —
  *Owner: Jesus*: **derive the identity from the environment.** For a local RPC
  service the caller is the **operating-system user** of the connecting peer
  (Linux): read `SO_PEERCRED` off the Unix-domain socket to get `(pid, uid,
  gid)` and resolve the uid to a username via `pwd`. When peer credentials are
  unavailable (non-UDS transport, unresolvable uid), fall back to a **fixed
  service identity**. That `user_id` populates the `UserSession` inside the
  `PermissionContext` handed to `ToolManager.execute_tool()`, so confirmation
  windows and grants are keyed per real human rather than `"anonymous"`.
  **Verified feasible** — see Code Context → OS-user identity.
- [x] Should exposure honour the agent's existing tool *categories* so a
  `search_tools`-style narrowing applies to the sub-agent too, or is the flat
  full set correct? — *Owner: Jesus*: **respect the narrowing** — but the
  decision hinged on what Claude Code does on its own, and it was measured:
  **Claude Code does NOT narrow.** Every exposed MCP tool is listed eagerly in
  the session `init` message (25 exposed → 25 listed), so the available set
  grows linearly with what we hand over. Claude Code does ship a native
  `ToolSearch` tool (always present, and used spontaneously even with a single
  parrot tool exposed), but that is *search over an already-loaded set*, not a
  reduction of it. So parrot-side narrowing is real context/cost control, not
  redundant work, and it composes with `ToolSearch` rather than duplicating it.
  See Code Context → Claude Code tool-loading behaviour.
- [x] Large tool results cross into the sub-agent's context and are billed
  there. Do the existing compression codecs apply on this path, and do we need
  a size ceiling? — *Owner: Jesus*: **no size ceiling; apply the compression
  codecs.** Results are not truncated — a hard cap would silently lose data the
  sub-agent needs — but the existing `parrot.tools.compression` codecs
  (`columnar`, `json_compact`, registered at import time) should run on the
  bridged result before it crosses into the sub-agent's context.

### Follow-up questions raised by these answers
- [ ] Which compression codec is selected for a bridged result, and on what
  signal — result shape (tabular → `columnar`), size threshold, or per-tool
  declaration? — *Owner: Jesus*
- [ ] What is the fixed service identity's `user_id` / `tenant_id` / `roles`
  when `SO_PEERCRED` is unavailable, and should a `ConfirmationGuard` window
  ever be honoured for it (or must the service identity always re-confirm)? —
  *Owner: Jesus*
- [ ] Capturing `SO_PEERCRED` means touching `agentd/server.py`
  (`_handle_connection`) to carry caller identity onto the `Session` — is that
  in scope for this feature, or a prerequisite feature of its own? —
  *Owner: Jesus*
- [ ] Which narrowing signal drives exposure — the agent's tool categories,
  an explicit per-agent budget (N tools max), or the same `search_tools`
  relevance ranking the primary LLM uses? — *Owner: Jesus*
