# TASK-066: Permission System Integration Tests

**Feature**: Granular Permissions System for Tools & Toolkits
**Spec**: `sdd/specs/granular-permission-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-059, TASK-060, TASK-061, TASK-062, TASK-063, TASK-064
**Assigned-to**: unassigned

---

## Context

> This task implements Module 9 from the spec: Unit Tests.

Write comprehensive integration tests that verify the full permission flow works end-to-end: session creation → context building → tool filtering → execution enforcement.

---

## Scope

- Write integration tests for full permission flow
- Test Layer 1 + Layer 2 working together
- Test backward compatibility (no context = no enforcement)
- Test edge cases (empty roles, unknown permissions, etc.)
- Create reusable test fixtures

**NOT in scope**:
- Redis resolver tests (P2)
- AgentCrew propagation tests (P3)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/tools/test_permissions.py` | CREATE | Integration tests |
| `tests/conftest.py` | MODIFY | Add shared permission fixtures |

---

## Implementation Notes

### Test Scenarios
1. **Full flow - denied**: User without role → tool filtered out → execution denied
2. **Full flow - allowed**: User with role → tool visible → execution succeeds
3. **Backward compat**: No context → all tools visible → execution succeeds
4. **Hierarchy**: Admin role → all implied permissions work
5. **OR semantics**: Multiple permissions → any match allows

### Fixtures to Create
```python
# tests/conftest.py additions

@pytest.fixture
def jira_hierarchy():
    return {
        'jira.admin': {'jira.manage', 'jira.write', 'jira.read'},
        'jira.manage': {'jira.write', 'jira.read'},
        'jira.write': {'jira.read'},
        'jira.read': set(),
    }


@pytest.fixture
def permission_resolver(jira_hierarchy):
    from parrot.auth.resolver import DefaultPermissionResolver
    return DefaultPermissionResolver(role_hierarchy=jira_hierarchy)


@pytest.fixture
def admin_session():
    from parrot.auth.permission import UserSession
    return UserSession(
        user_id="admin-user",
        tenant_id="test-tenant",
        roles=frozenset({'jira.admin'})
    )


@pytest.fixture
def reader_session():
    from parrot.auth.permission import UserSession
    return UserSession(
        user_id="reader-user",
        tenant_id="test-tenant",
        roles=frozenset({'jira.read'})
    )
```

### References in Codebase
- `tests/` — existing test patterns
- `tests/conftest.py` — shared fixtures

---

## Acceptance Criteria

- [ ] Integration test for full deny flow (filter + execute)
- [ ] Integration test for full allow flow
- [ ] Integration test for backward compatibility
- [ ] Integration test for role hierarchy expansion
- [ ] Integration test for OR permission semantics
- [ ] Shared fixtures added to conftest.py
- [ ] All tests pass: `pytest tests/tools/test_permissions.py -v`

---

## Test Specification

