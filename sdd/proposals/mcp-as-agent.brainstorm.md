---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Expose an AI-Parrot Agent as an MCP Server

**Date**: 2026-08-30
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option D

**Supersedes / folds in**: `sdd/proposals/sdd-brainstorm_agent-methods-as-mcp-tools.md`
(the untracked working draft, "Agent Methods as MCP Tools", D1–D11). Several of its
⚠️ VERIFY anchors were checked against the tree here and **three of its premises turned
out to be wrong** — see § Code Context.

**Depends on**: remote branch `claude/mcp-http-streamable-transport-bptepy`
(2 commits over `ab38e64ff`) merged to `dev` first — see § Constraints.

---

## Problem Statement

An AI-Parrot agent (`AbstractBot` / `BasicAgent`) encapsulates toolkits, knowledge
bases, credential brokers and corporate flows. Today that work is reachable only
through AI-Parrot's own HTTP chat API, through A2A (`A2AServer`), or by another agent
via `BasicAgent.as_tool()`. There is **no way to point an MCP client at an agent**.

What exists instead is *tool*-level MCP exposure: `ParrotMCPServer` mounts a flat,
process-global set of `AbstractTool`s (from `MCP_STARTED_TOOLS`) on one endpoint. That
surface has no notion of an agent, no per-user identity, and no per-principal
authorization — every caller sees and can call the same static tool list.

The gap this feature closes:

1. **Agent-scoped MCP endpoints.** A named agent publishes its own MCP surface —
   its `@mcp_tool`-decorated methods, its registered tools, and its metadata as MCP
   resources — so a user can add "the Finance agent" to Claude as a connector.
2. **Per-user identity.** Claude Web speaks OAuth 2.1 only; Claude Code / Desktop /
   API can also send an API key. Both must resolve to one `PermissionContext`.
3. **Per-principal authorization.** `tools/list` must be filtered by the caller's
   policy and `tools/call` re-verified — Claude must never see a tool the principal
   cannot invoke.
4. **Long-running work.** Agent flows/crews exceed the 300 s connector tool-call
   ceiling; they need a durable handle, not a blocking call.

**Who is affected**: end users consuming corporate agents from Claude Web/Code;
platform engineers mounting agents; agent authors who must declare what is safe to
expose.

## Constraints & Requirements

- **The Streamable HTTP transport is a prerequisite, not part of this feature.**
  `claude/mcp-http-streamable-transport-bptepy` must merge to `dev` first; this
  feature bases on `dev` and builds the agent layer on top of `StreamableHttpMCPServer`.
- **Authentication is delegated to navigator-auth as an external Authorization
  Server.** AI-Parrot is a resource server: it validates the bearer and resolves a
  principal. It does **not** grow its own production AS. The in-repo
  `OAuthAuthorizationServer` (`AuthMethod.OAUTH2_INTERNAL`) stays as a dev/test
  convenience only — its `/authorize` auto-approves (`oauth_server.py:638`), which is
  not acceptable in production.
- **PBAC is enforced from day one**, at both `tools/list` (filter) and `tools/call`
  (re-verify). Deny-by-default, consistent with `setup_pbac()`'s `PolicyEffect.DENY`.
- **`ask()` is NOT exposed as an MCP tool.** The LLM stays out of the loop by
  default; the injection surface a free-text `question` opens is out of scope.
- Only *fast* methods answer inline. Anything that can exceed ~300 s uses the job
  handle pattern (`start_*` → `job_id`, `*_status`, `*_result`).
- Tool responses must stay under the ~30 000-token custom-connector response
  ceiling — enforced by the adapter, not left to method authors.
- The decorator must be importable from core `ai-parrot` with **no extras
  installed**, so an agent can declare its MCP surface without depending on
  `ai-parrot-server`.
- Multi-tenant: the per-call runtime binds to `(tenant_id, principal)`.
- No regression to the existing tool-level MCP server, its transports, or A2A.

---

## Options Explored

### Option A: Parallel `AgentMethodAdapter` + `MCPAgentMount`

The design of the superseded draft (its D1/D2). A new `@mcp_tool` decorator populates
a **separate per-agent registry** of exposable methods. A new `AgentMethodAdapter`
converts a registry entry into an MCP tool definition and executes it — a sibling of
`MCPToolAdapter`, not a user of it. `MCPAgentMount(agents=[...])` registers
`/mcp/agents/{name}` per agent plus an optional aggregate `/mcp` with
`{agent}__{tool}` prefixes.

✅ **Pros:**
- Clean conceptual split: "tools" and "agent methods" are different things with
  different lifecycles.
- The method registry can carry MCP-specific metadata (`scope`, annotations,
  `ResultPolicy`) without polluting `AbstractTool`.
- No risk of an agent method accidentally becoming LLM-callable inside the agent
  itself.

❌ **Cons:**
- Duplicates machinery that already works: schema extraction, confirmation guard,
  `ToolResult` → MCP content conversion, `allowed_tools`/`blocked_tools` filtering.
- Two registration paths into one `tools/list` means two places to get PBAC,
  size policy and audit right.
