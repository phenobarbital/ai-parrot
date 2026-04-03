"""JSON REST API handlers for parrot-formdesigner.

Serves the form builder REST API: create, list, get schema, get HTML, validate, load from DB.
"""

from __future__ import annotations

import logging

from aiohttp import web

from ..core.schema import RenderedForm
from ..renderers.html5 import HTML5Renderer
from ..renderers.jsonschema import JsonSchemaRenderer
from ..services.registry import FormRegistry
from ..services.validators import FormValidator


class FormAPIHandler:
    """Serves JSON REST API endpoints for form management.

    Args:
        registry: FormRegistry instance for storing and retrieving forms.
        client: Optional LLM client for natural language form creation.
    """

    def __init__(
        self,
        registry: FormRegistry,
        client=None,
    ) -> None:
        self.registry = registry
        self.client = client
        self.html_renderer = HTML5Renderer()
        self.schema_renderer = JsonSchemaRenderer()
        self.validator = FormValidator()
        self.logger = logging.getLogger(__name__)

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
        except Exception:
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
        if self.client is None:
            return web.json_response(
                {"error": "No LLM client configured for form creation"},
                status=503,
            )
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        prompt = body.get("prompt")
        if not prompt:
            return web.json_response({"error": "prompt is required"}, status=400)

        from ..tools.create_form import CreateFormTool
        create_tool = CreateFormTool(client=self.client, registry=self.registry)
        result = await create_tool.execute(prompt=prompt, persist=True)

        if not result.success:
            return web.json_response(
                {"error": result.metadata.get("error", "Form creation failed")},
                status=500,
            )

        form_id = result.metadata["form"]["form_id"]
        return web.json_response({
            "form_id": form_id,
            "title": result.result["title"],
            "url": f"/forms/{form_id}",
        })

    async def load_from_db(self, request: web.Request) -> web.Response:
        """POST /api/forms/from-db — Load a form from database definition.

        Args:
            request: Incoming HTTP request with JSON body ``{"formid": int, "orgid": int}``.

        Returns:
            JSON response with ``form_id``, ``title``, and ``url`` on success.
        """
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        formid = body.get("formid")
        orgid = body.get("orgid")

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

        from ..tools.database_form import DatabaseFormTool
        db_tool = DatabaseFormTool(registry=self.registry)
        result = await db_tool.execute(formid=formid, orgid=orgid, persist=False)

        if not result.success:
            error_msg = result.metadata.get("error", "Failed to load form from database")
            status = 404 if "not found" in error_msg.lower() else 500
            return web.json_response({"error": error_msg}, status=status)

        form_id = result.metadata["form"]["form_id"]
        return web.json_response({
            "form_id": form_id,
            "title": result.result["title"],
            "url": f"/forms/{form_id}",
        })
