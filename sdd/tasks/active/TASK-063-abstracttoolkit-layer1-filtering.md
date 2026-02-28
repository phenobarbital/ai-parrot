# TASK-063: AbstractToolkit Layer 1 Filtering

**Feature**: Granular Permissions System for Tools & Toolkits
**Spec**: `sdd/specs/granular-permission-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-059, TASK-060
**Assigned-to**: unassigned

---

## Context

> This task implements Module 6 from the spec: AbstractToolkit Layer 1 Filtering.

Layer 1 is the preventive enforcement layer. When a `PermissionContext` is provided, `get_tools()` delegates filtering to the resolver. Unauthorized tools are invisible to the LLM — they never appear in the tool list.

---

## Scope

- Modify `AbstractToolkit.get_tools()` to accept optional `permission_context` and `resolver`
- Filter tools using `resolver.filter_tools()` when context provided
- Maintain backward compatibility (no context = no filtering)
- Write unit tests for filtering behavior

**NOT in scope**:
- Layer 2 enforcement (TASK-062)
- ToolManager changes (TASK-064)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/toolkit.py` | MODIFY | Add filtering in `get_tools()` |
| `tests/tools/test_toolkit_permissions.py` | CREATE | Unit tests for Layer 1 |

---

## Implementation Notes

### Pattern to Follow
```python
# In AbstractToolkit
from typing import Optional, List
from parrot.auth.permission import PermissionContext
from parrot.auth.resolver import AbstractPermissionResolver

async def get_tools(
    self,
    permission_context: Optional[PermissionContext] = None,
    resolver: Optional[AbstractPermissionResolver] = None,
) -> List[AbstractTool]:
    """Get all tools from this toolkit, optionally filtered by permissions.

    Args:
        permission_context: User context for permission filtering.
        resolver: Permission resolver for checking access.

    Returns:
        List of tools. If context and resolver provided, filtered by permission.
        Otherwise, all tools returned (backward compatible).
    """
    all_tools = self._generate_all_tools()  # existing method

    if permission_context is None or resolver is None:
        return all_tools  # backward compat — no filtering

    return await resolver.filter_tools(permission_context, all_tools)
```

### Key Constraints
- `get_tools()` signature must accept optional `permission_context` and `resolver`
- Both must be provided for filtering to occur
- Return all tools if either is None (backward compatible)
- Use `resolver.filter_tools()` for actual filtering logic
- Must work with existing toolkit implementations

### References in Codebase
- `parrot/tools/toolkit.py` — current `get_tools()` implementation
- `parrot/tools/aws/ecs.py` — example toolkit

---

## Acceptance Criteria

- [ ] `get_tools()` accepts optional `permission_context` and `resolver` params
- [ ] With both params, tools are filtered by resolver
- [ ] Without params, all tools returned (backward compat)
- [ ] Filtered list only contains tools user is allowed to execute
- [ ] Unit tests pass: `pytest tests/tools/test_toolkit_permissions.py -v`
- [ ] No linting errors: `ruff check parrot/tools/toolkit.py`
- [ ] Existing toolkit tests still pass

---

## Test Specification

```python
# tests/tools/test_toolkit_permissions.py
import pytest
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.decorators import requires_permission
from parrot.auth.permission import UserSession, PermissionContext
from parrot.auth.resolver import DefaultPermissionResolver


class TestToolkit(AbstractToolkit):
    """Test toolkit with mixed permissions."""

    async def public_search(self, query: str) -> str:
        """Search available to all users."""
        return f"searched: {query}"

    @requires_permission('read')
    async def read_data(self, id: str) -> str:
        """Read requires read permission."""
        return f"data: {id}"

    @requires_permission('write')
    async def write_data(self, id: str, value: str) -> str:
        """Write requires write permission."""
        return f"wrote: {id}={value}"

    @requires_permission('admin')
    async def admin_action(self) -> str:
        """Admin only action."""
        return "admin done"


@pytest.fixture
def resolver():
    return DefaultPermissionResolver(role_hierarchy={
        'admin': {'write', 'read'},
        'write': {'read'},
        'read': set(),
    })


@pytest.fixture
def admin_context():
    session = UserSession(user_id="admin", tenant_id="t1", roles=frozenset({'admin'}))
    return PermissionContext(session=session)


@pytest.fixture
def reader_context():
    session = UserSession(user_id="reader", tenant_id="t1", roles=frozenset({'read'}))
    return PermissionContext(session=session)


@pytest.fixture
def toolkit():
    return TestToolkit()


class TestLayer1Filtering:
    @pytest.mark.asyncio
    async def test_no_context_returns_all(self, toolkit):
        """Without context, all tools returned."""
        tools = await toolkit.get_tools()
        tool_names = [t.name for t in tools]

        assert 'public_search' in tool_names
        assert 'read_data' in tool_names
        assert 'write_data' in tool_names
        assert 'admin_action' in tool_names

    @pytest.mark.asyncio
    async def test_admin_sees_all(self, toolkit, resolver, admin_context):
        """Admin sees all tools."""
        tools = await toolkit.get_tools(
            permission_context=admin_context,
            resolver=resolver
        )
        tool_names = [t.name for t in tools]

        assert 'public_search' in tool_names
        assert 'read_data' in tool_names
        assert 'write_data' in tool_names
        assert 'admin_action' in tool_names

    @pytest.mark.asyncio
    async def test_reader_filtered(self, toolkit, resolver, reader_context):
        """Reader only sees public and read tools."""
        tools = await toolkit.get_tools(
            permission_context=reader_context,
            resolver=resolver
        )
        tool_names = [t.name for t in tools]

        assert 'public_search' in tool_names  # unrestricted
        assert 'read_data' in tool_names      # has read permission
        assert 'write_data' not in tool_names  # no write permission
        assert 'admin_action' not in tool_names  # no admin permission

    @pytest.mark.asyncio
    async def test_only_context_no_filter(self, toolkit, admin_context):
        """Only context without resolver = no filtering."""
        tools = await toolkit.get_tools(permission_context=admin_context)
        # Should return all tools
        assert len(tools) == 4

    @pytest.mark.asyncio
    async def test_only_resolver_no_filter(self, toolkit, resolver):
        """Only resolver without context = no filtering."""
        tools = await toolkit.get_tools(resolver=resolver)
        # Should return all tools
        assert len(tools) == 4

    @pytest.mark.asyncio
    async def test_empty_roles_sees_only_public(self, toolkit, resolver):
        """User with no roles sees only unrestricted tools."""
        session = UserSession(user_id="anon", tenant_id="t1", roles=frozenset())
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(
            permission_context=ctx,
            resolver=resolver
        )
        tool_names = [t.name for t in tools]

        assert tool_names == ['public_search']
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-063-abstracttoolkit-layer1-filtering.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
