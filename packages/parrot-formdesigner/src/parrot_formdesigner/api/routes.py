"""Route registration for the JSON REST surface of parrot-formdesigner.

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
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TYPE_CHECKING

from aiohttp import web

# HARD navigator-auth import — package fails to import without it.
# See FEAT-152 §1 Goals: "Promote navigator-auth to a hard dependency".
from navigator_auth.decorators import is_authenticated, user_session

from ..services.registry import FormRegistry
from . import controls as controls_module
from . import operations as operations_module
from . import render as render_module
from . import uploads as uploads_module
from .handlers import FormAPIHandler


if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient
    from parrot.voice.handler import TokenValidator
    from parrot.voice.tts.synthesizer import VoiceSynthesizer
    from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend

    from ..services.blob_storage import AbstractBlobStorage
    from ..services.forwarder import SubmissionForwarder
    from ..services.partial_saves import PartialSaveStore
    from ..services.rest_field_resolver import RestFieldResolver
    from ..services.submissions import FormSubmissionStorage


logger = logging.getLogger(__name__)


_Handler = Callable[[web.Request], Awaitable[web.Response]]


def _wrap_auth(handler: _Handler) -> _Handler:
    """Wrap a handler with navigator-auth ``is_authenticated`` + ``user_session``.

    Mirrors the previous ``handlers/routes.py:_wrap_auth`` shape, but without
    the ``_AUTH_AVAILABLE`` fallback — navigator-auth is a hard dep here.

    Args:
        handler: A bound async coroutine accepting ``request: web.Request``.

    Returns:
        The decorated handler.
    """

    @wraps(handler)
    async def _inner(request: web.Request, **kwargs) -> web.Response:
        # user_session's _func_wrapper injects session= and user= kwargs.
        # Our handlers don't accept those — consume them here so they
        # don't cause a TypeError, then call the original handler.
        return await handler(request)

    decorated = user_session()(_inner)
    decorated = is_authenticated(content_type="application/json")(decorated)
    return decorated


def setup_form_api(
    app: web.Application,
    registry: FormRegistry,
    *,
    client: "AbstractClient | None" = None,
    submission_storage: "FormSubmissionStorage | None" = None,
    forwarder: "SubmissionForwarder | None" = None,
    base_path: str = "/api/v1",
    blob_storage: "AbstractBlobStorage | None" = None,
    resolver: "RestFieldResolver | None" = None,
    partial_store: "PartialSaveStore | None" = None,
    synthesizer: "VoiceSynthesizer | None" = None,
    transcriber: "FasterWhisperBackend | None" = None,
    token_validator: "TokenValidator | None" = None,
) -> None:
    """Mount the JSON REST surface on ``app`` under ``base_path``.

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
    """
    # Stash the registry on the app for the dispatcher / operations handler.
    # Guard: skip if already set (FormRegistry.__init__ sets it when app= is
    # provided — avoids overwriting with a different reference).
    if "form_registry" not in app:
        app["form_registry"] = registry
    elif app["form_registry"] is not registry:
        logger.warning(
            "setup_form_api: app['form_registry'] is already set to a different "
            "registry instance. The passed registry will be ignored. Pass the same "
            "instance, or let FormRegistry(app=app) manage the assignment."
        )

    # Stash REST-field services (FEAT-170). Both may be None; the upload
    # handler resolves defaults lazily on first request.
    app["blob_storage"] = blob_storage
    app["rest_resolver"] = resolver

    # Seed the renderer registry with the V1 default renderers.
    render_module._seed_default_renderers()

    # Stash partial store on the app for lifecycle management (optional).
    if partial_store is not None:
        app["partial_store"] = partial_store

        async def _close_partial_store(app: web.Application) -> None:
            ps = app.get("partial_store")
            if ps is not None:
                await ps.close()

        app.on_shutdown.append(_close_partial_store)

    handler = FormAPIHandler(
        registry=registry,
        client=client,
        submission_storage=submission_storage,
        forwarder=forwarder,
        partial_store=partial_store,
    )

    bp = base_path.rstrip("/")

    # CRUD + listing
    app.router.add_get(f"{bp}/forms", _wrap_auth(handler.list_forms))
    app.router.add_post(f"{bp}/forms", _wrap_auth(handler.create_form))
    app.router.add_post(f"{bp}/forms/from-db", _wrap_auth(handler.load_from_db))
    app.router.add_get(f"{bp}/forms/{{form_id}}", _wrap_auth(handler.get_form))
    app.router.add_put(f"{bp}/forms/{{form_id}}", _wrap_auth(handler.update_form))
    app.router.add_patch(f"{bp}/forms/{{form_id}}", _wrap_auth(handler.patch_form))
    app.router.add_delete(f"{bp}/forms/{{form_id}}", _wrap_auth(handler.delete_form))

    # Natural language editing
    app.router.add_post(
        f"{bp}/forms/{{form_id}}/edit", _wrap_auth(handler.edit_form)
    )

    # Clone endpoint
    app.router.add_post(
        f"{bp}/forms/{{form_id}}/clone", _wrap_auth(handler.clone_form)
    )

    # Contract endpoints (schema, style)
    app.router.add_get(
        f"{bp}/forms/{{form_id}}/schema", _wrap_auth(handler.get_schema)
    )
    app.router.add_get(
        f"{bp}/forms/{{form_id}}/style", _wrap_auth(handler.get_style)
    )

    # Render dispatcher (path-param format)
    app.router.add_get(
        f"{bp}/forms/{{form_id}}/render/{{format}}",
        _wrap_auth(render_module.handle_render),
    )

    # Validation + submissions
    app.router.add_post(
        f"{bp}/forms/{{form_id}}/validate", _wrap_auth(handler.validate)
    )
    app.router.add_post(
        f"{bp}/forms/{{form_id}}/data", _wrap_auth(handler.submit_data)
    )

    # Form-controls toolbar metadata
    app.router.add_get(
        f"{bp}/form-controls",
        _wrap_auth(controls_module.handle_form_controls),
    )

    # Atomic batched-edit endpoint (Wave 2d replaces the stub body)
    app.router.add_patch(
        f"{bp}/forms/{{form_id}}/operations",
        _wrap_auth(operations_module.handle_operations),
    )

    # REST field upload endpoint (Phase 3 — FEAT-170)
    app.router.add_post(
        f"{bp}/forms/{{form_id}}/fields/{{field_id}}/upload",
        _wrap_auth(uploads_module.handle_rest_upload),
    )

    # Partial saves (FEAT-186)
    app.router.add_post(
        f"{bp}/forms/{{form_id}}/partial", _wrap_auth(handler.save_partial)
    )
    app.router.add_get(
        f"{bp}/forms/{{form_id}}/partial", _wrap_auth(handler.get_partial)
    )
    app.router.add_delete(
        f"{bp}/forms/{{form_id}}/partial", _wrap_auth(handler.delete_partial)
    )

    # Remote lifecycle event bridge (FEAT-188)
    app.router.add_post(
        f"{bp}/forms/{{form_id}}/events/{{event_name}}",
        _wrap_auth(handler.remote_event),
    )

    # Audio WebSocket endpoint (FEAT-224) — NOT wrapped with _wrap_auth.
    # JWT auth is handled inside AudioFormWSHandler via TokenValidator because
    # navigator-auth decorators return HTTP 401, which is incompatible with
    # the WebSocket upgrade handshake.
    if synthesizer is not None or transcriber is not None:
        from .audio_ws import AudioFormWSHandler
        from ..services.validators import FormValidator

        audio_handler = AudioFormWSHandler(
            registry=registry,
            synthesizer=synthesizer,
            transcriber=transcriber,
            validator=FormValidator(),
            token_validator=token_validator,
            submission_storage=submission_storage,
        )
        app.router.add_get(
            f"{bp}/forms/{{form_id}}/audio/ws",
            audio_handler.handle_websocket,
        )
        logger.info("setup_form_api: audio WS endpoint mounted at %s/forms/{form_id}/audio/ws", bp)

    logger.info("setup_form_api: mounted on %s", bp)
