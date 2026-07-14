---
type: Wiki Entity
title: MatrixCrewRegistry
id: class:parrot.integrations.matrix.crew.registry.MatrixCrewRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Thread-safe in-memory registry tracking agent status in a Matrix crew.
---

# MatrixCrewRegistry

Defined in [`parrot.integrations.matrix.crew.registry`](../summaries/mod:parrot.integrations.matrix.crew.registry.md).

```python
class MatrixCrewRegistry
```

Thread-safe in-memory registry tracking agent status in a Matrix crew.

All mutating operations use an ``asyncio.Lock`` to ensure consistency
when called from concurrent coroutines.

Usage::

    registry = MatrixCrewRegistry()
    card = MatrixAgentCard(
        agent_name="analyst",
        display_name="Financial Analyst",
        mxid="@analyst:example.com",
    )
    await registry.register(card)
    await registry.update_status("analyst", "busy", "Analyzing AAPL")
    agent = await registry.get("analyst")

## Methods

- `async def register(self, card: MatrixAgentCard) -> None` — Register an agent in the crew.
- `async def unregister(self, agent_name: str) -> None` — Remove an agent from the registry.
- `async def update_status(self, agent_name: str, status: str, current_task: Optional[str]=None) -> None` — Update an agent's status and optionally its current task.
- `async def get(self, agent_name: str) -> Optional[MatrixAgentCard]` — Get an agent card by agent name.
- `async def get_by_mxid(self, mxid: str) -> Optional[MatrixAgentCard]` — Find an agent card by its full MXID.
- `async def all_agents(self) -> List[MatrixAgentCard]` — Return all registered agents.
