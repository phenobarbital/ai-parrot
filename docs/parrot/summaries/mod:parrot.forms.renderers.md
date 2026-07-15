---
type: Wiki Summary
title: parrot.forms.renderers
id: mod:parrot.forms.renderers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Form renderers for the forms abstraction layer.
relates_to:
- concept: mod:parrot.forms
  rel: references
---

# `parrot.forms.renderers`

Form renderers for the forms abstraction layer.

Renderers convert FormSchema + StyleSchema into platform-specific output:
- AdaptiveCardRenderer: Adaptive Card JSON for MS Teams
- HTML5Renderer: HTML5 form fragment for web
- JsonSchemaRenderer: JSON Schema output for custom frontends
