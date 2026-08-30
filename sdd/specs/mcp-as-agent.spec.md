---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Expose an AI-Parrot Agent as an MCP Server

**Feature ID**: FEAT-477
**Date**: 2026-08-31
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.30.0

**Source brainstorm**: `sdd/proposals/mcp-as-agent.brainstorm.md` (Recommended Option **D**)
**Cross-repo dependency**: navigator-auth **FEAT-095** — `oauth2-for-mcp-agents.spec.md`
(v0.2, approved, target 1.4.0). Its D6 names this feature as its counterpart.

---

## 1. Motivation & Business Requirements

### Problem Statement

An AI-Parrot agent (`AbstractBot` / `BasicAgent`) encapsulates toolkits, knowledge
bases, credential brokers and corporate flows. Today that work is reachable only
through AI-Parrot's own HTTP chat API, through A2A (`A2AServer`), or by another agent
via `BasicAgent.as_tool()`. **There is no way to point an MCP client at an agent.**

What exists instead is *tool*-level MCP exposure: `ParrotMCPServer` mounts a flat,
process-global set of `AbstractTool`s on one endpoint. That surface has no notion of an
agent, no per-user identity, and no per-principal authorization — every caller sees and
can call the same static tool list.

The gap this feature closes:

1. **Agent-scoped MCP endpoints.** A named agent publishes its own MCP surface — its
   `@mcp_tool`-decorated methods, its registered tools, and its metadata as MCP
   resources — so a user can add "the Finance agent" to Claude as a connector.
2. **Per-user identity.** Claude Web speaks OAuth 2.1 only; Claude Code / Desktop / API
   can also send an API key. Both must resolve to one `PermissionContext`.
3. **Per-principal authorization.** `tools/list` must be filtered by the caller's policy
   and `tools/call` re-verified — Claude must never see a tool the principal cannot
   invoke.
4. **Long-running work.** Agent flows/crews exceed the 300 s connector tool-call
   ceiling; they need a durable handle, not a blocking call.

**Who is affected**: end users consuming corporate agents from Claude Web/Code; platform
engineers mounting agents; agent authors who must declare what is safe to expose.

### Goals

Every hard constraint from the brainstorm, each of which maps to an acceptance
criterion in §5:

