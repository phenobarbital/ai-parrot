---
type: Wiki Summary
title: parrot.outputs.formats.structured_base
id: mod:parrot.outputs.formats.structured_base
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'FEAT-223 Module 1: Shared structured-output base mixin.'
relates_to:
- concept: class:parrot.outputs.formats.structured_base.StructuredOutputBase
  rel: defines
- concept: mod:parrot.outputs.formats.table
  rel: references
---

# `parrot.outputs.formats.structured_base`

FEAT-223 Module 1: Shared structured-output base mixin.

Extracts the deterministic row-extraction + envelope-routing contract common to
all ``structured_*`` renderers (table, chart, map) into a single reusable mixin.

Inherit alongside ``BaseChart`` to adopt the contract without changing
``@register_renderer`` wiring::

    class StructuredTableRenderer(StructuredOutputBase, BaseChart):
        ...

## Classes

- **`StructuredOutputBase`** — Mixin providing the shared contract for all structured-output renderers.
