# Feature Specification: Policy-Based Access Control (PBAC) Integration

**Feature ID**: FEAT-077
**Date**: 2026-04-03
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x.x
**Proposal**: `sdd/proposals/policy-based-access-control.brainstorm.md`
**Builds on**: FEAT-014 (Granular Permissions System)

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-014 introduced a two-layer permission system (Layer 1: preventive filtering,
Layer 2: reactive enforcement) with `AbstractPermissionResolver`, `PermissionContext`,
and `@requires_permission`. However, this system is RBAC-only — permissions are
role-based and statically defined via decorators on tools.

ai-parrot needs **policy-driven, attribute-based access control** that can express
dynamic conditions:
- **Time-based**: "Agent X is only available during business hours"
- **Group/department-based**: "Only DevOps team can configure MCP servers"
- **Program/tenant-based**: "User can only access agents in their organization"
- **Resource-granular**: "Engineering can execute tools but not configure them"
- **Combinable**: "QA team can use testing tools during business hours only"

navigator-auth 0.19.0 provides a production-ready PBAC/ABAC engine with `PolicyEvaluator`,
`PDP`, `Guardian`, `ResourcePolicy`, and YAML-based policy definitions. Since we control
the navigator-auth codebase, we can extend it with `Guardian.filter_resources()`,
`ResourceType.DATASET`, and program-based conditions as needed.

### Goals
- Integrate navigator-auth's PBAC engine into ai-parrot using the hybrid approach:
  PDP + Guardian for handler-level enforcement, Guardian.filter_resources() for tool/dataset/MCP filtering
- Agent access control with real-time policy evaluation (business hours, groups, programs)
- Tool/dataset/MCP visibility filtering at handler level — unauthorized resources invisible to agents
- Frontend permission query API via `PDP.setup(app)` auto-registered endpoints
- Ship default YAML policies (deny-by-default) with ai-parrot
- Preserve FEAT-014's `AbstractPermissionResolver` contract as Layer 2 safety net

### Non-Goals (explicitly out of scope)
- Policy CRUD API (v1 is query-only; admin manages YAML files or database directly)
- Policy hot-reload without restart (deferred to v2; `YAMLStorage.reload()` exists but not wired)
- Argument-level ABAC (e.g., "user can query dataset X but only columns A,B,C")
- AgentCrew/A2A permission propagation across sub-agents
- UI for policy management

---

## 2. Architectural Design

### Overview

The hybrid architecture uses navigator-auth components at their intended abstraction levels:

1. **PDP + Guardian** — handler-level enforcement for agent access, leveraging
   `@requires_permission` and `@groups_protected` decorators.
2. **Guardian.filter_resources()** — generic resource filtering method (following
   `filter_files()` pattern) for tools, datasets, and MCP servers at the handler
   level when ToolManager is instantiated. NEVER at middleware level.
3. **PBACPermissionResolver** — thin adapter implementing `AbstractPermissionResolver`,
   wrapping Guardian for Layer 2 safety net in `AbstractTool.execute()`.
4. **PDP.setup(app)** — auto-registers Guardian as `app['security']`, middleware for
   general HTTP route policies, and `/api/v1/abac/check` REST endpoint.

