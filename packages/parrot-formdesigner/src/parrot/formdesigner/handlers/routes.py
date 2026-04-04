"""Route registration helper for parrot-formdesigner.

One-liner integration: setup_form_routes(app, registry=registry)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web

from ..services.registry import FormRegistry
from .api import FormAPIHandler
from .forms import FormPageHandler
from .telegram import TelegramWebAppHandler

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient


def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client: "AbstractClient | None" = None,
    api_key: str | None = None,
    prefix: str = "",
) -> None:
    """Register all form routes on the aiohttp application.

    Args:
        app: The aiohttp Application to register routes on.
        registry: Optional FormRegistry. A new one is created if not provided.
        client: Optional LLM client for natural language form creation.
        api_key: Optional shared-secret API key for endpoint authentication.
            Falls back to the ``PARROT_FORM_API_KEY`` environment variable.
            When neither is set the API runs in open/dev mode.
        prefix: Optional URL prefix for all routes (e.g. "/forms-app").
    """
    if registry is None:
        registry = FormRegistry()

    api = FormAPIHandler(registry=registry, client=client, api_key=api_key)
    page = FormPageHandler(registry=registry)
    telegram = TelegramWebAppHandler(registry=registry)

    p = prefix.rstrip("/")
    app["_form_prefix"] = p

    # HTML page routes
    # NOTE: Telegram route must be registered BEFORE the generic /forms/{form_id}
    # so aiohttp matches /forms/{id}/telegram before the catch-all.
    app.router.add_get(f"{p}/", page.index)
    app.router.add_get(f"{p}/gallery", page.gallery)
    app.router.add_get(f"{p}/forms/{{form_id}}/schema", page.view_schema)
    app.router.add_get(f"{p}/forms/{{form_id}}/telegram", telegram.serve_webapp)
    app.router.add_get(f"{p}/forms/{{form_id}}", page.render_form)
    app.router.add_post(f"{p}/forms/{{form_id}}", page.submit_form)

    # JSON REST API routes (v1)
    app.router.add_post(f"{p}/api/v1/forms", api.create_form)
    app.router.add_get(f"{p}/api/v1/forms", api.list_forms)
    app.router.add_post(f"{p}/api/v1/forms/from-db", api.load_from_db)
    app.router.add_get(f"{p}/api/v1/forms/{{form_id}}", api.get_form)
    app.router.add_get(f"{p}/api/v1/forms/{{form_id}}/schema", api.get_schema)
    app.router.add_get(f"{p}/api/v1/forms/{{form_id}}/style", api.get_style)
    app.router.add_get(f"{p}/api/v1/forms/{{form_id}}/html", api.get_html)
    app.router.add_post(f"{p}/api/v1/forms/{{form_id}}/validate", api.validate)

    # Telegram REST fallback (for WebApp payloads > 4 KB)
    app.router.add_post(
        f"{p}/api/v1/forms/{{form_id}}/telegram-submit", telegram.rest_fallback
    )
