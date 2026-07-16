---
type: Wiki Entity
title: HITLDemoAgent
id: class:parrot.agents.demo.HITLDemoAgent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Travel Concierge — demonstrates the web HITL (Human-in-the-Loop) flow.
relates_to:
- concept: class:parrot.bots.agent.BasicAgent
  rel: extends
---

# HITLDemoAgent

Defined in [`parrot.agents.demo`](../summaries/mod:parrot.agents.demo.md).

```python
class HITLDemoAgent(BasicAgent)
```

Travel Concierge — demonstrates the web HITL (Human-in-the-Loop) flow.

This agent uses :class:`~parrot.handlers.web_hitl.WebHumanTool` to ask
interactive questions over WebSocket, :class:`BookFlightTool` to simulate
flight booking (with intentional ``HumanInteractionInterrupt`` on bad dates),
and :class:`~parrot.core.tools.handoff.HandoffTool` for explicit handoff.

Attributes:
    agent_id: Registry name for this agent, fixed to ``"hitl_demo"``.

## Methods

- `def agent_tools(self) -> List[AbstractTool]` — Return the tools used by this agent.
