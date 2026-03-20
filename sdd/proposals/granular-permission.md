# AI-Parrot Framework — Granular Permissions System
**Technical Specification for Tools & Toolkits Permission Enforcement**
_Version 0.1 — Draft_

---

## 1. Overview & Motivation

AI-Parrot exposes LLM agents to collections of tools via Toolkits. At runtime, the LLM receives the full list of available tools in its context window and can call any of them. System-prompt enforcement ("only use tools the user is allowed to") is a guideline, not a contract — the model can deviate.

This specification defines a layered, enforcement-first permission system that operates at the Python execution layer, not the prompt layer. The goal is to make unauthorized tool execution structurally impossible regardless of what the LLM decides to call.

> **Core Principle:** Permission enforcement must live in the execution layer, not in the prompt. If a user lacks permission for a tool, the tool must never execute — even if the LLM requests it. The session stays lightweight. Permission logic lives in code, not in data structures.

---

## 2. Design Goals

- Enforcement at execution time — not prompt-dependent
- Lightweight sessions — user identity and roles only, no expanded permission maps
- Declarative tool permissions — annotated in code via decorators
- Pluggable resolver — injectable `PermissionResolver` supports custom logic per deployment
- Multi-tenant ready — resolver receives tenant context and can route to tenant-specific rule sets
- Optional caching — resolver can cache expanded role sets (e.g. Redis) without changing the interface
- Defense in depth — two enforcement layers: preventive filtering + reactive enforcement
- Zero breaking changes — fully backward-compatible; tools without annotations continue to work

---

## 3. Architecture

### 3.1 Two Enforcement Layers

The system uses a defense-in-depth approach with two independent layers:

| Layer | Where | What it does | When it fires |
|---|---|---|---|
| 1 — Preventive | `AbstractToolkit.get_tools()` | Filters tool list before LLM sees it. Unauthorized tools are invisible. | Agent startup / session init |
| 2 — Reactive | `AbstractTool.execute()` | Rejects execution even if LLM requests a tool it shouldn't call. | Every tool call attempt |

### 3.2 Component Map

| Component | Responsibility |
|---|---|
| `UserSession` | Carries `user_id`, `tenant_id`, and `roles` (frozenset). Lightweight — no expanded permissions. |
| `PermissionContext` | Thin wrapper passed to resolvers and filter methods. Bundles session + optional metadata. |
| `AbstractPermissionResolver` | Protocol/ABC defining the resolver interface. Implementations are injected. |
| `DefaultPermissionResolver` | Reference implementation: RBAC role hierarchy with in-memory LRU caching. |
| `@requires_permission()` | Decorator that annotates toolkit methods with required permission strings. |
| `AbstractToolkit.get_tools()` | Accepts optional `PermissionContext`; filters tools the user cannot access. |
| `AbstractTool.execute()` | Checks `PermissionContext` before calling `_execute()`. Returns `ToolResult(forbidden)`. |
| `ToolManager` | Holds the injected resolver; propagates `PermissionContext` during tool dispatch. |

---

## 4. Data Models

### 4.1 UserSession

The session object is intentionally minimal. It carries identity and role claims only — no expanded permission lists that would bloat session storage.

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass(frozen=True)
class UserSession:
    user_id:   str
    tenant_id: str
    roles:     frozenset[str]    # e.g. frozenset({'jira.manage', 'github.read'})
    metadata:  dict = field(default_factory=dict)  # JWT claims, etc.
```

> **Why `frozenset`?** Immutable and hashable — safe to use as cache keys. Efficient set operations for role intersection checks. Prevents accidental mutation during request handling.

### 4.2 PermissionContext

A thin, request-scoped wrapper that groups a session with optional extra context (e.g. request origin, impersonation flag). This is what gets passed through the execution chain.

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class PermissionContext:
    session:    UserSession
    request_id: Optional[str] = None   # for audit logging
    extra:      dict = field(default_factory=dict)

    @property
    def user_id(self) -> str:
        return self.session.user_id

    @property
    def tenant_id(self) -> str:
        return self.session.tenant_id

    @property
    def roles(self) -> frozenset[str]:
        return self.session.roles
```

---

## 5. AbstractPermissionResolver

The resolver is the single point of truth for "can this user execute this tool?" It is designed to be injected — different deployments can provide different implementations without touching framework internals.