- The agent's *own* tools (a Round-1 requirement) still need the existing adapter —
  so both adapters ship anyway.
- The A2A `AgentCard` cannot see decorated methods without a third bridge.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` >=2 | `args_schema` / `returns` models | already core |
| `aiohttp` | transport | already core |
| `navigator-auth` >0.20.9 | token validation + ABAC PDP | already a core dep |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py` — transport
- `packages/ai-parrot-server/src/parrot/mcp/parrot_server.py` — parent-app mounting pattern

---

### Option B: Extend `ParrotMCPServer` to accept agents

No new server class and no new endpoint topology. `ParrotMCPServer.setup()` grows an
`agents=[...]` parameter; each agent's exposable callables are registered into the
**existing single MCP server** under prefixed names (`finance__forecast`). PBAC and
identity are handled by a middleware in front of the one endpoint.

✅ **Pros:**
- Smallest diff by far; one endpoint to secure, one connector to configure.
- Reuses `MCPToolAdapter` and the whole existing registration path untouched.
- `notifications/tools/list_changed` semantics stay trivial (one surface).

❌ **Cons:**
- **No per-agent isolation** — rejected in Round 2. One compromised or misconfigured
  agent widens the blast radius of the single endpoint.
- The canonical PBAC resource degrades to a name-prefix convention; a tool name
  containing `__` breaks resource resolution.
- Users cannot subscribe to just one agent; Claude's per-connector UX is lost.
- Cannot vary auth method, allowed origins, or session TTL per agent.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | transport | already core |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/mcp/parrot_server.py:76-200` — transport config + mount
- `packages/ai-parrot/src/parrot/mcp/adapter.py:8` — `MCPToolAdapter` unchanged

---

### Option C: Delegate the server to the official `mcp` Python SDK (FastMCP)

Drop the hand-rolled server for the agent surface. Each agent gets a FastMCP server
instance whose ASGI app is mounted next to (or inside) the aiohttp app; decorated
agent methods are registered with the SDK's own `@server.tool()`. Conformance,
session handling and future protocol revisions become the SDK's problem.

✅ **Pros:**
- Spec conformance for free, including revisions AI-Parrot has not implemented
  (elicitation, sampling, structured content, completions).
- The branch already anticipates the SDK as a test dependency — it added the
  `requires_mcp_sdk` pytest marker (`packages/ai-parrot-server/pyproject.toml`),
  so interop tests can pin real client behavior.
- Zero maintenance of transport minutiae (`Mcp-Session-Id`, `Last-Event-ID` replay,
  `MCP-Protocol-Version` negotiation).

❌ **Cons:**
- **Two MCP server stacks in one repo.** The tool-level server, all six existing
  transports (stdio/http/sse/unix/quic/websocket) and their auth stay hand-rolled;
  agents would behave differently from tools.
- FastMCP is ASGI/Starlette-shaped; AI-Parrot's server is aiohttp end-to-end.
  Mounting means an ASGI bridge or a second port — both hurt the "register routes in
  the existing app" model that `HttpMCPServer(parent_app=...)` is built around.
- The existing auth stack (`_authenticate_request`, `AuthMethod`, `mcp_user`) and the
  PBAC resolver would have to be re-implemented against SDK middleware.
- Throws away the work just done on the streamable branch.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `mcp` (official SDK) | server + FastMCP | new runtime dep; currently only a test marker |
| `starlette` / `uvicorn` | ASGI host | new; conflicts with the aiohttp-only rule |

🔗 **Existing Code to Reuse:**
- Little beyond the agent itself; that is the point and the problem.

---

### Option D: Method reification — one tool abstraction, one adapter *(recommended)*

The unconventional one: **do not build a parallel registry at all.**

`@mcp_tool` does not create a new kind of thing — it *marks* a bound agent method so
that, at agent configure time, it is **reified into a real `AbstractTool`** (an
`AgentMethodTool` wrapper whose `name`, `description`, `args_schema` come from the
decorator and whose `_execute()` calls the bound method). From that instant the method
is indistinguishable from any other tool to everything downstream:

- `MCPToolAdapter` (`adapter.py:8`) converts it — schema extraction, the
  `requires_confirmation` guard, `ToolResult` → MCP content — with **zero new code**.
- `RemoteMCPServerBase.register_tool()` (`transports/base.py:65`) applies
  `allowed_tools` / `blocked_tools` to it like any tool.
- `A2AServer._build_skills_from_tools()` (`a2a/server.py:400`) already walks
  `tool_manager` — so the same declaration surfaces in the `AgentCard` for free
  (settling the old draft's OQ7 without extra machinery).
- The agent's **own** tools are already tools — the Round-1 "expose the agent's own
  tools" requirement needs no second code path.

A thin `AgentMCPMount` then builds **one `StreamableHttpMCPServer` per agent**,
mounted at `/mcp/agents/{name}` into the existing aiohttp app (the exact pattern
`A2AServer.setup()` uses at `a2a/server.py:231`), plus an optional aggregate `/mcp`
publishing `{agent}__{tool}`. Both name forms resolve to the same canonical PBAC
resource `mcp:agent:{name}:tool:{tool}` — the aggregate is a naming convenience,
never an authorization path of its own.

Identity and policy are a **decorator layer around the adapter**, not a fork of the
server: a `PrincipalGuard` wraps each `MCPToolAdapter`, and the mount overrides
`handle_tools_list` / `handle_tools_call` to consult the PBAC resolver. The resolved
`PermissionContext` is published on the **existing** `_pctx_var` contextvar
(`auth/context.py:33`) — the same one `DatasetManager` and `DatabaseQueryTool` already
read — so every guard downstream of the agent method inherits the MCP caller's
identity with no signature changes anywhere.

✅ **Pros:**
- Maximum reuse: no second adapter, no second registry, no second filtering path.
- One place to enforce PBAC, size policy and audit (the guard around the adapter).
- Per-agent endpoints and isolation (Round 2) with the aggregate as sugar.
- Agent methods become visible to A2A and to the agent's own tool surface for free.
- Identity propagation reuses machinery that already exists and is already trusted.

❌ **Cons:**
- Reification means a decorated method **could** also become LLM-callable inside its
  own agent if registered into the agent's `ToolManager` — must be explicitly
  suppressed (exposure surface is a property of the tool, not an accident).
- MCP-specific metadata (`scope`, MCP annotations, `ResultPolicy`) has to ride on
  `AbstractTool` (e.g. via `routing_meta`, as `requires_confirmation` already does)
  rather than in a dedicated model — slightly less tidy.
- `AgentMethodTool` must not drag the agent into tool-serialization paths (weak
  reference / bound-method care).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` >=2 | mandatory `args_schema` / `returns` | already core |
