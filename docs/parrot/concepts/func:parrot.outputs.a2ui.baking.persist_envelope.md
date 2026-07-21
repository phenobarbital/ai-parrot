---
type: Concept
title: persist_envelope()
id: func:parrot.outputs.a2ui.baking.persist_envelope
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Persist the source envelope via ``ArtifactStore`` and return its reference.
---

# persist_envelope

```python
async def persist_envelope(envelope: CreateSurface, store: Any, *, user_id: str, agent_id: str, session_id: str, artifact_id: str | None=None, title: str='A2UI envelope') -> str
```

Persist the source envelope via ``ArtifactStore`` and return its reference.

The >200 KB S3 overflow is handled transparently by ``ArtifactStore`` (the
``definition_ref`` convention) — this function does not reimplement thresholds.

Args:
    envelope: The source envelope to persist.
    store: An ``ArtifactStore`` instance (``save_artifact`` coroutine).
    user_id: Owning user id.
    agent_id: Owning agent id.
    session_id: Owning session id.
    artifact_id: Optional explicit id; a UUID4 is generated when omitted.
    title: Artifact title.

Returns:
    The artifact id used as ``RenderedArtifact.source_envelope_ref``.
