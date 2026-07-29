---
type: Concept
title: project_permission_context()
id: func:parrot.tools.executors.abstract.project_permission_context
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Project a PermissionContext into a JSON-safe dict.
---

# project_permission_context

```python
def project_permission_context(pctx: 'PermissionContext | None') -> Optional[Dict[str, Any]]
```

Project a PermissionContext into a JSON-safe dict.

Only stable, request-scoped fields are exported — no resolver,
no live callables. Roles convert from frozenset → list. The trace
context piggy-backs on its own field in the envelope, not on this
projection, so it is omitted here.
