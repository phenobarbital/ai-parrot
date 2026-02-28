# Feature Specification: Granular Permissions System for Tools & Toolkits

**Feature ID**: FEAT-014
**Date**: 2026-02-28
**Author**: claude-session
**Status**: approved
**Target version**: 1.x.x
**Proposal**: `sdd/proposals/granular-permission.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot exposes LLM agents to collections of tools via Toolkits. At runtime, the LLM receives the full list of available tools in its context window and can call any of them. System-prompt enforcement ("only use tools the user is allowed to") is a guideline, not a contract — the model can deviate.

This creates a security gap where:
1. Users may see and attempt to use tools they shouldn't have access to
2. LLM prompt injection could bypass "soft" permission guidelines
3. Multi-tenant deployments have no isolation between tenant permissions
4. Audit trails cannot distinguish between authorized and unauthorized attempts

### Goals
- Implement enforcement-first permission system at Python execution layer
- Defense in depth: preventive filtering (Layer 1) + reactive enforcement (Layer 2)
- Lightweight sessions — user identity and roles only, no expanded permission maps
- Declarative tool permissions via `@requires_permission` decorator
- Pluggable resolver — injectable `AbstractPermissionResolver` supports custom logic
- Multi-tenant ready — resolver receives tenant context
- Zero breaking changes — backward-compatible; tools without annotations work unchanged

### Non-Goals (explicitly out of scope)
- Argument-level permissions (ABAC) — designed for but not implemented in v1
- Audit logging infrastructure (hooks defined, implementation P2)
- Permission context propagation in AgentCrew/A2A (P3)
- UI for permission management

---

## 2. Architectural Design

### Overview

The system uses a defense-in-depth approach with two independent enforcement layers:

| Layer | Where | What it does | When it fires |
|---|---|---|---|
| **1 — Preventive** | `AbstractToolkit.get_tools()` | Filters tool list before LLM sees it. Unauthorized tools are invisible. | Agent startup / session init |
| **2 — Reactive** | `AbstractTool.execute()` | Rejects execution even if LLM requests a tool it shouldn't call. | Every tool call attempt |

### Component Diagram
```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Session Layer                                  │
│  ┌──────────────┐     ┌───────────────────┐                            │
│  │ UserSession  │────▶│ PermissionContext │                            │
│  │ user_id      │     │ session           │                            │
│  │ tenant_id    │     │ request_id        │                            │
│  │ roles        │     │ extra             │                            │
│  └──────────────┘     └─────────┬─────────┘                            │
└─────────────────────────────────┼───────────────────────────────────────┘
                                  │
┌─────────────────────────────────┼───────────────────────────────────────┐
│                       Permission Resolver                               │
│                                 ▼                                       │
│  ┌──────────────────────────────────────────────────────────────┐      │
│  │            AbstractPermissionResolver                         │      │
│  │  ┌─────────────────┐  ┌─────────────────┐                    │      │
│  │  │ can_execute()   │  │ filter_tools()  │                    │      │
│  │  └─────────────────┘  └─────────────────┘                    │      │
│  └──────────────────────────────────────────────────────────────┘      │
│                                 │                                       │
│         ┌───────────────────────┼───────────────────────┐              │
│         ▼                       ▼                       ▼              │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐     │
│  │Default       │    │RedisTenant       │    │Custom            │     │
│  │Resolver      │    │Resolver          │    │Resolver          │     │
│  │(LRU cache)   │    │(Redis cache)     │    │(user-defined)    │     │
│  └──────────────┘    └──────────────────┘    └──────────────────┘     │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────┼───────────────────────────────────────┐
│                       Enforcement Points                                │
│                                 │                                       │
│  ┌──────────────────────────────┼──────────────────────────────┐       │
│  │ ToolManager                  │                              │       │
│  │  ├── resolver: AbstractPermissionResolver                   │       │
│  │  └── execute_tool() ─────────┼──────────────────────────────│───┐   │
│  └──────────────────────────────┼──────────────────────────────┘   │   │
│                                 │                                   │   │
│  ┌──────────────────────────────▼──────────────────────────────┐   │   │
│  │ AbstractToolkit.get_tools()                                 │   │   │
│  │   └── resolver.filter_tools() ◀── Layer 1: Filter tools    │   │   │
│  └─────────────────────────────────────────────────────────────┘   │   │
│                                                                     │   │
│  ┌──────────────────────────────────────────────────────────────┐  │   │
│  │ AbstractTool.execute()                     ◀─────────────────┼──┘   │
│  │   └── resolver.can_execute() ◀── Layer 2: Enforce per-call  │      │
│  └──────────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractTool` | modifies | Add Layer 2 check in `execute()` |
| `AbstractToolkit` | modifies | Add filtering in `get_tools()` |
| `ToolManager` | modifies | Accept and propagate resolver |
| `parrot/tools/decorators.py` | extends | Add `@requires_permission` decorator |

### Data Models

```python
from dataclasses import dataclass, field
from typing import Optional, Set
from abc import ABC, abstractmethod


