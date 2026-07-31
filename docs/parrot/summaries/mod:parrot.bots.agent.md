---
type: Wiki Summary
title: parrot.bots.agent
id: mod:parrot.bots.agent
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.bots.agent
relates_to:
- concept: class:parrot.bots.agent.Agent
  rel: defines
- concept: class:parrot.bots.agent.BasicAgent
  rel: defines
- concept: mod:parrot.bots.chatbot
  rel: references
- concept: mod:parrot.bots.prompts
  rel: references
- concept: mod:parrot.bots.prompts.domain_layers
  rel: references
- concept: mod:parrot.clients.google
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.mcp
  rel: references
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.models.google
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.notifications
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.agent
  rel: references
- concept: mod:parrot.tools.json_tool
  rel: references
- concept: mod:parrot.tools.pythonpandas
  rel: references
- concept: mod:parrot.tools.pythonrepl
  rel: references
- concept: mod:parrot.tools.working_memory
  rel: references
- concept: mod:parrot_tools.pdfprint
  rel: references
- concept: mod:parrot_tools.powerpoint
  rel: references
---

# `parrot.bots.agent`

## Classes

- **`BasicAgent(Chatbot, NotificationMixin)`** — Represents an Agent in Navigator.
- **`Agent(BasicAgent)`** — A general-purpose agent with no additional tools.
