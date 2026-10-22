---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
feature_id: FEAT-622
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-server]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [agentstudio, toolkits, multi-tenant, host-integration, tool-scope, tooling-policy]
---

<!-- LANGUAGE: This document MUST be written entirely in English (proper nouns keep native spelling). -->

# Feature Specification: Agent Studio — Host Toolkits

**Feature ID**: FEAT-622
**Date**: 2026-09-30
**Author**: Juan Ruffato (with Claude), for review by Jesus Lara
**Status**: approved (v0.2.2, 2026-09-30) — open questions resolved or deferred as non-blocking; ready for `/sdd-task`. Feature ID to be reserved by the maintainer.
**Target version**: ai-parrot 1.0.7 + ai-parrot-server 1.0.7 (lockstep)
**Inputs**: FieldSync `sdd/proposals/fieldsync-agent-toolkits.brainstorm.md`
(upstream asks U1 and U2, F1–F3, Q1–Q3, Q10); FieldSync
`artifacts/agentstudio/command-board-2026-09-30.md` (J8, J9, J11); Jesus's
review `agentstudio_host_integration_review.md` (findings R1, R3, R6, R7 and
"Package decisions and sequencing").
**Package siblings** (same review package):
- `sdd/specs/agentstudio-tenant-visibility.spec.md`: FEAT-605 v0.2.1. It produces `studio_scope`
  and requires this spec's policy, scope enforcement and confirmation rule on its routes (its C35, C36).
- `sdd/specs/agentstudio-db-storage.spec.md`: the storage spec. It owns `navigator.ai_agent_tooling`,
  the immutable Studio `agent_id`, the Studio runtime that builds agents, and the
  tenant-safe key/vault-name scheme this spec consumes (§2 "Tenant-safe identity keys").
- The exact shared names are in "Cross-spec contract (package)" below, identical in all three specs.

**Snapshot**: ai-parrot `dev` @ `3f0f2f726` (v0.1). The v0.2 additions were re-verified on the
package branch tree @ `8268c0911`; core paths are under `packages/ai-parrot/src/parrot/`, server
paths under `packages/ai-parrot-server/src/parrot/`.

---

## 1. Motivation & Business Requirements

### Problem Statement

A host application (FieldSync first) mounts Agent Studio and needs its
authors to attach **host-owned toolkits**, for example "events of my
programme" or "my team". Those tools read tenant data. Tenant authors must
also be prevented from attaching anything that runs code or reaches
resources the host did not approve.

**P1: Studio cannot see host toolkits on most paths.** Discovery has two
strategies (`parrot/tools/discovery.py`):

- `discover_from_registry()` reads `TOOL_REGISTRY` dicts. It **skips**
  `plugins.tools`, because that source is in `WALK_SOURCES` (`:28`, `:44-45`).
- `discover_all()` also walks `plugins.tools.*` (`:111-136`).

Each Studio path picks one strategy on its own:

| Studio path | Resolver used today | Sees `plugins.tools`? |
|---|---|---|
| `GET /catalog/tools` (`catalog.py:230` → `tools_catalog._build_catalog`) | `parrot_tools.TOOL_REGISTRY` only (`tools_catalog.py:34`, `:56`) | no |
| `GET /toolkits/{slug}/schema` (`toolkits.py:237-256`) | `_resolve_toolkit_class` → `discover_from_registry` (`toolkits.py:156-180`) | no |
| `POST /agents/{name}/toolkits` generic (`toolkits.py:443-459`) | same | no |
| FEAT-593 `GET/PUT …/toolkits/{slug}`, `/options/{param}`, `/toolkits/{slug}/me` | `AgentToolingStore.schema_for` → `_EXPLICIT` or `_resolve_toolkit_class` (`tooling_store.py:138-144`; callers `toolkit_config.py:146`, `toolkit_overrides.py:83-91`) | no |
| Bot build from a persisted `ToolkitSpec` | `AbstractBot._resolve_spec_class` → `discover_from_registry` (`interfaces/tools.py:177-186`) | no. The spec is dropped: "unknown slug, skipped" (`:202`) |
| `POST /agents/{name}/tools` (live assign) | `_resolve_registry_class` → `discover_all` (`testing.py:92-119`, `:458`) | yes |
| `POST /tools/{slug}/execute` | same (`testing.py:363`). Toolkits are rejected (`:364-368`) | yes, `AbstractTool` only |

A host toolkit is therefore missing from the catalogue, has no schema,
cannot be configured, and is dropped when the bot is built. Yet it *can* be
attached to a live agent through `POST /agents/{name}/tools`. Five
resolvers exist where there should be one.

**P2: a tool cannot learn the agent's tenant or its caller.**

- `AbstractBot.session()` binds a `RequestContext` to a ContextVar
  (`bots/abstract.py:4185-4266`). `current_context()`
  (`utils/helpers.py:58-65`) can read it anywhere in the call stack.
- Test chat (`testing.py:270`) and normal chat (`chat.py:455`) put only
  `request`, `app` and `llm` in it. The meta-agent path does the same
  (`meta_agent.py:110`).
- `PermissionContext.tenant_id` defaults to the principal
  (`auth/permission.py:166-205`). Test chat passes no permission context at
  all. So it cannot be used for tenancy.
- A toolkit instance has no back-reference to its agent. One instance serves
  every concurrent caller of a shared agent. The existing
  `_current_pctx`-on-instance pattern is explicitly *not* to be extended
  (`tools/abstract.py:59-75`).
- `POST /tools/{slug}/execute` runs `instance.execute()` outside any
  `bot.session()` (`testing.py:393`), so `current_context()` is `None` there.
- The FEAT-593 options handler builds the toolkit and calls
  `config_options()` without a context either (`toolkit_config.py:157-158`).

**P3: server-managed params are hard-coded.** Two dicts decide them:

- `_SERVER_MANAGED` (`tooling_store.py:40-43`), with entries for `wiki` and
  `infographic` only;
- `_KNOWN_APP_DEPS` (`testing.py:42-44`), with `artifact_store` only.

A host cannot declare that a parameter is server-owned. There is a second
gap: the `config_model` schema path ignores `server_managed` altogether
(`config_schema.py:122-143` against `:146-160`).

**P4: declarative tenant tooling can start processes (review R1).**

- `AgentMCPServerSpec` accepts `transport`, `command`, `args` and arbitrary
  `params` (`tools/spec.py:35-49`). `AgentToolingStore.put_mcp_servers`
  validates that shape and nothing else (`tooling_store.py:204-245`).
- `hydrate_mcp` dumps the top-level fields and then applies
  `base.update(spec.params)` (`tools/spec.py:187-189`), so `params` override
  `transport`, `command`, `args`. Vault values are applied last, by field
  name, for every `secret_refs` key (`:190-196`).
- `apply_tooling_specs` builds `MCPServerConfig(**kwargs)` and connects
  (`interfaces/tools.py:249-254`). `MCPServerConfig` is `MCPClientConfig`
  (`mcp/client.py:133`), whose default transport is `"auto"`; auto-detection
  picks `unix` for a `socket_path` and `stdio` for a `command`
  (`mcp/integration.py:374-390`). The stdio session runs
  `asyncio.create_subprocess_exec` with the command and the server's full
  environment (`server mcp/transports/stdio.py:153-165`).
- Built-ins are no safer: `parrot_tools.TOOL_REGISTRY` exposes `shell`
  (`parrot_tools/__init__.py:163`), `python_execution`, `file_operations`,
  `code_interpreter` (`:42-44`), `docker` (`:57`) and `local_git` (`:173`) to
  every Studio author through the catalogue, assign and execute paths.

**P5: the proposed scope gate does not cover every path (review R6).**
`ToolkitTool._execute` (`toolkit.py:142-201`) acquires resources
(`_ensure_open`, `:168`) *before* `_pre_execute` (`:179`). Standalone
`AbstractTool` subclasses never run `ToolkitTool._execute`, and they are the
only kind `/tools/{slug}/execute` accepts (`testing.py:363-393`). The options
handler calls `config_options()` directly (`toolkit_config.py:157-158`).

**P6: `confirming_tools` is metadata only (review R7).** It sets
`routing_meta["requires_confirmation"]` (`toolkit.py:692-699`). `ToolManager`
consults a `ConfirmationGuard` only if one is installed and otherwise proceeds
(`manager.py:1813-1849`, `:2009-2044`). `/tools/{slug}/execute` never goes
through `ToolManager.execute_tool`.

**P7: override keys and vault names collide across tenants (review R3).**
Overrides are keyed `(user_id, agent_id, slug)`, but every caller passes the
bare agent **name** as `agent_id` (`toolkit_persistence.py:28-55`;
`toolkit_overrides.py:109`, `:157`, `:183`; runtime `handlers/agent.py:1099`).
The session revision marker is `f"{agent.name}_toolkit_overrides_rev"`
(`agent.py:1102`). Agent vault names are `toolkit_<slug>_<name>` and
`mcp_agent_<server>_<name>` (`tools/spec.py:62-70`, used at
`tooling_store.py:201`, `:221`, `:263`); override secrets use
`toolkit_<slug>_<name>_user` (`toolkit_overrides.py:170`, `:200`).

### Goals

- **G1: one shared resolver.** Every Studio path and the bot build resolve
  toolkit slugs through a single resolver:
  - catalog, schema, assign, FEAT-593 config, per-user override, options;
  - bot build, live assign, execute.

  The resolver honours a declarative `plugins.tools.TOOL_REGISTRY`. The
  registry is never patched at runtime.
- **G2: tool context contract.** A tool reads the agent's scope (tenant,
  owner, visibility) and the **caller's** identity from `studio_scope`
  through one accessor. `studio_scope` is produced by FEAT-605 v0.2.
  The accessor works in test chat, normal chat, execute and options.
- **G3: fail closed, automatically.** A tenant-bound tool, toolkit method or
  options provider refuses with one standard error, `ToolScopeUnavailable`,
  when there is no request (scheduler, A2A), no scope, no tenant, or a tenant
  mismatch. The base classes enforce it before any resource acquisition or
  method body, on every entry point (agent run, direct execute, options). A
  host cannot forget the check.
- **G4: declarative server-managed params.** A toolkit or tool declares them
  in a `ClassVar`. They are never user-configurable and never read from
  client JSON or from the LLM, for generated and custom argument schemas
  alike. The ClassVar replaces `_SERVER_MANAGED`. The built-in toolkits
  migrate to it.
- **G5: host toolkit conventions.** A host slug prefix, a read/write marker
  on every tool, Pydantic return types, and row caps.
- **G6: host-owned tenant tooling policy.** `TenantToolingPolicy` decides
  which toolkits, built-in tools and MCP servers a tenant author may use. It
  is applied to the **final normalised** configuration on every write,
  activation and build. Tenant-supplied local execution is denied by default.
- **G7: host writes are approved or not executed.** A host write tool runs
  only with an approval from a supported confirmation mechanism. When no
  guard or channel exists, it performs zero writes.
- **G8: tenant-safe identity keys.** Toolkit overrides, vault names and
  override revision markers of Studio agents are keyed by the storage tooling
  ref `studio-agent:<agent_id>` (the immutable Studio `agent_id`), never by the
  bare name.

### Non-Goals (explicitly out of scope)

- Storage of toolkit config and the key/vault-name **scheme**. Agent-level
  tooling moves to `navigator.ai_agent_tooling`, which the storage spec owns,
  together with the scheme itself. This spec requires that neither `config`
  nor `secret_refs` ever contains a server-managed key, and it consumes the
  scheme (§2 "Tenant-safe identity keys"). Secret **values** and per-user
  overrides **stay in the DocumentDB vault** until storage M12 (its phase 2,
  §2.10 there) moves them to Postgres under the same names. Keeping DocumentDB
  is acceptable; keeping bare-name keys for Studio agents is not, and that
  change lands in v1 (storage M13 in its W1), not in phase 2.
- Building or authorizing `studio_scope` (tenant resolution, visibility,
  `may_author`). FEAT-605 v0.2 owns that.
- Tenant authorization of non-Studio runtime routes (FEAT-605 non-goal,
  unchanged). This spec only *binds* the scope in normal chat, so that tools
  can refuse.
- Executing a single toolkit *method* through `POST /tools/{slug}/execute`
  (see Q4).
- Any FieldSync toolkit. Those are FieldSync specs S1–S4.
- A scheduler or A2A principal for tenant-bound tools. They refuse in this
  spec (FieldSync Q7).
- A human-in-the-loop **UI** for Studio test chat. This spec defines the fail-
  closed rule and the approval token; which channel a host offers is P-Q2.
- Per-user MCP servers outside Studio (`UserMCPServerConfig`, `mcp/registry.py`).
  They are not tenant-authored agent configuration.

---

## 2. Architectural Design

### Overview

Five small pieces are added to ai-parrot core, and the server wires them
into its entry points:

1. **`ToolkitResolver`** (`parrot/tools/resolver.py`, new) is the one
   slug → class authority. It merges three sources:
   - the built-in explicit entries (`dataset_manager`, `wiki`, `infographic`);
   - `parrot_tools.TOOL_REGISTRY`;
   - the host's declared `plugins.tools.TOOL_REGISTRY`, which must carry
     `HOST_TOOL_PREFIX`.

   It never mutates a registry. It rejects host slugs that collide with
   built-ins or lack the prefix. It exposes `resolve(slug)`, `entry(slug)` and
   `entries()` (for the catalogue and the policy).
2. **Tool scope contract** (`parrot/tools/scope.py`, new):
   - `ToolScopeView` Protocols describe what a tool may read from
     `current_context().kwargs["studio_scope"]`.
   - `current_tool_scope()` and `require_tool_scope()` read it.
   - `ToolScopeUnavailable` is the standard refusal.
   - **Automatic enforcement** for every tenant-bound tool (standalone
     `AbstractTool`, toolkit-generated `ToolkitTool`) at the top of
     `AbstractTool.execute`, before `_ensure_open`, validation or `_execute`;
     and for every tenant-bound options provider, by wrapping
     `config_options` at class creation (§2 "Scope enforcement").
3. **`server_managed_params`** is a ClassVar on `AbstractToolkit` (and on
   `AbstractTool`) that maps a param name to a `ServerParam(source, key)`:
   - A **constructor** param is marked `x-server-managed` in every schema,
     rejected on PUT and on override, and filled by the server at
     construction.
   - A **method** param is absent from every LLM args schema (generated or
     custom) and filled per call from the scope.
