---
type: Wiki Entity
title: AgentRegistry
id: class:parrot.autonomous.transport.filesystem.registry.AgentRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Agent presence registry using JSON files on the filesystem.
---

# AgentRegistry

Defined in [`parrot.autonomous.transport.filesystem.registry`](../summaries/mod:parrot.autonomous.transport.filesystem.registry.md).

```python
class AgentRegistry
```

Agent presence registry using JSON files on the filesystem.

Each agent is represented by a ``<agent_id>.json`` file in the registry
directory. Liveness is determined by PID checking (``os.kill(pid, 0)``),
providing instant detection of crashed agents without waiting for
heartbeat timeouts.

All writes use the write-then-rename pattern for POSIX atomicity.

Args:
    registry_dir: Path to the registry directory.
    config: Transport configuration.

## Methods

- `async def join(self, agent_id: str, name: str, pid: int, hostname: str, cwd: str, role: str, *, status: str='idle', message: str='') -> None` — Register an agent in the registry.
- `async def leave(self, agent_id: str) -> None` — Deregister an agent from the registry.
- `async def heartbeat(self, agent_id: str, *, status: Optional[str]=None, message: Optional[str]=None) -> None` — Update an agent's heartbeat timestamp and optional fields.
- `async def list_active(self) -> List[Dict[str, Any]]` — List all agents with live PIDs.
- `async def resolve(self, name_or_id: str) -> Optional[Dict[str, Any]]` — Resolve an agent by agent_id (exact) or name (case-insensitive).
- `async def gc_stale(self) -> List[str]` — Remove registry entries for agents with dead PIDs.
