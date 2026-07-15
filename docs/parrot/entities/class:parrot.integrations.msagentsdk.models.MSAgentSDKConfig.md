---
type: Wiki Entity
title: MSAgentSDKConfig
id: class:parrot.integrations.msagentsdk.models.MSAgentSDKConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for a single agent exposed via Microsoft 365 Agents SDK.
---

# MSAgentSDKConfig

Defined in [`parrot.integrations.msagentsdk.models`](../summaries/mod:parrot.integrations.msagentsdk.models.md).

```python
class MSAgentSDKConfig
```

Configuration for a single agent exposed via Microsoft 365 Agents SDK.

Supports two authentication modes:
- Azure AD (production): provide ``client_id``, ``client_secret``, and
  ``tenant_id`` (or rely on env var fallback).
- Anonymous (local development): set ``anonymous_auth = True`` and omit
  Azure AD credentials.

Attributes:
    name: Agent name (used as key in YAML and for env var fallback prefix).
    chatbot_id: ID/name of the bot in BotManager (used with get_bot()).
    client_id: Microsoft App ID / Azure AD application (client) ID.
    client_secret: Microsoft App password / Azure AD client secret.
    tenant_id: Azure AD tenant ID for single-tenant apps; None for
        multi-tenant.
    anonymous_auth: If True, skip JWT validation. Use only for local
        development; never in production.
    api_key: Shared secret for API-Key inbound auth. When set, the wrapper
        accepts a request carrying this value in ``api_key_header`` (in
        addition to Bot Framework JWTs). Needed for Copilot Studio's
        "Microsoft 365 Agents SDK" connection, which does NOT accept the
        "None" auth option — it requires API Key or OAuth 2.0. The bot still
        needs its Azure AD credentials to authenticate the OUTBOUND reply.
    api_key_header: Header name that carries ``api_key`` (default
        ``"x-api-key"``). Must match the header configured in Copilot's
        "API Key" connection auth.
    app_type: Azure AD application type — ``"SingleTenant"`` (default) or
        ``"MultiTenant"``. This drives the OUTBOUND token authority: a
        multi-tenant Bot Framework app must mint its reply token against the
        ``botframework.com`` authority (not the bot's home tenant), or the
        Bot Connector rejects the reply with HTTP 401 (Teams especially).
    authority: Explicit OAuth authority override. When unset it is derived
        from ``app_type``/``tenant_id``. Set this only for sovereign clouds
        or non-standard setups.
    kind: Integration type discriminator — always ``"msagentsdk"``.
    welcome_message: Message sent when a new member joins the conversation.
    system_prompt_override: Override the agent's default system prompt.
    endpoint: Custom messaging route path to register for this bot. When
        unset the wrapper derives the per-bot path
        ``/api/msagentsdk/{safe_id}/messages``. Set this to the Bot
        Framework standard ``"/api/messages"`` when the channel (Copilot
        Studio, Teams, the Bot Framework Emulator) is hard-wired to that
        endpoint. The per-bot path is always ALSO registered, so the bot
        stays reachable by its canonical URL regardless of this override.
    oauth_connections: Maps tool name to Azure Bot OAuth connection name
        for per-user token acquisition via the Bot Framework Token Service.
        Example: ``{"o365": "graph_sso", "jira": "jira_oauth"}``.
        When empty, user-token acquisition is disabled (backward compatible).
    obo_scopes: Maps tool name to a list of OBO target scopes for
        Microsoft-cluster APIs that require on-behalf-of token exchange.
        Example: ``{"o365": ["https://graph.microsoft.com/.default"]}``.
        Only relevant when ``oauth_connections`` is non-empty.
    enable_semantic_cards: If True (default), a ``SemanticUIResult``
        returned by the agent (FEAT-303) is rendered as an Adaptive Card;
        if False, the plain-text path is always used even when the model
        is present.
    max_table_rows: Maximum number of table rows rendered in a Semantic
        UI table card before truncating with a "showing N of M" note
        (FEAT-303).
    max_card_bytes: Maximum serialized Semantic UI card size in bytes;
        exceeding it triggers the plain-text fallback (FEAT-303).

## Methods

- `def from_dict(cls, name: str, data: Dict[str, Any]) -> 'MSAgentSDKConfig'` — Create config from dictionary (YAML parsed data).
