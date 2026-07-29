---
type: Wiki Summary
title: parrot.integrations.slack.wrapper
id: mod:parrot.integrations.slack.wrapper
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Slack Agent Wrapper.
relates_to:
- concept: class:parrot.integrations.slack.wrapper.SlackAgentWrapper
  rel: defines
- concept: func:parrot.integrations.slack.wrapper.convert_markdown_to_mrkdwn
  rel: defines
- concept: mod:parrot.auth.jira_oauth
  rel: references
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.integrations.parser
  rel: references
- concept: mod:parrot.integrations.slack.assistant
  rel: references
- concept: mod:parrot.integrations.slack.commands
  rel: references
- concept: mod:parrot.integrations.slack.commands.jira_commands
  rel: references
- concept: mod:parrot.integrations.slack.dedup
  rel: references
- concept: mod:parrot.integrations.slack.interactive
  rel: references
- concept: mod:parrot.integrations.slack.models
  rel: references
- concept: mod:parrot.integrations.slack.oauth_callback
  rel: references
- concept: mod:parrot.integrations.slack.security
  rel: references
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
---

# `parrot.integrations.slack.wrapper`

Slack Agent Wrapper.

Handles Slack Events API and slash commands with async processing,
signature verification, and event deduplication.

## Classes

- **`SlackAgentWrapper`** — Wrap an AI-Parrot agent for Slack Events and slash commands.

## Functions

- `def convert_markdown_to_mrkdwn(text: str) -> str` — Convert standard Markdown to Slack mrkdwn format.