```python
from abc import ABC, abstractmethod
from typing import Optional, Set

class AbstractPermissionResolver(ABC):
    """
    Pluggable resolver for tool permission checks.
    Implementations can be injected into ToolManager.
    """

    @abstractmethod
    async def can_execute(
        self,
        context: PermissionContext,
        tool_name: str,
        required_permissions: Set[str],
    ) -> bool:
        """
        Return True if the user in context may execute the tool.
        required_permissions: set from @requires_permission decorator.
        Empty set means no restriction — always allow.
        """

    async def filter_tools(
        self,
        context: PermissionContext,
        tools: list,
    ) -> list:
        """
        Return the subset of tools the user is allowed to execute.
        Default: call can_execute for each. Override for bulk optimization.
        """
        allowed = []
        for tool in tools:
            perms = getattr(tool, '_required_permissions', set())
            if await self.can_execute(context, tool.name, perms):
                allowed.append(tool)
        return allowed
```

---

## 6. DefaultPermissionResolver

The reference implementation ships with AI-Parrot. It supports hierarchical RBAC and optional in-process LRU caching. Teams needing Redis-backed caching or database-driven rules can subclass or replace it entirely.

### 6.1 Role Hierarchy

Roles are defined as a DAG. A user with a higher-level role implicitly holds all permissions of lower-level roles. The resolver expands roles before checking.

```python
# Example hierarchy — defined per toolkit or globally
JIRA_ROLE_HIERARCHY: dict[str, set[str]] = {
    'jira.admin':  {'jira.manage', 'jira.write', 'jira.read'},
    'jira.manage': {'jira.write', 'jira.read'},
    'jira.write':  {'jira.read'},
    'jira.read':   set(),
}
```

### 6.2 Implementation

```python
from functools import lru_cache
from typing import Dict, Set

class DefaultPermissionResolver(AbstractPermissionResolver):

    def __init__(
        self,
        role_hierarchy: Dict[str, Set[str]] = None,
        cache_size: int = 256,
    ):
        self._hierarchy  = role_hierarchy or {}
        self._cache_size = cache_size
        # Wrap expansion with LRU cache keyed on frozenset
        self._expand_cached = lru_cache(maxsize=cache_size)(self._expand_roles)

    def _expand_roles(self, roles: frozenset[str]) -> frozenset[str]:
        """Expand roles to all implicitly granted permissions."""
        expanded = set(roles)
        queue    = list(roles)
        while queue:
            role    = queue.pop()
            implied = self._hierarchy.get(role, set())
            new     = implied - expanded
            expanded |= new
            queue.extend(new)
        return frozenset(expanded)

    async def can_execute(
        self,
        context: PermissionContext,
        tool_name: str,
        required_permissions: Set[str],
    ) -> bool:
        if not required_permissions:
            return True  # unrestricted tool
        expanded = self._expand_cached(context.roles)
        return bool(required_permissions & expanded)
```

> **Caching note:** `lru_cache` keys on `frozenset(roles)` — identical role sets share a cached expansion. Cache is per-resolver instance. For multi-process deployments, inject a Redis-backed resolver instead of relying on the in-process LRU.

---

## 7. Multi-Tenant Redis Resolver (Sketch)

For production multi-tenant deployments, a Redis-backed resolver allows sharing expanded role caches across processes and isolating resolution logic per tenant.

```python
class RedisTenantPermissionResolver(AbstractPermissionResolver):
    """
    Tenant-aware resolver with Redis caching.
    Cache key: {tenant_id}:perm:{user_id}:{hash(roles)}
    """

    def __init__(self, redis_client, role_hierarchy_loader, ttl: int = 300):
        self._redis  = redis_client
        self._loader = role_hierarchy_loader  # callable(tenant_id) -> hierarchy dict
        self._ttl    = ttl                    # seconds

    async def can_execute(
        self,
        context: PermissionContext,
        tool_name: str,
        required_permissions: Set[str],
    ) -> bool:
        if not required_permissions:
            return True
        expanded = await self._get_expanded_roles(context)
        return bool(required_permissions & expanded)

    async def _get_expanded_roles(
        self, context: PermissionContext
    ) -> frozenset[str]:
        key    = f"{context.tenant_id}:perm:{context.user_id}"
        cached = await self._redis.smembers(key)
        if cached:
            return frozenset(cached)
        # Cache miss — expand and store
        hierarchy = await self._loader(context.tenant_id)
        expanded  = self._expand(context.roles, hierarchy)
        await self._redis.sadd(key, *expanded)
        await self._redis.expire(key, self._ttl)
        return expanded
```

---

## 8. `@requires_permission` Decorator

