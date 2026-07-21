---
type: Concept
title: requires_permission()
id: func:parrot.tools.decorators.requires_permission
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Annotate a toolkit method or AbstractTool class with required permissions.
---

# requires_permission

```python
def requires_permission(*permissions: str)
```

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
