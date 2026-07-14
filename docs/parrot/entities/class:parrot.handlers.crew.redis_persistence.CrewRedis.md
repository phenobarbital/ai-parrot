---
type: Wiki Entity
title: CrewRedis
id: class:parrot.handlers.crew.redis_persistence.CrewRedis
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Redis-based persistence for AgentsCrew definitions.
---

# CrewRedis

Defined in [`parrot.handlers.crew.redis_persistence`](../summaries/mod:parrot.handlers.crew.redis_persistence.md).

```python
class CrewRedis
```

Redis-based persistence for AgentsCrew definitions.

## Methods

- `async def save_crew(self, crew: CrewDefinition) -> bool` — Save crew definition to Redis.
- `async def load_crew(self, name: str, tenant: Optional[str]=None) -> Optional[CrewDefinition]` — Load crew definition from Redis by name.
- `async def load_crew_by_id(self, crew_id: str, tenant: Optional[str]=None) -> Optional[CrewDefinition]` — Load crew definition from Redis by crew_id.
- `async def delete_crew(self, name: str, tenant: Optional[str]=None) -> bool` — Delete crew definition from Redis.
- `async def list_crews(self, tenant: Optional[str]=None) -> List[str]` — List all crew names in Redis.
- `async def list_all_crews(self) -> List[Dict[str, str]]` — List all crew names across tenants.
- `async def crew_exists(self, name: str, tenant: Optional[str]=None) -> bool` — Check if a crew exists in Redis.
- `async def get_all_crews(self, tenant: Optional[str]=None) -> List[CrewDefinition]` — Get all crew definitions from Redis.
- `async def get_crew_metadata(self, name: str, tenant: Optional[str]=None) -> Optional[Dict[str, Any]]` — Get crew metadata without loading the full definition.
- `async def update_crew_metadata(self, name: str, metadata: Dict[str, Any], tenant: Optional[str]=None) -> bool` — Update crew metadata without modifying agents or configuration.
- `async def ping(self) -> bool` — Test Redis connection.
- `async def close(self)` — Close the Redis connection.
- `async def clear_all_crews(self) -> int` — Delete all crews from Redis (use with caution).