| `aiohttp` | transport, parent-app mount | already core |
| `navigator-auth` >0.20.9 | RFC 7662 introspection + ABAC PDP | already a core dep (`packages/ai-parrot/pyproject.toml:83`) |
| `redis.asyncio` | job handles via `SuspendedExecutionStore` | already used by HITL |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/mcp/adapter.py:8` — `MCPToolAdapter`, unchanged
- `packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py:125` — transport
- `packages/ai-parrot-server/src/parrot/a2a/server.py:231` — per-agent mount precedent
- `packages/ai-parrot/src/parrot/auth/resolver.py:247` — `PBACPermissionResolver`
- `packages/ai-parrot/src/parrot/auth/context.py:33` — `_pctx_var`
- `packages/ai-parrot-server/src/parrot/human/suspended_store.py:64` — job handles

---

## Recommendation

**Option D**, with Option A's endpoint topology (per-agent + optional aggregate) and
Option C's SDK used *only* as an interop test client.

The decisive argument is that this repo already contains every piece except the
declaration and the mount. `MCPToolAdapter` already does schema extraction, the
destructive-operation confirmation guard, and `ToolResult` conversion.
`RemoteMCPServerBase` already does auth dispatch across five methods and static tool
filtering. `A2AServer` already proves the per-agent, parent-app mount pattern against
the same aiohttp app. `PBACPermissionResolver` + `setup_pbac()` already provide
deny-by-default policy evaluation, and `_pctx_var` already carries a
`PermissionContext` across await boundaries into the data-plane guards.
Option A spends High effort rebuilding parallel versions of the first two; Option C
spends High effort replacing all of them with a stack that does not speak aiohttp.

What Option D trades away is conceptual tidiness. A decorated agent method becomes an
`AbstractTool`, so MCP-specific metadata rides on `routing_meta` instead of a purpose-
built `MCPToolSpec`, and the spec must state explicitly that reification does **not**
imply LLM-callability inside the owning agent. That is a real cost, and it is the one
place the spec has to be precise. In exchange, `tools/list`, PBAC, audit, size policy
and the A2A `AgentCard` all have exactly one implementation each.

Option B is rejected on isolation grounds (explicitly, in Round 2). Option C is
rejected as a *server*, but its SDK is adopted as a **test client**: the branch's
`requires_mcp_sdk` marker should gate an interop test that drives the agent endpoint
with the reference implementation, which is the cheapest possible conformance signal.

---

## Feature Description

### User-Facing Behavior

**For the agent author.** Decorate the methods that should be callable from outside:

- the decorator requires `name`, `args_schema` (Pydantic), `returns` (Pydantic) and
  `scope`; registration **fails loudly** if any is missing — no schema inference in
  v1;
- having at least one decorated method **is** the opt-in (Round 3): no
  `expose_as_mcp` flag, no server-side allowlist to keep in sync;
- long-running work is declared as a `start_*` / `*_status` / `*_result` trio; the
  decorator does not make a blocking method safe.

**For the platform engineer.** Agents already loaded by `BotManager` gain MCP
endpoints when the mount is enabled. Each exposed agent serves:

- `POST/GET/DELETE /mcp/agents/{name}` — Streamable HTTP,
- `GET /mcp/agents/{name}/info` — human-readable surface summary,
- optionally, an aggregate `/mcp` with `{agent}__{tool}` names.

**For the end user.** They add `https://<host>/mcp/agents/finance` as a Claude custom
connector, complete an OAuth login against navigator-auth, and see exactly the tools
their policy allows — plus the agent's description, capability summary and knowledge-
base descriptors as MCP **resources** (Round 1), readable via `resources/read`.

