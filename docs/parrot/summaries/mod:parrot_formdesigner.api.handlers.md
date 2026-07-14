---
type: Wiki Summary
title: parrot_formdesigner.api.handlers
id: mod:parrot_formdesigner.api.handlers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: JSON REST API handlers for parrot-formdesigner.
relates_to:
- concept: class:parrot_formdesigner.api.handlers.FormAPIHandler
  rel: defines
- concept: mod:parrot.clients.base
  rel: references
- concept: mod:parrot.clients.google
  rel: references
- concept: mod:parrot_formdesigner.api._utils
  rel: references
- concept: mod:parrot_formdesigner.core.events
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.renderers.jsonschema
  rel: references
- concept: mod:parrot_formdesigner.services.auth_context
  rel: references
- concept: mod:parrot_formdesigner.services.csrf
  rel: references
- concept: mod:parrot_formdesigner.services.event_dispatcher
  rel: references
- concept: mod:parrot_formdesigner.services.form_version
  rel: references
- concept: mod:parrot_formdesigner.services.forwarder
  rel: references
- concept: mod:parrot_formdesigner.services.metadata_enricher
  rel: references
- concept: mod:parrot_formdesigner.services.org_graph
  rel: references
- concept: mod:parrot_formdesigner.services.partial_saves
  rel: references
- concept: mod:parrot_formdesigner.services.project_service
  rel: references
- concept: mod:parrot_formdesigner.services.question_bank
  rel: references
- concept: mod:parrot_formdesigner.services.rbac
  rel: references
- concept: mod:parrot_formdesigner.services.registry
  rel: references
- concept: mod:parrot_formdesigner.services.submissions
  rel: references
- concept: mod:parrot_formdesigner.services.validators
  rel: references
- concept: mod:parrot_formdesigner.services.venue_service
  rel: references
- concept: mod:parrot_formdesigner.services.workday_sync
  rel: references
- concept: mod:parrot_formdesigner.tools.create_form
  rel: references
- concept: mod:parrot_formdesigner.tools.database_form
  rel: references
- concept: mod:parrot_formdesigner.tools.services.networkninja
  rel: references
---

# `parrot_formdesigner.api.handlers`

JSON REST API handlers for parrot-formdesigner.

Serves the form builder REST API: create, list, get schema, validate, load
from DB. HTML rendering moved to the render dispatcher in ``api/render.py``.

All endpoints are protected by navigator-auth session authentication via
``api/routes.py`` (hard import — see FEAT-152).

## Classes

- **`FormAPIHandler`** — Serves JSON REST API endpoints for form management.
