---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
feature_id: FEAT-TBD  # PROVISIONAL — reserved on approval
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-server]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [agentstudio, toolkits, multi-tenant, host-integration, tool-scope]
---

<!-- LANGUAGE: This document MUST be written entirely in English (proper nouns keep native spelling). -->

# Feature Specification: Agent Studio — Host Toolkits

**Feature ID**: FEAT-TBD (provisional; reserved on approval)
**Date**: 2026-09-30
**Author**: Juan Ruffato (with Claude), for review by Jesus Lara
**Status**: draft
**Target version**: ai-parrot 1.0.7 + ai-parrot-server 1.0.7 (lockstep)
**Inputs**: FieldSync `sdd/proposals/fieldsync-agent-toolkits.brainstorm.md`
(upstream asks U1 and U2, F1–F3, Q1–Q3, Q10); FieldSync
`artifacts/agentstudio/command-board-2026-09-30.md` (J8, J9, J11).
**Package siblings** (same review package):
- `sdd/specs/agentstudio-tenant-visibility.spec.md`: FEAT-605 v0.2. It produces `studio_scope`.
- `sdd/specs/agentstudio-db-storage.spec.md`: the storage spec. It owns `navigator.ai_agent_tooling`
  and the Studio runtime that builds agents from it.
- The exact shared names are in "Cross-spec contract (package)" below, identical in all three specs.

**Snapshot**: ai-parrot `dev` @ `3f0f2f726`. Every `file:line` below was checked there.

---

## 1. Motivation & Business Requirements

### Problem Statement

A host application (FieldSync first) mounts Agent Studio and needs its
authors to attach **host-owned toolkits**, for example "events of my
programme" or "my team". Those tools read tenant data. Today two things are
missing.

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
- **G3: fail closed.** A tenant-bound tool refuses with one standard error,
  `ToolScopeUnavailable`, when there is no request (scheduler, A2A), no
  scope, no tenant, or a tenant mismatch.
- **G4: declarative server-managed params.** A toolkit declares them in a
  `ClassVar`. They are never user-configurable and never read from client
  JSON or from the LLM. The ClassVar replaces `_SERVER_MANAGED`. The
  built-in toolkits migrate to it.
- **G5: host toolkit conventions.** A host slug prefix, a read/write marker
  on every tool (writes are confirm-first), Pydantic return types, and row
  caps.

### Non-Goals (explicitly out of scope)

- Storage of toolkit config. Agent-level tooling moves to
  `navigator.ai_agent_tooling` (`position`, secret-free `config`,
  `secret_refs`, `vault_owner`), which the storage spec owns. This spec only
  requires that neither `config` nor `secret_refs` ever contains a
  server-managed key. Secret **values** and per-user `/toolkits/{slug}/me`
  overrides do **not** move: they stay in the DocumentDB vault until the
  storage spec's phase 2 (its Q5). Anything here that stores a secret in a
  host without DocumentDB requires storage P2.
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

---

## 2. Architectural Design

### Overview

Three small pieces are added to ai-parrot core, and the server wires them
into its entry points:

1. **`ToolkitResolver`** (`parrot/tools/resolver.py`, new) is the one
   slug → class authority. It merges three sources:
   - the built-in explicit entries (`dataset_manager`, `wiki`, `infographic`);
   - `parrot_tools.TOOL_REGISTRY`;
   - the host's declared `plugins.tools.TOOL_REGISTRY`, which must carry
     `HOST_TOOL_PREFIX`.

   It never mutates a registry. It rejects host slugs that collide with
   built-ins or lack the prefix. It exposes `resolve(slug)` and `entries()`
   (for the catalogue).
2. **Tool scope contract** (`parrot/tools/scope.py`, new):
   - `ToolScopeView` Protocols describe what a tool may read from
     `current_context().kwargs["studio_scope"]`.
   - `current_tool_scope()` and `require_tool_scope()` read it.
   - `ToolScopeUnavailable` is the standard refusal.
   - A toolkit that sets `tenant_bound = True` is gated by the base class
     before `_pre_execute`, so a host cannot forget the check.
3. **`server_managed_params`** is a ClassVar on `AbstractToolkit` (and on
   `AbstractTool`) that maps a param name to a `ServerParam(source, key)`:
   - A **constructor** param is marked `x-server-managed` in every schema,
     rejected on PUT and on override, and filled by the server at
     construction.
   - A **method** param is hidden from the LLM args schema and filled per
     call from the scope.

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

FEAT-605 v0.2 builds studio_scope ──▶ bot.session(..., studio_scope=scope)   [test chat, meta-agent]
                                  ──▶ this spec binds it                      [chat.py, execute, options]
                                            │
                                            ▼  current_context().kwargs["studio_scope"]
       ToolkitTool._execute ─▶ (tenant_bound?) require_tool_scope() ─▶ fill server-managed method params
                            ─▶ toolkit._pre_execute (host cross-checks its own validated tenant)
                            ─▶ method ─▶ Pydantic result (capped)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `discovery.discover_from_registry` (`discovery.py:31`) | uses | The resolver reads declared registries itself. `discover_*` keep their signatures for `ToolManager`. |
