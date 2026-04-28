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
* Jira service account: ``JIRA_INSTANCE``, ``JIRA_USERNAME``,
  ``JIRA_API_TOKEN`` and (optionally) ``JIRA_PROJECT`` — the toolkit uses
  ``basic_auth``
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
    """Service-account JiraToolkit (flow-bot, basic_auth)."""
    return JiraToolkit(
        server_url=conf.config.get("JIRA_INSTANCE"),
        auth_type="basic_auth",
        username=conf.config.get("JIRA_USERNAME"),
        password=conf.config.get("JIRA_API_TOKEN"),
        default_project=conf.config.get("JIRA_PROJECT"),
    )


def _build_log_toolkits() -> dict[str, object]:
    """Real-mode log toolkits.

    The CloudWatch toolkit is configured with a fixed ``aws_id`` profile
    and ``default_log_group`` per project policy — the per-source log
    group from each :class:`LogSource` is no longer forwarded as a
    per-query kwarg.
    """
    from parrot_tools.aws.cloudwatch import CloudWatchToolkit

    aws_id = conf.config.get("AWS_PROFILE", fallback="cloudwatch")
    log_group = conf.config.get(
        "CLOUDWATCH_LOG_GROUP", fallback="fluent-bit-cloudwatch"
    )
    toolkits: dict[str, object] = {
        "cloudwatch": CloudWatchToolkit(
            aws_id=aws_id,
            default_log_group=log_group,
        ),
    }
    logger.info(
        "CloudWatch toolkit ready (profile=%s, log_group=%s)",
        aws_id, log_group,
    )
    return toolkits


# ---------------------------------------------------------------------------
# BugBrief / WorkBrief construction from form payload
# ---------------------------------------------------------------------------


_ALLOWED_SHELL_HEADS = {
    "task", "flowtask", "pytest", "ruff", "mypy", "pylint",
}

# FEAT-132: accepted work-kind values (snake_case, lower).
_KIND_VALUES = {"bug", "enhancement", "new_feature"}


def _build_brief_from_form(form: dict[str, Any]) -> dict[str, Any]:
    """Translate the UI form payload into a fully-formed ``WorkBrief``.

    Required form fields:

    * ``summary``              — short title (becomes the Jira summary)
    * ``affected_component``   — file path or component slug
    * ``acceptance_criteria``  — list of shell commands (``ruff check .`` …)
                                 OR list of objects matching the criterion
                                 schema if the UI builds them client-side.

    Optional form fields:

    * ``kind``                 — work kind: ``"Bug"``, ``"Enhancement"``, or
                                 ``"New Feature"`` (as sent by the UI radios).
                                 Normalised to snake_case; unknown values warn
                                 and default to ``"bug"``. FEAT-132.
    * ``description``          — long-form incident text appended to the
                                 summary.
    * ``log_group``            — CloudWatch log group override; falls back
                                 to ``CLOUDWATCH_LOG_GROUP``.
    * ``time_window_minutes``  — CloudWatch lookback window (default 60).
    * ``reporter``             — Jira accountId; falls back to
                                 ``JIRA_REPORTER_ACCOUNT_ID`` then
                                 ``FLOW_BOT_JIRA_ACCOUNT_ID``.
    * ``escalation_assignee``  — Jira accountId; falls back to
                                 ``JIRA_ESCALATION_ACCOUNT_ID`` then
                                 ``FLOW_BOT_JIRA_ACCOUNT_ID``.
    """
    # FEAT-132: normalise kind (label → snake_case value).
    raw_kind = (form.get("kind") or "bug").strip().lower().replace(" ", "_")
    if raw_kind not in _KIND_VALUES:
        logger.warning(
            "Unknown kind %r submitted; defaulting to 'bug'", raw_kind
        )
        raw_kind = "bug"

    summary = (form.get("summary") or "").strip()
    if not summary:
        raise ValueError("summary is required")
    if len(summary) > 255:
        # Atlassian rejects summaries > 255 chars with a 400 — trim
        # explicitly with a sentinel so the user notices it happened.
        summary = summary[:252].rstrip() + "..."
    description = (form.get("description") or "").strip()

    component = (form.get("affected_component") or "").strip()
    if not component:
        raise ValueError("affected_component is required")

    log_group = (
        form.get("log_group")
        or conf.config.get("CLOUDWATCH_LOG_GROUP",
                           fallback="fluent-bit-cloudwatch")
    )
    window = int(form.get("time_window_minutes") or 60)

    raw_criteria = form.get("acceptance_criteria") or []
    criteria = _normalise_criteria(raw_criteria)
    if not criteria:
        raise ValueError(
            "at least one acceptance criterion is required — write one "
            "per line. Lines starting with an allowlisted head "
            f"({sorted(_ALLOWED_SHELL_HEADS)}) become executable shell "
            "criteria; any other prose becomes a manual criterion that "
            "the human reviewer signs off in Jira."
        )

    bot_account = conf.config.get("FLOW_BOT_JIRA_ACCOUNT_ID", fallback="")
    reporter = (
        form.get("reporter")
        or conf.config.get("JIRA_REPORTER_ACCOUNT_ID", fallback=bot_account)
    )
    escalation = (
        form.get("escalation_assignee")
        or conf.config.get("JIRA_ESCALATION_ACCOUNT_ID", fallback=bot_account)
    )
    if not reporter or not escalation:
        raise ValueError(
            "reporter and escalation_assignee are required; set "
            "FLOW_BOT_JIRA_ACCOUNT_ID, JIRA_REPORTER_ACCOUNT_ID and "
            "JIRA_ESCALATION_ACCOUNT_ID in the environment, or pass them "
            "in the form payload."
        )

    payload: dict[str, Any] = {
        "kind": raw_kind,  # FEAT-132
        "summary": summary,
        "description": description,
        "affected_component": component,
        "log_sources": [
            {
                "kind": "cloudwatch",
                "locator": log_group,
                "time_window_minutes": window,
            }
        ],
        "acceptance_criteria": criteria,
        "reporter": reporter,
        "escalation_assignee": escalation,
    }
    existing = (form.get("existing_issue_key") or "").strip()
    if existing:
        payload["existing_issue_key"] = existing
    return payload


