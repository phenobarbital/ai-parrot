"""Example: aiohttp form server using parrot-formdesigner.

Open http://localhost:8080 in a browser to:
1. Log in at /admin — authenticates via /api/v1/login
2. Describe a form in plain language — AI generates a FormSchema
3. Load a form from PostgreSQL — enter formid + orgid to import a DB-defined form
4. Fill in the generated HTML5 form
5. Submit and see validated results

API endpoints:
- GET  /admin              — admin login page
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
from navigator_auth import AuthHandler

from parrot.autonomous.admin import admin_login_page
from parrot.clients.factory import LLMFactory
from parrot.formdesigner.handlers import setup_form_routes


async def create_app() -> web.Application:
    """Build and return the configured aiohttp Application.

    Uses ``navigator_auth.AuthHandler`` which automatically:
    - Registers ``/api/v1/login`` and ``/api/v1/logout`` routes.
    - Adds JWT-validating middleware to all requests.
    - Excludes public paths (login, logout, static) from auth checks.

    The admin login page (``/admin``) collects credentials, POSTs to
    ``/api/v1/login``, and stores the JWT in localStorage.  The
    ``page_shell`` auth script injects the token into every ``fetch()``
    call to ``/api/`` endpoints.

    Returns:
        Configured aiohttp Application with auth + form routes.
    """
    app = web.Application()

    # Admin login page (excluded from auth below).
    app.router.add_get("/admin", admin_login_page)

    # Form designer routes — protect_pages=False because authentication
    # for HTML pages is handled client-side: the _AUTH_SCRIPT in page_shell
    # checks localStorage for the JWT and injects it into fetch() calls.
    client = LLMFactory.create("google")
    setup_form_routes(app, client=client, protect_pages=False)

    # Authentication — registers /api/v1/login, /api/v1/logout, and
    # JWT-validating middleware automatically.
    auth = AuthHandler()
    auth.setup(app)
    # Exclude HTML pages from middleware auth; the client-side script
    # redirects to /admin when no token is present in localStorage.
    app["auth_exclude_list"].extend([
        "/admin", "/", "/gallery", "/forms/*",
    ])

    return app


if __name__ == "__main__":
    print("AI Form Builder running at http://localhost:8080")
    print("  Admin login: http://localhost:8080/admin")
    web.run_app(create_app(), host="0.0.0.0", port=8080)
