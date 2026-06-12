"""JSON REST API handlers for parrot-formdesigner.

Serves the form builder REST API: create, list, get schema, validate, load
from DB. HTML rendering moved to the render dispatcher in ``api/render.py``.

All endpoints are protected by navigator-auth session authentication via
``api/routes.py`` (hard import — see FEAT-152).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, get_args

from aiohttp import web
from pydantic import ValidationError
from navigator.responses import JSONResponse
from ..core.events import FormEventAbort, FormEventName

from ..core.schema import FormField, FormSchema, RenderedForm
from ..renderers.jsonschema import JsonSchemaRenderer
from ..services.auth_context import AuthContext
from ..services.csrf import issue_form_csrf_token, validate_form_csrf_token
from ..services.event_dispatcher import apply_schema_overrides, dispatch
from ..services.registry import FormAlreadyExistsError, FormRegistry
from ..services.validators import FormValidator
from ._utils import _bump_version, _deep_merge, _loc_to_str

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient

    from ..services.form_version import FormVersionService
    from ..services.forwarder import SubmissionForwarder
    from ..services.partial_saves import PartialSaveStore
    from ..services.question_bank import QuestionBankService
    from ..services.submissions import FormSubmissionStorage
    from ..tools.services.networkninja import ImportDiffReport


class FormAPIHandler:
    """Serves JSON REST API endpoints for form management.

    All API routes are protected by navigator-auth session authentication.
    The decorators are applied at route-registration time in
    ``api/routes.py``.

    User identity context (``org_id``, ``programs``) is extracted from the
    authenticated session via the :meth:`_get_org_id` and :meth:`_get_programs`
    helper methods.

    Args:
        registry: FormRegistry instance for storing and retrieving forms.
        client: Optional LLM client for natural language form creation.
        submission_storage: Optional storage backend for form submissions.
        forwarder: Optional submission forwarder for endpoint-bound submits.
        partial_store: Optional Redis-backed store for ephemeral partial form
            answers.  When ``None``, partial save endpoints return 503.
    """

    def __init__(
        self,
        registry: FormRegistry,
        client: "AbstractClient | None" = None,
        submission_storage: "FormSubmissionStorage | None" = None,
        forwarder: "SubmissionForwarder | None" = None,
        partial_store: "PartialSaveStore | None" = None,
    ) -> None:
        self.registry = registry
        self._client = client
        self._submission_storage = submission_storage
        self._forwarder = forwarder
        self._partial_store = partial_store
        self.schema_renderer = JsonSchemaRenderer()
        self.validator = FormValidator()
        self.logger = logging.getLogger(__name__)

        # Pre-construct tools once (avoid per-request instantiation overhead)
        from ..tools.create_form import CreateFormTool
        from ..tools.database_form import DatabaseFormTool
        self._create_tool = CreateFormTool(
            client=self._get_llm_client(),
            registry=self.registry
        )
        self._db_tool = DatabaseFormTool(
            registry=self.registry
        )

        # FEAT-300 — form version service (lazy-init so tests can override)
        self._version_service: "FormVersionService | None" = None

        # FEAT-300 — per-tenant QuestionBankService cache (one instance per tenant)
        self._question_banks: "dict[str, QuestionBankService]" = {}

        # FEAT-300 — per-form import diff reports (populated by import flows).
        # Keyed by (tenant, form_id) to prevent cross-tenant leaks (review M3).
        self._import_reports: "dict[tuple[str, str], ImportDiffReport]" = {}

    def _get_llm_client(self) -> "AbstractClient | None":
        """Return the configured LLM client, lazily creating a GoogleGenAI default.

        If a client was passed at init time, returns it directly. Otherwise
        creates a ``GoogleGenAIClient`` on first call and caches it.

        Returns:
            An ``AbstractClient`` instance, or ``None`` if instantiation fails.
        """
        if self._client is not None:
            return self._client
        try:
            from parrot.clients.google import GoogleGenAIClient
            self._client = GoogleGenAIClient()
        except Exception as exc:
            self.logger.warning("Failed to create default GoogleGenAIClient: %s", exc)
            return None
        return self._client

    # ------------------------------------------------------------------
    # User context helpers (navigator-auth integration)
    # ------------------------------------------------------------------

    def _get_org_id(self, request: web.Request) -> int | None:
        """Extract org_id from the authenticated user's first organization.

        Reads ``request.user.organizations[0].org_id`` as set by the
        ``@user_session()`` decorator from navigator-auth and normalises it
        to an integer (the DB primary key type).

        Args:
            request: Incoming HTTP request with ``user`` attribute attached
                by the navigator-auth ``user_session`` decorator.

        Returns:
            The ``org_id`` as an integer from the first organization, or
            ``None`` if the user has no organizations, the user is not set,
            or the value cannot be converted to an integer.
        """
        user = getattr(request, "user", None)
        if user and user.organizations:
            try:
                return int(user.organizations[0].org_id)
            except (TypeError, ValueError):
                self.logger.warning(
                    "org_id value %r is not a valid integer",
                    user.organizations[0].org_id,
                )
                return None
        return None

    def _get_programs(self, request: web.Request) -> list[str]:
        """Extract programs (tenant context) from the user session.

        Reads ``session.get("session", {}).get("programs", [])`` where the
        outer ``"session"`` key is the ``AUTH_SESSION_OBJECT`` constant from
        navigator-auth (value: ``"session"``).

        Args:
            request: Incoming HTTP request with ``session`` attribute attached
                by the navigator-auth ``user_session`` decorator.

        Returns:
            A list of program slug strings. Returns an empty list when no
            programs are found or no session is available.
        """
        session = getattr(request, "session", None)
        if session is None:
            return []
        userinfo = session.get("session", {})
        return userinfo.get("programs", [])

    def _get_tenant(self, request: web.Request) -> str:
        """Extract the effective tenant for this request.

        Returns the first program slug from the navigator-auth session (as set
        by :meth:`_get_programs`). When no programs are present — anonymous
        requests, sessions without program scope, or test setups without
        navigator-auth — falls back to the registry's configured
        ``default_tenant`` so write paths don't crash on
        ``require_tenant=True``.

        Args:
            request: Incoming HTTP request with ``session`` attribute attached
                by the navigator-auth ``user_session`` decorator.

        Returns:
            A tenant slug string — never ``None``.
        """
        programs = self._get_programs(request)
        if programs:
            return programs[0]
        return self.registry.default_tenant

    def _build_auth_context(self, request: web.Request) -> AuthContext:
        """Build AuthContext from the inbound aiohttp request.

        Checks (in order):
        1. ``request["auth_context"]`` — set by navigator-auth middleware if present.
        2. ``Authorization: Bearer <token>`` header.
        3. ``Authorization: ApiKey <token>`` header.
        4. Defaults to ``AuthContext(scheme="none")``.

        Args:
            request: The incoming aiohttp web.Request.

        Returns:
            AuthContext for this request.
        """
        # 1. Check if middleware already resolved auth
        if "auth_context" in request:
            existing = request["auth_context"]
            if isinstance(existing, AuthContext):
                return existing

        # 2. Authorization header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            return AuthContext(
                scheme="bearer",
                token=token,
                headers={"Authorization": auth_header},
            )
        if auth_header.startswith("ApiKey "):
            token = auth_header[7:]
            return AuthContext(
                scheme="api_key",
                token=token,
                headers={"X-API-Key": token},
            )

        # 3. Default: no auth
        return AuthContext(scheme="none")

    # ------------------------------------------------------------------
    # Partial-save helpers
    # ------------------------------------------------------------------

    def _extract_session_id(self, request: web.Request) -> str | None:
        """Extract the session ID from the navigator-auth session.

        Follows the verified pattern from ``api/uploads.py:316-319``.

        Args:
            request: Incoming HTTP request with ``session`` attribute.

        Returns:
            Session ID string, or ``None`` if unavailable.
        """
        session_id: str | None = None
        if "session" in request:
            _sid = request["session"].get("id")
            session_id = str(_sid) if _sid else None
        return session_id

    def _find_field(
        self, form: FormSchema, field_id: str
    ) -> "FormField | None":
        """Find a FormField by field_id, searching all sections.

        Args:
            form: FormSchema to search.
            field_id: Field identifier to find.

        Returns:
            The matching FormField, or None if not found.
        """
        for section in form.sections:
            for field in section.iter_fields():
                if field.field_id == field_id:
                    return field
        return None

    # ------------------------------------------------------------------
    # Partial-save REST endpoints
    # ------------------------------------------------------------------

    async def save_partial(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/{form_id}/partial — Save partial answers.

        Merges the submitted answers into the cached partial for this
        form+session.  Each submitted field is validated individually via
        ``FormValidator.validate_field()`` and per-field errors are returned
        in the response.

        Request body::

            {"answers": {"field_id": <value>, ...}}

        Args:
            request: Incoming HTTP request.

        Returns:
            200 — full PartialFormData state as JSON, including field_errors.
            400 — invalid JSON body or missing session_id.
            404 — form not found in registry.
            503 — partial save service not configured or Redis unavailable.
        """
        if self._partial_store is None:
            return JSONResponse(
                {"error": "Partial save service not configured"}, status=503
            )

        form_id = request.match_info["form_id"]

        session_id = self._extract_session_id(request)
        if not session_id:
            return JSONResponse(
                {"error": "Session ID required"}, status=400
            )

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        answers: dict = body.get("answers", {})

        if not isinstance(answers, dict):
            return JSONResponse(
                {"error": "'answers' must be a JSON object"}, status=400
            )

        if not answers:
            existing = await self._partial_store.get(form_id, session_id)
            if existing is not None:
                return JSONResponse(existing.model_dump(mode="json"), status=200)
            return JSONResponse(
                {"form_id": form_id, "session_id": session_id, "data": {}, "field_errors": {}},
                status=200,
            )

        form = await self.registry.get(form_id)
        if form is None:
            return JSONResponse(
                {"error": f"Form '{form_id}' not found"}, status=404
            )

        # Save merged answers to store
        try:
            partial = await self._partial_store.save(form_id, session_id, answers)
        except Exception as exc:
            self.logger.warning(
                "PartialSaveStore.save failed for %s/%s: %s", form_id, session_id, exc
            )
            return JSONResponse(
                {"error": "Partial save service unavailable"}, status=503
            )

        # Per-field validation (non-blocking — store all, report errors)
        field_errors: dict[str, list[str]] = {}
        for field_id, value in answers.items():
            field = self._find_field(form, field_id)
            if field is not None:
                errors = await self.validator.validate_field(field, value)
                if errors:
                    field_errors[field_id] = errors

        # Attach field_errors to the PartialFormData using model_copy
        if field_errors:
            partial = partial.model_copy(update={"field_errors": field_errors})
            # Persist updated partial (with field_errors) back to Redis so that
            # GET /partial returns the last validation state.
            try:
                await self._partial_store._redis_set(
                    await self._partial_store._get_redis(), partial
                )
            except Exception as exc:
                self.logger.warning(
                    "PartialSaveStore: failed to persist field_errors for %s/%s: %s",
                    form_id,
                    session_id,
                    exc,
                )

        return JSONResponse(
            partial.model_dump(mode="json"), status=200
        )

    async def get_partial(self, request: web.Request) -> web.Response:
        """GET /api/v1/forms/{form_id}/partial — Retrieve cached partial answers.

        Args:
            request: Incoming HTTP request.

        Returns:
            200 — PartialFormData as JSON.
            400 — missing session_id.
            404 — no cached partial for this form+session.
            503 — partial save service not configured.
        """
        if self._partial_store is None:
            return JSONResponse(
                {"error": "Partial save service not configured"}, status=503
            )

        form_id = request.match_info["form_id"]

        session_id = self._extract_session_id(request)
        if not session_id:
            return JSONResponse(
                {"error": "Session ID required"}, status=400
            )

        try:
            partial = await self._partial_store.get(form_id, session_id)
        except Exception as exc:
            self.logger.warning(
                "PartialSaveStore.get failed for %s/%s: %s", form_id, session_id, exc
            )
            return JSONResponse(
                {"error": "Partial save service unavailable"}, status=503
            )

        if partial is None:
            return JSONResponse(
                {"error": "No partial save found for this form and session"},
                status=404,
            )

        return JSONResponse(
            partial.model_dump(mode="json"), status=200
        )

    async def delete_partial(self, request: web.Request) -> web.Response:
        """DELETE /api/v1/forms/{form_id}/partial — Clear cached partial answers.

        Args:
            request: Incoming HTTP request.

        Returns:
            204 — partial cleared (or did not exist).
            400 — missing session_id.
            503 — partial save service not configured.
        """
        if self._partial_store is None:
            return JSONResponse(
                {"error": "Partial save service not configured"}, status=503
            )

        form_id = request.match_info["form_id"]

        session_id = self._extract_session_id(request)
        if not session_id:
            return JSONResponse(
                {"error": "Session ID required"}, status=400
            )

        try:
            await self._partial_store.delete(form_id, session_id)
        except Exception as exc:
            self.logger.warning(
                "PartialSaveStore.delete failed for %s/%s: %s",
                form_id,
                session_id,
                exc,
            )

        return web.Response(status=204)

    async def list_forms(self, request: web.Request) -> web.Response:
        """GET /api/v1/forms — List all registered forms with rich metadata.

        Merges in-memory FormRegistry entries with persisted FormStorage rows
        (when a storage backend is configured). Each entry includes form_id,
        title, description, version, source ("memory" | "db"), and an
        ISO-8601 created_at (or None).

        Args:
            request: Incoming HTTP request.

        Returns:
            JSON response ``{"forms": [<descriptor>, ...]}`` sorted by form_id.
        """
        tenant = self._get_tenant(request)
        in_memory = await self.registry.list_forms(tenant=tenant)
        descriptors: dict[str, dict] = {}

        for form in in_memory:
            ts = form.created_at
            descriptors[form.form_id] = {
                "form_id": form.form_id,
                "title": _loc_to_str(form.title),
                "description": _loc_to_str(form.description),
                "version": form.version,
                "source": "memory",
                "created_at": ts.isoformat() if ts is not None else None,
            }

        storage = self.registry.storage
        if storage is not None:
            try:
                persisted = await storage.list_forms(tenant=tenant)
            except Exception as exc:
                self.logger.warning("FormStorage.list_forms failed: %s", exc)
                persisted = []

            for row in persisted:
                fid = row.get("form_id")
                if not fid:
                    continue
                existing = descriptors.get(fid)
                if existing is not None:
                    # In both: registry wins for title/description/version,
                    # storage wins for created_at; mark source as "db".
                    existing["source"] = "db"
                    if row.get("created_at") is not None:
                        existing["created_at"] = row["created_at"]
                else:
                    descriptors[fid] = {
                        "form_id": fid,
                        "title": _loc_to_str(row.get("title")),
                        "description": _loc_to_str(row.get("description")),
                        "version": row.get("version", "1.0"),
                        "source": "db",
                        "created_at": row.get("created_at"),
                    }

        forms = sorted(descriptors.values(), key=lambda d: d["form_id"])
        return JSONResponse({"forms": forms})

    @staticmethod
    def _form_has_remote_binding(form: FormSchema) -> bool:
        """Return True if the form declares any event binding with remote=True.

        Args:
            form: FormSchema to inspect.

        Returns:
            ``True`` when at least one binding has ``remote=True``.
        """
        events = getattr(form, "events", None)
        if events is None:
            return False
        for field_name in type(events).model_fields:
            binding = getattr(events, field_name, None)
            if binding is not None and getattr(binding, "remote", False):
                return True
        return False

    async def get_form(self, request: web.Request) -> web.Response:
        """GET /api/v1/forms/{form_id} — Get full FormSchema as JSON."""
        form_id = request.match_info["form_id"]
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_id, tenant=tenant)
        if form is None:
            return JSONResponse({"error": f"Form '{form_id}' not found"}, status=404)
        # lifecycle: onBeforeOpen — can abort or mutate (abort only in MVP)
        try:
            await dispatch(
                "onBeforeOpen",
                form=form,
                request=request,
                tenant=tenant,
                auth_context=self._build_auth_context(request),
            )
        except FormEventAbort as exc:
            return JSONResponse(
                {"error": exc.user_message, "reason": exc.reason},
                status=exc.status_code,
            )
        response = JSONResponse(form.model_dump(mode="json", exclude_none=True))
        # Attach CSRF token when the form has any remote-bridged binding
        if self._form_has_remote_binding(form):
            session_id = self._extract_session_id(request)
            if session_id:
                response.headers["X-Form-CSRF-Token"] = issue_form_csrf_token(
                    session_id, form_id
                )
        return response

    async def get_schema(self, request: web.Request) -> web.Response:
        """GET /api/v1/forms/{form_id}/schema — Get JSON Schema (structural)."""
        form_id = request.match_info["form_id"]
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_id, tenant=tenant)
        if form is None:
            return JSONResponse({"error": f"Form '{form_id}' not found"}, status=404)
        rendered: RenderedForm = await self.schema_renderer.render(form)
        # lifecycle: onSchemaLoaded — can apply shallow schema_overrides
        try:
            resolution = await dispatch(
                "onSchemaLoaded",
                form=form,
                request=request,
                tenant=tenant,
                auth_context=self._build_auth_context(request),
                schema_dump=rendered.content,
            )
        except FormEventAbort as exc:
            return JSONResponse(
                {"error": exc.user_message, "reason": exc.reason},
                status=exc.status_code,
            )
        content = rendered.content
        if resolution.schema_overrides:
            content = apply_schema_overrides(content, dict(resolution.schema_overrides))
        return JSONResponse(content)

    async def get_style(self, request: web.Request) -> web.Response:
        """GET /api/v1/forms/{form_id}/style — Get style schema."""
        form_id = request.match_info["form_id"]
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_id, tenant=tenant)
        if form is None:
            return JSONResponse({"error": f"Form '{form_id}' not found"}, status=404)
        style = form.meta.get("style") if form.meta else None
        return JSONResponse(style or {})

    async def remote_event(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/{form_id}/events/{event_name} — Remote event bridge.

        Called by the HTML5 renderer when a binding declares ``remote: true``.
        Validates a per-session per-form CSRF token, dispatches the lifecycle
        event, and returns the ``EventResolution`` as JSON.

        Args:
            request: Incoming POST request with ``form_id`` and ``event_name``
                in the URL, ``X-CSRF-Token`` header, and a JSON body optionally
                containing ``payload`` and ``schema_dump``.

        Returns:
            200 — EventResolution JSON.
            400 — Unknown event name or invalid JSON body.
            403 — Missing or invalid CSRF token.
            404 — Form not found.
            status from FormEventAbort.status_code — when a handler aborts.
        """
        form_id = request.match_info["form_id"]
        event_name = request.match_info["event_name"]

        # 1. Validate event_name against the FormEventName Literal
        if event_name not in get_args(FormEventName):
            return JSONResponse(
                {"error": f"Unknown event '{event_name}'"}, status=400
            )

        # 2. Load form
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_id, tenant=tenant)
        if form is None:
            return JSONResponse(
                {"error": f"Form '{form_id}' not found"}, status=404
            )

        # 3. CSRF validation
        session_id = self._extract_session_id(request)
        token = request.headers.get("X-CSRF-Token") or request.headers.get(
            "X-Form-CSRF-Token"
        )
        if (
            not session_id
            or not token
            or not validate_form_csrf_token(session_id, form_id, token)
        ):
            return JSONResponse(
                {"error": "CSRF token invalid or missing"}, status=403
            )

        # 4. Parse body
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError, Exception):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        # 5. Build auth context (with fallback)
        try:
            auth_ctx = self._build_auth_context(request)
        except Exception as _auth_exc:
            self.logger.warning(
                "remote_event: _build_auth_context failed for form=%r event=%r — "
                "falling back to scheme=none. Error: %s",
                form_id,
                event_name,
                _auth_exc,
            )
            auth_ctx = AuthContext(scheme="none")

        # 6. Dispatch the event
        try:
            resolution = await dispatch(
                event_name,  # type: ignore[arg-type]
                form=form,
                request=request,
                tenant=tenant,
                auth_context=auth_ctx,
                payload=body.get("payload"),
                schema_dump=body.get("schema_dump"),
            )
        except FormEventAbort as exc:
            return JSONResponse(
                {"error": exc.user_message, "reason": exc.reason},
                status=exc.status_code,
            )

        return JSONResponse(resolution.model_dump(mode="json", exclude_none=True))

    async def validate(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/{form_id}/validate — Validate form submission."""
        form_id = request.match_info["form_id"]
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_id, tenant=tenant)
        if form is None:
            return JSONResponse({"error": f"Form '{form_id}' not found"}, status=404)
        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        result = await self.validator.validate(form, data)
        status = 200 if result.is_valid else 422
        return JSONResponse(
            {"is_valid": result.is_valid, "errors": result.errors},
            status=status,
        )

    async def create_form(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms — Create a form from a natural language prompt."""
        # _create_tool was initialised with the client available at construction
        # time. Check its client directly rather than calling _get_llm_client()
        # again, so the guard accurately reflects the tool's actual state.
        if self._create_tool.client is None:
            return JSONResponse(
                {"error": "No LLM client configured for form creation"},
                status=503,
            )
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        prompt = body.get("prompt")
        if not prompt:
            return JSONResponse({"error": "prompt is required"}, status=400)

        tenant = self._get_tenant(request)
        from ..tools.create_form import CreateFormTool
        create_tool = CreateFormTool(
            client=self._get_llm_client(),
            registry=self.registry,
            tenant=tenant,
        )
        result = await create_tool.execute(prompt=prompt, persist=True)

        if not result.success:
            return JSONResponse(
                {"error": result.metadata.get("error", "Form creation failed")},
                status=500,
            )

        form_data = result.metadata.get("form", {})
        form_id = form_data.get("form_id")
        if not form_id:
            return JSONResponse(
                {"error": "Form creation succeeded but form_id missing"},
                status=500,
            )
        title = (result.result or {}).get("title", "")
        prefix = request.app.get("_form_prefix", "")
        return JSONResponse({
            "form_id": form_id,
            "title": title,
            "url": f"{prefix}/forms/{form_id}",
        })

    async def edit_form(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/{form_id}/edit — Edit a form using natural language.

        Loads the existing form from the registry, passes its JSON schema to the
        LLM along with the user's edit prompt, and returns the updated form.
        The LLM is instructed to strictly preserve the FormSchema JSON structure.
        """
        if self._create_tool.client is None:
            return JSONResponse(
                {"error": "No LLM client configured for form editing"},
                status=503,
            )

        form_id = request.match_info["form_id"]
        tenant = self._get_tenant(request)
        existing = await self.registry.get(form_id, tenant=tenant)
        if existing is None:
            return JSONResponse(
                {"error": f"Form '{form_id}' not found"}, status=404
            )

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        prompt = body.get("prompt")
        if not prompt:
            return JSONResponse({"error": "prompt is required"}, status=400)

        from ..tools.create_form import CreateFormTool
        create_tool = CreateFormTool(
            client=self._get_llm_client(),
            registry=self.registry,
            tenant=tenant,
        )
        result = await create_tool.execute(
            prompt=prompt,
            refine_form_id=form_id,
            persist=True,
        )

        if not result.success:
            return JSONResponse(
                {"error": result.metadata.get("error", "Form editing failed")},
                status=500,
            )

        form_data = result.metadata.get("form", {})
        updated_form_id = form_data.get("form_id")
        if not updated_form_id:
            return JSONResponse(
                {"error": "Form editing succeeded but form_id missing"},
                status=500,
            )
        title = (result.result or {}).get("title", "")
        prefix = request.app.get("_form_prefix", "")
        return JSONResponse({
            "form_id": updated_form_id,
            "title": title,
            "url": f"{prefix}/forms/{updated_form_id}",
        })

    async def clone_form(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/{form_id}/clone — Clone a form under a new ID.

        Creates a deep copy of the source form identified by ``form_id``,
        assigns ``new_form_id`` from the request body, optionally applies an
        RFC 7396 merge-patch, validates the result, and persists it.

        Request body (JSON):
            new_form_id (str): Required. Slug for the cloned form.
            patch (dict | None): Optional RFC 7396 merge-patch.
            tenant (str | None): Optional tenant override for the clone.

        Returns:
            201 Created with the full cloned ``FormSchema`` JSON body.
            400 if ``new_form_id`` is missing or empty.
            404 if the source form is not found.
            409 if ``new_form_id`` already exists.
            422 if the patch produces an invalid schema.
        """
        form_id = request.match_info["form_id"]

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        new_form_id = (body.get("new_form_id") or "").strip()
        if not new_form_id:
            return JSONResponse({"error": "new_form_id is required"}, status=400)

        patch = body.get("patch") or None
        if patch is not None and not isinstance(patch, dict):
            return JSONResponse(
                {"error": "patch must be a JSON object"}, status=400
            )
        tenant = body.get("tenant") or None

        try:
            clone = await self.registry.clone_form(
                form_id,
                new_form_id,
                patch,
                tenant=tenant,
            )
        except KeyError:
            return JSONResponse(
                {"error": f"Form '{form_id}' not found"}, status=404
            )
        except FormAlreadyExistsError as exc:
            return JSONResponse({"error": str(exc)}, status=409)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status=422)

        self.logger.info(
            "Cloned form '%s' -> '%s'", form_id, clone.form_id
        )
        return JSONResponse(clone.model_dump(mode="json"), status=201)

    async def update_form(self, request: web.Request) -> web.Response:
        """PUT /api/v1/forms/{form_id} — Fully replace a registered form.

        Accepts a complete ``FormSchema`` JSON body. The ``form_id`` in the URL
        must match the ``form_id`` in the body. Runs structural validation via
        ``FormValidator.check_schema()`` before persisting. Automatically bumps
        the form version.
        """
        form_id = request.match_info["form_id"]
        tenant = self._get_tenant(request)
        existing = await self.registry.get(form_id, tenant=tenant)
        if existing is None:
            return JSONResponse(
                {"error": f"Form '{form_id}' not found"}, status=404
            )

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        if not isinstance(body, dict) or body.get("form_id") != form_id:
            return JSONResponse(
                {"error": "form_id in URL and body must match"}, status=400
            )

        body["version"] = _bump_version(existing.version)
        # published_version is immutable from the API surface — only
        # FormVersionService.publish() may set it (review M1).
        body.pop("published_version", None)
        body["published_version"] = existing.published_version

        try:
            form = FormSchema.model_validate(body)
        except ValidationError as exc:
            return JSONResponse({"errors": exc.errors()}, status=422)

        schema_errors = self.validator.check_schema(form)
        if schema_errors:
            return JSONResponse({"errors": schema_errors}, status=422)

        persist = self.registry.has_storage
        await self.registry.register(form, persist=persist, overwrite=True, tenant=tenant)
        self.logger.info("PUT form '%s' → version %s", form_id, form.version)
        return JSONResponse(form.model_dump(mode="json", exclude_none=True))

    async def patch_form(self, request: web.Request) -> web.Response:
        """PATCH /api/v1/forms/{form_id} — Partially update a registered form.

        Applies RFC 7396 JSON merge-patch semantics to the existing form.
        Arrays (sections, fields) are replaced entirely — not merged
        element-by-element. ``form_id`` cannot be changed via PATCH.
        Runs structural validation after merging. Automatically bumps version.
        """
        form_id = request.match_info["form_id"]
        tenant = self._get_tenant(request)
        existing = await self.registry.get(form_id, tenant=tenant)
        if existing is None:
            return JSONResponse(
                {"error": f"Form '{form_id}' not found"}, status=404
            )

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        if not body:
            return JSONResponse(
                {"error": "PATCH body must not be empty"}, status=400
            )

        existing_dict = existing.model_dump()
        merged = _deep_merge(existing_dict, body)
        merged["version"] = _bump_version(existing.version)
        # Prevent form_id change via PATCH
        merged["form_id"] = form_id
        # published_version is immutable from the API surface — only
        # FormVersionService.publish() may set it (review M1).
        merged["published_version"] = existing.published_version

        try:
            form = FormSchema.model_validate(merged)
        except ValidationError as exc:
            return JSONResponse({"errors": exc.errors()}, status=422)

        schema_errors = self.validator.check_schema(form)
        if schema_errors:
            return JSONResponse({"errors": schema_errors}, status=422)

        persist = self.registry.has_storage
        await self.registry.register(form, persist=persist, overwrite=True, tenant=tenant)
        self.logger.info("PATCH form '%s' → version %s", form_id, form.version)
        return JSONResponse(form.model_dump(mode="json", exclude_none=True))

    async def delete_form(self, request: web.Request) -> web.Response:
        """DELETE /api/v1/forms/{form_id} — Remove a registered form.

        Unregisters the form from the in-memory registry and, when a
        ``FormStorage`` backend is configured, deletes the persisted row as
        well (scoped by the form's tenant so per-tenant Postgres schemas
        resolve correctly). Returns ``204 No Content`` on success, ``404``
        when no form with the given id exists.
        """
        form_id = request.match_info["form_id"]
        tenant = self._get_tenant(request)
        existing = await self.registry.get(form_id, tenant=tenant)
        if existing is None:
            return JSONResponse(
                {"error": f"Form '{form_id}' not found"}, status=404
            )

        # Spec invariant (FEAT-300 §8, Vision IQ parity): a form with ≥1
        # response can never be deleted — only deactivated.
        version_svc = self._get_version_service()
        if not await version_svc.can_delete(form_id, tenant=tenant):
            return web.json_response(
                {
                    "error": (
                        f"Form '{form_id}' has responses and cannot be deleted. "
                        "Deactivate it instead."
                    )
                },
                status=409,
            )

        await self.registry.unregister(form_id, tenant=tenant)

        storage = self.registry.storage
        if storage is not None:
            try:
                await storage.delete(form_id, tenant=existing.tenant)
            except Exception as exc:
                self.logger.warning(
                    "FormStorage.delete failed for %s: %s", form_id, exc
                )

        self.logger.info("DELETE form '%s'", form_id)
        return web.Response(status=204)

    async def submit_data(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/{form_id}/data — Receive and process a form submission.

        Flow:
        1. Load the form from registry (404 if not found).
        2. Parse JSON body (400 if invalid).
        3. If ``?merge_partials=true``, load cached partial and merge into data
           (submitted values override cached; skipped silently if no store or
           no cached partial).
        4. Validate submission data (422 if invalid).
        5. Store locally if ``submission_storage`` is configured.
        6. Forward to endpoint if form has an ``endpoint`` submit action and
           ``forwarder`` is configured.
        7. If merge was performed, delete the cached partial on success.
        8. Return composite result — always 200, even when forwarding fails.
        """
        import uuid
        from datetime import datetime, timezone

        from ..services.metadata_enricher import (
            MetadataResolutionError,
            enrich_submission,
        )
        from ..services.submissions import FormSubmission

        form_id = request.match_info["form_id"]
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_id, tenant=tenant)
        if form is None:
            return JSONResponse(
                {"error": f"Form '{form_id}' not found"}, status=404
            )

        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        # lifecycle: outer envelope for onError dispatch on any exception.
        # FormEventAbort from onBeforeSubmit is caught INSIDE and handled
        # directly — it is never routed through onError (spec §7).
        # _auth_ctx is computed lazily on first dispatch call to avoid
        # breaking tests that mock request.headers as a generic MagicMock.
        _auth_ctx = None

        try:
            try:
                _auth_ctx = self._build_auth_context(request)
            except Exception:
                _auth_ctx = AuthContext(scheme="none")

            # Optional: merge cached partial answers into submitted data
            # (?merge_partials=true — submitted values take precedence)
            _merge_session_id: str | None = None
            merge_partials = request.query.get("merge_partials", "").lower() == "true"
            if merge_partials and self._partial_store is not None:
                _merge_session_id = self._extract_session_id(request)
                if _merge_session_id:
                    try:
                        cached = await self._partial_store.get(form_id, _merge_session_id)
                        if cached:
                            # cached values fill gaps; submitted values win on overlap
                            data = {**cached.data, **data}
                            self.logger.debug(
                                "Merged %d cached partial fields into submit for %s/%s",
                                len(cached.data),
                                form_id,
                                _merge_session_id,
                            )
                    except Exception as exc:
                        self.logger.warning(
                            "Failed to load partial for merge %s/%s: %s",
                            form_id,
                            _merge_session_id,
                            exc,
                        )

            # lifecycle: onBeforeSubmit — may mutate payload or abort
            try:
                resolution = await dispatch(
                    "onBeforeSubmit",
                    form=form,
                    request=request,
                    tenant=tenant,
                    auth_context=_auth_ctx,
                    payload=data,
                )
                if resolution.payload is not None:
                    data = dict(resolution.payload)
            except FormEventAbort as exc:
                # Abort is a controlled flow — do NOT route through onError.
                return JSONResponse(
                    {"error": exc.user_message, "reason": exc.reason},
                    status=exc.status_code,
                )

            # Validate submission data against form schema
            result = await self.validator.validate(form, data)
            if not result.is_valid:
                _validation_exc = ValueError(f"Validation failed: {result.errors}")
                # dispatch onError (best-effort) before the early 422 return
                try:
                    _err_res = await dispatch(
                        "onError",
                        form=form,
                        request=request,
                        tenant=tenant,
                        auth_context=_auth_ctx,
                        error=_validation_exc,
                    )
                except Exception as _meta_exc:
                    self.logger.exception("onError handler raised during validation: %s", _meta_exc)
                return JSONResponse(
                    {"is_valid": False, "errors": result.errors},
                    status=422,
                )

            # Build submission record
            submission = FormSubmission(
                submission_id=str(uuid.uuid4()),
                form_id=form_id,
                form_version=form.version,
                data=result.sanitized_data,
                is_valid=True,
                created_at=datetime.now(timezone.utc),
            )

            # Metadata enrichment runs between validation and storage so the
            # resolved values are persisted alongside the answers.
            if form.metadata:
                try:
                    core_overrides, extra_flat = await enrich_submission(
                        request=request,
                        form=form,
                        submission=submission,
                        answers=result.sanitized_data,
                        auth_context=_auth_ctx,
                    )
                except MetadataResolutionError as exc:
                    # dispatch onError (best-effort) before the early 422 return
                    try:
                        await dispatch(
                            "onError",
                            form=form,
                            request=request,
                            tenant=tenant,
                            auth_context=_auth_ctx,
                            error=exc,
                        )
                    except Exception as _meta_exc:
                        self.logger.exception(
                            "onError handler raised during metadata: %s", _meta_exc
                        )
                    return JSONResponse(
                        {"is_valid": False, "errors": {"_metadata": str(exc)}},
                        status=422,
                    )
                if core_overrides:
                    submission = submission.model_copy(update=core_overrides)
                if extra_flat:
                    submission.data = {**submission.data, **extra_flat}

            # Store locally (if storage configured)
            if self._submission_storage is not None:
                await self._submission_storage.store(submission)
            else:
                self.logger.debug(
                    "No submission_storage configured — skipping local storage for %s",
                    submission.submission_id,
                )

            # Forward to endpoint (if form has endpoint action and forwarder configured)
            forwarded = False
            forward_status = None
            forward_error = None
            if (
                form.submit is not None
                and form.submit.action_type == "endpoint"
                and self._forwarder is not None
            ):
                fwd_result = await self._forwarder.forward(result.sanitized_data, form.submit)
                forwarded = fwd_result.success
                forward_status = fwd_result.status_code
                forward_error = fwd_result.error
                if not forwarded:
                    self.logger.warning(
                        "Forward failed for submission %s: %s",
                        submission.submission_id,
                        forward_error,
                    )

            # Cleanup: delete cached partial after successful submission
            if merge_partials and _merge_session_id and self._partial_store is not None:
                try:
                    await self._partial_store.delete(form_id, _merge_session_id)
                    self.logger.debug(
                        "Deleted cached partial for %s/%s after successful submit",
                        form_id,
                        _merge_session_id,
                    )
                except Exception as exc:
                    self.logger.warning(
                        "Failed to delete partial after submit %s/%s: %s",
                        form_id,
                        _merge_session_id,
                        exc,
                    )

            # lifecycle: onAfterSubmit — side-effects only; failures routed via onError
            await dispatch(
                "onAfterSubmit",
                form=form,
                request=request,
                tenant=tenant,
                auth_context=_auth_ctx,
                payload=submission.data,
            )

            return JSONResponse({
                "submission_id": submission.submission_id,
                "is_valid": True,
                "forwarded": forwarded,
                "forward_status": forward_status,
                "forward_error": forward_error,
            })

        except FormEventAbort:
            # Already handled above — re-raise so it surfaces correctly
            # if there is an outer handler.
            raise
        except Exception as exc:
            # lifecycle: onError — dispatch and then re-raise original exception.
            # The original status code (422 for validation, 500 for unexpected)
            # is preserved because we re-raise.
            _user_message: str | None = None
            try:
                _err_res = await dispatch(
                    "onError",
                    form=form,
                    request=request,
                    tenant=tenant,
                    auth_context=_auth_ctx,
                    error=exc,
                )
                _user_message = _err_res.user_message
            except Exception as meta_exc:
                self.logger.exception("onError handler itself raised: %s", meta_exc)
            if _user_message:
                # Surface friendly message in the request for outer error handlers
                request["_lifecycle_user_message"] = _user_message
            self.logger.exception(
                "submit_data failed for form %r: %s", form_id, exc
            )
            raise

    async def load_from_db(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/from-db — Load a form from database definition.

        The ``orgid`` in the request body is optional. When omitted, the
        ``org_id`` is extracted from the authenticated user's session via
        :meth:`_get_org_id`. If neither the body nor the session provides an
        ``org_id``, the request is rejected with a 400 error.
        """
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        formid = body.get("formid")

        # orgid: body takes precedence over session
        orgid = body.get("orgid")
        if orgid is None:
            orgid = self._get_org_id(request)

        if formid is None or orgid is None:
            missing = [name for name, val in [("formid", formid), ("orgid", orgid)] if val is None]
            return JSONResponse(
                {"error": f"Missing required field(s): {', '.join(missing)}"},
                status=400,
            )

        try:
            formid = int(formid)
            orgid = int(orgid)
        except (TypeError, ValueError):
            return JSONResponse(
                {"error": "'formid' and 'orgid' must be integers"},
                status=422,
            )

        if formid < 1 or orgid < 1:
            return JSONResponse(
                {"error": "'formid' and 'orgid' must be positive integers"},
                status=422,
            )

        service = str(body.get("service", "networkninja"))
        tenant = self._get_tenant(request)
        from ..tools.database_form import DatabaseFormTool
        db_tool = DatabaseFormTool(registry=self.registry, tenant=tenant)
        result = await db_tool.execute(
            service=service, formid=formid, orgid=orgid, persist=False
        )

        if not result.success:
            error_msg = result.metadata.get("error", "Failed to load form from database")
            status = 404 if "not found" in error_msg.lower() else 500
            return JSONResponse({"error": error_msg}, status=status)

        form_data = result.metadata.get("form", {})
        form_id = form_data.get("form_id")
        if not form_id:
            return JSONResponse(
                {"error": "Form load succeeded but form_id missing"},
                status=500,
            )

        # FEAT-300: persist the per-field ImportDiffReport so
        # GET /forms/{form_id}/import-report can serve it (review H2).
        report_data = result.metadata.get("import_report")
        if report_data:
            from ..tools.services.networkninja import ImportDiffReport
            self._import_reports[(tenant, form_id)] = (
                ImportDiffReport.model_validate(report_data)
            )

        title = (result.result or {}).get("title", "")
        prefix = request.app.get("_form_prefix", "")
        return JSONResponse({
            "form_id": form_id,
            "title": title,
            "url": f"{prefix}/forms/{form_id}",
        })

    # ------------------------------------------------------------------
    # FEAT-300 helpers — version service + question bank
    # ------------------------------------------------------------------

    def _get_version_service(self) -> "FormVersionService":
        """Return the shared FormVersionService, initialising it lazily.

        Returns:
            Configured ``FormVersionService`` instance.
        """
        if self._version_service is None:
            from ..services.form_version import FormVersionService
            self._version_service = FormVersionService(self.registry)
        return self._version_service

    def _make_question_bank(self, tenant: str) -> "QuestionBankService":
        """Return a tenant-scoped QuestionBankService, creating it on first call.

        One service instance is cached per tenant so in-memory state (and DB
        connections when a storage backend is configured) is shared across
        requests within the same handler lifetime.

        Args:
            tenant: Tenant slug for this request.

        Returns:
            ``QuestionBankService`` backed by the registry's storage (or
            in-memory when no storage backend is configured).
        """
        if tenant not in self._question_banks:
            from ..services.question_bank import QuestionBankService
            self._question_banks[tenant] = QuestionBankService(
                storage=self.registry.storage,  # type: ignore[arg-type]
                tenant=tenant,
            )
        return self._question_banks[tenant]

    # ------------------------------------------------------------------
    # FEAT-300 — publish / question-bank / version / import-report endpoints
    # ------------------------------------------------------------------

    async def publish_form(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/{form_id}/publish — Publish current form as immutable snapshot.

        Bumps the form's semver minor tag and freezes the current state as a
        published snapshot. Returns ``409`` when the computed tag already
        exists (immutability guard). Returns ``404`` when the form is not found.

        Args:
            request: Incoming HTTP request (path param: ``form_id``).

        Returns:
            ``{"form_id": str, "version": str}`` on success (200),
            ``{"error": str}`` on 404 (not found) or 409 (frozen conflict).
        """
        form_id = request.match_info["form_id"]
        tenant = self._get_tenant(request)
        svc = self._get_version_service()
        try:
            version = await svc.publish(form_id, tenant=tenant)
        except KeyError as exc:
            return web.json_response({"error": str(exc)}, status=404)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except Exception as exc:
            self.logger.exception("publish_form failed for '%s': %s", form_id, exc)
            return web.json_response({"error": str(exc)}, status=500)
        self.logger.info("Published form '%s' → version '%s'", form_id, version)
        return web.json_response({"form_id": form_id, "version": version})

    async def list_fields(self, request: web.Request) -> web.Response:
        """GET /api/v1/fields — List all reusable fields for the current tenant.

        Args:
            request: Incoming HTTP request.

        Returns:
            ``{"fields": [<ReusableField>, ...]}`` (200).
        """
        tenant = self._get_tenant(request)
        svc = self._make_question_bank(tenant)
        fields = await svc.list_fields()
        return web.json_response(
            {"fields": [f.model_dump(mode="json") for f in fields]}
        )

    async def create_field(self, request: web.Request) -> web.Response:
        """POST /api/v1/fields — Add a field definition to the question bank.

        Args:
            request: Incoming HTTP request with ``FormField`` JSON body.

        Returns:
            ``ReusableField`` JSON (201 Created), ``400`` on bad JSON, ``422``
            on validation errors.
        """
        tenant = self._get_tenant(request)
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        from ..core.schema import FormField
        try:
            field_def = FormField.model_validate(body)
        except ValidationError as exc:
            return web.json_response({"error": exc.errors(include_url=False)}, status=422)

        svc = self._make_question_bank(tenant)
        entry = await svc.create_field(field_def)
        return web.json_response(entry.model_dump(mode="json"), status=201)

    async def list_versions(self, request: web.Request) -> web.Response:
        """GET /api/v1/forms/{form_id}/versions — List published version history.

        Each entry includes ``version``, ``published_at`` (ISO-8601),
        ``published_by`` (``null`` when not tracked), and ``is_current``
        (``True`` for the form's active published version).

        Args:
            request: Incoming HTTP request (path param: ``form_id``).

        Returns:
            ``{"form_id": str, "versions": [...]}`` (200), ``404`` if not found.
        """
        form_id = request.match_info["form_id"]
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_id, tenant=tenant)
        if form is None:
            return web.json_response({"error": f"Form '{form_id}' not found"}, status=404)

        svc = self._get_version_service()
        meta_list = await svc.list_versions(form_id, tenant=tenant)
        current_version = form.published_version or form.version

        return web.json_response({
            "form_id": form_id,
            "versions": [
                {
                    "version": m.version,
                    "published_at": m.published_at.isoformat(),
                    "published_by": None,
                    "is_current": m.version == current_version,
                }
                for m in meta_list
            ],
        })

    async def get_version(self, request: web.Request) -> web.Response:
        """GET /api/v1/forms/{form_id}/versions/{version} — Retrieve a frozen snapshot.

        Returns the immutable ``FormSchema`` snapshot for the requested semver
        tag. Returns ``404`` when the form or version is not found.

        Args:
            request: Incoming HTTP request (path params: ``form_id``, ``version``).

        Returns:
            Full ``FormSchema`` JSON (200) or ``{"error": str}`` (404).
        """
        form_id = request.match_info["form_id"]
        version = request.match_info["version"]
        tenant = self._get_tenant(request)
        svc = self._get_version_service()
        snap = await svc.get_published(form_id, version=version, tenant=tenant)
        if snap is None:
            return web.json_response(
                {"error": f"Version '{version}' of form '{form_id}' not found"},
                status=404,
            )
        return web.json_response(snap.model_dump(mode="json"))

    async def get_import_report(self, request: web.Request) -> web.Response:
        """GET /api/v1/forms/{form_id}/import-report — Latest ImportDiffReport.

        Returns the per-field mapping report generated when this form was last
        imported from an external source (e.g. Networkninja). Returns ``404``
        when no import history exists for this form.

        Args:
            request: Incoming HTTP request (path param: ``form_id``).

        Returns:
            ``ImportDiffReport`` JSON (200) or ``{"error": str}`` (404).
        """
        form_id = request.match_info["form_id"]
        tenant = self._get_tenant(request)
        report = self._import_reports.get((tenant, form_id))
        if report is None:
            return web.json_response(
                {"error": f"No import report found for form '{form_id}'"},
                status=404,
            )
        return web.json_response(report.model_dump(mode="json"))

    async def evaluate_form(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/{form_id}/evaluate — Server-side rule evaluation.

        Evaluates all ``DependencyRule`` conditions in the form against the
        provided context (current answers + location variables + visit context)
        and returns a per-field visibility/effect map.

        **Intended uses**:

        1. **Thin/server-driven clients** (Adaptive Card / Teams) that cannot
           run a local rule evaluator and need the server to drive visibility.
        2. **Authoritative re-validation at submit** — the client sends the
           final answer set and the server confirms the visibility state used
           for validation.  Any divergence between client-side and server-side
           evaluation is surfaced here.

        **Note on ``location_vars``**: In the request body, ``location_vars``
        is for testing/preview only.  In production, the server injects the
        location variable snapshot into the form payload when the form is
        served for a visit (so the client always has a consistent snapshot).

        Body (all keys optional — missing keys default to ``{}``):
            ``{"answers": {"field_id": <value>, ...},``
            ``"location_vars": {"key": <value>, ...},``
            ``"visit_context": {"key": <value>, ...}}``

        Returns:
            200: ``{"results": {"field_id": {"effect": "show"|"hide"|..., "matched": bool}}}``
            400: ``{"error": "..."}`` — malformed JSON body or non-dict values.
            404: ``{"error": "..."}`` — form not found.

        Args:
            request: Incoming HTTP request (path param: ``form_id``).
        """
        from ..services.rule_evaluator import EvaluationContext, DEFAULT_EVALUATOR

        form_id = request.match_info["form_id"]
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_id, tenant=tenant)
        if form is None:
            return web.json_response(
                {"error": f"Form '{form_id}' not found"}, status=404
            )

        # Parse body — all keys optional
        try:
            raw_body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        if not isinstance(raw_body, dict):
            return web.json_response(
                {"error": "Request body must be a JSON object"}, status=400
            )

        answers = raw_body.get("answers", {})
        location_vars = raw_body.get("location_vars", {})
        visit_context = raw_body.get("visit_context", {})

        if not isinstance(answers, dict) or not isinstance(location_vars, dict) or not isinstance(visit_context, dict):
            return web.json_response(
                {"error": "answers, location_vars, and visit_context must be objects"},
                status=400,
            )

        try:
            context = EvaluationContext(
                answers=answers,
                location_vars=location_vars,
                visit_context=visit_context,
            )
        except Exception as exc:
            return web.json_response({"error": f"Invalid context: {exc}"}, status=422)

        evaluator = DEFAULT_EVALUATOR
        results = evaluator.evaluate_form(form, context)

        return web.json_response({
            "results": {
                field_id: {"effect": r.effect, "matched": r.matched}
                for field_id, r in results.items()
            }
        })
