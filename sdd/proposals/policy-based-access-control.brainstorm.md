# Brainstorm: Policy-Based Access Control (PBAC) Integration

**Date**: 2026-04-03
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: D

---

## Problem Statement

ai-parrot currently has a basic RBAC permission system (roles, groups, users) baked into
`AbstractBot._permissions` and a two-layer tool permission architecture
(`ToolManager.filter_tools()` + `AbstractTool.execute()` check via `AbstractPermissionResolver`).
However, it lacks policy-driven, attribute-based access control that can express conditions
like business hours, department membership, program adherence, or resource-level granularity.

navigator-auth's `abac` module provides a production-ready PBAC engine with:
- `PolicyEvaluator` — high-performance decision engine with LRU caching and priority resolution
- `ResourcePolicy` — modern PBAC policy model with `SubjectSpec`, `ResourcePattern`, conditions
- `ResourceType` enum defining `TOOL`, `AGENT`, `MCP`, `KB`, `VECTOR` (+ `DATASET` to be added)
- `ActionType` enum with `tool:execute`, `tool:list`, `agent:chat`, `agent:configure`, etc.
- `EvalContext` — request/session context builder
- `Environment` — time-aware conditions (business hours, day segments, weekends)
- `YAMLStorage` / `pgStorage` — pluggable policy backends
- `PDP` — full Policy Decision Point with `setup(app)` auto-registration
- `Guardian` — Policy Enforcement Point with `authorize()`, `is_allowed()`, `filter_files()`,
  and handler-level wrappers (to be extended with `filter_tools()`)
- `@requires_permission`, `@groups_protected` — ready-made decorators
- Classic `Policy` supports both URI (`urn:uri:/epson.*$`) and resource-type (`mcp:*`) matching

**Note**: navigator-auth codebase is under our control — we can add `ResourceType.DATASET`,
`Guardian.filter_tools()`, short-TTL cache support, and program-based conditions as needed.

Integrating this into ai-parrot would provide:

- **Agent access control**: Restrict which users can interact with specific agents based
  on groups, roles, time-of-day, departments, programs, or custom attributes (real-time).
- **Tool filtering**: Make unauthorized tools invisible to the agent (not just denied at
  execution) using `Guardian.filter_tools()` at the handler level.
- **MCP server access control**: Restrict which external MCP servers a user can consume.
- **Frontend module permissions**: Expose a REST API so frontends can query "can user X
  access module Y?" for UI-level gating (AgentChat, AgentDashboard, CrewBuilder).

**Who is affected**: End users (see only what they're allowed to), developers (configure
policies declaratively), ops (audit and manage access centrally).

## Constraints & Requirements

- Must use navigator-auth's PBAC engine directly — `PolicyEvaluator`, `PDP`, `Guardian`.
- navigator-auth >= 0.19.0 required (bump from current >= 0.18.5).
- Tool filtering must happen at the **handler level** when ToolManager instance is created —
  NEVER at middleware level. Use `Guardian.filter_tools()` (new method, similar to `filter_files()`).
- Agent-level policies (e.g., business hours) require real-time evaluation per request
  via `Guardian.is_allowed()` or `@requires_permission` decorator.
- Tool/dataset-level policies can use `PolicyEvaluator`'s built-in LRU cache with short TTL
  for time-dependent policies.
- Session/user info comes from `navigator_session.get_session(request)` — JWT-resolved.
  `EvalContext` is built from request + session with userinfo (username, groups, roles).
- Must ship with default YAML policies (deny-by-default) loaded via `PolicyLoader`.
- Frontend permission API: `POST /api/v1/abac/check` provided by `PDP.setup(app)` — no CRUD in v1.
- Must not break existing `AbstractPermissionResolver` / `ToolManager` contracts.
- `PDP.setup(app)` registers Guardian, middleware, and REST endpoints automatically.
- Programs (tenants/organizations) mapped as condition attributes in policies.

---

## Options Explored

### Option A: PBAC Permission Resolver Only (Adapter Pattern)

