"""Development console for the ``dev-flow`` topology (FEAT-412).

The **development** sibling of ``server.py``: same streaming/telemetry
plumbing, a different intake and a HITL write path.

Deltas versus the operations console (spec §2 table):

======================  ==============================  ===========================
Concern                 ``server.py`` (ops)             ``server_dev.py`` (dev-flow)
======================  ==============================  ===========================
``GET /``               ``static/index.html``           ``static/dev.html``
Flow                    bug graph + injected feature    ``build_dev_flow`` only
Runner                  ``DevLoopRunner``               ``DevFlowRunner``
Log toolkits            CloudWatch via                  **absent** — dev-flow has
                        ``_build_log_toolkits()``       no ``ResearchNode``
Jira                    required for bug runs           optional, link-only
Brief building          summary + ``affected_component``  ``DevRequestBrief`` (title
                        + ``log_sources``               + description) or
                                                        ``FeatureBrief``
Gate resolution         **not mounted**                 mounted (the HITL write path)
Plan gate               fixed at flow build              per-run UI toggle
Default port            8080                            **8081**
======================  ==============================  ===========================

Both servers can therefore run side by side against the same Redis.

Reuse policy: every ops-free helper (dispatcher/reviewer builders, the
document-brief form parser, the bundle/replay/cancel handlers) is **imported
from** ``server.py`` rather than copied, so the two consoles cannot drift.
``server.py`` itself is not modified in any way — this module only reads it.
Deliberately NOT imported: ``_build_log_toolkits`` (CloudWatch) and
``_build_brief_from_form`` (bug intake).

Run it with::

    PORT=8081 python examples/dev_loop/server_dev.py
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis
from aiohttp import web
from parrot import conf
from parrot.flows.dev_flow.flow import build_dev_flow
from parrot.flows.dev_flow.models import DevRequestBrief
from parrot.flows.dev_flow.runner import DevFlowRunner
from parrot.flows.dev_loop import (
    ClaudeCodeDispatcher,
    flow_stream_ws,
    parse_repo_specs,
)
from parrot.flows.dev_loop.agent_builder import (
    build_dispatcher,
    parse_pool_env,
    resolve_pool_max,
)
from parrot.flows.dev_loop.commands import resolve_gate_handler
from parrot.flows.dev_loop.graph_memory import DevLoopGraphMemory
from parrot.flows.dev_loop.models import DevAgentSpec, JudgePanelConfig
from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch

# Sibling-module imports, resolvable whether this file is launched as a
# script or imported from elsewhere — the same trick ``server.py`` uses for
# ``llm_catalog``.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_catalog
import server as ops_server

logger = logging.getLogger("dev_flow.server")
STATIC_DIR = Path(__file__).parent / "static"
# Same artifact convention as the ops console: DevLoopRunner._close_host
# writes {run_id}.bundle.json / {run_id}.report.md there, and the reused
# bundle/replay handlers read it from that module-level constant.
RUN_ARTIFACT_DIR = ops_server.RUN_ARTIFACT_DIR

# The three user-selected dev-flow intents (spec §8: no LLM classification).
_DEV_KINDS = ("enhancement", "new_feature", "feature")


# ---------------------------------------------------------------------------
# Brief building
# ---------------------------------------------------------------------------


def _normalise_kind(raw: Any) -> str:
    """Normalise a console ``kind`` label to its canonical value.

    Args:
        raw: The raw form value (e.g. ``"New Feature"``).

    Returns:
        The canonical kind (``"enhancement"``, ``"new_feature"`` or
        ``"feature"``), or the normalised input when unrecognised — the
        caller reports the error.
    """
    return (str(raw or "")).strip().lower().replace(" ", "_").replace("-", "_")


def _build_dev_brief_from_form(form: dict[str, Any]) -> DevRequestBrief | Any:
    """Translate the dev console's form into a dev-flow brief.

    Two shapes, selected by ``kind``:

    * ``enhancement`` / ``new_feature`` → a :class:`DevRequestBrief`. The
      request is **natural language**: ``title`` (the slug source) and
      ``description`` are required; ``context`` is optional. No document
      exists yet — ``IdeationNode`` writes it.
    * ``feature`` → a ``FeatureBrief``, built by the ops console's own
      ``_build_feature_brief_from_form`` (imported, not duplicated) so the
      document intake behaves identically in both consoles.

    Optional in both shapes: ``jira_issue_key`` (link-only — dev-flow never
    creates a ticket), ``dev_agents``, ``judge_panel``.

    Deliberately absent: ``affected_component``, ``log_sources``,
    ``reporter``, ``escalation_assignee`` and ``acceptance_criteria`` — those
    are bug-intake concepts with no meaning here.

    Args:
        form: The decoded JSON body posted by the console.

    Returns:
        A validated ``DevRequestBrief`` or ``FeatureBrief``.

    Raises:
        ValueError: Unknown ``kind``, or a missing ``title``/``description``
            for a natural-language request (plus anything the models'
            own validators reject).
    """
    kind = _normalise_kind(form.get("kind"))
    if kind == "feature":
        return ops_server._build_feature_brief_from_form(form)
    if kind not in ("enhancement", "new_feature"):
        raise ValueError("kind must be 'enhancement', 'new_feature' or 'feature', got " f"{kind!r}")

    title = (form.get("title") or "").strip()
    if not title:
        raise ValueError(
            "title is required — it names the request and is the slug source " "for sdd/proposals/<slug>.*.md"
        )
    description = (form.get("description") or "").strip()
    if not description:
        raise ValueError(
            "description is required — it is the natural-language request the "
            "sdd-ideation subagent turns into an SDD document"
        )

    payload: dict[str, Any] = {
        "kind": kind,
        "title": title,
        "description": description,
    }
    context = (form.get("context") or "").strip()
    if context:
        payload["context"] = context
    issue_key = (form.get("jira_issue_key") or "").strip()
    if issue_key:
        payload["jira_issue_key"] = issue_key
    dev_agents = ops_server._parse_dev_agents(form.get("dev_agents"))
    if dev_agents:
        payload["dev_agents"] = dev_agents
    judges = ops_server._parse_judge_panel(form.get("judge_panel"))
    if judges:
        payload["judge_panel"] = JudgePanelConfig(judges=judges)

    # FEAT-466 TASK-2508: reuse the ops-server override parser. Note:
    # DevRequestBrief (like FeatureBrief) declares no flow_type/base_branch
    # fields — this flow never handles kind="bug", so the override is
    # currently inert here (Pydantic's default extra="ignore" drops the
    # keys); parsed only to keep every payload builder symmetric.
    ops_server._apply_flow_override(payload, form)
    return DevRequestBrief.model_validate(payload)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def handle_index(request: web.Request) -> web.FileResponse:
    """Serve the development console (never ``index.html``)."""
    return web.FileResponse(STATIC_DIR / "dev.html")


async def handle_config(request: web.Request) -> web.Response:
    """Serve the dev console's configuration catalog.

    Same LLM-catalog payload as the ops console, but the operator-visible
    defaults carry the dev-flow knobs and **no** observability/Jira-project
    settings: there is no CloudWatch log group, no time window and no
    mandatory project, because nothing in this topology reads them.
    """
    app = request.app
    runner = app.get("runner")
    return web.json_response(
        {
            **llm_catalog.catalog_payload(),
            "kinds": [
                {"value": "enhancement", "label": "Enhancement"},
                {"value": "new_feature", "label": "New Feature"},
                {"value": "feature", "label": "Feature (existing SDD doc)"},
            ],
            "document_kinds": ["brainstorm", "proposal", "spec"],
            # The intents whose runs go through ideation (the UI shows the
            # natural-language intake for these, a document picker otherwise).
            "nl_kinds": ["enhancement", "new_feature"],
            "gate_resolve_url_template": ("/api/flow/{run_id}/gates/{gate_id}/resolve"),
            "defaults": {
                "development_agent": conf.config.get("DEV_LOOP_DEVELOPMENT_AGENT", fallback="claude-code"),
                "codereview_agent": app.get("codereview_agent_key", "parallel"),
                "codereview_agent_configured": conf.config.get("DEV_LOOP_CODEREVIEW_AGENT", fallback="parallel"),
                "qa_max_retries": conf.DEV_LOOP_QA_MAX_RETRIES,
                "development_pool_max": app.get("development_pool_max", 4),
                "max_concurrent_runs": getattr(runner, "max_concurrent_runs", None),
                "ideation_max_rounds": getattr(conf, "DEV_FLOW_IDEATION_MAX_ROUNDS", 2),
                "gate_ttl_questions": getattr(conf, "DEV_FLOW_GATE_TTL_QUESTIONS", 86400),
                "require_plan_approval": bool(app.get("require_plan_approval", False)),
                "skip_qa": bool(getattr(conf, "DEV_LOOP_SKIP_QA", False)),
                "docs_artifact_dir": conf.DEV_LOOP_DOCS_ARTIFACT_DIR,
                "wiki_page_ingest": conf.DEV_LOOP_WIKI_PAGE_INGEST,
                "wiki_search": app.get("wiki_search") is not None,
                "jira_configured": app.get("jira_toolkit") is not None,
            },
            "adversarial_review": {
                "mandatory": True,
                "scope": conf.DEV_LOOP_ADVERSARIAL_SCOPE,
                "base_ref": conf.DEV_LOOP_ADVERSARIAL_BASE_REF,
                "note": (
                    "Every dev-flow run carries the read-only Codex "
                    "sdd-secondopinion seat as a judge in the QA panel. It "
                    "cannot be switched off."
                ),
            },
        }
    )


async def handle_run(request: web.Request) -> web.Response:
    """Start one ``DevFlowRunner.run(...)`` invocation.

    The JSON body is the dev console's form payload. ``kind`` decides the
    brief shape only — every run executes the SAME dev-flow graph, whose
    ``dev_intake`` node routes a natural-language brief through ideation and
    a document brief straight to the planner.
    """
    if not request.can_read_body:
        return web.json_response({"error": "JSON body required"}, status=400)
    try:
        form = await request.json()
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"error": f"invalid JSON: {exc}"}, status=400)
    if not isinstance(form, dict):
        return web.json_response({"error": "body must be a JSON object"}, status=400)

    try:
        brief = _build_dev_brief_from_form(form)
    except (ValueError, TypeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001 - validation surface
        return web.json_response({"error": str(exc)}, status=400)

    kind = getattr(brief, "kind", "")
    if kind == "feature":
        label = brief.document_path
        initial_task = f"feature: {Path(brief.document_path).name}"
    else:
        label = brief.title
        initial_task = f"{kind}: {brief.title[:120]}"

    run_id = f"run-{uuid.uuid4().hex[:8]}"
    runner: DevFlowRunner = request.app["runner"]
    started_at = time.time()

    extra_shared: dict[str, Any] = {}
    if bool(form.get("skip_qa", False)):
        extra_shared["skip_qa"] = True
    if bool(form.get("skip_jira", False)):
        extra_shared["skip_jira"] = True
    # FEAT-412 / TASK-2123: the per-run plan-gate toggle. Only forwarded when
    # the form actually carries the field, so an absent toggle falls back to
    # the flow's build-time default instead of silently overriding it.
    if "require_plan_approval" in form:
        extra_shared["require_plan_approval"] = bool(form.get("require_plan_approval"))

    async def _run() -> None:
        try:
            logger.info(
                "Starting dev-flow run_id=%s kind=%s (%s) extra_shared=%s",
                run_id,
                kind,
                label,
                sorted(extra_shared),
            )
            result = await runner.run(
                brief,
                run_id=run_id,
                initial_task=initial_task,
                extra_shared=extra_shared or None,
            )
            logger.info(
                "dev-flow run_id=%s finished status=%s in %.1fs",
                run_id,
                result.status,
                time.time() - started_at,
            )
        except Exception:
            logger.exception("dev-flow run_id=%s failed", run_id)

    task = asyncio.create_task(_run(), name=f"dev-flow-run-{run_id}")
    request.app["flow_tasks"][run_id] = task
    task.add_done_callback(lambda t: request.app["flow_tasks"].pop(run_id, None))

    return web.json_response(
        {
            "run_id": run_id,
            "mode": "dev-flow",
            "kind": kind,
            "ws_url": f"/api/flow/{run_id}/ws",
            "state_ws_url": f"/api/flow/{run_id}/ws?view=state",
            "bundle_url": f"/api/flow/{run_id}/bundle",
            "gate_resolve_url": f"/api/flow/{run_id}/gates/{{gate_id}}/resolve",
        }
    )


async def handle_resolve_gate(request: web.Request) -> web.Response:
    """``POST /api/flow/{run_id}/gates/{gate_id}/resolve`` — the HITL write path.

    This is the route ``server.py`` never mounts, and the reason the dev
    console's Open-Questions panel can actually answer a gate.

    Of the two options the spec allows, this console mounts **only** the
    ``/api/flow``-prefixed alias (not ``register_command_routes``'s
    ``/runs/{run_id}/...`` pair), so every console route lives under one
    prefix and ``handle_cancel`` stays the single cancel entry point. The
    alias is a pure delegation to the library handler, so the body contract
    (``ResolveGateRequest``, including FEAT-412's ``answers``) and every
    status code are identical — 200 / 400 ``invalid_body`` / 400
    ``answers_required`` / 404 / 409. The template is published to the UI as
    ``gate_resolve_url_template`` in ``/api/config``.

    The handler resolves the runner from ``app["dev_loop_runner"]``, which
    ``_on_startup`` binds.
    """
    return await resolve_gate_handler(request)


# ---------------------------------------------------------------------------
# Startup / app
# ---------------------------------------------------------------------------


def _build_optional_jira_toolkit() -> Any | None:
    """Build a ``JiraToolkit`` only when Jira is actually configured.

    dev-flow Jira is link-only and entirely optional (spec §1 Non-Goals), so
    a missing/incomplete ``JIRA_*`` environment must NOT fail startup — it
    degrades to ``None``, which makes every Jira seam a no-op.

    Returns:
        The toolkit, or ``None`` when Jira is unconfigured or unbuildable.
    """
    if not (conf.config.get("JIRA_INSTANCE") and conf.config.get("JIRA_USERNAME")):
        logger.info(
            "JIRA_* not configured — dev-flow runs with jira_toolkit=None " "(Jira is link-only and optional here)."
        )
        return None
    try:
        return ops_server._build_jira_toolkit()
    except Exception as exc:  # noqa: BLE001 - Jira is optional in dev-flow
        logger.warning("JiraToolkit unavailable (%s) — continuing without Jira.", exc)
        return None


async def _on_startup(app: web.Application) -> None:
    """Wire the dev-flow: dispatchers, reviewers, pool, flow, runner.

    Mirrors ``server.py::_on_startup`` minus ``_build_log_toolkits()`` and
    minus the bug/feature dual-flow build.
    """
    redis_url = app["redis_url"]
    app["redis"] = aioredis.from_url(redis_url, decode_responses=True)

    dispatcher = ClaudeCodeDispatcher(
        max_concurrent=conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES,
        redis_url=redis_url,
        stream_ttl_seconds=conf.FLOW_STREAM_TTL_SECONDS,
    )

    # -- development backend selection (same cascade as the ops console) --
    development_dispatcher: object = dispatcher
    development_agent = conf.config.get("DEV_LOOP_DEVELOPMENT_AGENT", fallback="claude-code").strip().lower()
    env_map = ops_server._DEVELOPMENT_AGENT_MAX_CONCURRENT_ENV
    if development_agent in {"claude", "claude-code"}:
        pass
    elif development_agent in env_map or development_agent == "llm":
        backend = "nvidia" if development_agent == "llm" else development_agent
        development_dispatcher, development_profile = build_dispatcher(
            DevAgentSpec(agent=backend),
            redis_url=redis_url,
            max_concurrent=conf.config.getint(
                env_map[backend],
                fallback=conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES,
            ),
            stream_ttl_seconds=conf.FLOW_STREAM_TTL_SECONDS,
        )
        ops_server._log_development_agent_selection(backend, development_profile)
        # NOTE: like feature-mode (`build_dev_loop_feature_flow`), the dev-flow
        # builder takes no `development_dispatcher`/`development_profile`, so
        # this selection currently applies to the code-review reviewer
        # resolution below, not to DevelopmentNode's own dispatches. Pin the
        # backend per run from the console's "Agents & models" tab instead.
        logger.info(
            "DEV_LOOP_DEVELOPMENT_AGENT=%r selected; dev-flow dispatches "
            "development through the shared claude-code dispatcher unless a "
            "pool is declared per run.",
            development_agent,
        )
    else:
        raise RuntimeError(
            "DEV_LOOP_DEVELOPMENT_AGENT must be 'claude-code', 'codex', "
            "'gemini', 'nvidia', 'grok', 'zai', or 'moonshot', "
            f"got {development_agent!r}"
        )

    # -- QA review: the judge panel is dev-flow's default review gate ----
    _, codereview_agent_key = ops_server._resolve_codereview_dispatcher(
        dispatcher=dispatcher,
        development_dispatcher=development_dispatcher,
        redis_url=redis_url,
    )
    judge_panel_dispatcher = ops_server._build_judge_panel_dispatcher(redis_url=redis_url)

    repos = parse_repo_specs(conf.DEV_LOOP_REPOS)
    if repos:
        logger.info(
            "DEV_LOOP_REPOS configured: %d repo(s) — primary alias=%r",
            len(repos),
            repos[0].alias,
        )

    # -- dev-agent pool (FEAT-323) ---------------------------------------
    development_pool_config = parse_pool_env(conf.config.get)
    development_pool_max = resolve_pool_max(conf.config.get)
    development_dispatcher_builder = functools.partial(
        build_dispatcher,
        redis_url=redis_url,
        max_concurrent=conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES,
        stream_ttl_seconds=conf.FLOW_STREAM_TTL_SECONDS,
    )
    if development_pool_config is not None:
        # Honest reporting: dev-flow sizes the pool the way feature-mode does —
        # PlannerNode derives it from the first task-dependency wave (capped at
        # development_pool_max), or the brief's own `dev_agents` overrides it.
        # `build_dev_flow` deliberately takes no `development_pool_config`
        # (its signature mirrors build_dev_loop_feature_flow), so this env
        # value is NOT injected into DevelopmentNode here.
        logger.info(
            "DEV_LOOP_DEV_AGENTS is set (%s, isolation=%s) but dev-flow does "
            "NOT inject it: the pool is planner-sized (cap pool_max=%d) or set "
            "per run via the brief's dev_agents. Use the console's "
            "'Agents & models' tab to pin a pool for a run.",
            ", ".join(f"{spec.agent}x{spec.count}" for spec in development_pool_config.agents),
            development_pool_config.isolation_mode,
            development_pool_max,
        )

    graph_memory = await DevLoopGraphMemory.from_config()
    wiki_search = DevLoopWikiSearch.from_project()
    app["wiki_search"] = wiki_search

    jira_toolkit = _build_optional_jira_toolkit()
    app["jira_toolkit"] = jira_toolkit
    git_toolkit = ops_server._build_git_toolkit()
    wiki_toolkit = ops_server._build_wiki_toolkit()

    require_plan_approval = bool(getattr(conf, "DEV_LOOP_REQUIRE_PLAN_APPROVAL", False))
    skip_qa = bool(getattr(conf, "DEV_LOOP_SKIP_QA", False))

    # FEAT-480 (TASK-2628): same pattern as server.py's dev-loop wiring —
    # captured once as the exact kwargs `build_dev_flow` is called with, then
    # handed to `DevFlowRunner` as `dev_loop_flow_kwargs` (the attribute name
    # is generic across both workflows per `DevFlowRunner`'s inherited
    # `__init__`) so its checkpoint-recovery path builds a genuinely fresh,
    # checkpoint-enabled `AgentsFlow` per run instead of reusing `app["flow"]`.
    dev_loop_flow_kwargs: dict[str, Any] = {
        "dispatcher": dispatcher,
        "redis_url": redis_url,
        "jira_toolkit": jira_toolkit,
        "git_toolkit": git_toolkit,
        "wiki_toolkit": wiki_toolkit,
        "codereview_dispatcher": judge_panel_dispatcher,
        "development_dispatcher_builder": development_dispatcher_builder,
        "development_pool_max": development_pool_max,
        "graph_memory": graph_memory,
        "wiki_search": wiki_search,
        "skip_qa": skip_qa,
        "require_plan_approval": require_plan_approval,
        "name": "dev-flow-console",
    }
    app["flow"] = build_dev_flow(**dev_loop_flow_kwargs)
    runner = DevFlowRunner(
        app["flow"],
        dispatcher=dispatcher,
        jira_toolkit=jira_toolkit,
        git_toolkit=git_toolkit,
        wiki_toolkit=wiki_toolkit,
        redis_url=redis_url,
        codereview_dispatcher=judge_panel_dispatcher,
        graph_memory=graph_memory,
        # FEAT-480 (TASK-2628): see server.py's identical wiring note — each
        # `handle_run` request below mints its own stable per-job `run_id`
        # (never shared across jobs), and `checkpoint_store=None` resolves
        # through the existing env-fallback precedence.
        checkpoint_store=None,
        dev_loop_flow_kwargs=dev_loop_flow_kwargs,
    )

    app["runner"] = runner
    app["codereview_agent_key"] = codereview_agent_key
    app["development_pool_max"] = development_pool_max
    app["require_plan_approval"] = require_plan_approval
    app["flow_tasks"] = {}  # run_id -> asyncio.Task
    # The library's gate/cancel handlers read the runner from this key.
    app["dev_loop_runner"] = runner
    logger.info(
        "dev-flow ready: dev_intake → ideation → planner → development → "
        "synthesis → qa[judge-panel] → feature_handoff → close "
        "(max %d concurrent runs, ideation_max_rounds=%s)",
        runner.max_concurrent_runs,
        getattr(conf, "DEV_FLOW_IDEATION_MAX_ROUNDS", 2),
    )


def build_app(redis_url: str = "redis://localhost:6379/0") -> web.Application:
    """Build the dev console's aiohttp application."""
    app = web.Application()
    app["redis_url"] = redis_url
    app.on_startup.append(_on_startup)
    # Cleanup is mode-agnostic (cancel flow tasks + close Redis) — reused.
    app.on_cleanup.append(ops_server._on_cleanup)

    app.router.add_get("/", handle_index)
    app.router.add_static("/static/", STATIC_DIR, show_index=False)
    app.router.add_get("/api/config", handle_config)
    app.router.add_post("/api/flow/run", handle_run)
    # Bundle/replay/cancel are app-key driven and mode-agnostic — reused
    # verbatim from the ops console so the artifact contract stays identical.
    app.router.add_get("/api/flow/{run_id}/bundle", ops_server.handle_bundle)
    app.router.add_get("/api/flow/{run_id}/replay", ops_server.handle_replay)
    app.router.add_get("/api/flow/{run_id}/ws", flow_stream_ws)
    app.router.add_post("/api/flow/{run_id}/cancel", ops_server.handle_cancel)
    # THE HITL write path server.py never mounts — under /api/flow to match
    # the console's other routes.
    app.router.add_post("/api/flow/{run_id}/gates/{gate_id}/resolve", handle_resolve_gate)
    return app


def main() -> None:
    """Run the dev console (default port 8081, so it coexists with 8080)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8081"))
    app = build_app(redis_url=redis_url)
    logger.info("dev-flow console on http://%s:%s (Redis=%s)", host, port, redis_url)
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    main()