| `AbstractBot._resolve_spec_class` (`interfaces/tools.py:177`) | modifies | Delegates to the resolver. `apply_tooling_specs` fills constructor server-managed params (`:242`). |
| `_resolve_toolkit_class` (`toolkits.py:156`), `_resolve_registry_class` (`testing.py:92`), `_EXPLICIT` (`tooling_store.py:39`) | replaces | Thin shims that call the resolver, so imports and tests keep working. |
| `tools_catalog._build_catalog` (`tools_catalog.py:44`) | modifies | Iterates `resolver.entries()`. Adds `source` and `access` per entry. |
| `_SERVER_MANAGED` (`tooling_store.py:40`), `_KNOWN_APP_DEPS` (`testing.py:42`) | replaces | Read from the ClassVar. The dicts are deleted once the built-ins declare it. |
| `introspect_config_schema` / `model_config_schema` (`config_schema.py:92`, `:122`) | modifies | Both honour the ClassVar (this closes the model-path gap). |
| `ToolkitTool._execute` (`toolkit.py:142-201`), `_generate_args_schema_from_method` (`toolkit.py:95`) | modifies | Scope gate, per-call fills, and args-schema exclusion. |
| `AbstractTool.execute` error path (`abstract.py:1191-1205`) | modifies | `ToolScopeUnavailable` → `ToolResult(status="error")` carrying `error_code` and `reason`. |
| `StudioTestingHandler.post` (`testing.py:270`), `meta_agent.py:110` | consumes | FEAT-605 v0.2 passes `studio_scope=`. This spec only asserts it (see §6). |
| `chat.py:455`, `StudioToolExecuteHandler` (`testing.py:393`), `StudioToolkitOptionsHandler` (`toolkit_config.py:157`) | modifies | Bind a `RequestContext` carrying `studio_scope` (built with FEAT-605's builder). |
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

class AgentScopeView(Protocol):        # satisfied by FEAT-605's StudioAgentRef (it also carries agent_id)
    name: str
    owner: str | None
    tenant: str | None
    visibility: str                    # "private" | "tenant" | "groups"

class ToolScopeView(Protocol):         # REQUIRED shape of current_context().kwargs["studio_scope"] (FEAT-605 v0.2)
    caller: CallerView
    agent: AgentScopeView | None       # None only on agent-less calls (execute)

ScopeRefusal = Literal[
    "no_context",           # no RequestContext / no request: scheduler, A2A, background task
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
```

### New Public Interfaces

```python
# parrot/tools/resolver.py (new)
class ToolkitEntry(BaseModel, frozen=True):
    slug: str
    dotted_path: str | None            # None for built-in explicit entries
    source: Literal["builtin", "parrot_tools", "host"]

class ToolkitResolver:
    def entries(self) -> list[ToolkitEntry]: ...
    def resolve(self, slug: str) -> type | None: ...     # case-insensitive, like today
    def reload(self) -> None: ...                        # tests / hot reload only

def get_toolkit_resolver() -> ToolkitResolver: ...        # process-wide, lazily built

# parrot/tools/scope.py (new)
def current_tool_scope() -> ToolScopeView | None: ...
def require_tool_scope(*, tool_name: str | None = None) -> tuple[str, ToolScopeView]: ...
    # returns (tenant, scope) or raises ToolScopeUnavailable

# AbstractToolkit (parrot/tools/toolkit.py, next to options_params :327) — new ClassVars
tenant_bound: ClassVar[bool] = False
server_managed_params: ClassVar[Mapping[str, ServerParam]] = {}
read_tools: ClassVar[frozenset[str]] = frozenset()        # method names that are read-only
# AbstractTool gets `tenant_bound`, `server_managed_params` and `access: ClassVar[ToolAccess | None] = None`.

# host side: plugins/tools/__init__.py
HOST_TOOL_PREFIX = "fs_"
TOOL_REGISTRY = {"fs_events": "plugins.tools.fieldsync.events.FieldsyncEventsToolkit"}
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
   classes keep their current keys. This keeps `POST /agents/{name}/tools`
   and `/execute` behaving exactly as before.
4. `plugins.tools` missing (`ImportError`) means no host entries. It is not
   an error.

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
    on the `/me` override.
  - Assign and bot build drop any client or stored value, then fill it:
    - `source="app"` → `app[key]`;
    - `source="server"` → the bespoke builder, as `_assign_wiki` does today.
  - `tenant`, `caller` and `agent` sources are **forbidden** on constructor
    params, because an instance is shared across callers.
    `__init_subclass__` raises `TypeError`.
- **Method param** (the name is in a tool method's signature):
  - It is excluded from `_generate_args_schema_from_method`.
  - An LLM-supplied value is dropped with a warning.
  - It is filled in `ToolkitTool._execute` from `require_tool_scope()`:
    - `tenant` → `str`;
    - `caller` → `CallerView`;
    - `agent` → `AgentScopeView | None`.
  - Declaring any such param implies `tenant_bound = True`.
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
- A host write tool is added to `confirming_tools` automatically, so writes
  are always confirm-first.

**Error surface:**

- In an agent run, `ToolScopeUnavailable` goes through the existing generic
  path (`abstract.py:1191-1205`). That path already sets
  `metadata.error_type="ToolScopeUnavailable"`. This spec adds
  `metadata.error_code="tool_scope_unavailable"` and `metadata.reason`.
- On `POST /tools/{slug}/execute`, the same `ToolResult` is returned with
  **HTTP 403** and body code `tool_scope_unavailable`.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: toolkit-resolver | yes | rules 1–4 above, `ToolkitEntry`, shims keep old names | — |
| M2: resolver-adoption | yes | every row of the P1 table calls `get_toolkit_resolver()` | — |
| M3: tool-scope-contract | yes | Protocols, refusals, `require_tool_scope` order fixed | — |
| M4: server-managed-params | no | — | ClassVar fill order in `apply_tooling_specs` interacts with `hydrate_params` and the DatasetManager branch (`interfaces/tools.py:203-228`). Needs a design pass during `/sdd-task`. |
| M5: scope-binding | yes, after FEAT-605 v0.2 freezes its builder name | bind sites fixed | depends on a sibling name |
| M6: host-conventions | yes | prefix, `read_tools`, auto-confirm, catalogue fields | — |

### Module 1: toolkit-resolver
- **Path**: `packages/ai-parrot/src/parrot/tools/resolver.py` (new)
- **Responsibility**: the single slug → class authority (rules 1–4).
- **Depends on**: `discovery.py` (`resolve_class`, `discover_from_walk`)
- **Interface Skeleton**: see §2 *New Public Interfaces*.

### Module 2: resolver-adoption
- **Path**: `interfaces/tools.py:177`, `studio/toolkits.py:156`, `studio/testing.py:92`, `studio/tooling_store.py:39,138`, `handlers/tools_catalog.py:44`
- **Responsibility**: every P1 path calls `get_toolkit_resolver()`.
  - `_resolve_toolkit_class`, `_resolve_registry_class` and `_resolve_spec_class` become one-line shims.
  - The catalogue cache (`tools_catalog._CATALOG_CACHE`) is built from `entries()`.
  - Persisted specs whose slug no longer resolves are **kept**, and reported as `unavailable` (not deleted) in the FEAT-593 list response.
- **Depends on**: M1

### Module 3: tool-scope-contract
- **Path**: `parrot/tools/scope.py` (new), `parrot/tools/toolkit.py:142-201`, `parrot/tools/abstract.py:1191-1205`
- **Responsibility**: Protocols, accessor, error, the `tenant_bound` gate before `_pre_execute`, and the error metadata.
- **Depends on**: — (it only reads `current_context()`)

### Module 4: server-managed-params
- **Path**: `parrot/tools/server_params.py` (new), `toolkit.py` (ClassVars, `:95`, `__init_subclass__`), `abstract.py` (ClassVars), `config_schema.py:92,122`, `interfaces/tools.py:230-242`, `studio/tooling_store.py:40,167`, `studio/testing.py:42,122-161`, `studio/toolkits.py:443-459`, `studio/toolkit_overrides.py`, wiki and infographic toolkits
- **Responsibility**: the server-managed rules above, and migrating plus deleting both hard-coded dicts.
- **Depends on**: M1, M3

### Module 5: scope-binding
- **Path**: `handlers/chat.py:455`, `studio/testing.py:393`, `studio/toolkit_config.py:157`
- **Responsibility**: wrap each call in `RequestContext(request=..., app=..., studio_scope=build_tool_scope(scope, agent))` (FEAT-605 `handlers/studio/access.py`).
  - Normal chat and options bind a `StudioAgentRef` when the bot is a Studio agent, recognised by `bot._studio_key` (storage spec runtime).
  - `chat.py` resolves bots with `get_bot(name)`, which never returns a tenant row (storage §2.7). So in v1 the only Studio agents chat can bind are tenant-NULL rows, whose tools refuse with `agent_tenant_unset`; tenant agents in normal chat are the storage/FEAT-605 P13 follow-up. A non-Studio bot binds `agent=None`.
  - Options resolve the agent through `AgentToolingStore` (Studio row → `StudioAgentRecord`), then FEAT-605's `StudioAccess.agent_ref`.
  - Execute binds `agent=None`.
  - When the host installed no resolver (`has_installed_resolver(app)` is false, FEAT-605 M1), nothing is bound, so tenant-bound tools refuse with `no_scope`.
  - Test chat and the meta-agent are bound by FEAT-605 v0.2. This module only adds tests that assert it.
- **Depends on**: M3, FEAT-605 v0.2 (W0.1 `RequestScope`, W2.1 `StudioAgentRef` + `build_tool_scope`), storage W2 (`bot._studio_key`)

### Module 6: host-conventions
- **Path**: `toolkit.py` (`read_tools`, `routing_meta["access"]`, auto-confirm for host), `resolver.py` (prefix checks), `tools_catalog.py` (`source`, `access`), `docs/` (one host-toolkit guide page)
- **Responsibility**: G5.
  - The guide states the conventions that are not enforced: Pydantic return models; a row cap with `max_rows` in `config_model` plus `truncated: bool` in the result; no secrets in results.
- **Depends on**: M1

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
or storage P2; without either they skip with that reason. Mutation-check
every new assertion: revert the code, and the test must go red.

**Host fixture**: a tmp package `plugins/tools/` put on `sys.path`, with
`HOST_TOOL_PREFIX="tp_"` and `TOOL_REGISTRY={"tp_probe": ...}`.
`ProbeToolkit` has:
- `tenant_bound=True`;
- one read tool `whoami()` that returns a Pydantic `ProbeResult(tenant, caller, agent)`;
- one write tool;
- one constructor server-managed param (`source="app"`);
- one method server-managed param (`source="tenant"`).

The resolver is reset between tests with `reload()`.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_resolver_sees_declared_host_registry` | M1 | `tp_probe` resolves and appears in `entries()` with `source="host"` |
| `test_resolver_rejects_unprefixed_and_colliding_host_slugs` | M1 | `probe` (no prefix) and a slug equal to a `parrot_tools` key are excluded, one error logged each |
| `test_resolver_walk_fallback_without_registry` | M1 | a `plugins.tools` without `TOOL_REGISTRY` still resolves walked classes (back-compat) |
| `test_require_scope_refusals` | M3 | each `ScopeRefusal` reason from a real `RequestContext`/no context; `no_context` with `bot.session` absent |
| `test_tenant_bound_gate_runs_before_pre_execute` | M3 | `_pre_execute` is never called when the gate refuses |
| `test_scope_error_is_structured_tool_result` | M3 | `status="error"`, `error_code`, `reason` in metadata |
| `test_server_managed_ctor_param_marked_on_both_schema_paths` | M4 | introspection and `config_model` both emit `x-server-managed` |
| `test_server_managed_method_param_hidden_and_llm_value_dropped` | M4 | the args schema lacks `tenant`; an LLM-supplied `tenant="other"` is ignored and the scope value is used |
| `test_scope_source_on_ctor_param_is_typeerror` | M4 | `__init_subclass__` refuses |
| `test_builtin_wiki_infographic_declare_classvar` | M4 | no `_SERVER_MANAGED` / `_KNOWN_APP_DEPS` left; schemas unchanged versus a golden copy |
| `test_host_write_tool_auto_confirming_and_access_meta` | M6 | write → `requires_confirmation`, `access="write"`; read tool `access="read"`; built-in `access is None` |

### Integration Tests
| Test | Description |
|---|---|
| `test_every_studio_path_sees_host_toolkit` | one parametrized test over catalog, schema, generic assign, FEAT-593 PUT/GET, options, `/me` override, live assign, bot build (`apply_tooling_specs`). Each finds `tp_probe`. |
| `test_put_rejects_server_managed_param` | PUT and `/me` with the ctor param give 400; the stored spec never contains it (database backend: neither `ai_agent_tooling.config` nor `secret_refs`) |
| `test_test_chat_join_scope_reaches_tool` | seam-shaped request → Studio test chat → `whoami` returns the **caller's** tenant and id and the agent's owner/visibility. Drive the tool with `tool_manager.execute_tool` inside the handler's `bot.session`, or with a scripted client if one exists. No LLM network. |
| `test_normal_chat_binds_scope` | same join through `chat.py:455` |
| `test_execute_binds_caller_scope_agent_none` | `/tools/tp_whoami_tool/execute` (an `AbstractTool` variant) sees `agent=None`, caller tenant; with no resolver → 403 `tool_scope_unavailable` / `no_scope` |
| `test_no_request_refuses` | calling the tool outside any session (the scheduler shape) → `no_context` |
| `test_concurrent_callers_never_cross` | two concurrent `bot.session`s on one shared agent, different sessions/tenants → each sees only its own scope (mutation: store the scope on the instance → red) |
| `test_tenant_mismatch_refuses` | agent stamped tenant A, caller tenant B → `tenant_mismatch` |

### Test Data / Fixtures
```python
@pytest.fixture
def host_plugins(tmp_path, monkeypatch):
    """Writes plugins/tools/__init__.py (+ probe module) and prepends tmp_path to sys.path."""

@pytest.fixture
def seam_request(app):
    """make_mocked_request(..., app=app); request[SESSION_OBJECT] = real navigator_session shape."""
```

---

## 5. Acceptance Criteria

- [ ] All seven P1 paths resolve through `get_toolkit_resolver()`. No other module calls `discover_from_registry` or `discover_all` to resolve a Studio slug (`grep` shows only the resolver and the `ToolManager` call sites).
- [ ] A host toolkit declared in `plugins.tools.TOOL_REGISTRY` appears in the catalogue, schema, config, override and options paths, and survives bot build (`test_every_studio_path_sees_host_toolkit`).
- [ ] No code path mutates `parrot_tools.TOOL_REGISTRY` or any registry dict.
- [ ] Tools read tenant, caller and agent only through `current_tool_scope()` / `require_tool_scope()`. Nothing is stored on a toolkit instance.
- [ ] A tenant-bound tool with no request, scope or tenant, or with a mismatched tenant, returns `error_code="tool_scope_unavailable"` with the right `reason`. It never returns data.
- [ ] `_SERVER_MANAGED` and `_KNOWN_APP_DEPS` are deleted. The wiki and infographic schemas are byte-identical to the pre-change golden copies.
- [ ] Server-managed params cannot be set via PUT, `/me`, the assign JSON, or LLM args (tests prove each).
- [ ] The catalogue carries `source` and `access`. Host write tools are confirm-first.
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
    config_model: ClassVar[type[BaseModel] | None] = None      # :321
    secret_params: ClassVar[frozenset[str]] = frozenset()      # :323
    default_user_overridable: ClassVar[frozenset[str]] = frozenset()  # :325
    options_params: ClassVar[frozenset[str]] = frozenset()     # :327
    async def _prepare_kwargs(self, tool_name, kwargs) -> dict  # :446
    async def _pre_execute(self, tool_name, /, **kwargs) -> None  # :463
    def config_schema(cls, slug) -> dict      # :704 (calls build_schema_envelope WITHOUT server_managed)
class ToolkitTool(AbstractTool):  # :37 — _execute :142, _generate_args_schema_from_method :95, _pre_execute call :179
# parrot/tools/spec.py:21  class ToolkitSpec(slug, params, user_overridable, secret_refs, vault_owner)
# parrot/auth/exceptions.py:12  class AuthorizationRequired(Exception)  — the precedent for a structured tool refusal
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ToolkitResolver` | `AbstractBot._resolve_spec_class` | delegation | `interfaces/tools.py:177` |
| `ToolkitResolver` | Studio shims | delegation | `toolkits.py:156`, `testing.py:92`, `tooling_store.py:138` |
| `ToolkitResolver` | catalogue | `entries()` | `tools_catalog.py:56` |
| `require_tool_scope` | `ToolkitTool._execute` | call before `_pre_execute` | `toolkit.py:179` |
| scope binding | normal chat | `session(..., studio_scope=)` | `chat.py:455` |
| scope binding | execute | `RequestContext` + `_current_ctx` set/reset | `testing.py:393` |
| scope binding | options | same | `toolkit_config.py:157-158` |
| error metadata | generic tool error path | `metadata` dict | `abstract.py:1201-1206` |

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
- ~~`ToolkitResolver`, `ToolScopeUnavailable`, `ServerParam`, `require_tool_scope`~~: introduced by this spec.

### Edit Sites (Blueprint Anchors)

Verified against `3f0f2f726`.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/tools/resolver.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/tools/scope.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/tools/server_params.py` | CREATE | — | — | — |
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

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Structured refusal: follow `AuthorizationRequired` (`auth/exceptions.py:12`), but convert to a `ToolResult` in the generic path instead of adding a new `ToolManager` status. UIs that match `status == "error"` keep working.
- Per-call state lives only in a ContextVar (the `_A2UI_SURFACE_STATE_VAR` precedent, `abstract.py:59-75`), never on the instance.
- Core never imports ai-parrot-server. The Protocols in `scope.py` are the only coupling to FEAT-605's types.
- Logging goes through `self.logger`. The resolver logs each rejected host entry once, at build time.

### Known Risks / Gotchas
- **ContextVar reach.** Tasks created *inside* `bot.session()` inherit the scope, and so does `asyncio.to_thread`. A task spawned before the session, or a streaming generator consumed after the `async with` exits, does not. Such a tool refuses with `no_context`, which is fail-closed. The chat streaming path must be checked in M5.
- **Import-time side effects.** The resolver imports `plugins.tools` lazily, on first use, never at parrot import. The host package must be importable by then.
- **Stored specs with a now-server-managed key** (for example a legacy row, or an `ai_agent_tooling.config` written before M4): the key is stripped on load, with a warning. It is never applied.
- **Toolkit secrets need DocumentDB.** Secret values and per-user overrides stay in the DocumentDB vault until storage P2 (storage Q5). A host without DocumentDB (FieldSync) can attach secret-free host toolkits only; a secret write answers 503 there. Per-user override secrets require storage P2 or DocumentDB.
- **Walk fallback keys** (`getattr(obj, "name", attr_name)`, `discovery.py:105`) can differ from the registry slugs. The fallback exists only for back-compat and is not subject to the prefix rules.

### External Dependencies
None new.

---

## 8. Dependencies on sibling specs

| Need | Provided by | What this spec assumes | If it differs |
|---|---|---|---|
| `studio_scope` object in `RequestContext.kwargs` | FEAT-605 v0.2 (C16) | `StudioToolScope` satisfies `ToolScopeView`: `.caller` = `RequestScope` (`user_id`, `tenant`, `groups`, `is_superuser`, …), `.agent` = `StudioAgentRef` (`agent_id`, `name`, `owner`, `tenant`, `visibility`) or `None` | FEAT-605 keeps its names; this spec adapts the Protocol attribute names only |
| scope builder usable from `chat.py`, execute, options | FEAT-605 v0.2 W2.1 | `build_tool_scope(scope, agent=None) -> StudioToolScope` in `handlers/studio/access.py` (name frozen) | M5 waits for it |
| test chat + meta-agent bind `studio_scope` | FEAT-605 v0.2 (W3.4 `testing.py:270`, W3.5 `meta_agent.py:110`) | bound there | if FEAT-605 binds only the meta-agent, M5 also binds test chat |
| Studio bot identity and build | storage spec W2 (`StudioAgentBuilder`, `StudioAgentKey`, `get_studio_bot`) | a Studio bot carries `bot._studio_key` (`studio:<tenant\|->:<name>`); its toolkits come from `ai_agent_tooling` rows ordered by `position`, turned into `ToolkitSpec`s and built by `apply_tooling_specs`, so M1/M4 apply unchanged; `get_bot(name)` never returns a tenant row | M5 chat binding degrades to `agent=None` / refusal |
| toolkit secret values, per-user overrides | DocumentDB vault today; storage P2 (Q5) later | unchanged storage; `ai_agent_tooling.secret_refs` holds vault names only | a host without DocumentDB cannot store secrets until storage P2 |
| `has_installed_resolver(app)` | FEAT-605 v0.2 M1 | exists | — |
| storage of agent-level toolkit specs | storage spec (`navigator.ai_agent_tooling`: `kind`, `slug`, `position`, `config`, `secret_refs`, `vault_owner`) | `AgentToolingStore` keeps `schema_for` / `put_toolkit` semantics (`source="studio"` branch); this spec changes only *which class* and *which keys are refused*; unresolvable slugs stay as rows and are reported `unavailable` | resolver and refusal rules are storage-agnostic; no change needed |

Ordering: M1–M4 and M6 have **no sibling dependency in code** and can land
first. M5 lands after FEAT-605 v0.2 W2.1 (builder). Merge order, per file:
M2/M4 edit `tooling_store.py`, `toolkits.py`, `testing.py`, `toolkit_config.py`
and `toolkit_overrides.py`, which storage W2/W3 also edit, so each of those
files merges after the storage task for it and rebases (the package's
per-file rule). Both sides meet at `AgentToolingStore`, and the integration
tests run against whichever store is current.

---

## Cross-spec contract (package)

This section is **identical** in the three package specs: STORAGE =
`agentstudio-db-storage.spec.md`, FEAT-605 = `agentstudio-tenant-visibility.spec.md` (v0.2),
TOOLKITS = `agentstudio-host-toolkits.spec.md`. Changing a row means changing it in all three.
STORAGE waves are W0–W4 and P2; FEAT-605 tasks are W0.1–W4.3; TOOLKITS waves are Wave 1–4.

| # | Item (exact names) | Provided by | Consumed by | Contract |
|---|---|---|---|---|
| X1 | Tables `navigator.ai_agents`, `navigator.ai_agent_assets`, `navigator.ai_agent_tooling`, `navigator.ai_agent_drafts`, `navigator.ai_studio_migrations`; the **existing** `navigator.ai_skills_catalog` extended in place (content column `body`; adds `tenant`, `visibility`, `allowed_groups text[]`) | STORAGE W0 (migrations 0001–0005) | FEAT-605, TOOLKITS (only through STORAGE services / `AgentToolingStore`) | `tenant text NULL`; `visibility` ∈ `private`/`tenant`/`groups`; `allowed_groups text[]`; `UNIQUE(tenant, name)` + partial unique `(name) WHERE tenant IS NULL`; `tenant IS NULL ⇒ visibility = 'private'` (CHECK). No DDL outside the migration files |
| X2 | Tenant-less rows (`tenant IS NULL`) | STORAGE | FEAT-605, TOOLKITS | They form the GLOBAL partition of hosts with **no** resolver. No resolver may return a NULL or empty tenant as valid; a NULL row never satisfies FEAT-605 `in_tenant`; a tenant-bound tool on such an agent refuses `agent_tenant_unset` |
| X3 | `ai_agent_tooling(agent_id, kind, slug, position, config, secret_refs, vault_owner, updated_at)`, PK `(agent_id, kind, slug)` | STORAGE W0 (table), W2/W3 (`StudioToolingService`, `AgentToolingStore` `source="studio"`) | TOOLKITS (M2, M4) | `position` = list order of `ToolkitSpec`/MCP specs; `config` = secret-free spec dump, never contains a TOOLKITS server-managed key; `secret_refs` = `{dotted.path: vault_name}`; `vault_owner` = `ToolkitSpec.vault_owner`. Secret **values** and per-user `/toolkits/{slug}/me` overrides stay in the DocumentDB vault until STORAGE P2 (STORAGE Q5) |
| X4 | `StudioPartition(tenant)`, `StudioPartition.GLOBAL`, `StudioPartition.from_scope(scope)` (duck-typed `.tenant`) | STORAGE W0 | FEAT-605 W2.1 | Storage addresses rows by tenant only; it never sees groups, superuser or visibility policy |
| X5 | `async StudioBaseView._studio_partition()` | STORAGE W1 (returns `GLOBAL`) | FEAT-605 W2.1 (override) | No resolver ⇒ `GLOBAL`. Resolver + tenant ⇒ `StudioPartition.from_scope(await self._scope())`. Resolver + no tenant ⇒ never `GLOBAL`: the handler answers empty / 404 / 422 `tenant_required` before any storage call |
| X6 | Records `StudioAgentRecord`, `StudioDraftRecord`, `StudioSkillRecord` (`owner`, `tenant`, `visibility`, `allowed_groups`, id, `name`); errors `StudioNameConflict`, `StudioVersionConflict`, `StudioStorageUnavailable`; services `StudioAgentService` (`create`, `patch`, `update_visibility`, …), `StudioDraftService` (`save_bundle`, `activate`, `update_visibility`, `python_drafts_allowed`), `StudioSkillCatalogService` (`publish`, `update_visibility`, …); test fake `InMemoryStudioRepositories` (`storage/testing.py`) | STORAGE W0 (records, errors), W1 (repositories, fake), W2 (services) | FEAT-605 (`StudioAccess`, handlers, tests) | Services validate data, never access. The fake enforces the same uniqueness and raises the same signals |
| X7 | Registry key `StudioAgentKey(tenant, name).qualified` = `studio:<tenant\|->:<name>`; `BotManager.get_studio_bot(key, *, new=False, session_id="", request=None)`; `BotManager.studio.reload(key)`; `bot._studio_key`, `bot._studio_version` | STORAGE W2 | FEAT-605 (test/ask, reload, activation), TOOLKITS M5 (identifies a Studio bot) | `get_bot(name)` never resolves a tenant row and never parses a qualified id; only tenant-NULL rows are reachable by bare name. Tenant agents outside Studio (chat, A2A, scheduler) are the P13 follow-up |
| X8 | `BotManager.studio` startup step | STORAGE W2 | FEAT-605 W0.2 (`setup_registry_only` extension point), host | Appended by both `BotManager.setup()` and `BotManager.setup_registry_only(app)`; runs after `resolve_studio_storage`; only when `app["studio_storage"].backend == "database"`; no eager load |
| X9 | `RequestScope(user_id, tenant, groups, is_superuser, may_author, may_administer, studio_enabled)`; `app["scope_resolver"]` (legacy `app["ui_surfaces_scope_resolver"]`); `get_scope_resolver(app)`; `has_installed_resolver(app)` | FEAT-605 W0.1 | STORAGE (duck-typed `.tenant` only), TOOLKITS M5 | "Opted-in host" := `has_installed_resolver(app)` |
| X10 | `setup_studio_routes(app, *, prefix=None, view_wrapper=None)`; `BotManager.setup(..., studio_routes=True)`; `BotManager.setup_registry_only(app)` | FEAT-605 W0.2 | STORAGE (registers `resolve_studio_storage` through it), host | Idempotent per prefix; every startup hook (FEAT-467 `reconcile_skills_catalog`, STORAGE `resolve_studio_storage`, the `BotManager.studio` step) appended at most once per app |
| X11 | `RequestContext.kwargs["studio_scope"]` = `StudioToolScope(caller: RequestScope, agent: StudioAgentRef \| None)`, built only by `build_tool_scope(scope, agent=None)` in `handlers/studio/access.py`; `StudioAgentRef(agent_id, name, owner, tenant, visibility)` | FEAT-605 W2.1 (builder); binds at test/ask (W3.4) and the meta-agent (W3.5) | TOOLKITS (`ToolScopeView` / `CallerView` / `AgentScopeView` Protocols; binds at `chat.py`, execute and options in M5); STORAGE assistant tools (partition = `StudioPartition.from_scope(studio_scope.caller)`) | Nothing is bound without a resolver. For an addressed agent `agent.tenant == caller.tenant` |
| X12 | Routes: `PATCH /agents/{name}` (General fields) | STORAGE W3 (route, `StudioAgentPatch`, version bump) | FEAT-605 W3.1 (policy row) | Name immutable (`name_immutable`); `can_manage` inside the tenant + `may_author`; 404 first |
| X13 | Routes: `GET /me`; `PATCH /agents/{name}/visibility`, `/drafts/{name}/visibility`, `/skills/{id}/visibility` | FEAT-605 (W1.2, W3.1–W3.3, W4.1) | UI, host | Persist through the X6 `update_visibility` service methods |
| X14 | Error codes | STORAGE: `studio_storage_unavailable` (503), `version_conflict`, `name_immutable`, `not_studio_agent`, `asset_too_large`, `agent_assets_quota`, `binary_assets_unsupported`. FEAT-605: `name_taken` (409, raised from `StudioNameConflict`), `declarative_only` (422, also the STORAGE tenant-path Python-draft refusal), `studio_disabled` (404), `tenant_mismatch`, `authoring_denied`, `reserved_config_key`, `tenant_required`, `groups_required`. TOOLKITS: `tool_scope_unavailable` (403 on execute) | all three | One code per condition across the package; no spec defines a synonym |
| X15 | `get_toolkit_resolver()` / `ToolkitResolver`; `server_managed_params`, `ServerParam`; `tenant_bound` | TOOLKITS Wave 1–3 | STORAGE (`StudioAgentBuilder` → `apply_tooling_specs` builds toolkits from `ai_agent_tooling` rows; `StudioToolingService` reuses the refusal of server-managed keys) | Storage-agnostic: the resolver and refusals work on either backend |
| X16 | Merge order | — | all three | FEAT-605 W0.1–W0.3, W1.1–W1.2 and TOOLKITS Wave 1 have no sibling dependency. FEAT-605 W2.1 needs STORAGE W0 + W1. Every task that edits a Studio handler file also edited by STORAGE W2/W3 (`agents.py`, `drafts.py`, `skills_catalog.py`, `files.py`, `testing.py`, `tooling_store.py`, `toolkit_config.py`, `toolkits.py`, `toolkit_overrides.py`, `meta_agent.py`, core `bots/studio/tools.py`) merges **after** the STORAGE task for that file, per file. `studio/_base.py`, `studio/__init__.py` and `manager/manager.py` (STORAGE W1/W2, FEAT-605 W0.2/W1.1) carry small non-overlapping edits: serialise, whichever merges first. TOOLKITS Wave 4 (M5) needs FEAT-605 W2.1 (builder) |

---

## 9. Task Breakdown (waves; no IDs until approval)

- **Wave 1** (parallel; no sibling dependency):
  - resolver (M1) plus its unit tests;
  - scope contract and error (M3) plus unit tests.
- **Wave 2** (parallel; after Wave 1; per file after storage W2/W3, see §8):
  - adopt the resolver on all seven paths (M2), plus `test_every_studio_path_sees_host_toolkit`;
  - host conventions: prefix checks, `read_tools`, auto-confirm, catalogue fields (M6).
- **Wave 3** (per file after storage W2/W3): server-managed params: the ClassVar, both schema paths, refusals, fills, migrating wiki and infographic, and deleting both dicts (M4).
- **Wave 4** (after FEAT-605 v0.2 W2.1 `build_tool_scope`, and W3.4/W3.5 for the asserted bindings):
  - scope binding in chat, execute and options, and asserting the test-chat and meta-agent bindings (M5);
  - the join, concurrency, mismatch and no-request integration tests;
  - the host-toolkit guide page.

---

## 10. Open Questions (for Jesus)

- [ ] **Q1: Host registration mechanism.** Should parrot honour a declarative
  `plugins.tools.TOOL_REGISTRY` (+ `HOST_TOOL_PREFIX`), or offer a
  programmatic `register_host_toolkits(app, {...})` hook?
  *Recommendation: the declarative registry.* It needs no app, so bot build
  and the catalogue work at import time, and it matches `parrot_tools`. No
  runtime mutation either way. — *Owner: Jesus*
- [ ] **Q2: Collision policy.** Can a host slug ever shadow a built-in or
  `parrot_tools` slug?
  *Recommendation: never. Reject it and log the error; the prefix makes
  collisions unlikely anyway.* — *Owner: Jesus*
- [ ] **Q3: Walk fallback lifetime.** Should the resolver keep walking a
  `plugins.tools` that has no `TOOL_REGISTRY`?
  *Recommendation: keep it one minor version, with a deprecation warning,
  then require the registry.* — *Owner: Jesus*
- [ ] **Q4: Toolkit methods on `/tools/{slug}/execute`.** Today only
  `AbstractTool` classes run there.
  *Recommendation: keep it that way in this spec.* FieldSync does not mount
  execute (P6). A `{slug}.{method}` form can be a follow-up. — *Owner: Jesus*
- [ ] **Q5: `studio_scope` shape.** Should `studio_scope` carry both
  `.caller` and `.agent` (this spec's Protocol), or should tools join the
  caller `RequestScope` with a separate `agent_scope` kwarg?
  *Recommendation: one object with both.* That gives one ContextVar read and
  one mismatch check. The final names belong to FEAT-605 v0.2. *Package status*: FEAT-605 v0.2 C16 adopted one object (`StudioToolScope(caller, agent)`, `build_tool_scope`); only Jesus's confirmation remains. — *Owner: Jesus (with the FEAT-605 v0.2 author)*
- [ ] **Q6: Unstamped agents.** Should a tenant-bound tool on an agent whose
  record has `tenant=None` (a storage GLOBAL-partition row) refuse?
  *Recommendation: yes, with `agent_tenant_unset`, always.* The package has
  no adoption path: tenant-NULL rows belong to hosts with no resolver, and
  opted-in hosts never read them (FEAT-605 C15, C24). This supersedes J11
  "adopt on first visibility change". — *Owner: Jesus*
- [ ] **Q7: Default access for built-ins.** Should `parrot_tools` toolkits
  that have no `read_tools` stay `access=None` ("unknown"), or default to
  `"write"`?
  *Recommendation: `None` now,* so no confirmation behaviour changes. Mark
  the built-ins over time. Only host toolkits default to `"write"`. — *Owner: Jesus*
- [ ] **Q8: Conventions that are not enforced.** Should Pydantic return
  types and row caps (`max_rows` + `truncated`) be enforced by the resolver,
  or documented only?
  *Recommendation: document them, and enforce only the prefix and the
  read/write marker.* Return-type enforcement would reject existing
  `str`/`dict` tools. — *Owner: Jesus*
- [ ] **Q9: Scheduler and A2A.** Should a tenant-bound tool refuse when no
  request exists?
  *Recommendation: refuse (`no_context`) in this spec.* A scheduler
  principal carrying a stamped tenant is a separate feature, with the
  scheduler lane. — *Owner: Jesus / Juan*

---

## Design Compliance (FieldSync ARCHITECTURE.md, applied to the upstream ask)
- [x] R1 Library-first: it reuses `discovery.resolve_class` / `discover_from_walk`, `current_context()`, `confirming_tools`, `config_schema`, and the `AuthorizationRequired` pattern. Nothing is re-implemented, and five ad-hoc resolvers become one.
- [x] R2 Endpoints: no new routes. The existing CBVs change behaviour only.
- [x] R3 app.py: N/A (upstream library). The host adds only `plugins/tools/__init__.py`.
- [ ] R4 Complexity: `resolver.py` and `scope.py` each stay well under 500 lines. `flake8` runs per task.
- [x] R5 Layering: handlers bind context, the resolver and scope live in core, and tools stay free of HTTP.
- [x] R6 Test doubles: §4 requires real aiohttp requests with `request[SESSION_OBJECT]`, FEAT-605's real scope types, an end-to-end join test, and mutation checks.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-30 | Juan Ruffato (with Claude) | Initial draft for the Agent Studio host-integration package |
| 0.1.1 | 2026-09-30 | Juan Ruffato (with Claude) | Package reconciliation: FEAT-605 builder/type names, storage runtime key and chat reach, `ai_agent_tooling` columns, secrets depend on DocumentDB or storage P2, per-file merge order, cross-spec contract section |
