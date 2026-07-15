---
type: Wiki Entity
title: RenderedArtifact
id: class:parrot.outputs.a2ui.artifacts.RenderedArtifact
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A baked, self-contained rendered output ready for delivery (spec §2, G5).
---

# RenderedArtifact

Defined in [`parrot.outputs.a2ui.artifacts`](../summaries/mod:parrot.outputs.a2ui.artifacts.md).

```python
class RenderedArtifact(BaseModel)
```

A baked, self-contained rendered output ready for delivery (spec §2, G5).

Exactly one of ``content`` (inline bytes) or ``path`` (temp file) is set.

Attributes:
    artifact_id: Unique id for this rendered artifact.
    mime_type: MIME type of the rendered content (e.g. ``application/pdf``).
    content: Inline bytes (XOR ``path``).
    path: Temp-file path for attachment delivery (XOR ``content``).
    filename: Suggested delivery filename.
    title: Human-readable title.
    surface: The renderer name that produced this artifact.
    source_envelope_ref: ``ArtifactStore`` id / S3 URI of the source envelope.
    deep_links: Deep links for actions degraded on this static surface.
    metadata: Free-form renderer metadata.
