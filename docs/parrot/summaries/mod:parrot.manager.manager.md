---
type: Wiki Summary
title: parrot.manager.manager
id: mod:parrot.manager.manager
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Chatbot Manager.
relates_to:
- concept: class:parrot.manager.manager.BotManager
  rel: defines
- concept: mod:parrot.auth.agent_guard
  rel: references
- concept: mod:parrot.auth.oauth2.jira_provider
  rel: references
- concept: mod:parrot.auth.oauth2.registry
  rel: references
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.bots.agent
  rel: references
- concept: mod:parrot.bots.basic
  rel: references
- concept: mod:parrot.bots.chatbot
  rel: references
- concept: mod:parrot.bots.flows.crew
  rel: references
- concept: mod:parrot.bots.prompts.domain_layers
  rel: references
- concept: mod:parrot.bots.prompts.layers
  rel: references
- concept: mod:parrot.bots.prompts.presets
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.exceptions
  rel: references
- concept: mod:parrot.handlers
  rel: references
- concept: mod:parrot.handlers.agent
  rel: references
- concept: mod:parrot.handlers.agent_voice
  rel: references
- concept: mod:parrot.handlers.agents.data
  rel: references
- concept: mod:parrot.handlers.agents.ephemeral
  rel: references
- concept: mod:parrot.handlers.agents.factory
  rel: references
- concept: mod:parrot.handlers.agents.users
  rel: references
- concept: mod:parrot.handlers.avatar
  rel: references
- concept: mod:parrot.handlers.avatar_fullmode
  rel: references
- concept: mod:parrot.handlers.chat
  rel: references
- concept: mod:parrot.handlers.chat_interaction
  rel: references
- concept: mod:parrot.handlers.config_handler
  rel: references
- concept: mod:parrot.handlers.credentials
  rel: references
- concept: mod:parrot.handlers.crew.execution_handler
  rel: references
- concept: mod:parrot.handlers.crew.execution_history_handler
  rel: references
- concept: mod:parrot.handlers.crew.handler
  rel: references
- concept: mod:parrot.handlers.crew.redis_persistence
  rel: references
- concept: mod:parrot.handlers.crew.special_nodes
  rel: references
- concept: mod:parrot.handlers.crew.tool_catalog
  rel: references
- concept: mod:parrot.handlers.dashboard_handler
  rel: references
- concept: mod:parrot.handlers.database
  rel: references
- concept: mod:parrot.handlers.datasets
  rel: references
- concept: mod:parrot.handlers.infographic
  rel: references
- concept: mod:parrot.handlers.integrations
  rel: references
- concept: mod:parrot.handlers.knowledge
  rel: references
- concept: mod:parrot.handlers.liveavatar_output
  rel: references
- concept: mod:parrot.handlers.mcp_helper
  rel: references
- concept: mod:parrot.handlers.models
  rel: references
- concept: mod:parrot.handlers.print_pdf
  rel: references
- concept: mod:parrot.handlers.prompt
  rel: references
- concept: mod:parrot.handlers.stream
  rel: references
- concept: mod:parrot.handlers.testing_handler
  rel: references
- concept: mod:parrot.handlers.tools_catalog
  rel: references
- concept: mod:parrot.handlers.web_hitl
  rel: references
- concept: mod:parrot.integrations
  rel: references
- concept: mod:parrot.integrations.liveavatar
  rel: references
- concept: mod:parrot.manager.ephemeral
  rel: references
- concept: mod:parrot.models.crew_definition
  rel: references
- concept: mod:parrot.openapi.config
  rel: references
- concept: mod:parrot.registry
  rel: references
- concept: mod:parrot.rerankers.factory
  rel: references
- concept: mod:parrot.rerankers.llm
  rel: references
- concept: mod:parrot.storage
  rel: references
- concept: mod:parrot.stores.parents.factory
  rel: references
- concept: mod:parrot.voice.handler
  rel: references
---

# `parrot.manager.manager`

Chatbot Manager.

Tool for instanciate, managing and interacting with Chatbot through APIs.

## Classes

- **`BotManager`** — BotManager.