- **G1** — Build the agent layer on top of the already-merged `StreamableHttpMCPServer`
  (PR #1274, on `dev`). No new transport.
- **G2** — Delegate authentication to navigator-auth as an **external** Authorization
  Server. AI-Parrot is a resource server: it validates the bearer, enforces the
  audience, and resolves a principal. It does **not** grow its own production AS.
- **G3** — Each MCP mount is an RFC 8707 audience. A token minted for agent A must not
  open agent B.
- **G4** — AI-Parrot serves its own RFC 9728 protected-resource metadata and a
  `resource_metadata=`-bearing 401, pointing Claude at navigator-auth as the AS.
- **G5** — Session and SSE-replay state must be shared across gunicorn workers.
- **G6** — PBAC enforced from day one, at both `tools/list` (filter) and `tools/call`
  (re-verify), deny-by-default.
- **G7** — Only *fast* methods answer inline; anything that can exceed ~300 s uses the
  job-handle trio.
- **G8** — Tool responses stay under the ~30 000-token custom-connector ceiling,
  enforced by the adapter, not by method authors.
- **G9** — The decorator is importable from core `ai-parrot` with **no extras
  installed**.
- **G10** — Multi-tenant: the per-call runtime binds to `(tenant_id, principal)`.
- **G11** — No regression to the existing tool-level MCP server, its six transports, or
  A2A.

### Non-Goals (explicitly out of scope)

- **`ask()` is NOT exposed as an MCP tool.** The LLM stays out of the loop by default;
  the injection surface a free-text `question` opens is out of scope.
- **No schema inference in v1.** `name`, `args_schema`, `returns` and `scope` are all
  mandatory on the decorator; registration fails loudly if any is missing.
- **Not Agents-as-Tool.** `BasicAgent.as_tool()` / `register_as_tool()` already exist
  (`bots/agent.py:961`, `:1002`) and are a different feature.
- **No production OAuth AS in this repo.** The in-repo `OAuthRoutesMixin._handle_authorize`
  (`oauth_server.py:638`, *"auto-approves"*) stays a dev/test fixture. FEAT-095 explicitly
  declines to delete it.
- **No PBAC shadow / audit-only rollout.** It does not exist in either repo — see §7.
- **No conversational memory shared between MCP calls.**
- **No legacy SSE transport and no stdio for Claude Web.**
- **No `client_credentials` (M2M)** — Claude Web requires interactive `authorization_code`.
- **No `static_headers`** as a primary path — it loses per-user identity.
- *Single-endpoint agent multiplexing* (brainstorm Option B) was **rejected on isolation
  grounds** — see `proposals/mcp-as-agent.brainstorm.md` Option B.
- *Replacing the server with the official MCP SDK / FastMCP* (Option C) was **rejected as
  a server**, but the SDK is adopted as an **interop test client** via the existing
  `requires_mcp_sdk` pytest marker.

---

## 2. Architectural Design

### Overview

**Option D — method reification.** `@mcp_tool` does not create a new kind of thing. It
*marks* a bound agent method so that, at `configure()` time, it is **reified into a real
`AbstractTool`** (an `AgentMethodTool` wrapper whose `name`, `description`, `args_schema`
come from the decorator and whose `_execute()` calls the bound method). From that instant
the method is indistinguishable from any other tool to everything downstream:
`MCPToolAdapter` converts it with zero new code, `RemoteMCPServerBase.register_tool()`
filters it like any tool, and `A2AServer._build_skills_from_tools()` surfaces it in the
`AgentCard` for free.

Seven decisions define the design; each is a resolved brainstorm question carried
forward verbatim (§8):

1. **Reification is MCP-only (OQ2).** A reified `@mcp_tool` method is **never registered
   into the owning agent's `ToolManager`**. It lives in a separate *exposure set*.
   Decorating a method changes what MCP clients can call and **nothing else** — it does
   not make the method LLM-callable inside its own agent. This is the single most
   important invariant in the spec and the one real cost of Option D.
2. **Topology.** One `StreamableHttpMCPServer` per exposed agent at
   `/mcp/agents/{name}`, mounted into the existing `web.Application` — the exact pattern
   `A2AServer.setup()` uses (`a2a/server.py:231`) — plus an optional aggregate `/mcp`
   publishing `{agent}__{tool}`. Both name forms resolve to the **same canonical PBAC
   resource** `mcp:agent:{name}:tool:{tool}`; the aggregate is naming sugar, never an
   authorization path of its own.
3. **Opt-in is implicit.** Having at least one decorated method **is** the opt-in. No
   `expose_as_mcp` flag, no server-side allowlist to keep in sync.
4. **Identity.** `_authenticate_request()` resolves the bearer: Claude Web presents a
   navigator-auth OAuth 2.1 token validated by RFC 7662 introspection
   (`AuthMethod.OAUTH2_EXTERNAL`); Claude Code/Desktop present an API key
   (`AuthMethod.API_KEY`). Both land in `request["mcp_user"]`; one principal-resolution
   step converts either into a `PermissionContext`, published on the **existing**
   `_pctx_var` contextvar (`auth/context.py:33`) — the same one `DatasetManager` and
   `DatabaseQueryTool` already read, so every downstream guard inherits the MCP caller's
   identity with no signature changes anywhere.
5. **Authorization.** `tools/list` asks the PBAC resolver per candidate tool and returns
   only permitted entries; `tools/call` **re-evaluates the same resource** — the list is
   never trusted as an authorization record.
6. **Long-running work.** `start_*` persists a job record (Redis, reusing
   `SuspendedExecutionStore` semantics) and returns a `job_id` immediately;
   `*_status` / `*_result` project a manifest, never raw payloads.
7. **Introspection-with-cache is the v1 default.** FEAT-095 also offers offline JWKS
   verification. `ExternalOAuthValidator` already caches introspection results for
   `min(exp, now+300)` (`oauth_server.py:317`), which bounds both the per-call network
   hop *and* revocation latency at ~5 minutes. JWKS is an optimization to revisit, not
   the v1 path.

**Two orthogonal pieces of platform work ship with this feature** because the agent
endpoints are not usable without them:

- **RFC 9728 PRM (G4).** Claude's connector discovery expects a protected-resource
  metadata document. Nothing serves one today, and the 401 header is hardcoded
  `'Bearer realm="mcp"'` (`transports/base.py:307`). navigator-auth ships the *builder*
  (`build_protected_resource_metadata` in its `oauth2/metadata.py`); **we serve the
  document** — do not hand-roll its shape.
- **Shared session store (G5).** The project's own deploy template runs
  `aiohttp.GunicornWebWorker` with `(2×CPUs)+1` workers, recycles them every 2000
  requests, and states *"Do NOT rely on in-process dicts for cross-request state"*
  (`autonomous/deploy/templates.py:3`). `StreamableHttpMCPServer._sessions` is a plain
  dict (`streamable_http.py:265`) and `StreamBuffer` is an in-process ring
  (`streamable_http.py:144`). A Redis-backed store replaces both — which also fixes the
  existing tool-level streamable endpoint.

### Component Diagram

```
                        Claude Web  /  Claude Code
                              │  (OAuth 2.1 bearer | API key)
                              ▼
   GET /.well-known/oauth-protected-resource   ──►  RFC 9728 PRM  (M5)
        401 WWW-Authenticate: resource_metadata="…"      │ authorization_servers
                              │                          ▼
                              │                 navigator-auth AS (FEAT-095, external)
                              ▼                   DCR · upstream IdP · access gate
              POST/GET/DELETE /mcp/agents/{name}
                              │
                    StreamableHttpMCPServer  (merged, dev)
                       _guard  ──► _authenticate_request      transports/base.py:190
                              │        └─► request["mcp_user"]
                              ▼
                     PrincipalGuard                                    (M3)
        mcp_user ──► PermissionContext ──► _pctx_var  (auth/context.py:33)
                              │
             ┌────────────────┼─────────────────┐
             ▼                ▼                 ▼
      handle_tools_list   handle_tools_call   handle_resources_*
        filter by PBAC     re-verify PBAC      identity card
             │                │                tool catalog (filtered)
             │                │                KB descriptors        (M2)
             └────────┬───────┘
                      ▼
              MCPToolAdapter        (core, adapter.py:8 — UNCHANGED)
                      │
                      ▼
              AgentMethodTool  ◄── reified at configure() from @mcp_tool   (M1)
                      │                exposure set, NOT tool_manager
                      ▼
          bound agent method ──► fast: inline result ──► size policy ──► MCP content
                              └─► slow: start_* ──► job_id ──► Redis      (M4)
                                              *_status / *_result

              AuditLedger.append(...)   security/audit_ledger.py:338
              Redis session + event store  ◄── replaces _sessions/StreamBuffer  (M6)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/mcp/` (core) | extends | new decorator + `AgentMethodTool`; importable with no extras (G9) |
| `MCPToolAdapter` (`mcp/adapter.py:8`) | uses, unchanged | schema extraction, confirmation guard, `ToolResult` → MCP content |
| `StreamableHttpMCPServer` (`transports/streamable_http.py:250`) | instantiates / subclasses | one per exposed agent |
| `RemoteMCPServerBase` (`transports/base.py:18`) | extends | principal resolution from `mcp_user`; `_unauthorized_response` gains `resource_metadata=` |
| `OAuthRoutesMixin` (`oauth_server.py:569`) | extends | new RFC 9728 PRM route beside the existing RFC 8414 discovery |
| `ParrotMCPServer` (`mcp/parrot_server.py`) | modifies | agent mount registered alongside the tool-level server; must not double-claim `base_path` (`_check_base_path_conflicts:121`) |
| `_sessions` / `StreamBuffer` (`streamable_http.py:265`, `:144`) | modifies | Redis-backed shared store; benefits the tool-level endpoint too |
| `AuditLedger` (`security/audit_ledger.py:296`) | uses | `await ledger.append(...)` per `tools/call` |
| `MCPServerConfig` (`mcp/config.py:16`) | extends | agent-mount settings (exposed agents, aggregate on/off, size caps, tenant) |
| `BotManager.setup()` (`manager/manager.py:1965`) | modifies | wires the agent mount from loaded bots |
| `PBACPermissionResolver` (`auth/resolver.py:247`) | uses | policy decisions per MCP resource |
| `_pctx_var` (`auth/context.py:33`) | uses | carries the MCP principal into data-plane guards |
| `SuspendedExecutionStore` (`human/suspended_store.py:64`) | uses (semantics) | job-handle persistence |
| `A2AServer` (`a2a/server.py:86`) | precedent + consequence | mount pattern; inherits decorated methods as `AgentCard` skills |
| navigator-auth **FEAT-095** (external) | depends on | DCR, RFC 8414/9728, upstream IdP, access gate, introspection |
| Deployment | modifies | endpoint must be publicly routable for Claude Web; **Redis becomes required** for agent MCP endpoints |

**Breaking changes**: none expected. The tool-level MCP server, all existing transports
and A2A keep their current behavior (G11).

### Data Models

```python
# Declaration metadata attached by @mcp_tool. Lives in core parrot/mcp/.
class MCPToolDeclaration(BaseModel):
    name: str                                  # mandatory — no inference
    description: str                           # mandatory
    args_schema: Type[BaseModel]               # mandatory — no inference
    returns: Type[BaseModel]                   # mandatory — no inference
    scope: str                                 # mandatory — PBAC action
    read_only_hint: bool = False               # -> MCP readOnlyHint  (explicit, OQ7)
    idempotent_hint: bool = False              # -> MCP idempotentHint (explicit, OQ7)
    requires_confirmation: bool = False        # -> routing_meta -> destructiveHint
    max_result_tokens: int | None = None       # per-tool cap; None -> mount default


# Resolved caller identity. NOTE: PermissionContext already plays the "Principal"
# role — do NOT introduce a new Principal model.
# UserSession(user_id: str, tenant_id: str, roles: frozenset[str], metadata: dict)
# PermissionContext(session, request_id, channel, trace_context, extra)


class AgentMCPMountConfig(BaseModel):
    agents: list[str]                          # agent names, resolved via BotManager
    base_path: str = "/mcp/agents"
    aggregate_enabled: bool = False            # the optional /mcp aggregate
    default_tenant_id: str | None = None       # fallback when the token carries none
    resource_server_url: str                   # RFC 8707 audience for THIS mount
    max_result_tokens: int = 25_000            # under the ~30k connector ceiling
    call_deadline_seconds: float = 240.0       # below the 300 s client ceiling


class AgentJobRecord(BaseModel):
    job_id: str
    agent: str
    tool: str
    tenant_id: str
    principal: str
    status: Literal["pending", "running", "succeeded", "failed", "expired"]
    created_at: datetime
    manifest: dict[str, Any] | None = None     # projection, never the raw payload
    error: str | None = None
```

### New Public Interfaces

```python
# core: packages/ai-parrot/src/parrot/mcp/  — importable with NO extras (G9)
def mcp_tool(
    *,
    name: str,
    description: str,
    args_schema: Type[BaseModel],
    returns: Type[BaseModel],
    scope: str,
    read_only_hint: bool = False,
    idempotent_hint: bool = False,
    requires_confirmation: bool = False,
    max_result_tokens: int | None = None,
) -> Callable[[F], F]:
    """Mark a bound agent method as externally callable over MCP.

    Marks only. Reification into an AgentMethodTool happens at configure()
    time. The decorated method is NEVER registered into the owning agent's
    ToolManager and does not become LLM-callable inside that agent (OQ2).
    """


class AgentMethodTool(AbstractTool):
    """An agent method reified as a real AbstractTool."""
    async def _execute(self, **kwargs) -> ToolResult: ...


# ai-parrot-server: packages/ai-parrot-server/src/parrot/mcp/
class AgentMCPMount:
    def __init__(self, bot_manager: "BotManager", config: AgentMCPMountConfig): ...
    def setup(self, app: web.Application) -> web.Application: ...
```

---

## 3. Module Breakdown

### Module 1: `@mcp_tool` decorator + `AgentMethodTool` reification
- **Path**: `packages/ai-parrot/src/parrot/mcp/agent_tools.py` (new, **core**)
- **Responsibility**: the decorator, its mandatory-field validation, the
  `AgentMethodTool` wrapper, and the configure-time scan that builds an agent's
  *exposure set*. MCP annotations ride on `routing_meta` (OQ7). The exposure set is
  **deliberately not** registered into `AbstractBot.tool_manager` (OQ2).
- **Depends on**: `AbstractTool` / `ToolResult`, `pydantic`. **No `ai-parrot-server`
  import** — must work with no extras installed (G9).
- **Note**: hold the agent by weak reference / bound-method care so `AgentMethodTool`
  never drags the agent into tool-serialization paths.

### Module 2: `AgentMCPMount` — per-agent endpoints and resources
- **Path**: `packages/ai-parrot-server/src/parrot/mcp/agent_mount.py` (new)
- **Responsibility**: build one `StreamableHttpMCPServer` per exposed agent at
  `/mcp/agents/{name}`, register the exposure set plus the agent's own tools (minus
  `A2AServer._INTERNAL_TOOL_NAMES`-style plumbing), the optional aggregate `/mcp`, and
  the three metadata resources. Holds agents **by name**, resolving through
  `BotManager` per call (OQ5).
