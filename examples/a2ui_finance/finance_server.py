"""A2UI finance example server — QuerySource + AuthHandler + the shared static renderer, definition-only envelope.

Run: ENV=prod QS_PBAC_ENABLED=false python examples/a2ui_finance/finance_server.py --port 5001

Differences from examples/a2ui/server.py: the served envelope is definition-only (``ensure_definition_only``), the
static lane (``linked.js`` / ``renderer.js`` / ``styles.css``) is SHARED with examples/a2ui/static, and the startup
check also exercises the backend path the ``--check`` client relies on: ``DatasetManager.add_query`` +
``materialize`` over the seeded slug.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from aiohttp import web

from parrot.outputs.a2ui.linked.executor import is_empty_result

HERE = Path(__file__).resolve().parent
POLESTAR_EXAMPLE = HERE.parent / "a2ui"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(POLESTAR_EXAMPLE))

from finance_dashboard import (  # noqa: E402
    DEFAULT_LLM,
    LATEST_SLUG,
    PROGRAM,
    SNAPSHOTS_SLUG,
    build_dashboard_agent,
    dashboard_question,
    ensure_definition_only,
    extract_envelope,
)
from server import echarts_handler, require_querysource  # noqa: E402 - reused from the Polestar example

logger = logging.getLogger("a2ui_finance.example")
STATIC = HERE / "static"  # only index.html lives here
STATIC_SHARED = POLESTAR_EXAMPLE / "static"  # linked.js, renderer.js, styles.css


async def check_slugs(app: web.Application) -> None:
    """Startup check, read-only: warn when a finance slug is missing or the DatasetManager path cannot run it.

    Never seeds. The DatasetManager probe (``querylimit=1``) is the same in-process path ``finance_client.py --check``
    uses to compute its expected values, so a warning here means the check would fail too.
    """
    try:
        from parrot.tools.dataset_manager.tool import DatasetManager
        from parrot_tools.querysource.toolkit import QuerysourceToolkit

        toolkit = QuerysourceToolkit(programs=[PROGRAM])
    except Exception as exc:  # noqa: BLE001
        logger.warning("slug check skipped: %s", exc)
        return
    missing: list[str] = []
    try:
        for slug in (SNAPSHOTS_SLUG, LATEST_SLUG):
            try:
                await toolkit.describe_slug(slug)
            except Exception as exc:  # noqa: BLE001
                missing.append(slug)
                logger.warning("slug %r is not available: %s", slug, exc)
    finally:
        await toolkit._close()
    if missing:
        logger.warning("run: ENV=prod python examples/a2ui_finance/seed_finance.py --yes")
        return
    try:
        manager = DatasetManager(generate_guide=False)
        manager.add_query("finance_latest", query_slug=LATEST_SLUG, description="latest finance snapshot")
        frame = await manager.materialize("finance_latest", querylimit=1)
        logger.info("DatasetManager probe of %r ok: columns %s", LATEST_SLUG, list(frame.columns))
    except Exception as exc:  # noqa: BLE001
        if is_empty_result(exc):
            logger.warning("%r ran but matched no row: is troc.finance_projection empty?", LATEST_SLUG)
        else:
            logger.warning("DatasetManager cannot run %r (the --check client will fail too): %s", LATEST_SLUG, exc)


async def index_handler(request: web.Request) -> web.FileResponse:
    """Serve the finance dashboard page."""
    return web.FileResponse(STATIC / "index.html")


async def dashboard_handler(request: web.Request) -> web.Response:
    """GET /api/a2ui/dashboard[?rebuild=1] returns the cached, definition-only envelope JSON."""
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
                envelope = ensure_definition_only(extract_envelope(response))
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
    QuerySource(lazy=False).setup(app)  # /api/v2/services/queries, /api/v3/queries, /api/v1/{tenant}/queries
    if with_agent_api:
        from parrot.manager import BotManager

        manager = BotManager(enable_database_bots=False, enable_registry_bots=False)
        manager.add_agent(build_dashboard_agent(llm))
        manager.setup(app)
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/a2ui/dashboard", dashboard_handler)
    app.router.add_get("/static/vendor/echarts.min.js", echarts_handler)
    if STATIC_SHARED.is_dir():
        app.router.add_static("/static/", STATIC_SHARED)
    app.on_startup.append(check_slugs)
    AuthHandler().setup(app)
    app["auth_exclude_list"].extend(["/", "/static/*"])
    return app


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host", default="127.0.0.1", help="bind address (default: loopback; the server reads production data)"
    )
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--with-agent-api", action="store_true")
    parser.add_argument("--llm", default=DEFAULT_LLM)
    args = parser.parse_args()
    require_querysource()
    app = create_app(with_agent_api=args.with_agent_api, llm=args.llm)
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
