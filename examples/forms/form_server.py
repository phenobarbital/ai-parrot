"""Example: aiohttp form server using parrot-formdesigner.

Open http://localhost:8080 in a browser to:
1. Describe a form in plain language — AI generates a FormSchema
2. Load a form from PostgreSQL — enter formid + orgid to import a DB-defined form
3. Fill in the generated HTML5 form
4. Submit and see validated results

API endpoints:
- POST /api/forms          — create a form (JSON body: {"prompt": "..."})
- GET  /api/forms          — list all created forms
- POST /api/forms/from-db  — load a form from PostgreSQL
- GET  /forms/{id}         — render the form
- POST /forms/{id}         — validate a submission
- GET  /api/forms/{id}/schema  — get JSON Schema
- GET  /api/forms/{id}/html    — get rendered HTML

Usage:
    source .venv/bin/activate
    python examples/forms/form_server.py
"""

from aiohttp import web

from parrot.clients.factory import LLMFactory
from parrot.formdesigner.handlers import setup_form_routes


async def create_app() -> web.Application:
    """Build and return the configured aiohttp Application.

    Returns:
        Configured aiohttp Application with all form routes registered.
    """
    app = web.Application()
    client = LLMFactory.create("google")
    setup_form_routes(app, client=client)
    return app


if __name__ == "__main__":
    print("AI Form Builder running at http://localhost:8080")
    web.run_app(create_app(), host="0.0.0.0", port=8080)
