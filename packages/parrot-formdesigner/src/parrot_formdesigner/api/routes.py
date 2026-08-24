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

Autonomous FormSchema persistence (FEAT-457): passing ``alias_registry``
wires the connection-alias allowlist as the ``app["form_sink_aliases"]``
app key — an explicit, testable, deliberately NOT runtime-mutable
security control (no route ever mutates it). A ``SinkFactory`` is built
from it and injected into ``FormAPIHandler``; a shutdown hook closes
every cached sink. Omitting ``alias_registry`` (the default) leaves the
feature entirely inactive — forms without a ``persistence`` block behave
exactly as before this feature existed.
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

from ..services.public_forms import public_form_paths
from ..services.registry import FormRegistry
from ..services.sinks.factory import SinkFactory
from . import controls as controls_module
from . import file_upload as file_upload_module
from . import operations as operations_module
from . import render as render_module
from . import uploads as uploads_module
from .handlers import FormAPIHandler
from .tenant import requires_tenant

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient
    from parrot.core.ws_auth import TokenValidator
    from parrot.voice.tts.synthesizer import VoiceSynthesizer
    from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend

    from ..services.blob_storage import AbstractBlobStorage
    from ..services.forwarder import SubmissionForwarder
    from ..services.org_graph import OrgGraphService
    from ..services.partial_saves import PartialSaveStore
    from ..services.project_service import ProjectService
    from ..services.rbac import RBACService
    from ..services.rest_field_resolver import RestFieldResolver
    from ..services.sink_aliases import SinkAliasRegistry
    from ..services.submissions import FormSubmissionStorage
    from ..services.venue_service import VenueService
    from ..services.workday_sync import WorkdayIdentitySyncAdapter


logger = logging.getLogger(__name__)


_Handler = Callable[[web.Request], Awaitable[web.Response]]

_TENANT_MODES = ("required", "public", "none")


def _wrap_auth(handler: _Handler, *, tenant: str = "required") -> _Handler:
    """Wrap a handler with navigator-auth ``is_authenticated`` + ``user_session``.

    Mirrors the previous ``handlers/routes.py:_wrap_auth`` shape, but without
    the ``_AUTH_AVAILABLE`` fallback — navigator-auth is a hard dep here.
    Also composes the ``requires_tenant`` decorator (FEAT-421) as the
    innermost layer, so it runs after ``user_session`` has populated
    ``request.session`` and before the handler body.

    Args:
        handler: A bound async coroutine accepting ``request: web.Request``.
        tenant: Tenant-enforcement mode — one of ``"required"`` (forms
            routes: declare + authorize, the default so a newly added forms
            route is protected by omission), ``"public"`` (public-form
            routes: declare, skip authorization), or ``"none"`` (``/org/*``
            routes: no tenant layer at all).

    Returns:
        The decorated handler.

    Raises:
        ValueError: ``tenant`` is not one of the three valid modes.
    """
    if tenant not in _TENANT_MODES:
        raise ValueError(f"tenant must be one of {_TENANT_MODES}, got {tenant!r}")

    tenant_applied = tenant != "none"
    if tenant_applied:
        handler = requires_tenant(public=(tenant == "public"))(handler)

    @wraps(handler)
    async def _inner(request: web.Request, **kwargs) -> web.Response:
        # user_session's _func_wrapper injects session= and user= kwargs.
        # Our handlers don't accept those — consume them here so they
        # don't cause a TypeError, then call the original handler.
        return await handler(request)

    decorated = user_session()(_inner)
    decorated = is_authenticated(content_type="application/json")(decorated)
    if tenant_applied:
        decorated._requires_tenant = True
    return decorated