- **Depends on**: Module 1; `StreamableHttpMCPServer`; `BotManager.get_bots()`.

### Module 3: `PrincipalGuard` — identity, PBAC and audit
- **Path**: `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py` (new)
- **Responsibility**: convert `request["mcp_user"]` into a `PermissionContext`, publish
  it on `_pctx_var`, filter `handle_tools_list` and re-verify `handle_tools_call`
  against `mcp:agent:{name}:tool:{tool}`, bind the runtime to `(tenant_id, principal)`,
  enforce the size policy and the call deadline, and append to the `AuditLedger`.
- **Depends on**: Modules 1–2; `PBACPermissionResolver`; `security/audit_ledger`.
- **Note**: the merged branch centralizes auth in `_guard` (`streamable_http.py:530`,
  calling `_authenticate_request` at `:532`) rather than per-handler — that is the
  single injection point for principal resolution.

### Module 4: Job handles for long-running methods
- **Path**: `packages/ai-parrot-server/src/parrot/mcp/agent_jobs.py` (new)
- **Responsibility**: the `start_*` / `*_status` / `*_result` trio; Redis persistence
  reusing `SuspendedExecutionStore` semantics (caller-provided TTL, tombstone on
  delete); manifest projection.
- **Depends on**: Module 1. Runs alongside Modules 2–3.

### Module 5: RFC 9728 protected-resource metadata
- **Path**: `packages/ai-parrot-server/src/parrot/mcp/oauth_server.py` (extend),
  `transports/base.py` (extend `_unauthorized_response`)
- **Responsibility**: serve `/.well-known/oauth-protected-resource` using
  navigator-auth's `build_protected_resource_metadata` builder, and add
  `resource_metadata="…"` to the 401 `WWW-Authenticate`. Configure
  `ExternalOAuthValidator.resource_server_url` per mount so the existing audience check
  (`oauth_server.py:262-267`) enforces G3.
- **Depends on**: nothing in this feature — self-contained, parallelizable.

### Module 6: Redis-backed shared session + event store
- **Path**: `packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py`
  (modify) + a new store module
- **Responsibility**: replace `self._sessions` (`:265`) and the in-process
  `StreamBuffer` (`:144`) with a Redis-backed store so a session created on one gunicorn
  worker resolves on any other and survives the `max_requests = 2000` recycle. Store
  unavailability must **fail the request cleanly**, never silently degrade to
  per-process state.
