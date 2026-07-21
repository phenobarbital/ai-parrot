---
type: Wiki Entity
title: CredentialProvider
id: class:parrot.a2a.security.CredentialProvider
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base for credential storage and retrieval.
---

# CredentialProvider

Defined in [`parrot.a2a.security`](../summaries/mod:parrot.a2a.security.md).

```python
class CredentialProvider(ABC)
```

Abstract base for credential storage and retrieval.

Implementations can use different backends:
- InMemoryCredentialProvider: For development/testing
- RedisCredentialProvider: For distributed production systems
- DatabaseCredentialProvider: For SQL-based storage
- VaultCredentialProvider: For HashiCorp Vault integration

The provider is responsible for:
- Storing and retrieving API keys
- Validating bearer tokens
- Managing agent certificates for mTLS
- Storing agent metadata and permissions

## Methods

- `async def get_api_key(self, key_id: str) -> Optional[Dict[str, Any]]` — Get API key details by key ID or the key itself.
- `async def get_agent_by_token(self, token: str) -> Optional[CallerIdentity]` — Validate a bearer token and return the caller identity.
- `async def get_agent_by_certificate(self, fingerprint: str) -> Optional[CallerIdentity]` — Get agent identity by certificate fingerprint.
- `async def register_agent(self, agent_name: str, *, permissions: Optional[List[str]]=None, roles: Optional[List[str]]=None, scopes: Optional[List[str]]=None, api_key: Optional[str]=None, certificate_fingerprint: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None) -> Dict[str, Any]` — Register a new agent with credentials.
- `async def revoke_agent(self, agent_name: str) -> bool` — Revoke all credentials for an agent.
- `async def validate_basic_auth(self, username: str, password: str) -> Optional[CallerIdentity]` — Validate basic authentication credentials.
- `async def validate_hmac(self, signature: str, payload: bytes, timestamp: str) -> Optional[CallerIdentity]` — Validate HMAC signature.