Create a `PBACPermissionResolver` that implements `AbstractPermissionResolver` and wraps
navigator-auth's `PolicyEvaluator` for tool/dataset/MCP filtering. For agent-level
enforcement, use `@requires_permission` decorator in handlers. Initialize `PDP` with
`setup(app)` for REST endpoint registration.

**Pros:**
- Builds on existing `AbstractPermissionResolver` contract — no changes to ToolManager.
- `AllowAllResolver`/`DenyAllResolver` remain swappable for testing.
- Clean abstraction boundary between ai-parrot and navigator-auth.

**Cons:**
- Thin adapter adds indirection — `PBACPermissionResolver.filter_tools()` just calls
  `PolicyEvaluator.filter_resources()` and translates the result.
- Doesn't leverage `Guardian` at all — misses the PEP pattern (session extraction,
  audit logging, file/object filtering) that navigator-auth already provides.
- Handler code must manually build `EvalContext` and call the resolver, duplicating
  what `Guardian` already does.
- No reuse of `Guardian.filter_files()` pattern for tool filtering.

**Effort:** Low-Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth >= 0.19.0` | PolicyEvaluator, PDP, ResourcePolicy | Bump from >= 0.18.5 |

**Existing Code to Reuse:**
- `navigator_auth.abac.policies.evaluator.PolicyEvaluator` — `check_access()`, `filter_resources()`
- `parrot/auth/resolver.py` — `AbstractPermissionResolver` interface

---

### Option B: Direct PolicyEvaluator Wiring (No Abstraction)

Skip `AbstractPermissionResolver` entirely. Wire `PolicyEvaluator` directly into
`ToolManager` and handlers.

**Pros:**
- No adapter indirection — direct access to `EvaluationResult` details.
- Simpler call stack for debugging.

**Cons:**
- Breaks `AbstractPermissionResolver` contract — ToolManager coupled to navigator-auth.
- `AllowAllResolver`/`DenyAllResolver` can't be swapped in for testing.
- Every component imports PolicyEvaluator — no single interface.

**Effort:** Low

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth >= 0.19.0` | Full PBAC engine | Bump from >= 0.18.5 |

**Existing Code to Reuse:**
- Same navigator-auth imports as Option A
- `parrot/tools/manager.py` — modify directly

---

### Option C: PDP-First with Guardian Middleware Only (Full HTTP Stack)

Use navigator-auth's full HTTP stack: `PDP` + `Guardian` + `abac_middleware`. Let the
middleware handle ALL access control at the HTTP layer, including tool filtering.

**Pros:**
- Maximum reuse of navigator-auth — minimal ai-parrot code.
- `PDP.setup(app)` does most of the wiring automatically.
- Single enforcement point at middleware level.

**Cons:**
- Tool filtering at middleware level is wrong timing — ToolManager instance is created
  at the handler level, not at middleware. Middleware runs too early.
- Middleware treats all resource types the same, but agent access (real-time) and
  tool access (session-cached) have different timing requirements.
