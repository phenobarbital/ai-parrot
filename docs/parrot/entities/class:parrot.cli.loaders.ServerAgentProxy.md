---
type: Wiki Entity
title: ServerAgentProxy
id: class:parrot.cli.loaders.ServerAgentProxy
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Proxy agent interactions to a running AI-Parrot server via HTTP.
---

# ServerAgentProxy

Defined in [`parrot.cli.loaders`](../summaries/mod:parrot.cli.loaders.md).

```python
class ServerAgentProxy
```

Proxy agent interactions to a running AI-Parrot server via HTTP.

Lists available agents from the server registry and proxies ``ask()``
calls through the server REST API.

Attributes:
    server_url: Base URL of the running server.
    timeout: HTTP request timeout in seconds.

## Methods

- `async def load(self, name: str) -> _ServerBotProxy` — Create a proxy bot for the named agent on the server.
- `async def list_agents(self) -> List[Dict[str, Any]]` — Fetch the list of agents from the server registry.
- `async def select_agent(self) -> str` — Present an interactive agent picker from the server's agent list.
- `async def close(self) -> None` — Close the underlying HTTP session.