### Internal Behavior

1. **Declaration → reification.** At `configure()`, the agent scans itself for
   decorated methods and reifies each into an `AgentMethodTool` bound to that
   instance, recorded in an *exposure set* distinct from the LLM tool set.
2. **Mount.** `AgentMCPMount` builds one `StreamableHttpMCPServer` per exposed agent
   against the existing `web.Application`, registering the reified methods plus the
   agent's own tools (minus internal plumbing, as `A2AServer._INTERNAL_TOOL_NAMES`
   already does) and the agent's metadata resources.
3. **Authentication.** `_authenticate_request()` resolves the bearer. Claude Web
   presents a navigator-auth OAuth 2.1 access token, validated by RFC 7662
   introspection (`AuthMethod.OAUTH2_EXTERNAL`); Claude Code/Desktop present an API
   key (`AuthMethod.API_KEY`). Both land in `request["mcp_user"]`; a single
   principal-resolution step converts either into a `PermissionContext`
   (`user_id`, `tenant_id`, `roles`).
4. **Authorization.** `tools/list` asks the PBAC resolver per candidate tool against
   `mcp:agent:{name}:tool:{tool}` and returns only permitted entries. `tools/call`
   re-evaluates the same resource — the list is never trusted as an authorization
   record.
5. **Execution.** The guard publishes the `PermissionContext` on `_pctx_var`, binds a
   runtime keyed by `(tenant_id, principal)`, and invokes the adapter. The result
   passes through the size policy before serialization.
6. **Long-running.** A `start_*` method persists a job record (Redis, via the HITL
   `SuspendedExecutionStore` semantics: caller-provided TTL, tombstone on delete) and
   returns a `job_id` immediately. `*_status` / `*_result` project a manifest — never
   raw payloads.
7. **Audit.** Every `tools/call` records principal, agent, tool, argument hash,
   decision and duration in the `AuditLedger`.

### Edge Cases & Error Handling

- **Decorator misuse** — missing `args_schema`/`returns`, a name colliding with an
  existing tool, or a non-async method: fail at configure time with the agent name and
  method in the message. Never silently skip.
- **Unauthenticated / expired token** — 401 with a `WWW-Authenticate` header that
  points at the protected-resource metadata, so Claude can re-discover the AS. (The
  header today carries only `Bearer realm="mcp"`; see § Does NOT Exist.)
- **Authenticated but unauthorized** — the tool is absent from `tools/list`; a direct
  `tools/call` returns a clean MCP error, never a stack trace, and is audited as a
  denial.
- **Revoked principal** — access ends within the access-token TTL. A `tools/call`
  after revocation fails on introspection, not on policy.
- **Aggregate-endpoint name collisions** — two agents exposing the same tool name are
  disambiguated by the `{agent}__` prefix; an agent whose own name contains the
  separator is rejected at mount time.
- **Oversized result** — the size policy truncates or paginates deterministically and
  the response says so explicitly, so the model does not silently reason over a
  clipped list.
- **Long-running method that blocks anyway** — a hard per-call deadline below the
  300 s client ceiling turns it into a clean timeout error naming the method.
- **Disconnect mid-call** — the branch's `SessionEventStore` buffers the response and
  replays it on `Last-Event-ID` reconnect within the session TTL. Beyond that window,
  the job handle is the only durable path — which is exactly why long-running work
  must use it.
- **Multi-worker deployment** — sessions and the event buffer are in-memory
  per-process (`streamable_http.py:77`). With more than one worker, a session can land
  on a process that does not know it. v1 must either pin to one worker or document
  this loudly; a shared store is a follow-up.
- **Agent hot-reload** — `BotManager.reload_agent()` rebuilds the instance; reified
  methods are bound to the *old* one. The mount must re-reify on reload or hold the
  agent by name, not by reference.

---

## Capabilities

### New Capabilities
- `mcp-as-agent`: publish a named agent as an MCP server (Streamable HTTP) exposing
  its decorated methods, its own tools, and its metadata as resources.
- `mcp-tool-decorator`: transport-agnostic declaration of an agent method as an
  externally callable operation, with mandatory Pydantic input/output schemas.
- `mcp-principal-authz`: per-principal `tools/list` filtering and `tools/call`
  re-verification against a canonical PBAC resource, with audit.
- `mcp-job-handles`: durable `start_*` / `*_status` / `*_result` pattern for agent
  work exceeding the client tool-call ceiling.

### Modified Capabilities
- The MCP server stack (`parrot.mcp`) — gains an agent-aware mount alongside the
  existing tool-level `ParrotMCPServer`; existing transports and behavior unchanged.
