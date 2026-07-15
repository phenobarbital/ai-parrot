---
type: Wiki Entity
title: FlowLoader
id: class:parrot.bots.flows.flow.loader.FlowLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Load, save, and materialize FlowDefinition instances.
---

# FlowLoader

Defined in [`parrot.bots.flows.flow.loader`](../summaries/mod:parrot.bots.flows.flow.loader.md).

```python
class FlowLoader
```

Load, save, and materialize FlowDefinition instances.

## Methods

- `def from_dict(cls, data: Dict[str, Any]) -> FlowDefinition` — Parse a dict into a validated FlowDefinition.
- `def from_json(cls, json_str: str) -> FlowDefinition` — Parse a JSON string into a validated FlowDefinition.
- `def load_from_file(cls, path: Union[str, Path]) -> FlowDefinition` — Load from file path or AGENTS_DIR/flows/{name}.json.
- `def save_to_file(cls, definition: FlowDefinition, path: Union[str, Path], *, indent: int=2, update_timestamp: bool=True) -> None` — Persist FlowDefinition as JSON with optional timestamp update.
- `async def load_from_redis(cls, redis: Any, flow_name: str) -> FlowDefinition` — Load a FlowDefinition from Redis.
- `async def save_to_redis(cls, redis: Any, definition: FlowDefinition, *, ttl: Optional[int]=None, update_timestamp: bool=True) -> None` — Save a FlowDefinition to Redis.
- `async def list_flows_in_redis(cls, redis: Any) -> List[str]` — List all flow names stored in Redis.
- `async def delete_from_redis(cls, redis: Any, flow_name: str) -> None` — Delete a flow from Redis.
- `def to_agents_flow(cls, definition: FlowDefinition, agent_registry: Optional[Any]=None, extra_agents: Optional[Dict[str, Any]]=None) -> 'AgentsFlow'` — Materialize a FlowDefinition into a runnable AgentsFlow.
