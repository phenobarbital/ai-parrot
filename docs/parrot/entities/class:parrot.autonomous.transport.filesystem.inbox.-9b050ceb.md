---
type: Wiki Entity
title: InboxManager
id: class:parrot.autonomous.transport.filesystem.inbox.InboxManager
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Point-to-point message delivery between agents using the filesystem.
---

# InboxManager

Defined in [`parrot.autonomous.transport.filesystem.inbox`](../summaries/mod:parrot.autonomous.transport.filesystem.inbox.md).

```python
class InboxManager
```

Point-to-point message delivery between agents using the filesystem.

Messages are delivered atomically via write-then-rename. Processing
uses exactly-once semantics by moving messages to ``.processed/``
before yielding them. Optional watchdog/inotify integration provides
sub-50ms notification latency with automatic fallback to polling.

Args:
    inbox_dir: Path to the inbox root directory.
    agent_id: The agent ID whose inbox this manager owns.
    config: Transport configuration.

## Methods

- `def setup(self) -> None` — Create inbox directories for this agent.
- `async def deliver(self, from_agent: str, from_name: str, to_agent: str, content: str, msg_type: str='message', payload: Optional[Dict[str, Any]]=None, reply_to: Optional[str]=None) -> str` — Deliver a message to an agent's inbox atomically.
- `async def poll(self) -> AsyncGenerator[Dict[str, Any], None]` — Poll the inbox for new messages.
- `def stop_watcher(self) -> None` — Stop the watchdog observer if running.
