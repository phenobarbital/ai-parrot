---
type: Concept
title: to_eval_context()
id: func:parrot.auth.permission.to_eval_context
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Bridge a PermissionContext to a navigator-auth EvalContext.
---

# to_eval_context

```python
def to_eval_context(context: 'PermissionContext') -> 'EvalContext'
```

Bridge a PermissionContext to a navigator-auth EvalContext.

Creates a minimal ``EvalContext`` that the ``PolicyEvaluator`` can use
to evaluate PBAC policies.  Extracts ``username``, ``groups``, ``roles``,
and ``programs`` from the ``UserSession.metadata`` where available.

Args:
    context: The AI-Parrot permission context carrying user session data.

Returns:
    An ``EvalContext`` instance populated with the session's userinfo.

Raises:
    ImportError: If navigator-auth is not installed.
