---
type: Wiki Summary
title: parrot.forms.renderers.html5
id: mod:parrot.forms.renderers.html5
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: HTML5 form renderer for FormSchema.
relates_to:
- concept: class:parrot.forms.renderers.html5.HTML5Renderer
  rel: defines
- concept: mod:parrot.forms.constraints
  rel: references
- concept: mod:parrot.forms.options
  rel: references
- concept: mod:parrot.forms.renderers.base
  rel: references
- concept: mod:parrot.forms.schema
  rel: references
- concept: mod:parrot.forms.style
  rel: references
- concept: mod:parrot.forms.types
  rel: references
---

# `parrot.forms.renderers.html5`

HTML5 form renderer for FormSchema.

Renders FormSchema + StyleSchema as HTML5 <form> fragments using Jinja2 templates.
Output is a form fragment (not a full page) ready to be embedded in a web application.

## Classes

- **`HTML5Renderer(AbstractFormRenderer)`** — Renders FormSchema as an HTML5 <form> fragment.
