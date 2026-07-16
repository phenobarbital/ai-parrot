---
type: Wiki Entity
title: NetSuiteM2MAuth
id: class:parrot.mcp.oauth.NetSuiteM2MAuth
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: OAuth2 Client Credentials (M2M) for NetSuite using certificate-based JWT
  assertion.
---

# NetSuiteM2MAuth

Defined in [`parrot.mcp.oauth`](../summaries/mod:parrot.mcp.oauth.md).

```python
class NetSuiteM2MAuth
```

OAuth2 Client Credentials (M2M) for NetSuite using certificate-based JWT assertion.

NetSuite M2M requires a signed JWT as the ``client_assertion`` when
requesting an access token. The JWT is signed with the private key whose
matching X.509 certificate was uploaded to the NetSuite Integration Record.

Args:
    client_id: OAuth2 client ID from the NetSuite integration record.
    certificate_id: Certificate ID shown in NetSuite after uploading the
        public certificate.
    private_key_path: Path to the PEM-encoded RSA private key file.
    account_id: NetSuite account ID (e.g. ``"4984231"``).
    token_url: NetSuite token endpoint. Built automatically when ``None``.
    scopes: OAuth2 scopes (default ``["mcp"]``).
    token_store: Optional :class:`TokenStore` for persisting tokens.

## Methods

- `async def ensure_token(self, user_id: str='m2m') -> str` — Obtain or refresh an access token via Client Credentials grant.
- `def token_supplier(self) -> str | None` — Synchronous hook called by the HTTP transport before each request.
