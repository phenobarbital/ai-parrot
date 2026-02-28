# TASK-062: AbstractTool Layer 2 Enforcement

**Feature**: Granular Permissions System for Tools & Toolkits
**Spec**: `sdd/specs/granular-permission-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-059, TASK-060
**Assigned-to**: unassigned

---

## Context

> This task implements Module 5 from the spec: AbstractTool Layer 2 Enforcement.

Layer 2 enforcement is the reactive safety net. Even if a tool slips through Layer 1 filtering (e.g., registered manually), `execute()` checks permissions before calling `_execute()`. Returns a structured `ToolResult` rather than raising an exception.

---

## Scope

- Modify `AbstractTool.execute()` to check permissions before `_execute()`
- Accept `_permission_context` and `_resolver` kwargs
- Return `ToolResult(status='forbidden')` on permission denial
- Log permission denials with warning level
- Maintain backward compatibility (no context = no check)
- Write unit tests for enforcement

**NOT in scope**:
- Layer 1 filtering (TASK-063)
- ToolManager changes (TASK-064)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/abstract.py` | MODIFY | Add Layer 2 permission check in `execute()` |
| `tests/tools/test_abstract_permissions.py` | CREATE | Unit tests for Layer 2 |

---

## Implementation Notes

### Pattern to Follow
```python
# In AbstractTool.execute()
async def execute(self, *args, **kwargs) -> ToolResult:
    # ── Permission check (Layer 2 safety net) ────────────────────────────
    pctx = kwargs.pop('_permission_context', None)
    resolver = kwargs.pop('_resolver', None)

    if pctx is not None and resolver is not None:
        required = getattr(self, '_required_permissions', set())
        allowed = await resolver.can_execute(pctx, self.name, required)
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
    # ... existing validation and _execute() call ...
```

### Key Constraints
- Pop `_permission_context` and `_resolver` from kwargs before passing to `_execute()`
- Return `ToolResult` not exception on denial
- Use `status='forbidden'` for permission errors
- Log with `self.logger.warning()` including user_id and tool_name
- No context = no enforcement (backward compatible)

### References in Codebase
- `parrot/tools/abstract.py` — current `execute()` implementation
- `parrot/tools/abstract.py:ToolResult` — result model

---

## Acceptance Criteria

- [ ] `execute()` accepts `_permission_context` and `_resolver` kwargs
- [ ] Permission check runs before `_execute()`
- [ ] Denied calls return `ToolResult(status='forbidden')`
- [ ] Denied calls are logged as warnings
- [ ] No context provided = no enforcement
- [ ] Existing tool behavior unchanged when no context
- [ ] Unit tests pass: `pytest tests/tools/test_abstract_permissions.py -v`
- [ ] No linting errors: `ruff check parrot/tools/abstract.py`

---

## Test Specification

```python
# tests/tools/test_abstract_permissions.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.auth.permission import UserSession, PermissionContext
from parrot.auth.resolver import DefaultPermissionResolver
from parrot.tools.decorators import requires_permission


class MockTool(AbstractTool):
    """Test tool for permission testing."""
    name = "mock_tool"
    description = "A mock tool"

    async def _execute(self, **kwargs):
        return ToolResult(success=True, status="success", result="executed")


@requires_permission('write')
class RestrictedTool(AbstractTool):
    """Tool requiring write permission."""
    name = "restricted_tool"
    description = "Requires write permission"

    async def _execute(self, **kwargs):
        return ToolResult(success=True, status="success", result="restricted executed")


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


class TestLayer2Enforcement:
    @pytest.mark.asyncio
    async def test_no_context_no_enforcement(self):
        """Without context, no permission check runs."""
        tool = MockTool()
        result = await tool.execute()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_unrestricted_tool_allowed(self, resolver, reader_context):
        """Unrestricted tool (no decorator) is always allowed."""
        tool = MockTool()
        result = await tool.execute(
            _permission_context=reader_context,
            _resolver=resolver
        )
        assert result.success is True
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_restricted_tool_denied(self, resolver, reader_context):
        """Restricted tool denies user without permission."""
        tool = RestrictedTool()
        result = await tool.execute(
            _permission_context=reader_context,
            _resolver=resolver
        )
        assert result.success is False
        assert result.status == "forbidden"
        assert "Permission denied" in result.error

    @pytest.mark.asyncio
    async def test_restricted_tool_allowed(self, resolver, admin_context):
        """Restricted tool allows user with permission."""
        tool = RestrictedTool()
        result = await tool.execute(
            _permission_context=admin_context,
            _resolver=resolver
        )
        assert result.success is True
        assert result.result == "restricted executed"

    @pytest.mark.asyncio
    async def test_denial_logged(self, resolver, reader_context, caplog):
        """Permission denial is logged as warning."""
        import logging
        with caplog.at_level(logging.WARNING):
            tool = RestrictedTool()
            await tool.execute(
                _permission_context=reader_context,
                _resolver=resolver
            )

        assert "Permission denied" in caplog.text
        assert "reader" in caplog.text
        assert "restricted_tool" in caplog.text

    @pytest.mark.asyncio
    async def test_kwargs_not_passed_to_execute(self, resolver, admin_context):
        """_permission_context and _resolver are not passed to _execute."""
        class InspectingTool(AbstractTool):
            name = "inspect_tool"
            description = "Inspects kwargs"
            captured_kwargs = None

            async def _execute(self, **kwargs):
                InspectingTool.captured_kwargs = kwargs
                return ToolResult(success=True, status="success", result="ok")

        tool = InspectingTool()
        await tool.execute(
            _permission_context=admin_context,
            _resolver=resolver,
            actual_arg="value"
        )

        assert '_permission_context' not in InspectingTool.captured_kwargs
        assert '_resolver' not in InspectingTool.captured_kwargs
        assert InspectingTool.captured_kwargs.get('actual_arg') == "value"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-062-abstracttool-layer2-enforcement.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