4. **`TenantToolingPolicy`** (`parrot/tools/tooling_policy.py`, new): the
   host-registered allow-list for tenant tooling, the one write hook that
   storage and the FEAT-593 handlers call, and the build hook in
   `apply_tooling_specs`, which the storage builder feeds through
   `AbstractBot.bind_tooling_policy` (§2 "Tenant tooling policy", "Build-hook
   plumbing").
5. **Enforced confirmation for host writes** (`parrot/auth/confirmation.py`,
   `tools/manager.py`, `tools/abstract.py`): a per-call approval token set
   only by `ToolManager` after a `ConfirmationGuard` decision of
   `confirmed`, checked by `AbstractTool.execute` (§2 "Host-write
   confirmation").

### Component Diagram

```
host plugins/tools/__init__.py            parrot_tools.TOOL_REGISTRY     built-in explicit
  TOOL_REGISTRY {"fs_events": "..."}               │                    (wiki, dataset_manager,
  HOST_TOOL_PREFIX = "fs_"                         │                     infographic)
            └──────────────┬───────────────────────┴───────────────────────┘
                           ▼
              ToolkitResolver (parrot/tools/resolver.py)  ◀── one process-wide instance
     ┌─────────┬──────────┬──────────┬───────────┬────────────┬──────────┬──────────┐
  catalog   schema    assign    FEAT-593     override     options    bot build   live assign
                                config                                (apply_      / execute
                                                                      tooling_specs)

host startup: set_tenant_tooling_policy(app, TenantToolingPolicy(...))
   every tenant write / activation ─▶ enforce_tenant_tooling(app, tooling, subject=...)  ─▶ refuse before persist/vault
   every tenant build ─▶ bot.bind_tooling_policy(policy, subject) ─▶ bot.configure(app) ─▶ apply_tooling_specs()
                           └─ hydrate_mcp(spec) ─▶ policy.resolve_mcp(final kwargs) ─▶ MCPServerConfig ─▶ connect

FEAT-605 v0.2 builds studio_scope ──▶ bot.session(..., studio_scope=scope)   [test chat, meta-agent]
                                  ──▶ this spec binds it                      [chat.py, execute, options]
                                            │
                                            ▼  current_context().kwargs["studio_scope"]
  AbstractTool.execute ─▶ (tenant_bound?) require_tool_scope()      ◀── before ANY side effect
                       ─▶ (strict confirm?) approval token matches  ◀── else zero writes
                       ─▶ drop client/LLM server-managed args ─▶ _ensure_open ─▶ validate ─▶ fill from scope
                       ─▶ _execute (ToolkitTool: _pre_execute host cross-check ─▶ method) ─▶ Pydantic result
  options handler ─▶ ensure_tool_scope(cls) ─▶ hydrate/construct ─▶ config_options (wrapped: gate first)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `discovery.discover_from_registry` (`discovery.py:31`) | uses | The resolver reads declared registries itself. `discover_*` keep their signatures for `ToolManager`. |
| `AbstractBot._resolve_spec_class` (`interfaces/tools.py:177`) | modifies | Delegates to the resolver. `apply_tooling_specs` fills constructor server-managed params (`:242`). |
| `AbstractBot.apply_tooling_specs` (`interfaces/tools.py:188-262`) | modifies | New keyword-only `tooling_policy`, `tooling_subject` (explicit kwargs, else the values bound by the new `bind_tooling_policy`, §2 "Build-hook plumbing"); `check_tool` before each class construction (`:200`) and `resolve_mcp` between `hydrate_mcp` and `MCPServerConfig` (`:251-252`). The no-argument call in `AbstractBot.configure()` (`bots/abstract.py:1524`) is unchanged. |
| `hydrate_mcp` (`tools/spec.py:187`) | modifies | Vault values may fill only `MCP_SECRET_FIELDS`; any other `secret_refs` key raises before return. |
| `_resolve_toolkit_class` (`toolkits.py:156`), `_resolve_registry_class` (`testing.py:92`), `_EXPLICIT` (`tooling_store.py:39`) | replaces | Thin shims that call the resolver, so imports and tests keep working. |
| `tools_catalog._build_catalog` (`tools_catalog.py:44`) | modifies | Iterates `resolver.entries()`. Adds `source` and `access` per entry; a tenant partition lists only entries its policy permits. |
| `_SERVER_MANAGED` (`tooling_store.py:40`), `_KNOWN_APP_DEPS` (`testing.py:42`) | replaces | Read from the ClassVar. The dicts are deleted once the built-ins declare it. |
| `introspect_config_schema` / `model_config_schema` (`config_schema.py:92`, `:122`) | modifies | Both honour the ClassVar (this closes the model-path gap). |
| `AbstractTool.execute` (`abstract.py:881-1210`) | modifies | Scope gate and strict-confirmation check right after the special kwargs are popped (`:904-912`) and before `_ensure_open` (`:976`); server-managed drop and fill around `validate_args` (`:982`); error metadata (`:1201-1206`). |
| `ToolkitTool._execute` (`toolkit.py:142-201`), `_generate_args_schema_from_method` (`toolkit.py:95`), `_create_tool_from_method` (`toolkit.py:655-700`) | modifies | No gate of its own (the inherited `execute` gates first). Args-schema exclusion; custom `_args_schema` validation; host-write routing meta. |
| `AbstractToolkit.__init_subclass__` / `AbstractTool.__init_subclass__` | adds | Compute effective `tenant_bound`; wrap `config_options`; refuse scope-sourced constructor params and custom schemas that expose server-managed names. |
| `ToolManager.execute_tool` confirmation blocks (`manager.py:1813-1849`, `:2009-2044`) and dispatch (`:2048-2061`) | modifies | After a `confirmed` decision, sets the approval ContextVar around `tool.execute`. Without a guard, nothing is set. |
| `ConfirmationGuard` (`auth/confirmation.py:378`) | uses | Already fail-closed without a `human_manager` (its step 3). |
| `AgentToolingStore.put_toolkit` / `put_mcp_servers` / `delete_toolkit` (`tooling_store.py:177-245`) | modifies | `enforce_tenant_tooling` before `_split_secrets` or any vault write; storage-scheme vault names for Studio agents. |
| `StudioUserToolkitOverrideHandler` (`toolkit_overrides.py:76-205`), `ToolkitConfigService` (`toolkit_persistence.py:28`), `_apply_user_toolkit_overrides` (`handlers/agent.py:1082-1125`) | modifies | Studio agents key overrides, override vault names and the revision marker by `agent_id`. |
| `StudioTestingHandler.post` (`testing.py:270`), `meta_agent.py:110` | consumes | FEAT-605 v0.2 passes `studio_scope=`. This spec only asserts it (see §6). |
| `chat.py:455`, `StudioToolExecuteHandler` (`testing.py:340-394`), `StudioToolkitOptionsHandler` (`toolkit_config.py:130-170`) | modifies | Bind a `RequestContext` carrying `studio_scope` (built with FEAT-605's builder); execute and options call `ensure_tool_scope(cls)` before construction. |
| MCP `read_only_hint` (`mcp/agent_tools.py:47`) | mirrors | The read/write marker uses the same semantics. |

### Data Models

```python
# parrot/tools/scope.py (new) — ai-parrot core; imports nothing from ai-parrot-server.
ToolAccess = Literal["read", "write"]

class CallerView(Protocol):            # satisfied by FEAT-605 RequestScope (user_id, tenant, groups, is_superuser)
    user_id: str | None
    tenant: str | None
    groups: frozenset[str]
    is_superuser: bool

class AgentScopeView(Protocol):        # satisfied by FEAT-605's StudioAgentRef
    agent_id: UUID | None              # immutable Studio id; None for non-Studio bots
    name: str
    owner: str | None
    tenant: str | None
    visibility: str                    # "private" | "tenant" | "groups"

class ToolScopeView(Protocol):         # REQUIRED shape of current_context().kwargs["studio_scope"] (FEAT-605 v0.2)
    caller: CallerView
    agent: AgentScopeView | None       # None only on agent-less calls (execute)

ScopeRefusal = Literal[
    "no_context",           # no RequestContext / no request: scheduler, A2A, background task, remote worker
    "no_scope",             # context present, studio_scope absent (host installed no resolver)
    "no_tenant",            # caller.tenant is None
    "agent_tenant_unset",   # agent present with tenant None (storage GLOBAL-partition row, tenant NULL)
    "tenant_mismatch",      # agent.tenant != caller.tenant
    "host_tenant_mismatch", # raised by host code: scope disagrees with the host's own validated tenant
]

class ToolScopeUnavailable(Exception):
    code: ClassVar[str] = "tool_scope_unavailable"
    def __init__(self, reason: ScopeRefusal, *, tool_name: str | None = None) -> None: ...

# parrot/tools/server_params.py (new)
class ServerParam(BaseModel, frozen=True):
    source: Literal["server", "app", "tenant", "caller", "agent"]
    key: str | None = None             # app key, required when source == "app"

# parrot/tools/tooling_policy.py (new) — see §2 "Tenant tooling policy"
TenantMCPTransport = Literal["http", "sse", "streamable-http"]   # stdio/unix/quic/websocket/grpc are not expressible

class HostMCPServer(BaseModel, frozen=True):
    name: str                          # the name a tenant spec references
    config: dict[str, Any]             # host-owned MCPServerConfig kwargs; may be stdio (host-owned command)
    tenant_fields: frozenset[str] = frozenset({"allowed_tools", "blocked_tools", "description"})

class ToolingSubject(BaseModel, frozen=True):
    tenant: str | None                 # partition tenant; None only for the GLOBAL partition
    agent_id: UUID | None              # None before the row exists (create, draft save)
    actor: str | None                  # authenticated user on writes; None at build
    phase: Literal["write", "activate", "build", "attach", "execute"]

ToolingRefusal = Literal[
    "local_execution",           # stdio/unix transport (explicit or auto-detected), or non-empty command/args/env/socket_path
    "transport_not_permitted",   # any transport outside policy.mcp_transports
    "endpoint_not_allowed",      # url missing or not under an allow-listed prefix
    "mcp_server_unknown",        # reserved: a named reference in a form only host servers use
    "field_not_permitted",       # a key outside the tenant-settable MCP fields, or a host server's non-tenant field
    "secret_ref_not_permitted",  # client/bundle-supplied secret_refs/vault_owner; a vault name outside the agent's namespace
    "builtin_not_permitted",     # built-in / parrot_tools / walked slug not in policy.builtin_tools
    "toolkit_unavailable",       # the slug does not resolve (or its host entry was rejected)
]

class TenantToolingRefused(Exception):
    code: ClassVar[str] = "tooling_not_permitted"   # HTTP 422 on writes and assign, 403 on execute
    def __init__(self, reason: ToolingRefusal, *, item: str) -> None: ...
```

### New Public Interfaces

```python
# parrot/tools/resolver.py (new)
class ToolkitEntry(BaseModel, frozen=True):
    slug: str
    dotted_path: str | None            # None for built-in explicit entries
    source: Literal["builtin", "parrot_tools", "host", "walk"]

class ToolkitResolver:
    def entries(self) -> list[ToolkitEntry]: ...
    def entry(self, slug: str) -> ToolkitEntry | None: ...   # case-insensitive
    def resolve(self, slug: str) -> type | None: ...         # case-insensitive, like today
    def reload(self) -> None: ...                            # tests / hot reload only

def get_toolkit_resolver() -> ToolkitResolver: ...            # process-wide, lazily built

# parrot/tools/scope.py (new)
def current_tool_scope() -> ToolScopeView | None: ...
def require_tool_scope(*, tool_name: str | None = None) -> tuple[str, ToolScopeView]: ...
    # returns (tenant, scope) or raises ToolScopeUnavailable
def is_tenant_bound(cls_or_instance: type | object) -> bool: ...   # effective flag (§2 "Scope enforcement")
def ensure_tool_scope(cls_or_instance: type | object, *, tool_name: str | None = None) -> None: ...
    # no-op when not tenant-bound; otherwise require_tool_scope() — used by handlers before construction

# parrot/tools/tooling_policy.py (new)
class TenantToolingPolicy(BaseModel, frozen=True):
    mcp_servers: Mapping[str, HostMCPServer] = {}
    mcp_endpoints: tuple[str, ...] = ()          # absolute https URL prefixes, normalised at construction
    mcp_transports: frozenset[TenantMCPTransport] = frozenset({"http", "sse", "streamable-http"})
    builtin_tools: frozenset[str] = frozenset()  # built-in / parrot_tools slugs and tool names tenants may use
    host_toolkits: bool = True                   # resolver entries with source="host"
    apply_to_global: bool = False                # also police the GLOBAL partition (no resolver)

    @classmethod
    def deny_all(cls) -> "TenantToolingPolicy": ...     # the default: host toolkits only, no MCP, no built-ins
    def check_tool(self, slug: str, *, subject: ToolingSubject) -> None: ...
    def resolve_mcp(self, config: Mapping[str, Any], *, subject: ToolingSubject) -> dict[str, Any]: ...
    def check_tooling(self, tooling: NormalizedTooling, *, subject: ToolingSubject) -> None: ...

def effective_mcp_config(spec: AgentMCPServerSpec) -> dict[str, Any]: ...
    # exactly what hydrate_mcp returns, minus the vault read: top-level dump, then params, then each
    # secret_refs field present as a key (value = SECRET_MASK)
def set_tenant_tooling_policy(app: MutableMapping[str, Any], policy: TenantToolingPolicy) -> None: ...
def get_tenant_tooling_policy(app: Mapping[str, Any]) -> TenantToolingPolicy: ...
def enforce_tenant_tooling(
    app: Mapping[str, Any],
    tooling: NormalizedTooling,
    *,
    subject: ToolingSubject,
) -> None: ...
    # THE write/activation hook. Pure and synchronous: no I/O, no vault, no process.
    # Raises TenantToolingRefused; no-op only when subject.tenant is None and not policy.apply_to_global.

# AbstractBot.apply_tooling_specs (interfaces/tools.py:188) — THE build hook
async def apply_tooling_specs(
    self,
    *,
    tooling_policy: TenantToolingPolicy | None = None,
    tooling_subject: ToolingSubject | None = None,
) -> list[str]: ...
    # explicit kwargs win; otherwise the values stored by bind_tooling_policy (§2 "Build-hook plumbing")

# AbstractBot.bind_tooling_policy (interfaces/tools.py, new, next to apply_tooling_specs)
def bind_tooling_policy(self, policy: TenantToolingPolicy | None, subject: ToolingSubject) -> None: ...
    # stores self._tooling_policy / self._tooling_subject for the configure() → apply_tooling_specs() call;
    # raises RuntimeError once self._tooling_applied is True (binding after the build is a bug)

# AbstractToolkit (parrot/tools/toolkit.py, next to options_params :327) — new ClassVars
tenant_bound: ClassVar[bool] = False
server_managed_params: ClassVar[Mapping[str, ServerParam]] = {}
read_tools: ClassVar[frozenset[str]] = frozenset()        # method names that are read-only
# AbstractTool gets `tenant_bound`, `server_managed_params` and `access: ClassVar[ToolAccess | None] = None`.

# parrot/auth/confirmation.py — approval token (new)
def current_confirmed_call() -> tuple[int, str] | None: ...   # (id(tool), args_hash) set by ToolManager only

# host side: plugins/tools/__init__.py
HOST_TOOL_PREFIX = "fs_"
TOOL_REGISTRY = {"fs_events": "plugins.tools.fieldsync.events.FieldsyncEventsToolkit"}
# host side: startup
set_tenant_tooling_policy(app, TenantToolingPolicy(builtin_tools=frozenset({"wiki"})))
```

**Resolution rules** (in `ToolkitResolver`, built once):

1. Built-in explicit entries come first, then `parrot_tools.TOOL_REGISTRY`.
2. Host entries come from `importlib.import_module("plugins.tools")`, which
   must be a declared `TOOL_REGISTRY` dict plus a `HOST_TOOL_PREFIX` string.
   A host entry is **rejected**, with one `logger.error` naming it, when:
   - its slug lacks the prefix;
   - it collides case-insensitively with a built-in or `parrot_tools` slug;
   - its toolkit's `tool_prefix` does not equal `HOST_TOOL_PREFIX` without
     its trailing `_`.

   A host never shadows a built-in.
3. A `plugins.tools` package **without** a `TOOL_REGISTRY` falls back to
   today's walk (`discover_from_walk`), with a deprecation warning. Walked
   classes keep their current keys and get `source="walk"`. This keeps
   `POST /agents/{name}/tools` and `/execute` behaving exactly as before for
   the GLOBAL partition. For a tenant subject, walked entries are **not**
   host-registered capabilities: the policy treats them like built-ins
   (`builtin_tools` allow-list).
4. `plugins.tools` missing (`ImportError`) means no host entries. It is not
   an error.
5. Until the scope enforcement (M3b) is merged, a host entry whose class is
   tenant-bound resolves as `unavailable` (fail closed), so a discovery-only
   build never runs an ungated tenant-bound tool.

**Scope rules** (in `require_tool_scope`):

- `ctx = current_context()`. No context, or `ctx.request is None`, raises
  `no_context`.
- `scope = ctx.kwargs.get("studio_scope")`. `None` raises `no_scope`.
- `scope.caller.tenant is None` raises `no_tenant`.
- If `scope.agent` is present:
  - `scope.agent.tenant is None` raises `agent_tenant_unset`;
  - `scope.agent.tenant != scope.caller.tenant` raises `tenant_mismatch`.
- Otherwise it returns `(scope.caller.tenant, scope)`.
- The **caller**, never the author, is the principal: a shared agent runs
  with the caller's identity (FieldSync Q11).
- The host still cross-checks the returned tenant against its own validated
  tenant in `_pre_execute`, for example FieldSync's `declared_programme(request)`.
  On disagreement it raises `ToolScopeUnavailable("host_tenant_mismatch")`.

**Server-managed rules:**

- **Constructor param** (the name is in `cls.__init__`):
  - The schema marks it `{"x-server-managed": true}` on both schema paths.
  - `_reject_server_managed` refuses it on PUT (`tooling_store.py:167`) and
    on the `/me` override with 422 `server_managed` (today PUT maps the
    `ValueError` to 422 `invalid_params`, `toolkit_config.py:52-53`; the code
    becomes the one the assign and execute paths already use).
  - Assign and bot build drop any client or stored value, then fill it:
    - `source="app"` → `app[key]`;
    - `source="server"` → the bespoke builder, as `_assign_wiki` does today.
  - `tenant`, `caller` and `agent` sources are **forbidden** on constructor
    params, because an instance is shared across callers.
    `__init_subclass__` raises `TypeError`.
- **Method param** (the name is in a tool method's signature, or in a
  standalone tool's `_execute`): see §2 "Scope enforcement" for the schema and
  per-call rules. Declaring any such param implies tenant-bound.
- **Built-in migration:**
  - `LLMWikiToolkit` declares `pageindex_toolkit`, `graphindex_toolkit` and
    `okf_toolkit` as `source="server"`.
  - `InfographicToolkit` declares `artifact_store` as
    `source="app", key="artifact_store"`.
  - Both dicts are then deleted.

**Read/write marker:**

- The effective access is:
  - `"read"` when the method is in `read_tools`;
  - otherwise `"write"` for **host** toolkits, which is fail-safe;
  - otherwise `None` ("unknown") for built-ins, so their behaviour does not
    change.
- It is written to `routing_meta["access"]` and to the catalogue.
- A host write tool is strictly marked (§2 "Host-write confirmation"): it runs
  only with an approval token and never on direct execute.

**Error surface:**

- In an agent run, `ToolScopeUnavailable` and a missing approval return a
  `ToolResult(status="error" | "forbidden")` from `AbstractTool.execute`,
  with `metadata.error_type`, `metadata.error_code`
  (`tool_scope_unavailable` / `confirmation_required`) and `metadata.reason`.
  UIs that match `status` keep working.
- On `POST /tools/{slug}/execute`: **HTTP 403** with body code
  `tool_scope_unavailable`, `confirmation_required` or `tooling_not_permitted`;
  a server-managed key in the body is **HTTP 422** `server_managed`.
- On the options route: **HTTP 403** `tool_scope_unavailable`.
- On tooling writes, activation, assign and attach (and a build the storage
  runtime refuses): **HTTP 422** `tooling_not_permitted` with `details.reason`
  (a `ToolingRefusal`) and `details.item`; a client-supplied server-managed key
  on PUT, `/me` or the assign JSON is **HTTP 422** `server_managed`.
- These four codes are owned here, each with the status above; the package
  list is X14. A `ScopeRefusal` / `ToolingRefusal` value is only ever a
  `reason`, never a top-level code.

### Tenant tooling policy (R1)

The host owns the policy; ai-parrot owns its enforcement points.

**Registration.** `set_tenant_tooling_policy(app, policy)` stores the frozen
policy under one `web.AppKey`-style key, at most once, before startup
completes; a second call raises `RuntimeError`. `get_tenant_tooling_policy(app)`
returns it, or `TenantToolingPolicy.deny_all()` when the host registered
nothing. There is no mutation API: a host that needs a different policy
restarts with it.

**When it applies.** Whenever `subject.tenant is not None` (every partition an
opted-in host produces, storage X5), and for the GLOBAL partition only when
`apply_to_global=True`. The GLOBAL partition otherwise keeps today's
behaviour (P-Q3). **Host guide statement (mandatory):** the GLOBAL partition is
intentionally outside tenant policy and is not a tenant-compatible deployment
mode; a host that serves tenants must not expose GLOBAL Studio rows to tenant
users, and should set `apply_to_global=True` if any GLOBAL rows exist.

**`check_tool(slug, subject)`**: the resolver entry must exist
(`toolkit_unavailable` otherwise). `source="host"` passes when `host_toolkits`;
`builtin`, `parrot_tools` and `walk` pass only when the slug is in
`builtin_tools` (`builtin_not_permitted`). The same check covers plain tool
names in `NormalizedTooling.tools`.

**`resolve_mcp(config, subject)`** runs on the **final** kwargs, i.e. after
`params` have overridden the top-level fields and after the vault fields are
applied. Checks, in order:

1. **Named host server.** `config["name"]` in `mcp_servers`: every key other
   than `name`, the host server's `tenant_fields`, and fields equal to the
   `AgentMCPServerSpec` defaults must be absent (`field_not_permitted`). It
   returns `{**host.config, **tenant_fields_supplied, "name": name}`. Host
   config may use stdio: the host registered that command, the tenant did not.
2. **Local execution.** A non-empty `command`, `args`, `env` or `socket_path`
   is refused (`local_execution`). The transport is resolved exactly as
   `MCPClient._detect_transport` does (`integration.py:374-390`); `stdio` and
   `unix` are `local_execution`, any other transport outside `mcp_transports`
   is `transport_not_permitted`.
3. **Field allow-list.** The keys must be a subset of `name`, `url`,
   `transport`, `description`, `allowed_tools`, `blocked_tools`, `auth_type`,
   `headers`, `auth_config`, `timeout` (`field_not_permitted`). Callables
   (`header_provider`, `token_supplier`) never come from a spec.
4. **Endpoint.** `url` must be present and under one `mcp_endpoints` prefix
   after normalisation (scheme, lower-cased host, explicit port, path-segment
   boundary; no userinfo). Otherwise `endpoint_not_allowed`.

It returns the kwargs to pass to `MCPServerConfig(**kwargs)`. It is pure and
synchronous: nothing is connected, spawned or read.

**`check_tooling(tooling, subject)`**: `check_tool` for every toolkit spec and
plain tool; `resolve_mcp(effective_mcp_config(spec))` for every MCP spec. At
`write`/`activate`/`attach`, any non-empty `secret_refs` or `vault_owner`
supplied by the client or bundle is refused (`secret_ref_not_permitted`); the
server computes both. At `build`, every `secret_refs` vault name must lie in
the agent's storage namespace and `vault_owner` must equal the row owner
(`secret_ref_not_permitted`).

**`hydrate_mcp` hardening.** Vault values may fill only `MCP_SECRET_FIELDS`
(`headers`, `auth_config`, `env`); any other `secret_refs` key raises before
the kwargs are returned. `resolve_mcp` still runs afterwards, so an `env`
value from the vault on a tenant spec is refused as `local_execution`.

**Enforcement points** (all refuse before any persistence, vault write,
process start or network connection):

| Phase | Where | Call |
|---|---|---|
| write | `AgentToolingStore.put_toolkit`, `put_mcp_servers` (`tooling_store.py:177`, `:204`) before `_split_secrets` / `store_vault_credential`; generic assign (`toolkits.py:443-459`); storage `StudioToolingService` writes; storage `StudioAgentService.create`/`patch` when the body carries tooling; storage `StudioDraftService.save_bundle` | `enforce_tenant_tooling(app, resulting_tooling, subject=ToolingSubject(..., phase="write"))` on the **complete resulting** tooling of the agent, not only the delta |
| activate | storage `StudioDraftService.activate` | same, `phase="activate"`, on the bundle's normalised tooling, inside the activation transaction before any row is written |
| attach | `POST /agents/{name}/tools` live assign (`testing.py:458`) | `policy.check_tool` per slug, `phase="attach"` |
| execute | `POST /tools/{slug}/execute` (`testing.py:363`) | `policy.check_tool(slug)`, `phase="execute"`, before `_instantiate_tool`; refusal is 403 |
| build | storage `StudioAgentBuilder`: `bot.bind_tooling_policy(get_tenant_tooling_policy(app), ToolingSubject(tenant, agent_id, None, "build"))`, then `await bot.configure(app)`, whose existing `apply_tooling_specs()` call uses the binding (see "Build-hook plumbing") | `check_tool` before each class construction; `resolve_mcp` between `hydrate_mcp` and `MCPServerConfig`. A refused spec is skipped, logged at `error`, and never connected |
| catalogue | `GET /catalog/tools`, meta-agent "list tools" (`bots/studio/tools.py:547`) | a tenant partition lists only entries `check_tool` permits |

`apply_tooling_specs` with `tooling_subject.tenant` set and
`tooling_policy=None` behaves as `deny_all()`. Studio agents reach the bot's
MCP connections only through `agent_mcp_servers` → `apply_tooling_specs`
(the factory's `normalize_tooling` path, `registry.py:908-913`), never
through `setup_mcp_servers` directly (`registry.py:165-176`).

**Build-hook plumbing** (owned by M7, in `interfaces/tools.py`, the module that
changes `apply_tooling_specs`). The build hook is reached from `configure()`,
which calls `await self.apply_tooling_specs()` with **no arguments**
(`bots/abstract.py:1524`) and must keep doing so for every non-Studio bot. So:

1. `AbstractBot.bind_tooling_policy(policy, subject)` (new, in the same mixin)
   stores `self._tooling_policy = policy` and `self._tooling_subject = subject`.
   It raises `RuntimeError` when `self._tooling_applied` is already `True`: a
   binding after the specs were applied would silently police nothing.
2. `apply_tooling_specs(*, tooling_policy=None, tooling_subject=None)` resolves
   `policy = tooling_policy if tooling_policy is not None else getattr(self,
   "_tooling_policy", None)` and the subject the same way, **before** the
   `_tooling_applied` short-circuit (`:193`). A resolved subject with a tenant
   and no policy is `deny_all()`; no subject means today's behaviour.
3. The storage builder (`StudioAgentBuilder.build`, storage §2.7 step 4) calls
   `bot.bind_tooling_policy(get_tenant_tooling_policy(app),
   ToolingSubject(tenant=part.tenant, agent_id=record.agent_id, actor=None,
   phase="build"))` after the factory returns and before `await
   bot.configure(app)`. It also installs `app["studio_confirmation_guard"]` on
   `bot.tool_manager` with `set_confirmation_guard` when the host set one
   (§2 "Host-write confirmation").
4. No other caller binds. `configure()`, `BotManager` and the registry factory
   are not changed; a legacy bot never has a binding, so its build is exactly
   today's.

### Scope enforcement (R6)

**Effective `tenant_bound`.** A class is tenant-bound when it sets
`tenant_bound = True`, or declares a `tenant`/`caller`/`agent` method
server-managed param. A `ToolkitTool` inherits its owning toolkit's flag.
`__init_subclass__` computes it once; `is_tenant_bound()` reads it.

**Where the gate runs.** In `AbstractTool.execute` (every standalone tool and
every toolkit-generated tool, since `ToolkitTool` inherits it), immediately
after the special kwargs are popped (`abstract.py:904-912`) and **before** the
permission resolver, lifecycle events, `_ensure_open` (`:976`),
`validate_args` (`:982`), the credential seam, the executor dispatch and
`_execute`. `ToolkitTool._execute` therefore never reaches `_ensure_open`
(`toolkit.py:168`) or `_pre_execute` (`:179`) without a scope. A refusal
returns the structured `ToolResult` below.

**Options.** `AbstractToolkit.__init_subclass__` wraps any `config_options`
defined by a tenant-bound subclass so `require_tool_scope()` runs first. A
direct call of `instance.config_options(param)` is therefore gated without
any code in the host method. The options handler additionally calls
`ensure_tool_scope(cls)` **before** `hydrate_params` (the vault read,
`toolkit_config.py:154`) and before construction (`:157`).

**Direct execute.** `StudioToolExecuteHandler` calls `ensure_tool_scope(cls)`
before `_instantiate_tool` (`testing.py:372`), then `instance.execute(...)`
gates again. Refusal: HTTP 403, body code `tool_scope_unavailable`.

**Construction rule.** A tenant-bound class must not acquire resources in
`__init__`; resources belong in `_open()` (FEAT-391). The probe fixture counts
constructor side effects to prove it for the reference toolkit; the host guide
states the rule.

**Remote executors.** A tenant-bound tool with `executor` set is refused at
registration (`TypeError`) in v1: the worker process has no ContextVar, so
`_pre_execute` host cross-checks could not run there.

**Server-managed arguments, generated and custom schemas.**

- *Generated* toolkit schemas (`_generate_args_schema_from_method`,
  `toolkit.py:95`) exclude every method server-managed name.
- *Custom* schemas — a toolkit method's `_args_schema` (`toolkit.py:663`) or a
  standalone tool's `args_schema` (`abstract.py:298`) — must not declare a
  server-managed name. The toolkit refuses at tool generation, the standalone
  tool at `__init_subclass__`, both with `TypeError`. The LLM never sees the
  field.
- *Per call*, in `AbstractTool.execute` after the gate: any supplied kwarg
  whose name is server-managed is dropped with a warning (LLM path).
  `/tools/{slug}/execute` refuses such a body key with 422 `server_managed`,
  the code the handler already uses (`testing.py:374-380`). After
  `validate_args`, the scope values are injected into the resolved kwargs
  handed to `_execute`: `tenant` → `str`, `caller` → `CallerView`, `agent` →
  `AgentScopeView | None`.

### Host-write confirmation (R7)

`confirming_tools` stays the declaration. Enforcement is new:

- **Strict marking.** A host tool with effective access `"write"` gets
  `routing_meta["requires_confirmation"] = True`,
  `routing_meta["confirmation_enforced"] = True`, and
  `routing_meta["confirm_window_seconds"] = 0` (no window reuse: test chat
  passes no permission context, and `ConfirmationGuard` keys its window by
  `"anonymous"` then, `confirmation.py:446`). A host may opt other tools
  into `confirmation_enforced`.
- **Approval token.** After a `ConfirmationGuard` decision with
  `status == "confirmed"`, `ToolManager.execute_tool` sets a ContextVar
  `(id(tool), compute_args_hash(final_parameters))` around `tool.execute(...)`
  and resets it afterwards. Only `ToolManager` sets it. An LLM cannot, and a
  kwarg is not accepted as approval.
- **Check.** `AbstractTool.execute`, after the scope gate and before
  `_ensure_open`, refuses a `confirmation_enforced` tool unless the token
  matches this tool and the hash of the kwargs it received. Refusal:
  `ToolResult(status="forbidden", metadata.error_code="confirmation_required")`.
- **Consequences (fail closed).**
  - No guard installed on the `ToolManager`: no token, zero writes.
  - A guard without a `human_manager`: it already cancels (`confirmation.py`
    step 3), zero writes.
  - Rejected or timed out: zero writes (existing `ToolManager` return).
  - Approved: exactly one execution with the approved parameters.
  - `POST /tools/{slug}/execute`: never goes through `ToolManager`, so a
    `confirmation_enforced` tool is refused with 403 `confirmation_required`
    before `_instantiate_tool`. Direct execution has no approval channel.
- **Who installs the guard.** The Studio runtime (storage builder) and test
  chat use whatever `ConfirmationGuard` the host configured on the app
  (`app["studio_confirmation_guard"]`, set by the host); without one, host
  writes are simply unavailable. The HITL channel is a product choice (P-Q2),
  not a correctness gap.
- Built-ins with `access=None` keep today's behaviour (Q7).

### Tenant-safe identity keys (R3, consumer side)

For a **Studio** agent every per-agent key derives from the storage tooling ref
`studio-agent:<agent_id>` (`StudioAgentRecord.tooling_ref`, on the instance
`bot._tooling_ref`, read through core `agent_tooling_ref(bot)`; storage §2.5c,
package X17). The scheme and its plumbing are **owned by the storage spec**
(M10 core helpers in its W0, M13 plumbing in its W1); this spec consumes them
and defines no key of its own:

| Key | Today (legacy, unchanged) | Studio agent (storage scheme) |
|---|---|---|
| Agent toolkit secret vault name (owner vault) | `toolkit_<slug>_<name>` (`spec.py:62`) | `toolkit_<slug>_studio-agent:<uuid>` = `toolkit_vault_name(slug, ref)` |
| Agent MCP secret vault name (owner vault) | `mcp_agent_<server>_<name>` (`spec.py:67`) | `mcp_agent_<server>_studio-agent:<uuid>` = `mcp_vault_name(server, ref)` |
| User override secret vault name (user vault) | `toolkit_<slug>_<name>_user` (`toolkit_overrides.py:170`) | `toolkit_<slug>_studio-agent:<uuid>_user` = `toolkit_override_vault_name(slug, ref)` |
| Override document key `(user_id, agent_id, slug)` | `{user_id, agent_id: <name>, slug}` (`toolkit_overrides.py:183`) | `{user_id, agent_id: "studio-agent:<uuid>", slug}` |
| Session revision marker / tool-manager key | `f"{agent.name}_toolkit_overrides_rev"`, `f"{agent.name}_tool_manager"` (`agent.py:1102`, `:1130`) | `studio-agent:<uuid>_toolkit_overrides_rev`, `studio-agent:<uuid>_tool_manager` |

Rules:

- Every read, write and delete of these keys receives the ref from the
  partitioned lookup (`AgentToolingStore.load` → `ToolingState.tooling_ref`,
  storage X5/X6), never from the URL name. `_apply_user_toolkit_overrides`
  uses `agent_tooling_ref(agent)`, not `agent.name` (storage M13).
- Non-Studio (legacy) agents keep the bare-name keys unchanged:
  `agent_tooling_ref(bot) == bot.name`.
- Recreating a deleted agent yields a new `agent_id`, hence a new ref, and
  never inherits the old credentials or overrides. Storage's agent delete
  purges, best-effort after commit, the deleted id's owner-vault names, the
  override documents whose `agent_id` is the old ref
  (`ToolkitConfigService.purge_agent(ref)`) and their `…_user` vault entries
  (all users). Isolation does not depend on the purge: the new ref never
  reads the old names.
- The policy's build check (`secret_ref_not_permitted`) accepts a
  `secret_refs` vault name only when it equals `toolkit_vault_name(spec.slug,
  ref)` (toolkit spec) or `mcp_vault_name(spec.name, ref)` (MCP spec), with
  `ref = f"studio-agent:{subject.agent_id}"`.
- Everything this spec adds on the identity files (the M2 resolver shim in
  `toolkit_overrides._spec`, the M4 `/me` refusal, M7 on `tooling_store.py`)
  uses `state.tooling_ref`; M9 verifies that and owns the two-tenant
  regression test.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: toolkit-resolver | yes | rules 1–5 above, `ToolkitEntry`, shims keep old names | — |
| M2: resolver-adoption | yes | every row of the P1 table calls `get_toolkit_resolver()` | — |
| M3a: tool-scope-contract | yes | Protocols, refusals, `require_tool_scope` order, `is_tenant_bound`, `ensure_tool_scope` | — |
| M3b: scope-enforcement | yes, after FEAT-605 W2.1 and storage W2 | gate position in `AbstractTool.execute`, `config_options` wrapper, custom-schema refusal, handler pre-construction checks | depends on sibling names |
| M4: server-managed-params | no | — | ClassVar fill order in `apply_tooling_specs` interacts with `hydrate_params` and the DatasetManager branch (`interfaces/tools.py:203-228`). Needs a design pass during `/sdd-task`. |
| M5: scope-binding | yes, after FEAT-605 v0.2 W2.1 | bind sites fixed | depends on a sibling name |
| M6: host-conventions | yes | prefix, `read_tools`, strict marking, catalogue fields | — |
| M7: tenant-tooling-policy | yes | §2 "Tenant tooling policy": API, check order, enforcement table, build-hook plumbing (`bind_tooling_policy`) | — |
| M8: host-write-confirmation | yes | token ContextVar, strict marking, execute refusal | — |
| M9: studio-identity-keys (consumer) | yes, after storage M13 (its W1) and, per file, storage W3 | §2 "Tenant-safe identity keys" (scheme fixed by storage §2.5c / X17) | — |

### Module 1: toolkit-resolver
- **Path**: `packages/ai-parrot/src/parrot/tools/resolver.py` (new)
- **Responsibility**: the single slug → class authority (rules 1–5).
- **Depends on**: `discovery.py` (`resolve_class`, `discover_from_walk`)
- **Interface Skeleton**: see §2 *New Public Interfaces*.

### Module 2: resolver-adoption
- **Path**: `interfaces/tools.py:177`, `studio/toolkits.py:156`, `studio/testing.py:92`, `studio/tooling_store.py:39,138`, `handlers/tools_catalog.py:44`
- **Responsibility**: every P1 path calls `get_toolkit_resolver()`.
  - `_resolve_toolkit_class`, `_resolve_registry_class` and `_resolve_spec_class` become one-line shims.
  - The catalogue cache (`tools_catalog._CATALOG_CACHE`) is built from `entries()`.
  - Persisted specs whose slug no longer resolves are **kept**, and reported as `unavailable` (not deleted) in the FEAT-593 list response.
- **Depends on**: M1

### Module 3a: tool-scope-contract
- **Path**: `parrot/tools/scope.py` (new)
- **Responsibility**: Protocols, accessor, `ToolScopeUnavailable`, `is_tenant_bound`, `ensure_tool_scope`, the `tenant_bound` ClassVar. No call site changes.
- **Depends on**: — (it only reads `current_context()`)

### Module 3b: scope-enforcement
- **Path**: `parrot/tools/abstract.py:881-1010` (`execute`), `:1191-1206` (error metadata), `AbstractTool.__init_subclass__`; `parrot/tools/toolkit.py` (`__init_subclass__`, `config_options` wrapper, `_create_tool_from_method` custom-schema check, `:95`); `studio/testing.py:363-394`; `studio/toolkit_config.py:146-158`
- **Responsibility**: §2 "Scope enforcement". Lifts resolver rule 5.
- **Depends on**: M3a, M4 (per-call fill), FEAT-605 v0.2 W2.1, storage W2 (runtime identity `bot._studio_key`, `bot._tooling_ref`)

### Module 4: server-managed-params
- **Path**: `parrot/tools/server_params.py` (new), `toolkit.py` (ClassVars, `:95`, `__init_subclass__`), `abstract.py` (ClassVars), `config_schema.py:92,122`, `interfaces/tools.py:230-242`, `studio/tooling_store.py:40,167`, `studio/testing.py:42,122-161`, `studio/toolkits.py:443-459`, `studio/toolkit_overrides.py`, wiki and infographic toolkits
- **Responsibility**: the server-managed rules above (constructor params; method-param declaration and schema exclusion), and migrating plus deleting both hard-coded dicts.
- **Depends on**: M1, M3a

### Module 5: scope-binding
- **Path**: `handlers/chat.py:455`, `studio/testing.py:393`, `studio/toolkit_config.py:157`
- **Responsibility**: wrap each call in `RequestContext(request=..., app=..., studio_scope=build_tool_scope(scope, agent))` (FEAT-605 `handlers/studio/access.py`).
  - Normal chat and options bind a `StudioAgentRef` when the bot is a Studio agent, recognised by `bot._studio_key` (storage spec runtime).
  - `chat.py` resolves bots with `get_bot(name)`, which never returns a tenant row (storage §2.7). So in v1 the only Studio agents chat can bind are tenant-NULL rows, whose tools refuse with `agent_tenant_unset`; tenant agents in normal chat are the storage/FEAT-605 P13 follow-up. A non-Studio bot binds `agent=None`.
  - Options resolve the agent through `AgentToolingStore` (Studio row → `StudioAgentRecord`), then FEAT-605's `StudioAccess.agent_ref`.
  - Execute binds `agent=None`.
  - When the host installed no resolver (`has_installed_resolver(app)` is false, FEAT-605 M1), nothing is bound, so tenant-bound tools refuse with `no_scope`.
  - Test chat and the meta-agent are bound by FEAT-605 v0.2. This module only adds tests that assert it.
- **Depends on**: M3a, FEAT-605 v0.2 (W0.1 `RequestScope`, W2.1 `StudioAgentRef` + `build_tool_scope`), storage W2 (`bot._studio_key`)

### Module 6: host-conventions
- **Path**: `toolkit.py` (`read_tools`, `routing_meta["access"]`, strict marking for host writes), `resolver.py` (prefix checks), `tools_catalog.py` (`source`, `access`), `docs/` (one host-toolkit guide page)
- **Responsibility**: G5.
  - The guide states the conventions that are not enforced: Pydantic return models; a row cap with `max_rows` in `config_model` plus `truncated: bool` in the result; no secrets in results; no resource acquisition in a tenant-bound constructor.
- **Depends on**: M1

### Module 7: tenant-tooling-policy
- **Path**: `parrot/tools/tooling_policy.py` (new); `parrot/tools/spec.py:187-197` (`hydrate_mcp` hardening); `interfaces/tools.py:188-262` (build hook + new `bind_tooling_policy`); `studio/tooling_store.py:177-245`, `studio/toolkits.py:443-459`, `studio/testing.py:363,458` (write/attach/execute); `handlers/tools_catalog.py`, `bots/studio/tools.py:547` (catalogue filter)
- **Responsibility**: G6, §2 "Tenant tooling policy" and "Build-hook plumbing". Storage wires its own services and builder through the two hooks (package X15, X18).
- **Depends on**: M1 (`entry()` for `check_tool`). The core part (policy module, `hydrate_mcp` hardening, build hook, `bind_tooling_policy`) is Wave 1 and merges before storage W2, whose services and builder call it. Wiring into storage-owned handler files follows the per-file merge rule (X16).

### Module 8: host-write-confirmation
- **Path**: `parrot/auth/confirmation.py` (token), `parrot/tools/manager.py:1813-1849,2009-2061`, `parrot/tools/abstract.py` (`execute` check), `parrot/tools/toolkit.py:692-699` (strict marking), `studio/testing.py:363` (execute refusal)
- **Responsibility**: G7, §2 "Host-write confirmation".
- **Depends on**: M6 (effective access). Lands together with M6, before any release that resolves host toolkits.

### Module 9: studio-identity-keys (consumer)
- **Path**: `parrot/tools/tooling_policy.py` (the build-time vault-name check of §2 "Tenant-safe identity keys"); `studio/toolkit_overrides.py`, `studio/tooling_store.py` (only where M2/M4/M7 added code that computes a key); tests. **No edits** to `handlers/toolkit_persistence.py`, `handlers/agent.py` or `tools/spec.py`: storage M13/M10 own the key plumbing there.
- **Responsibility**: G8 on the consumer side: every TOOLKITS-added path uses `state.tooling_ref` / `agent_tooling_ref`; the namespace check; `test_same_names_two_tenants_independent_secrets_and_overrides`.
- **Depends on**: storage M10 (W0, helpers), storage M13 (W1, plumbing), storage W2 (runtime `_tooling_ref`), storage W3 (handler switch) and FEAT-605 W2.1 (tenant partitions) for the two-tenant test. **Per-file order** (package X16): storage M13 merges first on `tooling_store.py`, `toolkit_overrides.py`, `toolkit_persistence.py` and `agent.py`; M9 follows (after storage W3 on the two Studio handler files).

---

## 4. Test Specification

**Rule for every test**: build requests with a real aiohttp request. Use
`aiohttp.test_utils.make_mocked_request` with the session installed the way
`navigator_session` does it (`request[SESSION_OBJECT]`), or an
`aiohttp_client` over a real app. Never use `Mock` or `SimpleNamespace` with
hand-set `.session` or `.app`. The `studio_scope` fixture is
`build_tool_scope(RequestScope(...), StudioAgentRef(...))`, FEAT-605's real
types, not a stand-in. Tests that store a secret **value** (FEAT-593 PUT
with a `secret_params` value, the `/me` override) need the DocumentDB vault
or storage M12 (phase 2); without either they skip with that reason. Mutation-check
every new assertion: revert the code, and the test must go red.

**Host fixture**: a tmp package `plugins/tools/` put on `sys.path`, with
`HOST_TOOL_PREFIX="tp_"` and `TOOL_REGISTRY={"tp_probe": ..., "tp_probe_tool": ...}`.
`ProbeToolkit` has:
- `tenant_bound=True`;
- one read tool `whoami()` that returns a Pydantic `ProbeResult(tenant, caller, agent)`;
- one write tool `bump()` that increments a module-level counter (the side-effect probe);
- one constructor server-managed param (`source="app"`);
- one method server-managed param (`source="tenant"`);
- an `_open()` that increments an `opened` counter;
- a `config_options()` that increments an `options_calls` counter and contains **no** scope check.

`ProbeTool` (`tp_probe_tool`) is a standalone `AbstractTool` with
`tenant_bound=True`, a custom `args_schema`, an `_open()` counter and an
`_execute` counter, and **no** scope check in its code.

The resolver is reset between tests with `reload()`; the policy is installed
per test with `set_tenant_tooling_policy` on a fresh app.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_resolver_sees_declared_host_registry` | M1 | `tp_probe` resolves and appears in `entries()` with `source="host"` |
| `test_resolver_rejects_unprefixed_and_colliding_host_slugs` | M1 | `probe` (no prefix) and a slug equal to a `parrot_tools` key are excluded, one error logged each |
| `test_resolver_walk_fallback_without_registry` | M1 | a `plugins.tools` without `TOOL_REGISTRY` still resolves walked classes (back-compat), `source="walk"` |
| `test_tenant_bound_host_entry_unavailable_before_enforcement` | M1 | before M3b lands, `tp_probe` reports `unavailable`; M3b replaces this test with the enforcement tests |
| `test_require_scope_refusals` | M3a | each `ScopeRefusal` reason from a real `RequestContext`/no context; `no_context` with `bot.session` absent |
| `test_standalone_tool_refuses_before_side_effects` | M3b | `ProbeTool.execute()` with no/mismatched scope → `tool_scope_unavailable`; `opened == 0`, `_execute` count 0, no `BeforeToolCallEvent` |
| `test_toolkit_gate_runs_before_ensure_open_and_pre_execute` | M3b | `whoami` refuses; `opened == 0`; `_pre_execute` never called |
| `test_options_provider_refuses_on_direct_call` | M3b | `ProbeToolkit(...).config_options("x")` outside a scope raises `ToolScopeUnavailable`; `options_calls == 0` |
| `test_custom_args_schema_exposing_server_managed_is_typeerror` | M3b | a custom `args_schema` / `_args_schema` containing `tenant` refuses at class creation / tool generation |
| `test_remote_executor_on_tenant_bound_is_typeerror` | M3b | registering a tenant-bound tool with `executor` set raises |
| `test_scope_error_is_structured_tool_result` | M3b | `status="error"`, `error_code`, `reason` in metadata |
| `test_server_managed_ctor_param_marked_on_both_schema_paths` | M4 | introspection and `config_model` both emit `x-server-managed` |
| `test_server_managed_method_param_hidden_and_llm_value_dropped` | M4 | generated and custom schemas lack `tenant`; an LLM-supplied `tenant="other"` is dropped and the scope value reaches the method |
| `test_scope_source_on_ctor_param_is_typeerror` | M4 | `__init_subclass__` refuses |
| `test_builtin_wiki_infographic_declare_classvar` | M4 | no `_SERVER_MANAGED` / `_KNOWN_APP_DEPS` left; schemas unchanged versus a golden copy |
| `test_host_write_tool_strict_marking_and_access_meta` | M6 | write → `requires_confirmation`, `confirmation_enforced`, window 0, `access="write"`; read tool `access="read"`; built-in `access is None` |
| `test_policy_refuses_stdio_and_params_smuggling` | M7 | tenant subject; each of: `transport="stdio"`; `transport="http"` + `params={"transport": "stdio", "command": "sh"}`; `params={"command": "sh"}` with default `auto`; `params={"socket_path": ...}`; non-empty `args`/`env`; `secret_refs={"command": ...}` → `TenantToolingRefused` with the right reason |
| `test_policy_endpoint_allowlist_normalisation` | M7 | `https://mcp.host/api/` allows `https://MCP.host:443/api/x`; refuses `https://mcp.host/apix`, `https://user@mcp.host/api/`, `http://mcp.host/api/`, a missing url |
| `test_policy_named_host_server_allows_host_stdio` | M7 | a `HostMCPServer` with a stdio config, referenced by name with `allowed_tools` only → returned kwargs are the host config; adding `url` or `command` → `field_not_permitted` |
| `test_policy_builtin_allowlist` | M7 | `shell`, `python_execution`, `docker` refused (`builtin_not_permitted`) under `deny_all()`; `wiki` passes when listed; host toolkit passes; walked slug treated as built-in |
| `test_policy_refuses_client_secret_refs` | M7 | `phase="activate"` bundle with `secret_refs`/`vault_owner` → `secret_ref_not_permitted`; `phase="build"` vault name other than `toolkit_vault_name(slug, "studio-agent:<agent_id>")` / `mcp_vault_name(server, "studio-agent:<agent_id>")` (e.g. another agent's ref, or a bare name) → refused |
| `test_policy_registration_once_and_default_deny` | M7 | second `set_tenant_tooling_policy` raises; unset → `deny_all()` |
| `test_hydrate_mcp_vault_fills_only_secret_fields` | M7 | a `secret_refs` key outside `MCP_SECRET_FIELDS` raises |
| `test_bind_tooling_policy_reaches_configure` | M7 | a bot bound with a tenant subject and `deny_all()` builds through the unchanged no-argument `configure()` → `apply_tooling_specs()` path and skips a stdio MCP spec (no process); binding after `_tooling_applied` raises `RuntimeError`; an unbound bot builds exactly as today (mutation: ignore the bound values ⇒ RED) |
| `test_host_write_without_guard_zero_writes` | M8 | `ToolManager` with no guard; the LLM calls `bump` → `confirmation_required`, counter 0 |
| `test_host_write_approved_executes_once` | M8 | guard with a scripted `human_manager` that approves → counter 1, parameters are the approved ones |
| `test_host_write_rejected_executes_zero` | M8 | scripted rejection and timeout → counter 0 |
| `test_approval_token_not_forgeable` | M8 | LLM args carrying `_confirmation` / any key → still refused; token for another tool or other args hash → refused |

### Integration Tests
| Test | Description |
|---|---|
| `test_every_studio_path_sees_host_toolkit` | one parametrized test over catalog, schema, generic assign, FEAT-593 PUT/GET, options, `/me` override, live assign, bot build (`apply_tooling_specs`). Each finds `tp_probe`. |
| `test_put_rejects_server_managed_param` | PUT and `/me` with the ctor param give 422 `server_managed`; the stored spec never contains it (database backend: neither `ai_agent_tooling.config` nor `secret_refs`) |
| `test_tenant_stdio_refused_before_any_process` | **R1 regression.** Tenant partition; `PUT /agents/{name}/mcp-servers` with stdio, and with `transport`/`command` inside `params` → 422 `tooling_not_permitted`, nothing persisted or vaulted; a bundle carrying the same entry is refused at save and at activation; a row planted directly in storage is skipped at build. `asyncio.create_subprocess_exec` is patched to fail the test if called: call count 0 on every path |
| `test_approved_host_config_still_works` | **R1 regression.** The same tenant attaches a named `HostMCPServer` and an allow-listed https endpoint (served by a local test MCP server on an allow-listed prefix) and a host toolkit; write, activation and build succeed and the tools register |
| `test_tenant_catalogue_and_execute_respect_policy` | a tenant partition's catalogue omits `shell`; `POST /tools/shell/execute` and live assign of `shell` → 403/422 `tooling_not_permitted`; the GLOBAL partition is unchanged |
| `test_execute_standalone_refuses_without_scope` | **R6 regression.** `/tools/tp_probe_tool/execute` with a resolver installed but a mismatched/absent scope → 403 `tool_scope_unavailable`; constructor, `_open` and `_execute` counters 0 |
| `test_options_refuse_before_vault_and_construction` | **R6 regression.** options route for `tp_probe` with a missing/mismatched scope → 403 `tool_scope_unavailable`; `hydrate_params` not called (vault spy), constructor and `options_calls` counters 0 |
| `test_execute_refuses_host_write` | **R7 regression.** `/tools/tp_probe_tool_write/execute` (a write `AbstractTool` variant) → 403 `confirmation_required`, zero writes |
| `test_test_chat_join_scope_reaches_tool` | seam-shaped request → Studio test chat → `whoami` returns the **caller's** tenant and id and the agent's owner/visibility. Drive the tool with `tool_manager.execute_tool` inside the handler's `bot.session`, or with a scripted client if one exists. No LLM network. |
| `test_normal_chat_binds_scope` | same join through `chat.py:455` |
| `test_execute_binds_caller_scope_agent_none` | `/tools/tp_probe_tool/execute` sees `agent=None`, caller tenant; with no resolver → 403 `tool_scope_unavailable` / `no_scope` |
| `test_no_request_refuses` | calling the tool outside any session (the scheduler shape) → `no_context` |
| `test_concurrent_callers_never_cross` | two concurrent `bot.session`s on one shared agent, different sessions/tenants → each sees only its own scope (mutation: store the scope on the instance → red) |
| `test_tenant_mismatch_refuses` | agent stamped tenant A, caller tenant B → `tenant_mismatch` |
| `test_same_names_two_tenants_independent_secrets_and_overrides` | **R3 regression.** One user; tenants `acme` and `beta`; an agent `sales` in each with toolkit `tp_probe` (secret param) and an MCP server with the same name. Create/read/update/delete the agent secrets and the user's `/me` override in `acme`; `beta`'s values, vault entries and override documents are unchanged at every step, and vice versa. Runtime hydration (`_apply_user_toolkit_overrides`) of each tenant's bot sees only its own override. Vault names and override documents are exactly the storage scheme (`toolkit_tp_probe_studio-agent:<uuid>`, `…_user`, `agent_id: "studio-agent:<uuid>"`). Delete `acme/sales` and recreate it: the new agent has no secrets and no override. Mutation: key by name → red. Complements storage `test_cross_tenant_tooling_identity` (same property through the host probe toolkit and the FEAT-593 paths) |

### Test Data / Fixtures
```python
@pytest.fixture
def host_plugins(tmp_path, monkeypatch):
    """Writes plugins/tools/__init__.py (+ probe modules) and prepends tmp_path to sys.path."""

@pytest.fixture
def seam_request(app):
    """make_mocked_request(..., app=app); request[SESSION_OBJECT] = real navigator_session shape."""

@pytest.fixture
def no_subprocess(monkeypatch):
    """Patches asyncio.create_subprocess_exec to record and fail; asserts zero calls at teardown."""
```

---

## 5. Acceptance Criteria

- [ ] All seven P1 paths resolve through `get_toolkit_resolver()`. No other module calls `discover_from_registry` or `discover_all` to resolve a Studio slug (`grep` shows only the resolver and the `ToolManager` call sites).
- [ ] A host toolkit declared in `plugins.tools.TOOL_REGISTRY` appears in the catalogue, schema, config, override and options paths, and survives bot build (`test_every_studio_path_sees_host_toolkit`).
- [ ] No code path mutates `parrot_tools.TOOL_REGISTRY` or any registry dict.
- [ ] Tools read tenant, caller and agent only through `current_tool_scope()` / `require_tool_scope()`. Nothing is stored on a toolkit instance.
- [ ] A tenant-bound tool (standalone or toolkit), or options provider, with no request, scope or tenant, or with a mismatched tenant, refuses with `tool_scope_unavailable` and the right `reason` before any constructor side effect, `_open`, vault read or method body, on the agent, execute and options paths; the host code contains no scope check (`test_standalone_tool_refuses_before_side_effects`, `test_options_refuse_before_vault_and_construction`).
- [ ] Server-managed names never appear in generated or custom LLM schemas, and cannot be set via PUT, `/me`, the assign JSON, the execute body or LLM args (tests prove each).
- [ ] `_SERVER_MANAGED` and `_KNOWN_APP_DEPS` are deleted. The wiki and infographic schemas are byte-identical to the pre-change golden copies.
- [ ] A tenant partition cannot persist, activate, build, attach or execute tooling its `TenantToolingPolicy` does not permit; stdio, `command`/`args`/`env`/`socket_path` and transport overrides inside `params` or the vault are refused before any process starts; approved host configuration works (`test_tenant_stdio_refused_before_any_process`, `test_approved_host_config_still_works`).
- [ ] Built-in tools are available to tenant authors only when listed in `builtin_tools` (`test_tenant_catalogue_and_execute_respect_policy`).
- [ ] A host write tool performs zero writes without a confirmation guard, zero on rejection or timeout, exactly one on approval, and zero on direct execute (M8 tests, `test_execute_refuses_host_write`).
- [ ] Studio agent overrides, vault names and revision markers use the storage tooling ref `studio-agent:<agent_id>` (package X17); the two-tenant same-name test passes, including delete/recreate.
- [ ] The storage builder's policy reaches `apply_tooling_specs` through `bind_tooling_policy` without changing `configure()` (`test_bind_tooling_policy_reaches_configure`).
- [ ] The catalogue carries `source` and `access`.
- [ ] Existing Studio and tools tests pass unchanged: `pytest packages/ai-parrot-server/tests/studio packages/ai-parrot/tests/tools -q`.
- [ ] Every new assertion is mutation-checked. The evidence is in the task Completion Notes.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.tools.discovery import discover_from_registry, discover_all, discover_from_walk, resolve_class  # discovery.py:31,111,64,139
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool   # toolkit.py:203, :37
from parrot.tools.abstract import AbstractTool, ToolResult      # abstract.py
from parrot.tools.config_schema import build_schema_envelope, introspect_config_schema, model_config_schema  # :146, :92, :122
from parrot.tools.spec import AgentMCPServerSpec, ToolkitSpec, NormalizedTooling, hydrate_mcp, MCP_SECRET_FIELDS  # spec.py:35, :21, :50, :187, :18
from parrot.mcp import MCPServerConfig          # lazy export of parrot.mcp.integration (mcp/__init__.py:38); the client config class (mcp/client.py:133)
from parrot.auth.confirmation import ConfirmationGuard, ConfirmationDecision, compute_args_hash  # confirmation.py:378, :88, :46
from parrot.utils.helpers import RequestContext, current_context  # helpers.py:7, :58
```

### Existing Class Signatures
```python
# parrot/utils/helpers.py
class RequestContext:  # :7 — __init__(request=None, app=None, llm=None, user_id=None, session_id=None, **kwargs) → self.kwargs (:36)
# parrot/bots/abstract.py
#   session(ctx=None, request=..., app=..., llm=..., user_id=..., session_id=..., **ctx_kwargs)  → RequestContext(**ctx_kwargs) (:4185-4193), bound via _current_ctx.set (:4262)
# parrot/tools/toolkit.py
class AbstractToolkit(ABC):  # :203
    tool_prefix: str | None = None            # :254
    prefix_separator: str = "_"               # :257
    confirming_tools: frozenset = frozenset() # :272
    auto_open: bool = False                   # :316
    config_model: ClassVar[type[BaseModel] | None] = None      # :321
    secret_params: ClassVar[frozenset[str]] = frozenset()      # :323
    default_user_overridable: ClassVar[frozenset[str]] = frozenset()  # :325
    options_params: ClassVar[frozenset[str]] = frozenset()     # :327
    async def _ensure_open(self) -> None      # :427
    async def _prepare_kwargs(self, tool_name, kwargs) -> dict  # :446
    async def _pre_execute(self, tool_name, /, **kwargs) -> None  # :463
    def config_schema(cls, slug) -> dict      # :704 (calls build_schema_envelope WITHOUT server_managed)
    async def config_options(self, param: str) -> list[ConfigOption]  # :710
class ToolkitTool(AbstractTool):  # :37 — _execute :142 (_ensure_open :168, _pre_execute :179), _generate_args_schema_from_method :95
# parrot/tools/abstract.py
class AbstractTool:  # args_schema :298, auto_open :321; execute :881 (special-kwarg pops :904-912, _ensure_open :976, validate_args :982, generic error ToolResult :1201-1206)
# parrot/tools/manager.py — ToolManager: _confirmation_guard :395, set_confirmation_guard :551; confirmation blocks :1813-1849 (ToolDefinition), :2009-2044 (AbstractTool); tool.execute dispatch :2061
# parrot/auth/confirmation.py — ConfirmationDecision.status ∈ confirmed|cancelled|timeout|not_required (:103); ConfirmationGuard.confirm: no human_manager ⇒ cancelled (step 3)
# parrot/tools/spec.py:21  class ToolkitSpec(slug, params, user_overridable, secret_refs, vault_owner)
# parrot/tools/spec.py:35  class AgentMCPServerSpec(name, transport="http", url, command, args=[], allowed_tools, blocked_tools, description, auth_type, params, secret_refs, vault_owner)
# parrot/mcp/client.py:133 class MCPClientConfig(name, url, command, args, env, …, transport="auto", socket_path, headers, header_provider, …)
# parrot/auth/exceptions.py:12  class AuthorizationRequired(Exception)  — the precedent for a structured tool refusal
# server handlers/toolkit_persistence.py:28 ToolkitConfigService.save/load/remove/revision keyed (user_id, agent_id, slug)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ToolkitResolver` | `AbstractBot._resolve_spec_class` | delegation | `interfaces/tools.py:177` |
| `ToolkitResolver` | Studio shims | delegation | `toolkits.py:156`, `testing.py:92`, `tooling_store.py:138` |
| `ToolkitResolver` | catalogue | `entries()` | `tools_catalog.py:56` |
| `require_tool_scope` | `AbstractTool.execute` | call before `_ensure_open` | `abstract.py:904-976` |
| `config_options` wrapper | `AbstractToolkit.__init_subclass__` | wrap at class creation | `toolkit.py:710` |
| `ensure_tool_scope` | execute / options handlers | call before construction | `testing.py:372`, `toolkit_config.py:154` |
| `TenantToolingPolicy.resolve_mcp` | `apply_tooling_specs` | between `hydrate_mcp` and `MCPServerConfig` | `interfaces/tools.py:251-252` |
| `enforce_tenant_tooling` | FEAT-593 writes; storage services | call before vaulting | `tooling_store.py:185`, `:218` |
| approval token | `ToolManager.execute_tool` → `AbstractTool.execute` | ContextVar | `manager.py:2044-2061` |
| scope binding | normal chat | `session(..., studio_scope=)` | `chat.py:455` |
| scope binding | execute | `RequestContext` + `_current_ctx` set/reset | `testing.py:393` |
| scope binding | options | same | `toolkit_config.py:157-158` |
| error metadata | generic tool error path | `metadata` dict | `abstract.py:1201-1206` |
| identity keys | overrides, runtime hydration, vault names | storage scheme | `toolkit_overrides.py:109,157,170,183,200`; `agent.py:1099,1102`; `tooling_store.py:201,221,263` |

### Does NOT Exist (Anti-Hallucination)
- ~~`plugins.tools.TOOL_REGISTRY` honoured by `discover_from_registry`~~: skipped (`discovery.py:44-45`).
- ~~a `HOST_TOOL_PREFIX` convention~~: introduced here.
- ~~`studio_scope` in any `RequestContext` today~~: FEAT-605 v0.2 introduces it. `grep -rn studio_scope packages` finds nothing in code.
- ~~an agent back-reference on a toolkit instance~~: none. Do not add one; read the scope.
- ~~a trustworthy `PermissionContext.tenant_id`~~: it defaults to the principal (`auth/permission.py:199-205`).
- ~~a request context in `/tools/{slug}/execute` or the options handler~~: none today (`testing.py:393`, `toolkit_config.py:157`).
- ~~toolkit execution through `/tools/{slug}/execute`~~: toolkits are rejected (`testing.py:364-368`).
- ~~a read/write marker on parrot tools~~: none. Only MCP's `read_only_hint` exists (`mcp/agent_tools.py:47`).
- ~~a tenant-bound tool convention (`requires_tenant` for tools)~~: `requires_tenant` is a parrot-formdesigner HTTP decorator only.
- ~~`server_managed` honoured by `model_config_schema`~~: it takes no such argument (`config_schema.py:122`).
- ~~any transport or command restriction on agent MCP specs~~: none (`spec.py:35`, `tooling_store.py:204`).
- ~~a confirmation requirement that holds without a guard~~: `ToolManager` proceeds when `_confirmation_guard is None` (`manager.py:1817`, `:2012`).
- ~~agent-id-keyed overrides or vault names~~: all use the bare name today (P7).
- ~~`ToolkitResolver`, `ToolScopeUnavailable`, `ServerParam`, `require_tool_scope`, `TenantToolingPolicy`, `enforce_tenant_tooling`, `current_confirmed_call`, `AbstractBot.bind_tooling_policy`~~: introduced by this spec.
- ~~a `studio/<agent_id>/…` vault-name form~~: never existed; it was this spec's v0.2 placeholder. The scheme is storage's `studio-agent:<agent_id>` ref (X17).
- ~~`agent_tooling_ref`, `toolkit_override_vault_name`, `ToolingState.tooling_ref`, `ToolkitConfigService.purge_agent`~~: introduced by the storage spec (M10, M13), consumed here.

### Edit Sites (Blueprint Anchors)

Rows up to `chat.py` verified against `3f0f2f726`; rows marked † re-verified on the branch tree `8268c0911`.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/tools/resolver.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/tools/scope.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/tools/server_params.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/tools/tooling_policy.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/interfaces/tools.py` | MODIFY | `def _resolve_spec_class(slug: str) -> type \| None:` | `:177` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/tools.py` | MODIFY | `instance = cls(**filtered)` | `:242` | 1 |
| `packages/ai-parrot/src/parrot/tools/toolkit.py` | MODIFY | `options_params: ClassVar[frozenset[str]] = frozenset()` | `:327` | 1 |
| `packages/ai-parrot/src/parrot/tools/toolkit.py` | MODIFY | `await toolkit._pre_execute(self.name, **hook_kwargs)` | `:179` | 1 |
| `packages/ai-parrot/src/parrot/tools/config_schema.py` | MODIFY | `def model_config_schema(cls: type) -> dict[str, Any]:` | `:122` | 1 |
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | `metadata={"tool_name": self.name, "error_type": type(e).__name__},` | `:1205` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` | MODIFY | `def _resolve_toolkit_class(slug: str) -> type \| None:` | `:156` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` | MODIFY | `schema = cls.config_schema(slug)` | `:253` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` | MODIFY | `_SERVER_MANAGED = {` | `:40` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` | MODIFY | `_EXPLICIT = {` | `:39` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` | MODIFY | `def _resolve_registry_class(slug: str) -> type \| None:` | `:92` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` | MODIFY | `_KNOWN_APP_DEPS: dict[str, str] = {` | `:42` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` | MODIFY | `result = await instance.execute(**execute_request.args)` | `:393` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py` | MODIFY | `instance = cls(**params)` | `:157` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/tools_catalog.py` | MODIFY | `for slug, dotted_path in sorted(TOOL_REGISTRY.items()):` | `:56` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/chat.py` | MODIFY | `async with chatbot.session(request=self.request, app=app, llm=llm) as bot:` | `:455` | 1 |
| `packages/ai-parrot/src/parrot/tools/abstract.py` † | MODIFY | `pctx = kwargs.pop("_permission_context", None)` | `:904` | 1 |
| `packages/ai-parrot/src/parrot/tools/abstract.py` † | MODIFY | `if self.auto_open and self.executor is None:` | `:976` | 1 |
| `packages/ai-parrot/src/parrot/tools/toolkit.py` † | MODIFY | `if method_name in self.confirming_tools:` | `:696` | 1 |
| `packages/ai-parrot/src/parrot/tools/toolkit.py` † | MODIFY | `args_schema = getattr(bound_method, "_args_schema", None)` | `:663` | 1 |
| `packages/ai-parrot/src/parrot/tools/manager.py` † | MODIFY | `result = await self._observed(observation, tool_name, lambda: tool.execute(**exec_kwargs))` | `:2061` | 1 |
| `packages/ai-parrot/src/parrot/tools/spec.py` † | MODIFY | `base.update(spec.params)` | `:189` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/tools.py` † | MODIFY | `kwargs = await hydrate_mcp(mspec)` | `:251` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/tools.py` † | MODIFY | `    async def apply_tooling_specs(self) -> list[str]:` (signature + `bind_tooling_policy` next to it) | `:188` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` † | REFERENCE (unchanged) | `                await self.apply_tooling_specs()` | `:1524` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` † | MODIFY | `candidate = AgentMCPServerSpec.model_validate({**payload, "params": params})` | `:218` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` † | MODIFY | `instance = _instantiate_tool(cls, self.request.app)` | `:372` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py` † | MODIFY | `hydrated = await hydrate_params(spec)` | `:154` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py` † | MODIFY | `UserToolkitOverride(user_id=user.user_id, agent_id=name, slug=slug, params=clean, secret_refs=refs)` | `:183` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` † | MODIFY | `overrides = await svc.load(str(user_id), agent.name)` | `:1099` | 1 |

Implementers re-verify every anchor against the tree they branch from (`origin/dev`) before editing.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Structured refusal: follow `AuthorizationRequired` (`auth/exceptions.py:12`), but convert to a `ToolResult` in `AbstractTool.execute` instead of adding a new `ToolManager` status. UIs that match `status` keep working.
- Per-call state lives only in a ContextVar (the `_A2UI_SURFACE_STATE_VAR` precedent, `abstract.py:59-75`), never on the instance. The approval token follows the same rule.
- Core never imports ai-parrot-server. The Protocols in `scope.py` are the only coupling to FEAT-605's types; `tooling_policy.py` takes `app` as a plain `Mapping`.
- The policy is a frozen Pydantic model; its checks are pure functions, so storage can call them inside a transaction without I/O.
- Logging goes through `self.logger`. The resolver logs each rejected host entry once, at build time; the build hook logs each refused spec at `error` with its `ToolingRefusal`.

### Known Risks / Gotchas
- **ContextVar reach.** Tasks created *inside* `bot.session()` inherit the scope and any approval token, and so does `asyncio.to_thread`. A task spawned before the session, or a streaming generator consumed after the `async with` exits, does not. Such a tool refuses with `no_context`, which is fail-closed. The chat streaming path must be checked in M5.
- **Import-time side effects.** The resolver imports `plugins.tools` lazily, on first use, never at parrot import. The host package must be importable by then.
- **Stored specs with a now-server-managed key** (for example a legacy row, or an `ai_agent_tooling.config` written before M4): the key is stripped on load, with a warning. It is never applied.
- **Stored tooling the policy refuses at build** (a stdio MCP row or a disallowed built-in written before M7, or a policy tightened later): the agent build **fails closed** with `tooling_not_permitted` (STORAGE §2.7 "Build refusal vs. unavailable tooling"); never connected. Only an **unresolvable** toolkit (not installed / discovery `unavailable`) is skipped and reported `unavailable`.
- **Toolkit secrets need DocumentDB.** Secret values and per-user overrides stay in the DocumentDB vault until storage M12 (phase 2), under the ref-derived names above. A host without DocumentDB (FieldSync) can attach secret-free host toolkits only; a secret write answers 503 there.
- **Walk fallback keys** (`getattr(obj, "name", attr_name)`, `discovery.py:105`) can differ from the registry slugs. The fallback exists only for back-compat and is not subject to the prefix rules; for tenants it counts as built-in.
- **Endpoint allow-list is not SSRF-proof by itself.** It bounds the URL a tenant names; DNS and redirects are the host network's concern. Hosts list only endpoints they operate.

### External Dependencies
None new.

---

## 8. Dependencies on sibling specs

| Need | Provided by | What this spec assumes | If it differs |
|---|---|---|---|
| `studio_scope` object in `RequestContext.kwargs` | FEAT-605 v0.2 (C16) | `StudioToolScope` satisfies `ToolScopeView`: `.caller` = `RequestScope` (`user_id`, `tenant`, `groups`, `is_superuser`, …), `.agent` = `StudioAgentRef` (`agent_id`, `name`, `owner`, `tenant`, `visibility`) or `None` | FEAT-605 keeps its names; this spec adapts the Protocol attribute names only |
| scope builder usable from `chat.py`, execute, options | FEAT-605 v0.2 W2.1 | `build_tool_scope(scope, agent=None) -> StudioToolScope` in `handlers/studio/access.py` (name frozen) | M3b/M5 wait for it |
| test chat + meta-agent bind `studio_scope` | FEAT-605 v0.2 (W3.4 `testing.py:270`, W3.5 `meta_agent.py:110`) | bound there | if FEAT-605 binds only the meta-agent, M5 also binds test chat |
| FEAT-605 routes require policy, enforcement, confirmation | FEAT-605 v0.2 C35, C36 | its route table calls this spec's hooks; refusal codes `tooling_not_permitted`, `tool_scope_unavailable`, `confirmation_required` are owned here | codes are renamed here only, never there |
| Studio bot identity and build | storage spec W2 (`StudioAgentBuilder`, `StudioAgentKey`, `get_studio_bot`, `StudioRuntimeCache`) | a Studio bot carries `bot._studio_key`, `bot._studio_agent_id` and `bot._tooling_ref`; its toolkits come from `ai_agent_tooling` rows ordered by `position`, turned into `ToolkitSpec`s; the builder calls `bot.bind_tooling_policy(get_tenant_tooling_policy(app), ToolingSubject(tenant, agent_id, None, "build"))` before `configure()` (§2 "Build-hook plumbing"); MCP reaches the bot only as `agent_mcp_servers`; `get_bot(name)` refuses `studio:`/`studio-agent:` names and never returns a tenant row | M5 chat binding degrades to `agent=None` / refusal; without the binding the storage builder is non-compliant (R1) |
| policy at every storage write and activation | storage W2/W3 (`StudioToolingService`, `StudioAgentService.create`/`patch`, `StudioDraftService.save_bundle`/`activate`) | each calls `enforce_tenant_tooling(app, resulting_tooling, *, subject=ToolingSubject(tenant, agent_id, actor, "write" \| "activate"))` before any row or vault write; activation inside its transaction; client/bundle `secret_refs`/`vault_owner` never accepted | a missing call site is an R1 defect in storage, not a question |
| tenant-safe key/vault-name scheme | storage §2.5c (owner of the scheme): M10 (W0) helpers, M13 (W1) plumbing | ref `studio-agent:<agent_id>`; `toolkit_<slug>_studio-agent:<uuid>`, `mcp_agent_<server>_studio-agent:<uuid>`, `toolkit_<slug>_studio-agent:<uuid>_user` (`toolkit_override_vault_name`); override document key `{user_id, agent_id: <ref>, slug}`; storage's agent delete purges the deleted id's names and override documents (`purge_agent`) | none: the names are final (X17) |
| toolkit secret values, per-user overrides | DocumentDB vault today; storage M12 (phase 2) later | unchanged names, ref-derived; `ai_agent_tooling.secret_refs` holds vault names only | a host without DocumentDB cannot store secrets until storage M12 |
| confirmation guard for Studio runtime and test chat | host (`app["studio_confirmation_guard"]`), used by storage builder and FEAT-605 test chat | installed on the bot's `ToolManager` via `set_confirmation_guard` when present | none present ⇒ host writes unavailable (correct, fail closed) |
| `has_installed_resolver(app)` | FEAT-605 v0.2 M1 | exists | — |
| storage of agent-level toolkit specs | storage spec (`navigator.ai_agent_tooling`: `kind`, `slug`, `position`, `config`, `secret_refs`, `vault_owner`) | `AgentToolingStore` keeps `schema_for` / `put_toolkit` semantics (`source="studio"` branch); this spec changes *which class*, *which keys are refused*, *which tooling is permitted* and *which vault names are used*; unresolvable or refused slugs stay as rows and are reported `unavailable` | resolver, policy and refusal rules are storage-agnostic |

Ordering: see §9 and package X16. Files M2/M4/M7/M9 edit — `tooling_store.py`, `toolkits.py`,
`testing.py`, `toolkit_config.py`, `toolkit_overrides.py` — are also edited by
storage W1 (M13, identity plumbing) and W2/W3, so each of those files merges after the
storage tasks for it and rebases (the package's per-file rule). On the identity files
storage M13 goes first; M9 makes no edit to `toolkit_persistence.py` or `handlers/agent.py`.
Core `interfaces/tools.py` goes the other way: M7 core (build hook, `bind_tooling_policy`)
merges before storage W2's builder. Both sides meet at `AgentToolingStore`,
and the integration tests run against whichever store is current.

---

## Cross-spec contract (package)

This section is **identical** in the three package specs: STORAGE =
`agentstudio-db-storage.spec.md` (v0.2.1), FEAT-605 = `agentstudio-tenant-visibility.spec.md` (v0.2.1),
TOOLKITS = `agentstudio-host-toolkits.spec.md` (v0.2.1). Changing a row means changing it in all three.
STORAGE waves are W0–W4 and P2 (modules M1–M13); FEAT-605 tasks are W0.1–W4.3; TOOLKITS waves are
Wave 1–4 (modules M1–M9). The owner named in "Provided by" wins any naming conflict. Rows X17 and X18
were appended in the v0.2.1 reconciliation; X1–X16 keep their numbers so existing references stay valid.

| # | Item (exact names) | Provided by | Consumed by | Contract |
|---|---|---|---|---|
| X1 | Tables `navigator.ai_agents`, `navigator.ai_agent_assets`, `navigator.ai_agent_tooling`, `navigator.ai_agent_drafts` (with its own `version`), `navigator.ai_studio_migrations`; the **existing** `navigator.ai_skills_catalog` extended in place (content column `body`; adds `tenant`, `visibility`, `allowed_groups text[]`); phase 2: `navigator.ai_user_llm_keys`, `navigator.ai_user_credentials`, `navigator.ai_user_toolkit_overrides` | STORAGE W0 (migrations 0001–0005, M1); P2 (migrations 0006–0008, M11/M12) | FEAT-605, TOOLKITS (only through STORAGE services / `AgentToolingStore`) | `tenant text NULL`; agents, drafts **and** catalogue each carry the visibility-domain CHECK (`private`/`tenant`/`groups`), the tenant-format CHECK and the `tenant IS NULL ⇒ visibility = 'private'` CHECK; `allowed_groups text[]`; `UNIQUE(tenant, name)` + partial unique `(name) WHERE tenant IS NULL`; `ai_agents.version` and `ai_agent_drafts.version` bumped by trigger. Each migration file = body + one `-- @studio-ledger` trailer; the checksum is sha256 over the body only (never the trailer) and equals the trailer hex and `migrations/MANIFEST.json`; every body first takes `pg_advisory_xact_lock(4715391001)`; one transaction per file; PostgreSQL ≥ 14; required versions 1..8 for the `database` backend (phase 2 ships in the same release; `parrot-studio-migrate --verify` covers 1..8), a gap or drift ⇒ backend `unavailable`. Literal schema `navigator` (`search_path` cannot redirect qualified names). No DDL outside the migration files, never at startup |
| X2 | Tenant-less rows (`tenant IS NULL`) | STORAGE | FEAT-605, TOOLKITS | They form the GLOBAL partition of hosts with **no** resolver; there is no sentinel tenant. No resolver may return a NULL or empty tenant as valid; a NULL row never satisfies FEAT-605 `in_tenant`; a tenant-bound tool on such an agent refuses `agent_tenant_unset` |
| X3 | `ai_agent_tooling(agent_id, kind, slug, position, config, secret_refs, vault_owner, updated_at)`, PK `(agent_id, kind, slug)` | STORAGE W0 (table), W1 (M13 identity plumbing), W2/W3 (`StudioToolingService`, `AgentToolingStore` `source="studio"`) | TOOLKITS (M2, M4, M7, M9) | `position` = list order of `ToolkitSpec`/MCP specs; `config` = secret-free spec dump, never contains a TOOLKITS server-managed key; `secret_refs` = `{dotted.path: vault_name}`, every vault name derived from `record.tooling_ref` (X17), never from the URL name; `vault_owner` = the row owner. Secret **values** and per-user `/toolkits/{slug}/me` overrides stay in DocumentDB (`user_credentials`, `user_toolkit_configs`) until STORAGE M12 moves them to Postgres under the same names; override documents are keyed `{user_id, agent_id: <tooling_ref>, slug}`. Agent delete purges, best-effort after commit, the deleted id's owner-vault names, its override documents (`ToolkitConfigService.purge_agent(ref)`) and their `…_user` vault entries; isolation never depends on the purge |
| X4 | `StudioPartition(tenant)`, `StudioPartition.GLOBAL`, `StudioPartition.from_scope(scope)` (duck-typed `.tenant`) | STORAGE W0 | FEAT-605 W2.1 | Storage addresses rows by tenant only; it never sees groups, superuser or visibility policy |
| X5 | `async StudioBaseView._studio_partition()` | STORAGE W1 (returns `GLOBAL`) | FEAT-605 W2.1 (override) | No resolver ⇒ `GLOBAL`. Resolver + tenant ⇒ `StudioPartition.from_scope(await self._scope())`. Resolver + no tenant ⇒ never `GLOBAL`: the handler answers empty / 404 / 422 `tenant_required` before any storage call |
| X6 | Records `StudioAgentRecord` (incl. `tooling_ref`), `StudioDraftRecord`, `StudioSkillRecord` (`owner`, `tenant`, `visibility`, `allowed_groups`, id, `name`); `StudioAgentHead(agent_id, version, status)`; `StudioWriteGuard(authorized_version, expected_version)`; errors `StudioNameConflict`, `StudioVersionConflict`, `StudioStaleAuthorization`, `StudioToolingRefused`, `StudioStorageUnavailable`; services `StudioAgentService` (`create(part, *, name, owner, definition, visibility="private", allowed_groups=(), toolkits=(), mcp_servers=(), assets=())`, `create_from_bundle`, `patch(…, guard=)`, `update_visibility(…, guard=)`, `delete(…, guard=)`, `get_version(part, name) -> StudioAgentHead \| None`), `StudioDraftService` (`save_bundle`, `activate(part, name, *, owner, replace=False, guard, target_guard=None)`, `update_visibility`, `python_drafts_allowed`), `StudioSkillCatalogService` (`publish`, `update_visibility`, …); test fake `InMemoryStudioRepositories` (`storage/testing.py`) | STORAGE W0 (records, errors), W1 (repositories, fake), W2 (services) | FEAT-605 (`StudioAccess`, handlers, tests) | Services validate data, never access. A plain `POST /agents` creates without a bundle. Every agent/draft write locks the row (`FOR UPDATE`) and applies the guard in one transaction; FEAT-605 passes the version its access decision was made on as `authorized_version`; `StudioStaleAuthorization` ⇒ re-read, re-authorise and retry once, then 409 `version_conflict`; the client `expected_version` is accepted only on the STORAGE §2.9 routes. Draft activation and `replace=true` are one transaction with atomic bundle replacement. The fake enforces the same uniqueness, CHECKs, version bump and guard, and raises the same signals |
| X7 | Registry key `StudioAgentKey(tenant, name).qualified` = `studio:<tenant\|->:<name>`; `BotManager.get_studio_bot(key, *, new=False, session_id="", request=None)`; `BotManager.studio` = `StudioAgentRuntime` (`get`, `get_session`, `use(key, *, session_id=None, request=None)`, `reload(key)`), whose instances live only in its private `StudioRuntimeCache`; on every Studio instance `bot._studio_key`, `bot._studio_version`, `bot._studio_agent_id`, `bot._tooling_ref` | STORAGE W2 | FEAT-605 (test/ask through `studio.use()` / `get_studio_bot`, reload, activation), TOOLKITS M5 (identifies a Studio bot by `_studio_key`), M9 (`agent_tooling_ref`) | Studio instances are never stored in `BotManager._bots` or `_botdef`. `get_bot(name, …)` returns `None` for any name starting with `studio:` or `studio-agent:` (with or without `new=True`) before touching `_bots`, `_botdef` or the registry; `add_bot` raises `ValueError` for an instance carrying `_studio_key`; `get_bots()`, `reload_agent` and the legacy cleanup paths never see a Studio instance. The only fallback: `get_bot(name)` with `new=False`, backend `database` and no installed resolver returns `studio.get(StudioAgentKey(None, name))` (GLOBAL only) without adding it to `_bots`. Tenant rows are unreachable by name (chat, A2A, scheduler: the P13 follow-up). Studio handlers that run a request on an instance hold a lease through `studio.use()`. Runtime memory identity: `chatbot_id = str(agent_id)` (X17) |
| X8 | Storage and runtime lifecycle hooks: `ensure_studio_storage(app)` (memoised probe; `resolve_studio_storage` is its `on_startup` wrapper, registered once by `setup_studio_routes`); `add_studio_runtime_hooks(app)` → `install_studio_runtime` (`on_startup`) + `shutdown_studio_runtime` (`on_cleanup`); `StudioAgentRuntime.start()` / `sweep(now=None)` / `shutdown()` / `use()`; `StudioRuntimeCache`; `cleanup_bot_instance(bot, *, label)` | STORAGE W1 (`ensure_studio_storage`), W2 (runtime, hooks) | `BotManager.setup()` (STORAGE M7), FEAT-605 W2.2 (`setup_registry_only` calls `add_studio_runtime_hooks`), host | `install_studio_runtime` awaits `ensure_studio_storage` **first**, so storage resolution precedes runtime construction whatever order the hooks were appended in; it installs `BotManager.studio` only when `app["studio_storage"].backend == "database"`; no eager load. `add_studio_runtime_hooks` appends each hook at most once per app. Studio expiry (session TTL, idle TTL, retirement grace), identity-based once-only cleanup, leases, in-flight retention and versioned asset directories are STORAGE's alone. FEAT-605's manager-level lifecycle in registry-only mode (`registry.setup`, the legacy `_cleanup_expired_bots` task, `_cleanup_all_bots`) applies to non-Studio bots only and never touches a Studio instance |
| X9 | `RequestScope(user_id, tenant, groups, is_superuser, may_author, may_administer, studio_enabled)`; `app["scope_resolver"]` (legacy `app["ui_surfaces_scope_resolver"]`); `get_scope_resolver(app)`; `has_installed_resolver(app)` | FEAT-605 W0.1 | STORAGE (duck-typed `.tenant` only), TOOLKITS M5 | "Opted-in host" := `has_installed_resolver(app)` |
| X10 | `setup_studio_routes(app, *, prefix=None, view_wrapper=None)`; `BotManager.setup(..., studio_routes=True)`; `BotManager.setup_registry_only(app)` | FEAT-605 W0.2 (routes, mount, manager-level lifecycle), W2.2 (`setup_registry_only` calls STORAGE `add_studio_runtime_hooks(app)`) | STORAGE (`setup_studio_routes` registers `resolve_studio_storage`), host | Idempotent per prefix; every hook (FEAT-467 `reconcile_skills_catalog`, STORAGE `resolve_studio_storage` and the X8 runtime hooks, FEAT-605's assistant clean-up) appended at most once per app, whatever the number of prefixes or calls. `setup_registry_only` registers no route, imports no `AGENTS_DIR` module or YAML definition, and is not recommended to tenant hosts until W2.2 has merged. Documented mount order: resolver → `setup_registry_only` → `setup_studio_routes`; the reverse order behaves the same (X8) |
| X11 | `RequestContext.kwargs["studio_scope"]` = `StudioToolScope(caller: RequestScope, agent: StudioAgentRef \| None)`, built only by `build_tool_scope(scope, agent=None)` in `handlers/studio/access.py`; `StudioAgentRef(agent_id, name, owner, tenant, visibility)` | FEAT-605 W2.1 (builder); binds at test/ask (W3.4) and the meta-agent (W3.5) | TOOLKITS (`ToolScopeView` / `CallerView` / `AgentScopeView` Protocols; binds at `chat.py`, execute and options in M5); STORAGE assistant tools (partition = `StudioPartition.from_scope(studio_scope.caller)`) | Nothing is bound without a resolver. For an addressed agent `agent.tenant == caller.tenant` |
| X12 | Routes: `PATCH /agents/{name}` (General fields) | STORAGE W3 (route, `StudioAgentPatch`, version bump) | FEAT-605 W3.1 (policy row) | Name immutable (422 `name_immutable`); legacy agent 409 `not_studio_agent`; `can_manage` inside the tenant + `may_author`; 404 first; tooling policy re-checked (X18) |
| X13 | Routes: `GET /me`; `PATCH /agents/{name}/visibility`, `/drafts/{name}/visibility`, `/skills/{id}/visibility` | FEAT-605 (W1.2, W3.1–W3.3, W4.1) | UI, host | Persist through the X6 `update_visibility` service methods, with a `StudioWriteGuard` |
| X14 | Error codes (code — HTTP status — owner) | STORAGE: `studio_storage_unavailable` 503; `version_conflict` 409; `expected_version_unsupported` 400; `unsupported_config_key` 422; `name_immutable` 422; `not_studio_agent` 409; `asset_too_large` 413; `agent_assets_quota` 413; `binary_assets_unsupported` 415. FEAT-605: `name_taken` 409 (raised from `StudioNameConflict`); `declarative_only` 422 (also STORAGE's tenant-path Python-draft refusal); `studio_disabled` 404; `tenant_mismatch` 403; `authoring_denied` 403; `reserved_config_key` 400; `tenant_required` 422; `groups_required` 422; `groups_not_allowed` 422 (`allowed_groups` outside the caller's own groups); `not_manageable` 403 (visible but not manageable, on every Studio route). TOOLKITS: `tooling_not_permitted` 422 on write, activation, attach and a refused build, 403 on execute (STORAGE maps `StudioToolingRefused` to it); `confirmation_required` 403 on execute; `server_managed` 422 (a client-supplied server-managed key on PUT, `/me`, assign or the execute body, or a server dependency the endpoint cannot supply); `tool_scope_unavailable` 403 on execute and options | all three | One owner, one code and one HTTP status per condition across the package; no spec defines a synonym. Inside an agent run, TOOLKITS refusals are a `ToolResult` (`status` `error`/`forbidden`) carrying the same `metadata.error_code`. `ScopeRefusal` and `ToolingRefusal` values (e.g. the scope reason `tenant_mismatch`) travel in `details.reason` / `metadata.reason` and are never top-level codes |
| X15 | `get_toolkit_resolver()` / `ToolkitResolver`; `server_managed_params`, `ServerParam`; `tenant_bound`; `TenantToolingPolicy`, `enforce_tenant_tooling(app, tooling, *, subject)`, `get_tenant_tooling_policy(app)`; the build hook `apply_tooling_specs(*, tooling_policy=, tooling_subject=)` with `AbstractBot.bind_tooling_policy(policy, subject)`; `ensure_tool_scope(cls)`; STORAGE `StudioToolingGate` (calls TOOLKITS) | TOOLKITS Wave 1 (M1, M3a, M7 core incl. the build hook and `bind_tooling_policy`), Wave 3 (M4); STORAGE W2 (`StudioToolingGate`) | STORAGE (`StudioToolingGate.enforce` on every write and activation; `StudioAgentBuilder` runs the gate with `phase="build"`, then `bot.bind_tooling_policy(get_tenant_tooling_policy(app), ToolingSubject(part.tenant, agent_id, None, "build"))` before `configure()`, whose existing `apply_tooling_specs()` call picks the binding up; `StudioToolingService` reuses the refusal of server-managed keys) | Storage-agnostic: resolver, policy and refusals work on either backend. `bind_tooling_policy` is valid only before tooling is applied (else `RuntimeError`); a bound tenant subject without a policy behaves as `deny_all()` |
| X16 | Merge order and release gate | — | all three | **No sibling dependency** (early): FEAT-605 W0.1–W0.3 and W1.1–W1.5 (its whole early subset), TOOLKITS Wave 1, STORAGE W0 and W1. **Before STORAGE W3**: FEAT-605 W1.3 (`testing.py` execute, `skills_catalog.py` resync), W1.4 and W1.5 (`drafts.py`) merge first and STORAGE W3 rebases on them (its `_legacy_*` bodies carry the D1/D3 guards); these are the only exceptions to the per-file rule. **Identity files**: STORAGE W1 "Tooling identity plumbing" (M13) merges **first** on `studio/tooling_store.py`, `studio/toolkit_overrides.py`, `handlers/toolkit_persistence.py` and `handlers/agent.py`; TOOLKITS M9 (R3 consumer) follows on every one of them: on `toolkit_persistence.py` and `agent.py` M9 makes no edit (M13 owns the key plumbing; M9 only tests it, and P2 M12 later edits `toolkit_persistence.py` after M9), on `tooling_store.py` and `toolkit_overrides.py` it merges after STORAGE W3 like every other TOOLKITS edit there. **Per-file rule**: every other FEAT-605 or TOOLKITS task that edits a Studio handler file also edited by STORAGE W2/W3 (`agents.py`, `drafts.py`, `skills_catalog.py`, `files.py`, `testing.py`, `tooling_store.py`, `toolkit_config.py`, `toolkits.py`, `toolkit_overrides.py`, `meta_agent.py`, core `bots/studio/tools.py`) merges **after** the STORAGE task for that file and rebases on it. `studio/_base.py`, `studio/__init__.py` and `manager/manager.py` (STORAGE W1/W2; FEAT-605 W0.2, W1.1, W2.1, W2.2, W3.6) carry small non-overlapping edits: serialise, whichever merges first, except that FEAT-605 W2.2 needs STORAGE W2 (runtime + hooks). Core `interfaces/tools.py`: TOOLKITS M7 core (Wave 1) before STORAGE W2 (builder), then TOOLKITS M2/M4 serialise. **Cross-spec waits**: FEAT-605 W2.1 needs STORAGE W0 + W1; STORAGE W2 services need TOOLKITS Wave 1 (M7 core); TOOLKITS Wave 2 lands M6 together with M8 (no build resolves host write tools without M8); TOOLKITS Wave 4 (M3b + M5) needs FEAT-605 W2.1 (`build_tool_scope`) and STORAGE W2 (runtime identity), and W3.4/W3.5 for the asserted bindings; FEAT-605 W3.6 (assistant partitioning) needs W3.5 and STORAGE W3 "Assistant tools on services" (`meta_agent.py`). **Release gate**: no release is called, documented or enabled as tenant-ready until every spec's gate is met — FEAT-605 §3 "Release gate" (through W4.3, incl. W2.2 and W3.6), STORAGE W0–W4 (W4 = shape snapshot + host guide), TOOLKITS Waves 1–4 (§9 there). Early subsets (FEAT-605's, TOOLKITS discovery, STORAGE on plain hosts) never ship as tenant-ready; tenant hosts keep `studio_enabled=False` until the gate is met |
| X17 | Identity scheme: `agent_id` (immutable uuid, never reused); tooling ref `studio-agent:<agent_id>` (`StudioAgentRecord.tooling_ref`, `bot._tooling_ref`, core `agent_tooling_ref(bot)`); vault names `toolkit_<slug>_studio-agent:<uuid>` (`toolkit_vault_name(slug, ref)`), `mcp_agent_<server>_studio-agent:<uuid>` (`mcp_vault_name(server, ref)`), `toolkit_<slug>_studio-agent:<uuid>_user` (`toolkit_override_vault_name(slug, ref)`); override document key `{user_id, agent_id: <ref>, slug}`; session keys `<ref>_toolkit_overrides_rev`, `<ref>_tool_manager`; runtime `chatbot_id = str(agent_id)`; registry key `studio:<tenant\|->:<name>`; the Studio assistant's `chatbot_id = "agent_studio:<tenant\|->"` | STORAGE W0 (M2 records, M10 core helpers), W1 (M13 plumbing), W2 (builder stamps `chatbot_id`, `_tooling_ref`, `_studio_agent_id`); FEAT-605 W3.6 (assistant identity) | TOOLKITS (M5, M7 build-time namespace check, M9), FEAT-605 (test chat, assistant, AC25) | Legacy agents keep their bare-name identities byte for byte (`agent_tooling_ref(bot) == bot.name`). `:` never occurs in a Studio or legacy slug, so a ref never equals a legacy name. Every key read or write receives the ref from the partitioned lookup, never from the URL name. Delete + recreate yields a new `agent_id`: no credential, override, memory or cache is inherited. The registry key is used only inside `StudioRuntimeCache` and test-session keys; it never names a vault entry, an override or a memory. The assistant is not a Studio agent: FEAT-605 partitions it by `(tenant or "-", user_id)` and passes explicit `user_id` / `session_id` to `ask` |
| X18 | Policy, enforcement and confirmation: `TenantToolingPolicy` (default `deny_all()`), `set_tenant_tooling_policy(app, policy)` (once, before startup), `get_tenant_tooling_policy(app)`, `enforce_tenant_tooling(app, tooling, *, subject)`, `ToolingSubject(tenant, agent_id, actor, phase)`; `require_tool_scope` / `ensure_tool_scope` and the automatic gate in `AbstractTool.execute` and the wrapped `config_options`; the approval token set only by `ToolManager` after a `ConfirmationGuard` `confirmed` decision; `app["studio_confirmation_guard"]` | TOOLKITS Wave 1 (M7 core, M3a), Wave 2 (M6 + M8, M7 wiring), Wave 4 (M3b, M5) | STORAGE (`StudioToolingGate` on every write, activation and build; the builder binds the policy and installs `app["studio_confirmation_guard"]` on the bot's `ToolManager` when present), FEAT-605 (route rows C35/C36: tooling writes, activation, test/ask, execute, options, meta-agent writing tools) | Applies when `subject.tenant is not None` (GLOBAL only with `apply_to_global`). Evaluated on the **final normalised** configuration (the `params` overlay and vault fields included) before any row, vault write, process start or connection; tenant-supplied local execution (stdio/unix, `command`/`args`/`env`/`socket_path`) is denied by default; client- or bundle-supplied `secret_refs`/`vault_owner` are refused; at build every vault name must be the ref-derived name of X17. Tenant-bound tools and options providers refuse a missing or mismatched scope before any side effect. A `confirmation_enforced` host write runs only with a matching approval token: no guard, no channel or direct execute ⇒ zero writes. Codes: X14 |

---

## 9. Task Breakdown (waves; no IDs until approval)

Release gate: **no release is called, documented or enabled as tenant-ready**
until Waves 1–4 are merged **and** every sibling's gate is met (package X16:
FEAT-605 §3 "Release gate", storage W0–W4). Discovery (Waves 1–2) may ship early
only for hosts without a resolver (GLOBAL partition); in such a build, tenant-bound
host entries are `unavailable` (resolver rule 5) and host writes are already
fail-closed (M8).

- **Wave 1** (parallel; no sibling dependency — resolver discovery and pure policy):
  - resolver (M1) plus its unit tests;
  - scope contract types, `is_tenant_bound`, `ensure_tool_scope` (M3a), no call sites;
  - `TenantToolingPolicy`, `effective_mcp_config`, `enforce_tenant_tooling`, registration, `hydrate_mcp` hardening, the build hook in `apply_tooling_specs` and `bind_tooling_policy` (M7 core) plus unit tests incl. `test_bind_tooling_policy_reaches_configure`. Merges **before** storage W2 (its services and builder call these).
- **Wave 2** (after Wave 1; per file after storage W2/W3, see §8):
  - adopt the resolver on all seven paths (M2), plus `test_every_studio_path_sees_host_toolkit`;
  - host conventions and strict marking (M6) **together with** host-write confirmation (M8): no build resolves host write tools without M8;
  - M7 wiring on the FEAT-593 write, assign, attach, execute and catalogue paths, plus `test_tenant_stdio_refused_before_any_process` and `test_approved_host_config_still_works`. Storage wires its own services and builder (§8).
- **Wave 3** (per file after storage W2/W3):
  - server-managed params: the ClassVar, both schema paths, refusals, fills, migrating wiki and infographic, and deleting both dicts (M4);
  - Studio identity keys, consumer side (M9): after storage M13 (W1) on every identity file and after storage W3 on `tooling_store.py` / `toolkit_overrides.py`; no edit to `toolkit_persistence.py` or `handlers/agent.py`; plus `test_same_names_two_tenants_independent_secrets_and_overrides` (needs storage W3 and FEAT-605 W2.1).
- **Wave 4** (after FEAT-605 v0.2 W2.1 `build_tool_scope` and storage W2 runtime identity; W3.4/W3.5 for the asserted bindings):
  - scope enforcement (M3b): the gate in `AbstractTool.execute`, the `config_options` wrapper, custom-schema refusals, execute/options pre-construction checks; lifts resolver rule 5;
  - scope binding in chat, execute and options, and asserting the test-chat and meta-agent bindings (M5);
  - the join, concurrency, mismatch, no-request, standalone-execute and options regression tests;
  - the host-toolkit guide page.

---

## 10. Questions and resolved requirements

### Product questions (for Jesus)

- [x] **Q1: Host registration mechanism.** **Decided 2026-09-30 (Juan, with Jesus's go-ahead; revisit in PR #1524 if needed): recommendation adopted.** Should parrot honour a declarative
  `plugins.tools.TOOL_REGISTRY` (+ `HOST_TOOL_PREFIX`), or offer a
  programmatic `register_host_toolkits(app, {...})` hook?
  *Recommendation: the declarative registry.* It needs no app, so bot build
  and the catalogue work at import time, and it matches `parrot_tools`. No
  runtime mutation either way. — *Owner: Jesus*
- [x] **Q3: Walk fallback lifetime.** **Decided 2026-09-30 (Juan, with Jesus's go-ahead; revisit in PR #1524 if needed): recommendation adopted.** Should the resolver keep walking a
  `plugins.tools` that has no `TOOL_REGISTRY`?
  *Recommendation: keep it one minor version, with a deprecation warning,
  then require the registry.* — *Owner: Jesus*
- [x] **Q4: Toolkit methods on `/tools/{slug}/execute`.** **Decided 2026-09-30 (Juan, with Jesus's go-ahead; revisit in PR #1524 if needed): recommendation adopted.** Today only
  `AbstractTool` classes run there.
  *Recommendation: keep it that way in this spec.* FieldSync does not mount
  execute (FieldSync P6). A `{slug}.{method}` form can be a follow-up; it would inherit
  M3b and the M8 execute refusal unchanged. — *Owner: Jesus*
- [x] **Q7: Default access for built-ins.** **Decided 2026-09-30 (Juan, with Jesus's go-ahead; revisit in PR #1524 if needed): recommendation adopted.** Should `parrot_tools` toolkits
  that have no `read_tools` stay `access=None` ("unknown"), or default to
  `"write"`?
  *Recommendation: `None` now,* so no confirmation behaviour changes for the
  GLOBAL partition. Tenant availability of built-ins is already governed by
  `builtin_tools` (R1). Only host toolkits default to `"write"`. — *Owner: Jesus*
- [x] **Q8: Conventions that are not enforced.** **Decided 2026-09-30 (Juan, with Jesus's go-ahead; revisit in PR #1524 if needed): recommendation adopted.** Should Pydantic return
  types and row caps (`max_rows` + `truncated`) be enforced by the resolver,
  or documented only?
  *Recommendation: document them, and enforce only the prefix and the
  read/write marker.* Return-type enforcement would reject existing
  `str`/`dict` tools. — *Owner: Jesus*
- [x] **Q9: Scheduler and A2A principal.** **Deferred 2026-09-30 — non-blocking follow-up:** a separate feature; until it exists tenant-bound tools refuse (`no_context`). Should a separate feature give
  schedulers/A2A a principal carrying a stamped tenant? Until it exists they
  refuse (`no_context`, RC-5 below). — *Owner: Jesus / Juan*
- [x] **P-Q1: Built-ins a tenant host should allow.** **Moved to the host:** FieldSync decides its `builtin_tools` list in its own mount spec; parrot's default stays `deny_all()` (none). Which built-ins, if
  any, should FieldSync list in `builtin_tools` (e.g. `wiki`, `infographic`,
  `dataset_manager`)? Default is none. — *Owner: Juan (host), Jesus (review)*
- [x] **P-Q2: Approval channel for Studio test chat.** **Deferred 2026-09-30 — non-blocking follow-up:** until a HITL channel exists, host write tools are refused in test chat, by design. Which HITL channel
  (`HumanInteractionManager` backend) should Studio offer so host write tools
  are usable in test chat? Until one exists they are refused, by design. —
  *Owner: Jesus*
- [x] **P-Q3: Policy for the GLOBAL partition.** **Decided 2026-09-30 (Juan, with Jesus's go-ahead; revisit in PR #1524 if needed): recommendation adopted.** opt-in (`apply_to_global=False`) with a deprecation note; the host-guide statement in §2 applies. Should single-tenant hosts
  also get `deny_all()` by default (`apply_to_global=True`), which would change
  today's behaviour for existing deployments?
  *Recommendation: opt-in (`False`) in 1.0.7, with a deprecation note.* —
  *Owner: Jesus*

### Resolved correctness requirements (not open)

- **RC-1 (was Q2): no shadowing.** A host slug never shadows a built-in or
  `parrot_tools` slug; it is rejected and logged (resolution rule 2).
- **RC-2 (was Q5): one scope object.** `studio_scope` is one
  `StudioToolScope(caller, agent)` built by `build_tool_scope`, as FEAT-605
  v0.2 C16 adopted.
- **RC-3 (was Q6): unstamped agents refuse.** A tenant-bound tool on an agent
  whose record has `tenant=None` refuses with `agent_tenant_unset`, always.
  Opted-in hosts never read tenant-NULL rows (FEAT-605 C15, C24). This
  supersedes J11 "adopt on first visibility change".
- **RC-4 (R1): tenant tooling is policy-checked** on the final normalised
  configuration at every write, activation, attach, execute and build;
  tenant-supplied local execution is denied (§2 "Tenant tooling policy").
- **RC-5 (was Q9, first half): no request, no data.** Tenant-bound tools
  refuse with `no_context` when no request exists.
- **RC-6 (R6): enforcement is automatic** for toolkit methods, standalone tools
  and options providers, before any side effect (§2 "Scope enforcement").
- **RC-7 (R7): host writes need an approval token**; zero writes without one,
  including direct execute (§2 "Host-write confirmation").
- **RC-8 (R3): Studio keys use the storage ref `studio-agent:<agent_id>`** now
  (storage M13, v1), independent of storage phase 2 (§2 "Tenant-safe identity
  keys", X17).
- **RC-9 (was a storage open point): build-hook plumbing.** The storage builder
  passes the policy to `apply_tooling_specs` through `bind_tooling_policy`
  before `configure()`; `configure()` is unchanged (§2 "Build-hook plumbing").

---

## Design Compliance (FieldSync ARCHITECTURE.md, applied to the upstream ask)
- [x] R1 Library-first: it reuses `discovery.resolve_class` / `discover_from_walk`, `current_context()`, `confirming_tools`, `ConfirmationGuard` / `compute_args_hash`, `MCPClient._detect_transport` semantics, `config_schema`, and the `AuthorizationRequired` pattern. Nothing is re-implemented, and five ad-hoc resolvers become one.
- [x] R2 Endpoints: no new routes. The existing CBVs change behaviour only.
- [x] R3 app.py: N/A (upstream library). The host adds only `plugins/tools/__init__.py` and one `set_tenant_tooling_policy(app, ...)` call in its composition root.
- [ ] R4 Complexity: `resolver.py`, `scope.py` and `tooling_policy.py` each stay well under 500 lines; `AbstractTool.execute` is already long, so the gate and token check are extracted into helpers (`_enforce_scope_and_approval`) rather than inlined. `flake8` runs per task.
- [x] R5 Layering: handlers bind context and call the policy hook, the resolver, scope and policy live in core, and tools stay free of HTTP.
- [x] R6 Test doubles: §4 requires real aiohttp requests with `request[SESSION_OBJECT]`, FEAT-605's real scope types, an end-to-end join test, side-effect counters instead of mocks for the refusal proofs, and mutation checks.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-30 | Juan Ruffato (with Claude) | Initial draft for the Agent Studio host-integration package |
| 0.1.1 | 2026-09-30 | Juan Ruffato (with Claude) | Package reconciliation: FEAT-605 builder/type names, storage runtime key and chat reach, `ai_agent_tooling` columns, secrets depend on DocumentDB or storage P2, per-file merge order, cross-spec contract section |
| 0.2 | 2026-09-30 | Juan Ruffato (with Claude) | **R1**: host-owned `TenantToolingPolicy` (P4, G6, §2 "Tenant tooling policy", M7): registration, check order on the final kwargs after `hydrate_mcp`, deny-by-default local execution, named host servers and https endpoint allow-list, built-in allow-list, write/activate/attach/execute/build enforcement table, `enforce_tenant_tooling` and `apply_tooling_specs(tooling_policy=, tooling_subject=)` hooks for storage, `hydrate_mcp` hardening, regression tests |
| 0.2 | 2026-09-30 | Juan Ruffato (with Claude) | **R6**: scope gate moved to `AbstractTool.execute` before `_ensure_open` (covers standalone tools and direct execute), `config_options` wrapped at class creation, execute/options check before construction and vault read, server-managed handling for custom schemas, remote-executor refusal, M3 split into M3a/M3b, regression tests |
| 0.2 | 2026-09-30 | Juan Ruffato (with Claude) | **R7**: `confirming_tools` no longer counts as enforcement; approval-token ContextVar set only by `ToolManager` after a `confirmed` decision, window 0, fail-closed without guard, direct execute refuses host writes (§2 "Host-write confirmation", M8), regression tests |
| 0.2 | 2026-09-30 | Juan Ruffato (with Claude) | **R3** (consumer side): P7, G8, §2 "Tenant-safe identity keys", M9; non-goal rewritten (DocumentDB may stay, bare-name keys may not); storage scheme referenced with the `studio/<agent_id>/...` placeholder; two-tenant same-name CRUD + delete/recreate test |
| 0.2 | 2026-09-30 | Juan Ruffato (with Claude) | **Sequencing** (review "Package decisions"): waves rebuilt — discovery and pure policy first, enforcement and binding after FEAT-605 W2.1 and storage runtime identity; release gate; resolver rule 5 keeps tenant-bound host entries unavailable until enforcement lands; §10 split into product questions and resolved requirements (Q2, Q5, Q6, Q9 first half resolved) |
| 0.2.1 | 2026-09-30 | Juan Ruffato (with Claude) | **Package reconciliation** (owner names win): placeholder `studio/<agent_id>/...` vault names and override key replaced by the storage scheme — ref `studio-agent:<agent_id>`, `toolkit_<slug>_studio-agent:<uuid>`, `mcp_agent_<server>_studio-agent:<uuid>`, `toolkit_<slug>_studio-agent:<uuid>_user`, override `{user_id, agent_id: <ref>, slug}` — in §2, tests, AC, §6, §8; M9 narrowed to the consumer side (no edits to `toolkit_persistence.py` / `handlers/agent.py`; storage M13 goes first per file); new §2 "Build-hook plumbing": `AbstractBot.bind_tooling_policy` in `interfaces/tools.py`, used by the storage builder before an unchanged `configure()` (RC-9, `test_bind_tooling_policy_reaches_configure`); `server_managed` fixed at 422 on PUT and `/me` too (was "400" in a test, 422 `invalid_params` in code) and the error surface now lists every TOOLKITS code with one status; "until storage P2 (Q5)" → storage M12; release gate tied to every sibling's gate; "Cross-spec contract (package)" rewritten (identical in the three specs, new rows X17 identity and X18 policy/enforcement/confirmation) |
| 0.2.2 | 2026-09-30 | Juan Ruffato (with Claude) | Adversarial-review follow-ups: build-time policy refusal fails closed (aligned with STORAGE §2.7); mandatory host-guide statement that GLOBAL is outside tenant policy. |
