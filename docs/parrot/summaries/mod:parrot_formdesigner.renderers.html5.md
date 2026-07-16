---
type: Wiki Summary
title: parrot_formdesigner.renderers.html5
id: mod:parrot_formdesigner.renderers.html5
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTML5 form renderer for FormSchema.
relates_to:
- concept: class:parrot_formdesigner.renderers.html5.HTML5Renderer
  rel: defines
- concept: mod:parrot_formdesigner.core.constraints
  rel: references
- concept: mod:parrot_formdesigner.core.events
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.style
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
- concept: mod:parrot_formdesigner.renderers.base
  rel: references
- concept: mod:parrot_formdesigner.renderers.fields.audio
  rel: references
---

# `parrot_formdesigner.renderers.html5`

HTML5 form renderer for FormSchema.

Renders FormSchema + StyleSchema as HTML5 <form> fragments using Jinja2 templates.
Output is a form fragment (not a full page) ready to be embedded in a web application.

## Classes

- **`HTML5Renderer(AbstractFormRenderer)`** — Renders FormSchema as an HTML5 <form> fragment.