- **Depends on**: nothing in this feature — independent, and it also fixes the existing
  tool-level streamable endpoint.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_mcp_tool_requires_all_fields` | M1 | Missing `args_schema`/`returns`/`scope`/`name` raises at decoration/configure with agent+method in the message |
| `test_mcp_tool_rejects_sync_method` | M1 | A non-async decorated method fails loudly at configure time |
| `test_reified_tool_not_in_tool_manager` | M1 | **OQ2 invariant**: after `configure()`, the method is in the exposure set and absent from `agent.tool_manager.list_tools()` |
| `test_reification_maps_annotations_to_routing_meta` | M1 | `requires_confirmation` → `routing_meta`; `read_only_hint`/`idempotent_hint` carried explicitly |
| `test_core_import_without_extras` | M1 | `from parrot.mcp.agent_tools import mcp_tool` succeeds with no `ai-parrot-server` installed |
| `test_mount_creates_per_agent_endpoint` | M2 | `/mcp/agents/{name}` registered for each exposed agent |
| `test_mount_resolves_agent_by_name_per_call` | M2 | **OQ5**: after `BotManager.reload_agent()`, the mount serves the new instance, not the cleaned-up one |
| `test_aggregate_prefix_and_separator_rejection` | M2 | `{agent}__{tool}` naming; an agent name containing `__` is rejected at mount time |
| `test_resources_exclude_system_prompt` | M2 | **OQ8**: identity card, tool catalog and KB descriptors are served; `backstory`, `rationale` and the assembled system prompt are in neither `resources/list` nor `resources/read` |
| `test_principal_from_oauth_and_api_key` | M3 | Both auth paths produce an equivalent `PermissionContext` |
| `test_tenant_id_precedence_and_fail_closed` | M3 | `tenant_id` claim → `org_id` → mount default → 401; `client_id` is never used as tenant |
| `test_tools_list_filtered_by_policy` | M3 | A denied tool is absent from `tools/list` |
| `test_tools_call_reverifies_policy` | M3 | A `tools/call` for a tool absent from the list returns a clean MCP error, not a stack trace, and is audited as a denial |
| `test_pctx_var_published_during_call` | M3 | `_pctx_var` carries the caller inside the invoked method |
| `test_result_size_policy_truncates_explicitly` | M3 | Oversized results are truncated/paginated and the response *says so* |
| `test_call_deadline_below_client_ceiling` | M3 | A blocking method yields a clean timeout naming the method |
| `test_start_returns_job_id_immediately` | M4 | `start_*` does not block; `*_status`/`*_result` project a manifest, never raw payloads |
| `test_prm_document_shape` | M5 | PRM built via navigator-auth's builder; `authorization_servers` points at the AS issuer |
| `test_401_carries_resource_metadata` | M5 | `WWW-Authenticate` includes `resource_metadata=`, replacing the bare `Bearer realm="mcp"` |
| `test_audience_rejects_foreign_token` | M5 | **G3**: a token whose `aud` omits this mount's resource URI is rejected |
| `test_session_resolves_across_workers` | M6 | A session written by one store client resolves from a second, independent client |
| `test_store_unavailable_fails_cleanly` | M6 | Redis down ⇒ clean error, never a silent fall back to a per-process dict |

### Integration Tests

| Test | Description |
|---|---|
| `test_api_key_end_to_end` | Claude Code path: API key → `initialize` → `tools/list` → `tools/call` → audited result. **No navigator-auth dependency — the first vertical slice.** |
| `test_oauth_end_to_end_mocked` | Claude Web path with introspection + PRM legs mocked; asserts discovery → 401 challenge → token → filtered list → call |
| `test_agent_isolation_across_mounts` | A token for agent A cannot call agent B |
| `test_no_regression_tool_level_server` | **G11**: the existing tool-level MCP server and its transports behave unchanged |
| `test_a2a_agent_card_includes_decorated_methods` | Reification side effect: decorated methods appear as `AgentCard` skills |
| `test_mcp_sdk_interop` | Drives the agent endpoint with the reference MCP SDK client, gated by the existing `requires_mcp_sdk` marker |

### Test Data / Fixtures

```python
@pytest.fixture
def exposed_agent():
    """A BasicAgent with one @mcp_tool method and one ordinary tool."""

@pytest.fixture
def mock_introspection():
    """RFC 7662 endpoint returning a token with sub/scope/aud/tenant_id."""