- Forces all enforcement through HTTP middleware — doesn't work for tool filtering
  which happens inside handler logic after ToolManager cloning.

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth >= 0.19.0` | Full stack: PDP, Guardian, middleware | Bump from >= 0.18.5 |

**Existing Code to Reuse:**
- `navigator_auth.abac.pdp.PDP` — `setup(app)` for auto-registration
- `navigator_auth.abac.guardian.Guardian` — handler enforcement
- `navigator_auth.abac.middleware.abac_middleware` — request interceptor

---

### Option D: Hybrid — PDP + Guardian for Handlers, Guardian.filter_tools() for Resources

**Recommended approach.** Combine the best of Options A and C:

- **PDP + Guardian + decorators** for handler-level enforcement (agent access, route
  protection, middleware for general HTTP policies).
- **Guardian.filter_tools()** (new method, following `filter_files()` pattern) for
  tool/dataset/MCP filtering at the handler level when ToolManager is instantiated.
- **PBACPermissionResolver** as a thin bridge so ToolManager's existing `set_resolver()`
  contract still works — delegates to `Guardian` for actual decisions.

**How it works:**

1. **Startup**: `PDP` instantiated with `YAMLStorage` + optional `pgStorage`.
   `PolicyEvaluator` created with policies loaded via `PolicyLoader.load_from_directory()`.
   `PDP.setup(app)` registers Guardian middleware, `/api/v1/abac/check`, and routes.

2. **Agent access (real-time)**: Handlers use `@requires_permission(resource_type=ResourceType.AGENT,
   action="agent:chat", resource_name_param="agent_id")` or call
   `guardian.is_allowed(request, resource="agent:{id}", action="agent:chat")`.
   Guardian extracts session, builds `EvalContext`, evaluates via `PolicyEvaluator`.

3. **Tool filtering (handler-level)**: When `AgentTalk` creates/clones the session-scoped
   ToolManager, it calls:
   ```python
   guardian = request.app['security']
   allowed_tools = await guardian.filter_tools(
       tools=tool_manager.tool_names,
       request=request,
       action="tool:execute"
   )
   ```
   `Guardian.filter_tools()` follows the same pattern as `Guardian.filter_files()`:
   builds `EvalContext`, calls `PolicyEvaluator.filter_resources(ResourceType.TOOL, ...)`,
   returns only allowed tool names. Handler removes denied tools from the cloned ToolManager.

4. **Dataset filtering (handler-level)**: Same pattern via
   `guardian.filter_datasets(datasets, request)` using `ResourceType.DATASET` (new).

5. **MCP filtering (handler-level)**: Same pattern via
   `guardian.filter_resources(mcp_servers, request, ResourceType.MCP)`.

6. **Frontend permissions**: `POST /api/v1/abac/check` handled by navigator-auth's
   `PolicyHandler` (auto-registered by `PDP.setup(app)`).

7. **ToolManager bridge**: `PBACPermissionResolver` wraps `Guardian` so existing
   `ToolManager.set_resolver()` / `can_execute()` contract works for Layer 2 safety net.

**Pros:**
- Uses Guardian as the single PEP — session extraction, audit logging, and evaluation
  all handled by navigator-auth. No duplicated logic in ai-parrot handlers.
- `Guardian.filter_tools()` follows established `filter_files()` pattern — consistent API,
  easy to implement in navigator-auth since we control the codebase.
- `@requires_permission` and `@groups_protected` decorators used directly on handlers —
  no custom decorator needed in ai-parrot.
- `PDP.setup(app)` handles middleware, routes, and REST endpoint registration automatically.
- Tool filtering happens at the correct time — handler level, after ToolManager cloning,
  before agent execution. NEVER at middleware level.
- `PBACPermissionResolver` preserves ToolManager's `AbstractPermissionResolver` contract
  as Layer 2 safety net, but primary filtering is via Guardian.
- `PolicyEvaluator` handles caching (short TTL for time-dependent), priority resolution,
  enforcing short-circuit, and deny-takes-precedence — zero reimplementation.
- Programs mapped as condition attributes in policies — `SubjectSpec` extended or
  conditions used for program/tenant matching.
- `AuditLog` records all decisions for compliance — comes free with Guardian.

**Cons:**
- Requires changes to navigator-auth: add `Guardian.filter_tools()`, add
  `ResourceType.DATASET`, add short-TTL cache support, add programs as condition attribute.
  Acceptable since we control the codebase.
- Two permission paths: Guardian (primary, handler-level) and PBACPermissionResolver
  (Layer 2 safety net in AbstractTool.execute()). Must ensure they use the same
  PolicyEvaluator instance to avoid inconsistencies.

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth >= 0.19.0` | Full PBAC engine + Guardian extensions | Bump from >= 0.18.5; add filter_tools(), ResourceType.DATASET |

