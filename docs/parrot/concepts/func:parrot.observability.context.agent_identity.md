---
type: Concept
title: agent_identity()
id: func:parrot.observability.context.agent_identity
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Bind *name* as the active agent for the duration of the block.
---

# agent_identity

```python
def agent_identity(name: Optional[str]) -> Iterator[None]
```

Bind *name* as the active agent for the duration of the block.

Uses a token-based ``set()`` / ``reset()`` so nested invocations restore
the prior value rather than resetting to ``None``.

Args:
    name: The ``AbstractBot.name`` of the invoking agent.  ``None`` is
        accepted for call-sites that do not have an agent in scope; the
        prior value is still restored correctly on exit.

Example::

    with agent_identity("porygon"):
        # current_agent_name.get() == "porygon"
        with agent_identity("inner"):
            # current_agent_name.get() == "inner"
        # current_agent_name.get() == "porygon" (restored)
    # current_agent_name.get() is None (restored)
