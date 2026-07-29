---
type: Wiki Summary
title: parrot.integrations.slack.assistant
id: mod:parrot.integrations.slack.assistant
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Slack Agents & AI Apps integration for AI-Parrot.
relates_to:
- concept: class:parrot.integrations.slack.assistant.SlackAssistantHandler
  rel: defines
- concept: mod:parrot.integrations.parser
  rel: references
- concept: mod:parrot.integrations.slack.interactive
  rel: references
- concept: mod:parrot.integrations.slack.wrapper
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
---

# `parrot.integrations.slack.assistant`

Slack Agents & AI Apps integration for AI-Parrot.

Implements the assistant container experience with split-view panel,
suggested prompts, loading states, thread titles, and streaming.

Part of FEAT-010: Slack Wrapper Integration Enhancements.

Ref: https://api.slack.com/docs/apps/ai

## Classes

- **`SlackAssistantHandler`** — Handles Slack's Agents & AI Apps events.