### 8.1 Specification

The decorator annotates toolkit methods (or standalone `AbstractTool` subclasses) with the minimum permissions required to execute them. The annotation is introspected at runtime by the resolver and by `get_tools()` for filtering.

```python
def requires_permission(*permissions: str):
    """
    Annotate a toolkit method or AbstractTool class with required permissions.

    Usage on toolkit methods:
        @requires_permission('jira.manage')
        async def delete_sprint(self, sprint_id: str): ...

    Usage on AbstractTool subclasses:
        @requires_permission('github.write', 'github.admin')
        class CreateRepositoryTool(AbstractTool): ...

    Semantics: ANY of the listed permissions grants access (OR logic).
    For AND logic, use a single compound permission string.
    """
    def decorator(obj):
        obj._required_permissions = frozenset(permissions)
        return obj
    return decorator
```

### 8.2 Semantics: OR vs AND

| Pattern | Meaning | Example |
|---|---|---|
| `@requires_permission('a', 'b')` | OR — user needs `a` OR `b` | `jira.manage` OR `jira.admin` |
| `@requires_permission('a.b')` | Exact match — user needs `a.b` | `jira.write` exactly |
| No decorator | Unrestricted — any user may call | `search_issues`, `get_issue` |

### 8.3 Usage in JiraToolkit

```python
class JiraToolkit(AbstractToolkit):

    # ── No decorator — available to all users ──────────────────────────────
    async def search_issues(self, query: str, project: str) -> ToolResult:
        """Search for Jira issues by JQL query."""
        ...

    async def get_issue(self, issue_key: str) -> ToolResult:
        """Retrieve a single Jira issue by key."""
        ...

    # ── jira.write — developers and above ─────────────────────────────────
    @requires_permission('jira.write')
    async def create_issue(self, project: str, summary: str,
                           description: str = '') -> ToolResult:
        """Create a new Jira issue."""
        ...

    @requires_permission('jira.write')
    async def add_comment(self, issue_key: str, body: str) -> ToolResult:
        """Add a comment to an existing issue."""
        ...

    # ── jira.manage — team leads and PMs ──────────────────────────────────
    @requires_permission('jira.manage')
    async def delete_sprint(self, sprint_id: str) -> ToolResult:
        """Delete a sprint. Requires management permissions."""
        ...

    @requires_permission('jira.manage')
    async def assign_roles(self, user: str, role: str) -> ToolResult:
        """Assign roles to team members."""
        ...

    # ── jira.admin — admins only ───────────────────────────────────────────
    @requires_permission('jira.admin')
    async def delete_project(self, project_key: str) -> ToolResult:
        """Permanently delete a project. Admin only."""
        ...
```

---

## 9. Integration Points

### 9.1 `AbstractToolkit.get_tools()`

Layer 1 enforcement. When a `PermissionContext` is provided, `get_tools()` delegates filtering to the resolver. Without a context, all tools are returned (backward-compatible behavior).

```python
# In AbstractToolkit
async def get_tools(
    self,
    permission_context: Optional[PermissionContext] = None,
    resolver: Optional[AbstractPermissionResolver] = None,
) -> List[AbstractTool]:
    all_tools = self._generate_all_tools()
    if permission_context is None or resolver is None:
        return all_tools  # backward compat — no filtering
    return await resolver.filter_tools(permission_context, all_tools)
```

### 9.2 `AbstractTool.execute()`

Layer 2 enforcement. Even if a tool slips through (e.g. registered manually without filtering), `execute()` checks permissions before calling `_execute()`. Returns a structured `ToolResult` rather than raising an exception.

```python
# In AbstractTool
async def execute(self, *args, **kwargs) -> ToolResult:
    # ── Permission check (Layer 2 safety net) ────────────────────────────
    pctx     = kwargs.pop('_permission_context', None)
    resolver = kwargs.pop('_resolver', None)

    if pctx is not None and resolver is not None:
        required = getattr(self, '_required_permissions', set())
        allowed  = await resolver.can_execute(pctx, self.name, required)
        if not allowed:
            self.logger.warning(
                f"Permission denied: user={pctx.user_id} "
                f"tool={self.name} required={required}"
            )
            return ToolResult(
                success=False,
                status='forbidden',
                error=f"Permission denied: '{self.name}' requires {required}",
                result=None,
            )
    # ── Normal execution ─────────────────────────────────────────────────
    validated_args = self.validate_args(**kwargs)
    result = await self._execute(**validated_args.model_dump())
    ...
```

