"""FEAT-129 — Dev-Loop Orchestration: real demo server.

Hosts an aiohttp app that wires the **real** five-node ``AgentsFlow``
(BugIntake → Research → Development → QA → DeploymentHandoff) behind
three HTTP endpoints, plus a vanilla-JS UI client at ``/`` that
visualises the merged event stream.

Endpoints:

* ``GET  /``                            — UI client (served from ``static/``)
* ``POST /api/flow/run``                — start a real flow run; body is a
                                          ``BugBrief`` JSON (or omit to use
                                          the bundled sample brief)
* ``GET  /api/flow/{run_id}/ws``        — WebSocket multiplexer
                                          (``parrot.flows.dev_loop.flow_stream_ws``)
* ``GET  /api/flow/{run_id}/replay``    — JSON dump of stored events for a run

Runtime requirements:

* Redis on ``REDIS_URL`` (default ``redis://localhost:6379/0``)
* ``ANTHROPIC_API_KEY`` (or any provider key the Claude Agent SDK accepts)
* ``claude`` CLI on ``$PATH`` and authenticated
* Jira service-account token in ``FLOW_BOT_JIRA_TOKEN`` +
  ``JIRA_SERVER_URL``
* AWS credentials (CloudWatch) and ``ELASTICSEARCH_URL`` if you want both
  log toolkits — set ``LOG_TOOLKITS`` (comma-separated) to limit.
* ``gh`` CLI authenticated for the DeploymentHandoff PR step

Boot::

    docker run --rm -p 6379:6379 redis:7    # if you don't have one
    source .venv/bin/activate
    python examples/dev_loop/server.py
    # http://localhost:8080
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis
from aiohttp import web

from parrot import conf
from parrot.auth.credentials import StaticCredentialResolver, StaticCredentials
from parrot.flows.dev_loop import (
    BugBrief,
    ClaudeCodeDispatcher,
    build_dev_loop_flow,
    flow_stream_ws,
)
from parrot_tools.jiratoolkit import JiraToolkit


logger = logging.getLogger("dev_loop.server")
STATIC_DIR = Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# Toolkit wiring
# ---------------------------------------------------------------------------


def _build_jira_toolkit() -> JiraToolkit:
    """Service-account JiraToolkit (flow-bot)."""
    resolver = StaticCredentialResolver(
        credentials=StaticCredentials(
            token=conf.config.get("FLOW_BOT_JIRA_TOKEN"),
            user_id="flow-bot",
        ),
    )
    return JiraToolkit(
        server_url=conf.config.get("JIRA_SERVER_URL"),
        auth_type="bearer",
        user_id="flow-bot",
        credential_resolver=resolver,
    )


def _build_log_toolkits() -> dict[str, object]:
    """Build only the log toolkits whose env config is present.

    Set ``LOG_TOOLKITS=cloudwatch`` or ``=elasticsearch`` to force a
    subset; default tries both and skips missing config.
    """
    requested = {
        s.strip()
        for s in os.environ.get("LOG_TOOLKITS", "cloudwatch,elasticsearch").split(",")
        if s.strip()
    }
    toolkits: dict[str, object] = {}

    if "cloudwatch" in requested:
        try:
            from parrot_tools.aws.cloudwatch import CloudWatchToolkit

            toolkits["cloudwatch"] = CloudWatchToolkit(
                region_name=conf.config.get("AWS_REGION", fallback="us-east-1"),
            )
        except Exception as exc:  # noqa: BLE001 - optional toolkit
            logger.warning("CloudWatch toolkit disabled: %s", exc)

    if "elasticsearch" in requested:
        try:
            from parrot_tools.elasticsearch import ElasticsearchTool

            toolkits["elasticsearch"] = ElasticsearchTool(
                host=conf.config.get("ELASTICSEARCH_HOST"),
                port=conf.config.get("ELASTICSEARCH_PORT", fallback=9200),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Elasticsearch toolkit disabled: %s", exc)

    return toolkits


def _sample_brief_payload() -> dict[str, Any]:
    """Default BugBrief used when the UI sends an empty body."""
    return {
        "summary": (
            "Customer sync flowtask drops the last row when input has "
            ">1000 records. Reproduce: run etl/customers/sync.yaml against "
            "a 1500-row CSV; the resulting Postgres table has 1499 rows."
        ),
        "affected_component": "etl/customers/sync.yaml",
        "log_sources": [
            {
                "kind": "cloudwatch",
                "locator": "/etl/prod/customers",
                "time_window_minutes": 120,
            }
        ],
        "acceptance_criteria": [
            {
                "kind": "flowtask",
                "name": "customers-sync-no-row-drop",
                "task_path": "etl/customers/sync.yaml",
                "args": ["--input", "tests/fixtures/customers_1500.csv"],
                "expected_exit_code": 0,
                "timeout_seconds": 600,
            },
            {"kind": "shell", "name": "ruff-clean", "command": "ruff check ."},
            {"kind": "shell", "name": "mypy-clean",
             "command": "mypy --no-incremental"},
        ],
        "reporter": conf.config.get(
            "DEMO_REPORTER_ACCOUNT_ID", fallback="557058:original-human"
        ),
        "escalation_assignee": conf.config.get(
            "FLOW_BOT_JIRA_ACCOUNT_ID", fallback="557058:on-call-engineer"
        ),
    }


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------


async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_run(request: web.Request) -> web.Response:
    """Start a real ``flow.run_flow(...)`` invocation.

    Body is an optional JSON ``BugBrief``; missing fields fall back to
    :func:`_sample_brief_payload`.
    """
    payload: dict[str, Any] = {}
    if request.can_read_body:
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {}
    payload = {**_sample_brief_payload(), **(payload or {})}
    try:
        brief = BugBrief.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"error": str(exc)}, status=400)

    run_id = f"run-{uuid.uuid4().hex[:8]}"
    flow = request.app["flow"]
    started_at = time.time()

    async def _run() -> None:
        try:
            logger.info("Starting flow run_id=%s", run_id)
            await flow.run_flow(
                initial_task=f"resolve: {brief.summary[:120]}",
                bug_brief=brief,
                run_id=run_id,
            )
            logger.info("Flow run_id=%s finished in %.1fs",
                        run_id, time.time() - started_at)
        except Exception:
            logger.exception("Flow run_id=%s failed", run_id)

    task = asyncio.create_task(_run(), name=f"flow-run-{run_id}")
    request.app["flow_tasks"].add(task)
    task.add_done_callback(request.app["flow_tasks"].discard)

    return web.json_response(
        {"run_id": run_id, "ws_url": f"/api/flow/{run_id}/ws"}
    )


async def handle_replay(request: web.Request) -> web.Response:
    """Dump every stored event for a run (debugging helper)."""
    run_id = request.match_info["run_id"]
    redis = request.app["redis"]
    flow_key = f"flow:{run_id}:flow"
    dispatch_keys = [
        k async for k in redis.scan_iter(match=f"flow:{run_id}:dispatch:*")
    ]
    out: list[dict[str, Any]] = []
    for key in [flow_key, *dispatch_keys]:
        for _entry_id, fields in await redis.xrange(key, "-", "+"):
            raw = fields.get("event")
            try:
                out.append({"stream": key, "event": json.loads(raw)})
            except (TypeError, ValueError):
                out.append({"stream": key, "raw": fields})
    return web.json_response(out)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


async def _on_startup(app: web.Application) -> None:
    redis_url = app["redis_url"]
    app["redis"] = aioredis.from_url(redis_url, decode_responses=True)

    dispatcher = ClaudeCodeDispatcher(
        max_concurrent=conf.config.get(
            "CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES", fallback=3
        ),
        redis_url=redis_url,
        stream_ttl_seconds=conf.config.get(
            "FLOW_STREAM_TTL_SECONDS", fallback=604800
        ),
    )
    app["flow"] = build_dev_loop_flow(
        dispatcher=dispatcher,
        jira_toolkit=_build_jira_toolkit(),
        log_toolkits=_build_log_toolkits(),
        redis_url=redis_url,
        name="dev-loop-demo",
    )
    app["flow_tasks"] = set()
    logger.info("Dev-loop flow ready")


async def _on_cleanup(app: web.Application) -> None:
    for task in list(app.get("flow_tasks", [])):
        task.cancel()
    redis = app.get("redis")
    if redis is not None:
        try:
            await redis.aclose()
        except AttributeError:  # pragma: no cover - older redis-py
            await redis.close()


def build_app(redis_url: str = "redis://localhost:6379/0") -> web.Application:
    app = web.Application()
    app["redis_url"] = redis_url
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)

    app.router.add_get("/", handle_index)
    app.router.add_static("/static/", STATIC_DIR, show_index=False)
    app.router.add_post("/api/flow/run", handle_run)
    app.router.add_get("/api/flow/{run_id}/replay", handle_replay)
    app.router.add_get("/api/flow/{run_id}/ws", flow_stream_ws)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    app = build_app(redis_url=redis_url)
    logger.info(
        "Dev-loop demo on http://%s:%s (Redis=%s)", host, port, redis_url
    )
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    main()