### Component Diagram
```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              Startup (app.py)                                    │
│                                                                                  │
│  YAMLStorage ──→ PolicyLoader ──→ PolicyEvaluator ──→ PDP ──→ PDP.setup(app)   │
│                                    (cache_ttl=30s)     │                         │
│                                         │              └──→ Guardian             │
│                                         │                    │                   │
│                                         │              app['security']           │
│                                         │                    │                   │
│                                         └──→ PBACPermissionResolver              │
│                                              (Layer 2 safety net)                │
└──────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────────┐
│                         Request Flow (per-request)                                │
│                                                                                  │
│  HTTP Request ──→ auth middleware (JWT/session) ──→ abac_middleware (URI routes) │
│       │                                                                          │
│       ▼                                                                          │
│  ┌─────────────────────────────────────────────────────────────┐                │
│  │ Handler (AgentTalk / ChatHandler)                            │                │
│  │                                                              │                │
│  │  ┌─ @requires_permission(ResourceType.AGENT, "agent:chat")  │                │
│  │  │   └─ Guardian.is_allowed(request) ──→ ALLOW/DENY (403)  │                │
│  │  │                                                           │                │
│  │  ├─ Guardian.filter_resources(tools, request, TOOL)         │                │
│  │  │   └─ PolicyEvaluator.filter_resources() ──→ allowed[]   │                │
│  │  │   └─ Remove denied tools from cloned ToolManager         │                │
│  │  │                                                           │                │
│  │  ├─ Guardian.filter_resources(datasets, request, DATASET)   │                │
│  │  │   └─ Remove denied datasets from DatasetManager          │                │
│  │  │                                                           │                │
│  │  ├─ Guardian.filter_resources(mcp_servers, request, MCP)    │                │
│  │  │   └─ Skip denied MCP server tool registration            │                │
│  │  │                                                           │                │
│  │  └─ Agent executes with filtered ToolManager                │                │
│  │      └─ AbstractTool.execute() ──→ PBACPermissionResolver   │                │
│  │          (Layer 2 safety net, logs denials)                  │                │
│  └─────────────────────────────────────────────────────────────┘                │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐                │
│  │ PermissionCheckHandler (auto-registered by PDP.setup)        │                │
│  │  POST /api/v1/abac/check                                    │                │
│  │   └─ PolicyEvaluator.check_access() ──→ {allowed, reason}  │                │
│  └─────────────────────────────────────────────────────────────┘                │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator_auth.abac.PDP` | uses | `setup(app)` for Guardian, middleware, REST |
| `navigator_auth.abac.Guardian` | uses + extends | `filter_resources()` (new generic method) |
| `navigator_auth.abac.PolicyEvaluator` | uses | `check_access()`, `filter_resources()`, LRU cache |
| `navigator_auth.abac.ResourceType` | extends | Add `DATASET` enum value |
| `navigator_auth.abac.decorators` | uses | `@requires_permission`, `@groups_protected` |
| `navigator_auth.abac.EvalContext` | uses | Built from request + session |
| `navigator_auth.abac.Environment` | uses | `is_business_hours`, `day_segment` |
| `navigator_auth.abac.YAMLStorage` | uses | Policy file loading |
| `parrot/auth/resolver.py` | extends | Add `PBACPermissionResolver` |
| `parrot/tools/manager.py` | modifies | Set PBAC resolver when policies configured |
| `parrot/handlers/agent.py` | modifies | Agent guard + tool filtering via Guardian |
| `parrot/handlers/chat.py` | modifies | Agent guard decorator |
| `parrot/mcp/integration.py` | modifies | MCP tool filtering via Guardian |
| `app.py` | modifies | PDP + PolicyEvaluator initialization |

### Data Models

```python
# navigator-auth additions (upstream)

class ResourceType(Enum):
    TOOL = "tool"
    KB = "kb"
    VECTOR = "vector"
    AGENT = "agent"
    MCP = "mcp"
    URI = "uri"
    DATASET = "dataset"  # NEW

# ai-parrot: PBACPermissionResolver

class PBACPermissionResolver(AbstractPermissionResolver):
    """PBAC-backed resolver delegating to Guardian/PolicyEvaluator.

    Acts as Layer 2 safety net in AbstractTool.execute().
    Primary enforcement happens via Guardian at handler level.
    """

    def __init__(
        self,
        guardian: Guardian,
        evaluator: PolicyEvaluator,
        logger: Optional[logging.Logger] = None,
    ):
        self._guardian = guardian
        self._evaluator = evaluator
        self.logger = logger or logging.getLogger(__name__)

    async def can_execute(
        self,
        context: PermissionContext,
        tool_name: str,
        required_permissions: set[str],
    ) -> bool:
        """Layer 2 check — evaluates PBAC policy for tool execution."""
        ...

    async def filter_tools(
        self,
        context: PermissionContext,
        tools: list,
    ) -> list:
        """Delegates to PolicyEvaluator.filter_resources()."""
        ...
```

### New Public Interfaces

