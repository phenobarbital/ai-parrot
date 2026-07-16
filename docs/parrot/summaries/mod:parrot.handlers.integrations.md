---
type: Wiki Summary
title: parrot.handlers.integrations
id: mod:parrot.handlers.integrations
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTTP handler for the OAuth2 integrations endpoints.
relates_to:
- concept: class:parrot.handlers.integrations.IntegrationsHandler
  rel: defines
- concept: mod:parrot.auth.oauth2.models
  rel: references
- concept: mod:parrot.auth.oauth2.service
  rel: references
- concept: mod:parrot.conf
  rel: references
---

# `parrot.handlers.integrations`

HTTP handler for the OAuth2 integrations endpoints.

Exposes four routes under ``/api/v1/agents/integrations/{agent_id}``:

- ``GET    /api/v1/agents/integrations/{agent_id}``
  → list integrations for the current user.
- ``POST   /api/v1/agents/integrations/{agent_id}/{provider}/connect``
  → initiate the OAuth2 popup flow; returns auth_url + state nonce.
- ``POST   /api/v1/agents/integrations/{agent_id}/{provider}/enable``
  → confirm-enable after the popup completes; writes user_agent_toolkits.
- ``DELETE /api/v1/agents/integrations/{agent_id}/{provider}``
  → disconnect; deletes both persistence rows.

The handler delegates all business logic to
:class:`~parrot.integrations.oauth2.service.IntegrationsService`.

## Classes

- **`IntegrationsHandler(BaseView)`** — Aiohttp class-based view for the OAuth2 integrations API.
