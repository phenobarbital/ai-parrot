---
type: Wiki Summary
title: parrot_formdesigner.renderers.base
id: mod:parrot_formdesigner.renderers.base
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base class for form renderers.
relates_to:
- concept: class:parrot_formdesigner.renderers.base.AbstractFormRenderer
  rel: defines
- concept: class:parrot_formdesigner.renderers.base.FallbackRenderer
  rel: defines
- concept: class:parrot_formdesigner.renderers.base.FieldRenderer
  rel: defines
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.style
  rel: references
---

# `parrot_formdesigner.renderers.base`

Abstract base class for form renderers.

All form renderers implement AbstractFormRenderer to produce RenderedForm
output from FormSchema + StyleSchema input.

## Classes

- **`FieldRenderer(Protocol)`** — Per-target field renderer. One concrete impl per (FieldType, output target).
- **`FallbackRenderer`** — Concrete fallback emitter — degraded representation.
- **`AbstractFormRenderer(ABC)`** — Abstract base for form renderers.
