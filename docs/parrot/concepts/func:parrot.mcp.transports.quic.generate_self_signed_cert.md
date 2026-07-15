---
type: Concept
title: generate_self_signed_cert()
id: func:parrot.mcp.transports.quic.generate_self_signed_cert
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generate self-signed certificate for development.
---

# generate_self_signed_cert

```python
def generate_self_signed_cert(cert_path: str='cert.pem', key_path: str='key.pem', hostname: str='localhost', days: int=365) -> None
```

Generate self-signed certificate for development.
For production, use proper certificates from a CA.