```python
# navigator-auth: Guardian.filter_resources() (new generic method)

class Guardian:
    async def filter_resources(
        self,
        resources: list[str],
        request: web.Request,
        resource_type: ResourceType = ResourceType.TOOL,
        action: str = "tool:execute",
    ) -> FilteredResources:
        """Filter resources by PBAC policies for the authenticated user.

        Follows the same pattern as filter_files(): extracts session,
        builds EvalContext, delegates to PolicyEvaluator.filter_resources().

        Returns:
            FilteredResources with .allowed and .denied lists.
        """
        ...

# ai-parrot: PBAC setup helper

async def setup_pbac(
    app: web.Application,
    policy_dir: str = "policies",
    cache_ttl: int = 30,
    default_effect: PolicyEffect = PolicyEffect.DENY,
) -> tuple[PDP, PolicyEvaluator, PBACPermissionResolver]:
    """Initialize PBAC engine and register with the aiohttp app.

    1. Loads YAML policies from policy_dir via YAMLStorage.
    2. Creates PolicyEvaluator with short TTL cache.
    3. Creates PDP, attaches evaluator, calls PDP.setup(app).
    4. Creates PBACPermissionResolver for Layer 2 safety net.
    """
    ...
```

---

## 3. Module Breakdown

### Module 1: navigator-auth Upstream Changes
- **Path**: `navigator-auth` (separate repository)
- **Responsibility**:
  - Add `ResourceType.DATASET` to `navigator_auth/abac/policies/resources.py`
  - Add `Guardian.filter_resources()` generic method to `navigator_auth/abac/guardian.py`
    (following `filter_files()` pattern, accepting `resource_type` and `action` parameters)
  - Add programs/tenants as condition attribute support in policy evaluation
  - Support configurable short TTL in `PolicyEvaluator` for time-dependent policies
- **Depends on**: None (upstream, must be completed and released first)

### Module 2: PBAC Setup & Initialization
- **Path**: `parrot/auth/pbac.py` (new file)
- **Responsibility**:
  - `setup_pbac()` function: initializes `YAMLStorage`, `PolicyEvaluator` (with short TTL),
    `PDP`, calls `PDP.setup(app)`, creates `PBACPermissionResolver`
  - Configuration loading (policy directory path from app config)
  - Store references in `app` for handler access
- **Depends on**: Module 1

### Module 3: PBACPermissionResolver
- **Path**: `parrot/auth/resolver.py` (extend existing file)
- **Responsibility**:
  - Implement `PBACPermissionResolver(AbstractPermissionResolver)`
  - `can_execute()`: delegates to `PolicyEvaluator.check_access(ResourceType.TOOL, ...)`
  - `filter_tools()`: delegates to `PolicyEvaluator.filter_resources(ResourceType.TOOL, ...)`
  - Logs denials for audit trail (even when Guardian already filtered the tool)
  - Bridges `PermissionContext` to `EvalContext`
- **Depends on**: Module 1, Module 2

### Module 4: Agent Access Guard
- **Path**: `parrot/handlers/agent.py`, `parrot/handlers/chat.py`
- **Responsibility**:
  - Add `@requires_permission(resource_type=ResourceType.AGENT, action="agent:chat",
    resource_name_param="agent_id")` decorator to `AgentTalk` POST/PATCH handlers
  - Add same decorator to `ChatHandler` POST handler
  - Guardian evaluates agent access in real-time (no caching for time-dependent policies)
  - Returns 403 with `EvaluationResult.reason` on denial
- **Depends on**: Module 2

### Module 5: Tool Filtering Integration
- **Path**: `parrot/handlers/agent.py`
- **Responsibility**:
  - After creating/cloning session-scoped ToolManager in `AgentTalk`:
    ```python
    guardian = self.request.app['security']
    filtered = await guardian.filter_resources(
        resources=tool_manager.tool_names,
        request=self.request,
        resource_type=ResourceType.TOOL,
        action="tool:execute"
    )
    ```
  - Remove denied tools from cloned ToolManager
  - Cached by PolicyEvaluator LRU (30s TTL)
- **Depends on**: Module 2, Module 3

### Module 6: Dataset Filtering Integration
- **Path**: `parrot/handlers/agent.py` (or `parrot/handlers/datasets.py`)
- **Responsibility**:
  - Filter DatasetManager entries through Guardian before agent receives them:
    ```python
    filtered = await guardian.filter_resources(
        resources=dataset_names,
        request=self.request,
        resource_type=ResourceType.DATASET,
        action="dataset:query"
    )
    ```
  - Denied datasets removed — invisible to agent
