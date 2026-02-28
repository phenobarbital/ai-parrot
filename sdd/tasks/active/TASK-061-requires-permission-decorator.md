# TASK-061: Requires Permission Decorator

**Feature**: Granular Permissions System for Tools & Toolkits
**Spec**: `sdd/specs/granular-permission-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task implements Module 4 from the spec: Requires Permission Decorator.

The `@requires_permission` decorator annotates toolkit methods with required permissions. The annotation is introspected at runtime by the resolver and `get_tools()` for filtering.

---

## Scope

- Implement `@requires_permission(*permissions)` decorator
- Set `_required_permissions` attribute as frozenset
- Support both toolkit methods and AbstractTool classes
- Use OR semantics (any matching permission grants access)
- Write unit tests for decorator

**NOT in scope**:
- AND logic (use compound permission strings instead)
- Enforcement logic (handled in TASK-062, TASK-063)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/decorators.py` | MODIFY | Add `requires_permission` decorator |
| `tests/tools/test_decorators.py` | MODIFY | Add tests for new decorator |

---

## Implementation Notes

### Pattern to Follow
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

    Args:
        *permissions: Variable permission strings. User needs at least one.

    Returns:
        Decorated function/class with `_required_permissions` attribute.
    """
    def decorator(obj):
        obj._required_permissions = frozenset(permissions)
        return obj
    return decorator
```

### Key Constraints
- Decorator must work on both functions and classes
- Must set `_required_permissions` as `frozenset`
- Empty permissions (`@requires_permission()`) results in empty frozenset
- Does NOT raise at decoration time — validation happens at execution

### Semantics Table
| Pattern | Meaning | Example |
|---|---|---|
| `@requires_permission('a', 'b')` | OR — user needs `a` OR `b` | `jira.manage` OR `jira.admin` |
| `@requires_permission('a.b')` | Exact match — user needs `a.b` | `jira.write` exactly |
| No decorator | Unrestricted — any user may call | `search_issues`, `get_issue` |

### References in Codebase
- `parrot/tools/decorators.py` — existing decorators (`@tool`, `@tool_schema`)

---

## Acceptance Criteria

- [ ] `@requires_permission` decorator exists in `parrot/tools/decorators.py`
- [ ] Decorator sets `_required_permissions` as frozenset
- [ ] Works on async methods
- [ ] Works on classes
- [ ] Multiple permissions use OR semantics
- [ ] Unit tests pass: `pytest tests/tools/test_decorators.py -v -k permission`
- [ ] Import works: `from parrot.tools.decorators import requires_permission`

---

## Test Specification

```python
# tests/tools/test_decorators.py (add to existing)
import pytest
from parrot.tools.decorators import requires_permission


class TestRequiresPermissionDecorator:
    def test_sets_attribute_on_function(self):
        """Decorator sets _required_permissions on function."""
        @requires_permission('admin')
        async def my_func():
            pass

        assert hasattr(my_func, '_required_permissions')
        assert my_func._required_permissions == frozenset({'admin'})

    def test_sets_attribute_on_class(self):
        """Decorator sets _required_permissions on class."""
        @requires_permission('write', 'admin')
        class MyTool:
            pass

        assert hasattr(MyTool, '_required_permissions')
        assert MyTool._required_permissions == frozenset({'write', 'admin'})

    def test_multiple_permissions_or_semantics(self):
        """Multiple permissions are stored for OR check."""
        @requires_permission('a', 'b', 'c')
        async def multi_perm():
            pass

        assert multi_perm._required_permissions == frozenset({'a', 'b', 'c'})

    def test_single_permission(self):
        """Single permission works."""
        @requires_permission('read')
        async def single():
            pass

        assert single._required_permissions == frozenset({'read'})

    def test_empty_permissions(self):
        """Empty permissions results in empty frozenset."""
        @requires_permission()
        async def unrestricted():
            pass

        assert unrestricted._required_permissions == frozenset()

    def test_preserves_function_metadata(self):
        """Decorator preserves function name and docstring."""
        @requires_permission('admin')
        async def documented_func():
            '''This is the docstring.'''
            pass

        assert documented_func.__name__ == 'documented_func'
        assert 'docstring' in documented_func.__doc__

    def test_function_still_callable(self):
        """Decorated function is still callable."""
        @requires_permission('admin')
        def sync_func(x):
            return x * 2

        assert sync_func(5) == 10
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-061-requires-permission-decorator.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
