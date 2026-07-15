---
type: Wiki Entity
title: A2AAgentConfig
id: class:parrot.integrations.a2a.models.A2AAgentConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for a single agent exposed via the A2A protocol.
---

# A2AAgentConfig

Defined in [`parrot.integrations.a2a.models`](../summaries/mod:parrot.integrations.a2a.models.md).

```python
class A2AAgentConfig
```

Configuration for a single agent exposed via the A2A protocol.

Models a ``kind: a2a`` entry in ``integrations_bots.yaml``. Wraps a
registered agent with ``A2AServer``, optionally protected by
``A2ASecurityMiddleware`` (JWT, API key, mTLS, HMAC, or Basic auth), and
optionally wired to a ``CredentialBroker`` built from the inline
``credentials`` list.

Attributes:
    name: Agent name (used as key in YAML and for env var fallback prefix).
    chatbot_id: ID/name of the bot in BotManager (used with get_bot()).
    kind: Integration type discriminator — always ``"a2a"``.
    url: Public base URL for this A2A agent (used in the AgentCard).
    base_path: Base path for the A2A routes (default ``"/a2a"``).
    port: Dedicated TCP port for this agent. When ``None`` the agent's
        routes are mounted on the shared aiohttp app.
    tags: Tags describing the agent, surfaced in the AgentCard.
    welcome_message: Message sent when a new conversation starts.
    system_prompt_override: Override the agent's default system prompt.
    jwt_secret: Shared secret for JWT auth on inbound A2A requests.
    api_key: Shared secret for API-Key auth on inbound A2A requests.
    api_key_header: Header name that carries ``api_key`` (default
        ``"X-API-Key"``).
    mtls_ca_cert: Path to the CA cert used to validate client certs for
        mTLS auth.
    hmac_secret: Shared secret for HMAC-signed request auth.
    basic_credentials: Mapping of username to password for Basic auth.
    security_policy: Raw ``SecurityPolicy`` fields (require_auth,
        allowed_schemes, allowed_agents, etc.), forwarded as-is.
    enable_credential_broker: If True, build a ``CredentialBroker`` from
        ``credentials`` and pass it to ``A2AServer``.
    credentials: Inline list of provider credential dicts (raw, parsed
        into ``ProviderCredentialConfig`` at startup time).

## Methods

- `def from_dict(cls, name: str, data: Dict[str, Any]) -> 'A2AAgentConfig'` — Create config from dictionary (YAML parsed data).