def _reserved_tenant_segments(app: web.Application, bp: str) -> frozenset[str]:
    """Derive reserved literal segments from the router (FEAT-429 Module 5).

    Introspects every route already registered on ``app`` and collects the
    literal (non-``{tenant}``) first path segment of any route mounted
    directly under ``bp`` — the exact tree level the dynamic ``{tenant}``
    segment occupies. This is what makes the reserved set DERIVED rather
    than hardcoded (spec Module 5 / AC13): calling this AFTER a module's
    own routes are registered means any literal added later in that same
    function is picked up automatically, with no second edit required.

    Args:
        app: The aiohttp application whose router has already had this
            module's routes registered.
        bp: The stripped base path (``base_path.rstrip("/")``) routes in
            this module were mounted under — ``""`` for a root mount.

    Returns:
        The set of literal first-segment strings sitting at the same tree
        level as ``{tenant}`` under ``bp`` (e.g. ``{"org",
        "form-controls"}``). Empty when no such literal exists.
    """
    reserved: set[str] = set()
    for route in app.router.routes():
        resource = route.resource
        if resource is None:
            continue
        canonical = resource.canonical
        if bp and not canonical.startswith(f"{bp}/"):
            continue
        remainder = canonical[len(bp) :].lstrip("/")
        if not remainder:
            continue
        first_segment = remainder.split("/", 1)[0]
        if first_segment and not first_segment.startswith("{"):
            reserved.add(first_segment)
    return frozenset(reserved)


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
    org_graph_service: "OrgGraphService | None" = None,
    project_service: "ProjectService | None" = None,
    rbac_service: "RBACService | None" = None,
    workday_adapter: "WorkdayIdentitySyncAdapter | None" = None,
    venue_service: "VenueService | None" = None,
    rbac_enforcing: bool = False,
    alias_registry: "SinkAliasRegistry | None" = None,
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
            endpoints (POST/GET/DELETE ``/forms/{form_uid}/partial``) will
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
        alias_registry: Optional ``SinkAliasRegistry`` (FEAT-457). When
            provided, exposed as the ``app["form_sink_aliases"]`` app key
            and used to build a ``SinkFactory`` injected into
            ``FormAPIHandler`` — forms declaring ``persistence`` write to
            their own sink. ``None`` (default) leaves the feature
            entirely inactive; no route ever mutates this allowlist.
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

    # FEAT-457 — Autonomous FormSchema Persistence. The alias allowlist is
    # an explicit, deliberately NOT runtime-mutable security control: no
    # route below ever writes to `app["form_sink_aliases"]`. Omitting
    # `alias_registry` (the default) leaves the feature entirely inactive
    # — `sink_factory` stays `None` and forms without a `persistence`
    # block behave exactly as before this feature existed.
    sink_factory: SinkFactory | None = None
    if alias_registry is not None:
        app["form_sink_aliases"] = alias_registry
        sink_factory = SinkFactory(alias_registry)

        async def _close_sink_factory(app: web.Application) -> None:
            await sink_factory.close_all()

        app.on_shutdown.append(_close_sink_factory)

    handler = FormAPIHandler(
        registry=registry,
        client=client,
        submission_storage=submission_storage,
        forwarder=forwarder,
        partial_store=partial_store,
        org_graph_service=org_graph_service,
        project_service=project_service,
        rbac_service=rbac_service,
        workday_adapter=workday_adapter,
        venue_service=venue_service,
        rbac_enforcing=rbac_enforcing,
        sink_factory=sink_factory,
    )
    app["form_api_handler"] = handler

    bp = base_path.rstrip("/")
    # FEAT-421: every FORMS route is mounted under a declared `{tenant}`
    # path component so the tenant is a declared, cross-checkable path
    # component rather than an inferred value. aiohttp's UrlDispatcher
    # resolves literal child nodes before dynamic ones at every tree
    # level, so `{tenant}` safely coexists with the literal `/org/*`
    # branch, which is UNCHANGED (spec G7, AC11). FEAT-429 removed the
    # literal `t` disambiguation marker segment as unnecessary (see spec §2).
    tp = f"{bp}/{{tenant}}"

    # CRUD + listing
    app.router.add_get(f"{tp}/forms", _wrap_auth(handler.list_forms))
    app.router.add_post(f"{tp}/forms", _wrap_auth(handler.create_form))
    app.router.add_post(f"{tp}/forms/from-db", _wrap_auth(handler.load_from_db))
    # Blank form creation (FEAT-389) — MUST be registered BEFORE the
    # {form_uid} catch-all routes below, so the literal "blank" segment is
    # never captured as a form_uid path param.
    app.router.add_post(f"{tp}/forms/blank", _wrap_auth(handler.create_blank_form))
    # GET /forms/{form_uid} is the one CRUD route also reachable by public
    # forms (is_public=True) — tenant="public" skips authorization (the
    # form's is_public flag IS the grant) but the tenant is still mandatory.
    app.router.add_get(
        f"{tp}/forms/{{form_uid}}",
        _wrap_auth(handler.get_form, tenant="public"),
    )
    app.router.add_put(f"{tp}/forms/{{form_uid}}", _wrap_auth(handler.update_form))
    app.router.add_patch(f"{tp}/forms/{{form_uid}}", _wrap_auth(handler.patch_form))
    app.router.add_delete(f"{tp}/forms/{{form_uid}}", _wrap_auth(handler.delete_form))

    # Natural language editing
    app.router.add_post(f"{tp}/forms/{{form_uid}}/edit", _wrap_auth(handler.edit_form))

    # Clone endpoint
    app.router.add_post(f"{tp}/forms/{{form_uid}}/clone", _wrap_auth(handler.clone_form))

    # Contract endpoints (schema, style). /schema is one of the five
    # public-form globs (services/public_forms.py); /style is not.
    app.router.add_get(
        f"{tp}/forms/{{form_uid}}/schema",
        _wrap_auth(handler.get_schema, tenant="public"),
    )
    app.router.add_get(f"{tp}/forms/{{form_uid}}/style", _wrap_auth(handler.get_style))

    # Render dispatcher (path-param format) — a public-form glob.
    app.router.add_get(
        f"{tp}/forms/{{form_uid}}/render/{{format}}",
        _wrap_auth(render_module.handle_render, tenant="public"),
    )

    # Validation + submissions — both public-form globs.
    app.router.add_post(
        f"{tp}/forms/{{form_uid}}/validate",
        _wrap_auth(handler.validate, tenant="public"),
    )
    app.router.add_post(
        f"{tp}/forms/{{form_uid}}/data",
        _wrap_auth(handler.submit_data, tenant="public"),
    )

    # Form-controls toolbar metadata — static, tenant-agnostic field-type
    # catalog (no registry access, no per-tenant data). Path unchanged,
    # not under {tp}: tenant="none", same carve-out as /org/*.
    app.router.add_get(
        f"{bp}/form-controls",
        _wrap_auth(controls_module.handle_form_controls, tenant="none"),
    )

    # Atomic batched-edit endpoint (Wave 2d replaces the stub body)
    app.router.add_patch(
        f"{tp}/forms/{{form_uid}}/operations",
        _wrap_auth(operations_module.handle_operations),
    )

    # REST field upload endpoint (Phase 3 — FEAT-170; field_uid FEAT-393)
    app.router.add_post(
        f"{tp}/forms/{{form_uid}}/fields/{{field_uid}}/upload",
        _wrap_auth(uploads_module.handle_rest_upload),
    )

    # Raw upload field types (FILE/IMAGE/IMAGE_DROPZONE/MULTI_UPLOAD) — FEAT-460
    app.router.add_post(
        f"{tp}/forms/{{form_uid}}/fields/{{field_uid}}/file-upload",
        _wrap_auth(file_upload_module.handle_file_upload),
    )

    # Partial saves (FEAT-186)
    app.router.add_post(f"{tp}/forms/{{form_uid}}/partial", _wrap_auth(handler.save_partial))
    app.router.add_get(f"{tp}/forms/{{form_uid}}/partial", _wrap_auth(handler.get_partial))
    app.router.add_delete(f"{tp}/forms/{{form_uid}}/partial", _wrap_auth(handler.delete_partial))

    # Remote lifecycle event bridge (FEAT-188)
    app.router.add_post(
        f"{tp}/forms/{{form_uid}}/events/{{event_name}}",
        _wrap_auth(handler.remote_event),
    )

    # Audio WebSocket endpoint (FEAT-224, FEAT-236) — NOT wrapped with
    # _wrap_auth. JWT auth is handled inside AudioFormWSHandler via
    # TokenValidator because navigator-auth decorators return HTTP 401, which is
    # incompatible with the WebSocket upgrade handshake. FEAT-421: its tenant
    # check is inline inside the handler (TASK-2204), not this decorator —
    # deliberately left undecorated, see spec §7 "Known Risks".
    #
    # FEAT-236: when audio is intended (transcriber/token_validator provided)
    # but no explicit ``synthesizer`` is injected, the handler synthesizes TTS
    # via the SuperTonic-first fallback helper (``auto_synthesize=True``). No
    # ONNX model is loaded here — ``VoiceSynthesizer`` is lazy and the backend
    # only loads on first ``synthesize()``. An explicitly-injected
    # ``synthesizer`` takes precedence over the lazy build.
    if synthesizer is not None or transcriber is not None or token_validator is not None:
        from .audio_ws import AudioFormWSHandler
        from ..services.validators import FormValidator

        audio_handler = AudioFormWSHandler(
            registry=registry,
            synthesizer=synthesizer,
            transcriber=transcriber,
            validator=FormValidator(),
            token_validator=token_validator,
            submission_storage=submission_storage,
            auto_synthesize=synthesizer is None,
        )
        app.router.add_get(
            f"{tp}/forms/{{form_uid}}/audio/ws",
            audio_handler.handle_websocket,
        )
        logger.info("setup_form_api: audio WS endpoint mounted at %s/{tenant}/forms/{form_uid}/audio/ws", bp)
    # FEAT-300 — publish, question-bank, version history, import-report
    # Note: /versions and /import-report routes are registered BEFORE the
    # generic /{form_uid} catch-all to avoid shadowing issues if the router
    # were order-sensitive (aiohttp matches on specificity, but belt-and-braces).
    app.router.add_post(f"{tp}/forms/{{form_uid}}/publish", _wrap_auth(handler.publish_form))
    app.router.add_get(f"{tp}/fields", _wrap_auth(handler.list_fields))
    app.router.add_post(f"{tp}/fields", _wrap_auth(handler.create_field))
    app.router.add_get(f"{tp}/forms/{{form_uid}}/versions", _wrap_auth(handler.list_versions))
    app.router.add_get(
        f"{tp}/forms/{{form_uid}}/versions/{{version}}",
        _wrap_auth(handler.get_version),
    )
    app.router.add_get(
        f"{tp}/forms/{{form_uid}}/import-report",
        _wrap_auth(handler.get_import_report),
    )

    # FEAT-302 — Org Graph + RBAC + Projects + Workday sync
    # FEAT-421 G7: the /org/* surface is untouched — paths stay
    # byte-identical to 0.8.21 and none of them carries the tenant
    # decorator (tenant="none"). Organizations are the layer that
    # *defines* tenants; scoping them by one would invert the dependency.
    app.router.add_get(f"{bp}/org/graph", _wrap_auth(handler.get_org_graph, tenant="none"))
    app.router.add_post(f"{bp}/org/projects", _wrap_auth(handler.create_project, tenant="none"))
    app.router.add_post(
        f"{bp}/org/cost-centers/{{project_id}}/workday-map",
        _wrap_auth(handler.map_project_workday, tenant="none"),
    )
    app.router.add_post(
        f"{bp}/org/users/{{user_id}}/assign",
        _wrap_auth(handler.assign_user_role, tenant="none"),
    )
    app.router.add_post(
        f"{bp}/org/sync/workday",
        _wrap_auth(handler.sync_workday_identities, tenant="none"),
    )

    # FEAT-330 — Store sub-structure (Store → Site → Location)
    app.router.add_get(
        f"{bp}/org/stores/{{store_id}}/sites",
        _wrap_auth(handler.list_sites, tenant="none"),
    )
    app.router.add_post(
        f"{bp}/org/stores/{{store_id}}/sites",
        _wrap_auth(handler.create_site, tenant="none"),
    )
    app.router.add_get(
        f"{bp}/org/sites/{{site_id}}/locations",
        _wrap_auth(handler.list_locations, tenant="none"),
    )
    app.router.add_post(
        f"{bp}/org/sites/{{site_id}}/locations",
        _wrap_auth(handler.create_location, tenant="none"),
    )
    app.router.add_get(
        f"{bp}/org/locations/{{location_id}}",
        _wrap_auth(handler.get_location, tenant="none"),
    )

    # FEAT-241 M6: Wire is_public toggle → auth exclude list.
    # When app["auth"] is present and supports register_exclusions, register an
    # async callback on the FormRegistry that is invoked whenever a form's
    # is_public flag changes (False→True registers paths; True→False unregisters).
    _auth = app.get("auth")
    if _auth is not None:
        if not hasattr(_auth, "register_exclusions"):
            logger.warning(
                "setup_form_api: app['auth'] is present but lacks register_exclusions — "
                "is_public toggle disabled. Upgrade navigator-auth to >=0.20.11."
            )
        else:
            _bp = bp  # capture stripped base_path in closure

            async def _public_toggle(form_uid: str, is_public: bool) -> None:
                # FEAT-389: FormRegistry now fires the public-toggle callback
                # with form_uid (not form_id) — see registry.py's register()/
                # unregister() firing sites. Routes are form_uid-based
                # (TASK-1976), so exclusion patterns must match.
                #
                # FEAT-421: public_form_paths() now needs the form's tenant to
                # build a tenant-qualified glob. The callback signature is
                # fixed to (form_uid, is_public) — FormRegistry is unchanged
                # by this feature — so the tenant is resolved HERE, at
                # callback time, rather than cached from an earlier lookup:
                # a form can be re-tenanted while staying public (no toggle
                # fires on tenant change alone), so a cached tenant value
                # could register/unregister the wrong tenant's exemption.
                if is_public:
                    tenant = None
                    for candidate_tenant in await registry.list_tenants():
                        if await registry.get(form_uid, tenant=candidate_tenant):
                            tenant = candidate_tenant
                            break
                    if tenant is None:
                        logger.warning(
                            "setup_form_api: public_toggle could not resolve "
                            "a tenant for form_uid=%s — exclusion registration "
                            "skipped",
                            form_uid,
                        )
                        return
                    _auth.register_exclusions(public_form_paths(form_uid, tenant, base_path=_bp))
                else:
                    # The form may already be gone (unregister() fires this
                    # callback AFTER removing the form — FEAT-241) or may
                    # have been re-tenanted since it was registered, so its
                    # current/former tenant cannot be resolved reliably.
                    # Sweep every known tenant: unregistering a glob that
                    # was never registered is a harmless no-op, and this is
                    # the only way to guarantee no stale exemption survives
                    # a delete or a re-tenant.
                    for candidate_tenant in await registry.list_tenants():
                        _auth.unregister_exclusions(public_form_paths(form_uid, candidate_tenant, base_path=_bp))

            registry.set_public_toggle_callback(_public_toggle)
            logger.info("setup_form_api: is_public toggle wired to auth exclude list (base_path=%s)", _bp)

    # FEAT-241 M7: Register exclude-provider for restart re-hydration.
    # On each server startup, AuthHandler will invoke this provider and
    # register the paths for all persisted is_public=True forms, restoring
    # auth exemptions that were wiped when the exclude list was re-seeded.
    #
    # Startup-ordering note: auth_startup (which invokes providers) may fire
    # before FormRegistry.on_startup (which loads forms from storage) because
    # aiohttp calls on_startup hooks in FIFO order and AuthHandler.setup() is
    # typically called before FormRegistry is constructed.  To guarantee correct
    # results regardless of setup order, the provider calls load_from_storage()
    # itself when a backend is configured, then lists all tenants so that
    # multi-tenant deployments are fully covered.
    if _auth is not None and hasattr(_auth, "add_exclude_provider"):
        _bp_m7 = bp  # capture stripped base_path in closure

        async def _public_forms_exclude_provider() -> list[str]:
            """Yield auth-exempt paths for all persisted is_public=True forms.

            Proactively loads from storage (when configured) before listing so
            this provider returns correct results even when invoked before
            FormRegistry.on_startup has had a chance to hydrate the in-memory
            cache.  Iterates all registered tenants to cover multi-tenant
            deployments.
            """
            paths: list[str] = []
            try:
                # Proactively hydrate from storage in case auth_startup fires
                # before FormRegistry.on_startup (startup-ordering safety).
                if registry.has_storage:
                    await registry.load_from_storage()
                # Iterate all tenants so no tenant's public forms are missed.
                for tenant in await registry.list_tenants():
                    for form in await registry.list_forms(tenant=tenant):
                        if form.is_public:
                            paths.extend(public_form_paths(form.form_uid, tenant, base_path=_bp_m7))
            except Exception as exc:
                logger.warning("public_forms_exclude_provider: failed: %s", exc)
            return paths

        _auth.add_exclude_provider(_public_forms_exclude_provider)
        logger.info(
            "setup_form_api: exclude-provider registered for restart re-hydration (base_path=%s)",
            _bp_m7,
        )

    # FEAT-429 Module 5: reserved-segment guard. Every route above is now
    # registered, so introspect the router for literal (non-`{tenant}`)
    # first-path-segments sitting directly under `bp` — the exact tree
    # level `{tenant}` occupies (today: `org`, `form-controls`). DERIVED
    # from the actual registrations (spec Module 5 / AC13: "never
    # hardcoded"), so a future literal route added anywhere above is
    # reserved automatically, with no second edit required. Merged (union)
    # with any reserved set already stashed by the other setup function on
    # the same app, since requires_tenant() is shared across the API and UI
    # surfaces and a tenant identity is not siloed per mount.
    api_reserved_tenant_segments = _reserved_tenant_segments(app, bp)
    app["formdesigner_reserved_tenant_segments"] = (
        app.get("formdesigner_reserved_tenant_segments", frozenset()) | api_reserved_tenant_segments
    )

    # FEAT-429 Module 5: boot-time warning when a provisioned tenant
    # collides with a reserved literal segment (see the reserved-segment
    # guard above and api/tenant.py's requires_tenant()). Reads the
    # reserved set from `app` at startup time (not the local variable
    # above) so it reflects the FINAL merged set regardless of whether
    # setup_form_api or setup_form_ui ran last.
    async def _warn_reserved_tenant_collisions(app: web.Application) -> None:
        reserved = app.get("formdesigner_reserved_tenant_segments", frozenset())
        if not reserved:
            return
        colliding = sorted(set(await registry.list_tenants()) & reserved)
        if colliding:
            logger.warning(
                "setup_form_api: registry tenant(s) %s collide with a reserved "
                "literal route segment — these tenants are UNREACHABLE via the "
                "tenant-qualified forms routes (requires_tenant() returns 404 "
                "for them). Rename the tenant or the colliding literal route.",
                colliding,
            )

    app.on_startup.append(_warn_reserved_tenant_collisions)

    logger.info("setup_form_api: mounted on %s", bp)
