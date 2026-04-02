# Brainstorm: Policy-Based Access Control (PBAC) Integration

**Date**: 2026-04-03
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

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
- `ResourceType` enum already defining `TOOL`, `AGENT`, `MCP`, `KB`, `VECTOR`
- `ActionType` enum with `tool:execute`, `tool:list`, `agent:chat`, `agent:configure`, etc.
- `EvalContext` — request/session context builder
- `Environment` — time-aware conditions (business hours, day segments, weekends)
- `YAMLStorage` / `pgStorage` — pluggable policy backends
- `PDP` — full Policy Decision Point with `setup(app)` auto-registration
- `Guardian` — Policy Enforcement Point with handler-level wrappers
- `@requires_permission`, `@groups_protected` — ready-made decorators

Integrating this into ai-parrot would provide:

- **Agent access control**: Restrict which users can interact with specific agents based
  on groups, roles, time-of-day, departments, or custom attributes (real-time evaluation).
- **Tool filtering**: Make unauthorized tools invisible to the agent (not just denied at
  execution) using `PolicyEvaluator.filter_resources()`, including dataset-level restrictions.
- **MCP server access control**: Restrict which external MCP servers a user can consume.
- **Frontend module permissions**: Expose a REST API so frontends can query "can user X
  access module Y?" for UI-level gating (AgentChat, AgentDashboard, CrewBuilder).

**Who is affected**: End users (see only what they're allowed to), developers (configure
policies declaratively), ops (audit and manage access centrally).

## Constraints & Requirements

- Must use navigator-auth's PBAC engine directly — `PolicyEvaluator`, `PDP`, `Guardian`.
- navigator-auth >= 0.19.0 required (bump from current >= 0.18.5).
- Tool filtering must happen BEFORE agent execution — unauthorized tools are invisible.
  Use `PolicyEvaluator.filter_resources(resource_type=ResourceType.TOOL, ...)`.
- Agent-level policies (e.g., business hours) require real-time evaluation per request
  via `PolicyEvaluator.check_access()` (no caching for time-dependent conditions).
- Tool/dataset-level policies can use `PolicyEvaluator`'s built-in LRU cache (300s TTL).
- Session/user info comes from `navigator_session.get_session(request)` — JWT-resolved.
  `EvalContext` is built from request + session with userinfo (username, groups, roles).
- Must ship with default YAML policies (deny-by-default) loaded via `PolicyLoader`.
- Frontend permission API: query endpoint only (no CRUD in v1). navigator-auth's
  `PolicyHandler` provides a `/api/v1/abac/check` endpoint that can be reused.
- Must not break existing `AbstractPermissionResolver` / `ToolManager` contracts.
- `PDP.setup(app)` registers Guardian and middleware automatically — leverage this.

---

## Options Explored

### Option A: PBAC Permission Resolver + PDP Integration (Adapter Pattern)

Create a `PBACPermissionResolver` that implements `AbstractPermissionResolver` and wraps
navigator-auth's `PolicyEvaluator` for tool/dataset/MCP filtering. For agent-level
enforcement, use `@requires_permission` decorator or `Guardian.is_allowed()` in handlers.
Initialize the full `PDP` with `setup(app)` for middleware and REST endpoint registration.

**How it works:**
1. At startup, `PDP` is instantiated with `YAMLStorage` (and optionally `pgStorage`).
   `PolicyEvaluator` is created, policies loaded via `PolicyLoader.load_from_directory()`.
   `PDP.setup(app)` registers Guardian middleware and `/api/v1/abac/check` endpoint.
2. `PBACPermissionResolver` holds a reference to the `PolicyEvaluator` and implements:
   - `can_execute(ctx, tool_name, perms)` → delegates to `evaluator.check_access()`
   - `filter_tools(tools, ctx)` → delegates to `evaluator.filter_resources(ResourceType.TOOL, ...)`
3. Handlers build `EvalContext` from request/session (already available via decorators).
4. Agent access uses `@requires_permission(resource_type=ResourceType.AGENT, ...)` or
   `Guardian.is_allowed(request, resource="agent:{id}", action="agent:chat")`.
5. Tool/dataset/MCP filtering uses `PBACPermissionResolver.filter_tools()` which
   calls `PolicyEvaluator.filter_resources()` — returns `FilteredResources(allowed, denied)`.

**Pros:**
- Builds on existing `AbstractPermissionResolver` contract — no changes to ToolManager or AbstractTool.
- `PolicyEvaluator` already handles caching (LRU, 300s TTL), priority resolution, and
  deny-takes-precedence logic — no need to reimplement.
