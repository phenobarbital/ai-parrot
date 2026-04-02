# Brainstorm: Policy-Based Access Control (PBAC) Integration

**Date**: 2026-04-03
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

ai-parrot currently has a basic RBAC permission system (roles, groups, users) baked into
`AbstractBot._permissions` and a two-layer tool permission architecture
(`ToolManager.filter_tools()` + `AbstractTool.execute()` check). However, it lacks
policy-driven, attribute-based access control that can express conditions like business
hours, department membership, program adherence, or resource-level granularity.

navigator-auth 0.19.0 ships a full PBAC/ABAC engine with YAML-based policy definitions.
Integrating it into ai-parrot would provide:

- **Agent access control**: Restrict which users can interact with specific agents based
  on groups, roles, time-of-day, departments, or custom attributes.
- **Tool filtering**: Make unauthorized tools invisible to the agent (not just denied at
  execution) based on policies, including dataset-level restrictions.
- **MCP server access control**: Restrict which external MCP servers a user can consume.
- **Frontend module permissions**: Expose a REST API so frontends can query "can user X
  access module Y?" for UI-level gating (AgentChat, AgentDashboard, CrewBuilder).

**Who is affected**: End users (see only what they're allowed to), developers (configure
policies declaratively), ops (audit and manage access centrally).

## Constraints & Requirements

- Must use navigator-auth's PBAC engine directly (no external PDP service).
- navigator-auth >= 0.19.0 required (bump from current >= 0.18.5).
- Tool filtering must happen BEFORE agent execution — unauthorized tools are invisible.
- Agent-level policies (e.g., business hours) require real-time evaluation per request.
- Tool/dataset-level policies can be cached per session lifetime.
- Session/user info comes from `navigator_session.get_session(request)` — JWT-resolved.
- Must ship with default YAML policies (deny-by-default pattern).
- Frontend permission API is a query endpoint only (no CRUD for policies in v1).
- Must not break existing `AbstractPermissionResolver` / `ToolManager` contracts.

---

## Options Explored

### Option A: PBAC Permission Resolver (Adapter Pattern)

Create a `PBACPermissionResolver` that implements the existing `AbstractPermissionResolver`
interface and delegates all decisions to navigator-auth's policy engine. This slots into the
existing two-layer permission architecture with minimal structural changes.

The resolver loads YAML policies at startup, evaluates them using navigator-auth's engine,
and translates results into the existing `can_execute()` / `filter_tools()` contract.
A thin `PolicyContext` adapter maps `PermissionContext` + request attributes to the policy
engine's expected input format.

For agent-level enforcement, a lightweight aiohttp middleware or handler decorator evaluates
agent access policies before the handler body runs. For frontend module queries, a simple
REST endpoint wraps the same policy engine.

**Pros:**
- Builds on existing `AbstractPermissionResolver` contract — no changes to ToolManager or AbstractTool.
- Minimal new abstractions — one resolver class, one context adapter, one middleware.
- Session-scoped caching fits naturally into ToolManager's existing per-session pattern.
- Default YAML policies are loaded once, navigator-auth handles evaluation.
- Existing `AllowAllResolver` and `DenyAllResolver` remain available for dev/testing.

**Cons:**
- Policy resource naming (`tool:*`, `agent:*`, `mcp:*`) must be manually mapped to internal names.
- Agent-level enforcement requires a new middleware/decorator layer outside the resolver.
- MCP tool filtering relies on MCP tools already being registered as AbstractTools (which they are via MCPToolProxy).

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth >= 0.19.0` | PBAC policy engine | Bump from >= 0.18.5 |
| `pyyaml` | YAML policy file loading | Already a transitive dependency |

**Existing Code to Reuse:**
- `parrot/auth/resolver.py` — `AbstractPermissionResolver` interface, extend with PBAC implementation
- `parrot/auth/permission.py` — `PermissionContext`, `UserSession` dataclasses
- `parrot/tools/manager.py` — `ToolManager.set_resolver()`, `filter_tools()` pipeline
- `parrot/tools/abstract.py` — Layer 2 `_required_permissions` check in `execute()`
- `parrot/handlers/agent.py` — Session-scoped ToolManager swap pattern in AgentTalk
- `parrot/mcp/integration.py` — `MCPToolProxy` inherits AbstractTool permission checks

---

### Option B: Centralized Policy Middleware

Create a standalone `PolicyMiddleware` for aiohttp that intercepts ALL requests and
evaluates policies before they reach any handler. The middleware resolves the user session,
determines the resource being accessed (agent, tool, MCP, module), and applies policies.
Tools are filtered by the middleware injecting a pre-filtered ToolManager into the request.

This is a "gateway" approach: all access control happens at one choke point.

**Pros:**
- Single enforcement point — easier to audit and reason about.
- No changes needed to individual handlers or the resolver interface.
- Policy evaluation happens once per request, naturally cached.
- Clean separation: handlers never think about permissions.

**Cons:**
- Middleware must understand all resource types (agents, tools, MCP, modules) — becomes a god-object.
- Tool filtering at the middleware level requires knowledge of which tools exist before the handler configures them — timing issue with session-scoped ToolManagers.
- Agent-level and tool-level policies have different evaluation timing (real-time vs cached) — hard to handle uniformly in middleware.
- Breaks the existing `AbstractPermissionResolver` pattern — parallel permission systems create confusion.
- Harder to test individual components in isolation.

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth >= 0.19.0` | PBAC policy engine | Bump from >= 0.18.5 |
| `pyyaml` | YAML policy file loading | Already a transitive dependency |

