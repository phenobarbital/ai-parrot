---
type: Wiki Entity
title: BotConfigStorage
id: class:parrot.registry.storage.BotConfigStorage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Redis-backed CRUD storage for BotConfig agent definitions.
---

# BotConfigStorage

Defined in [`parrot.registry.storage`](../summaries/mod:parrot.registry.storage.md).

```python
class BotConfigStorage
```

Redis-backed CRUD storage for BotConfig agent definitions.

## Methods

- `async def list(self) -> List[BotConfig]` — Return all BotConfig objects stored in Redis.
- `async def get(self, name: str) -> Optional[BotConfig]` — Fetch a single BotConfig by agent name.
- `async def save(self, config: BotConfig) -> None` — Update an existing agent config in Redis.
- `async def insert(self, config: BotConfig, registered_agents: Optional[Dict[str, Any]]=None) -> None` — Insert a new agent config into Redis.
- `async def transfer(self, name: str, registry: 'AgentRegistry', category: str='general') -> Path` — Move a BotConfig from Redis to the filesystem as a YAML file.
- `async def delete(self, name: str) -> bool` — Remove a BotConfig from Redis by name.
- `async def close(self) -> None` — Close the underlying Redis connection.
