---
type: Wiki Summary
title: parrot_formdesigner.renderers.xforms
id: mod:parrot_formdesigner.renderers.xforms
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: XForms 1.1 (W3C) exporter for ``FormSchema``.
relates_to:
- concept: class:parrot_formdesigner.renderers.xforms.XFormsRenderer
  rel: defines
- concept: mod:parrot_formdesigner.core.constraints
  rel: references
- concept: mod:parrot_formdesigner.core.options
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.style
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
- concept: mod:parrot_formdesigner.renderers.base
  rel: references
---

# `parrot_formdesigner.renderers.xforms`

XForms 1.1 (W3C) exporter for ``FormSchema``.

Maps a ``FormSchema`` to a W3C XForms 1.1 document using ``lxml``. The
output declares ``xmlns:xf="http://www.w3.org/2002/xforms"`` and
``xmlns:xs="http://www.w3.org/2001/XMLSchema"``. Per Q5 (resolved), V1
emits structural model + UI bindings AND ``<xf:bind>`` constraint
expressions derived from ``FieldConstraints``.

Output format: ``RenderedForm(content=<xml-bytes>,
content_type="application/xml")``.

Limitations:
- ``style`` / ``prefilled`` / ``errors`` arguments are accepted (per the
  base contract) but ignored; they are HTML-only concerns.
- ``DependencyRule`` mapping covers only the simple ``field_id == value``
  case; more complex AND/OR trees fall back to no ``relevant`` attribute.
- ``XFormsRenderer`` does NOT round-trip — there is no parser back to
  ``FormSchema`` (Non-Goal of FEAT-152).

## Classes

- **`XFormsRenderer(AbstractFormRenderer)`** — Render a ``FormSchema`` as an XForms 1.1 (W3C) document.
