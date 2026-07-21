---
type: Concept
title: build_public_html_url()
id: func:parrot.storage.artifact_signing.build_public_html_url
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build a signed, relative public-HTML URL for an infographic artifact.
---

# build_public_html_url

```python
def build_public_html_url(artifact_id: str, *, user_id: str | None=None, agent_id: str | None=None, session_id: str | None=None, expiry_seconds: int | None=None, key: bytes | None=None) -> str
```

Build a signed, relative public-HTML URL for an infographic artifact.

The result targets the server's ``ArtifactPublicHTMLView`` which streams
rendered HTML from ``Artifact.definition.html`` — unlike the S3 presigned
URL produced by ``ArtifactStore.get_public_url`` (which points at the raw
overflow JSON object, not servable HTML).

Scope query params (``user_id`` / ``agent_id`` / ``session_id``) are
appended when provided so that scope-partitioned backends (e.g. the local
filesystem store, whose objects live under
``USER#…/AGENT#…/THREAD#…``) can locate the artifact without session
context. They are NOT covered by the signature; on backends that support
global lookup by ``artifact_id`` they can be omitted to avoid leaking
scope into the URL.

Args:
    artifact_id: Artifact identifier.
    user_id: Owning user (storage scope).
    agent_id: Producing agent (storage scope).
    session_id: Owning session/thread (storage scope).
    expiry_seconds: URL validity window; defaults to
        ``INFOGRAPHIC_URL_EXPIRY_SECONDS`` (7 days).
    key: Override signing key (defaults to ``get_signing_key()``).

Returns:
    A relative URL string, e.g.
    ``/api/v1/artifacts/public/1717100000.AbCd/infographic-x.html?...``.