**Existing Code to Reuse (navigator-auth):**
- `navigator_auth.abac.pdp.PDP` — `setup(app)` auto-registration of Guardian + middleware + routes
- `navigator_auth.abac.guardian.Guardian` — `is_allowed()`, `authorize()`, `filter_files()` (pattern for `filter_tools()`)
- `navigator_auth.abac.decorators.requires_permission` — handler-level agent access guard
- `navigator_auth.abac.decorators.groups_protected` — group-based handler protection
- `navigator_auth.abac.policies.evaluator.PolicyEvaluator` — `check_access()`, `filter_resources()`, LRU cache
- `navigator_auth.abac.policies.evaluator.PolicyLoader` — `load_from_directory()`, `load_from_dict()`
- `navigator_auth.abac.policies.resource_policy.ResourcePolicy` — modern PBAC policy model
- `navigator_auth.abac.policies.resources.ResourceType` — `TOOL`, `AGENT`, `MCP`, `KB`, `VECTOR` (+ `DATASET`)
- `navigator_auth.abac.policies.resources.ActionType` — `tool:execute`, `agent:chat`, etc.
- `navigator_auth.abac.context.EvalContext` — request/session context builder
- `navigator_auth.abac.policies.environment.Environment` — time conditions (business hours)
- `navigator_auth.abac.storages.yaml_storage.YAMLStorage` — YAML policy loading
- `navigator_auth.abac.policyhandler` — REST `/api/v1/abac/check` endpoint
- `navigator_auth.abac.audit.AuditLog` — access decision logging

**Existing Code to Reuse (ai-parrot):**
- `parrot/auth/resolver.py` — `AbstractPermissionResolver` (implement `PBACPermissionResolver`)
- `parrot/auth/permission.py` — `PermissionContext`, `UserSession` (bridge to `EvalContext`)
- `parrot/tools/manager.py` — `ToolManager.set_resolver()`, existing filter pipeline
- `parrot/handlers/agent.py` — session-scoped ToolManager swap in `AgentTalk`
- `parrot/handlers/chat.py` — `ChatHandler` with session access

---

## Recommendation

**Option D (Hybrid)** is recommended because it uses navigator-auth's components at
their intended abstraction levels:

1. **Guardian as the single PEP**: All policy enforcement flows through `Guardian`, which
   handles session extraction, `EvalContext` building, `PolicyEvaluator` delegation, and
   audit logging. No duplicated logic in ai-parrot.

2. **Right enforcement at right timing**: Agent access uses `@requires_permission` decorators
   (real-time, per-request). Tool/dataset/MCP filtering uses `Guardian.filter_tools()` at
   handler level (after ToolManager cloning, before agent execution). Middleware handles
   general HTTP route policies. Each enforcement point operates at the correct lifecycle stage.

3. **`filter_tools()` follows established pattern**: `Guardian.filter_files()` already exists
   and works. Adding `filter_tools()` with the same session/context/evaluate pattern is
   minimal effort in navigator-auth and gives ai-parrot a clean, consistent API:
   ```python
   guardian = request.app['security']
   allowed = await guardian.filter_tools(tools=tool_names, request=request)
   ```

4. **Preserves existing contracts**: `PBACPermissionResolver` keeps `AbstractPermissionResolver`
   working as a Layer 2 safety net. ToolManager doesn't change. `AllowAllResolver` still
   works for dev/testing.

5. **navigator-auth changes are additive**: `Guardian.filter_tools()`, `ResourceType.DATASET`,
   programs as conditions, short-TTL cache — all are backward-compatible additions.

**What we're trading off**: Two permission paths (Guardian primary + PBACPermissionResolver
safety net) could cause confusion. Mitigated by: both use the same `PolicyEvaluator`
instance, and the resolver is documented as a safety net, not the primary enforcement path.

---

## Feature Description

### User-Facing Behavior

**For end users:**
- Users authenticate normally via JWT. No new auth flow.
- When a user accesses an agent, the system checks policies in real-time via
  `Guardian.is_allowed()` or `@requires_permission`. If denied (e.g., outside business
  hours, wrong group/program), they receive a 403 with reason from
  `EvaluationResult.reason` (e.g., "Access DENY by business_hours_access").
- Tools the user cannot access are invisible — `Guardian.filter_tools()` returns only
  allowed tool names, and the handler removes denied tools from the cloned ToolManager.
  The agent never sees denied tools.
