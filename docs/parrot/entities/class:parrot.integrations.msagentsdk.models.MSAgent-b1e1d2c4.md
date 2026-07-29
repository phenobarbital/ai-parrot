---
type: Wiki Entity
title: MSAgentIntegrationConfig
id: class:parrot.integrations.msagentsdk.models.MSAgentIntegrationConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for a full-featured Microsoft Agents SDK bot exposed via
---

# MSAgentIntegrationConfig

Defined in [`parrot.integrations.msagentsdk.models`](../summaries/mod:parrot.integrations.msagentsdk.models.md).

```python
class MSAgentIntegrationConfig
```

Configuration for a full-featured Microsoft Agents SDK bot exposed via
``kind: msagent`` entries in ``integrations_bots.yaml``.

Extends the minimal ``MSAgentSDKConfig`` surface with a
``CredentialBroker`` (built from the inline ``credentials`` list), O365
OAuth2 SSO/OBO infrastructure, and an automatic A2A companion surface
(sharing the same broker). Use ``to_msagentsdk_config()`` to obtain the
inner ``MSAgentSDKConfig`` consumed by ``MSAgentSDKWrapper``.

Attributes:
    name: Agent name (used as key in YAML and for env var fallback prefix).
    chatbot_id: ID/name of the bot in BotManager (used with get_bot()).
    kind: Integration type discriminator — always ``"msagent"``.
    microsoft_app_id: Microsoft App ID / Azure AD application (client) ID.
        Forwarded to ``MSAgentSDKConfig.client_id``.
    microsoft_app_password: Microsoft App password / Azure AD client
        secret. Forwarded to ``MSAgentSDKConfig.client_secret``.
    microsoft_tenant_id: Azure AD tenant ID for single-tenant apps.
        Forwarded to ``MSAgentSDKConfig.tenant_id``.
    anonymous_auth: If True, skip JWT validation (local dev only).
    api_key: Shared secret for API-Key inbound auth.
    api_key_header: Header name that carries ``api_key``.
    app_type: Azure AD application type — ``"SingleTenant"`` or
        ``"MultiTenant"``.
    authority: Explicit OAuth authority override.
    welcome_message: Message sent when a new member joins.
    system_prompt_override: Override the agent's default system prompt.
    endpoint: Custom messaging route path override.
    oauth_connections: Maps tool name to Azure Bot OAuth connection name.
    obo_scopes: Maps tool name to a list of OBO target scopes.
    url: Public base URL for the automatic A2A companion surface.
    tags: Tags describing the agent, surfaced in the companion AgentCard.
    enable_credential_broker: If True, build a ``CredentialBroker`` from
        ``credentials`` and pass it to ``MSAgentSDKWrapper`` and the A2A
        companion.
    credentials: Inline list of provider credential dicts (raw, parsed
        into ``ProviderCredentialConfig`` at startup time).
    o365_client_id: Azure AD application (client) ID for O365 OAuth2 SSO.
    o365_client_secret: Azure AD client secret for O365 OAuth2 SSO.
    o365_tenant_id: Azure AD tenant ID for O365 OAuth2 SSO.
    redirect_uri: OAuth2 redirect URI for the O365 SSO flow.
    jwt_secret: Shared secret for JWT auth on the A2A companion surface.
    debug: If True, enable verbose debug logging for this bot.

## Methods

- `def from_dict(cls, name: str, data: Dict[str, Any]) -> 'MSAgentIntegrationConfig'` — Create config from dictionary (YAML parsed data).
- `def to_msagentsdk_config(self) -> MSAgentSDKConfig` — Convert to the inner ``MSAgentSDKConfig`` used by ``MSAgentSDKWrapper``.
