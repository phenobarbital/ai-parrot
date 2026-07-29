---
type: Wiki Entity
title: A2AEnabledMixin
id: class:parrot.a2a.server.A2AEnabledMixin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mixin to add A2A server capabilities to an agent class.
---

# A2AEnabledMixin

Defined in [`parrot.a2a.server`](../summaries/mod:parrot.a2a.server.md).

```python
class A2AEnabledMixin
```

Mixin to add A2A server capabilities to an agent class.

Similar to MCPEnabledMixin, this adds A2A methods directly to your agent.

Example:
    class MyAgent(A2AEnabledMixin, BasicAgent):
        pass

    agent = MyAgent(name="test", llm="openai:gpt-4")
    await agent.configure()

    # Start A2A server
    app = web.Application()
    agent.setup_a2a(app, url="https://my-agent.example.com")

## Methods

- `def setup_a2a(self, app: web.Application, url: Optional[str]=None, base_path: str='/a2a', **kwargs) -> A2AServer` — Setup A2A server for this agent.
- `def get_a2a_server(self) -> Optional[A2AServer]` — Get the A2A server instance if setup.
- `def get_agent_card(self) -> Optional[AgentCard]` — Get the AgentCard if A2A is setup.
