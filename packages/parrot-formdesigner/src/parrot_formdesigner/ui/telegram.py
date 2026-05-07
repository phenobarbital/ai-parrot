"""Telegram WebApp handlers for parrot-formdesigner.

Serves forms as Telegram WebApps with the JS SDK embedded, and provides
a REST fallback endpoint for payloads exceeding the 4 KB sendData() limit.
"""

from __future__ import annotations

import json
import logging
from html import escape
from pathlib import Path

import jinja2
from aiohttp import web

from ..core.style import StyleSchema
from ..renderers.html5 import HTML5Renderer
from ..services.registry import FormRegistry
from ..services.validators import FormValidator

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "renderers" / "templates"


class TelegramWebAppHandler:
    """Serves forms as Telegram WebApps and handles REST fallback submissions.

    Args:
        registry: FormRegistry for looking up forms by ID.
        renderer: Optional HTML5Renderer. Created if not provided.
        validator: Optional FormValidator. Created if not provided.
    """

    def __init__(
        self,
        registry: FormRegistry,
        renderer: HTML5Renderer | None = None,
        validator: FormValidator | None = None,
    ) -> None:
        self.registry = registry
        self.renderer = renderer or HTML5Renderer()
        self.validator = validator or FormValidator()
        self.logger = logging.getLogger(__name__)
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=True,
        )

    async def serve_webapp(self, request: web.Request) -> web.Response:
        """GET /forms/{form_id}/telegram — Serve the form as a Telegram WebApp.

        Args:
            request: Incoming HTTP request.

        Returns:
            HTML response with the Telegram WebApp page, or 404.
        """
        form_id = request.match_info["form_id"]
        form = await self.registry.get(form_id)
        if form is None:
            return web.Response(text="Form not found", status=404)

        # Render the form HTML
        style = StyleSchema()
        rendered = await self.renderer.render(form)
        form_html = rendered.content

        # Remove the default method="post" from the form tag to prevent
        # standard submission — the JS SDK handles it
        form_html = form_html.replace('method="post"', '', 1)

        title = form.title if isinstance(form.title, str) else form.title.get("en", "Form")

        # Build fallback URL
        prefix = request.app.get("_form_prefix", "")
        fallback_url = f"{prefix}/api/v1/forms/{form_id}/telegram-submit"

        template = self._env.get_template("telegram_webapp.html.j2")
        html = template.render(
            form_id=form_id,
            form_title=title,
            form_html=form_html,
            fallback_url=fallback_url,
            locale="en",
        )

        return web.Response(text=html, content_type="text/html")

    async def rest_fallback(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/{form_id}/telegram-submit — REST fallback.

        Validates a form submission for payloads too large for sendData().

        Args:
            request: Incoming HTTP request with JSON body.

        Returns:
            JSON response with is_valid and errors.
        """
        form_id = request.match_info["form_id"]
        form = await self.registry.get(form_id)
        if form is None:
            return web.json_response(
                {"error": f"Form '{form_id}' not found"}, status=404
            )

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        # Remove internal _form_id field before validation
        data.pop("_form_id", None)

        result = await self.validator.validate(form, data)
        status = 200 if result.is_valid else 422
        return web.json_response(
            {"is_valid": result.is_valid, "errors": result.errors},
            status=status,
        )
