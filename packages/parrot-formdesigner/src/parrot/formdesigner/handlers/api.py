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
import os
from typing import TYPE_CHECKING

from aiohttp import web

from ..core.schema import RenderedForm
from ..renderers.html5 import HTML5Renderer
from ..renderers.jsonschema import JsonSchemaRenderer
from ..services.registry import FormRegistry
from ..services.validators import FormValidator

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient


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
    ) -> None:
        self.registry = registry
        self._client = client
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

    def _get_org_id(self, request: web.Request) -> str | None:
        """Extract org_id from the authenticated user's first organization.

        Reads ``request.user.organizations[0].org_id`` as set by the
        ``@user_session()`` decorator from navigator-auth.

        Args:
            request: Incoming HTTP request with ``user`` attribute attached
                by the navigator-auth ``user_session`` decorator.

        Returns:
            The ``org_id`` string from the first organization, or ``None``
            if the user has no organizations or the user is not set.
        """
        user = getattr(request, "user", None)
        if user and user.organizations:
            return user.organizations[0].org_id
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
        session = getattr(request, "session", None) or request.get("session")
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
        if self._get_llm_client() is None:
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
        return web.json_response({
            "form_id": form_id,
            "title": title,
            "url": f"/forms/{form_id}",
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
            return web.json_response(
                {"error": "Both 'formid' and 'orgid' are required"},
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
        return web.json_response({
            "form_id": form_id,
            "title": title,
            "url": f"/forms/{form_id}",
        })
