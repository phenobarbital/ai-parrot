---
type: Concept
title: scope()
id: func:parrot.core.events.lifecycle.global_registry.scope
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Replace the global registry with a fresh one for the block duration.
---

# scope

```python
def scope() -> Iterator[EventRegistry]
```

Replace the global registry with a fresh one for the block duration.

Yields a new ``EventRegistry(forward_to_global=False)`` and restores the
previous registry on exit, even if the block raises.  Use this in tests
and isolated execution contexts to prevent event leakage between scopes.

The token-based restore via ``ContextVar.reset(token)`` is the only
correct way to restore the prior value — direct re-assignment would break
the ContextVar chain for nested scopes.

Yields:
    A fresh, isolated ``EventRegistry`` instance.

Warning:
    Tasks scheduled via ``create_task`` inside the scope may still hold a
    reference to the scoped registry after ``scope()`` exits.  In tests,
    always ``await asyncio.sleep(0)`` before asserting on events forwarded
    to the global registry to ensure all scheduled tasks have completed.

Example::

    with scope() as reg:
        reg.subscribe(BeforeInvokeEvent, my_listener)
        await agent.ask("hello")
    # Subscriptions are gone after the block.