- Datasets the user cannot query are invisible — `Guardian.filter_datasets()` uses
  `ResourceType.DATASET` to filter entries before the agent receives them.
- MCP server tools follow the same visibility pattern via `ResourceType.MCP`.

**For frontend developers:**
- `POST /api/v1/abac/check` (registered by `PDP.setup(app)`) accepts
  `{user, resource, action, groups}` and returns
  `{allowed: bool, effect: "ALLOW"|"DENY", policy: str, reason: str}`.
- Frontend gates UI modules: `resource="concierge:AgentChat"`, `action="view"`.

**For operators/admins:**
- YAML policy files in a configurable directory loaded via `YAMLStorage`.
- Default policies ship with ai-parrot (deny-by-default with sensible allows).
- Policy schema matches navigator-auth's established format (version, defaults, policies).
- Policies support resource-type matching (`tool:*`, `mcp:*`, `agent:finance_bot`) and
  URI matching (`urn:uri:/api/agents.*`).
- Programs/tenants supported as condition attributes in policies.
- `PolicyEvaluator` stats available (evaluations, cache_hits, cache_misses, hit_rate).
- `AuditLog` records all access decisions for compliance.

### Internal Behavior

**Startup:**
1. `YAMLStorage(directory=config.policy_dir)` loads YAML policy files.
2. `PolicyEvaluator(default_effect=PolicyEffect.DENY, cache_ttl_seconds=30)` created
   with short TTL for time-dependent policies.
3. `PolicyLoader.load_from_directory()` parses YAML into `ResourcePolicy` objects.
4. Policies indexed by `ResourceType` in `PolicyIndex` for O(1) lookup.
5. `PDP(storage=yaml_storage)` created, `evaluator` attached.
6. `PDP.setup(app)` registers Guardian as `app['security']`, middleware, and
   `/api/v1/abac/check` endpoint.
7. `PBACPermissionResolver(guardian=guardian)` set as default resolver on `BotManager`
   (Layer 2 safety net).

**Agent access (per-request, real-time):**
1. Request arrives at `AgentTalk` or `ChatHandler`.
2. `@requires_permission(resource_type=ResourceType.AGENT, action="agent:chat",
   resource_name_param="agent_id")` decorator fires.
3. Guardian extracts session, builds `EvalContext` (with username, groups, roles, programs).
4. `PolicyEvaluator.check_access()` evaluates:
   - Enforcing DENY policies checked first (short-circuit).
   - Subject matching via `SubjectSpec.matches_user()`.
   - Environment conditions via `Environment` (is_business_hours, day_segment).
   - Condition attributes (programs, departments, custom).
   - Priority resolution: DENY takes precedence at equal priority.
5. Returns `EvaluationResult(allowed, effect, matched_policy, reason)`.
6. If denied -> 403 with reason. If allowed -> proceed.

**Tool filtering (handler-level, after ToolManager cloning):**
1. In `AgentTalk`, after creating/cloning the session-scoped ToolManager:
   ```python
   guardian = self.request.app['security']
   allowed_tools = await guardian.filter_tools(
       tools=tool_manager.tool_names,
       request=self.request,
       action="tool:execute"
   )
   tool_manager.remove_tools(excluded=denied_tools)
   ```
2. `Guardian.filter_tools()` builds `EvalContext`, calls
   `PolicyEvaluator.filter_resources(ctx, ResourceType.TOOL, tool_names, action)`.
3. Returns `FilteredResources(allowed, denied, policies_applied)`.
4. Denied tools removed from cloned ToolManager — agent never sees them.
5. Cached by PolicyEvaluator LRU (key: user|groups|TOOL|tool_name|action, TTL: 30s).

**Dataset filtering (handler-level, same pattern):**
1. `guardian.filter_datasets(datasets=dataset_names, request=request)`.
2. Uses `ResourceType.DATASET` (new) for policy matching.
3. Denied datasets removed before agent receives DatasetManager.

