---
type: Concept
title: setup_form_api()
id: func:parrot_formdesigner.api.routes.setup_form_api
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mount the JSON REST surface on ``app`` under ``base_path``.
---

# setup_form_api

```python
def setup_form_api(app: web.Application, registry: FormRegistry, *, client: 'AbstractClient | None'=None, submission_storage: 'FormSubmissionStorage | None'=None, forwarder: 'SubmissionForwarder | None'=None, base_path: str='/api/v1', blob_storage: 'AbstractBlobStorage | None'=None, resolver: 'RestFieldResolver | None'=None, partial_store: 'PartialSaveStore | None'=None, synthesizer: 'VoiceSynthesizer | None'=None, transcriber: 'FasterWhisperBackend | None'=None, token_validator: 'TokenValidator | None'=None, org_graph_service: 'OrgGraphService | None'=None, project_service: 'ProjectService | None'=None, rbac_service: 'RBACService | None'=None, workday_adapter: 'WorkdayIdentitySyncAdapter | None'=None, venue_service: 'VenueService | None'=None, rbac_enforcing: bool=False) -> None
```

Mount the JSON REST surface on ``app`` under ``base_path``.

Every route is wrapped with navigator-auth's ``is_authenticated`` +
``user_session`` decorators. Telegram webhook routes do NOT belong here
— see ``parrot_formdesigner.ui.setup_form_ui`` for those.

Args:
    app: aiohttp application to register routes on.
    registry: Pre-built ``FormRegistry`` shared across requests.
    client: Optional LLM client for natural language form creation.
    submission_storage: Optional storage backend for submissions.
    forwarder: Optional submission forwarder.
    base_path: URL prefix for all routes (default ``"/api/v1"``).
    blob_storage: Optional ``AbstractBlobStorage`` instance for REST field
        binary uploads. If ``None``, the upload handler will construct an
        ``S3BlobStorage()`` lazily on first use from environment variables.
    resolver: Optional ``RestFieldResolver`` instance. If ``None``, the
        upload handler will create a default instance on first use.
    partial_store: Optional Redis-backed ``PartialSaveStore`` for ephemeral
        partial form answer caching.  When ``None``, the partial save
        endpoints (POST/GET/DELETE ``/forms/{form_id}/partial``) will
        return 503.
    synthesizer: Optional ``VoiceSynthesizer`` for audio-form TTS. When
        provided it is used as-is (tests/overrides). When ``None`` but audio
        is intended (``transcriber`` or ``token_validator`` given), the
        audio handler synthesizes lazily via the SuperTonic-first fallback
        (SuperTonic → Google → text-only). SuperTonic requires the
        ``ai-parrot-integrations[voice-supertonic]`` extra and the
        ``SUPERTONIC_MODEL_PATH`` env var pointing at the ONNX weights; when
        unavailable the session degrades gracefully to Google, then to
        text-only. No model is loaded at route-setup time (the backend loads
        lazily on first synthesis).
    transcriber: Optional ``FasterWhisperBackend`` for audio-form STT.
        Providing it (or ``token_validator``) mounts the audio WS endpoint.
    token_validator: Optional ``TokenValidator`` for audio-form WebSocket
        JWT authentication. Providing it mounts the audio WS endpoint.
    org_graph_service: Optional ``OrgGraphService`` for ``GET /org/graph``.
    project_service: Optional ``ProjectService`` for org project endpoints.
    rbac_service: Optional ``RBACService`` for RBAC policy endpoints.
    workday_adapter: Optional ``WorkdayIdentitySyncAdapter`` for
        ``POST /org/sync/workday``.
    rbac_enforcing: When ``False`` (default), RBAC gate-keeping on existing
        form endpoints runs in shadow mode (log only, never block).
