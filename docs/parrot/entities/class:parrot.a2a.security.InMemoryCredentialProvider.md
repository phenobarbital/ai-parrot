---
type: Wiki Entity
title: InMemoryCredentialProvider
id: class:parrot.a2a.security.InMemoryCredentialProvider
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: In-memory credential provider for development and testing.
relates_to:
- concept: class:parrot.a2a.security.CredentialProvider
  rel: extends
---

# InMemoryCredentialProvider

Defined in [`parrot.a2a.security`](../summaries/mod:parrot.a2a.security.md).

```python
class InMemoryCredentialProvider(CredentialProvider)
```

In-memory credential provider for development and testing.

NOT suitable for production - credentials are lost on restart.

Example:
    provider = InMemoryCredentialProvider()

    # Register an agent
    result = await provider.register_agent(
        "DataBot",
        permissions=["skill:analyze", "skill:query"],
        roles=["analyst"],
    )
    api_key = result["api_key"]

    # Validate later
    identity = await provider.get_agent_by_token(token)

## Methods

- `async def get_api_key(self, key_id: str) -> Optional[Dict[str, Any]]` — Get API key details.
- `async def get_agent_by_token(self, token: str) -> Optional[CallerIdentity]` — Get identity by bearer token.
- `async def get_agent_by_certificate(self, fingerprint: str) -> Optional[CallerIdentity]` — Get identity by certificate fingerprint.
- `async def register_agent(self, agent_name: str, *, permissions: Optional[List[str]]=None, roles: Optional[List[str]]=None, scopes: Optional[List[str]]=None, api_key: Optional[str]=None, certificate_fingerprint: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None) -> Dict[str, Any]` — Register a new agent.
- `async def revoke_agent(self, agent_name: str) -> bool` — Revoke all credentials for an agent.
- `async def store_token(self, token: str, identity: CallerIdentity) -> None` — Store a token for later validation.
- `async def validate_hmac(self, signature: str, payload: bytes, timestamp: str, agent_name: Optional[str]=None) -> Optional[CallerIdentity]` — Validate HMAC signature with replay-attack protection.
- `def get_hmac_secret(self, agent_name: str) -> Optional[str]` — Get HMAC secret for an agent (for client-side signing).
