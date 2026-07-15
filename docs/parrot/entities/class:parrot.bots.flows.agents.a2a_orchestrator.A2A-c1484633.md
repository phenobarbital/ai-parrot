---
type: Wiki Entity
title: A2AOrchestratorAgent
id: class:parrot.bots.flows.agents.a2a_orchestrator.A2AOrchestratorAgent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: An orchestrator agent that supports both local and remote A2A agents.
relates_to:
- concept: class:parrot.a2a.mixin.A2AClientMixin
  rel: extends
- concept: class:parrot.bots.flows.agents.orchestrator.OrchestratorAgent
  rel: extends
---

# A2AOrchestratorAgent

Defined in [`parrot.bots.flows.agents.a2a_orchestrator`](../summaries/mod:parrot.bots.flows.agents.a2a_orchestrator.md).

```python
class A2AOrchestratorAgent(A2AClientMixin, OrchestratorAgent)
```

An orchestrator agent that supports both local and remote A2A agents.

This class combines the OrchestratorAgent's ability to coordinate local
specialized agents with A2AClientMixin's remote agent communication.

Features:
    - Add local agents with add_agent()
    - Add remote A2A agents with add_a2a_agent()
    - Both types become callable tools for the LLM
    - Built-in discovery tool for finding remote agents
    - Enhanced system prompt explaining hybrid orchestration

Example::

    orchestrator = A2AOrchestratorAgent(
        name="HybridOrchestrator",
        llm="google:gemini-3.1-flash-lite-preview"
    )
    await orchestrator.configure()

    # Add local agents
    local_agent = BasicAgent(name="Analyst", llm="openai:gpt-4")
    await local_agent.configure()
    orchestrator.add_agent(local_agent)

    # Add remote A2A agents
    await orchestrator.add_a2a_agent("http://localhost:8082")
    await orchestrator.add_a2a_agent("http://localhost:8083")

    # Now orchestrator can use both local and remote agents
    response = await orchestrator.ask("Analyze data and summarize")

## Methods

- `async def configure(self, app=None) -> None` — Configure the A2AOrchestratorAgent.
- `def list_all_agents(self) -> Dict[str, List[str]]` — List all agents (both local and remote).
- `def get_all_agent_stats(self) -> Dict[str, Any]` — Get statistics about all agent usage.
- `async def shutdown(self, **kwargs) -> None` — Shutdown orchestrator and cleanup all connections.