**MCP server filtering (handler-level, same pattern):**
1. Before registering MCP server tools into ToolManager:
   ```python
   allowed_mcp = await guardian.filter_resources(
       resources=mcp_server_names, request=request,
       resource_type=ResourceType.MCP, action="tool:execute"
   )
   ```
2. Denied MCP servers' tools are not registered.

**Frontend permission check (per-request):**
1. `POST /api/v1/abac/check` handled by navigator-auth's `PolicyHandler`.
2. Builds `EvalContext`, evaluates via `PolicyEvaluator.check_access()`.
3. Returns JSON with `allowed`, `effect`, `policy`, `reason`.

### Edge Cases & Error Handling

- **No policies loaded**: `PolicyEvaluator` with `default_effect=PolicyEffect.DENY` denies
  everything. For dev/testing, use `AllowAllResolver` as resolver instead.
- **Malformed YAML policy**: `YAMLStorage.load_policies()` logs error, skips invalid files.
  Server starts with valid policies only.
- **User with no groups/roles**: `SubjectSpec.matches_user()` matches only if policy has
  `groups: ["*"]` (wildcard = any authenticated user).
- **Tool added mid-session (via PATCH)**: `PolicyEvaluator.invalidate_cache(user_id)` clears
  user's cached decisions. New tools evaluated fresh on next request.
- **Business hours boundary**: Short TTL cache (30s) ensures time-dependent policies refresh
  quickly. Agent access denied within 30s of business hours ending.
- **Conflicting policies**: `PolicyEvaluator._evaluate_policies()` resolves: enforcing
  policies short-circuit, then highest priority wins, DENY takes precedence at equal
  priority, default effect if no match.
- **Missing session/userinfo**: `EvalContext.__missing__()` returns `False` for undefined
  keys — policies requiring those attributes won't match, defaulting to DENY.
- **Programs/tenants not in session**: Policies with program conditions won't match,
  falling through to default DENY.
- **Guardian not initialized**: If `PDP.setup(app)` wasn't called, `request.app['security']`
  raises KeyError — caught and logged, falls back to deny-all.

---

## Capabilities

### New Capabilities
- `pbac-setup`: Initialization of `PDP` + `PolicyEvaluator` + `YAMLStorage` in app startup,
  `PDP.setup(app)` for Guardian, middleware, and REST endpoint registration
- `pbac-agent-guard`: `@requires_permission` / `@groups_protected` decorators on
  `AgentTalk`/`ChatHandler` for real-time agent access evaluation
- `pbac-tool-filtering`: `Guardian.filter_tools()` integration in handlers at ToolManager
  cloning time — tools filtered before agent sees them
- `pbac-dataset-filtering`: `Guardian.filter_datasets()` integration for dataset visibility
  control using `ResourceType.DATASET`
- `pbac-mcp-filtering`: `Guardian.filter_resources(ResourceType.MCP)` integration for
  MCP server access control at handler level
- `pbac-permission-resolver`: `PBACPermissionResolver` implementing `AbstractPermissionResolver`
  as Layer 2 safety net, delegating to Guardian
- `pbac-default-policies`: Default YAML policy files shipped with ai-parrot

### Modified Capabilities (ai-parrot)
- `tool-manager`: `PBACPermissionResolver` set as resolver via `set_resolver()` (safety net)
- `dataset-manager`: Filtered through Guardian before agent receives datasets
- `mcp-tool-registration`: MCP server tools filtered through Guardian before registration
- `agent-talk-handler`: Agent access guard + Guardian-filtered ToolManager integration
- `chat-handler`: Agent access guard decorator

