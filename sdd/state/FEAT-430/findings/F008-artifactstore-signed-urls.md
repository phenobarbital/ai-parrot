# F008 — Secure artifact storage + signed iframe URLs ALREADY EXIST (FEAT-103 / FEAT-197)

**Query:** Q010 (wiki_query + direct read)
**Citations:**
  `packages/ai-parrot/src/parrot/storage/artifacts.py` :: `ArtifactStore`
  `packages/ai-parrot/src/parrot/storage/artifact_signing.py`
    :: `sign_artifact`, `verify_signature`, `build_public_html_url`, `get_signing_key`
  `packages/ai-parrot-server/src/parrot/handlers/infographic_render.py`
    :: `resolve_response_url` (L665-710)
  `packages/ai-parrot-server/src/parrot/manager/manager.py` L2155-2163 (`app['artifact_store']`)
  `packages/ai-parrot-server/src/parrot/handlers/artifacts.py`
**Confidence:** high (direct source read)

## This is the headline finding

Brainstorm §4.1.B proposes building: private S3 + a **non-expiring internal token**
consumed by a middleware that hides the credential. That mechanism already exists in a
**stronger form**, shipped under FEAT-103 + FEAT-197:

**1. `ArtifactStore` with S3 presigned URLs** — wired into the app at
`app['artifact_store']` during manager init. `resolve_response_url()` documents the rule:

> `persisted=True` and `public=False` → try `ArtifactStore.get_public_url`
> (**S3 presigned, ALWAYS** — infographics are never hosted on public S3)

**2. HMAC-signed, expiry-bound iframe URLs (FEAT-197)** — purpose-built for this exact
use case:

> The public HTML serving route `GET /api/v1/artifacts/public/{signature}/{artifact_id}.html`
> authorises requests with an HMAC signature instead of a session, **so the frontend can
> embed a frozen infographic in an `<iframe>` without an auth round-trip**.

Signature scheme: `{expiry}.{base64url(HMAC-SHA256(INFOGRAPHIC_SIGNING_KEY, "{artifact_id}|{expiry}"))}`,
with `expiry` an absolute UNIX timestamp. `artifact_signing.py` is the declared single
source of truth shared by producer and verifier.

## Why this beats the brainstorm's proposed design

| Brainstorm §4.1.B | Existing FEAT-197/FEAT-103 |
|---|---|
| non-expiring internal token | expiry baked into every signature |
| credential hidden behind middleware | no credential in the URL at all (HMAC) |
| new middleware to build | serving route + verifier already shipped |
| new S3 wiring | `ArtifactStore` already initialized in manager |

It also satisfies HI-3 more completely than the brainstorm's own design, and it is
already the mechanism used for iframe-embedded infographics — the very widget shape
Carlos's dashboard uses.

## Constraint to carry into the spec

`resolve_response_url` shows `public=True` publishes to a world-readable `STATIC_DIR`.
Given rev2 #3 ("static publishing is rejected — strategic financial data"), SPEC-A must
pin `public=False` and use the presigned / HMAC-signed path exclusively. The
`STATIC_DIR` branch should be explicitly forbidden for dashboard artifacts.