@pytest.fixture
def fake_redis():
    """Shared store double, and a variant that raises to test fail-closed."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **G1** — Agent endpoints are served by `StreamableHttpMCPServer`; no new transport
      was added.
- [ ] **G2** — Authentication resolves through navigator-auth via RFC 7662 introspection
      (`AuthMethod.OAUTH2_EXTERNAL`) or an API key; **no production AS was added to this
      repo**.
- [ ] **G3** — A token whose `aud` omits the mount's resource URI is rejected; a token
      for agent A cannot call agent B (`test_agent_isolation_across_mounts`).
- [ ] **G4** — `/.well-known/oauth-protected-resource` serves an RFC 9728 document built
      with navigator-auth's builder, and every MCP 401 carries `resource_metadata=`.
- [ ] **G5** — A Streamable HTTP session created on one gunicorn worker resolves on
      another; store unavailability fails the request cleanly.
- [ ] **G6** — `tools/list` is filtered per principal and `tools/call` re-verifies the
      same canonical resource; the default effect is DENY.
- [ ] **G7** — Every method that can exceed ~300 s is exposed as a `start_*` / `*_status`
      / `*_result` trio; a blocking call hits the deadline and returns a clean timeout.
- [ ] **G8** — Results are capped below the ~30 000-token ceiling by the adapter layer,
      and truncation is stated explicitly in the response.
- [ ] **G9** — `from parrot.mcp.agent_tools import mcp_tool` works in an environment with
      core `ai-parrot` only.
- [ ] **G10** — The per-call runtime binds to `(tenant_id, principal)`; `tenant_id`
      resolution follows the precedence in §8 and fails closed.
- [ ] **G11** — No regression to the tool-level MCP server, its six transports, or A2A.
- [ ] **OQ2 invariant** — a decorated method is provably absent from its own agent's
      `ToolManager` (`test_reified_tool_not_in_tool_manager`).
- [ ] **OQ8 invariant** — `backstory`, `rationale` and the assembled system prompt are
      served by no resource.
- [ ] Every `tools/call` appends principal, agent, tool, argument hash, decision and
      duration to `parrot.security.audit_ledger.AuditLedger`.
- [ ] All unit tests pass (`pytest packages/ai-parrot-server/tests/mcp/ -v`)
- [ ] All integration tests pass (`pytest tests/integration/ -v`)
- [ ] Documentation updated in `docs/` (agent-author guide + platform-engineer mount guide)
- [ ] No breaking changes to existing public API

**Deferred evidence (cross-repo)**: the live Claude Web path (DCR → Google login → gate
→ token → `tools/call`) cannot be verified until navigator-auth 1.4.0 ships. CI mocks the
introspection and PRM legs; **one live conformance run is a post-release gate**, not a
merge blocker. The API-key path has no such dependency and is demonstrated end-to-end at
merge time.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Re-verified against `dev` @ `7c92a73f8` on 2026-08-31, **after** PR #1274
> (`claude/mcp-http-streamable-transport-bptepy`) merged. The brainstorm's anchors were
> written against the pre-merge branch and **have drifted** — the corrections below are
> authoritative. Most importantly: **`SessionEventStore` no longer exists.**

### Verified Imports

```python
# core ai-parrot — no extras required
from parrot.mcp.adapter import MCPToolAdapter
from parrot.mcp.server_base import (
    MCPServerBase, LocalServerConfig,
    SUPPORTED_PROTOCOL_VERSIONS, LATEST_PROTOCOL_VERSION, DEFAULT_PROTOCOL_VERSION,
)
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.auth.context import UserContext, _pctx_var
from parrot.auth.permission import UserSession, PermissionContext, build_principal_context
from parrot.auth.pbac import setup_pbac
from parrot.auth.resolver import PBACPermissionResolver
from parrot.security.audit_ledger import AuditLedger          # canonical — NOT parrot.auth.audit

# ai-parrot-server
from parrot.mcp.config import AuthMethod, MCPServerConfig
from parrot.mcp.transports.base import RemoteMCPServerBase
from parrot.mcp.transports.http import HttpMCPServer
from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer   # now on dev
from parrot.mcp.oauth_server import APIKeyStore, ExternalOAuthValidator, OAuthRoutesMixin
from parrot.human.suspended_store import SuspendedExecutionStore
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/mcp/adapter.py
class MCPToolAdapter:                                            # :8
    def __init__(self, tool: AbstractTool): ...                  # :19
    def _requires_confirmation(self) -> bool: ...                # :23
    def to_mcp_tool_definition(self) -> dict[str, Any]: ...       # :27
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]: ...   # :59
    def _toolresult_to_mcp(self, result: ToolResult) -> dict[str, Any]: ...     # :108
    # :10-18 docstring: honors routing_meta["requires_confirmation"] by injecting a
    # required `confirm` boolean into inputSchema and rejecting unconfirmed calls.

# packages/ai-parrot/src/parrot/mcp/server_base.py   (line numbers CORRECTED)
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...]        # :17  ("2024-11-05","2025-03-26","2025-06-18")
LATEST_PROTOCOL_VERSION: str                        # :23
DEFAULT_PROTOCOL_VERSION: str                       # :26
class LocalServerConfig:                            # :48
class MCPServerBase(ABC):                           # :57   (brainstorm said :27 — WRONG)
    def register_tool(self, tool: AbstractTool): ...                            # :68
    def register_tools(self, tools: list[AbstractTool]): ...                    # :75
    async def handle_initialize(self, params) -> dict[str, Any]: ...            # :80
    async def handle_tools_list(self, params) -> dict[str, Any]: ...            # :100 (was :68)
    async def handle_tools_call(self, params) -> dict[str, Any]: ...            # :111 (was :79)

# packages/ai-parrot-server/src/parrot/mcp/transports/base.py
class RemoteMCPServerBase(_CoreMCPServerBase):                                  # :18
    def register_resource(self, resource, read_handler): ...                    # :49
    def register_tool(self, tool: AbstractTool): ...                            # :65  allowed/blocked filter
    async def handle_resources_list(self, params) -> dict[str, Any]: ...        # :86
    async def handle_resources_read(self, params) -> dict[str, Any]: ...        # :93
    async def _authenticate_request(self, request) -> web.Response | None: ...  # :190 (was :188)
    def _unauthorized_response(self, message,
                               www_authenticate: str = 'Bearer realm="mcp"'     # :307 (was :305)
                               ) -> web.Response: ...
    # :263-267 — external-OAuth path sets request["mcp_user"] =
    #     {"user_id": sub or client_id, "scopes": [...], "token_info": {...}}

# packages/ai-parrot-server/src/parrot/mcp/transports/http.py
class HttpMCPServer(OAuthRoutesMixin, RemoteMCPServerBase):                     # :22
    def __init__(self, config: MCPServerConfig,
                 parent_app: Optional[web.Application] = None)                  # :25
    async def start(self): ...                                                  # :38
    def _register_routes(self, router, base_route: str) -> None: ...            # :94 (was :90)
    async def stop(self): ...                                                   # :107

# packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py
#   *** ALL LINE NUMBERS CHANGED post-merge (review findings S-01…S-15) ***
KEEP_ALIVE_INTERVAL: float = 15.0                                               # :56
ASSUMED_HEADER_VERSION: str = "2025-03-26"                                      # :65
class StreamEvent:                                                              # :104
class StreamBuffer:                                                             # :144  <-- was SessionEventStore
    def __init__(self, stream_id: str, max_events: int = 1000)                  # :154
    def append(self, message) -> StreamEvent                                    # :163
    def events_after(self, sequence: int) -> list[StreamEvent]                  # :174
    def undelivered(self) -> list[StreamEvent]                                  # :184
class McpStreamSession:                                                         # :184 (was :111)
class StreamableHttpMCPServer(HttpMCPServer):                                   # :250 (was :125)
    def __init__(self, ...)                                                     # :259
    self._sessions: dict[str, McpStreamSession]                                 # :265  <-- in-process (M6 target)
    self._max_sessions: int                                                     # :272
    def _register_routes(self, router, base_route) -> None                      # :286
    async def _handle_info(self, request)                                       # :311
    def _principal(self, request) -> Any                                        # :327
    def _credential_digest(self, request) -> str | None                         # :353
    async def _create_session(...)                                              # :362
    async def _get_session(...)                                                 # :389
    async def _prune_sessions(self)                                             # :420
    def _check_origin(self, request)                                            # :487  DNS-rebinding protection
    def _check_protocol_header(self, ...)                                       # :514
    async def _guard(self, request)                                             # :530  <-- CENTRALIZED auth;
                                                                                #        calls _authenticate_request at :532
    async def _handle_streamable_post(self, request)                            # :582
    async def _handle_streamable_get(self, request)                             # :892
    async def _handle_streamable_delete(self, request)                          # :1035

# packages/ai-parrot-server/src/parrot/mcp/oauth_server.py
class APIKeyRecord:                                                             # :31
class APIKeyStore:                                                              # :41
    def issue_key(...)          # :53      def validate_key(...)   # :119
    def revoke_key(...)         # :142
class ExternalOAuthValidator:                                                   # :211
    def __init__(self, introspection_endpoint, client_id, client_secret,
                 resource_server_url: Optional[str] = None, http_timeout=15.0)  # :219
    async def validate_token(self, token) -> Optional[Dict[str, Any]]           # :244
    # :262-267 — AUDIENCE ENFORCEMENT ALREADY EXISTS: when resource_server_url is set,
    #   a token whose `aud` (str or list) omits it is rejected. This is the G3 hook.
    async def get_token_info(self, token) -> Dict[str, Any]                     # :274
    # :288-318 — introspection cache: min(exp, now+300) => revocation latency <= ~5 min
    def clear_cache(self) -> None                                               # :322
class OAuthAuthorizationServer:                                                 # :374  register_routes :393
class OAuthRoutesMixin:                                                         # :569
    def _oauth_paths(self) -> Dict[str, str]                                    # :576
    def _add_oauth_routes(self, router)                                         # :586
    async def _handle_discovery(self, request)                                  # :593  RFC 8414
    async def _handle_registration(self, request)                               # :609  RFC 7591
    async def _handle_authorize(self, request)                                  # :638  *** auto-approves — dev/test ONLY ***

# packages/ai-parrot-server/src/parrot/a2a/server.py  — PER-AGENT MOUNT PRECEDENT
class A2AServer:                                                                # :86
    def __init__(self, agent, *, base_path="/a2a", suspended_store=None,
                 audit_ledger=None, ...)                                        # :120
    def setup(self, ...)                                                        # :231  registers routes on the aiohttp app
    def get_agent_card(self) -> AgentCard                                       # :334
    _INTERNAL_TOOL_NAMES = frozenset({"to_json"})                               # :398
    def _build_skills_from_tools(self) -> List[AgentSkill]                      # :400  walks agent.tool_manager
    def _tool_to_skill(self, tool) -> Optional[AgentSkill]                      # :425

# packages/ai-parrot/src/parrot/auth/
class UserSession:                    # permission.py:21   user_id: str, tenant_id: str (REQUIRED),
                                      #   roles: frozenset[str], metadata: dict
class PermissionContext:              # permission.py:81   session, request_id, channel, trace_context, extra
def build_principal_context(principal: str, *, channel: str,
                           tenant_id=None, roles=None) -> PermissionContext     # permission.py:166
_pctx_var: ContextVar["PermissionContext | None"]                               # context.py:33
class UserContext:                                                              # context.py:39
def setup_pbac(app, policy_dir="policies", cache_ttl=30, default_effect=None)   # pbac.py:67
                                      #   deny-by-default; fail-closed when PARROT_SAAS_MODE=true
class PBACPermissionResolver(AbstractPermissionResolver):                       # resolver.py:247  __init__ :275

# packages/ai-parrot/src/parrot/security/audit_ledger.py   — CANONICAL (OQ3)
class AuditLedgerEntry(BaseModel):                                              # :80
class AuditLedger:                                                              # :296
    async def append(self, ...)                                                 # :338

# packages/ai-parrot-server/src/parrot/human/suspended_store.py
class SuspendedExecutionStore:                                                  # :64
    def __init__(self, redis: Any) -> None                                      # :87
    async def save(self, record, ttl: int) -> None                              # :103
    async def load(self, interaction_id) -> Optional[SuspendedExecution]        # :128
    async def delete(self, interaction_id) -> None                              # :149
    # key format: hitl:suspended:{interaction_id}; delete leaves hitl:interaction:{id} intact
```

### Key Attributes & Constants

- `AuthMethod` members → `NONE | API_KEY | OAUTH2_INTERNAL | OAUTH2_EXTERNAL | BEARER`
  (`mcp/config.py:6`).
- `MCPServerConfig` (`mcp/config.py:16`): `allowed_tools` `:32`, `blocked_tools` `:33`
  — static process-wide name filters applied in `RemoteMCPServerBase.register_tool`
  (`base.py:65`), **not** per-principal; `base_path = "/mcp"` `:61`;
  `allowed_origins` `:70`; `session_ttl = 3600` `:75`; `event_buffer_size = 1000` `:77`.
- `ParrotMCPServer._check_base_path_conflicts()` (`parrot_server.py:121`, called `:164`)
  — two transports may not share a `base_path`. The agent mount must not collide.
- `AbstractBot.tool_manager: ToolManager` (`bots/abstract.py:386`);
  `AbstractBot.knowledge_bases: List[AbstractKnowledgeBase]` (`bots/abstract.py:554`).
- `ToolManager.get_tool` (`tools/manager.py:1231`), `.list_tools` (`:1251`),
  `.tool_count` (`:2053`).
- `AbstractTool.name` (`tools/abstract.py:296`), `.args_schema: Type[BaseModel]` (`:298`),
  `.routing_meta: Dict` (declared `:300`, set per-instance `:373`) — the existing
  precedent for per-tool MCP metadata.
- `BasicAgent.agent_tools` (`bots/agent.py:337`), `as_tool()` (`:961`),
  `register_as_tool()` (`:1002`) — agent-as-tool already exists and is NOT this feature.
- `BotManager.reload_agent()` (`manager/manager.py:856`), `.get_bots()` (`:1146`),
  `.setup(app)` (`:1965`, **synchronous**).
- `navigator-auth>0.20.9` is a **core** dependency (`packages/ai-parrot/pyproject.toml:83`).
- `GUNICORN_CONFIG_TEMPLATE` (`autonomous/deploy/templates.py:3`) —
  `worker_class = "aiohttp.GunicornWebWorker"`, `workers = (2×CPUs)+1`,
  `max_requests = 2000`, and an explicit *"Do NOT rely on in-process dicts for
  cross-request state"*.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AgentMethodTool` | `MCPToolAdapter.__init__` | constructor arg | `mcp/adapter.py:19` |
| `AgentMCPMount` | `StreamableHttpMCPServer` | instantiation per agent | `transports/streamable_http.py:250` |
| `AgentMCPMount.setup` | `web.Application` router | parent-app route registration | `a2a/server.py:231` (precedent) |
| `AgentMCPMount` | `BotManager.get_bots()` | by-name resolution per call | `manager/manager.py:1146` |
| `PrincipalGuard` | `request["mcp_user"]` | read after `_guard` | `transports/streamable_http.py:530-532` |
| `PrincipalGuard` | `_pctx_var.set(...)` | contextvar publish | `auth/context.py:33` |
| `PrincipalGuard` | `PBACPermissionResolver` | policy evaluation | `auth/resolver.py:247` |
| `PrincipalGuard` | `AuditLedger.append()` | await per tools/call | `security/audit_ledger.py:338` |
| PRM 401 hint | `_unauthorized_response(www_authenticate=…)` | override default arg | `transports/base.py:307` |
| Audience check | `ExternalOAuthValidator(resource_server_url=…)` | constructor arg | `mcp/oauth_server.py:219`, enforced `:262-267` |
| Job store | `SuspendedExecutionStore` | semantics reuse | `human/suspended_store.py:64` |

### Does NOT Exist (Anti-Hallucination)

Re-verified absent on `dev` @ `7c92a73f8` (post-merge):

- ~~`@mcp_tool` / `def mcp_tool`~~ — no definition or usage anywhere in `packages/`.
- ~~`AgentMethodTool`, `AgentMCPMount`, `AgentMethodAdapter`, `MCPAgentMount`,
  `ResultPolicy`, `JobHandle`, `resolve_principal()`~~ — none exist. All are created by
  this feature.
- ~~`SessionEventStore`~~ — **removed by the merge**. The brainstorm cites it at
  `streamable_http.py:77`; it is now `StreamBuffer` at `:144`. Do not import the old name.
- ~~`MCPToolSpec`, `MCPAgentManifest`, `Principal`~~ — the prior draft's contracts.
  `PermissionContext` already plays the `Principal` role.
- ~~`parrot.interfaces.mcp`~~ — `parrot/interfaces/` exists but contains no `mcp.py`.
- ~~`/.well-known/oauth-protected-resource` (RFC 9728)~~ — **not implemented**; no
  occurrence of `protected_resource` anywhere. Only RFC 8414
  `/.well-known/oauth-authorization-server` exists (`oauth_server.py:593`,
  `parrot_server.py:195`).
- ~~`resource_metadata=` in the 401 `WWW-Authenticate`~~ — hardcoded
  `'Bearer realm="mcp"'` (`transports/base.py:307`).
- ~~Per-principal `tools/list`~~ — `handle_tools_list(params)` (`server_base.py:100`)
  takes no principal and returns every registered adapter.
- ~~PBAC enforcement inside any MCP transport~~ — no MCP module imports
  `parrot.auth.pbac` or `PBACPermissionResolver` (grep over both `mcp/` trees: empty).
- ~~A shared/Redis session store for Streamable HTTP~~ — `_sessions` is a plain dict
  (`streamable_http.py:265`); the only `redis` mention is a docstring note at `:35`
  calling a shared store a follow-up.
- ~~A production-grade OAuth AS in ai-parrot~~ — `OAuthRoutesMixin._handle_authorize`
  (`oauth_server.py:638`) is documented *"auto-approves"*; no consent, no refresh
  rotation, no user gate. It is a dev fixture, **not** an absent component.
- ~~A PBAC shadow / audit-only mode~~ — does not exist in either repo. navigator-auth's
  `enforcing: false` means *"non-short-circuiting ordinary policy"*, NOT dry-run.
- ~~A per-agent grant in navigator-auth~~ — the FEAT-095 access gate is keyed
  `(user_id, client_uid)` and Claude registers a single client.
- ~~`MCPAgent` as a distinct class~~ — `bots/mcp.py:11` is an alias of `BasicAgent`
  (MCP *client* capability — the opposite direction).
- ~~`EpisodicMemoryStore` in the `parrot.memory` root~~ — it is at
  `parrot/memory/episodic/store.py`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Mount like A2A.** `A2AServer.setup()` (`a2a/server.py:231`) is the reference for
  registering per-agent routes into an existing `web.Application`. Follow it.
- **Metadata rides `routing_meta`.** `MCPToolAdapter` already reads
  `routing_meta["requires_confirmation"]` (`adapter.py:10-18`) — extend that channel
  rather than inventing a parallel metadata model.
- **One injection point for auth.** The merge centralized authentication in
  `_guard` (`streamable_http.py:530`). Resolve the principal there, not in each handler.
- Async-first throughout; Pydantic models for all structured data; `self.logger`, never
  `print`.
- Google-style docstrings and strict type hints on every new function and class.

### Known Risks / Gotchas

- **Reification leaking into the agent (OQ2).** The one real cost of Option D: a
  decorated method *could* become LLM-callable inside its own agent if registered into
  `ToolManager`. Mitigation: the exposure set is a separate collection, and
  `test_reified_tool_not_in_tool_manager` is a merge-blocking assertion.
- **Bound-method reference cycles.** `AgentMethodTool` must not drag the agent into
  tool-serialization paths — use a weak reference / careful bound-method handling.
- **Stale agent after reload (OQ5).** `BotManager.reload_agent()` (`manager.py:856`)
  swaps `self._bots[name]` **and `_safe_cleanup()`s the old instance**, so a held object
  reference serves a closed agent. Mitigation: hold by name, resolve per call, rebuild
  the exposure set on reload. In-flight calls against the old instance are unaffected
  (documented at `manager.py:868-872`).
- **The brainstorm's line anchors are stale.** PR #1274's review-findings commit
  (`d7434be92`, S-01…S-15) renamed `SessionEventStore` → `StreamBuffer` and shifted most
  offsets. §6 is authoritative; the brainstorm is not.
- **Silent multi-worker breakage.** An in-process session map fails *intermittently*
  under gunicorn — the worst failure mode. Mitigation: fail closed on store
  unavailability; never fall back to a local dict.
- **Aggregate-endpoint collisions.** Two agents exposing the same tool name are
  disambiguated by the `{agent}__` prefix; an agent whose own name contains `__` must be
  rejected at mount time.
- **Oversized results.** Truncation must be *stated* in the response so the model does
  not silently reason over a clipped list.
- **`base_path` double-claim.** `_check_base_path_conflicts` (`parrot_server.py:121`)
  raises when two transports share a path — the agent mount must claim a distinct one.
- **No shadow mode.** Do not plan a dry-run rollout on `enforcing: false`; it is not
  audit-only. PBAC is enforced from day one.
- **Revocation latency.** Introspection-with-cache bounds revocation at ~5 minutes
  (`oauth_server.py:317`). Acceptable for v1 and stated here so it is a known property,
  not a surprise.
- **Cross-repo timing.** navigator-auth FEAT-095 is approved but unreleased (1.4.0).
  Build against the specified contract; mock introspection/PRM in CI; keep one live
  conformance run as a post-release gate.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2` | mandatory `args_schema` / `returns` models — already core |
| `aiohttp` | current | transport + parent-app mount — already core |
| `navigator-auth` | `>0.20.9` | RFC 7662 introspection, RFC 9728 builder, ABAC PDP — already core (`pyproject.toml:83`) |
| `redis.asyncio` | current | shared session store + job handles — already used by HITL |
| `mcp` (official SDK) | test-only | interop client behind the existing `requires_mcp_sdk` marker |

**Deployment**: the endpoint must be publicly routable for Claude Web, and **Redis
becomes a hard requirement** for agent MCP endpoints (sessions + job handles).

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks run sequentially in one worktree.
- **Shape**: one sequential head followed by a fan-out. **M1 is a hard dependency of
  M2, M3 and M4.** M5 and M6 are self-contained and depend on nothing in this feature.

```
M1 decorator + reification  (core)
   ├── M2 mount + resources
   ├── M3 identity / PBAC / audit
   └── M4 job handles
M5 PRM endpoint      ── independent
M6 Redis session store ── independent (also fixes the tool-level endpoint)
```

- **Rationale for one worktree**: M2 and M3 share the mount's contract and edit the same
  handful of files in `parrot/mcp/` — files PR #1274 has just rewritten. The head task
  blocks the others anyway, so sequential tasks cost little and avoid merge churn.
- **Cross-feature dependencies**:
  - `claude/mcp-http-streamable-transport-bptepy` — **already merged** (PR #1274,
    `e92d549f1`). Satisfied.
  - FEAT-476 (`agentchat-migration`) is in flight but touches only
    `ui/src/lib/oauth/popup.ts` in this feature's areas — **verified: no collision** with
    `manager/manager.py` or `parrot/mcp/`. The brainstorm flagged `manager.setup()` as a
    plausible collision point with FEAT-475; FEAT-475 is merged and did not touch it.
  - navigator-auth FEAT-095 — build against the contract; live verification is
    post-release.

```bash
git worktree add -b feat-477-mcp-as-agent \
  .claude/worktrees/feat-477-mcp-as-agent HEAD
```

---

## 8. Open Questions

> All questions are resolved. The first thirteen were settled in brainstorm Rounds 0–3,
> OQ1–OQ8 in a follow-up pass on 2026-08-31, and the final three at `/sdd-spec` time.

### Resolved in the brainstorm (Rounds 0–3)

- [x] Flow type and base branch — *Resolved in brainstorm*: `type: feature`,
      `base_branch: dev`. → frontmatter.
- [x] Which agent surface becomes MCP tools in v1? — *Resolved in brainstorm*: decorated
      methods **and** the agent's own tools **and** agent metadata as MCP resources;
      `ask()` is NOT exposed. → §1 Non-Goals, §2 Overview, §3 M1–M2.
- [x] Which authentication path? — *Resolved in brainstorm*: navigator-auth as the
      external OAuth 2.1 AS; validate via introspection (`AuthMethod.OAUTH2_EXTERNAL`).
      → §2 Overview #4, G2.
- [x] Relationship to the streamable-HTTP branch? — *Resolved in brainstorm*: merge it
      to `dev` first; this feature bases on `dev`. → satisfied by PR #1274; Worktree
      Strategy.
- [x] Long-running calls? — *Resolved in brainstorm*: job handle (`start_*` → `job_id`,
      `*_status`, `*_result`). → §3 M4, G7.
- [x] Mount topology? — *Resolved in brainstorm*: per-agent endpoints plus an optional
      aggregate with `{agent}__{tool}` prefixes; one canonical PBAC resource.
      → §2 Overview #2, §3 M2.
- [x] Is PBAC in v1? — *Resolved in brainstorm*: yes — filter `tools/list`, re-verify
      `tools/call`. → §3 M3, G6.
- [x] Where does the decorator live? — *Resolved in brainstorm*: core `ai-parrot`,
      importable with no extras, MCP-only semantics. → §3 M1, G9.
- [x] Job store? — *Resolved in brainstorm*: reuse `SuspendedExecutionStore` semantics.
      → §3 M4, §6.
- [x] Principal propagation? — *Resolved in brainstorm*: contextvar — concretely the
      existing `_pctx_var` (`auth/context.py:33`). → §2 Overview #4, §3 M3.
- [x] Agent opt-in? — *Resolved in brainstorm*: implicit — any agent with at least one
      decorated method. → §2 Overview #3.
- [x] Response-size policy? — *Resolved in brainstorm*: enforced in the adapter layer
      (mandatory pagination on lists, `exclude_none`, per-tool cap). → §3 M3, G8.
- [x] Tenant binding? — *Resolved in brainstorm*: per `(tenant_id, principal)`.
      → §2 Data Models, G10.

### Resolved in the follow-up pass (2026-08-31)

- [x] **OQ1 — Who ships the RFC 9728 protected-resource metadata?** — *Resolved
      (confirmed by navigator-auth FEAT-095 D6)*: **AI-Parrot serves its own PRM
      document, in this feature**, consuming navigator-auth's builder.
      → §3 M5, G4.
- [x] **OQ2 — Reification vs LLM-callability?** — *Resolved*: **MCP-only, no opt-in.**
      A reified `@mcp_tool` method is never registered into the owning agent's
      `ToolManager`. → §2 Overview #1, §3 M1, merge-blocking test in §4/§5.
- [x] **OQ3 — Which `AuditLedger`?** — *Settled by the code*:
      `parrot.security.audit_ledger.AuditLedger` (`:296`). `parrot/auth/audit.py:1` is
      explicitly *"DEPRECATED"*. → §6 Verified Imports.
- [x] **OQ4 — Single-worker constraint?** — *Resolved*: **no — a Redis-backed
      session/event store lands in this feature** (reconfirmed at `/sdd-spec` time,
      below). → §3 M6, G5.
- [x] **OQ5 — Agent reload?** — *Settled by the code*: hold agents **by name**, resolve
      per call; `reload_agent()` `_safe_cleanup()`s the old instance. → §3 M2, §7 Risks.
- [x] **OQ6 — navigator-auth scopes, claims and the activation gate?** — *Resolved
      against FEAT-095 (approved)*: **coarse upstream / fine downstream.** The
      activation gate lives entirely in navigator-auth at `/oauth2/authorize`, keyed
      `(user_id, client_uid)` — **nothing to build here**. Because Claude registers a
      single client, that gate *cannot* express a per-agent grant, so **per-agent and
      per-tool authorization exist only in ai-parrot's PBAC layer** — which makes M3
      load-bearing, not defense-in-depth. Audience is enforced via
      `ExternalOAuthValidator.resource_server_url`. → §2 Overview #4–5, §3 M3/M5, G3/G6.
- [x] **OQ7 — MCP tool annotations?** — *Resolved*: **ride `routing_meta`**;
      `requires_confirmation` maps to `destructiveHint`, while `readOnlyHint` /
      `idempotentHint` are declared explicitly on the decorator. → §2 Data Models, §3 M1.
- [x] **OQ8 — Which agent metadata becomes an MCP resource?** — *Resolved*: **three** —
      identity card, policy-filtered tool catalog, and KB descriptors. The system prompt,
      `backstory` and `rationale` are **excluded outright** — never served, not
      policy-gated. → §3 M2, merge-blocking test in §4/§5.
      *(Note: the brainstorm's User-Facing Behavior prose says "four MCP resources" but
      enumerates three; OQ8's later revision is authoritative — it is **three**.)*

### Resolved at `/sdd-spec` time (2026-08-31)

- [x] **Where does `tenant_id` come from in the introspection response?** —
      *Resolved: jesuslarag*: a **dedicated claim with a mount fallback**. Precedence:
      `token_info["tenant_id"]` → `token_info["org_id"]` →
      `AgentMCPMountConfig.default_tenant_id`. If none yields a value, **fail closed**
      with a 401 audited as `principal_unresolved`. **`client_id` is never used as a
      tenant** in any of its three FEAT-095 meanings. This closes the sub-item OQ6
      carried forward. → §2 Data Models, §3 M3, G10, `test_tenant_id_precedence_and_fail_closed`.
- [x] **Does the Redis session store (OQ4) stay in this feature?** — *Resolved:
      jesuslarag*: **yes, keep it here** as M6. Agent MCP endpoints are unusable under
      the project's standard gunicorn deploy without it, so it is a prerequisite for the
      acceptance criteria rather than a follow-up. → §3 M6, G5.
- [x] **Target version?** — *Resolved: jesuslarag*: **0.30.0**, leaving 0.29.0 to
      in-flight work. → header.

### Carried forward as stated design properties (not open)

- **Introspection vs JWKS**: introspection-with-cache is the v1 default; JWKS is an
  optimization to revisit. Revocation latency is bounded at ~5 minutes
  (`oauth_server.py:317`). → §2 Overview #7, §7 Risks.
- **No PBAC shadow mode** exists in either repo; `enforcing: false` is not audit-only.
  No task may assume a safe observation period. → §1 Non-Goals, §7 Risks.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-31 | Jesus Lara | Initial draft from `mcp-as-agent.brainstorm.md` (Option D). Codebase contract re-verified post-PR-#1274; corrected stale anchors (`SessionEventStore` → `StreamBuffer`, centralized `_guard`). Resolved `tenant_id` precedence, M6 scoping and target version. |
