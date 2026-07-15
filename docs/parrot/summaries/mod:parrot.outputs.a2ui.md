---
type: Wiki Summary
title: parrot.outputs.a2ui
id: mod:parrot.outputs.a2ui
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: '``parrot.outputs.a2ui`` — A2UI v1.0 rendering core (FEAT-273).'
relates_to:
- concept: mod:parrot.outputs.a2ui.models
  rel: references
- concept: mod:parrot.outputs.a2ui.serialization
  rel: references
---

# `parrot.outputs.a2ui`

``parrot.outputs.a2ui`` — A2UI v1.0 rendering core (FEAT-273).

Core-side contract for the A2UI output pipeline: the v1.0 wire message models,
the serialization layer that owns the protocol ``version``, the component catalog
with mandatory lowering, and the capability-declaring renderer registry.

One-way import rule (spec G8): this package MUST NEVER import from
``parrot.bots``, ``parrot.clients``, agents, or DatasetManager. Concrete
renderers live in the ``ai-parrot-visualizations`` satellite.
