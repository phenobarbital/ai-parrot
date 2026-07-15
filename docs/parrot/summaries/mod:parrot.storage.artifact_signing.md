---
type: Wiki Summary
title: parrot.storage.artifact_signing
id: mod:parrot.storage.artifact_signing
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Shared signing helpers for public infographic artifact URLs (FEAT-197).
relates_to:
- concept: func:parrot.storage.artifact_signing.build_public_html_url
  rel: defines
- concept: func:parrot.storage.artifact_signing.get_signing_key
  rel: defines
- concept: func:parrot.storage.artifact_signing.sign_artifact
  rel: defines
- concept: func:parrot.storage.artifact_signing.verify_signature
  rel: defines
---

# `parrot.storage.artifact_signing`

Shared signing helpers for public infographic artifact URLs (FEAT-197).

The public HTML serving route
``GET /api/v1/artifacts/public/{signature}/{artifact_id}.html`` authorises
requests with an HMAC signature instead of a session, so the frontend can
embed a frozen infographic in an ``<iframe>`` without an auth round-trip.

This module is the **single source of truth** for that signature scheme so
that both producers (the core ``InfographicToolkit`` that mints the URL when
it persists an artifact) and consumers (the server-side
``ArtifactPublicHTMLView`` that verifies it) agree byte-for-byte.

Signature format::

    {expiry}.{hmac_sha256_base64url}

where ``hmac_sha256_base64url = HMAC-SHA256(key=INFOGRAPHIC_SIGNING_KEY,
msg='{artifact_id}|{expiry}')`` base64url-encoded without padding and
``expiry`` is an absolute UNIX timestamp (seconds).

Environment variables:
    INFOGRAPHIC_SIGNING_KEY:        HMAC secret; required in production.
    INFOGRAPHIC_URL_EXPIRY_SECONDS: Default URL validity (seconds, 7 days).

## Functions

- `def get_signing_key() -> bytes` — Read ``INFOGRAPHIC_SIGNING_KEY`` from the environment.
- `def sign_artifact(artifact_id: str, expiry: int, key: bytes) -> str` — Compute the base64url HMAC digest over ``'{artifact_id}|{expiry}'``.
- `def verify_signature(artifact_id: str, signature_segment: str, key: bytes) -> bool` — Verify a ``{expiry}.{sig}`` signature segment.
- `def build_public_html_url(artifact_id: str, *, user_id: str | None=None, agent_id: str | None=None, session_id: str | None=None, expiry_seconds: int | None=None, key: bytes | None=None) -> str` — Build a signed, relative public-HTML URL for an infographic artifact.
