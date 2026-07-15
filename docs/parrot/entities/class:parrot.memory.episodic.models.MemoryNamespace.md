---
type: Wiki Entity
title: MemoryNamespace
id: class:parrot.memory.episodic.models.MemoryNamespace
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Hierarchical namespace for isolating episodes.
---

# MemoryNamespace

Defined in [`parrot.memory.episodic.models`](../summaries/mod:parrot.memory.episodic.models.md).

```python
class MemoryNamespace(BaseModel)
```

Hierarchical namespace for isolating episodes.

Supports queries at different granularity levels:
- Global agent: (tenant_id, agent_id)
- Per-user: (tenant_id, agent_id, user_id)
- Per-room: (tenant_id, agent_id, room_id)
- Per-session: (tenant_id, agent_id, user_id, session_id)
- Per-crew: (tenant_id, crew_id)

## Methods

- `def build_filter(self) -> dict[str, Any]` — Generate a filter dict for backend queries.
- `def scope_label(self) -> str` — Human-readable label for this namespace scope.
- `def redis_prefix(self) -> str` — Redis key prefix for this namespace.
