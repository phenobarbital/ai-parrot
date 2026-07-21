---
type: Wiki Entity
title: RedisCredentialProvider
id: class:parrot.a2a.security.RedisCredentialProvider
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Redis-based credential provider for distributed systems.
relates_to:
- concept: class:parrot.a2a.security.CredentialProvider
  rel: extends
---

# RedisCredentialProvider

Defined in [`parrot.a2a.security`](../summaries/mod:parrot.a2a.security.md).

```python
class RedisCredentialProvider(CredentialProvider)
```

Redis-based credential provider for distributed systems.

Provides persistent, distributed credential storage with
automatic expiration support.

Example:
    import redis.asyncio as redis

    redis_client = redis.Redis(host='localhost', port=6379)
    provider = RedisCredentialProvider(redis_client)

    await provider.register_agent("DataBot", permissions=["skill:*"])

## Methods

- `async def get_api_key(self, key_id: str) -> Optional[Dict[str, Any]]` — Get API key details from Redis.
- `async def get_agent_by_token(self, token: str) -> Optional[CallerIdentity]` — Get identity by bearer token from Redis.
- `async def get_agent_by_certificate(self, fingerprint: str) -> Optional[CallerIdentity]` — Get identity by certificate fingerprint from Redis.
- `async def register_agent(self, agent_name: str, *, permissions: Optional[List[str]]=None, roles: Optional[List[str]]=None, scopes: Optional[List[str]]=None, api_key: Optional[str]=None, certificate_fingerprint: Optional[str]=None, metadata: Optional[Dict[str, Any]]=None) -> Dict[str, Any]` — Register agent in Redis.
- `async def revoke_agent(self, agent_name: str) -> bool` — Revoke agent from Redis.
- `async def store_token(self, token: str, identity: CallerIdentity, ttl: Optional[int]=None) -> None` — Store token in Redis with TTL.
- `async def validate_hmac(self, signature: str, payload: bytes, timestamp: str, agent_name: Optional[str]=None) -> Optional[CallerIdentity]` — Validate HMAC signature with replay-attack protection (Redis backend).
