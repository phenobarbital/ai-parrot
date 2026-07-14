---
type: Wiki Entity
title: SecureA2AClient
id: class:parrot.a2a.security.SecureA2AClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wrapper for A2AClient with automatic authentication.
---

# SecureA2AClient

Defined in [`parrot.a2a.security`](../summaries/mod:parrot.a2a.security.md).

```python
class SecureA2AClient
```

Wrapper for A2AClient with automatic authentication.

Handles credential management and automatic token refresh.

Example:
    # With API key
    client = SecureA2AClient(
        "http://agent:8080",
        auth_scheme=AuthScheme.API_KEY,
        api_key="your-api-key",
    )

    # With JWT
    client = SecureA2AClient(
        "http://agent:8080",
        auth_scheme=AuthScheme.BEARER,
        token=jwt_token,
    )

    # With JWT auto-refresh
    client = SecureA2AClient(
        "http://agent:8080",
        auth_scheme=AuthScheme.BEARER,
        jwt_authenticator=jwt_auth,
        agent_name="MyAgent",
        permissions=["skill:*"],
    )

    # With mTLS
    client = SecureA2AClient(
        "https://agent:8443",
        auth_scheme=AuthScheme.MTLS,
        cert_path="/path/to/client.crt",
        key_path="/path/to/client.key",
        ca_cert_path="/path/to/ca.crt",
    )

    async with client:
        task = await client.send_message("Hello!")

## Methods

- `async def connect(self) -> 'A2AClient'` — Create and return a configured A2AClient.
- `async def disconnect(self) -> None` — Disconnect the client.
- `async def send_message(self, content: str, **kwargs)` — Send message through secure client.
- `async def stream_message(self, content: str, **kwargs)` — Stream message through secure client.
- `async def invoke_skill(self, skill_id: str, params=None, **kwargs)` — Invoke skill through secure client.
