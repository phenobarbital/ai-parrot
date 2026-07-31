---
type: Wiki Entity
title: AgentLike
id: class:parrot.bots.flows.core.types.AgentLike
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Structural protocol for any object that can act as an agent node.
---

# AgentLike

Defined in [`parrot.bots.flows.core.types`](../summaries/mod:parrot.bots.flows.core.types.md).

```python
class AgentLike(Protocol)
```

Structural protocol for any object that can act as an agent node.

Using a Protocol (rather than importing ``BasicAgent`` / ``AbstractBot``)
keeps this module import-cycle-free and allows StartNode, EndNode, and
mock objects to satisfy the contract.

Attributes:
    name: Human-readable agent identifier.

Methods:
    invoke: Async call that processes a prompt and returns a result.

.. warning:: ``runtime_checkable`` limitation

    ``isinstance(obj, AgentLike)`` only checks for *attribute existence*,
    not whether ``invoke`` is a coroutine function.  An object with a
    *synchronous* ``invoke`` method will pass the check but will raise a
    ``TypeError`` at runtime when the engine does ``await agent.invoke(...)``.
    Callers that need strict enforcement should additionally verify
    ``asyncio.iscoroutinefunction(obj.invoke)``.

## Methods

- `def name(self) -> str` — Human-readable agent identifier.
- `async def invoke(self, prompt: str, **kwargs: Any) -> Any` — Process a prompt and return a result.
