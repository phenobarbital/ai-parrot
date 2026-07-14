---
type: Wiki Entity
title: CrewRegistry
id: class:parrot.integrations.telegram.crew.registry.CrewRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Thread-safe in-memory registry tracking active agents in the crew.
---

# CrewRegistry

Defined in [`parrot.integrations.telegram.crew.registry`](../summaries/mod:parrot.integrations.telegram.crew.registry.md).

```python
class CrewRegistry
```

Thread-safe in-memory registry tracking active agents in the crew.

All mutating operations use an asyncio.Lock to ensure consistency
when called from concurrent coroutines.

## Methods

- `async def register(self, card: AgentCard) -> None` — Register an agent in the crew.
- `async def unregister(self, username: str) -> Optional[AgentCard]` — Remove an agent from the registry.
- `async def update_status(self, username: str, status: str, current_task: Optional[str]=None) -> None` — Update an agent's status and optionally its current task.
- `def get(self, username: str) -> Optional[AgentCard]` — Get an agent card by Telegram username.
- `def list_active(self) -> List[AgentCard]` — Return all agents that are not offline.
- `def resolve(self, name_or_username: str) -> Optional[AgentCard]` — Resolve an agent by username or agent name.
