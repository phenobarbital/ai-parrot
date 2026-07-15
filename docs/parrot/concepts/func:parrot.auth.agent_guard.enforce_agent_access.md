---
type: Concept
title: enforce_agent_access()
id: func:parrot.auth.agent_guard.enforce_agent_access
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raise ``AgentAccessDenied`` if the request's subject cannot resolve ``bot_name``.
---

# enforce_agent_access

```python
async def enforce_agent_access(evaluator: object | None, bot_name: str, request: Optional[web.Request]) -> None
```

Raise ``AgentAccessDenied`` if the request's subject cannot resolve ``bot_name``.

Allow-paths (no exception raised):
  - ``evaluator is None`` — PBAC not initialized; backwards-compatible allow.
  - ``request is None`` — programmatic Python invocation (script, CLI, internal
    crew composition, tests). PBAC enforcement is HTTP-scoped: no request,
    no check. (Resolved §8 Q1.)
  - No policies are registered for ``agent:<bot_name>`` — bot is public.
  - ``PolicyEvaluator.check_access(...)`` returns ``allowed=True``.

Deny-path (``AgentAccessDenied`` raised):
  - ``request is not None`` AND policies are registered AND
    ``PolicyEvaluator.check_access(...)`` returns ``allowed=False``.

Logs a WARNING on denials, mirroring the ``PBACPermissionResolver`` pattern.

Args:
    evaluator: Shared ``PolicyEvaluator`` instance (from
        ``AgentRegistry._evaluator``), or ``None`` when PBAC is disabled.
    bot_name: Base name of the bot being resolved (used as ``resource_name``).
    request: The incoming aiohttp request, or ``None`` for programmatic calls.

Raises:
    AgentAccessDenied: When the evaluator denies the request's subject.

Example::

    await enforce_agent_access(self.registry._evaluator, name, request)