- **Depends on**: Module 1 (ResourceType.DATASET), Module 2

### Module 7: MCP Server Filtering Integration
- **Path**: `parrot/handlers/agent.py` (or `parrot/mcp/integration.py`)
- **Responsibility**:
  - Before registering MCP server tools into ToolManager:
    ```python
    filtered = await guardian.filter_resources(
        resources=mcp_server_names,
        request=self.request,
        resource_type=ResourceType.MCP,
        action="tool:execute"
    )
    ```
  - Denied MCP servers' tools are not registered
- **Depends on**: Module 2

### Module 8: App Startup Integration
- **Path**: `app.py`
- **Responsibility**:
  - Call `setup_pbac(app, policy_dir=config.policy_dir)` during app initialization
  - Set `PBACPermissionResolver` as default resolver on `BotManager`
  - Conditional: only activate PBAC if policy directory exists and contains policies
  - Fallback to `AllowAllResolver` if no policies configured
- **Depends on**: Module 2, Module 3

### Module 9: Default YAML Policies
- **Path**: `policies/` (new directory at project root)
- **Responsibility**:
  - `defaults.yaml`: Base deny-by-default with `groups: ["*"]` allow for common operations
  - `agents.yaml`: Example agent access policies (business hours, group restrictions)
  - `tools.yaml`: Example tool access policies (per-group tool visibility)
  - `mcp.yaml`: Example MCP server access policies
  - `README.md`: Policy authoring guide with schema reference
- **Depends on**: None (can be written in parallel)

### Module 10: Unit & Integration Tests
- **Path**: `tests/auth/test_pbac.py` (new file)
- **Responsibility**:
  - Test `PBACPermissionResolver.can_execute()` and `filter_tools()`
  - Test `setup_pbac()` initialization
  - Test agent access guard decorator behavior (allow/deny)
  - Test tool filtering integration (tools invisible after filtering)
  - Test dataset filtering
  - Test MCP filtering
  - Test business hours time-dependent policy evaluation
  - Test default deny when no policies match
  - Test policy priority resolution (deny takes precedence)
