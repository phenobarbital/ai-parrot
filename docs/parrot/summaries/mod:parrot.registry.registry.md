---
type: Wiki Summary
title: parrot.registry.registry
id: mod:parrot.registry.registry
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Agent Auto-Registration System for AI-Parrot.
relates_to:
- concept: class:parrot.registry.registry.AgentFactory
  rel: defines
- concept: class:parrot.registry.registry.AgentRegistry
  rel: defines
- concept: class:parrot.registry.registry.BotConfig
  rel: defines
- concept: class:parrot.registry.registry.BotMetadata
  rel: defines
- concept: class:parrot.registry.registry.PromptConfig
  rel: defines
- concept: mod:parrot
  rel: references
- concept: mod:parrot.auth.agent_guard
  rel: references
- concept: mod:parrot.auth.models
  rel: references
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.bots.prompts
  rel: references
- concept: mod:parrot.bots.prompts.domain_layers
  rel: references
- concept: mod:parrot.bots.prompts.layers
  rel: references
- concept: mod:parrot.bots.prompts.presets
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.core.events.lifecycle.yaml_loader
  rel: references
- concept: mod:parrot.mcp
  rel: references
- concept: mod:parrot.models.basic
  rel: references
- concept: mod:parrot.models.stores
  rel: references
---

# `parrot.registry.registry`

Agent Auto-Registration System for AI-Parrot.

This module provides multiple approaches for automatically discovering
and registering agents from the agents/ directory.

## Classes

- **`AgentFactory(Protocol)`** — Protocol for agent factory callable.
- **`BotMetadata`** — Metadata about a discovered Bot or Agent.
- **`PromptConfig(BaseModel)`** — Declarative prompt layer configuration from YAML.
- **`BotConfig(BaseModel)`** — Configuration for the bot in config-based discovery.
- **`AgentRegistry`** — Central registry for managing Bo/Agent discovery and registration.