@dataclass(frozen=True)
class UserSession:
    """Minimal session carrying identity and role claims."""
    user_id: str
    tenant_id: str
    roles: frozenset[str]  # e.g. frozenset({'jira.manage', 'github.read'})
    metadata: dict = field(default_factory=dict)


@dataclass
class PermissionContext:
    """Request-scoped wrapper grouping session with extra context."""
    session: UserSession
    request_id: Optional[str] = None
    extra: dict = field(default_factory=dict)

    @property
    def user_id(self) -> str:
        return self.session.user_id

    @property
    def tenant_id(self) -> str:
        return self.session.tenant_id

    @property
    def roles(self) -> frozenset[str]:
        return self.session.roles


class AbstractPermissionResolver(ABC):
    """Pluggable resolver for tool permission checks."""

    @abstractmethod
    async def can_execute(
        self,
        context: PermissionContext,
        tool_name: str,
        required_permissions: Set[str],
    ) -> bool:
        """Return True if user in context may execute the tool."""
        ...

    async def filter_tools(
        self,
        context: PermissionContext,
        tools: list,
    ) -> list:
        """Return subset of tools the user is allowed to execute."""
        allowed = []
        for tool in tools:
            perms = getattr(tool, '_required_permissions', set())
            if await self.can_execute(context, tool.name, perms):
                allowed.append(tool)
        return allowed
```

### New Public Interfaces

```python
# Decorator for annotating permissions
def requires_permission(*permissions: str):
    """
    Annotate a toolkit method or AbstractTool class with required permissions.

    Usage:
        @requires_permission('jira.manage')
        async def delete_sprint(self, sprint_id: str): ...

    Semantics: ANY of the listed permissions grants access (OR logic).
    """
    def decorator(obj):
        obj._required_permissions = frozenset(permissions)
        return obj
    return decorator


# Default resolver with RBAC hierarchy
class DefaultPermissionResolver(AbstractPermissionResolver):
    """Reference implementation with LRU-cached role expansion."""

    def __init__(
        self,
        role_hierarchy: dict[str, set[str]] = None,
        cache_size: int = 256,
    ): ...

    async def can_execute(
        self,
        context: PermissionContext,
        tool_name: str,
        required_permissions: Set[str],
    ) -> bool: ...
```

---

## 3. Module Breakdown

### Module 1: Permission Data Models
- **Path**: `parrot/auth/permission.py`
- **Responsibility**: Define `UserSession` and `PermissionContext` dataclasses
- **Depends on**: None

### Module 2: Abstract Permission Resolver
- **Path**: `parrot/auth/resolver.py`
- **Responsibility**: Define `AbstractPermissionResolver` ABC
- **Depends on**: Module 1

### Module 3: Default Permission Resolver
- **Path**: `parrot/auth/resolver.py`
- **Responsibility**: Implement `DefaultPermissionResolver` with RBAC hierarchy and LRU cache
- **Depends on**: Module 1, Module 2

### Module 4: Requires Permission Decorator
- **Path**: `parrot/tools/decorators.py`
- **Responsibility**: Implement `@requires_permission` decorator
- **Depends on**: None

### Module 5: AbstractTool Layer 2 Enforcement
- **Path**: `parrot/tools/abstract.py`
- **Responsibility**: Add permission check in `execute()` method
- **Depends on**: Module 1, Module 2

### Module 6: AbstractToolkit Layer 1 Filtering
- **Path**: `parrot/tools/toolkit.py`
- **Responsibility**: Add filtering in `get_tools()` method
- **Depends on**: Module 1, Module 2

### Module 7: ToolManager Resolver Injection
- **Path**: `parrot/tools/manager.py`
- **Responsibility**: Accept resolver, propagate context during dispatch
- **Depends on**: Module 1, Module 2

### Module 8: JiraToolkit Permission Annotations
- **Path**: `parrot/tools/jiratoolkit.py`
- **Responsibility**: Annotate methods with `@requires_permission`
- **Depends on**: Module 4

### Module 9: Unit Tests
- **Path**: `tests/tools/test_permissions.py`
- **Responsibility**: Test resolver, decorator, enforcement layers
- **Depends on**: Modules 1-7

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_user_session_immutable` | Module 1 | UserSession is frozen dataclass |
| `test_user_session_roles_frozenset` | Module 1 | Roles are frozenset, hashable |
| `test_permission_context_properties` | Module 1 | Context proxies session properties |
| `test_resolver_unrestricted_tool` | Module 3 | Empty required_permissions returns True |
| `test_resolver_role_match` | Module 3 | User with matching role is allowed |
| `test_resolver_role_hierarchy` | Module 3 | Hierarchy expands roles correctly |
| `test_resolver_cache_hit` | Module 3 | LRU cache returns same expansion |
| `test_decorator_sets_attribute` | Module 4 | Decorator sets `_required_permissions` |
| `test_decorator_or_semantics` | Module 4 | Multiple permissions use OR logic |
| `test_execute_layer2_deny` | Module 5 | Execute returns forbidden on deny |
| `test_execute_layer2_allow` | Module 5 | Execute proceeds on allow |
| `test_get_tools_layer1_filter` | Module 6 | Unauthorized tools are filtered out |
| `test_get_tools_backward_compat` | Module 6 | No context = no filtering |
| `test_manager_propagates_context` | Module 7 | Context passed through to execute |

