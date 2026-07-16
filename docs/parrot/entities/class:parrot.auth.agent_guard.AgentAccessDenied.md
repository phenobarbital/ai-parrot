---
type: Wiki Entity
title: AgentAccessDenied
id: class:parrot.auth.agent_guard.AgentAccessDenied
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised by ``enforce_agent_access`` when PBAC denies bot resolution.
---

# AgentAccessDenied

Defined in [`parrot.auth.agent_guard`](../summaries/mod:parrot.auth.agent_guard.md).

```python
class AgentAccessDenied(PermissionError)
```

Raised by ``enforce_agent_access`` when PBAC denies bot resolution.

Attributes:
    bot_name: Name of the bot that was denied.
    user_id: User/subject identifier extracted from the request session.
    matched_policy: Name of the policy rule that triggered the denial
        (may be ``None`` if the evaluator did not report one).
    reason: Human-readable denial reason from the evaluator (may be ``None``).

Example::

    try:
        await enforce_agent_access(evaluator, "finance_bot", request)
    except AgentAccessDenied as exc:
        # 403 response
        return web.Response(status=403, text=str(exc))