### 9.3 `ToolManager` — Resolver Injection

The `ToolManager` is the injection point for the resolver. A single resolver instance is shared across all tool dispatches within an agent session.

```python
class ToolManager:

    def __init__(
        self,
        resolver: Optional[AbstractPermissionResolver] = None,
        **kwargs
    ):
        self._resolver = resolver  # None = no permission enforcement
        ...

    def set_resolver(self, resolver: AbstractPermissionResolver) -> None:
        """Swap the resolver at runtime (e.g. after auth upgrade)."""
        self._resolver = resolver

    async def execute_tool(
        self,
        tool_name: str,
        permission_context: Optional[PermissionContext] = None,
        **kwargs
    ) -> ToolResult:
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(success=False, status='not_found', ...)
        return await tool.execute(
            _permission_context=permission_context,
            _resolver=self._resolver,
            **kwargs
        )
```

---

## 10. Execution Flow

```
Session init
  └── UserSession { user_id, tenant_id, roles: frozenset }
        └── PermissionContext(session)

Agent init
  ├── ToolManager(resolver=DefaultPermissionResolver(hierarchy))
  └── For each Toolkit:
        toolkit.get_tools(permission_context, resolver)
          └── resolver.filter_tools()          ← Layer 1: LLM never sees forbidden tools
                └── resolver.can_execute() per tool
                      └── _expand_cached(roles) & required_permissions

LLM requests tool call
  └── ToolManager.execute_tool(name, permission_context, **args)
        └── AbstractTool.execute(_permission_context, _resolver, **args)
              └── resolver.can_execute()        ← Layer 2: final safety net
                    ├── DENY  → ToolResult(status='forbidden')
                    └── ALLOW → _execute(**validated_args)
```

---

## 11. Open Questions

### 11.1 Argument-Level Permissions (ABAC)

The current design is RBAC at the tool level. A future extension could support Attribute-Based Access Control where the permission check also inspects the call arguments. Example: "user can `create_issue` only in projects they own."

This would require passing `kwargs` into `can_execute()`, and resolvers that understand domain-specific argument semantics. Out of scope for v0.1 but the interface is designed to accommodate it: `can_execute()` signature can be extended with `**call_kwargs`.

`navigator-auth` have a module for defining ABAC rules, with policies and PDP, for future extension we can use it to define more granular permissions.

### 11.2 Audit Logging

Both denial and grant events should be logged with `user_id`, `tenant_id`, `tool_name`, `required_permissions`, and `request_id`. The `request_id` on `PermissionContext` enables correlation with upstream HTTP request traces. A hook (`on_grant`, `on_deny`) on the resolver interface would allow implementations to emit structured audit events.

### 11.3 Permission Context Propagation in AgentCrew

When agents spawn sub-agents (AgentCrew / A2A), the `PermissionContext` must propagate downstream. A sub-agent should never have more permissions than its parent. This requires a delegation protocol — likely the A2A communication spec will define how context is forwarded.

---

## 12. Implementation Plan

| # | Task | Component | Priority |
|---|---|---|---|
| 1 | Define `UserSession` and `PermissionContext` dataclasses | `parrot/auth/permission.py` | P0 |
| 2 | Implement `AbstractPermissionResolver` ABC | `parrot/auth/resolver.py` | P0 |
| 3 | Implement `DefaultPermissionResolver` with LRU cache | `parrot/auth/resolver.py` | P0 |
| 4 | Implement `@requires_permission` decorator | `parrot/tools/decorators.py` | P0 |
| 5 | Update `AbstractTool.execute()` with Layer 2 check | `parrot/tools/abstract.py` | P0 |
| 6 | Update `AbstractToolkit.get_tools()` with Layer 1 filter | `parrot/tools/toolkit.py` | P0 |
| 7 | Update `ToolManager` to accept and propagate resolver | `parrot/tools/manager.py` | P0 |
| 8 | Annotate `JiraToolkit` methods with `@requires_permission` | `parrot/toolkits/jira.py` | P1 |
| 9 | Write unit tests for resolver and decorator | `tests/test_permissions.py` | P1 |
| 10 | Implement `RedisTenantPermissionResolver` | `parrot/auth/redis_resolver.py` | P2 |
| 11 | Audit logging hooks on `AbstractPermissionResolver` | `parrot/auth/resolver.py` | P2 |
| 12 | `PermissionContext` propagation in AgentCrew / A2A | `parrot/agents/crew.py` | P3 |