- A2A `AgentCard` skills — decorated methods become visible as skills via the
  existing `_build_skills_from_tools()` walk (a consequence of reification, not a
  separate change).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/` (core) | extends | new decorator + `AgentMethodTool`; importable with no extras |
| `packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py` | depends on | prerequisite branch; agent mount subclasses/instantiates it |
| `packages/ai-parrot-server/src/parrot/mcp/parrot_server.py` | modifies | agent mount registered alongside the tool-level server; must not double-claim `base_path` |
| `packages/ai-parrot-server/src/parrot/mcp/transports/base.py` | extends | principal resolution from `mcp_user`; PRM-aware 401 |
| `packages/ai-parrot-server/src/parrot/mcp/config.py` | extends | agent-mount settings (exposed agents, aggregate on/off, size caps) |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | modifies | `setup()` wires the agent mount from loaded bots |
| `packages/ai-parrot/src/parrot/auth/resolver.py` / `pbac.py` | depends on | policy decisions per MCP resource |
| `packages/ai-parrot/src/parrot/auth/context.py` | depends on | `_pctx_var` carries the MCP principal |
| `packages/ai-parrot-server/src/parrot/human/suspended_store.py` | depends on | job-handle persistence semantics |
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | depends on | mount pattern precedent; inherits decorated methods as skills |
| navigator-auth (external) | depends on | OAuth 2.1 AS + introspection + ABAC policies |
| Deployment | modifies | endpoint must be publicly routable for Claude Web; single-worker caveat |

**Breaking changes**: none expected. The tool-level MCP server, all existing
transports and A2A keep their current behavior.

---

## Code Context

### User-Provided Code

The user supplied the prior draft
`sdd/proposals/sdd-brainstorm_agent-methods-as-mcp-tools.md` (untracked) and the remote
branch `claude/mcp-http-streamable-transport-bptepy`. No inline snippets.

**Branch contents** (`git diff ab38e64ff origin/claude/mcp-http-streamable-transport-bptepy`,
11 files, +1369/−23):

```
A packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py   (591)
A packages/ai-parrot-server/tests/mcp/test_streamable_http.py              (499)
A packages/ai-parrot-server/tests/mcp/test_streamable_http_interop.py       (77)
M packages/ai-parrot/src/parrot/mcp/server_base.py          (+ protocol negotiation)
M packages/ai-parrot-server/src/parrot/mcp/config.py        (+ allowed_origins, session_ttl, event_buffer_size)
M packages/ai-parrot-server/src/parrot/mcp/server.py        (+ StreamableHttpMCPServer, create_streamable_http_mcp_server)
M packages/ai-parrot-server/src/parrot/mcp/parrot_server.py (+ base_path collision guard)
M packages/ai-parrot-server/src/parrot/mcp/transports/http.py (+ _register_routes hook)
M packages/ai-parrot-server/pyproject.toml                  (+ requires_mcp_sdk marker)
```

### Verified Codebase References

#### Classes & Signatures

```python
# packages/ai-parrot/src/parrot/mcp/adapter.py:8
class MCPToolAdapter:
    def __init__(self, tool: AbstractTool): ...              # :19
    def to_mcp_tool_definition(self) -> dict[str, Any]: ...   # :27
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]: ...  # :59
    # :10-18 docstring: honors routing_meta["requires_confirmation"] by injecting a
    # required `confirm` boolean into inputSchema and rejecting unconfirmed calls.

# packages/ai-parrot/src/parrot/mcp/server_base.py:27
class MCPServerBase(ABC):
    tools: dict[str, MCPToolAdapter]
    def register_tool(self, tool: AbstractTool): ...                              # :38
    async def handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]   # :50
    async def handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]   # :68
    async def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]   # :79

# packages/ai-parrot-server/src/parrot/mcp/transports/base.py:18
class RemoteMCPServerBase(_CoreMCPServerBase):
    oauth_server: OAuthAuthorizationServer | None
    api_key_store: APIKeyStore | None
    external_oauth: ExternalOAuthValidator | None
    def register_resource(self, resource: MCPResource, read_handler): ...          # :49
    def register_tool(self, tool: AbstractTool): ...   # :65 — allowed/blocked filter
    async def handle_resources_list(self, params) -> dict[str, Any]: ...           # :86
    async def handle_resources_read(self, params) -> dict[str, Any]: ...           # :93
    async def _authenticate_request(self, request) -> web.Response | None: ...     # :188
    def _unauthorized_response(self, message, www_authenticate='Bearer realm="mcp"') # :305

# packages/ai-parrot-server/src/parrot/mcp/transports/http.py:22
class HttpMCPServer(OAuthRoutesMixin, RemoteMCPServerBase):
    def __init__(self, config: MCPServerConfig, parent_app: Optional[web.Application] = None)  # :25
    def _register_routes(self, router, base_route: str) -> None   # :90  (added by the branch)

# ON BRANCH — packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py:125
class StreamableHttpMCPServer(HttpMCPServer):
    def _register_routes(self, router, base_route) -> None        # :151  POST/GET/DELETE + /info
    async def _handle_streamable_post(self, request)              # :290  calls _authenticate_request at :294
    async def _handle_streamable_get(self, request)               # :473  auth at :477; Last-Event-ID replay
    async def _handle_streamable_delete(self, request)            # :570  auth at :574
    def _check_origin(self, request)                              # :233  DNS-rebinding protection
    def _check_protocol_header(self, ...)                         # :256  MCP-Protocol-Version
