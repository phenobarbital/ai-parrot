---
type: Wiki Summary
title: parrot.auth.oauth2.models
id: mod:parrot.auth.oauth2.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic wire models for the OAuth2 integration layer.
relates_to:
- concept: class:parrot.auth.oauth2.models.AuthRequiredEnvelope
  rel: defines
- concept: class:parrot.auth.oauth2.models.ConnectInitRequest
  rel: defines
- concept: class:parrot.auth.oauth2.models.ConnectInitResponse
  rel: defines
- concept: class:parrot.auth.oauth2.models.DisconnectResponse
  rel: defines
- concept: class:parrot.auth.oauth2.models.EnableResponse
  rel: defines
- concept: class:parrot.auth.oauth2.models.IntegrationDescriptor
  rel: defines
- concept: class:parrot.auth.oauth2.models.UserAgentToolkitRow
  rel: defines
- concept: class:parrot.auth.oauth2.models.UsersIntegrationRow
  rel: defines
---

# `parrot.auth.oauth2.models`

Pydantic wire models for the OAuth2 integration layer.

These models represent the data contracts between:
- the HTTP API (``IntegrationsHandler``) and its callers,
- the ``AgentTalk`` envelope response, and
- the DocumentDB persistence layer (``UsersIntegrationRow``,
  ``UserAgentToolkitRow``).

## Classes

- **`IntegrationDescriptor(BaseModel)`** — Describes one OAuth2-capable integration for the menu listing.
- **`ConnectInitRequest(BaseModel)`** — Request body for ``POST .../integrations/{agent_id}/{provider}/connect``.
- **`ConnectInitResponse(BaseModel)`** — Response for the connect-init endpoint.
- **`EnableResponse(BaseModel)`** — Response for the confirm-enable endpoint.
- **`DisconnectResponse(BaseModel)`** — Response for the disconnect endpoint.
- **`AuthRequiredEnvelope(BaseModel)`** — Single-body response returned by ``AgentTalk`` when a tool raises
- **`UsersIntegrationRow(BaseModel)`** — Durable credential record stored in the ``users_integrations`` collection.
- **`UserAgentToolkitRow(BaseModel)`** — Per-``(user, agent, toolkit)`` enablement record stored in