### New Capabilities (navigator-auth — upstream changes)
- `guardian-filter-tools`: `Guardian.filter_tools()` method following `filter_files()` pattern
- `resource-type-dataset`: `ResourceType.DATASET` enum value for dataset policies
- `program-conditions`: Programs/tenants as condition attributes in policy evaluation
- `short-ttl-cache`: Configurable short TTL in `PolicyEvaluator` for time-dependent policies

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `navigator-auth: Guardian` | extends | Add `filter_tools()`, `filter_datasets()` methods |
| `navigator-auth: ResourceType` | extends | Add `DATASET` enum value |
| `navigator-auth: PolicyEvaluator` | modifies | Support short TTL cache configuration |
| `navigator-auth: SubjectSpec/conditions` | extends | Add programs/tenants as condition attribute |
| `parrot/auth/resolver.py` | extends | Add `PBACPermissionResolver` wrapping Guardian |
| `parrot/tools/manager.py` | modifies | Set PBAC resolver as default when policies configured |
| `parrot/tools/dataset_manager/` | modifies | Add Guardian filtering for dataset entries |
| `parrot/handlers/agent.py` | modifies | Add `@requires_permission`, Guardian tool filtering |
| `parrot/handlers/chat.py` | modifies | Add `@requires_permission` for agent access |
| `parrot/mcp/integration.py` | modifies | Filter MCP tools through Guardian before registration |
| `app.py` | modifies | Init PDP + PolicyEvaluator + YAMLStorage, call `PDP.setup(app)` |
| `pyproject.toml` | modifies | Bump navigator-auth to >= 0.19.0 |
| `policies/` (new dir) | new | Default YAML policy files |

**Breaking changes:** None. Existing `AllowAllResolver` remains the default when no PBAC
policies are configured. The PBAC resolver activates only when policy files are present.
navigator-auth changes are all additive.

---

## Parallelism Assessment

**Internal parallelism**: Medium. Two work streams:
- **Stream 1 (navigator-auth)**: Add `Guardian.filter_tools()`, `ResourceType.DATASET`,
  programs as conditions, short-TTL cache. Must complete before ai-parrot integration.
- **Stream 2 (ai-parrot)**: PBAC setup in app.py, agent guards, tool/dataset/MCP filtering
  in handlers, PBACPermissionResolver, default policies. Sequential within stream.

**Cross-feature independence**: No conflicts with in-flight specs. Auth layer not modified
by other features. navigator-auth changes are additive, no risk to other consumers.

**Recommended isolation**: `per-spec` — navigator-auth changes should be done first (or
in a separate repo PR), then ai-parrot integration follows sequentially. Within ai-parrot,
tasks share handlers and app.py, making parallel worktrees risky.

**Rationale**: The dependency on navigator-auth changes is the critical path. Once
`Guardian.filter_tools()` and `ResourceType.DATASET` exist, ai-parrot integration is
straightforward sequential work.

---

## Open Questions

- [x] ~~PolicyEvaluator cache for time-dependent policies~~ — **Resolved**: Use short TTL
      (30s) for time-dependent policies. PolicyEvaluator cache key doesn't include time,
      so short TTL ensures business hours changes take effect within 30 seconds.
- [x] ~~Resource naming for datasets~~ — **Resolved**: Add `ResourceType.DATASET` to
      navigator-auth. KB covers knowledge bases, not arbitrary datasets/dataframes/queries.
- [x] ~~Programs mapping to PBAC subjects~~ — **Resolved**: Programs (alias for tenants/
      organizations) added as condition attributes in policies, not as SubjectSpec fields.
- [x] ~~PDP.setup(app) scope~~ — **Resolved**: `PDP.setup(app)` registers routes for all
      endpoints as designed. Agent access uses decorators on handlers. Tool filtering
      happens at handler level via Guardian, NOT at middleware level.
- [x] ~~Hot-reload for policies~~ — **Resolved**: Deferred to v2.
- [x] Exact method signature for `Guardian.filter_tools()` — should it accept a
      `resource_type` parameter to be generic (`filter_resources()`), or be tool-specific
      like `filter_files()`? — *Owner: Jesus Lara*: be generic as "filter_resources" receiving any kind of resource_type to be filtered (even filter_files can be superseeded by filter_resources)
- [x] Should `PBACPermissionResolver` (Layer 2 safety net) log when it denies a tool that
      Guardian already filtered out, or silently allow (since Guardian already handled it)?
      — *Owner: Jesus Lara*: log when it denies a tool
