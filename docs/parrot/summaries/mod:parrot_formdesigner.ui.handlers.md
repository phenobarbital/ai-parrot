---
type: Wiki Summary
title: parrot_formdesigner.ui.handlers
id: mod:parrot_formdesigner.ui.handlers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: HTML page handlers for parrot-formdesigner.
relates_to:
- concept: class:parrot_formdesigner.ui.handlers.FormPageHandler
  rel: defines
- concept: mod:parrot_formdesigner.core.style
  rel: references
- concept: mod:parrot_formdesigner.renderers.html5
  rel: references
- concept: mod:parrot_formdesigner.renderers.jsonschema
  rel: references
- concept: mod:parrot_formdesigner.services.registry
  rel: references
- concept: mod:parrot_formdesigner.services.validators
  rel: references
- concept: mod:parrot_formdesigner.ui.templates
  rel: references
---

# `parrot_formdesigner.ui.handlers`

HTML page handlers for parrot-formdesigner.

Serves the form builder UI: index, gallery, render form, submit form.

Every handler reads the optional URL mount prefix from
``request.app["_form_prefix"]`` (populated by ``setup_form_routes``) and
forwards it to the page-template builders so that links and form
actions match the routes registered by aiohttp.

## Classes

- **`FormPageHandler`** — Serves HTML pages for the form builder UI.