- `ResourceType.TOOL/AGENT/MCP/KB/VECTOR` already defined — zero mapping effort.
- `PDP.setup(app)` auto-registers Guardian middleware + REST `/api/v1/abac/check` endpoint.
- `@requires_permission` decorator ready for handler-level agent access control.
- `EvalContext` built from `aiohttp.web.Request` + session — matches ai-parrot's patterns.
- `Environment` model auto-computes `is_business_hours`, `day_segment`, `is_weekend`.
- `PolicyEvaluator.invalidate_cache(user_id)` available for per-user cache busting.
- Existing `AllowAllResolver` and `DenyAllResolver` remain available for dev/testing.

**Cons:**
- `PBACPermissionResolver` is a thin adapter — adds an indirection layer between
  ToolManager and PolicyEvaluator. Could be argued to wire PolicyEvaluator directly,
  but the adapter preserves the existing contract.
- Must ensure `EvalContext` is populated with `userinfo["groups"]`, `userinfo["roles"]`,
  `userinfo["username"]` — depends on session middleware running first.
- `PolicyEvaluator` cache uses MD5(user|groups|resource|action) — time-dependent policies
  (business hours) must bypass cache or use short TTL.

**Effort:** Low-Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth >= 0.19.0` | Full PBAC engine: PolicyEvaluator, PDP, Guardian, ResourcePolicy | Bump from >= 0.18.5 |

**Existing Code to Reuse:**
- `navigator_auth.abac.policies.evaluator.PolicyEvaluator` — decision engine with `check_access()`, `filter_resources()`
- `navigator_auth.abac.policies.evaluator.PolicyLoader` — `load_from_directory()`, `load_from_dict()`
- `navigator_auth.abac.policies.resource_policy.ResourcePolicy` — modern PBAC policy model
- `navigator_auth.abac.policies.resources.ResourceType` — `TOOL`, `AGENT`, `MCP`, `KB`, `VECTOR`
- `navigator_auth.abac.policies.resources.ActionType` — `tool:execute`, `agent:chat`, etc.
- `navigator_auth.abac.context.EvalContext` — request/session context builder
- `navigator_auth.abac.policies.environment.Environment` — time conditions (business hours)
- `navigator_auth.abac.pdp.PDP` — `setup(app)` auto-registration
- `navigator_auth.abac.guardian.Guardian` — `is_allowed()`, `authorize()`
- `navigator_auth.abac.decorators.requires_permission` — handler decorator
- `navigator_auth.abac.storages.yaml_storage.YAMLStorage` — YAML policy loading
- `navigator_auth.abac.policyhandler` — REST `/api/v1/abac/check` endpoint
- `parrot/auth/resolver.py` — `AbstractPermissionResolver` interface to implement
- `parrot/auth/permission.py` — `PermissionContext`, `UserSession` (bridge to `EvalContext`)
- `parrot/tools/manager.py` — `ToolManager.set_resolver()`, existing filter pipeline
- `parrot/handlers/agent.py` — session-scoped ToolManager swap in AgentTalk

---

### Option B: Direct PolicyEvaluator Wiring (No Resolver Adapter)

Skip the `AbstractPermissionResolver` adapter entirely. Wire `PolicyEvaluator` directly
into `ToolManager` and handlers. ToolManager gets a `policy_evaluator` attribute and
calls `filter_resources()` directly in its tool-listing methods.

**Pros:**
- No adapter indirection — ToolManager talks to PolicyEvaluator directly.
- Simpler call stack for debugging.
- Full access to `EvaluationResult` details (matched_policy, reason, timing) without lossy translation.

**Cons:**
- Breaks `AbstractPermissionResolver` contract — ToolManager now depends on navigator-auth directly.
- Existing `AllowAllResolver`/`DenyAllResolver` can't be swapped in for testing without mocking PolicyEvaluator.
- ToolManager becomes coupled to a specific auth library — violates the abstraction boundary.
- Every component that does permission checks must import PolicyEvaluator — no single interface.
- Harder to test: mocking PolicyEvaluator requires understanding its full API.

**Effort:** Low

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth >= 0.19.0` | Full PBAC engine | Bump from >= 0.18.5 |

**Existing Code to Reuse:**
- Same navigator-auth imports as Option A
- `parrot/tools/manager.py` — modify directly to use PolicyEvaluator

---

### Option C: PDP-First with Guardian Middleware (Full navigator-auth Stack)

