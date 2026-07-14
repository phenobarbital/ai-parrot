---
type: Wiki Summary
title: parrot_formdesigner.services.metadata_enricher
id: mod:parrot_formdesigner.services.metadata_enricher
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Before-save submission metadata enrichment.
relates_to:
- concept: class:parrot_formdesigner.services.metadata_enricher.MetadataResolutionError
  rel: defines
- concept: func:parrot_formdesigner.services.metadata_enricher.enrich_submission
  rel: defines
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.services.auth_context
  rel: references
- concept: mod:parrot_formdesigner.services.callback_registry
  rel: references
- concept: mod:parrot_formdesigner.services.metadata_callbacks
  rel: references
- concept: mod:parrot_formdesigner.services.metadata_sources
  rel: references
- concept: mod:parrot_formdesigner.services.submissions
  rel: references
---

# `parrot_formdesigner.services.metadata_enricher`

Before-save submission metadata enrichment.

Given a validated submission, a form schema with declared
``metadata`` entries, and the inbound aiohttp request, this module
resolves every declared field, splits the resulting keys into the
"core" set (promoted to typed ``FormSubmission`` columns) and the
"extra" set (flat-merged into the submission ``data`` JSONB).

The enricher is intentionally a pure function — no HTTP, no DB —
so it is trivial to unit-test against stubbed requests.

## Classes

- **`MetadataResolutionError(Exception)`** — Raised when a required metadata field cannot be resolved.

## Functions

- `async def enrich_submission(*, request: 'web.Request', form: 'FormSchema', submission: 'FormSubmission', answers: dict[str, Any], auth_context: 'AuthContext') -> tuple[dict[str, Any], dict[str, Any]]` — Resolve declared metadata for a pending submission.