```python
# tests/tools/test_permissions.py
import pytest
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager
from parrot.tools.decorators import requires_permission
from parrot.auth.permission import UserSession, PermissionContext
from parrot.auth.resolver import DefaultPermissionResolver


# ── Test Toolkit ────────────────────────────────────────────────────────────

class IntegrationToolkit(AbstractToolkit):
    """Toolkit for integration testing."""

    async def public_action(self) -> str:
        """Available to everyone."""
        return "public"

    @requires_permission('read')
    async def read_action(self) -> str:
        """Requires read permission."""
        return "read"

    @requires_permission('write')
    async def write_action(self) -> str:
        """Requires write permission."""
        return "write"

    @requires_permission('admin')
    async def admin_action(self) -> str:
        """Requires admin permission."""
        return "admin"

    @requires_permission('read', 'special')
    async def or_action(self) -> str:
        """Requires read OR special permission."""
        return "or"


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def hierarchy():
    return {
        'admin': {'write', 'read'},
        'write': {'read'},
        'read': set(),
    }


@pytest.fixture
def resolver(hierarchy):
    return DefaultPermissionResolver(role_hierarchy=hierarchy)


@pytest.fixture
def toolkit():
    return IntegrationToolkit()


# ── Integration Tests ───────────────────────────────────────────────────────

class TestFullFlowDeny:
    """Test complete denial flow: filter + execute."""

    @pytest.mark.asyncio
    async def test_layer1_filters_unauthorized_tool(self, toolkit, resolver):
        """Layer 1: unauthorized tools filtered from list."""
        session = UserSession(user_id="reader", tenant_id="t1", roles=frozenset({'read'}))
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        assert 'public_action' in tool_names
        assert 'read_action' in tool_names
        assert 'write_action' not in tool_names
        assert 'admin_action' not in tool_names

    @pytest.mark.asyncio
    async def test_layer2_blocks_if_slips_through(self, resolver):
        """Layer 2: direct execution still blocked."""
        session = UserSession(user_id="reader", tenant_id="t1", roles=frozenset({'read'}))
        ctx = PermissionContext(session=session)

        @requires_permission('admin')
        class RestrictedTool(AbstractTool):
            name = "restricted"
            description = "Admin only"
            async def _execute(self, **kwargs):
                return ToolResult(success=True, status="success", result="should not reach")

        tool = RestrictedTool()
        result = await tool.execute(_permission_context=ctx, _resolver=resolver)

        assert result.success is False
        assert result.status == 'forbidden'


class TestFullFlowAllow:
    """Test complete allow flow: filter + execute."""

    @pytest.mark.asyncio
    async def test_admin_sees_all_tools(self, toolkit, resolver):
        """Admin sees all tools in filtered list."""
        session = UserSession(user_id="admin", tenant_id="t1", roles=frozenset({'admin'}))
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        assert len(tool_names) >= 4  # all regular tools
        assert 'admin_action' in tool_names
        assert 'write_action' in tool_names

    @pytest.mark.asyncio
    async def test_admin_can_execute_all(self, toolkit, resolver):
        """Admin can execute any tool."""
        session = UserSession(user_id="admin", tenant_id="t1", roles=frozenset({'admin'}))
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        admin_tool = next(t for t in tools if t.name == 'admin_action')

        result = await admin_tool.execute(_permission_context=ctx, _resolver=resolver)
        assert result.success is True


class TestBackwardCompatibility:
    """Test no context = no enforcement."""

    @pytest.mark.asyncio
    async def test_no_context_returns_all_tools(self, toolkit):
        """Without context, all tools returned."""
        tools = await toolkit.get_tools()
        assert len(tools) >= 5  # all tools including restricted

    @pytest.mark.asyncio
    async def test_no_context_executes_restricted(self):
        """Without context, restricted tools execute."""
        @requires_permission('super_admin')
        class SuperRestrictedTool(AbstractTool):
            name = "super_restricted"
            description = "Super admin only"
            async def _execute(self, **kwargs):
                return ToolResult(success=True, status="success", result="executed")

        tool = SuperRestrictedTool()
        result = await tool.execute()  # no context

        assert result.success is True
        assert result.result == "executed"


class TestHierarchyExpansion:
    """Test role hierarchy works correctly."""

    @pytest.mark.asyncio
    async def test_write_implies_read(self, toolkit, resolver):
        """User with write can access read tools."""
        session = UserSession(user_id="writer", tenant_id="t1", roles=frozenset({'write'}))
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        assert 'read_action' in tool_names  # implied by write
        assert 'write_action' in tool_names  # direct
        assert 'admin_action' not in tool_names  # higher level


class TestOrSemantics:
    """Test OR permission matching."""

    @pytest.mark.asyncio
    async def test_or_matches_first(self, toolkit, resolver):
        """Tool with OR permissions - first matches."""
        session = UserSession(user_id="reader", tenant_id="t1", roles=frozenset({'read'}))
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        assert 'or_action' in tool_names  # has 'read' which matches

    @pytest.mark.asyncio
    async def test_or_matches_second(self, toolkit, resolver):
        """Tool with OR permissions - second matches."""
        session = UserSession(user_id="special", tenant_id="t1", roles=frozenset({'special'}))
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        assert 'or_action' in tool_names  # has 'special' which matches


class TestToolManagerIntegration:
    """Test ToolManager with permission system."""

    @pytest.mark.asyncio
    async def test_manager_enforces_permissions(self, resolver):
        """ToolManager propagates context for enforcement."""
        session = UserSession(user_id="reader", tenant_id="t1", roles=frozenset({'read'}))
        ctx = PermissionContext(session=session)

        @requires_permission('admin')
        class AdminTool(AbstractTool):
            name = "admin_tool"
            description = "Admin only"
            async def _execute(self, **kwargs):
                return ToolResult(success=True, status="success", result="admin")

        manager = ToolManager(resolver=resolver)
        manager._tools = {'admin_tool': AdminTool()}

        result = await manager.execute_tool('admin_tool', permission_context=ctx)

        assert result.success is False
        assert result.status == 'forbidden'
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-066-permission-integration-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
