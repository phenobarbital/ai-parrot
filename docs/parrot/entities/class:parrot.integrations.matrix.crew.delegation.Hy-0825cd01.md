---
type: Wiki Entity
title: HybridDelegator
id: class:parrot.integrations.matrix.crew.delegation.HybridDelegator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Orchestrates hybrid tool delegation in a Matrix room.
---

# HybridDelegator

Defined in [`parrot.integrations.matrix.crew.delegation`](../summaries/mod:parrot.integrations.matrix.crew.delegation.md).

```python
class HybridDelegator
```

Orchestrates hybrid tool delegation in a Matrix room.

Combines visible Matrix messages (for human readability) with custom
``m.parrot.task`` / ``m.parrot.result`` events (for agent-to-agent
communication).

Args:
    appservice: The shared ``MatrixAppService`` instance.
    registry: ``MatrixCrewRegistry`` for resolving agent cards.

## Methods

- `async def delegate(self, request: DelegationRequest, timeout: float=60.0) -> Optional[str]` — Execute a hybrid delegation request.
- `async def on_custom_event(self, event_type: str, content: dict) -> None` — Handle an incoming custom event from the AppService.
