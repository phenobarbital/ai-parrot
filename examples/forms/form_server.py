"""Run the authenticated aiohttp form-designer example.

Open ``http://localhost:8080/admin`` to log in, generate or import a form,
render it, and submit validated results. Run with
``python examples/forms/form_server.py`` from the repository root.
"""

from aiohttp import web
from navigator_auth import AuthHandler

from parrot.autonomous.admin import admin_login_page
from parrot.clients.factory import LLMFactory
from parrot_formdesigner.handlers import setup_form_routes


async def create_app() -> web.Application:
    """Build the application with authentication and form routes."""
    app = web.Application()

    app.router.add_get("/admin", admin_login_page)

    # HTML pages use page_shell's client-side JWT flow.
    client = LLMFactory.create("google")
    setup_form_routes(app, client=client, protect_pages=False)

    auth = AuthHandler()
    auth.setup(app)
    app["auth_exclude_list"].extend([
        "/admin", "/", "/gallery", "/forms/*",
    ])

    return app


if __name__ == "__main__":
    print("AI Form Builder running at http://localhost:8080")
    print("  Admin login: http://localhost:8080/admin")
    web.run_app(create_app(), host="0.0.0.0", port=8080)
