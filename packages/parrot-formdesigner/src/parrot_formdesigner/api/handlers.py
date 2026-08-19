"""JSON REST API handlers for parrot-formdesigner.

Serves the form builder REST API: create, list, get schema, validate, load
from DB. HTML rendering moved to the render dispatcher in ``api/render.py``.

All endpoints are protected by navigator-auth session authentication via
``api/routes.py`` (hard import — see FEAT-152).
"""

from __future__ import annotations

import json
import logging
import uuid as _uuid
from typing import TYPE_CHECKING, Any, get_args

from aiohttp import web
from pydantic import ValidationError
from navigator.responses import JSONResponse
from ..core.events import FormEventAbort, FormEventName

from ..core.resolution import find_field_by_uid
from ..core.schema import FormField, FormSchema, RenderedForm
from ..renderers.jsonschema import JsonSchemaRenderer
from ..services.auth_context import AuthContext
from ..services.csrf import issue_form_csrf_token, validate_form_csrf_token
from ..services.event_dispatcher import apply_schema_overrides, dispatch
from ..services.registry import FormAlreadyExistsError, FormRegistry
from ..services.validators import FormValidator
from ._utils import _bump_version, _deep_merge, _loc_to_str
from .tenant import (
    assert_body_tenant_matches,
    declared_tenant,
    enforce_membership_unless_public,
)


def extract_form_uid(request: web.Request) -> _uuid.UUID:
    """Extract and validate ``form_uid`` from the request path (FEAT-389).

    Args:
        request: Incoming aiohttp request with ``form_uid`` in
            ``request.match_info`` (populated by the ``{form_uid}`` route
            pattern registered in ``api/routes.py``).

    Returns:
        The validated ``form_uid`` as a ``uuid.UUID``.

    Raises:
        web.HTTPBadRequest: If the path segment is not a well-formed UUID.
            The response is JSON: ``{"error": "..."}``.
    """
    raw = request.match_info["form_uid"]
    try:
        return _uuid.UUID(raw)
    except ValueError:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": f"Invalid form_uid: {raw!r} is not a valid UUID"}),
            content_type="application/json",
        )