### Integration Tests
| Test | Description |
|---|---|
| `test_full_flow_deny` | User without role tries tool → forbidden |
| `test_full_flow_allow` | User with role executes tool → success |
| `test_jira_toolkit_filtered` | JiraToolkit tools filtered by role |

### Test Data / Fixtures
```python
@pytest.fixture
def test_hierarchy():
    return {
        'jira.admin': {'jira.manage', 'jira.write', 'jira.read'},
        'jira.manage': {'jira.write', 'jira.read'},
        'jira.write': {'jira.read'},
        'jira.read': set(),
    }


@pytest.fixture
def admin_session():
    return UserSession(
        user_id="admin-1",
        tenant_id="tenant-1",
        roles=frozenset({'jira.admin'})
    )


@pytest.fixture
def reader_session():
    return UserSession(
        user_id="reader-1",
        tenant_id="tenant-1",
        roles=frozenset({'jira.read'})
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `UserSession` is frozen dataclass with `user_id`, `tenant_id`, `roles`
- [ ] `PermissionContext` wraps session with request metadata
- [ ] `AbstractPermissionResolver` ABC defines `can_execute()` and `filter_tools()`
- [ ] `DefaultPermissionResolver` implements RBAC with hierarchy expansion
- [ ] `DefaultPermissionResolver` uses LRU cache for role expansion
- [ ] `@requires_permission` decorator annotates tools with required permissions
- [ ] `AbstractTool.execute()` checks permissions (Layer 2) before `_execute()`
- [ ] `AbstractTool.execute()` returns `ToolResult(status='forbidden')` on deny
- [ ] `AbstractToolkit.get_tools()` filters tools by permission (Layer 1)
- [ ] `AbstractToolkit.get_tools()` without context returns all tools (backward compat)
- [ ] `ToolManager` accepts and propagates resolver
- [ ] At least one toolkit (JiraToolkit) annotated with permissions
- [ ] All unit tests pass: `pytest tests/tools/test_permissions.py -v`
- [ ] No breaking changes to existing unannotated tools

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Use `@dataclass(frozen=True)` for immutable session data
- Use `frozenset` for roles (hashable, cacheable)
- Use `functools.lru_cache` for role expansion caching
- Follow existing decorator patterns in `parrot/tools/decorators.py`
- Use `self.logger.warning()` for permission denials

### Known Risks / Gotchas
- **Cache invalidation**: LRU cache is per-resolver-instance; role changes require new resolver or cache clear
- **Context propagation**: Must ensure context flows through all execution paths
- **Backward compatibility**: Tools without decorator must continue working
- **Performance**: `filter_tools()` is O(n) — consider bulk optimization for large tool sets

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| None | — | No new dependencies required |

### Role Hierarchy Example
```python
# Define per-toolkit or globally
JIRA_ROLE_HIERARCHY = {
    'jira.admin':  {'jira.manage', 'jira.write', 'jira.read'},
    'jira.manage': {'jira.write', 'jira.read'},
    'jira.write':  {'jira.read'},
    'jira.read':   set(),
}
```

### Permission Annotation Example
```python
class JiraToolkit(AbstractToolkit):
    # No decorator — available to all users
    async def search_issues(self, query: str) -> ToolResult:
        ...

    # jira.write — developers and above
    @requires_permission('jira.write')
    async def create_issue(self, project: str, summary: str) -> ToolResult:
        ...

    # jira.manage — team leads and PMs
    @requires_permission('jira.manage')
    async def delete_sprint(self, sprint_id: str) -> ToolResult:
        ...

    # jira.admin — admins only
    @requires_permission('jira.admin')
    async def delete_project(self, project_key: str) -> ToolResult:
        ...
```

---

## 7. Open Questions

- [ ] **ABAC Extension**: Should `can_execute()` signature include `**call_kwargs` for future argument-level checks? — *Owner: architect* — Answer: Yes, design for it but don't implement
- [ ] **Audit hooks**: Should `AbstractPermissionResolver` define `on_grant()` / `on_deny()` hooks? — *Owner: security* — Answer: Define in interface, implement P2
- [ ] **AgentCrew propagation**: How should context propagate to sub-agents? — *Owner: architect* — Answer: P3, separate spec
- [ ] **Redis resolver**: Should `RedisTenantPermissionResolver` be included in v1? — *Owner: platform* — Answer: No, P2 follow-up

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-28 | claude-session | Initial draft from proposal |
