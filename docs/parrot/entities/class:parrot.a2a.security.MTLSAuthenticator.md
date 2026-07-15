---
type: Wiki Entity
title: MTLSAuthenticator
id: class:parrot.a2a.security.MTLSAuthenticator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mutual TLS (mTLS) authentication for A2A communication.
---

# MTLSAuthenticator

Defined in [`parrot.a2a.security`](../summaries/mod:parrot.a2a.security.md).

```python
class MTLSAuthenticator
```

Mutual TLS (mTLS) authentication for A2A communication.

Validates client certificates and extracts identity information.

Example:
    auth = MTLSAuthenticator(
        ca_cert_path="/path/to/ca.crt",
        credential_provider=provider,
    )

    # Create SSL context for server
    ssl_context = auth.create_server_ssl_context(
        cert_path="/path/to/server.crt",
        key_path="/path/to/server.key",
    )

    # Validate client certificate from request
    identity = await auth.validate_certificate(request)

## Methods

- `def create_server_ssl_context(self, cert_path: str, key_path: str, *, key_password: Optional[str]=None) -> ssl.SSLContext` — Create SSL context for server with mTLS support.
- `def create_client_ssl_context(self, cert_path: str, key_path: str, *, key_password: Optional[str]=None) -> ssl.SSLContext` — Create SSL context for client with mTLS support.
- `def get_certificate_fingerprint(cert_der: bytes) -> str` — Calculate SHA-256 fingerprint of a certificate.
- `async def validate_certificate(self, request: web.Request) -> Optional[CallerIdentity]` — Validate client certificate from an aiohttp request.