class McpStreamSession:                                           # :111  has `user: Optional[Any]`
class SessionEventStore:                                          # :77   in-memory ring buffer
# :372 — session is created with user=request.get("mcp_user")

# packages/ai-parrot-server/src/parrot/a2a/server.py:86  — PER-AGENT MOUNT PRECEDENT
class A2AServer:
    def __init__(self, agent: "AbstractBot", *, base_path: str = "/a2a",
                 suspended_store: Optional[Any] = None,
                 audit_ledger: Optional[Any] = None, ...)                          # :120
    def setup(self, ...)                          # :231 registers routes on the aiohttp app
    def get_agent_card(self) -> AgentCard         # :334
    _INTERNAL_TOOL_NAMES = frozenset({"to_json"}) # :398
    def _build_skills_from_tools(self) -> List[AgentSkill]   # :400 walks agent.tool_manager
    def _tool_to_skill(self, tool) -> Optional[AgentSkill]   # :425 uses args_schema.model_json_schema()

# packages/ai-parrot/src/parrot/auth/permission.py
class UserSession:                                # :21  user_id, tenant_id, roles: frozenset[str], metadata
class PermissionContext:                          # :81  session, request_id, channel, trace_context, extra
def build_principal_context(principal: str, *, channel: str,
                            tenant_id: Optional[str] = None,
                            roles: Optional[frozenset[str]] = None) -> PermissionContext  # :166

# packages/ai-parrot/src/parrot/auth/pbac.py:67
def setup_pbac(app, policy_dir="policies", cache_ttl=30,
               default_effect=None) -> tuple[PDP|None, PolicyEvaluator|None, Guardian|None]
# deny-by-default (PolicyEffect.DENY); fail-closed when PARROT_SAAS_MODE=true

# packages/ai-parrot/src/parrot/auth/resolver.py:247
class PBACPermissionResolver(AbstractPermissionResolver): ...   # __init__ :275

# packages/ai-parrot-server/src/parrot/human/suspended_store.py:64
class SuspendedExecutionStore:
    def __init__(self, redis: Any) -> None                       # :87
    async def save(self, record: SuspendedExecution, ttl: int) -> None
    # key format: hitl:suspended:{interaction_id}; delete leaves hitl:interaction:{id} intact

# packages/ai-parrot-server/src/parrot/mcp/oauth_server.py
class APIKeyStore:               # :41   issue_key :53, validate_key :119, revoke_key :142
class ExternalOAuthValidator:    # :211  RFC 7662 introspection
    async def validate_token(self, token: str) -> Optional[Dict[str, Any]]   # :244
class OAuthAuthorizationServer:  # :374  register_routes :393
class OAuthRoutesMixin:          # :569  _oauth_paths :576, _add_oauth_routes :586
    async def _handle_discovery  # :593  RFC 8414 metadata
    async def _handle_registration # :609 RFC 7591 DCR
    async def _handle_authorize  # :638  *** auto-approves — dev/test only ***
