"""Route registration helper for parrot-formdesigner.

One-liner integration: setup_form_routes(app, registry=registry)
"""

from __future__ import annotations

from aiohttp import web

from ..services.registry import FormRegistry
from .api import FormAPIHandler
from .forms import FormPageHandler


def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client=None,
    prefix: str = "",
) -> None:
    """Register all form routes on the aiohttp application.

    Args:
        app: The aiohttp Application to register routes on.
        registry: Optional FormRegistry. A new one is created if not provided.
        client: Optional LLM client for natural language form creation.
        prefix: Optional URL prefix for all routes (e.g. "/forms-app").
    """
    if registry is None:
        registry = FormRegistry()

    api = FormAPIHandler(registry=registry, client=client)
    page = FormPageHandler(registry=registry)

    p = prefix.rstrip("/")

    # HTML page routes
    app.router.add_get(f"{p}/", page.index)
    app.router.add_get(f"{p}/gallery", page.gallery)
    app.router.add_get(f"{p}/forms/{{form_id}}", page.render_form)
    app.router.add_get(f"{p}/forms/{{form_id}}/schema", page.view_schema)
    app.router.add_post(f"{p}/forms/{{form_id}}", page.submit_form)

    # JSON REST API routes
    app.router.add_post(f"{p}/api/forms", api.create_form)
    app.router.add_get(f"{p}/api/forms", api.list_forms)
    app.router.add_post(f"{p}/api/forms/from-db", api.load_from_db)
    app.router.add_get(f"{p}/api/forms/{{form_id}}", api.get_form)
    app.router.add_get(f"{p}/api/forms/{{form_id}}/schema", api.get_schema)
    app.router.add_get(f"{p}/api/forms/{{form_id}}/style", api.get_style)
    app.router.add_get(f"{p}/api/forms/{{form_id}}/html", api.get_html)
    app.router.add_post(f"{p}/api/forms/{{form_id}}/validate", api.validate)
