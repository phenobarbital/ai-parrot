---
type: Wiki Summary
title: parrot.handlers.artifacts
id: mod:parrot.handlers.artifacts
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: REST handler for artifact CRUD.
relates_to:
- concept: class:parrot.handlers.artifacts.ArtifactDetailView
  rel: defines
- concept: class:parrot.handlers.artifacts.ArtifactListView
  rel: defines
- concept: class:parrot.handlers.artifacts.ArtifactPublicHTMLView
  rel: defines
- concept: mod:parrot.handlers.csp
  rel: references
- concept: mod:parrot.models.infographic
  rel: references
- concept: mod:parrot.outputs.formats
  rel: references
- concept: mod:parrot.storage.artifact_signing
  rel: references
- concept: mod:parrot.storage.models
  rel: references
---

# `parrot.handlers.artifacts`

REST handler for artifact CRUD.

Provides endpoints for saving, loading, updating, and deleting
artifacts (charts, canvas tabs, infographics, dataframes, exports)
associated with a conversation thread.

FEAT-103: agent-artifact-persistency — Module 8.
FEAT-197: Added ArtifactPublicHTMLView and HTML content-negotiation.

Endpoints:
    GET    /api/v1/threads/{session_id}/artifacts               — list artifacts
    POST   /api/v1/threads/{session_id}/artifacts               — save artifact
    GET    /api/v1/threads/{session_id}/artifacts/{artifact_id}  — get artifact
    PUT    /api/v1/threads/{session_id}/artifacts/{artifact_id}  — update artifact
    DELETE /api/v1/threads/{session_id}/artifacts/{artifact_id}  — delete artifact

    GET    /api/v1/artifacts/public/{signature}/{artifact_id}.html  — public HTML
        (FEAT-197, TASK-1322)
        Signature scheme: ``{expiry}.{hmac_sha256}`` where
        ``hmac_sha256 = HMAC-SHA256(key=INFOGRAPHIC_SIGNING_KEY, msg='{artifact_id}|{expiry}')``
        base64url-encoded without padding.
        The env var INFOGRAPHIC_SIGNING_KEY is required for this endpoint to work.
        The env var INFOGRAPHIC_FRAME_ANCESTORS controls the CSP frame-ancestors
        directive (comma-separated, default ``'self'``).

## Classes

- **`ArtifactListView(BaseView)`** — List and create artifacts for a thread.
- **`ArtifactDetailView(BaseView)`** — Detail operations on a single artifact.
- **`ArtifactPublicHTMLView(web.View)`** — Public HTML serving endpoint for infographic artifacts.
