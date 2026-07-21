---
type: Wiki Summary
title: parrot.auth.oauth2
id: mod:parrot.auth.oauth2
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: OAuth2 integration package for AI-Parrot.
relates_to:
- concept: mod:parrot.auth
  rel: references
- concept: mod:parrot.auth.models
  rel: references
---

# `parrot.auth.oauth2`

OAuth2 integration package for AI-Parrot.

Provides a registry of OAuth2 providers, Pydantic wire models, and the
``IntegrationsService`` that orchestrates connect / enable / disconnect flows
for the web AgentChat channel.

Channel constant
----------------
``_WEB_CHANNEL`` mirrors the ``_TELEGRAM_CHANNEL = "telegram"`` constant in
``parrot.integrations.telegram.jira_commands`` and is used to tag OAuth2
state payloads that originate from the web channel.
