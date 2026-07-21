---
type: Wiki Summary
title: parrot.tools.agent
id: mod:parrot.tools.agent
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Complete Fixed AgentTool with Correct Schema Structure
relates_to:
- concept: class:parrot.tools.agent.AgentContext
  rel: defines
- concept: class:parrot.tools.agent.AgentTool
  rel: defines
- concept: class:parrot.tools.agent.QuestionInput
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.models.crew
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.tools.agent`

Complete Fixed AgentTool with Correct Schema Structure

## Classes

- **`AgentContext`** — Context passed between agents in orchestration.
- **`QuestionInput(BaseModel)`** — Input schema for AgentTool - defines the question parameter.
- **`AgentTool(AbstractTool)`** — Wraps any BasicAgent/AbstractBot as a tool for use by other agents.
