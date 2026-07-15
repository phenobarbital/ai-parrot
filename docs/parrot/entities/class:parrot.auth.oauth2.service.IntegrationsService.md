---
type: Wiki Entity
title: IntegrationsService
id: class:parrot.auth.oauth2.service.IntegrationsService
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Orchestrates OAuth2 provider registry, persistence, and PBAC checks.
---

# IntegrationsService

Defined in [`parrot.auth.oauth2.service`](../summaries/mod:parrot.auth.oauth2.service.md).

```python
class IntegrationsService
```

Orchestrates OAuth2 provider registry, persistence, and PBAC checks.

All public methods are coroutines.  The service is stateless — instantiate
once per request or once per application lifetime.

## Methods

- `async def list_for_user(self, user_id: str, agent_id: str, request: Any=None) -> List[IntegrationDescriptor]` — Return a PBAC-filtered list of integration descriptors.
- `async def start_connect(self, user_id: str, agent_id: str, provider_id: str, return_origin: str) -> ConnectInitResponse` — Validate the return origin and generate the OAuth2 authorization URL.
- `async def confirm_enable(self, user_id: str, agent_id: str, provider_id: str) -> IntegrationDescriptor` — Enable a connected integration on a specific agent.
- `async def disconnect(self, user_id: str, agent_id: str, provider_id: str) -> DisconnectResponse` — Disconnect a provider for a user.
- `async def persist_credential(self, user_id: str, provider_id: str, token_set: Any) -> UsersIntegrationRow` — Upsert a ``users_integrations`` row from any provider's token set.