Use navigator-auth's full stack as-is: `PDP` + `Guardian` + `abac_middleware`. Let the
middleware handle ALL access control (agents, tools, MCP, modules) at the HTTP layer.
Tool filtering happens in a post-middleware hook that examines the matched policies and
removes denied tools before the handler runs.

**Pros:**
- Maximum reuse of navigator-auth — minimal ai-parrot code.
- `PDP.setup(app)` does most of the wiring automatically.
- `abac_middleware` intercepts all requests — single enforcement point.
- Built-in audit logging via `AuditLog`.

**Cons:**
- `abac_middleware` is designed for URI-based resource matching (`urn:uri:/path`), not
  for resource-type matching (`tool:jira_*`). Tool filtering at the middleware level
  requires knowing which tools exist before the handler configures them — timing issue.
- Middleware evaluates classic `Policy` objects, not `ResourcePolicy` — the high-performance
  `PolicyEvaluator` with `ResourceType` indexing is bypassed.
- Tool filtering needs to happen AFTER the handler clones the ToolManager but BEFORE
  the agent executes — middleware runs too early for this.
- Agent-level access (real-time) and tool-level access (session-cached) have different
  timing requirements — middleware treats everything the same.
- Over-relies on navigator-auth's HTTP integration patterns, which were designed for
  general web apps, not for the agent/tool lifecycle.

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth >= 0.19.0` | Full stack: PDP, Guardian, middleware | Bump from >= 0.18.5 |

**Existing Code to Reuse:**
- `navigator_auth.abac.pdp.PDP` — `setup(app)` for full auto-registration
- `navigator_auth.abac.guardian.Guardian` — handler enforcement
- `navigator_auth.abac.middleware.abac_middleware` — request interceptor
- `parrot/tools/manager.py` — would need post-middleware hook integration

---

## Recommendation

**Option A** is recommended because it combines the best of both worlds:

1. **Preserves ai-parrot's abstraction boundary**: The `AbstractPermissionResolver` contract
   stays intact. ToolManager doesn't know or care that navigator-auth is behind the resolver.
   `AllowAllResolver`/`DenyAllResolver` remain available for testing and development.

2. **Uses navigator-auth's high-performance engine**: `PolicyEvaluator` with `ResourceType`
   indexing, LRU caching, priority resolution, and `filter_resources()` batch API. No need
   to reimplement any of this — the resolver is a thin adapter.

3. **Leverages navigator-auth's ready-made components**: `PDP.setup(app)` for REST endpoint,
   `@requires_permission` for handler decorators, `Environment` for time conditions,
   `YAMLStorage` for policy loading. These are used directly, not wrapped.

4. **Handles the timing difference correctly**: Agent-level enforcement (real-time) uses
   `@requires_permission` or `Guardian.is_allowed()` in handlers. Tool-level enforcement
   (session-cached) uses `PBACPermissionResolver.filter_tools()` in the ToolManager clone.
   These are separate concerns, handled at appropriate points in the request lifecycle.

**What we're trading off**: One thin adapter class (`PBACPermissionResolver`) adds a small
indirection. This is acceptable because it decouples ai-parrot from navigator-auth at the
ToolManager level — if the PBAC engine changes, only the adapter needs updating.

---

## Feature Description

### User-Facing Behavior

**For end users:**
- Users authenticate normally via JWT. No new auth flow.
- When a user accesses an agent, the system checks policies in real-time via
  `PolicyEvaluator.check_access(resource_type=ResourceType.AGENT, resource_name=agent_id, action="agent:chat")`.
  If denied (e.g., outside business hours, wrong group), they receive a 403 with reason
  from `EvaluationResult.reason` (e.g., "Access DENY by business_hours_access").
- Tools the user cannot access are invisible — `PolicyEvaluator.filter_resources()`
  returns `FilteredResources(allowed=[...], denied=[...])`, and only `allowed` tools
  are registered in the session-scoped ToolManager. The agent never sees denied tools.
- Datasets the user cannot query are invisible — same mechanism via `ResourceType.KB`
  or a custom resource type for datasets.
- MCP server tools follow the same visibility pattern via `ResourceType.MCP`.

**For frontend developers:**
- `POST /api/v1/abac/check` (provided by navigator-auth's `PolicyHandler`) accepts
  `{user, resource, action, groups}` and returns
  `{allowed: bool, effect: "ALLOW"|"DENY", policy: str, reason: str}`.
- Frontend gates UI modules: `resource="concierge:AgentChat"`, `action="view"`.

**For operators/admins:**
- YAML policy files in a configurable directory loaded via `YAMLStorage`.
- Default policies ship with ai-parrot (deny-by-default with sensible allows).
- Policy schema matches navigator-auth's established format (version, defaults, policies).
- `PolicyEvaluator` stats available (evaluations, cache_hits, cache_misses, hit_rate).
- `AuditLog` records all access decisions for compliance.

### Internal Behavior

**Startup:**
1. `YAMLStorage(directory=config.policy_dir)` loads YAML policy files.
2. `PolicyEvaluator(default_effect=PolicyEffect.DENY)` is created.
3. `PolicyLoader.load_from_directory()` parses YAML into `ResourcePolicy` objects.
4. Policies are indexed by `ResourceType` in `PolicyIndex` for O(1) lookup.
5. `PDP(storage=yaml_storage)` is created, `evaluator` attached.
6. `PDP.setup(app)` registers Guardian middleware + `/api/v1/abac/check` endpoint.
7. `PBACPermissionResolver(evaluator=evaluator)` is set as default resolver on `BotManager`.

**Agent access (per-request, real-time — no cache):**
1. Request arrives at `AgentTalk` or `ChatHandler`.
2. `@requires_permission(resource_type=ResourceType.AGENT, action="agent:chat",
   resource_name_param="agent_id")` decorator evaluates policy.
3. `PolicyEvaluator.check_access()` builds `EvalContext` from request, evaluates:
   - Enforcing DENY policies checked first (short-circuit).
   - Subject matching via `SubjectSpec.matches_user()`.
   - Environment conditions via `Environment` (is_business_hours, day_segment).
   - Priority resolution: DENY takes precedence at equal priority.
4. Returns `EvaluationResult(allowed, effect, matched_policy, reason)`.
5. If denied → 403 with reason. If allowed → proceed.

**Tool filtering (per-session, cached via PolicyEvaluator LRU):**
1. When `AgentTalk` prepares the session-scoped ToolManager:
2. Build `EvalContext` from request + session.
3. Collect all tool names from ToolManager.
4. Call `evaluator.filter_resources(ctx, ResourceType.TOOL, tool_names, "tool:execute")`.
5. Returns `FilteredResources(allowed=["tool_a", "tool_c"], denied=["tool_b"])`.
6. Remove denied tools from the cloned ToolManager.
7. Result is cached by PolicyEvaluator's LRU (key: user|groups|resource_type|tool|action).

**Dataset filtering (same mechanism):**
1. DatasetManager entries filtered via `filter_resources(ResourceType.KB, dataset_names, "kb:query")`.
2. Denied datasets removed from the DatasetManager before agent sees them.

**MCP server filtering (per-session, cached):**
1. Before registering MCP server tools into ToolManager:
2. `evaluator.filter_resources(ctx, ResourceType.MCP, server_names, "tool:execute")`.
3. Denied MCP servers' tools are not registered.

**Frontend permission check (per-request):**
1. `POST /api/v1/abac/check` handled by navigator-auth's `PolicyHandler`.
2. Builds `EvalContext`, evaluates via `PolicyEvaluator.check_access()`.
3. Returns JSON with `allowed`, `effect`, `policy`, `reason`.

### Edge Cases & Error Handling

- **No policies loaded**: `PolicyEvaluator` with `default_effect=PolicyEffect.DENY` denies
  everything. For dev/testing, use `AllowAllResolver` instead of PBAC resolver.
- **Malformed YAML policy**: `YAMLStorage.load_policies()` logs error, skips invalid files.
  Server starts with valid policies only.
- **User with no groups/roles**: `SubjectSpec.matches_user()` matches only if policy has
  `groups: ["*"]` (wildcard = any authenticated user).
- **Tool added mid-session (via PATCH)**: `PolicyEvaluator.invalidate_cache(user_id)` clears
  user's cached decisions. New tools evaluated fresh on next request.
- **Business hours boundary**: `Environment` is recomputed per-request (real-time). Agent
  access denied immediately when business hours end — no stale cache.
- **Conflicting policies**: `PolicyEvaluator._evaluate_policies()` resolves:
  enforcing policies short-circuit, then highest priority wins, DENY takes precedence
  at equal priority, default effect if no match.
- **Missing session/userinfo**: `EvalContext.__missing__()` returns `False` for undefined
  keys — policies requiring those attributes won't match, defaulting to DENY.
- **Cache invalidation on policy reload**: `PolicyEvaluator` cache cleared on reload.
  v1 requires restart; hot-reload deferred.

---

## Capabilities

### New Capabilities
- `pbac-permission-resolver`: `PBACPermissionResolver` implementing `AbstractPermissionResolver`,
  wrapping `PolicyEvaluator` with `check_access()` and `filter_resources()`
- `pbac-setup`: Initialization of `PDP`, `PolicyEvaluator`, `YAMLStorage` in app startup,
  `PDP.setup(app)` for middleware and REST endpoint registration
- `pbac-agent-guard`: `@requires_permission` decorator on `AgentTalk`/`ChatHandler` for
  real-time agent access evaluation via `ResourceType.AGENT`
- `pbac-tool-filtering`: Integration of `filter_resources(ResourceType.TOOL, ...)` into
  session-scoped ToolManager cloning in handlers
- `pbac-dataset-filtering`: Integration of `filter_resources()` into DatasetManager for
  dataset visibility control
- `pbac-mcp-filtering`: Integration of `filter_resources(ResourceType.MCP, ...)` into
  MCP server tool registration
- `pbac-default-policies`: Default YAML policy files shipped with ai-parrot

### Modified Capabilities
- `tool-manager`: `PBACPermissionResolver` set as resolver via `set_resolver()`
- `dataset-manager`: Filtered through PBAC before agent receives datasets
- `mcp-tool-registration`: MCP server tools filtered through PBAC before registration
- `agent-talk-handler`: Agent access guard + PBAC-filtered ToolManager integration
- `chat-handler`: Agent access guard decorator

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/auth/resolver.py` | extends | Add `PBACPermissionResolver` wrapping `PolicyEvaluator` |
| `parrot/auth/permission.py` | extends | Add `EvalContext` builder from `PermissionContext` + request |
| `parrot/tools/manager.py` | modifies | Set PBAC resolver as default when policies configured |
| `parrot/tools/dataset_manager/` | modifies | Add PBAC filtering for dataset entries |
| `parrot/handlers/agent.py` | modifies | Add `@requires_permission` for agent access, PBAC tool filtering |
| `parrot/handlers/chat.py` | modifies | Add `@requires_permission` for agent access |
| `parrot/mcp/integration.py` | modifies | Filter MCP tools through PBAC before registration |
| `app.py` | modifies | Init PDP + PolicyEvaluator + YAMLStorage, call `PDP.setup(app)` |
| `pyproject.toml` | modifies | Bump navigator-auth to >= 0.19.0 |
| `policies/` (new dir) | new | Default YAML policy files |

