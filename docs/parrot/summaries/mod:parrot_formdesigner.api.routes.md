---
type: Wiki Summary
title: parrot_formdesigner.api.routes
id: mod:parrot_formdesigner.api.routes
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Route registration for the JSON REST surface of parrot-formdesigner.
relates_to:
- concept: func:parrot_formdesigner.api.routes.setup_form_api
  rel: defines
- concept: mod:parrot.clients.base
  rel: references
- concept: mod:parrot.core.ws_auth
  rel: references
- concept: mod:parrot.voice.transcriber.faster_whisper_backend
  rel: references
- concept: mod:parrot.voice.tts.synthesizer
  rel: references
- concept: mod:parrot_formdesigner.api
  rel: references
- concept: mod:parrot_formdesigner.api.audio_ws
  rel: references
- concept: mod:parrot_formdesigner.api.controls
  rel: references
- concept: mod:parrot_formdesigner.api.handlers
  rel: references
- concept: mod:parrot_formdesigner.api.operations
  rel: references
- concept: mod:parrot_formdesigner.api.render
  rel: references
- concept: mod:parrot_formdesigner.api.uploads
  rel: references
- concept: mod:parrot_formdesigner.services.blob_storage
  rel: references
- concept: mod:parrot_formdesigner.services.forwarder
  rel: references
- concept: mod:parrot_formdesigner.services.org_graph
  rel: references
- concept: mod:parrot_formdesigner.services.partial_saves
  rel: references
- concept: mod:parrot_formdesigner.services.project_service
  rel: references
- concept: mod:parrot_formdesigner.services.public_forms
  rel: references
- concept: mod:parrot_formdesigner.services.rbac
  rel: references
- concept: mod:parrot_formdesigner.services.registry
  rel: references
- concept: mod:parrot_formdesigner.services.rest_field_resolver
  rel: references
- concept: mod:parrot_formdesigner.services.submissions
  rel: references
- concept: mod:parrot_formdesigner.services.validators
  rel: references
- concept: mod:parrot_formdesigner.services.venue_service
  rel: references
- concept: mod:parrot_formdesigner.services.workday_sync
  rel: references
---

# `parrot_formdesigner.api.routes`

Route registration for the JSON REST surface of parrot-formdesigner.

Hard-imports navigator-auth: any consumer that does not have the package
installed will fail at import time. This is intentional — see FEAT-152.

Public API:

    setup_form_api(app, registry, *, client=None, submission_storage=None,
                   forwarder=None, base_path="/api/v1",
                   blob_storage=None, resolver=None) -> None

Lazy-init contract for REST field services (FEAT-170):
- ``app["blob_storage"]`` — instance of ``AbstractBlobStorage``, or ``None``.
  When ``None``, the upload handler (TASK-1170) constructs ``S3BlobStorage()``
  on first use from environment variables (``PARROT_BLOB_BUCKET``, etc.).
- ``app["rest_resolver"]`` — instance of ``RestFieldResolver``, or ``None``.
  When ``None``, the upload handler creates a default instance on first use.

Callers that do not use ``FieldType.REST`` need not provide these kwargs;
defaults are ``None`` and no exception is raised.

## Functions

- `def setup_form_api(app: web.Application, registry: FormRegistry, *, client: 'AbstractClient | None'=None, submission_storage: 'FormSubmissionStorage | None'=None, forwarder: 'SubmissionForwarder | None'=None, base_path: str='/api/v1', blob_storage: 'AbstractBlobStorage | None'=None, resolver: 'RestFieldResolver | None'=None, partial_store: 'PartialSaveStore | None'=None, synthesizer: 'VoiceSynthesizer | None'=None, transcriber: 'FasterWhisperBackend | None'=None, token_validator: 'TokenValidator | None'=None, org_graph_service: 'OrgGraphService | None'=None, project_service: 'ProjectService | None'=None, rbac_service: 'RBACService | None'=None, workday_adapter: 'WorkdayIdentitySyncAdapter | None'=None, venue_service: 'VenueService | None'=None, rbac_enforcing: bool=False) -> None` — Mount the JSON REST surface on ``app`` under ``base_path``.
