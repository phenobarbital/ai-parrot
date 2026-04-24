"""JSON REST API handlers for parrot-formdesigner.

Serves the form builder REST API: create, list, get schema, get HTML, validate, load from DB.

All endpoints are protected by navigator-auth session authentication when the
``navigator-auth`` package is installed. Authentication is applied at route
registration time in ``routes.py``. When running standalone (without navigator-auth)
the API is open — useful for local development.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from aiohttp import web
from pydantic import ValidationError

from ..core.schema import FormSchema, RenderedForm
from ..renderers.html5 import HTML5Renderer
from ..renderers.jsonschema import JsonSchemaRenderer
from ..services.registry import FormRegistry
from ..services.validators import FormValidator

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient
    from ..services.forwarder import SubmissionForwarder
    from ..services.submissions import FormSubmissionStorage


# ---------------------------------------------------------------------------
# Module-level utility functions
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, patch: dict) -> dict:
    """RFC 7396 JSON merge-patch: recursively merge patch onto base.

    Rules:
    - ``dict`` values are merged recursively.
    - ``None`` (null) values remove the corresponding key from the base.
    - All other values (including lists) replace the base value entirely.

    Args:
        base: The original dict to merge into.
        patch: The partial update to apply.

    Returns:
        A new dict with the patch applied to the base.
    """
    result = base.copy()
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _bump_version(version: str) -> str:
    """Increment the minor component of a version string.

    Examples:
        ``"1.0"`` → ``"1.1"``
        ``"1.5"`` → ``"1.6"``
        ``"1"`` → ``"1.1"``
        ``"1.2.3"`` → ``"1.2.4"``

    Args:
        version: Current version string.

    Returns:
        Version string with the last numeric component incremented by 1.
    """
    parts = version.split(".")
    if len(parts) >= 2:
        parts[-1] = str(int(parts[-1]) + 1)
    else:
        parts.append("1")
    return ".".join(parts)


class FormAPIHandler:
    """Serves JSON REST API endpoints for form management.

    All 8 API routes are protected by navigator-auth session authentication
    when the ``navigator-auth`` package is installed. The decorators are applied
    at route-registration time in ``routes.py`` to avoid a hard import dependency.

    User identity context (``org_id``, ``programs``) is extracted from the
    authenticated session via the :meth:`_get_org_id` and :meth:`_get_programs`
    helper methods.

    Args:
        registry: FormRegistry instance for storing and retrieving forms.
        client: Optional LLM client for natural language form creation.
    """

    def __init__(
        self,
        registry: FormRegistry,
        client: "AbstractClient | None" = None,
        submission_storage: "FormSubmissionStorage | None" = None,
        forwarder: "SubmissionForwarder | None" = None,
    ) -> None:
        self.registry = registry
        self._client = client
        self._submission_storage = submission_storage
        self._forwarder = forwarder
        self.html_renderer = HTML5Renderer()
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

    async def list_forms(self, request: web.Request) -> web.Response:
        """GET /api/forms — List all registered forms.

        Args:
            request: Incoming HTTP request.

        Returns:
            JSON response with a ``forms`` list of form ID strings.
        """
        form_ids = await self.registry.list_form_ids()
        return web.json_response({"forms": form_ids})

    async def get_form(self, request: web.Request) -> web.Response:
        """GET /api/forms/{form_id} — Get full FormSchema as JSON.

        Args:
            request: Incoming HTTP request.

        Returns:
            JSON response with the full FormSchema dict, or 404.
        """
        form_id = request.match_info["form_id"]
        form = await self.registry.get(form_id)
        if form is None:
            return web.json_response({"error": f"Form '{form_id}' not found"}, status=404)
        return web.json_response(form.model_dump())

    async def get_schema(self, request: web.Request) -> web.Response:
        """GET /api/forms/{form_id}/schema — Get JSON Schema (structural).

        Args:
            request: Incoming HTTP request.

        Returns:
            JSON Schema dict for the form, or 404.
        """
        form_id = request.match_info["form_id"]
        form = await self.registry.get(form_id)
        if form is None:
            return web.json_response({"error": f"Form '{form_id}' not found"}, status=404)
        rendered: RenderedForm = await self.schema_renderer.render(form)
        return web.json_response(rendered.content)

    async def get_style(self, request: web.Request) -> web.Response:
        """GET /api/forms/{form_id}/style — Get style schema.

        Args:
            request: Incoming HTTP request.

        Returns:
            JSON response with style schema dict, or 404.
        """
        form_id = request.match_info["form_id"]
        form = await self.registry.get(form_id)
        if form is None:
            return web.json_response({"error": f"Form '{form_id}' not found"}, status=404)
        style = form.meta.get("style") if form.meta else None
        return web.json_response(style or {})

    async def get_html(self, request: web.Request) -> web.Response:
        """GET /api/forms/{form_id}/html — Render HTML5 form.

        Args:
            request: Incoming HTTP request.

        Returns:
            HTML string response with rendered form, or 404.
        """
        form_id = request.match_info["form_id"]
        form = await self.registry.get(form_id)
        if form is None:
            return web.json_response({"error": f"Form '{form_id}' not found"}, status=404)
        rendered = await self.html_renderer.render(form)
        return web.Response(text=rendered.content, content_type="text/html")

    async def validate(self, request: web.Request) -> web.Response:
        """POST /api/forms/{form_id}/validate — Validate form submission.

        Args:
            request: Incoming HTTP request with JSON submission data.

        Returns:
            JSON response with ``is_valid`` flag and ``errors`` dict.
        """
        form_id = request.match_info["form_id"]
        form = await self.registry.get(form_id)
        if form is None:
            return web.json_response({"error": f"Form '{form_id}' not found"}, status=404)
        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        result = await self.validator.validate(form, data)
        status = 200 if result.is_valid else 422
        return web.json_response(
            {"is_valid": result.is_valid, "errors": result.errors},
            status=status,
        )

    async def create_form(self, request: web.Request) -> web.Response:
        """POST /api/forms — Create a form from a natural language prompt.

        Args:
            request: Incoming HTTP request with JSON body ``{"prompt": "..."}``.

        Returns:
            JSON response with ``form_id``, ``title``, and ``url`` on success.
        """
        # _create_tool was initialised with the client available at construction
        # time. Check its client directly rather than calling _get_llm_client()
        # again, so the guard accurately reflects the tool's actual state.
        if self._create_tool.client is None:
            return web.json_response(
                {"error": "No LLM client configured for form creation"},
                status=503,
            )
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        prompt = body.get("prompt")
        if not prompt:
            return web.json_response({"error": "prompt is required"}, status=400)

        result = await self._create_tool.execute(prompt=prompt, persist=True)

        if not result.success:
            return web.json_response(
                {"error": result.metadata.get("error", "Form creation failed")},
                status=500,
            )

        form_data = result.metadata.get("form", {})
        form_id = form_data.get("form_id")
        if not form_id:
            return web.json_response(
                {"error": "Form creation succeeded but form_id missing"},
                status=500,
            )
        title = (result.result or {}).get("title", "")
        prefix = request.app.get("_form_prefix", "")
        return web.json_response({
            "form_id": form_id,
            "title": title,
            "url": f"{prefix}/forms/{form_id}",
        })

    async def update_form(self, request: web.Request) -> web.Response:
        """PUT /api/v1/forms/{form_id} — Fully replace a registered form.

        Accepts a complete ``FormSchema`` JSON body. The ``form_id`` in the URL
        must match the ``form_id`` in the body. Runs structural validation via
        ``FormValidator.check_schema()`` before persisting. Automatically bumps
        the form version.

        Args:
            request: Incoming HTTP request with a complete ``FormSchema`` body.

        Returns:
            JSON response with the updated ``FormSchema``, or an error status.
        """
        form_id = request.match_info["form_id"]
        existing = await self.registry.get(form_id)
        if existing is None:
            return web.json_response(
                {"error": f"Form '{form_id}' not found"}, status=404
            )

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        if not isinstance(body, dict) or body.get("form_id") != form_id:
            return web.json_response(
                {"error": "form_id in URL and body must match"}, status=400
            )

        body["version"] = _bump_version(existing.version)

        try:
            form = FormSchema.model_validate(body)
        except ValidationError as exc:
            return web.json_response({"errors": exc.errors()}, status=422)

        schema_errors = self.validator.check_schema(form)
        if schema_errors:
            return web.json_response({"errors": schema_errors}, status=422)

        persist = self.registry._storage is not None
        await self.registry.register(form, persist=persist, overwrite=True)
        self.logger.info("PUT form '%s' → version %s", form_id, form.version)
        return web.json_response(form.model_dump())

    async def patch_form(self, request: web.Request) -> web.Response:
        """PATCH /api/v1/forms/{form_id} — Partially update a registered form.

        Applies RFC 7396 JSON merge-patch semantics to the existing form.
        Arrays (sections, fields) are replaced entirely — not merged
        element-by-element. ``form_id`` cannot be changed via PATCH.
        Runs structural validation after merging. Automatically bumps version.

        Args:
            request: Incoming HTTP request with a partial ``FormSchema`` body.

        Returns:
            JSON response with the updated ``FormSchema``, or an error status.
        """
        form_id = request.match_info["form_id"]
        existing = await self.registry.get(form_id)
        if existing is None:
            return web.json_response(
                {"error": f"Form '{form_id}' not found"}, status=404
            )

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        if not body:
            return web.json_response(
                {"error": "PATCH body must not be empty"}, status=400
            )

        existing_dict = existing.model_dump()
        merged = _deep_merge(existing_dict, body)
        merged["version"] = _bump_version(existing.version)
        # Prevent form_id change via PATCH
        merged["form_id"] = form_id

        try:
            form = FormSchema.model_validate(merged)
        except ValidationError as exc:
            return web.json_response({"errors": exc.errors()}, status=422)

        schema_errors = self.validator.check_schema(form)
        if schema_errors:
            return web.json_response({"errors": schema_errors}, status=422)

        persist = self.registry._storage is not None
        await self.registry.register(form, persist=persist, overwrite=True)
        self.logger.info("PATCH form '%s' → version %s", form_id, form.version)
        return web.json_response(form.model_dump())

    async def submit_data(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/{form_id}/data — Receive and process a form submission.

        Flow:
        1. Load the form from registry (404 if not found).
        2. Parse JSON body (400 if invalid).
        3. Validate submission data (422 if invalid).
        4. Store locally if ``submission_storage`` is configured.
        5. Forward to endpoint if form has an ``endpoint`` submit action and
           ``forwarder`` is configured.
        6. Return composite result — always 200, even when forwarding fails.

        Args:
            request: Incoming HTTP request with submission data.

        Returns:
            JSON response with ``submission_id``, ``is_valid``, ``forwarded``,
            ``forward_status``, and ``forward_error``.
        """
        import uuid
        from datetime import datetime, timezone

        from ..services.submissions import FormSubmission

        form_id = request.match_info["form_id"]
        form = await self.registry.get(form_id)
        if form is None:
            return web.json_response(
                {"error": f"Form '{form_id}' not found"}, status=404
            )

        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        # Validate submission data against form schema
        result = await self.validator.validate(form, data)
        if not result.is_valid:
            return web.json_response(
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

        return web.json_response({
            "submission_id": submission.submission_id,
            "is_valid": True,
            "forwarded": forwarded,
            "forward_status": forward_status,
            "forward_error": forward_error,
        })

    async def load_from_db(self, request: web.Request) -> web.Response:
        """POST /api/forms/from-db — Load a form from database definition.

        The ``orgid`` in the request body is optional. When omitted, the
        ``org_id`` is extracted from the authenticated user's session via
        :meth:`_get_org_id`. If neither the body nor the session provides an
        ``org_id``, the request is rejected with a 400 error.

        Args:
            request: Incoming HTTP request with JSON body ``{"formid": int}``
                or ``{"formid": int, "orgid": int}``.

        Returns:
            JSON response with ``form_id``, ``title``, and ``url`` on success.
        """
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        formid = body.get("formid")

        # orgid: body takes precedence over session
        orgid = body.get("orgid")
        if orgid is None:
            orgid = self._get_org_id(request)

        if formid is None or orgid is None:
            missing = [name for name, val in [("formid", formid), ("orgid", orgid)] if val is None]
            return web.json_response(
                {"error": f"Missing required field(s): {', '.join(missing)}"},
                status=400,
            )

        try:
            formid = int(formid)
            orgid = int(orgid)
        except (TypeError, ValueError):
            return web.json_response(
                {"error": "'formid' and 'orgid' must be integers"},
                status=422,
            )

        if formid < 1 or orgid < 1:
            return web.json_response(
                {"error": "'formid' and 'orgid' must be positive integers"},
                status=422,
            )

        result = await self._db_tool.execute(formid=formid, orgid=orgid, persist=False)

        if not result.success:
            error_msg = result.metadata.get("error", "Failed to load form from database")
            status = 404 if "not found" in error_msg.lower() else 500
            return web.json_response({"error": error_msg}, status=status)

        form_data = result.metadata.get("form", {})
        form_id = form_data.get("form_id")
        if not form_id:
            return web.json_response(
                {"error": "Form load succeeded but form_id missing"},
                status=500,
            )
        title = (result.result or {}).get("title", "")
        prefix = request.app.get("_form_prefix", "")
        return web.json_response({
            "form_id": form_id,
            "title": title,
            "url": f"{prefix}/forms/{form_id}",
        })