```

#### Verified Imports

```python
from parrot.mcp.adapter import MCPToolAdapter                    # core, no extras
from parrot.mcp.server_base import (
    MCPServerBase, LocalServerConfig,
    SUPPORTED_PROTOCOL_VERSIONS, negotiate_protocol_version,      # last two: branch only
)
from parrot.mcp.config import AuthMethod, MCPServerConfig         # ai-parrot-server
from parrot.mcp.transports.base import RemoteMCPServerBase
from parrot.mcp.transports.http import HttpMCPServer
from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer   # branch only
from parrot.mcp.server import create_streamable_http_mcp_server             # branch only
from parrot.mcp.oauth_server import APIKeyStore, ExternalOAuthValidator
from parrot.auth.context import UserContext, _pctx_var
from parrot.auth.permission import UserSession, PermissionContext, build_principal_context
from parrot.auth.pbac import setup_pbac
from parrot.auth.resolver import PBACPermissionResolver
from parrot.human.suspended_store import SuspendedExecutionStore  # ai-parrot-server
from parrot.tools.abstract import AbstractTool, ToolResult
```

#### Key Attributes & Constants

- `AuthMethod` members → `NONE | API_KEY | OAUTH2_INTERNAL | OAUTH2_EXTERNAL | BEARER`
  (`mcp/config.py:6-12`). `BEARER` resolves a navigator-auth session via
  `request.app['auth'].get_session(request)` (`transports/base.py:277`).
- `request["mcp_user"]` → the authenticated principal dict, set by every auth path:
  API key `base.py:231`, external OAuth `base.py:261` (`{"user_id", "scopes",
  "token_info"}`), navigator-auth bearer `base.py:286` (raw userdata).
- `MCPServerConfig.allowed_tools` / `.blocked_tools` → static name filters applied in
  `RemoteMCPServerBase.register_tool` (`base.py:65`) — process-wide, **not**
  per-principal.
- `MCPServerConfig.base_path` → `"/mcp"` default (`config.py:58`).
- Branch-added config: `allowed_origins`, `session_ttl` (3600), `event_buffer_size`
  (1000).
- `SUPPORTED_PROTOCOL_VERSIONS` → `("2024-11-05", "2025-03-26", "2025-06-18")`
  (branch, `server_base.py:17`); `ASSUMED_HEADER_VERSION = "2025-03-26"`
  (`streamable_http.py:47`); `KEEP_ALIVE_INTERVAL = 15.0` (`:43`).
- `AbstractBot.tool_manager: ToolManager` (`bots/abstract.py:386`);
  `ToolManager.get_tool` (`tools/manager.py:1231`), `.list_tools`
  (`:1251`), `.tool_count` (`:2053`).
- `BasicAgent.agent_tools` property (`bots/agent.py:337`); `as_tool()` (`:961`);
  `register_as_tool()` (`:1002`) — agent-as-tool already exists and is NOT this feature.
- `BotManager.get_bots() -> Dict[str, AbstractBot]` (`manager/manager.py:1146`);
  `BotManager.setup(app)` (`:1965`); `reload_agent()` (`:856`).
- `AbstractTool.name` (`tools/abstract.py:296`), `.args_schema: Type[BaseModel]`
  (`:298`); `routing_meta["requires_confirmation"]` is the existing precedent for
  per-tool MCP metadata.
- `navigator-auth>0.20.9` is a **core** dependency (`packages/ai-parrot/pyproject.toml:83`).
- Two `AuditLedger` classes exist: `parrot/auth/audit.py:65` (in-memory,
  `record()`/`flush()`) and `parrot/security/audit_ledger.py:296`. The spec must pick
  one — `A2AServer.__init__` documents the `parrot.security.audit_ledger` one.

### Does NOT Exist (Anti-Hallucination)

Verified absent from the tree (`dev` and the branch):

- ~~`@mcp_tool` decorator~~ — no definition or usage anywhere (`grep -rn "def mcp_tool\|@mcp_tool" packages/` → empty).
- ~~`AgentMethodAdapter`, `MCPAgentMount`, `ResultPolicy`, `JobHandle`, `resolve_principal()`~~ — none exist.
- ~~`parrot.interfaces.mcp`~~ — `parrot/interfaces/` exists but contains **no** `mcp.py`.
- ~~`MCPToolSpec`, `MCPAgentManifest`, `Principal`~~ — the prior draft's Pydantic
  contracts. Do not import them; `PermissionContext` already plays the `Principal` role.
- ~~`/.well-known/oauth-protected-resource`~~ (RFC 9728) — **not implemented**. Only
  `/.well-known/oauth-authorization-server` exists (`oauth_server.py:394`, `:580`;
  `parrot_server.py:143`). Claude's connector discovery expects the PRM document.
- ~~`resource_metadata=` in the 401 `WWW-Authenticate` header~~ — the header is
  hardcoded `'Bearer realm="mcp"'` (`transports/base.py:305-314`).
- ~~Per-principal `tools/list`~~ — `handle_tools_list(params)` (`server_base.py:68`)
  takes no principal and returns every registered adapter. `allowed_tools`/
  `blocked_tools` are static config, not policy.
- ~~PBAC enforcement inside any MCP transport~~ — no MCP module imports
  `parrot.auth.pbac` or `PBACPermissionResolver`.
- ~~A shared/Redis session store for Streamable HTTP~~ — `SessionEventStore`
  (`streamable_http.py:77`) is an in-memory `deque`, per process. The module docstring
  states a shared store is "a documented follow-up".
- ~~A production-grade OAuth AS in ai-parrot~~ — `OAuthRoutesMixin._handle_authorize`
  (`oauth_server.py:638`) auto-approves; no refresh-token rotation, no consent, no
  user gate. **The prior draft was wrong that no AS exists — but it is a dev fixture,
  not a production AS.**
- ~~`EpisodicMemoryStore` in `parrot.memory` root~~ — it is at
  `parrot/memory/episodic/store.py:57`.
- ~~`MCPAgent` as a distinct class~~ — `parrot/bots/mcp.py:11` is a deprecated alias
  of `BasicAgent` (MCP *client* capability, the opposite direction).

---

## Parallelism Assessment

- **Internal parallelism**: real, along three seams that touch disjoint files —
  (1) the decorator + `AgentMethodTool` reification in **core** `parrot/mcp/`;
  (2) the mount + resources + endpoint topology in **ai-parrot-server**
  `parrot/mcp/`; (3) the identity/PBAC/audit guard, which straddles
  `parrot/auth/` and the mount. (1) is a hard dependency of (2) and (3), so the shape
  is one sequential head followed by a two-way fan-out, not three independent lanes.
  The job-handle work (4) depends only on (1) and can run alongside (2)/(3).
- **Cross-feature independence**: the prerequisite branch touches
  `mcp/config.py`, `mcp/server.py`, `mcp/parrot_server.py`,
  `transports/http.py` and core `mcp/server_base.py` — **the same files this feature
  extends**. Merging it to `dev` first is what makes the two independent; basing this
  feature on `dev` before that merge would guarantee conflicts.
  FEAT-476 (agentchat-migration) and FEAT-475 (ui-agent-management) are in flight
  around agent management; FEAT-475 touches agent definitions and the management UI,
  which this feature deliberately does not (opt-in is implicit, by decoration).
  `manager/manager.py:setup()` is the one plausible collision point with FEAT-475 —
  a single-line wiring change, worth checking at spec time.
- **Recommended isolation**: `per-spec`.
- **Rationale**: the three seams share the mount's contract and the tool-exposure
  model, and two of them edit the same handful of files in `parrot/mcp/`. Sequential
  tasks in one worktree cost little (the head task blocks the others anyway) and
  avoid merge churn on files the prerequisite branch has just rewritten.

---

## Open Questions

Resolved during discovery (Rounds 0–3):

- [x] Flow type and base branch — *Owner: jesuslarag*: `type: feature`, `base_branch: dev`.
- [x] Which agent surface becomes MCP tools in v1? — *Owner: jesuslarag*: decorated
  methods **and** the agent's own tools **and** agent metadata as MCP resources.
  `ask()` is NOT exposed.
- [x] Which authentication path? — *Owner: jesuslarag*: navigator-auth as the external
  OAuth 2.1 AS; AI-Parrot validates via introspection (`AuthMethod.OAUTH2_EXTERNAL`).
- [x] Relationship to the streamable-HTTP branch? — *Owner: jesuslarag*: merge it to
  `dev` first; this feature bases on `dev`.
- [x] Long-running calls? — *Owner: jesuslarag*: job handle (`start_*` → `job_id`,
  `*_status`, `*_result`).
- [x] Mount topology? — *Owner: jesuslarag*: per-agent endpoints plus an optional
  aggregate with `{agent}__{tool}` prefixes; one canonical PBAC resource.
- [x] Is PBAC in v1? — *Owner: jesuslarag*: yes — filter `tools/list`, re-verify
  `tools/call`.
- [x] Where does the decorator live? — *Owner: jesuslarag*: core `ai-parrot`
  (importable with no extras), MCP-only semantics. *Note*: Option D's reification
  makes decorated methods visible to A2A `AgentCard` skills as a side effect; the spec
  should state whether that is welcome or must be suppressed.
- [x] Job store? — *Owner: jesuslarag*: reuse `SuspendedExecutionStore` semantics;
  single-process for v1, multi-worker a follow-up.
- [x] Principal propagation? — *Owner: jesuslarag*: contextvar set by the adapter —
  concretely, the existing `_pctx_var` (`auth/context.py:33`).
- [x] Agent opt-in? — *Owner: jesuslarag*: implicit — any agent with at least one
  decorated method.
- [x] Response-size policy? — *Owner: jesuslarag*: yes, enforced in the adapter
  (mandatory pagination on lists, `exclude_none`, per-tool cap).
- [x] Tenant binding? — *Owner: jesuslarag*: per `(tenant_id, principal)`.

Still open:

- [ ] **OQ1 — Who ships the RFC 9728 protected-resource metadata?** The PRM document
  and the `resource_metadata=` 401 hint are missing (§ Does NOT Exist). navigator-auth
  is the AS, but PRM describes the *resource server* — so this endpoint belongs to
  AI-Parrot. Confirm it is in this feature's scope. — *Owner: jesuslarag*
- [ ] **OQ2 — Reification vs LLM-callability.** Must a decorated method be excluded
  from its own agent's `ToolManager` (MCP-only), or may an agent also call it
  internally? Affects whether the exposure set and the LLM tool set are two
  collections or one with a flag. — *Owner: jesuslarag*
- [ ] **OQ3 — Which `AuditLedger`?** `parrot/auth/audit.py:65` or
  `parrot/security/audit_ledger.py:296`. A2A documents the latter. — *Owner: jesuslarag*
- [ ] **OQ4 — Single-worker constraint.** Is v1 allowed to require one aiohttp worker
  (or sticky routing) for the streamable session/event store, or must a shared store
  land in this feature? — *Owner: jesuslarag*
- [ ] **OQ5 — Agent reload.** Re-reify on `BotManager.reload_agent()`, or hold agents
  by name and resolve per call? The second is cheaper and reload-safe. — *Owner: jesuslarag*
- [ ] **OQ6 — Which navigator-auth scopes/claims** carry `tenant_id` and the
  `mcp:agent:{name}` grant, and does the manual user-activation gate live in
  navigator-auth's `/authorize` or in an AI-Parrot policy? — *Owner: jesuslarag*
- [ ] **OQ7 — MCP tool annotations.** Derive `readOnlyHint` / `destructiveHint` /
  `idempotentHint` from the decorator's `scope`, or declare them explicitly? Note
  `routing_meta["requires_confirmation"]` already drives a destructive-op guard in
  `MCPToolAdapter` and is the natural carrier. — *Owner: jesuslarag*
- [ ] **OQ8 — Which agent metadata becomes an MCP resource?** Description and
  capability summary are obvious; KB descriptors and the system prompt are a
  disclosure decision. — *Owner: jesuslarag*
