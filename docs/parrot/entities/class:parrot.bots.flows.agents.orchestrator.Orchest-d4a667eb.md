---
type: Wiki Entity
title: OrchestratorAgent
id: class:parrot.bots.flows.agents.orchestrator.OrchestratorAgent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: An orchestrator agent that can coordinate multiple specialized agents.
relates_to:
- concept: class:parrot.bots.agent.BasicAgent
  rel: extends
---

# OrchestratorAgent

Defined in [`parrot.bots.flows.agents.orchestrator`](../summaries/mod:parrot.bots.flows.agents.orchestrator.md).

```python
class OrchestratorAgent(BasicAgent)
```

An orchestrator agent that can coordinate multiple specialized agents.

This agent decides which specialists to consult and synthesizes their
responses.

## Methods

- `async def configure(self, app=None) -> None` — Configure the OrchestratorAgent and register specialist agents.
- `async def register_specialist_agents(self)` — Hook method for registering specialist agents.
- `def add_agent(self, agent: Union[BasicAgent, AbstractBot], tool_name: str=None, description: str=None, use_conversation_method: bool=True, context_filter: Optional[Callable[[AgentContext], AgentContext]]=None) -> None` — Add a specialized agent to this orchestrator.
- `async def add_agent_by_name(self, agent_name: str, tool_name: str=None, description: str=None, **kwargs) -> None` — Resolve an agent by name from AgentRegistry and add it as a specialist.
- `async def ask(self, question: str, **kwargs) -> AIMessage` — Ask with automatic pass-through or synthesis based on agent responses.
- `def remove_agent(self, agent_name: str) -> None` — Remove a specialized agent from this orchestrator.
- `def list_agents(self) -> List[str]` — List all registered specialist agents.
- `def get_orchestration_stats(self) -> Dict[str, Any]` — Get statistics about agent usage in orchestration.
- `async def confer(self, question: str, agents: Optional[List[str]]=None, max_rounds: int=3, until_convergence: bool=True, **kwargs) -> AIMessage` — Run a deterministic multi-party conference over the specialists.
