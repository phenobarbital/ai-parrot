---
type: Wiki Entity
title: HITLResponseHandler
id: class:parrot.handlers.web_hitl.HITLResponseHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTTP handler for ``POST /api/v1/agents/hitl/respond``.
---

# HITLResponseHandler

Defined in [`parrot.handlers.web_hitl`](../summaries/mod:parrot.handlers.web_hitl.md).

```python
class HITLResponseHandler(BaseView)
```

HTTP handler for ``POST /api/v1/agents/hitl/respond``.

Accepts a JSON body containing ``interaction_id`` and ``value``, looks
up the pending interaction in the default
:class:`~parrot.human.manager.HumanInteractionManager`, and calls
``manager.receive_response(...)`` to unblock the waiting agent.

Authentication:
    Requires a valid session (enforced by ``@is_authenticated()``).
    Respondent identity is taken from ``request.session.get('user_id')``.

## Methods

- `async def post(self) -> web.Response` — Handle a human response submission.