**Existing Code to Reuse:**
- `app.py` — Middleware registration pattern
- `parrot/handlers/agents/abstract.py` — Session access patterns

---

### Option C: Event-Driven Policy Hooks

Instead of a resolver or middleware, define policy evaluation as an event/hook system.
Components emit "access request" events (e.g., `on_agent_access`, `on_tool_filter`,
`on_mcp_connect`) and a `PolicyHookManager` subscribes to these events, evaluates
policies, and either allows or denies access.

This is inspired by WordPress-style hooks / Django signals — decoupled and extensible.

**Pros:**
- Highly extensible — new resource types just register new hooks.
- Decoupled — components don't import the policy engine directly.
- Easy to add custom policy evaluators (e.g., rate limiting, IP filtering) as additional hooks.
- Natural logging/audit trail by subscribing an audit hook.

**Cons:**
- Adds an event system abstraction that doesn't exist in ai-parrot today.
- Harder to reason about "what policies apply?" — must trace event subscriptions.
- Performance overhead from event dispatch on every access check.
- Tool filtering requires synchronous resolution (agent needs filtered tools before execution) — async events add complexity.
- Over-engineered for the current use case — PBAC policies are well-structured, not arbitrary hooks.

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth >= 0.19.0` | PBAC policy engine | Bump from >= 0.18.5 |
| `blinker` or custom | Event/signal dispatch | New dependency or custom impl |

**Existing Code to Reuse:**
- `parrot/auth/resolver.py` — Event handlers would wrap resolver logic
- `parrot/tools/manager.py` — Would need hook integration points

---

## Recommendation

**Option A** is recommended because it builds directly on ai-parrot's existing two-layer
permission architecture. The `AbstractPermissionResolver` interface was designed for exactly
this kind of extension — swapping in a PBAC-backed resolver requires no changes to
ToolManager, AbstractTool, or any handler that already uses the permission system.

The key tradeoff is that agent-level enforcement (business hours, etc.) needs a thin
decorator/middleware outside the resolver, since the resolver interface is tool-scoped.
This is acceptable because it's a small, focused addition — not a god-object middleware
like Option B.

Option C's event system is elegant in theory but introduces unnecessary abstraction for a
well-defined policy model. PBAC policies have clear structure (subjects, resources, actions,
conditions) that maps cleanly to a resolver, not to arbitrary event hooks.

---

## Feature Description

### User-Facing Behavior

**For end users:**
- Users authenticate normally via JWT. No new auth flow.
- When a user accesses an agent, the system checks policies in real-time. If access is
  denied (e.g., outside business hours, wrong group), they receive a clear error with the
  reason ("Access denied: agent X is only available during business hours").
- Tools the user cannot access are invisible — the agent never mentions or attempts to use
  them. The user sees a naturally scoped set of capabilities.
- Datasets the user cannot query are invisible to the DatasetManager toolkit.
- MCP server tools follow the same visibility pattern.

**For frontend developers:**
- A REST endpoint `GET /api/v1/permissions/check` accepts `resource` and `action` parameters
  and returns `{allowed: bool, reason: string}` for the authenticated user.
- Frontend can gate UI modules: if `concierge:AgentChat` + `view` is denied, hide the module.

**For operators/admins:**
- YAML policy files in a configurable directory (e.g., `policies/` or via config path).
- Default policies ship with ai-parrot (deny-by-default with sensible allows).
- Policy changes take effect on next server restart (v1 — hot-reload is a future enhancement).

### Internal Behavior

**Startup:**
1. `PolicyEngine` (thin wrapper around navigator-auth PBAC) loads YAML policy files.
2. A `PBACPermissionResolver` is instantiated with the policy engine reference.
3. The resolver is set as the default resolver on `BotManager` and/or individual bots.

**Agent access (per-request, real-time):**
1. Request arrives at `AgentTalk` or `ChatHandler`.
2. A `@check_agent_access` decorator (or middleware) extracts the session, builds a policy
   context (`subject=user, resource=agent:{agent_id}, action=agent:execute`), and evaluates.
3. If denied, returns 403 with reason. If allowed, proceeds to handler body.

**Tool filtering (per-session, cached):**
1. When `AgentTalk.PATCH` configures a session-scoped ToolManager, or when
   `AgentTalk.POST` prepares the agent for execution:
2. The `PBACPermissionResolver.filter_tools()` evaluates each tool against policies
   (`resource=tool:{tool_name}`, `action=tool:execute`, subject=user session).
3. Denied tools are removed from the ToolManager clone. Result is cached in the session.
4. The agent receives only the allowed tools.

**Dataset filtering (per-session, cached):**
1. DatasetManager entries are filtered the same way as tools.
2. `resource=dataset:{dataset_name}`, `action=dataset:query`.

**MCP server filtering (per-session, cached):**
1. Before registering MCP server tools into the ToolManager, evaluate policies.
2. `resource=mcp:{server_name}`, `action=tool:execute`.
3. If the MCP server is denied, its tools are not registered.

**Frontend permission check (per-request, real-time):**
1. `GET /api/v1/permissions/check?resource=concierge:AgentChat&action=view`
2. Extracts session, evaluates policy, returns JSON result.

### Edge Cases & Error Handling

- **No policies loaded**: Falls back to `AllowAllResolver` behavior (or configurable default).
- **Malformed YAML policy**: Logged as error at startup, skipped. Server still starts.
- **User with no groups/roles**: Matches only policies with `groups: ["*"]`.
- **Tool added mid-session (e.g., via PATCH)**: Re-evaluates filter for new tools only,
  merges with cached allowed set.
- **Business hours boundary**: User starts a conversation at 4:55 PM, business hours end
  at 5:00 PM. Next request after 5:00 PM is denied (real-time evaluation).
- **MCP server unavailable**: MCP availability is orthogonal to policy — policy denies
  access, unavailability is a separate error.
- **Conflicting policies**: navigator-auth's priority system resolves conflicts
  (higher priority wins). If still ambiguous, deny-by-default applies.

---

## Capabilities

### New Capabilities
- `pbac-policy-engine`: Thin wrapper around navigator-auth PBAC for loading and evaluating YAML policies
- `pbac-permission-resolver`: `PBACPermissionResolver` implementing `AbstractPermissionResolver`
- `pbac-agent-guard`: Decorator/middleware for real-time agent access evaluation
- `pbac-permission-api`: REST endpoint for frontend permission queries
- `pbac-default-policies`: Default YAML policy files shipped with ai-parrot

### Modified Capabilities
- `tool-manager`: Add PBAC-aware filtering in `filter_tools()` via resolver swap
- `dataset-manager`: Integrate with PBAC resolver for dataset visibility filtering
- `mcp-tool-registration`: Filter MCP server tools through PBAC before registration
- `agent-talk-handler`: Integrate agent access guard and PBAC-filtered ToolManager

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/auth/resolver.py` | extends | Add `PBACPermissionResolver` class |
| `parrot/auth/permission.py` | extends | Add policy context adapter for PBAC attributes |
| `parrot/tools/manager.py` | modifies | Wire PBAC resolver as default, ensure filter_tools uses it |
| `parrot/tools/dataset_manager/` | modifies | Add PBAC filtering for dataset entries |
| `parrot/handlers/agent.py` | modifies | Add agent access guard decorator |
| `parrot/handlers/chat.py` | modifies | Add agent access guard decorator |
| `parrot/mcp/integration.py` | modifies | Filter MCP tools through PBAC before registration |
| `parrot/handlers/` (new) | extends | Add `PermissionCheckHandler` for frontend API |
| `app.py` | modifies | Initialize PolicyEngine, register permission handler route |
| `pyproject.toml` | modifies | Bump navigator-auth to >= 0.19.0 |
| `policies/` (new dir) | new | Default YAML policy files |

