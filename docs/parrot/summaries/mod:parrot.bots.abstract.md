---
type: Wiki Summary
title: parrot.bots.abstract
id: mod:parrot.bots.abstract
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract Bot interface.
relates_to:
- concept: class:parrot.bots.abstract.AbstractBot
  rel: defines
- concept: mod:parrot.auth.broker
  rel: references
- concept: mod:parrot.auth.context
  rel: references
- concept: mod:parrot.bots.dynamic_values
  rel: references
- concept: mod:parrot.bots.kb
  rel: references
- concept: mod:parrot.bots.middleware
  rel: references
- concept: mod:parrot.bots.prompts
  rel: references
- concept: mod:parrot.bots.prompts.agent_context
  rel: references
- concept: mod:parrot.bots.prompts.layers
  rel: references
- concept: mod:parrot.bots.prompts.presets
  rel: references
- concept: mod:parrot.bots.prompts.segments
  rel: references
- concept: mod:parrot.bots.stores
  rel: references
- concept: mod:parrot.clients.base
  rel: references
- concept: mod:parrot.clients.factory
  rel: references
- concept: mod:parrot.clients.models
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.core.events.lifecycle.events
  rel: references
- concept: mod:parrot.core.events.lifecycle.legacy_bridge
  rel: references
- concept: mod:parrot.core.events.lifecycle.mixin
  rel: references
- concept: mod:parrot.core.events.lifecycle.trace
  rel: references
- concept: mod:parrot.embeddings
  rel: references
- concept: mod:parrot.exceptions
  rel: references
- concept: mod:parrot.interfaces
  rel: references
- concept: mod:parrot.interfaces.database
  rel: references
- concept: mod:parrot.mcp
  rel: references
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.models.infographic
  rel: references
- concept: mod:parrot.models.infographic_templates
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.models.status
  rel: references
- concept: mod:parrot.models.stores
  rel: references
- concept: mod:parrot.outputs
  rel: references
- concept: mod:parrot.outputs.formats
  rel: references
- concept: mod:parrot.registry.routing
  rel: references
- concept: mod:parrot.rerankers.abstract
  rel: references
- concept: mod:parrot.security
  rel: references
- concept: mod:parrot.security.prompt_injection
  rel: references
- concept: mod:parrot.stores
  rel: references
- concept: mod:parrot.stores.arango
  rel: references
- concept: mod:parrot.stores.faiss_store
  rel: references
- concept: mod:parrot.stores.kb
  rel: references
- concept: mod:parrot.stores.kb.store
  rel: references
- concept: mod:parrot.stores.models
  rel: references
- concept: mod:parrot.stores.postgres
  rel: references
- concept: mod:parrot.tools
  rel: references
- concept: mod:parrot.tools._enhance_html_check
  rel: references
- concept: mod:parrot.tools.interactive.catalog_registry
  rel: references
- concept: mod:parrot.tools.interactive_toolkit
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
- concept: mod:parrot.utils.helpers
  rel: references
- concept: mod:parrot_tools.multistoresearch
  rel: references
---

# `parrot.bots.abstract`

Abstract Bot interface.

## Classes

- **`AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, EventEmitterMixin, ToolInterface, VectorInterface, ABC)`** — AbstractBot.
