---
type: Wiki Entity
title: ArtifactPublicHTMLView
id: class:parrot.handlers.artifacts.ArtifactPublicHTMLView
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Public HTML serving endpoint for infographic artifacts.
---

# ArtifactPublicHTMLView

Defined in [`parrot.handlers.artifacts`](../summaries/mod:parrot.handlers.artifacts.md).

```python
class ArtifactPublicHTMLView(web.View)
```

Public HTML serving endpoint for infographic artifacts.

Design B (per TASK-1322): signature validated in-app, HTML streamed
from ``Artifact.definition.html``; full CSP header set applied.

Route:
    GET /api/v1/artifacts/public/{signature}/{artifact_id}.html

Signature format:
    ``{expiry}.{hmac_sha256_base64url}``
    where
    ``hmac_sha256_base64url = HMAC-SHA256(INFOGRAPHIC_SIGNING_KEY,
                                           '{artifact_id}|{expiry}')``
    base64url-encoded without padding.

Environment variables:
    INFOGRAPHIC_SIGNING_KEY:  Secret key for HMAC; required in prod.
    INFOGRAPHIC_FRAME_ANCESTORS: CSV of allowed frame ancestors; default 'self'.

HTTP 403 on:
    - Invalid / tampered signature.
    - Expired signature (expiry < current UTC).

## Methods

- `async def get(self) -> web.Response` — Serve the frozen infographic HTML for a valid signature.
