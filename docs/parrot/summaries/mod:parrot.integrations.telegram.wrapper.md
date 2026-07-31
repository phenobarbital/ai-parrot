---
type: Wiki Summary
title: parrot.integrations.telegram.wrapper
id: mod:parrot.integrations.telegram.wrapper
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Telegram Agent Wrapper.
relates_to:
- concept: class:parrot.integrations.telegram.wrapper.TelegramAgentWrapper
  rel: defines
- concept: mod:parrot.auth.context
  rel: references
- concept: mod:parrot.auth.permission
  rel: references
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.core
  rel: references
- concept: mod:parrot.core.exceptions
  rel: references
- concept: mod:parrot.integrations.core.auth.post_auth
  rel: references
- concept: mod:parrot.integrations.core.state
  rel: references
- concept: mod:parrot.integrations.parser
  rel: references
- concept: mod:parrot.integrations.telegram.auth
  rel: references
- concept: mod:parrot.integrations.telegram.callbacks
  rel: references
- concept: mod:parrot.integrations.telegram.context
  rel: references
- concept: mod:parrot.integrations.telegram.decorators
  rel: references
- concept: mod:parrot.integrations.telegram.filters
  rel: references
- concept: mod:parrot.integrations.telegram.jira_commands
  rel: references
- concept: mod:parrot.integrations.telegram.mcp_commands
  rel: references
- concept: mod:parrot.integrations.telegram.models
  rel: references
- concept: mod:parrot.integrations.telegram.office365_commands
  rel: references
- concept: mod:parrot.integrations.telegram.operator_commands
  rel: references
- concept: mod:parrot.integrations.telegram.post_auth_jira
  rel: references
- concept: mod:parrot.integrations.telegram.utils
  rel: references
- concept: mod:parrot.integrations.utils
  rel: references
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.services.identity_mapping
  rel: references
- concept: mod:parrot.services.vault_token_sync
  rel: references
- concept: mod:parrot.tools.reminder
  rel: references
- concept: mod:parrot.voice.transcriber
  rel: references
- concept: mod:parrot.voice.tts.models
  rel: references
- concept: mod:parrot.voice.tts.synthesizer
  rel: references
---

# `parrot.integrations.telegram.wrapper`

Telegram Agent Wrapper.

Connects Telegram messages to AI-Parrot agents with per-chat conversation memory.
Supports:
- Direct messages (private chats)
- Group messages with @mentions
- Group commands (/ask)
- Channel posts (optional)

## Classes

- **`TelegramAgentWrapper(OperatorCommandsMixin)`** — Wraps an Agent/AgentCrew/AgentFlow for Telegram integration.
