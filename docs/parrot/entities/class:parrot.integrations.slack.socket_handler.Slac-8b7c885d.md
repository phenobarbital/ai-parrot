---
type: Wiki Entity
title: SlackSocketHandler
id: class:parrot.integrations.slack.socket_handler.SlackSocketHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handle Slack events via Socket Mode (WebSocket connection).
---

# SlackSocketHandler

Defined in [`parrot.integrations.slack.socket_handler`](../summaries/mod:parrot.integrations.slack.socket_handler.md).

```python
class SlackSocketHandler
```

Handle Slack events via Socket Mode (WebSocket connection).

Socket Mode allows receiving events from Slack without exposing
a public HTTP endpoint. It uses a WebSocket connection initiated
from the client side.

Requires:
- App-level token (xapp-...) with connections:write scope
- Socket Mode enabled in Slack app settings

Attributes:
    wrapper: The SlackAgentWrapper instance to route events to.
    client: The SocketModeClient for WebSocket communication.

## Methods

- `async def start(self) -> None` — Connect to Slack via WebSocket.
- `async def stop(self) -> None` — Disconnect from Slack.
