# TASK-060: Permission Resolver

**Feature**: Granular Permissions System for Tools & Toolkits
**Spec**: `sdd/specs/granular-permission-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-059
**Assigned-to**: unassigned

---

## Context

> This task implements Modules 2 and 3 from the spec: Abstract Permission Resolver and Default Permission Resolver.

The resolver is the single point of truth for "can this user execute this tool?" It is designed to be injectable — different deployments can provide different implementations.

---

## Scope

- Implement `AbstractPermissionResolver` ABC with `can_execute()` and `filter_tools()`
- Implement `DefaultPermissionResolver` with RBAC hierarchy and LRU caching
- Implement role expansion algorithm (DAG traversal)
- Write unit tests for resolver logic

**NOT in scope**:
- Redis-backed resolver (P2 follow-up)
- Audit logging hooks (P2 follow-up)
- Integration with AbstractTool/Toolkit

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/auth/resolver.py` | CREATE | AbstractPermissionResolver and DefaultPermissionResolver |
| `parrot/auth/__init__.py` | MODIFY | Add resolver exports |
| `tests/auth/test_resolver.py` | CREATE | Unit tests for resolvers |

---

## Implementation Notes

### Pattern to Follow
```python
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Dict, Set, Optional, List
from .permission import PermissionContext


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
        tools: List,
    ) -> List:
        """Return subset of tools the user is allowed to execute."""
        allowed = []
        for tool in tools:
            perms = getattr(tool, '_required_permissions', set())
            if await self.can_execute(context, tool.name, perms):
                allowed.append(tool)
        return allowed


class DefaultPermissionResolver(AbstractPermissionResolver):
    """Reference RBAC implementation with LRU-cached role expansion."""

    def __init__(
        self,
        role_hierarchy: Optional[Dict[str, Set[str]]] = None,
        cache_size: int = 256,
    ):
        self._hierarchy = role_hierarchy or {}
        self._expand_cached = lru_cache(maxsize=cache_size)(self._expand_roles)

    def _expand_roles(self, roles: frozenset) -> frozenset:
        """Expand roles to all implicitly granted permissions."""
        expanded = set(roles)
        queue = list(roles)
        while queue:
            role = queue.pop()
            implied = self._hierarchy.get(role, set())
            new = implied - expanded
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

### Key Constraints
- `can_execute()` returns `True` for empty `required_permissions` (unrestricted tools)
- Use `frozenset` for cache key compatibility
- Hierarchy expansion uses BFS/DFS traversal
- `filter_tools()` has default implementation calling `can_execute()` per tool

### Role Hierarchy Example
```python
JIRA_ROLE_HIERARCHY = {
    'jira.admin': {'jira.manage', 'jira.write', 'jira.read'},
    'jira.manage': {'jira.write', 'jira.read'},
    'jira.write': {'jira.read'},
    'jira.read': set(),
}
```

### References in Codebase
- `parrot/tools/abstract.py` — ABC pattern
- `parrot/interfaces/` — interface patterns

---

## Acceptance Criteria

- [ ] `AbstractPermissionResolver` is ABC with `can_execute()` and `filter_tools()`
- [ ] `DefaultPermissionResolver` implements RBAC with hierarchy
- [ ] Role expansion handles transitive permissions
- [ ] LRU cache caches expanded role sets
- [ ] Unrestricted tools (empty required_permissions) always allowed
- [ ] Unit tests pass: `pytest tests/auth/test_resolver.py -v`
- [ ] Import works: `from parrot.auth import AbstractPermissionResolver, DefaultPermissionResolver`

---

## Test Specification

```python
# tests/auth/test_resolver.py
import pytest
from parrot.auth.permission import UserSession, PermissionContext
from parrot.auth.resolver import DefaultPermissionResolver


@pytest.fixture
def hierarchy():
    return {
        'admin': {'manage', 'write', 'read'},
        'manage': {'write', 'read'},
        'write': {'read'},
        'read': set(),
    }


@pytest.fixture
def resolver(hierarchy):
    return DefaultPermissionResolver(role_hierarchy=hierarchy)


@pytest.fixture
def admin_context():
    session = UserSession(user_id="admin", tenant_id="t1", roles=frozenset({'admin'}))
    return PermissionContext(session=session)


@pytest.fixture
def reader_context():
    session = UserSession(user_id="reader", tenant_id="t1", roles=frozenset({'read'}))
    return PermissionContext(session=session)


class TestDefaultPermissionResolver:
    @pytest.mark.asyncio
    async def test_unrestricted_tool_always_allowed(self, resolver, reader_context):
        """Empty required_permissions returns True."""
        result = await resolver.can_execute(reader_context, "search", set())
        assert result is True

    @pytest.mark.asyncio
    async def test_direct_role_match(self, resolver, reader_context):
        """User with direct role is allowed."""
        result = await resolver.can_execute(reader_context, "view", {'read'})
        assert result is True

    @pytest.mark.asyncio
    async def test_hierarchy_expansion(self, resolver, admin_context):
        """Admin has all implied permissions."""
        assert await resolver.can_execute(admin_context, "read_op", {'read'}) is True
        assert await resolver.can_execute(admin_context, "write_op", {'write'}) is True
        assert await resolver.can_execute(admin_context, "manage_op", {'manage'}) is True

    @pytest.mark.asyncio
    async def test_deny_insufficient_role(self, resolver, reader_context):
        """Reader cannot access write-only tools."""
        result = await resolver.can_execute(reader_context, "create", {'write'})
        assert result is False

    @pytest.mark.asyncio
    async def test_or_semantics(self, resolver, reader_context):
        """Any matching permission grants access (OR logic)."""
        result = await resolver.can_execute(reader_context, "multi", {'read', 'write'})
        assert result is True  # has 'read'

    def test_cache_hit(self, resolver):
        """LRU cache returns same expansion."""
        roles = frozenset({'admin'})
        exp1 = resolver._expand_cached(roles)
        exp2 = resolver._expand_cached(roles)
        assert exp1 is exp2  # same object from cache


class TestFilterTools:
    @pytest.mark.asyncio
    async def test_filters_unauthorized(self, resolver, reader_context):
        """Unauthorized tools are filtered out."""
        class MockTool:
            def __init__(self, name, perms):
                self.name = name
                self._required_permissions = perms

        tools = [
            MockTool("search", set()),  # unrestricted
            MockTool("view", {'read'}),  # allowed
            MockTool("create", {'write'}),  # denied
        ]

        filtered = await resolver.filter_tools(reader_context, tools)
        names = [t.name for t in filtered]
        assert "search" in names
        assert "view" in names
        assert "create" not in names
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-060-permission-resolver.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
