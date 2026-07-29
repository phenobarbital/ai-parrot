---
type: Wiki Entity
title: MatrixA2ATransport
id: class:parrot.integrations.matrix.a2a_transport.MatrixA2ATransport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A2A transport layer using Matrix as the message bus.
---

# MatrixA2ATransport

Defined in [`parrot.integrations.matrix.a2a_transport`](../summaries/mod:parrot.integrations.matrix.a2a_transport.md).

```python
class MatrixA2ATransport
```

A2A transport layer using Matrix as the message bus.

Enables agent-to-agent communication by mapping A2A concepts
onto Matrix rooms and custom events:

- Agent discovery → m.parrot.agent_card state events
- Task submission → m.parrot.task message events
- Task results → m.parrot.result message events
- Status updates → m.parrot.status message events

Each agent can publish its card in a room and other agents
discover it by reading room state. Federation comes for free
from Matrix.

## Methods

- `async def publish_card(self, room_id: str, card_data: Dict[str, Any], *, state_key: str='') -> str` — Publish an agent's A2A card as room state.
- `async def discover_card(self, room_id: str, state_key: str='') -> Optional[AgentCardEventContent]` — Read an agent's card from room state.
- `async def send_task(self, room_id: str, content: str, *, task_id: Optional[str]=None, context_id: Optional[str]=None, target_agent: Optional[str]=None, skill_id: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None) -> str` — Send a task to an agent room via m.parrot.task.
- `async def send_result(self, room_id: str, task_id: str, content: str, *, context_id: Optional[str]=None, artifacts: Optional[List[Dict[str, Any]]]=None, success: bool=True, error: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None) -> str` — Send a task result via m.parrot.result.
- `async def send_status(self, room_id: str, task_id: str, state: str, *, message: Optional[str]=None, progress: Optional[float]=None) -> str` — Send a status update via m.parrot.status.
- `async def wait_for_result(self, room_id: str, task_id: str, *, timeout: float=60.0) -> Optional[ResultEventContent]` — Wait for a m.parrot.result event matching the task_id.
