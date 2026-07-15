---
type: Wiki Summary
title: parrot.integrations.msteams.wrapper
id: mod:parrot.integrations.msteams.wrapper
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: MS Teams Agent Wrapper.
relates_to:
- concept: class:parrot.integrations.msteams.wrapper.DebugMemoryStorage
  rel: defines
- concept: class:parrot.integrations.msteams.wrapper.MSTeamsAgentWrapper
  rel: defines
- concept: mod:parrot.auth.jira_oauth
  rel: references
- concept: mod:parrot.forms
  rel: references
- concept: mod:parrot.integrations.msteams.adapter
  rel: references
- concept: mod:parrot.integrations.msteams.commands
  rel: references
- concept: mod:parrot.integrations.msteams.commands.agent_commands
  rel: references
- concept: mod:parrot.integrations.msteams.commands.jira_commands
  rel: references
- concept: mod:parrot.integrations.msteams.dialogs.factory
  rel: references
- concept: mod:parrot.integrations.msteams.dialogs.orchestrator
  rel: references
- concept: mod:parrot.integrations.msteams.handler
  rel: references
- concept: mod:parrot.integrations.msteams.models
  rel: references
- concept: mod:parrot.integrations.msteams.oauth_callback
  rel: references
- concept: mod:parrot.integrations.msteams.voice
  rel: references
- concept: mod:parrot.integrations.parser
  rel: references
---

# `parrot.integrations.msteams.wrapper`

MS Teams Agent Wrapper.

Connects MS Teams messages to AI-Parrot agents.

## Classes

- **`DebugMemoryStorage(MemoryStorage)`**
- **`MSTeamsAgentWrapper(ActivityHandler, MessageHandler)`** — Wraps an Agent for MS Teams integration.
