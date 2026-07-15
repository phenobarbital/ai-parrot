---
type: Wiki Entity
title: ResultAgent
id: class:parrot.bots.flows.result_agent.ResultAgent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Internal agent that renders a crew's ExecutionMemory into a crew_report infographic.
relates_to:
- concept: class:parrot.bots.agent.Agent
  rel: extends
---

# ResultAgent

Defined in [`parrot.bots.flows.result_agent`](../summaries/mod:parrot.bots.flows.result_agent.md).

```python
class ResultAgent(Agent)
```

Internal agent that renders a crew's ExecutionMemory into a crew_report infographic.

## Methods

- `def agent_tools(self) -> List[AbstractTool]` — Return the tools used by this agent.
- `async def generate_infographic(self, summary: str, deterministic_blocks: List[Dict[str, Any]], crew_name: str='AgentCrew', theme: str='light') -> InfographicRenderResult` — LLM-author Tab 1 and render the merged crew_report infographic.
