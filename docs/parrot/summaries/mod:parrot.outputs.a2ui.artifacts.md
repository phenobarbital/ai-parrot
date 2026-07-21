---
type: Wiki Summary
title: parrot.outputs.a2ui.artifacts
id: mod:parrot.outputs.a2ui.artifacts
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Rendered-artifact and deep-link models (Module 6).
relates_to:
- concept: class:parrot.outputs.a2ui.artifacts.DeepLink
  rel: defines
- concept: class:parrot.outputs.a2ui.artifacts.RenderedArtifact
  rel: defines
---

# `parrot.outputs.a2ui.artifacts`

Rendered-artifact and deep-link models (Module 6).

Research confirmed no reusable rendered-file model exists anywhere in the monorepo,
so :class:`RenderedArtifact` is created here. A ``RenderedArtifact`` is the
self-contained, fully-baked output of a static renderer (PDF, email HTML, baked
document): it carries either inline ``content`` bytes XOR a ``path`` to a temp file
for attachment delivery, never both.

Core-side, dependency-free (spec G8): pydantic v2 + stdlib only.

## Classes

- **`DeepLink(BaseModel)`** — A single-use, TTL-bound deep link that resumes the originating channel.
- **`RenderedArtifact(BaseModel)`** — A baked, self-contained rendered output ready for delivery (spec §2, G5).