def _normalise_criteria(raw: Any) -> list[dict[str, Any]]:
    """Translate textarea lines into a list of acceptance-criterion dicts.

    Each line is classified by inspecting its first whitespace-separated
    token (with a trailing colon stripped):

    * **First token in the allowlist** → :class:`ShellCriterion`. The
      QA subagent runs the command via subprocess and asserts exit
      code 0. Allowed heads:
      ``task | flowtask | pytest | ruff | mypy | pylint``.
    * **Anything else** → :class:`ManualCriterion`. The line text is
      attached to the Jira ticket description; the QA gate auto-passes
      it (``passed=True`` in the report) and the human reviewer signs
      off as part of the PR review.

    Tolerated quirks:

    * Trailing colon on the head: ``task: foo.yaml`` → ``task foo.yaml``.
    * Leading bullet markers (``- `` or ``* ``) are stripped so users
      can paste prose lists.

    Examples (mixed: shell + manual)::

        task etl/customers/sync.yaml
        ruff check .
        - The customer count must equal 1500 after a sync of a 1500-row CSV
        PR description references the original Jira ticket
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            out.append(item)
            continue
        if not isinstance(item, str):
            continue
        line = item.strip()
        # Trim leading bullet/dash so prose lists work too.
        if line.startswith(("- ", "* ")):
            line = line[2:].lstrip()
        if not line:
            continue
        head_token, _, tail = line.partition(" ")
        head = head_token.rstrip(":")
        if head in _ALLOWED_SHELL_HEADS:
            cmd = head + (f" {tail}" if tail else "")
            out.append({
                "kind": "shell",
                "name": f"{head}-criterion-{idx}",
                "command": cmd,
            })
        else:
            out.append({
                "kind": "manual",
                "name": f"manual-criterion-{idx}",
                "text": line,
            })
    return out


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------


async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_run(request: web.Request) -> web.Response:
    """Start a real ``flow.run_flow(...)`` invocation.

    Body must be the JSON form payload described in
    :func:`_build_brief_from_form`. The UI client at ``/`` posts it from
    the incident form.
    """
    if not request.can_read_body:
        return web.json_response(
            {"error": "JSON body required"}, status=400
        )
    try:
        form = await request.json()
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"error": f"invalid JSON: {exc}"}, status=400
        )
    if not isinstance(form, dict):
        return web.json_response(
            {"error": "body must be a JSON object"}, status=400
        )

    try:
        payload = _build_brief_from_form(form)
        brief = BugBrief.model_validate(payload)
    except (ValueError, TypeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001 - validation surface
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
        max_concurrent=conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES,
        redis_url=redis_url,
        stream_ttl_seconds=conf.FLOW_STREAM_TTL_SECONDS,
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
    """Graceful Ctrl-C / SIGTERM cleanup.

    Cancels every in-flight flow task and waits for them to settle (so
    we don't leave zombies that scribble on Redis after the loop is
    teared down), then closes the shared Redis client. Each step
    swallows its own exceptions because shutdown errors should never
    mask each other.
    """
    tasks = list(app.get("flow_tasks", []))
    for task in tasks:
        task.cancel()
    if tasks:
        # gather(return_exceptions=True) collects CancelledError silently.
        await asyncio.gather(*tasks, return_exceptions=True)

    redis = app.get("redis")
    if redis is not None:
        try:
            await redis.aclose()
        except AttributeError:  # pragma: no cover - older redis-py
            try:
                await redis.close()
            except Exception:  # pragma: no cover
                logger.debug("redis close raised during shutdown",
                             exc_info=True)
        except Exception:  # pragma: no cover
            logger.debug("redis aclose raised during shutdown", exc_info=True)


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
