---
type: Wiki Summary
title: parrot.outputs.a2ui.catalog.components.infographic
id: mod:parrot.outputs.a2ui.catalog.components.infographic
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: A2UI ``Infographic`` composite catalog component (Module 3).
relates_to:
- concept: class:parrot.outputs.a2ui.catalog.components.infographic.InfographicComponent
  rel: defines
- concept: mod:parrot.outputs.a2ui.catalog
  rel: references
- concept: mod:parrot.outputs.a2ui.catalog.base
  rel: references
- concept: mod:parrot.outputs.a2ui.models
  rel: references
---

# `parrot.outputs.a2ui.catalog.components.infographic`

A2UI ``Infographic`` composite catalog component (Module 3).

Infographic is one of Parrot's "exceeds-the-spec" semantic citizens: a header plus
an ordered list of sections, each hosting nested catalog components (KPICard rows,
Chart, Text/Image blocks). Vocabulary is inspired by the legacy
``InfographicHTMLRenderer`` (header / stat blocks / chart slots / themed sections) —
inspiration only, no code reuse. Display-only (``requires_actions=False``).

Composite lowering delegates nested catalog children to their own registered
``lower()`` via the catalog registry, keeping the whole composite deterministic as
long as every child lowering is pure.

## Classes

- **`InfographicComponent`** — The ``Infographic`` composite catalog component (display-only).