def extract_uid(request: web.Request, param: str) -> _uuid.UUID:
    """Extract and validate a named UUID path param (FEAT-393).

    Generalizes :func:`extract_form_uid` to any ``{param}`` path segment
    (e.g. ``field_uid`` on the upload route).

    Args:
        request: Incoming aiohttp request with ``param`` in
            ``request.match_info``.
        param: Name of the path param to extract (e.g. ``"field_uid"``).

    Returns:
        The validated UUID.

    Raises:
        web.HTTPBadRequest: If the path segment is missing or not a
            well-formed UUID. The response is JSON: ``{"error": "..."}``.
    """
    raw = request.match_info.get(param)
    try:
        return _uuid.UUID(raw)
    except (KeyError, TypeError, ValueError):
        raise web.HTTPBadRequest(
            text=json.dumps({"error": f"Invalid {param}: {raw!r} is not a valid UUID"}),
            content_type="application/json",
        )

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient

    from ..core.partial import PartialFormData
    from ..services.form_version import FormVersionService
    from ..services.forwarder import SubmissionForwarder
    from ..services.org_graph import OrgGraphService
    from ..services.partial_saves import PartialSaveStore
    from ..services.project_service import ProjectService
    from ..services.question_bank import QuestionBankService
    from ..services.rbac import RBACService
    from ..services.submissions import FormSubmissionStorage
    from ..services.venue_service import VenueService
    from ..services.workday_sync import WorkdayIdentitySyncAdapter
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
        org_graph_service: Optional ``OrgGraphService`` for ``GET /org/graph``.
            When ``None``, the endpoint returns 501 Not Implemented.
        project_service: Optional ``ProjectService`` for org project endpoints.
        rbac_service: Optional ``RBACService`` for policy management endpoints.
        workday_adapter: Optional ``WorkdayIdentitySyncAdapter`` for
            ``POST /org/sync/workday``.
        rbac_enforcing: When ``False`` (default), RBAC gate-keeping on existing
            form endpoints runs in **shadow mode** — it logs permission checks
            but never blocks requests. Set to ``True`` only when nav-auth
            policies are fully configured. Consistent with ``Policy.enforcing=False``.
    """

    def __init__(
        self,
        registry: FormRegistry,
        client: "AbstractClient | None" = None,
        submission_storage: "FormSubmissionStorage | None" = None,
        forwarder: "SubmissionForwarder | None" = None,
        partial_store: "PartialSaveStore | None" = None,
        org_graph_service: "OrgGraphService | None" = None,
        project_service: "ProjectService | None" = None,
        rbac_service: "RBACService | None" = None,
        workday_adapter: "WorkdayIdentitySyncAdapter | None" = None,
        venue_service: "VenueService | None" = None,
        rbac_enforcing: bool = False,
    ) -> None:
        self.registry = registry
        self._client = client
        self._submission_storage = submission_storage
        self._forwarder = forwarder
        self._partial_store = partial_store
        # FEAT-302 — Org Graph services
        self._org_graph_service = org_graph_service
        self._project_service = project_service
        self._rbac_service = rbac_service
        self._workday_adapter = workday_adapter
        # FEAT-330 — Store sub-structure (Site / Location)
        self._venue_service = venue_service
        self.rbac_enforcing = rbac_enforcing
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
        # Keyed by (tenant, form_uid) to prevent cross-tenant leaks (review M3).
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
        """Return the tenant declared in the URL and validated by the decorator.

        FEAT-421: the client declares which tenant a forms request is
        about, in the URL (``/{tenant}/...``); ``requires_tenant``
        (``api/tenant.py``) validates and authorizes that declaration
        before the handler ever runs. This method's signature is
        preserved exactly so the 21 forms call sites are untouched — only
        this body changed. The old three-step host-context/session/default
        fallback chain is gone from the forms HTTP boundary entirely; see
        :meth:`_session_tenant` for the ``/org/*``-only survivor of the
        session-derived part of that inference.

        Args:
            request: Incoming HTTP request with the tenant already
                validated by ``@requires_tenant``.

        Returns:
            The declared tenant slug — never ``None``.

        Raises:
            RuntimeError: The route was mounted without
                ``@requires_tenant`` — a programming error, never a
                runtime fallback.
        """
        return declared_tenant(request)

    def _session_tenant(self, request: web.Request) -> str:
        """Legacy session-derived tenant, for ``/org/*`` only (FEAT-421 G7).

        Preserves the pre-0.9.0 :meth:`_get_tenant` behaviour verbatim:
        the first program slug from the navigator-auth session, falling
        back to the registry's configured ``default_tenant``. Organizations
        are the layer that *defines* tenants, so ``/org/*`` is out of scope
        for the tenant-URL scheme (spec G7) and keeps inferring its tenant
        from the session exactly as before. The explicit name (rather than
        sharing :meth:`_get_tenant`) is deliberate: it makes this surviving
        ``programs[0]`` inference greppable and impossible to reach from a
        forms handler by accident. See spec §7 "Residual" for why this
        arbitrary-index inference is left standing rather than fixed here.

        Args:
            request: Incoming HTTP request with ``session`` attribute
                attached by the navigator-auth ``user_session`` decorator.

        Returns:
            A tenant slug string — never ``None``.
        """
        programs = self._get_programs(request)
        if programs:
            return programs[0]
        return self.registry.default_tenant

    def _assert_form_tenant(self, form: FormSchema, tenant: str) -> None:
        """Assert a resolved form actually belongs to the declared tenant.

        Defense-in-depth after every ``registry.get``/``get_by_slug`` call in
        forms handlers: those lookups are already tenant-scoped (a form
        registered under a different tenant is invisible to them, returning
        ``None``, which callers already turn into a 404), so this assertion
        should never fire in practice. It exists so a future resolver
        change that bypasses tenant-scoping fails loudly here rather than
        silently serving a cross-tenant form. Raises 404, NEVER 403 — a 403
        would confirm the form exists under some other tenant, which is an
        existence oracle (spec §2).

        Args:
            form: The already-resolved (non-``None``) form.
            tenant: The declared (already-authorized) tenant for this
                request.

        Raises:
            web.HTTPNotFound: ``form.tenant`` differs from ``tenant``.
        """
        if form.tenant != tenant:
            self.logger.warning(
                "Cross-tenant form access blocked: form_uid=%s form.tenant=%s "
                "declared=%s",
                form.form_uid,
                form.tenant,
                tenant,
            )
            raise web.HTTPNotFound(
                text=json.dumps({"error": "form_not_found"}),
                content_type="application/json",
            )

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

    def _remap_partial_to_field_ids(
        self, form: FormSchema | None, partial: PartialFormData
    ) -> PartialFormData:
        """Map Redis-persisted ``field_uid`` keys back to CURRENT ``field_id``s.

        ``PartialSaveStore`` persists ``partial.data`` keyed by ``field_uid``
        (FEAT-393 / TASK-2003) so a mid-session ``field_id`` rename never
        orphans a saved answer. The wire contract (request/response) stays
        ``field_id``-keyed, so every read path must translate back via
        :func:`find_field_by_uid` before serializing.

        Args:
            form: The current ``FormSchema``, or ``None`` if the parent form
                no longer exists in the registry.
            partial: The ``PartialFormData`` as read from ``PartialSaveStore``.

        Returns:
            A copy of ``partial`` with ``data`` re-keyed by current
            ``field_id``. Entries whose ``field_uid`` no longer resolves to a
            field (deleted field, or — when ``form`` is ``None`` — deleted
            form) are dropped silently.
        """
        if form is None:
            return partial.model_copy(update={"data": {}})
        remapped: dict[str, Any] = {}
        for uid_str, value in partial.data.items():
            try:
                field_uid = _uuid.UUID(uid_str)
            except ValueError:
                continue
            found = find_field_by_uid(form, field_uid)
            if found is None:
                continue
            field, _section = found
            remapped[field.field_id] = value
        return partial.model_copy(update={"data": remapped})

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

        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)

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
            # PartialSaveStore's PartialFormData.form_id field is still str
            # (Module 9 / TASK-2003 territory) — form_uid is uuid.UUID since
            # FEAT-393, so stringify at this internal-service boundary.
            existing = await self._partial_store.get(str(form_uid), session_id)
            if existing is not None:
                # Stored data is field_uid-keyed (TASK-2003) — map back to
                # the CURRENT field_id for the wire response.
                form_for_remap = await self.registry.get(form_uid, tenant=tenant)
                existing = self._remap_partial_to_field_ids(form_for_remap, existing)
                return JSONResponse(existing.model_dump(mode="json"), status=200)
            return JSONResponse(
                {"form_uid": form_uid, "session_id": session_id, "data": {}, "field_errors": {}},
                status=200,
            )

        form = await self.registry.get(form_uid, tenant=tenant)
        if form is None:
            return JSONResponse(
                {"error": f"Form '{form_uid}' not found"}, status=404
            )
        self._assert_form_tenant(form, tenant)

        # Resolve each incoming field_id to its field_uid BEFORE storing —
        # unknown field_ids are rejected (field error, not stored) instead of
        # being silently accepted; known fields are re-keyed by field_uid so
        # a mid-session field_id rename never orphans a saved answer
        # (FEAT-393 / TASK-2003). Storage stays UID-keyed; the wire
        # request/response contract stays field_id-keyed.
        uid_answers: dict[str, Any] = {}
        field_errors: dict[str, list[str]] = {}
        for field_id, value in answers.items():
            field = self._find_field(form, field_id)
            if field is None:
                field_errors[field_id] = ["unknown field_id"]
                continue
            errors = await self.validator.validate_field(field, value, all_data=answers)
            if errors:
                field_errors[field_id] = errors
            uid_answers[str(field.field_uid)] = value

        # Save merged (UID-keyed) answers to store
        try:
            partial = await self._partial_store.save(str(form_uid), session_id, uid_answers)
        except Exception as exc:
            self.logger.warning(
                "PartialSaveStore.save failed for %s/%s: %s", form_uid, session_id, exc
            )
            return JSONResponse(
                {"error": "Partial save service unavailable"}, status=503
            )

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
                    form_uid,
                    session_id,
                    exc,
                )

        # Map the UID-keyed stored data back to CURRENT field_ids for the
        # response (wire contract stays field_id-keyed); UIDs whose field
        # was deleted are dropped silently.
        partial = self._remap_partial_to_field_ids(form, partial)

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

        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)

        session_id = self._extract_session_id(request)
        if not session_id:
            return JSONResponse(
                {"error": "Session ID required"}, status=400
            )

        try:
            partial = await self._partial_store.get(str(form_uid), session_id)
        except Exception as exc:
            self.logger.warning(
                "PartialSaveStore.get failed for %s/%s: %s", form_uid, session_id, exc
            )
            return JSONResponse(
                {"error": "Partial save service unavailable"}, status=503
            )

        if partial is None:
            return JSONResponse(
                {"error": "No partial save found for this form and session"},
                status=404,
            )

        # Stored data is field_uid-keyed (TASK-2003) — map back to CURRENT
        # field_ids for the wire response; UIDs whose field was deleted
        # (or whose form no longer exists) are dropped silently.
        form = await self.registry.get(form_uid, tenant=tenant)
        partial = self._remap_partial_to_field_ids(form, partial)

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

        form_uid = extract_form_uid(request)

        session_id = self._extract_session_id(request)
        if not session_id:
            return JSONResponse(
                {"error": "Session ID required"}, status=400
            )

        try:
            await self._partial_store.delete(str(form_uid), session_id)
        except Exception as exc:
            self.logger.warning(
                "PartialSaveStore.delete failed for %s/%s: %s",
                form_uid,
                session_id,
                exc,
            )

        return web.Response(status=204)

    async def list_forms(self, request: web.Request) -> web.Response:
        """GET /api/v1/forms — List all registered forms with rich metadata.

        Merges in-memory FormRegistry entries with persisted FormStorage rows
        (when a storage backend is configured). Each entry includes form_uid,
        form_id, title, description, version, source ("memory" | "db"), and
        an ISO-8601 created_at (or None).

        Supports ``?slug=<form_id>`` (FEAT-389) to filter results down to
        forms whose slug matches — resolved via
        ``FormRegistry.get_by_slug()`` rather than scanning the full list.

        Args:
            request: Incoming HTTP request.

        Returns:
            JSON response ``{"forms": [<descriptor>, ...]}`` sorted by
            form_id (slug — stable, human-meaningful ordering; form_uid is
            random and would not produce a stable order).
        """
        tenant = self._get_tenant(request)

        slug = request.query.get("slug")
        if slug:
            form = await self.registry.get_by_slug(slug, tenant=tenant)
            if form is None:
                return JSONResponse({"forms": []})
            self._assert_form_tenant(form, tenant)
            ts = form.created_at
            return JSONResponse({"forms": [{
                "form_uid": form.form_uid,
                "form_id": form.form_id,
                "title": _loc_to_str(form.title),
                "description": _loc_to_str(form.description),
                "version": form.version,
                "source": "memory",
                "created_at": ts.isoformat() if ts is not None else None,
            }]})

        in_memory = await self.registry.list_forms(tenant=tenant)
        descriptors: dict[str, dict] = {}

        for form in in_memory:
            ts = form.created_at
            descriptors[form.form_uid] = {
                "form_uid": form.form_uid,
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
                fuid = row.get("form_uid")
                if not fuid:
                    continue
                # Descriptors are keyed by FormSchema.form_uid (uuid.UUID), so
                # the row's form_uid must be one too. Since the column is now
                # native UUID, asyncpg already hands back a uuid.UUID and this
                # branch is inert — kept as belt-and-braces for a deployment
                # that has not yet applied 004_form_uid_uuid_type.sql, where
                # the column is still VARCHAR(36) and rows come back as str.
                if isinstance(fuid, str):
                    try:
                        fuid = _uuid.UUID(fuid)
                    except ValueError:
                        continue
                existing = descriptors.get(fuid)
                if existing is not None:
                    # In both: registry wins for title/description/version,
                    # storage wins for created_at; mark source as "db".
                    existing["source"] = "db"
                    if row.get("created_at") is not None:
                        existing["created_at"] = row["created_at"]
                else:
                    descriptors[fuid] = {
                        "form_uid": fuid,
                        "form_id": row.get("form_id"),
                        "title": _loc_to_str(row.get("title")),
                        "description": _loc_to_str(row.get("description")),
                        "version": row.get("version", "1.0"),
                        "source": "db",
                        "created_at": row.get("created_at"),
                    }

        forms = sorted(descriptors.values(), key=lambda d: d["form_id"] or "")
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
        """GET /api/v1/forms/{form_uid} — Get full FormSchema as JSON."""
        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_uid, tenant=tenant)
        if form is None:
            return JSONResponse({"error": f"Form '{form_uid}' not found"}, status=404)
        self._assert_form_tenant(form, tenant)
        # FEAT-421 review fix: this route is mounted tenant="public" (the
        # SAME route serves public and private forms) — requires_tenant
        # skipped membership authorization at the decorator level because
        # it can't know the specific form's is_public flag before it's
        # resolved. Close that gap here: private forms still require
        # membership; a truly public form is exempt.
        enforce_membership_unless_public(request, form, tenant)
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
                    session_id, form_uid
                )
        return response

    async def get_schema(self, request: web.Request) -> web.Response:
        """GET /api/v1/forms/{form_uid}/schema — Get JSON Schema (structural)."""
        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_uid, tenant=tenant)
        if form is None:
            return JSONResponse({"error": f"Form '{form_uid}' not found"}, status=404)
        self._assert_form_tenant(form, tenant)
        # FEAT-421 review fix: see get_form's comment — this route is also
        # mounted tenant="public".
        enforce_membership_unless_public(request, form, tenant)
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
        """GET /api/v1/forms/{form_uid}/style — Get style schema."""
        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_uid, tenant=tenant)
        if form is None:
            return JSONResponse({"error": f"Form '{form_uid}' not found"}, status=404)
        self._assert_form_tenant(form, tenant)
        style = form.meta.get("style") if form.meta else None
        return JSONResponse(style or {})

    async def remote_event(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/{form_uid}/events/{event_name} — Remote event bridge.

        Called by the HTML5 renderer when a binding declares ``remote: true``.
        Validates a per-session per-form CSRF token, dispatches the lifecycle
        event, and returns the ``EventResolution`` as JSON.

        Args:
            request: Incoming POST request with ``form_uid`` and ``event_name``
                in the URL, ``X-CSRF-Token`` header, and a JSON body optionally
                containing ``payload`` and ``schema_dump``.

        Returns:
            200 — EventResolution JSON.
            400 — Unknown event name or invalid JSON body.
            403 — Missing or invalid CSRF token.
            404 — Form not found.
            status from FormEventAbort.status_code — when a handler aborts.
        """
        form_uid = extract_form_uid(request)
        event_name = request.match_info["event_name"]

        # 1. Validate event_name against the FormEventName Literal
        if event_name not in get_args(FormEventName):
            return JSONResponse(
                {"error": f"Unknown event '{event_name}'"}, status=400
            )

        # 2. Load form
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_uid, tenant=tenant)
        if form is None:
            return JSONResponse(
                {"error": f"Form '{form_uid}' not found"}, status=404
            )
        self._assert_form_tenant(form, tenant)

        # 3. CSRF validation
        session_id = self._extract_session_id(request)
        token = request.headers.get("X-CSRF-Token") or request.headers.get(
            "X-Form-CSRF-Token"
        )
        if (
            not session_id
            or not token
            or not validate_form_csrf_token(session_id, form_uid, token)
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
                form_uid,
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
        """POST /api/v1/forms/{form_uid}/validate — Validate form submission."""
        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_uid, tenant=tenant)
        if form is None:
            return JSONResponse({"error": f"Form '{form_uid}' not found"}, status=404)
        self._assert_form_tenant(form, tenant)
        # FEAT-421 review fix: see get_form's comment — this route is also
        # mounted tenant="public".
        enforce_membership_unless_public(request, form, tenant)
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

    async def create_blank_form(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/blank — Create an empty form without an LLM (FEAT-389).

        Requires ``title`` in the JSON body. ``form_id`` (slug) is optional —
        if omitted, one is derived from ``title`` via the same slugify
        helper used by ``CreateFormTool``. ``form_uid`` is always freshly
        auto-generated by ``FormSchema``'s default factory.

        Request body::

            {"title": "My Form", "form_id": "my-form"}   # form_id optional

        Returns:
            201 — ``{"form_uid": str, "form_id": str, "title": str, "url": str}``.
            400 — invalid JSON body or missing ``title``.
            409 — ``form_id`` (slug) already exists in this tenant.
        """
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        title = body.get("title")
        if not title:
            return JSONResponse({"error": "title is required"}, status=400)

        from ..tools.create_form import _slugify
        form_id = body.get("form_id") or _slugify(_loc_to_str(title))

        tenant = self._get_tenant(request)
        assert_body_tenant_matches(body, tenant)
        try:
            form = FormSchema(
                form_id=form_id,
                title=title,
                sections=[],
                tenant=tenant,
            )
        except ValidationError as exc:
            return JSONResponse({"errors": exc.errors()}, status=422)

        persist = self.registry.has_storage
        try:
            await self.registry.register(
                form, persist=persist, overwrite=False, tenant=tenant
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status=409)

        self.logger.info(
            "Created blank form form_uid=%s (slug=%s)", form.form_uid, form.form_id
        )
        prefix = request.app.get("_form_prefix", "")
        return JSONResponse(
            {
                "form_uid": form.form_uid,
                "form_id": form.form_id,
                "title": _loc_to_str(title),
                "url": f"{prefix}/{tenant}/forms/{form.form_uid}",
            },
            status=201,
        )

    async def create_form(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms — Create a form from a natural language prompt."""
        # FEAT-302: RBAC gate-keeping (shadow mode by default)
        await self._rbac_shadow_gate(request, "create_form")
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
        form_uid = form_data.get("form_uid")
        if not form_uid:
            return JSONResponse(
                {"error": "Form creation succeeded but form_uid missing"},
                status=500,
            )
        title = (result.result or {}).get("title", "")
        prefix = request.app.get("_form_prefix", "")
        return JSONResponse({
            "form_uid": form_uid,
            "form_id": form_data.get("form_id"),
            "title": title,
            "url": f"{prefix}/{tenant}/forms/{form_uid}",
        })

    async def edit_form(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/{form_uid}/edit — Edit a form using natural language.

        Loads the existing form from the registry, passes its JSON schema to the
        LLM along with the user's edit prompt, and returns the updated form.
        The LLM is instructed to strictly preserve the FormSchema JSON structure.
        """
        # FEAT-302: RBAC gate-keeping (shadow mode by default)
        await self._rbac_shadow_gate(request, "edit_form")
        if self._create_tool.client is None:
            return JSONResponse(
                {"error": "No LLM client configured for form editing"},
                status=503,
            )

        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)
        existing = await self.registry.get(form_uid, tenant=tenant)
        if existing is None:
            return JSONResponse(
                {"error": f"Form '{form_uid}' not found"}, status=404
            )
        self._assert_form_tenant(existing, tenant)

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
            # FEAT-389 / TASK-1978: CreateFormInput's refinement parameter
            # is now refine_form_uid (renamed from refine_form_id) and is
            # form_uid-keyed throughout CreateFormTool.
            refine_form_uid=form_uid,
            persist=True,
        )

        if not result.success:
            return JSONResponse(
                {"error": result.metadata.get("error", "Form editing failed")},
                status=500,
            )

        form_data = result.metadata.get("form", {})
        updated_form_uid = form_data.get("form_uid")
        if not updated_form_uid:
            return JSONResponse(
                {"error": "Form editing succeeded but form_uid missing"},
                status=500,
            )
        title = (result.result or {}).get("title", "")
        prefix = request.app.get("_form_prefix", "")
        return JSONResponse({
            "form_uid": updated_form_uid,
            "form_id": form_data.get("form_id"),
            "title": title,
            "url": f"{prefix}/{tenant}/forms/{updated_form_uid}",
        })

    async def clone_form(self, request: web.Request) -> web.Response:
        """POST /api/v1/{tenant}/forms/{form_uid}/clone — Clone a form under a new slug.

        Creates a deep copy of the source form identified by ``form_uid``,
        assigns ``new_form_id`` (slug) from the request body and a freshly
        generated ``form_uid``, optionally applies an RFC 7396 merge-patch,
        validates the result, and persists it.

        FEAT-421: the tenant is the URL-declared, decorator-validated value
        (:meth:`_get_tenant`) — both the source lookup and the clone
        registration happen within that tenant scope. A body ``tenant`` is
        only ever an optional cross-check (spec §2); it is never trusted as
        an override, closing what would otherwise be a cross-tenant read+
        write via an unvalidated body field.

        Request body (JSON):
            new_form_id (str): Required. Slug for the cloned form.
            patch (dict | None): Optional RFC 7396 merge-patch.
            tenant (str | None): Optional cross-check — must match the URL
                tenant if present.

        Returns:
            201 Created with the full cloned ``FormSchema`` JSON body.
            400 if ``new_form_id`` is missing or empty, or the body tenant
                conflicts with the URL tenant.
            404 if the source form is not found.
            409 if ``new_form_id`` already exists.
            422 if the patch produces an invalid schema.
        """
        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)

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
        assert_body_tenant_matches(body, tenant)

        try:
            clone = await self.registry.clone_form(
                form_uid,
                new_form_id,
                patch,
                tenant=tenant,
            )
        except KeyError:
            return JSONResponse(
                {"error": f"Form '{form_uid}' not found"}, status=404
            )
        except FormAlreadyExistsError as exc:
            return JSONResponse({"error": str(exc)}, status=409)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status=422)

        self.logger.info(
            "Cloned form form_uid=%s -> form_uid=%s (slug=%s)",
            form_uid, clone.form_uid, clone.form_id,
        )
        return JSONResponse(clone.model_dump(mode="json"), status=201)

    async def update_form(self, request: web.Request) -> web.Response:
        """PUT /api/v1/forms/{form_uid} — Fully replace a registered form.

        Accepts a complete ``FormSchema`` JSON body. The ``form_uid`` in the
        URL must match the ``form_uid`` in the body — the immutable identity
        cannot change via PUT. The ``form_id`` (slug) MAY differ from the
        existing form's slug — this is how a form is renamed (FEAT-389); the
        registry's slug index is updated accordingly on re-registration. Runs
        structural validation via ``FormValidator.check_schema()`` before
        persisting. Automatically bumps the form version.
        """
        # FEAT-302: RBAC gate-keeping (shadow mode by default)
        await self._rbac_shadow_gate(request, "update_form")
        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)
        existing = await self.registry.get(form_uid, tenant=tenant)
        if existing is None:
            return JSONResponse(
                {"error": f"Form '{form_uid}' not found"}, status=404
            )
        self._assert_form_tenant(existing, tenant)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        if not isinstance(body, dict) or str(body.get("form_uid")) != str(form_uid):
            return JSONResponse(
                {"error": "form_uid in URL and body must match"}, status=400
            )
        assert_body_tenant_matches(body, tenant)

        body["version"] = _bump_version(existing.version)
        # published_version is immutable from the API surface — only
        # FormVersionService.publish() may set it (review M1).
        body.pop("published_version", None)
        body["published_version"] = existing.published_version
        # FEAT-421 review fix (2nd pass, CRITICAL): assert_body_tenant_matches()
        # only rejects a CONFLICTING body tenant — it is a no-op when the
        # field is omitted or null, both valid per FormSchema.tenant's
        # `str | None = None` type. Without this stamp, an ordinary client
        # that doesn't round-trip the optional `tenant` field would
        # silently persist form.tenant=None while the form still lives
        # under the correct registry bucket — permanently 404ing it on
        # every subsequent tenant-scoped read via _assert_form_tenant. The
        # URL is authoritative (spec §2): always stamp it, unconditionally.
        body["tenant"] = tenant

        try:
            form = FormSchema.model_validate(body)
        except ValidationError as exc:
            return JSONResponse({"errors": exc.errors()}, status=422)

        schema_errors = self.validator.check_schema(form)
        if schema_errors:
            return JSONResponse({"errors": schema_errors}, status=422)

        persist = self.registry.has_storage
        try:
            await self.registry.register(
                form, persist=persist, overwrite=True, tenant=tenant
            )
        except FormAlreadyExistsError as exc:
            # PUT may rename form_id (slug) — register() rejects the rename
            # if the target slug is already owned by a DIFFERENT form_uid
            # in this tenant (code-review fix: this check is now enforced
            # unconditionally, not just when overwrite=False, so a rename
            # can no longer silently steal another form's slug).
            return JSONResponse({"error": str(exc)}, status=409)
        self.logger.info(
            "PUT form_uid=%s (slug=%s) → version %s", form_uid, form.form_id, form.version
        )
        return JSONResponse(form.model_dump(mode="json", exclude_none=True))

    async def patch_form(self, request: web.Request) -> web.Response:
        """PATCH /api/v1/forms/{form_uid} — Partially update a registered form.

        Applies RFC 7396 JSON merge-patch semantics to the existing form.
        Arrays (sections, fields) are replaced entirely — not merged
        element-by-element. Neither ``form_uid`` nor ``form_id`` (slug) can
        be changed via PATCH (unchanged policy from before FEAT-389 — use
        PUT for renames). Runs structural validation after merging.
        Automatically bumps version.
        """
        # FEAT-302: RBAC gate-keeping (shadow mode by default)
        await self._rbac_shadow_gate(request, "patch_form")
        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)
        existing = await self.registry.get(form_uid, tenant=tenant)
        if existing is None:
            return JSONResponse(
                {"error": f"Form '{form_uid}' not found"}, status=404
            )
        self._assert_form_tenant(existing, tenant)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        if not body:
            return JSONResponse(
                {"error": "PATCH body must not be empty"}, status=400
            )
        assert_body_tenant_matches(body, tenant)

        existing_dict = existing.model_dump()
        merged = _deep_merge(existing_dict, body)
        merged["version"] = _bump_version(existing.version)
        # Prevent form_uid AND form_id (slug) change via PATCH.
        merged["form_uid"] = form_uid
        merged["form_id"] = existing.form_id
        # published_version is immutable from the API surface — only
        # FormVersionService.publish() may set it (review M1).
        merged["published_version"] = existing.published_version
        # FEAT-421 review fix (2nd pass, CRITICAL — same fix as update_form):
        # assert_body_tenant_matches() only rejects a CONFLICTING body
        # tenant. A PATCH body of {"tenant": null} would additionally
        # survive RFC 7396 merge semantics as an explicit key deletion via
        # _deep_merge, corrupting form.tenant to None on an otherwise
        # correctly tenant-scoped form. The URL is authoritative (spec
        # §2): always stamp it, unconditionally, after the merge.
        merged["tenant"] = tenant

        try:
            form = FormSchema.model_validate(merged)
        except ValidationError as exc:
            return JSONResponse({"errors": exc.errors()}, status=422)

        schema_errors = self.validator.check_schema(form)
        if schema_errors:
            return JSONResponse({"errors": schema_errors}, status=422)

        persist = self.registry.has_storage
        await self.registry.register(form, persist=persist, overwrite=True, tenant=tenant)
        self.logger.info(
            "PATCH form_uid=%s (slug=%s) → version %s", form_uid, form.form_id, form.version
        )
        return JSONResponse(form.model_dump(mode="json", exclude_none=True))

    async def delete_form(self, request: web.Request) -> web.Response:
        """DELETE /api/v1/forms/{form_uid} — Remove a registered form.

        Unregisters the form from the in-memory registry and, when a
        ``FormStorage`` backend is configured, deletes the persisted row as
        well (scoped by the form's tenant so per-tenant Postgres schemas
        resolve correctly). Returns ``204 No Content`` on success, ``404``
        when no form with the given id exists.
        """
        # FEAT-302: RBAC gate-keeping (shadow mode by default)
        await self._rbac_shadow_gate(request, "delete_form")
        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)
        existing = await self.registry.get(form_uid, tenant=tenant)
        if existing is None:
            return JSONResponse(
                {"error": f"Form '{form_uid}' not found"}, status=404
            )
        self._assert_form_tenant(existing, tenant)

        # Spec invariant (FEAT-300 §8, Vision IQ parity): a form with ≥1
        # response can never be deleted — only deactivated.
        # NOTE: FormVersionService itself is rekeyed to form_uid by TASK-1990,
        # not this task — passing form_uid here is what the eventual, fixed
        # FormVersionService.can_delete() will expect.
        version_svc = self._get_version_service()
        if not await version_svc.can_delete(form_uid, tenant=tenant):
            return web.json_response(
                {
                    "error": (
                        f"Form '{form_uid}' has responses and cannot be deleted. "
                        "Deactivate it instead."
                    )
                },
                status=409,
            )

        await self.registry.unregister(form_uid, tenant=tenant)

        storage = self.registry.storage
        if storage is not None:
            try:
                await storage.delete(form_uid, tenant=existing.tenant)
            except Exception as exc:
                self.logger.warning(
                    "FormStorage.delete failed for %s: %s", form_uid, exc
                )

        self.logger.info("DELETE form_uid=%s", form_uid)
        return web.Response(status=204)

    async def submit_data(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/{form_uid}/data — Receive and process a form submission.

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

        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_uid, tenant=tenant)
        if form is None:
            return JSONResponse(
                {"error": f"Form '{form_uid}' not found"}, status=404
            )
        self._assert_form_tenant(form, tenant)
        # FEAT-421 review fix: see get_form's comment — this route is also
        # mounted tenant="public" (a public form's submission must remain
        # reachable unauthenticated; a private form's must not).
        enforce_membership_unless_public(request, form, tenant)

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
                        cached = await self._partial_store.get(str(form_uid), _merge_session_id)
                        if cached:
                            # Stored data is field_uid-keyed (TASK-2003) — map
                            # back to CURRENT field_ids before merging into
                            # the field_id-keyed submission payload.
                            cached = self._remap_partial_to_field_ids(form, cached)
                            # cached values fill gaps; submitted values win on overlap
                            data = {**cached.data, **data}
                            self.logger.debug(
                                "Merged %d cached partial fields into submit for %s/%s",
                                len(cached.data),
                                form_uid,
                                _merge_session_id,
                            )
                    except Exception as exc:
                        self.logger.warning(
                            "Failed to load partial for merge %s/%s: %s",
                            form_uid,
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

            # Build submission record. FormSubmission.form_uid is required
            # (TASK-1979) — form.form_uid is the loaded form's stable
            # identity; form.form_id is its (possibly renamed) slug.
            submission = FormSubmission(
                submission_id=str(uuid.uuid4()),
                form_uid=form.form_uid,
                form_id=form.form_id,
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
                    await self._partial_store.delete(str(form_uid), _merge_session_id)
                    self.logger.debug(
                        "Deleted cached partial for %s/%s after successful submit",
                        form_uid,
                        _merge_session_id,
                    )
                except Exception as exc:
                    self.logger.warning(
                        "Failed to delete partial after submit %s/%s: %s",
                        form_uid,
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
                "submit_data failed for form %r: %s", form_uid, exc
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
        # persist=True: an import that only ever reached the in-memory registry
        # is invisible to every table-backed reader (the caller's very next
        # request usually IS one), which surfaced as a 404 on a form the
        # importer had just reported loading. Safe only because import identity
        # is now deterministic — with the former uuid4 this path silently
        # created db-form-X-Y-2, -3, -4, one duplicate per import.
        result = await db_tool.execute(
            service=service, formid=formid, orgid=orgid, persist=True
        )

        if not result.success:
            error_msg = result.metadata.get("error", "Failed to load form from database")
            status = 404 if "not found" in error_msg.lower() else 500
            return JSONResponse({"error": error_msg}, status=status)

        form_data = result.metadata.get("form", {})
        form_uid = form_data.get("form_uid")
        form_id = form_data.get("form_id")
        if not form_uid:
            return JSONResponse(
                {"error": "Form load succeeded but form_uid missing"},
                status=500,
            )

        # FEAT-300: persist the per-field ImportDiffReport so
        # GET /forms/{form_uid}/import-report can serve it (review H2).
        # FEAT-389: keyed by (tenant, form_uid) — both the write site here
        # and the read site in get_import_report live in this same file.
        report_data = result.metadata.get("import_report")
        if report_data:
            from ..tools.services.networkninja import ImportDiffReport
            self._import_reports[(tenant, form_uid)] = (
                ImportDiffReport.model_validate(report_data)
            )

        title = (result.result or {}).get("title", "")
        prefix = request.app.get("_form_prefix", "")
        return JSONResponse({
            "form_uid": form_uid,
            "form_id": form_id,
            "title": title,
            "url": f"{prefix}/{tenant}/forms/{form_uid}",
        })

    # ------------------------------------------------------------------
    # FEAT-300 helpers — version service + question bank
    # ------------------------------------------------------------------

    def _get_version_service(self) -> "FormVersionService":
        """Return the shared FormVersionService, initialising it lazily.

        Wires the registry's storage backend (FEAT-433 Module 1) so
        published snapshots are persisted to the same backend the rest of
        the handler uses (mirrors ``_make_question_bank``'s
        ``storage=self.registry.storage`` shape). ``FormRegistry.storage``
        may legitimately be ``None`` (in-memory deployments and most unit
        tests) — that is passed straight through and the service falls
        back to its in-memory store, as before.

        Note: the service is cached on ``self._version_service`` and the
        storage is read at construction time — a ``set_storage()`` call
        made after the first version request will not be picked up by
        this cached instance.

        Returns:
            Configured ``FormVersionService`` instance.
        """
        if self._version_service is None:
            from ..services.form_version import FormVersionService
            self._version_service = FormVersionService(
                self.registry, storage=self.registry.storage
            )
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
        """POST /api/v1/forms/{form_uid}/publish — Publish current form as immutable snapshot.

        Bumps the form's semver minor tag and freezes the current state as a
        published snapshot. Returns ``409`` when the computed tag already
        exists (immutability guard). Returns ``404`` when the form is not found.

        Args:
            request: Incoming HTTP request (path param: ``form_uid``).

        Returns:
            ``{"form_uid": str, "version": str}`` on success (200),
            ``{"error": str}`` on 404 (not found) or 409 (frozen conflict).
        """
        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)
        svc = self._get_version_service()
        try:
            version = await svc.publish(form_uid, tenant=tenant)
        except KeyError as exc:
            return web.json_response({"error": str(exc)}, status=404)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except Exception as exc:
            self.logger.exception("publish_form failed for '%s': %s", form_uid, exc)
            return web.json_response({"error": str(exc)}, status=500)
        self.logger.info("Published form '%s' → version '%s'", form_uid, version)
        return web.json_response({"form_uid": str(form_uid), "version": version})

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
        """GET /api/v1/forms/{form_uid}/versions — List a form's version history.

        Each entry includes ``version``, ``published_at`` (ISO-8601),
        ``published_by`` (``null`` when not tracked), ``is_current``
        (``True`` for the form's active published version), and
        ``is_published`` (FEAT-433 D1/D3) — every stored version is listed,
        draft or published; ``is_published`` labels which is which.
        ``is_current`` and ``is_published`` are independent: the newest row
        is normally a current *draft*, and the newest published row is
        normally an *older* entry.

        Args:
            request: Incoming HTTP request (path param: ``form_uid``).

        Returns:
            ``{"form_uid": str, "versions": [...]}`` (200), ``404`` if not found.
        """
        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)
        form = await self.registry.get(form_uid, tenant=tenant)
        if form is None:
            return web.json_response({"error": f"Form '{form_uid}' not found"}, status=404)
        self._assert_form_tenant(form, tenant)

        svc = self._get_version_service()
        meta_list = await svc.list_versions(form_uid, tenant=tenant)
        current_version = form.published_version or form.version

        return web.json_response({
            "form_uid": str(form_uid),
            "versions": [
                {
                    "version": m.version,
                    "published_at": m.published_at.isoformat(),
                    "published_by": None,
                    "is_current": m.version == current_version,
                    "is_published": m.is_published,
                }
                for m in meta_list
            ],
        })

    async def get_version(self, request: web.Request) -> web.Response:
        """GET /api/v1/forms/{form_uid}/versions/{version} — Retrieve a frozen snapshot.

        Returns the immutable ``FormSchema`` snapshot for the requested semver
        tag. Returns ``404`` when the form or version is not found.

        Args:
            request: Incoming HTTP request (path params: ``form_uid``, ``version``).

        Returns:
            Full ``FormSchema`` JSON (200) or ``{"error": str}`` (404).
        """
        form_uid = extract_form_uid(request)
        version = request.match_info["version"]
        tenant = self._get_tenant(request)
        svc = self._get_version_service()
        snap = await svc.get_published(form_uid, version=version, tenant=tenant)
        if snap is None:
            return web.json_response(
                {"error": f"Version '{version}' of form '{form_uid}' not found"},
                status=404,
            )
        return web.json_response(snap.model_dump(mode="json"))

    async def get_import_report(self, request: web.Request) -> web.Response:
        """GET /api/v1/forms/{form_uid}/import-report — Latest ImportDiffReport.

        Returns the per-field mapping report generated when this form was last
        imported from an external source (e.g. Networkninja). Returns ``404``
        when no import history exists for this form.

        Args:
            request: Incoming HTTP request (path param: ``form_uid``).

        Returns:
            ``ImportDiffReport`` JSON (200) or ``{"error": str}`` (404).
        """
        form_uid = extract_form_uid(request)
        tenant = self._get_tenant(request)
        report = self._import_reports.get((tenant, form_uid))
        if report is None:
            return web.json_response(
                {"error": f"No import report found for form '{form_uid}'"},
                status=404,
            )
        return web.json_response(report.model_dump(mode="json"))

    # ------------------------------------------------------------------
    # FEAT-302 — RBAC shadow-mode gate-keeping helper
    # ------------------------------------------------------------------

    async def _rbac_shadow_gate(
        self,
        request: web.Request,
        codename: str,
    ) -> None:
        """Log RBAC gate-keeping check in shadow mode (never blocks).

        When ``self.rbac_enforcing`` is ``False`` (default), this method
        only logs a DEBUG message with the permission check result.
        This is consistent with ``Policy.enforcing=False`` (nav-auth shadow
        mode) — gate-keeping is visible in logs but never blocks deployments.

        When ``self.rbac_enforcing`` is ``True`` and the user lacks the
        permission, ``web.HTTPForbidden`` is raised.

        Args:
            request: Incoming aiohttp request.
            codename: Permission codename to check (e.g. "create_form").
        """
        if self._rbac_service is None:
            return

        user = getattr(request, "user", None)
        user_id = str(getattr(user, "id", "anonymous")) if user else "anonymous"
        tenant = self._get_tenant(request)
        # H-4: _get_programs() returns program SLUGS, not numeric IDs. There is
        # no reliable numeric program_id in the slug-only session, so the gate
        # resolves at tenant+user granularity (program_id=0). RBACService.resolve
        # filters policies by user+tenant, so program scoping is not required here.
        program_id = 0

        try:
            ctx = await self._rbac_service.resolve(
                user_id, program_id=program_id, tenant=tenant
            )
            allowed = ctx.has_permission(codename)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug(
                "_rbac_shadow_gate: resolution failed for %s/%s: %s",
                user_id,
                codename,
                exc,
            )
            return

        if allowed:
            self.logger.debug(
                "_rbac_shadow_gate: ALLOW user=%s codename=%s tenant=%s",
                user_id, codename, tenant,
            )
        else:
            if self.rbac_enforcing:
                self.logger.warning(
                    "_rbac_shadow_gate: DENY (enforcing) user=%s codename=%s tenant=%s",
                    user_id, codename, tenant,
                )
                raise web.HTTPForbidden(
                    reason=f"Permission denied: {codename}"
                )
            else:
                self.logger.debug(
                    "_rbac_shadow_gate: WOULD-DENY (shadow) user=%s codename=%s tenant=%s",
                    user_id, codename, tenant,
                )

    # ------------------------------------------------------------------
    # FEAT-302 — Org Graph endpoints
    # ------------------------------------------------------------------

    async def get_org_graph(self, request: web.Request) -> web.Response:
        """GET /api/v1/org/graph — Return the org graph for the session's org.

        Calls ``OrgGraphService.get_graph()`` using the org_id extracted from
        the navigator-auth session (``request.user.organizations[0].org_id``).

        Args:
            request: Incoming HTTP request with navigator-auth session.

        Returns:
            200: Serialized ``OrgGraph`` as JSON.
            400: Missing org_id in session.
            501: OrgGraphService not configured.
        """
        if self._org_graph_service is None:
            return JSONResponse(
                {"error": "OrgGraphService not configured"}, status=501
            )

        org_id = self._get_org_id(request)
        if org_id is None:
            return JSONResponse(
                {"error": "org_id not found in session"}, status=400
            )

        tenant = self._session_tenant(request)
        try:
            graph = await self._org_graph_service.get_graph(org_id, tenant=tenant)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status=404)
        except Exception as exc:
            self.logger.exception("get_org_graph failed: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status=500)

        return JSONResponse(graph.model_dump(mode="json"), status=200)

    async def create_project(self, request: web.Request) -> web.Response:
        """POST /api/v1/org/projects — Create a fieldsync project.

        Request body::

            {
                "accounting_code": "ACC-001",
                "name": "Q1 Campaign",
                "client_id": 42,
                "org_id": 7
            }

        Args:
            request: Incoming HTTP request.

        Returns:
            201: Created ``Project`` as JSON.
            400: Invalid/missing fields.
            409: Duplicate accounting_code for client.
            501: ProjectService not configured.
        """
        if self._project_service is None:
            return JSONResponse(
                {"error": "ProjectService not configured"}, status=501
            )

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        accounting_code = body.get("accounting_code")
        if not accounting_code:
            return JSONResponse(
                {"error": "accounting_code is required"}, status=400
            )

        client_id = body.get("client_id")
        if client_id is None:
            return JSONResponse({"error": "client_id is required"}, status=400)
        # H-2: reject non-numeric client_id with 400, not 500.
        try:
            client_id_int = int(client_id)
        except (TypeError, ValueError):
            return JSONResponse(
                {"error": "client_id must be an integer"}, status=400
            )

        # C-4 (write isolation): org_id comes from the authenticated session,
        # NEVER from the request body — a caller cannot create a project under
        # another tenant's org.
        org_id = self._get_org_id(request)
        if org_id is None:
            return JSONResponse(
                {"error": "org_id not found in session"}, status=400
            )

        tenant = self._session_tenant(request)
        try:
            project = await self._project_service.create_project(
                accounting_code=str(accounting_code),
                name=body.get("name"),
                client_id=client_id_int,
                org_id=org_id,
                tenant=tenant,
            )
        except Exception as exc:
            from ..services.project_service import DuplicateAccountingCodeError

            if isinstance(exc, DuplicateAccountingCodeError):
                return JSONResponse({"error": str(exc)}, status=409)
            self.logger.exception("create_project failed: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status=500)

        return JSONResponse(project.model_dump(mode="json"), status=201)

    async def map_project_workday(self, request: web.Request) -> web.Response:
        """POST /api/v1/org/cost-centers/{project_id}/workday-map

        Maps a fieldsync project to a Workday cost center code.

        Request body::

            {"workday_code": "WD-99001"}

        Args:
            request: Incoming HTTP request (path param: ``project_id``).

        Returns:
            200: ``WorkdayCostCenterMapping`` as JSON.
            400: Missing workday_code.
            404: Project not found.
            501: ProjectService not configured.
        """
        if self._project_service is None:
            return JSONResponse(
                {"error": "ProjectService not configured"}, status=501
            )

        project_id_str = request.match_info.get("project_id", "")
        try:
            project_id = int(project_id_str)
        except (ValueError, TypeError):
            return JSONResponse(
                {"error": f"Invalid project_id: {project_id_str!r}"}, status=400
            )

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        workday_code = body.get("workday_code")
        if not workday_code:
            return JSONResponse({"error": "workday_code is required"}, status=400)

        tenant = self._session_tenant(request)
        try:
            mapping = await self._project_service.map_to_workday(
                project_id, str(workday_code), tenant=tenant
            )
        except Exception as exc:
            from ..services.project_service import ProjectNotFoundError

            if isinstance(exc, ProjectNotFoundError):
                return JSONResponse({"error": str(exc)}, status=404)
            self.logger.exception("map_project_workday failed: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status=500)

        return JSONResponse(mapping.model_dump(mode="json"), status=200)

    async def assign_user_role(self, request: web.Request) -> web.Response:
        """POST /api/v1/org/users/{user_id}/assign — Assign a role to a user.

        Compiles the given scope + codename to an ABAC policy and persists it
        in ``fieldsync.auth_policies``. NEVER writes to ``auth.user_permissions``.

        Request body::

            {
                "codename": "edit_form",
                "scope": "own",
                "program_id": 7
            }

        Args:
            request: Incoming HTTP request (path param: ``user_id``).

        Returns:
            200: ``PermissionRecord`` as JSON.
            400: Missing/invalid fields.
            501: RBACService not configured.
        """
        if self._rbac_service is None:
            return JSONResponse(
                {"error": "RBACService not configured"}, status=501
            )

        user_id = request.match_info.get("user_id", "")
        if not user_id:
            return JSONResponse({"error": "user_id is required"}, status=400)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        codename = body.get("codename")
        scope_str = body.get("scope")
        program_id = body.get("program_id")

        if not codename:
            return JSONResponse({"error": "codename is required"}, status=400)
        if not scope_str:
            return JSONResponse({"error": "scope is required"}, status=400)
        if program_id is None:
            return JSONResponse({"error": "program_id is required"}, status=400)

        from ..services.rbac import RBACScope

        try:
            scope = RBACScope(scope_str)
        except ValueError:
            valid = [s.value for s in RBACScope]
            return JSONResponse(
                {"error": f"Invalid scope {scope_str!r}; valid: {valid}"},
                status=400,
            )

        tenant = self._session_tenant(request)

        # H-1: assigning roles is a privileged action — ALWAYS enforce (never
        # shadow-only). The caller must hold the "manage_roles" permission.
        caller = getattr(request, "user", None)
        caller_id = str(getattr(caller, "id", "anonymous")) if caller else "anonymous"
        try:
            caller_ctx = await self._rbac_service.resolve(
                caller_id, program_id=int(program_id), tenant=tenant
            )
            if not caller_ctx.has_permission("manage_roles"):
                return JSONResponse(
                    {"error": "Permission denied: manage_roles required"},
                    status=403,
                )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "assign_user_role: privilege check failed for %s: %s",
                caller_id, exc,
            )
            return JSONResponse(
                {"error": "Permission denied: manage_roles required"},
                status=403,
            )

        try:
            record = await self._rbac_service.assign_role(
                user_id,
                program_id=int(program_id),
                codename=str(codename),
                scope=scope,
                tenant=tenant,
            )
        except Exception as exc:
            self.logger.exception("assign_user_role failed: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status=500)

        return JSONResponse(record.model_dump(mode="json"), status=200)

    async def sync_workday_identities(self, request: web.Request) -> web.Response:
        """POST /api/v1/org/sync/workday — Trigger Workday identity sync (stub).

        Calls ``WorkdayIdentitySyncAdapter.sync_user()`` which is a stub in
        FEAT-302 (FEAT-026/027 not available). Always returns 202 Accepted.

        Request body::

            {"user_id": "user-abc", "action": "provision", "org_id": 7}

        Args:
            request: Incoming HTTP request.

        Returns:
            202: Stub acceptance dict as JSON.
            400: Missing/invalid fields.
            501: WorkdayIdentitySyncAdapter not configured.
        """
        if self._workday_adapter is None:
            return JSONResponse(
                {"error": "WorkdayIdentitySyncAdapter not configured"}, status=501
            )

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        user_id = body.get("user_id")
        action = body.get("action")
        org_id = body.get("org_id")

        if not user_id:
            return JSONResponse({"error": "user_id is required"}, status=400)
        if action not in ("provision", "deprovision"):
            return JSONResponse(
                {"error": "action must be 'provision' or 'deprovision'"}, status=400
            )
        if org_id is None:
            return JSONResponse({"error": "org_id is required"}, status=400)

        try:
            result = await self._workday_adapter.sync_user(
                str(user_id), action=action, org_id=int(org_id)
            )
        except Exception as exc:
            self.logger.exception("sync_workday_identities failed: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status=500)

        return JSONResponse(result, status=202)

    # ------------------------------------------------------------------
    # FEAT-330 — Store sub-structure (Site / Location) endpoints
    # ------------------------------------------------------------------

    async def list_sites(self, request: web.Request) -> web.Response:
        """GET /api/v1/org/stores/{store_id}/sites — List sites under a store.

        Args:
            request: Incoming HTTP request (path param: ``store_id``).

        Returns:
            200: List of ``Site`` as JSON.
            400: Missing org_id in session.
            501: VenueService not configured.
        """
        if self._venue_service is None:
            return JSONResponse({"error": "VenueService not configured"}, status=501)

        store_id = request.match_info.get("store_id", "")
        org_id = self._get_org_id(request)
        if org_id is None:
            return JSONResponse({"error": "org_id not found in session"}, status=400)

        tenant = self._session_tenant(request)
        try:
            sites = await self._venue_service.list_sites(
                store_id=store_id, org_id=org_id, tenant=tenant
            )
        except Exception as exc:
            self.logger.exception("list_sites failed: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status=500)

        return JSONResponse([s.model_dump(mode="json") for s in sites], status=200)

    async def create_site(self, request: web.Request) -> web.Response:
        """POST /api/v1/org/stores/{store_id}/sites — Create a site.

        Request body::

            {"client_id": 42, "name": "Vending Zone"}

        ``org_id`` is taken from the authenticated session, never the body.

        Returns:
            201: Created ``Site`` as JSON.
            400: Invalid/missing fields.
            409: Duplicate site name in the store.
            501: VenueService not configured.
        """
        if self._venue_service is None:
            return JSONResponse({"error": "VenueService not configured"}, status=501)

        store_id = request.match_info.get("store_id", "")
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        name = body.get("name")
        if not name:
            return JSONResponse({"error": "name is required"}, status=400)

        client_id = body.get("client_id")
        if client_id is None:
            return JSONResponse({"error": "client_id is required"}, status=400)
        try:
            client_id_int = int(client_id)
        except (TypeError, ValueError):
            return JSONResponse({"error": "client_id must be an integer"}, status=400)

        org_id = self._get_org_id(request)
        if org_id is None:
            return JSONResponse({"error": "org_id not found in session"}, status=400)

        tenant = self._session_tenant(request)
        try:
            site = await self._venue_service.create_site(
                store_id=store_id,
                client_id=client_id_int,
                org_id=org_id,
                name=str(name),
                tenant=tenant,
            )
        except Exception as exc:
            from ..services.venue_service import DuplicateVenueError

            if isinstance(exc, DuplicateVenueError):
                return JSONResponse({"error": str(exc)}, status=409)
            self.logger.exception("create_site failed: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status=500)

        return JSONResponse(site.model_dump(mode="json"), status=201)

    async def list_locations(self, request: web.Request) -> web.Response:
        """GET /api/v1/org/sites/{site_id}/locations — List locations in a site.

        Returns:
            200: List of ``Location`` as JSON.
            400: Invalid site_id or missing org_id.
            501: VenueService not configured.
        """
        if self._venue_service is None:
            return JSONResponse({"error": "VenueService not configured"}, status=501)

        site_id_str = request.match_info.get("site_id", "")
        try:
            site_id = int(site_id_str)
        except (ValueError, TypeError):
            return JSONResponse(
                {"error": f"Invalid site_id: {site_id_str!r}"}, status=400
            )

        org_id = self._get_org_id(request)
        if org_id is None:
            return JSONResponse({"error": "org_id not found in session"}, status=400)

        tenant = self._session_tenant(request)
        try:
            locations = await self._venue_service.list_locations(
                site_id=site_id, org_id=org_id, tenant=tenant
            )
        except Exception as exc:
            self.logger.exception("list_locations failed: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status=500)

        return JSONResponse(
            [loc.model_dump(mode="json") for loc in locations], status=200
        )

    async def create_location(self, request: web.Request) -> web.Response:
        """POST /api/v1/org/sites/{site_id}/locations — Create a location.

        Request body::

            {
                "client_id": 42,
                "name": "Kiosk A-12",
                "location_type": "kiosk",
                "latitude": 34.0522,
                "longitude": -118.2437,
                "geofence_radius_m": 50
            }

        ``org_id`` is taken from the session, never the body.

        Returns:
            201: Created ``Location`` as JSON.
            400: Invalid/missing fields.
            409: Duplicate location name in the site.
            501: VenueService not configured.
        """
        if self._venue_service is None:
            return JSONResponse({"error": "VenueService not configured"}, status=501)

        site_id_str = request.match_info.get("site_id", "")
        try:
            site_id = int(site_id_str)
        except (ValueError, TypeError):
            return JSONResponse(
                {"error": f"Invalid site_id: {site_id_str!r}"}, status=400
            )

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)

        name = body.get("name")
        if not name:
            return JSONResponse({"error": "name is required"}, status=400)

        client_id = body.get("client_id")
        if client_id is None:
            return JSONResponse({"error": "client_id is required"}, status=400)
        try:
            client_id_int = int(client_id)
        except (TypeError, ValueError):
            return JSONResponse({"error": "client_id must be an integer"}, status=400)

        org_id = self._get_org_id(request)
        if org_id is None:
            return JSONResponse({"error": "org_id not found in session"}, status=400)

        tenant = self._session_tenant(request)
        try:
            location = await self._venue_service.create_location(
                site_id=site_id,
                client_id=client_id_int,
                org_id=org_id,
                name=str(name),
                location_type=str(body.get("location_type", "kiosk")),
                latitude=body.get("latitude"),
                longitude=body.get("longitude"),
                geofence_radius_m=body.get("geofence_radius_m"),
                tenant=tenant,
            )
        except Exception as exc:
            from ..services.venue_service import DuplicateVenueError

            if isinstance(exc, DuplicateVenueError):
                return JSONResponse({"error": str(exc)}, status=409)
            self.logger.exception("create_location failed: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status=500)

        return JSONResponse(location.model_dump(mode="json"), status=201)

    async def get_location(self, request: web.Request) -> web.Response:
        """GET /api/v1/org/locations/{location_id} — Fetch one location.

        Returns:
            200: ``Location`` as JSON (includes geofence params).
            400: Invalid location_id or missing org_id.
            404: Location not found in the session's org.
            501: VenueService not configured.
        """
        if self._venue_service is None:
            return JSONResponse({"error": "VenueService not configured"}, status=501)

        location_id_str = request.match_info.get("location_id", "")
        try:
            location_id = int(location_id_str)
        except (ValueError, TypeError):
            return JSONResponse(
                {"error": f"Invalid location_id: {location_id_str!r}"}, status=400
            )

        org_id = self._get_org_id(request)
        if org_id is None:
            return JSONResponse({"error": "org_id not found in session"}, status=400)

        tenant = self._session_tenant(request)
        try:
            location = await self._venue_service.get_location(
                location_id, org_id=org_id, tenant=tenant
            )
        except Exception as exc:
            from ..services.venue_service import LocationNotFoundError

            if isinstance(exc, LocationNotFoundError):
                return JSONResponse({"error": str(exc)}, status=404)
            self.logger.exception("get_location failed: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status=500)

        return JSONResponse(location.model_dump(mode="json"), status=200)

