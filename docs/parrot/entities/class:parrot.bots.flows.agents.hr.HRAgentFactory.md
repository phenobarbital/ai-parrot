---
type: Wiki Entity
title: HRAgentFactory
id: class:parrot.bots.flows.agents.hr.HRAgentFactory
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Factory for creating HR-specific agent orchestration systems.
---

# HRAgentFactory

Defined in [`parrot.bots.flows.agents.hr`](../summaries/mod:parrot.bots.flows.agents.hr.md).

```python
class HRAgentFactory
```

Factory for creating HR-specific agent orchestration systems.

## Methods

- `def create_hr_orchestrator(hr_agent: BasicAgent=None, employee_data_agent: BasicAgent=None, shared_tools: List[AbstractTool]=None) -> OrchestratorAgent` — Create an HR orchestrator with specialized agents.
- `def create_hr_crew(agents: List[BasicAgent], shared_tools: List[AbstractTool]=None) -> AgentCrew` — Create an HR processing crew that processes requests in sequence.
