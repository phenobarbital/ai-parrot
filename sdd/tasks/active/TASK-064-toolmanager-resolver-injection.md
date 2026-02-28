# TASK-064: ToolManager Resolver Injection

**Feature**: Granular Permissions System for Tools & Toolkits
**Spec**: `sdd/specs/granular-permission-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-059, TASK-060, TASK-062
**Assigned-to**: unassigned

---

## Context

> This task implements Module 7 from the spec: ToolManager Resolver Injection.

The `ToolManager` is the injection point for the resolver. A single resolver instance is shared across all tool dispatches within an agent session. The manager propagates the `PermissionContext` during tool execution.

---

## Scope

- Modify `ToolManager.__init__()` to accept optional resolver
- Add `set_resolver()` method for runtime resolver swapping
- Modify `execute_tool()` to propagate context and resolver to tool
- Maintain backward compatibility (no resolver = no enforcement)
- Write unit tests for injection and propagation

**NOT in scope**:
- Layer 1 filtering integration (handled by toolkit)
- AgentCrew context propagation (P3)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/manager.py` | MODIFY | Add resolver injection and propagation |
| `tests/tools/test_manager_permissions.py` | CREATE | Unit tests for manager |

---

## Implementation Notes

### Pattern to Follow
```python
from typing import Optional
from parrot.auth.permission import PermissionContext
from parrot.auth.resolver import AbstractPermissionResolver


class ToolManager:

    def __init__(
        self,
        resolver: Optional[AbstractPermissionResolver] = None,
        **kwargs
    ):
        self._resolver = resolver  # None = no permission enforcement
        # ... existing init code ...

    def set_resolver(self, resolver: AbstractPermissionResolver) -> None:
        """Swap the resolver at runtime (e.g., after auth upgrade)."""
        self._resolver = resolver

    @property
    def resolver(self) -> Optional[AbstractPermissionResolver]:
        """Get the current resolver."""
        return self._resolver

    async def execute_tool(
        self,
        tool_name: str,
        permission_context: Optional[PermissionContext] = None,
        **kwargs
    ) -> ToolResult:
        """Execute a tool by name, with optional permission enforcement."""
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(
                success=False,
                status='not_found',
                error=f"Tool '{tool_name}' not found",
                result=None
            )

        return await tool.execute(
            _permission_context=permission_context,
            _resolver=self._resolver,
            **kwargs
        )
```

### Key Constraints
- Resolver is optional — `None` means no enforcement
- `execute_tool()` must pass `_permission_context` and `_resolver` to `tool.execute()`
- `set_resolver()` allows runtime changes (useful for auth upgrades)
- Must not break existing ToolManager usages

### References in Codebase
- `parrot/tools/manager.py` — current ToolManager implementation

---

## Acceptance Criteria

- [ ] `ToolManager.__init__()` accepts optional `resolver` parameter
- [ ] `set_resolver()` method exists for runtime swapping
- [ ] `execute_tool()` accepts optional `permission_context`
- [ ] Context and resolver propagated to `tool.execute()`
- [ ] No resolver = no enforcement (backward compat)
- [ ] Unit tests pass: `pytest tests/tools/test_manager_permissions.py -v`
- [ ] No linting errors: `ruff check parrot/tools/manager.py`
- [ ] Existing ToolManager tests still pass

---

## Test Specification

```python
# tests/tools/test_manager_permissions.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.tools.manager import ToolManager
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.decorators import requires_permission
from parrot.auth.permission import UserSession, PermissionContext
from parrot.auth.resolver import DefaultPermissionResolver


class MockTool(AbstractTool):
    name = "mock_tool"
    description = "Mock tool"

    async def _execute(self, **kwargs):
        return ToolResult(success=True, status="success", result="mock result")


@requires_permission('admin')
class AdminTool(AbstractTool):
    name = "admin_tool"
    description = "Admin only"

    async def _execute(self, **kwargs):
        return ToolResult(success=True, status="success", result="admin result")


@pytest.fixture
def resolver():
    return DefaultPermissionResolver(role_hierarchy={
        'admin': {'write', 'read'},
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


class TestToolManagerInit:
    def test_init_without_resolver(self):
        """Manager can initialize without resolver."""
        manager = ToolManager()
        assert manager.resolver is None

    def test_init_with_resolver(self, resolver):
        """Manager accepts resolver at init."""
        manager = ToolManager(resolver=resolver)
        assert manager.resolver is resolver

    def test_set_resolver(self, resolver):
        """set_resolver swaps resolver at runtime."""
        manager = ToolManager()
        assert manager.resolver is None

        manager.set_resolver(resolver)
        assert manager.resolver is resolver


class TestToolManagerExecution:
    @pytest.mark.asyncio
    async def test_execute_without_context(self):
        """Execute without context runs normally."""
        manager = ToolManager()
        manager._tools = {'mock_tool': MockTool()}

        result = await manager.execute_tool('mock_tool')
        assert result.success is True
        assert result.result == "mock result"

    @pytest.mark.asyncio
    async def test_execute_not_found(self):
        """Execute non-existent tool returns not_found."""
        manager = ToolManager()
        manager._tools = {}

        result = await manager.execute_tool('nonexistent')
        assert result.success is False
        assert result.status == 'not_found'

    @pytest.mark.asyncio
    async def test_execute_with_permission_allowed(self, resolver, admin_context):
        """Admin can execute admin tool."""
        manager = ToolManager(resolver=resolver)
        manager._tools = {'admin_tool': AdminTool()}

        result = await manager.execute_tool(
            'admin_tool',
            permission_context=admin_context
        )
        assert result.success is True
        assert result.result == "admin result"

    @pytest.mark.asyncio
    async def test_execute_with_permission_denied(self, resolver, reader_context):
        """Reader cannot execute admin tool."""
        manager = ToolManager(resolver=resolver)
        manager._tools = {'admin_tool': AdminTool()}

        result = await manager.execute_tool(
            'admin_tool',
            permission_context=reader_context
        )
        assert result.success is False
        assert result.status == 'forbidden'

    @pytest.mark.asyncio
    async def test_context_propagated_to_tool(self, resolver, admin_context):
        """Context and resolver are passed to tool.execute()."""
        manager = ToolManager(resolver=resolver)

        mock_tool = MagicMock(spec=AbstractTool)
        mock_tool.execute = AsyncMock(return_value=ToolResult(
            success=True, status="success", result="ok"
        ))
        manager._tools = {'test': mock_tool}

        await manager.execute_tool(
            'test',
            permission_context=admin_context,
            custom_arg="value"
        )

        mock_tool.execute.assert_called_once()
        call_kwargs = mock_tool.execute.call_args.kwargs
        assert call_kwargs['_permission_context'] is admin_context
        assert call_kwargs['_resolver'] is resolver
        assert call_kwargs['custom_arg'] == "value"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-064-toolmanager-resolver-injection.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