- **Depends on**: Modules 2-8

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_pbac_resolver_init` | Module 3 | PBACPermissionResolver accepts Guardian + PolicyEvaluator |
| `test_pbac_resolver_can_execute_allow` | Module 3 | Returns True when policy allows tool execution |
| `test_pbac_resolver_can_execute_deny` | Module 3 | Returns False and logs when policy denies tool |
| `test_pbac_resolver_filter_tools` | Module 3 | Returns only allowed tools from PolicyEvaluator |
| `test_pbac_resolver_no_policies` | Module 3 | Default deny when no policies loaded |
| `test_context_bridge` | Module 3 | PermissionContext correctly bridges to EvalContext |
| `test_setup_pbac_with_policies` | Module 2 | setup_pbac loads YAML, creates PDP, registers Guardian |
| `test_setup_pbac_no_policies` | Module 2 | Falls back gracefully when no policy directory |
| `test_setup_pbac_malformed_yaml` | Module 2 | Skips invalid files, starts with valid policies only |
| `test_agent_guard_allow` | Module 4 | Agent access allowed for authorized user/group |
| `test_agent_guard_deny_group` | Module 4 | Agent access denied for wrong group, returns 403 |
| `test_agent_guard_deny_business_hours` | Module 4 | Agent access denied outside business hours |
| `test_tool_filter_removes_denied` | Module 5 | Denied tools removed from cloned ToolManager |
| `test_tool_filter_preserves_allowed` | Module 5 | Allowed tools remain in ToolManager |
| `test_tool_filter_wildcard` | Module 5 | `tool:*` policy matches all tools |
| `test_tool_filter_pattern` | Module 5 | `tool:jira_*` matches jira_create, jira_search |
| `test_dataset_filter` | Module 6 | Denied datasets invisible to agent |
| `test_mcp_filter` | Module 7 | Denied MCP server tools not registered |
| `test_policy_priority_deny_wins` | Module 10 | DENY at equal priority overrides ALLOW |
| `test_enforcing_short_circuit` | Module 10 | Enforcing policy stops evaluation |
| `test_cache_ttl_refresh` | Module 10 | Cached decisions expire after TTL |

### Integration Tests
| Test | Description |
|---|---|
| `test_full_flow_agent_access` | Authenticated user accesses agent — Guardian checks policy, allows/denies |
| `test_full_flow_tool_filtering` | User with restricted tools — agent only sees allowed tools |
| `test_full_flow_business_hours` | User accesses agent during/outside business hours — correct behavior |
| `test_full_flow_frontend_check` | Frontend calls `/api/v1/abac/check` — returns correct allow/deny |
| `test_full_flow_multiple_policies` | Multiple overlapping policies — priority resolution works |
| `test_backward_compat_no_pbac` | App without policies — AllowAllResolver, all tools visible |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_policies_dir(tmp_path):
    """Create temporary YAML policy files."""
    policy = {
        "version": "1.0",
        "defaults": {"effect": "deny"},
        "policies": [
            {
                "name": "engineering_tools",
                "effect": "allow",
                "resources": ["tool:*"],
                "actions": ["tool:execute", "tool:list"],
                "subjects": {"groups": ["engineering"]},
                "priority": 20,
            },
            {
                "name": "business_hours_agent",
                "effect": "allow",
                "resources": ["agent:*"],
                "actions": ["agent:chat"],
                "subjects": {"groups": ["*"]},
                "conditions": {"environment": {"is_business_hours": True}},
                "priority": 10,
            },
        ],
    }
    policy_file = tmp_path / "test_policies.yaml"
    import yaml
    policy_file.write_text(yaml.dump(policy))
    return tmp_path


@pytest.fixture
def engineering_user_session():
    return UserSession(
        user_id="eng-1",
        tenant_id="acme",
        roles=frozenset({"engineer"}),
        metadata={"groups": ["engineering"], "programs": ["acme_corp"]},
    )


@pytest.fixture
def guest_user_session():
    return UserSession(
        user_id="guest-1",
        tenant_id="acme",
        roles=frozenset(),
        metadata={"groups": ["guest"]},
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] navigator-auth >= 0.19.0 with `ResourceType.DATASET`, `Guardian.filter_resources()`,
      programs as conditions, and short-TTL cache support
- [ ] `setup_pbac()` initializes PDP + PolicyEvaluator + YAMLStorage + Guardian from config
- [ ] `PDP.setup(app)` registers Guardian as `app['security']`, middleware, and
      `/api/v1/abac/check` endpoint
- [ ] `PBACPermissionResolver` implements `AbstractPermissionResolver`, delegates to
      PolicyEvaluator, logs denials
- [ ] `AgentTalk` POST/PATCH uses `@requires_permission` for agent access (real-time)
- [ ] `ChatHandler` POST uses `@requires_permission` for agent access (real-time)
- [ ] Tool filtering via `Guardian.filter_resources(ResourceType.TOOL)` at handler level —
      denied tools invisible to agent
- [ ] Dataset filtering via `Guardian.filter_resources(ResourceType.DATASET)` — denied
      datasets invisible to agent
- [ ] MCP server filtering via `Guardian.filter_resources(ResourceType.MCP)` — denied
      MCP tools not registered
- [ ] Default YAML policies ship in `policies/` directory (deny-by-default)
- [ ] Business hours policy correctly denies agent access outside configured hours
- [ ] `PolicyEvaluator` cache uses short TTL (30s) for time-dependent policy refresh
- [ ] Frontend can query `POST /api/v1/abac/check` for module access (concierge:AgentChat)
- [ ] No policies configured → `AllowAllResolver` fallback, all tools/agents accessible
- [ ] All unit tests pass: `pytest tests/auth/test_pbac.py -v`
- [ ] All integration tests pass
- [ ] No breaking changes to existing tools, agents, or handlers
- [ ] FEAT-014's `AbstractPermissionResolver` contract preserved (Layer 2 safety net)

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Use navigator-auth's `Guardian` as the single Policy Enforcement Point (PEP)
- Use `@requires_permission` / `@groups_protected` decorators from navigator-auth directly
- Use `PolicyEvaluator.filter_resources()` for batch resource filtering
- Build `EvalContext` from `aiohttp.web.Request` + `navigator_session.get_session()`
- Follow async-first design — all Guardian methods are async
- Use `self.logger` for permission denials and audit trails
- Pydantic models for any new data structures

### Known Risks / Gotchas
- **Cache TTL vs real-time**: Time-dependent policies (business hours) require short TTL (30s).
  PolicyEvaluator cache key is `MD5(user|groups|resource_type|resource|action)` — does NOT
  include time. Short TTL is the mitigation.
- **Two permission paths**: Guardian (primary, handler-level) and PBACPermissionResolver
  (Layer 2 safety net in `AbstractTool.execute()`). Both MUST use the same PolicyEvaluator
  instance to avoid inconsistent decisions.
- **Navigator-auth dependency**: Upstream changes must be released before ai-parrot
  integration. Coordinate release timing.
- **EvalContext population**: Requires `userinfo["groups"]`, `userinfo["roles"]`,
  `userinfo["username"]` from session. If auth middleware hasn't run, EvalContext will be
  incomplete and policies will default to DENY.
- **Policy file location**: Policy directory must be configurable. Don't hardcode paths.
- **Backward compatibility**: When no policies are configured, system must behave exactly
  as before — `AllowAllResolver` as default, all tools/agents accessible.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `navigator-auth` | `>= 0.19.0` | PBAC engine: PolicyEvaluator, PDP, Guardian, ResourcePolicy, YAMLStorage |

### Policy File Schema Reference
```yaml
version: "1.0"
defaults:
  effect: deny           # Default effect when no policy matches
