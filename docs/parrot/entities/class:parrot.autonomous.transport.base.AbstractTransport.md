---
type: Wiki Entity
title: AbstractTransport
id: class:parrot.autonomous.transport.base.AbstractTransport
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base for all multi-agent transports.
---

# AbstractTransport

Defined in [`parrot.autonomous.transport.base`](../summaries/mod:parrot.autonomous.transport.base.md).

```python
class AbstractTransport(ABC)
```

Abstract base for all multi-agent transports.

Defines the common interface for agent-to-agent communication.
Concrete implementations (e.g. ``FilesystemTransport``,
``TelegramCrewTransport``) must implement all abstract methods.

Supports async context manager for lifecycle management::

    async with MyTransport(...) as t:
        await t.send("agent-b", "hello")

## Methods

- `async def start(self) -> None` — Start the transport (register presence, begin listening).
- `async def stop(self) -> None` — Stop the transport (deregister, clean up resources).
- `async def send(self, to: str, content: str, msg_type: str='message', payload: Optional[Dict[str, Any]]=None, reply_to: Optional[str]=None) -> str` — Send a point-to-point message to another agent.
- `async def broadcast(self, content: str, channel: str='general', payload: Optional[Dict[str, Any]]=None) -> None` — Broadcast a message to a channel.
- `async def messages(self) -> AsyncGenerator[Dict[str, Any], None]` — Yield incoming point-to-point messages.
- `async def list_agents(self) -> List[Dict[str, Any]]` — List all currently active agents.
- `async def reserve(self, paths: List[str], reason: str='') -> bool` — Acquire cooperative resource reservations.
- `async def release(self, paths: Optional[List[str]]=None) -> None` — Release resource reservations.
- `async def set_status(self, status: str, message: str='') -> None` — Update this agent's status in the registry.
