---
type: Wiki Entity
title: A2AServer
id: class:parrot.a2a.server.A2AServer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wraps an AI-Parrot Agent (BasicAgent/AbstractBot) as an A2A HTTP service.
---

# A2AServer

Defined in [`parrot.a2a.server`](../summaries/mod:parrot.a2a.server.md).

```python
class A2AServer
```

Wraps an AI-Parrot Agent (BasicAgent/AbstractBot) as an A2A HTTP service.

This server exposes your existing agent via the A2A protocol, automatically
generating the AgentCard from the agent's properties and tools.

Example:
    from parrot.bots import Agent
    from parrot.a2a import A2AServer

    # Create your agent as usual
    agent = Agent(
        name="CustomerSupport",
        llm="anthropic:claude-sonnet-4-20250514",
        tools=[QueryCustomersTool(), CreateTicketTool()]
    )
    await agent.configure()

    # Wrap it as A2A service
    a2a = A2AServer(agent)

    # Mount on your aiohttp app
    app = web.Application()
    a2a.setup(app)

    # Agent is now accessible at:
    # - GET  /.well-known/agent.json  (discovery)
    # - POST /a2a/message/send        (send message)
    # - POST /a2a/message/stream      (streaming)
    # - GET  /a2a/tasks/{id}          (get task)
    # etc.

## Methods

- `def setup(self, app: web.Application, url: Optional[str]=None, *, register_well_known: bool=True) -> None` — Register A2A routes on an aiohttp application.
- `def get_agent_card(self) -> AgentCard` — Generate AgentCard from the wrapped agent's properties.
- `def register_credential_resolver(self, provider: str, resolver: Any) -> None` — Register a :class:`~parrot.auth.credentials.CredentialResolver` for *provider*.
- `async def resume_from_oauth_callback(self, interaction_id: str, user_input: str='') -> None` — Resume a suspended A2A task after a successful OAuth callback.
- `async def process_message(self, message: Message, task: Optional[Task]=None) -> Task` — Process an A2A message by delegating to the wrapped agent.
