---
type: Wiki Summary
title: parrot.integrations.manager
id: mod:parrot.integrations.manager
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Integration Bot Manager.
relates_to:
- concept: class:parrot.integrations.manager.IntegrationBotManager
  rel: defines
- concept: func:parrot.integrations.manager.handle_a2a_directory
  rel: defines
- concept: mod:parrot.a2a.security
  rel: references
- concept: mod:parrot.a2a.server
  rel: references
- concept: mod:parrot.auth.broker
  rel: references
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.auth.jira_oauth
  rel: references
- concept: mod:parrot.auth.o365_oauth
  rel: references
- concept: mod:parrot.auth.oauth2_routes
  rel: references
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.human
  rel: references
- concept: mod:parrot.integrations.matrix.crew
  rel: references
- concept: mod:parrot.integrations.models
  rel: references
- concept: mod:parrot.integrations.msagentsdk.wrapper
  rel: references
- concept: mod:parrot.integrations.msteams.wrapper
  rel: references
- concept: mod:parrot.integrations.slack.socket_handler
  rel: references
- concept: mod:parrot.integrations.slack.wrapper
  rel: references
- concept: mod:parrot.integrations.telegram.wrapper
  rel: references
- concept: mod:parrot.integrations.whatsapp.wrapper
  rel: references
- concept: mod:parrot.manager
  rel: references
---

# `parrot.integrations.manager`

Integration Bot Manager.

Manages lifecycle of bots (Telegram, MS Teams, WhatsApp) exposing AI-Parrot agents.
Loads configuration from {ENV_DIR}/integrations_bots.yaml (or telegram_bots.yaml fallback).

## Classes

- **`IntegrationBotManager`** — Manages bot integrations for exposed agents.

## Functions

- `async def handle_a2a_directory(request: web.Request) -> web.Response` — GET /a2a/directory — returns JSON array of all registered AgentCards.
