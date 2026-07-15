---
type: Wiki Entity
title: FilesystemTransport
id: class:parrot.autonomous.transport.filesystem.transport.FilesystemTransport
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Multi-agent transport over the local filesystem.
relates_to:
- concept: class:parrot.autonomous.transport.base.AbstractTransport
  rel: extends
---

# FilesystemTransport

Defined in [`parrot.autonomous.transport.filesystem.transport`](../summaries/mod:parrot.autonomous.transport.filesystem.transport.md).

```python
class FilesystemTransport(AbstractTransport)
```

Multi-agent transport over the local filesystem.

Composes ``AgentRegistry``, ``InboxManager``, ``ActivityFeed``,
``ChannelManager``, and ``ReservationManager`` into a unified API.
Manages the agent lifecycle (presence registration, heartbeat loop)
and exposes the public interface for messaging, broadcasting,
discovery, and resource reservations.

Args:
    agent_name: Human-readable name for this agent.
    config: Transport configuration.
    agent_id: Optional explicit agent ID. Generated if not provided.
    role: Agent role string (e.g. "agent", "coordinator").

## Methods

- `def agent_id(self) -> str` — The unique agent ID for this transport instance.
- `def agent_name(self) -> str` — The human-readable agent name.
- `async def start(self) -> None` — Start the transport: register presence, begin heartbeat loop.
- `async def stop(self) -> None` — Stop the transport: cancel heartbeat, release reservations, deregister.
- `async def send(self, to: str, content: str, msg_type: str='message', payload: Optional[Dict[str, Any]]=None, reply_to: Optional[str]=None) -> str` — Send a point-to-point message to another agent.
- `async def broadcast(self, content: str, channel: str='general', payload: Optional[Dict[str, Any]]=None) -> None` — Broadcast a message to a channel.
- `async def messages(self) -> AsyncGenerator[Dict[str, Any], None]` — Yield incoming point-to-point messages from this agent's inbox.
- `async def channel_messages(self, channel: str='general', since_offset: int=0) -> AsyncGenerator[Dict[str, Any], None]` — Yield messages from a broadcast channel.
- `async def list_agents(self) -> List[Dict[str, Any]]` — List all currently active agents.
- `async def whois(self, name_or_id: str) -> Optional[Dict[str, Any]]` — Look up an agent by name or ID.
- `async def reserve(self, paths: List[str], reason: str='') -> bool` — Acquire cooperative resource reservations.
- `async def release(self, paths: Optional[List[str]]=None) -> None` — Release resource reservations.
- `async def set_status(self, status: str, message: str='') -> None` — Update this agent's status in the registry.
