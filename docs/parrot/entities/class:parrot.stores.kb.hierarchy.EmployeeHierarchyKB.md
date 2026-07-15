---
type: Wiki Entity
title: EmployeeHierarchyKB
id: class:parrot.stores.kb.hierarchy.EmployeeHierarchyKB
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Knowledge Base what provides employee hierarchy context.
relates_to:
- concept: class:parrot.stores.kb.abstract.AbstractKnowledgeBase
  rel: extends
---

# EmployeeHierarchyKB

Defined in [`parrot.stores.kb.hierarchy`](../summaries/mod:parrot.stores.kb.hierarchy.md).

```python
class EmployeeHierarchyKB(AbstractKnowledgeBase)
```

Knowledge Base what provides employee hierarchy context.

Extracts the associate_oid of the user from the session and searches for:
- Their direct boss and chain of command
- Their department and unit
- Their colleagues
- Their direct reports (if they are a manager)

This context is automatically incorporated into the user-context so that
the LLM is aware of the user's hierarchical position.
Args:
    permission_service: An instance of HierarchyPermissionService to fetch hierarchy data.
    always_active: If True, this KB is always active (default True)
    priority: The priority of this KB (higher = included first)

Example:
```python
hierarchy_kb = EmployeeHierarchyKB(
    permission_service=service,
    always_active=True
)
bot.register_kb(hierarchy_kb)
```

## Methods

- `async def close(self)` — Cleanup resources if needed.
- `async def should_activate(self, query: str, context: Dict[str, Any]) -> Tuple[bool, float]`
- `async def search(self, query: str, user_id: str=None, session_id: str=None, ctx: RequestContext=None, **kwargs) -> List[Dict[str, Any]]` — Search and return the employee hierarchy context.
- `def format_context(self, results: List[Dict[str, Any]]) -> str` — Final string injected into the Agent System Prompt.
