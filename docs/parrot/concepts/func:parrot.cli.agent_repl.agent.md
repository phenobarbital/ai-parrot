---
type: Concept
title: agent()
id: func:parrot.cli.agent_repl.agent
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Interactive REPL for AI-Parrot agents.
---

# agent

```python
def agent(name: Optional[str], list_agents: bool, server: Optional[str], no_stream: bool) -> None
```

Interactive REPL for AI-Parrot agents.

Loads the named agent (or prompts for selection) and drops into an
interactive console session.  Supports both standalone mode (default)
and server-proxy mode (``--server URL``).

Args:
    name: Optional agent name.  If omitted, an interactive picker is shown.
    list_agents: If True, list registered agents and exit.
    server: Optional server URL for server-proxy mode.
    no_stream: If True, disable streaming and use batch rendering.