policies:
  - name: policy_name    # Unique identifier
    effect: allow|deny   # Policy effect
    description: "..."   # Human-readable description
    resources:           # Resource patterns (type:name, supports wildcards)
      - "tool:*"
      - "agent:finance_bot"
      - "mcp:github_*"
      - "dataset:sales_*"
    actions:             # Action types
      - "tool:execute"
      - "tool:list"
      - "agent:chat"
      - "dataset:query"
    subjects:            # Who this policy applies to
      groups:
        - engineering
        - "*"            # Wildcard = any authenticated user
      users:
        - admin@acme.com
      roles:
        - senior_engineer
      exclude_groups:    # Exclusion takes precedence
        - contractors
      exclude_users:
        - blocked@acme.com
    conditions:          # Attribute-based conditions
      environment:
        is_business_hours: true
        day_of_week: [0, 1, 2, 3, 4]  # Mon-Fri
      programs:          # Tenant/organization conditions
        - acme_corp
    priority: 20         # Higher priority evaluated first; DENY wins at equal
    enforcing: false     # If true, short-circuits evaluation on match
```

---

## 7. Open Questions

> All critical questions resolved during brainstorm. Remaining items are implementation details.

- [ ] Should `Guardian.filter_resources()` supersede `filter_files()` entirely, or should
      `filter_files()` remain as a convenience wrapper? — *Owner: Jesus Lara*
- [ ] What `ActionType` values should be defined for `DATASET` resources? Candidates:
      `dataset:query`, `dataset:write`, `dataset:list`, `dataset:admin` — *Owner: Jesus Lara*

---

## Worktree Strategy

**Isolation**: `per-spec` (sequential tasks in one worktree)

**Rationale**: Tasks share handlers (`agent.py`), `app.py`, and the resolver module.
Parallel worktrees would cause merge conflicts. The navigator-auth upstream changes
(Module 1) are done in a separate repository and must be released first.

**Execution order**:
1. Module 1: navigator-auth upstream (separate repo, prerequisite)
2. Module 9: Default YAML policies (independent, can start early)
3. Module 2: PBAC setup
4. Module 3: PBACPermissionResolver
5. Module 8: App startup integration
6. Module 4: Agent access guard
7. Module 5: Tool filtering
8. Module 6: Dataset filtering
9. Module 7: MCP filtering
10. Module 10: Tests

**Cross-feature dependencies**: None. FEAT-014 (granular permissions) is already merged
and provides the `AbstractPermissionResolver` foundation.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-03 | Jesus Lara | Initial draft from brainstorm Option D (hybrid) |
