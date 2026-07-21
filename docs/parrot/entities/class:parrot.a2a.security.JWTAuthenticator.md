---
type: Wiki Entity
title: JWTAuthenticator
id: class:parrot.a2a.security.JWTAuthenticator
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: JWT-based authentication for A2A communication.
---

# JWTAuthenticator

Defined in [`parrot.a2a.security`](../summaries/mod:parrot.a2a.security.md).

```python
class JWTAuthenticator
```

JWT-based authentication for A2A communication.

Supports both symmetric (HS256) and asymmetric (RS256) algorithms.

Example:
    # Symmetric (shared secret)
    auth = JWTAuthenticator(
        secret_key="your-secret-key",
        algorithm="HS256",
        issuer="a2a-network",
    )

    # Create token for an agent
    token = auth.create_token(
        agent_name="DataBot",
        permissions=["skill:*"],
        expires_in=3600,  # 1 hour
    )

    # Validate token
    identity = await auth.validate_token(token)

    # Asymmetric (RSA key pair)
    auth = JWTAuthenticator(
        private_key=private_key_pem,
        public_key=public_key_pem,
        algorithm="RS256",
    )

## Methods

- `def create_token(self, agent_name: str, *, agent_url: Optional[str]=None, permissions: Optional[List[str]]=None, roles: Optional[List[str]]=None, scopes: Optional[List[str]]=None, metadata: Optional[Dict[str, Any]]=None, expires_in: Optional[int]=None) -> str` — Create a JWT token for an agent.
- `async def validate_token(self, token: str) -> Optional[CallerIdentity]` — Validate a JWT token and return the caller identity.
- `def decode_without_verification(self, token: str) -> Optional[Dict[str, Any]]` — Decode JWT without verifying signature.
