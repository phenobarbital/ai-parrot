---
type: Wiki Entity
title: IntentRouterMixin
id: class:parrot.bots.mixins.intent_router.IntentRouterMixin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mixin that adds intent-based routing to any Bot or Agent.
---

# IntentRouterMixin

Defined in [`parrot.bots.mixins.intent_router`](../summaries/mod:parrot.bots.mixins.intent_router.md).

```python
class IntentRouterMixin
```

Mixin that adds intent-based routing to any Bot or Agent.

Must be placed before the concrete bot class in the MRO::

    class MyAgent(IntentRouterMixin, BasicAgent): ...

The mixin's ``conversation()`` intercepts calls when active and routes
through strategy discovery → candidate retrieval → decision → execution.

When inactive (``configure_router()`` not called), the mixin is a
zero-overhead no-op pass-through.

## Methods

- `def configure_router(self, config: IntentRouterConfig, registry: CapabilityRegistry) -> None` — Activate the intent router with the given config and registry.
- `def configure_output_router(self, config: IntentRouterConfig) -> None` — Build the deterministic output-mode router once (CONFIGURE phase).
- `async def conversation(self, prompt: str, **kwargs: Any) -> Any` — Intercept conversation to route via intent router when active.
