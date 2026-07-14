---
type: Wiki Summary
title: parrot.handlers.infographic
id: mod:parrot.handlers.infographic
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: HTTP handler for get_infographic() generation, plus template and theme
relates_to:
- concept: class:parrot.handlers.infographic.InfographicTalk
  rel: defines
- concept: mod:parrot.handlers.agent
  rel: references
- concept: mod:parrot.helpers.infographics
  rel: references
- concept: mod:parrot.storage.models
  rel: references
---

# `parrot.handlers.infographic`

HTTP handler for get_infographic() generation, plus template and theme
discovery/registration endpoints.

Routes (registered by BotManager in TASK-651):
    POST /api/v1/agents/infographic/{agent_id}          — generate infographic
    GET  /api/v1/agents/infographic/templates           — list templates
    GET  /api/v1/agents/infographic/templates/{name}    — get template
    POST /api/v1/agents/infographic/templates           — register template
    GET  /api/v1/agents/infographic/themes              — list themes
    GET  /api/v1/agents/infographic/themes/{name}       — get theme
    POST /api/v1/agents/infographic/themes              — register theme

## Classes

- **`InfographicTalk(AgentTalk)`** — Dedicated HTTP handler for bot.get_infographic() plus template/theme
