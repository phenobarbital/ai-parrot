---
type: Wiki Overview
title: Infographic CSP and Signed URLs — Operations Guide
id: doc:docs-operations-infographic-csp-and-signed-urls-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: GET /api/v1/artifacts/public/{signature}/{artifact_id}.html
relates_to:
- concept: mod:parrot.handlers.artifacts
  rel: mentions
- concept: mod:parrot.models.infographic
  rel: mentions
- concept: mod:parrot.models.infographic_templates
  rel: mentions
---

# Infographic CSP and Signed URLs — Operations Guide

**Feature**: FEAT-197  
**Related**: `parrot/handlers/csp.py`, `parrot/handlers/artifacts.py`

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `INFOGRAPHIC_SIGNING_KEY` | `dev-insecure-key-change-in-prod` | Secret key for HMAC-SHA256 signatures on the public artifact HTML route.  **Set this in production.** |
| `INFOGRAPHIC_FRAME_ANCESTORS` | `'self'` | Comma-separated list of allowed `frame-ancestors` in the CSP header.  Example: `https://dashboard.example.com,https://embed.example.com` |

---

## Public HTML Route

```
GET /api/v1/artifacts/public/{signature}/{artifact_id}.html
```

Serves the frozen infographic HTML with full CSP headers.  No authentication
is required — the HMAC signature authorises access.

### Signature Scheme

```
signature = {expiry}.{hmac_base64url}

where:
  expiry        = Unix timestamp (seconds) when the URL expires
  hmac_base64url = HMAC-SHA256(key=INFOGRAPHIC_SIGNING_KEY,
                                msg='{artifact_id}|{expiry}')
                   base64url-encoded without padding
```

Generate a signed URL programmatically:

```python
from parrot.handlers.artifacts import _sign_artifact
import time

artifact_id = "infographic-abc123"
expiry = int(time.time()) + 604_800  # 7 days
key = b"your-secret-key"

sig = _sign_artifact(artifact_id, expiry, key)
url = f"/api/v1/artifacts/public/{expiry}.{sig}/{artifact_id}.html"
```

### 7-Day Cap

The maximum signature lifetime is **7 days** (604 800 seconds).  This matches
the S3 sigv4 hard limit.  Clients that need permanent URLs must use the
session-scoped `GET /api/v1/threads/{session_id}/artifacts/{artifact_id}` endpoint
(requires authentication).

---

## CSP Header Set

Every infographic HTML response carries:

| Header | Value |
|---|---|
| `Content-Security-Policy` | See below |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `no-referrer` |

### CSP Policy

```
default-src 'self';
script-src 'self' 'unsafe-inline' [<CDN origins from template js_bundles>];
style-src 'self' 'unsafe-inline';
img-src 'self' data:;
frame-ancestors <INFOGRAPHIC_FRAME_ANCESTORS>;
```

`'unsafe-inline'` in `script-src` is required for the optional LLM-enhanced
JavaScript interactivity.  External scripts are restricted to the template's
declared `js_bundles` SRI whitelist.

---

## Observability

The following log lines are emitted during normal operation:

| Level | Message | When |
|---|---|---|
| `INFO` | `Served public artifact id=... size=... bytes` | Successful HTML response |
| `INFO` | `Issuing presigned URL for artifact=... format=...` | `get_public_url` called |
| `INFO` | `Rendered infographic: template=... theme=... enhanced=... size=...` | Successful render |
| `WARNING` | `INFOGRAPHIC_SIGNING_KEY is not set — using insecure fallback key` | Missing env var |
| `WARNING` | `Rejected public artifact request: invalid or expired signature for artifact_id=...` | Tampered/expired URL |
| `WARNING` | `Enhanced HTML rejected (ENHANCE_OUTPUT_INVALID) — falling back...` | SRI whitelist violation in enhance pass |
| `WARNING` | `enhance requested without a brief — falling back to skeleton` | `mode=enhance` without `enhance_brief` |

---

## Adding a Template with CDN Bundles

1. Compute the genuine SRI hash:

```bash
curl -sL https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js \
  | openssl dgst -sha384 -binary | base64
```

2. Register the template with the real hash:

```python
from parrot.models.infographic import JSBundle
from parrot.models.infographic_templates import (
    BlockSpec, InfographicTemplate, infographic_registry,
)
from parrot.models.infographic import BlockType

my_template = InfographicTemplate(
    name="my_template",
    description="...",
    block_specs=[...],
    js_bundles=[
        JSBundle(
            name="echarts",
            scope="cdn",
            url="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js",
            sri_hash="sha384-<genuine-hash>",
        ),
    ],
)
infographic_registry.register(my_template)
```

3. The CSP builder automatically adds the CDN origin to `script-src` when the
   template is used.

---

## Known Limitations (v1)

- Signatures are not scoped to a user.  Any caller with the URL can fetch the artifact.
- Legacy artifacts (pre-FEAT-197) without `definition.html` fall back to re-rendering
  from `definition.blocks_envelope`.  This may fail if the block models have evolved.
- Streaming is disabled for `output_mode=infographic`.
- The SRI hash in the built-in `financial_projection_variance` template is a placeholder
  (`sha384-PLACEHOLDER_REPLACE_BEFORE_PRODUCTION`).  Replace it before enabling the
  `mode="enhance"` path in production.
