---
type: Wiki Summary
title: parrot.models.interactive
id: mod:parrot.models.interactive
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Models for Interactive HTML Artifacts ("vibe-coding" canvas).
relates_to:
- concept: class:parrot.models.interactive.InteractiveRenderResult
  rel: defines
- concept: class:parrot.models.interactive.LibraryEntry
  rel: defines
- concept: class:parrot.models.interactive.ScaffoldTemplate
  rel: defines
- concept: mod:parrot.models.infographic
  rel: references
---

# `parrot.models.interactive`

Models for Interactive HTML Artifacts ("vibe-coding" canvas).

This is the free-form counterpart to the structured ``Infographic`` system.
Where an infographic constrains the LLM to a fixed set of typed JSON blocks
rendered deterministically, an *interactive artifact* lets the LLM author the
HTML/JS directly — guided by a **catalog** of vetted JavaScript libraries and
HTML scaffold templates that is injected into the agent prompt.

Two pure-data models live here:

- :class:`LibraryEntry` — a single vetted JS library (Mermaid, ECharts,
  Grid.js, …) the LLM may use. It carries the :class:`~parrot.models.infographic.JSBundle`
  used by the SRI allow-list / CSP machinery, plus a usage snippet and optional
  TypeScript reference types that *guide* the LLM (the snippets are reference
  material — nothing is compiled; the LLM emits plain JavaScript).
- :class:`ScaffoldTemplate` — a deterministic HTML skeleton (``dashboard``,
  ``wizard``, ``diagram``, ``grid``, ``report``) with named ``<!-- SLOT:* -->``
  placeholders the LLM fills during the enhance pass.

The render envelope :class:`InteractiveRenderResult` mirrors
``InfographicRenderResult`` so the agent post-loop can treat both uniformly.

The catalog itself (loading entries from disk) lives in
``parrot.tools.interactive.catalog_registry`` to keep this module dependency-light.

## Classes

- **`LibraryEntry(BaseModel)`** — A single vetted JavaScript library the LLM may use in an artifact.
- **`ScaffoldTemplate(BaseModel)`** — A deterministic HTML skeleton with named slots for the enhance pass.
- **`InteractiveRenderResult(BaseModel)`** — Envelope returned by ``InteractiveToolkit.render`` (return_direct=True).