**Breaking changes:** None. Existing `AllowAllResolver` remains the default when no PBAC
policies are configured. The PBAC resolver activates only when policy files are present.

---

## Parallelism Assessment

**Internal parallelism**: High. The feature decomposes into independent components:
- PBAC setup + resolver (standalone foundation)
- Agent access guard (depends on setup only)
- Tool filtering integration (depends on resolver)
- Dataset filtering integration (depends on resolver)
- MCP filtering integration (depends on resolver)
- Default YAML policies (independent, can be written in parallel)

**Cross-feature independence**: No conflicts with in-flight specs. The auth layer is not
being modified by other features.

**Recommended isolation**: `per-spec` — despite high decomposability, the components share
the resolver and touch overlapping files (handlers, app.py). Sequential execution in one
worktree avoids merge conflicts.

**Rationale**: The setup/resolver task must complete before any filtering task. Filtering
tasks modify different files but share the resolver import. Sequential execution within
one worktree is simpler and only slightly slower than parallel.

---

## Open Questions

- [ ] Should `PolicyEvaluator` cache be disabled for time-dependent policies, or should we
      use a short TTL (e.g., 30s)? navigator-auth caches by user|groups|resource|action,
      not by time — business hours changes won't invalidate cache automatically. — *Owner: Jesus Lara*
- [ ] Resource naming for datasets: use `ResourceType.KB` (already defined) or add a new
      `ResourceType.DATASET`? KB semantically covers knowledge bases, not arbitrary datasets. — *Owner: Jesus Lara*
- [ ] How are "programs" from the user session mapped to PBAC subjects? `SubjectSpec` has
      `groups`, `users`, `roles` — programs would need to be mapped to one of these or
      added as a condition attribute. — *Owner: Jesus Lara*
- [ ] Should `PDP.setup(app)` register `abac_middleware` for all routes, or should we
      selectively apply it only to agent/tool endpoints? — *Owner: Jesus Lara*
- [ ] Hot-reload for policies: deferred to v2, or worth adding `YAMLStorage.reload()` +
      `PolicyEvaluator.invalidate_cache()` on a file watcher signal? — *Owner: Jesus Lara*