**Breaking changes:** None. Existing `AllowAllResolver` remains the default until policies
are configured. The PBAC resolver is opt-in via configuration.

---

## Parallelism Assessment

**Internal parallelism**: High. The feature decomposes into independent components:
- Policy engine wrapper (standalone, no deps on other new code)
- PBACPermissionResolver (depends on engine wrapper only)
- Agent access guard decorator (depends on engine wrapper only)
- Tool/dataset filtering integration (depends on resolver)
- MCP filtering integration (depends on resolver)
- Permission check REST API (depends on engine wrapper only)
- Default YAML policies (independent)

**Cross-feature independence**: No conflicts with in-flight specs. The auth layer is not
being modified by other features.

**Recommended isolation**: `mixed` — the policy engine, resolver, and REST API can be
developed in parallel worktrees. Tool/dataset/MCP integration tasks should be sequential
as they share the resolver.

**Rationale**: The engine wrapper and REST API have zero coupling to the filtering
integration tasks. Running them in parallel saves time without merge conflicts.

---

## Open Questions

- [ ] Does navigator-auth 0.19.0 expose a Python-importable policy engine class, or does it need to be instantiated via a specific factory? — *Owner: Jesus Lara*
- [ ] Should policy hot-reload (without restart) be a v1 requirement or deferred? — *Owner: Jesus Lara*
- [ ] What resource naming scheme for datasets? `dataset:{name}` or `tool:dataset:{name}`? — *Owner: Jesus Lara*
- [ ] Should the permission check API support batch queries (multiple resources in one call)? — *Owner: Jesus Lara*
- [ ] How are "programs" from the user session mapped to PBAC subjects? Direct attribute or custom condition? — *Owner: Jesus Lara*
