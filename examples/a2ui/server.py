"""FEAT-610 — A2UI linked dashboard example server (QuerySource + AuthHandler + static renderer).

Run: ENV=prod QS_PBAC_ENABLED=false python examples/a2ui/server.py --port 5000
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import importlib.resources
import logging
import sys
from pathlib import Path
from typing import Any

from aiohttp import web
from packaging.version import Version

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard import (  # noqa: E402
    BY_COURSE_SLUG,
    DEFAULT_LLM,
    SLUG,
    build_dashboard_agent,
    dashboard_question,
    extract_envelope,
)

logger = logging.getLogger("a2ui.example")
HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"


def require_querysource(min_version: str = "5.1.2") -> None:
    """Exit with a clear message when querysource is older than ``min_version``.

    Args:
        min_version: Minimum accepted querysource version.
    """
    try:
        found = importlib.metadata.version("querysource")
    except importlib.metadata.PackageNotFoundError:
        sys.exit(f"querysource>={min_version} required, but it is not installed")
    if Version(found) < Version(min_version):
        sys.exit(f"querysource>={min_version} required, found {found}")


async def check_slugs(app: web.Application) -> None:
    """Startup check, read-only: warn when a dashboard slug is missing (never seed here).

    Args:
        app: The aiohttp application.
    """
    try:
        from parrot_tools.querysource.toolkit import QuerysourceToolkit

        toolkit = QuerysourceToolkit(programs=["polestar"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("slug check skipped: %s", exc)
        return
    for slug in (SLUG, BY_COURSE_SLUG):
        try:
            await toolkit.describe_slug(slug)
        except Exception as exc:  # noqa: BLE001
            logger.warning("slug %r is not available: %s", slug, exc)
            if slug == BY_COURSE_SLUG:
                logger.warning("run: ENV=prod python examples/a2ui/seed_by_course.py --yes")


async def index_handler(request: web.Request) -> web.FileResponse:
    """Serve the static dashboard page."""
    return web.FileResponse(STATIC / "index.html")


async def echarts_handler(request: web.Request) -> web.FileResponse:
    """Serve the echarts bundle shipped by ai-parrot-visualizations.

    Resolve the ``assets`` package itself: ``parrot.outputs.formats`` spans the core and visualizations
    distributions, and ``files()`` on it returns only the core directory, which has no ``assets/``.
    """
    path = importlib.resources.files("parrot.outputs.formats.assets") / "echarts.min.js"
    return web.FileResponse(Path(str(path)))


async def dashboard_handler(request: web.Request) -> web.Response:
    """GET /api/a2ui/dashboard[?rebuild=1] returns the cached envelope JSON."""
    app = request.app
    async with app["a2ui_lock"]:
        if request.query.get("rebuild"):
            app.pop("a2ui_envelope", None)
        envelope: dict[str, Any] | None = app.get("a2ui_envelope")
        if envelope is None:
            agent = app.get("a2ui_agent")
            if agent is None:
                agent = build_dashboard_agent(app.get("llm"))
                await agent.configure()
                app["a2ui_agent"] = agent
            try:
                response = await agent.ask(dashboard_question())
                envelope = extract_envelope(response)
            except RuntimeError as exc:
                return web.json_response({"error": str(exc)}, status=502)
            except Exception as exc:  # noqa: BLE001 - an LLM/network failure must not surface as an opaque 500
                logger.exception("dashboard build failed")
                return web.json_response({"error": f"dashboard build failed: {exc}"}, status=502)
            app["a2ui_envelope"] = envelope
    return web.json_response(envelope)


def create_app(*, with_agent_api: bool = False, llm: str | None = None) -> web.Application:
    """Build the example app (QuerySource, optional BotManager, routes, AuthHandler last).

    Args:
        with_agent_api: Also mount the BotManager agent API.
        llm: LLM identifier for the dashboard agent.
    """
    from navigator_auth import AuthHandler
    from querysource.services import QuerySource

    app = web.Application()
    app["llm"] = llm
    app["a2ui_lock"] = asyncio.Lock()
    QuerySource(lazy=False).setup(app)
    if with_agent_api:
        from parrot.manager import BotManager

        manager = BotManager(enable_database_bots=False, enable_registry_bots=False)
        manager.add_agent(build_dashboard_agent(llm))
        manager.setup(app)
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/a2ui/dashboard", dashboard_handler)
    app.router.add_get("/static/vendor/echarts.min.js", echarts_handler)
    if STATIC.is_dir():
        app.router.add_static("/static/", STATIC)
    app.on_startup.append(check_slugs)
    AuthHandler().setup(app)
    app["auth_exclude_list"].extend(["/", "/static/*"])
    return app


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: loopback; the server reads production data)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--with-agent-api", action="store_true")
    parser.add_argument("--llm", default=DEFAULT_LLM)
    args = parser.parse_args()
    require_querysource()
    app = create_app(with_agent_api=args.with_agent_api, llm=args.llm)
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
