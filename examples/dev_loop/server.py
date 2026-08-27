"""FEAT-129 / FEAT-250 / FEAT-253 / FEAT-377 / FEAT-378 — Dev-Loop demo server.

Hosts an aiohttp app that wires the **real** dev-loop topologies behind a
small HTTP/WebSocket API, plus a vanilla-JS console at ``/``:

* **bug mode** — the eight-node ``AgentsFlow`` (IntentClassifier →
  [BugIntake →] Research → Development → QA → DeploymentHandoff → Close,
  with a FailureHandler ``on_error`` fan-in).
* **feature mode** (FEAT-378) — the document-driven topology
  (IntentClassifier → Planner → Development → Synthesis → QA →
  FeatureHandoff → Close, with a FeedbackRouter on the QA-fail edge),
  selected by posting a brief with ``kind: "feature"``.

Adversarial code review is **mandatory** in this server (never optional):
bug-mode runs always get a ``parallel`` reviewer whose adversary is the
read-only Codex ``sdd-secondopinion`` seat, and feature-mode runs always
get a ``judge-panel`` containing a Codex judge — whatever
``DEV_LOOP_CODEREVIEW_AGENT`` / ``DEV_LOOP_JUDGE_PANEL`` say. See
:func:`_resolve_codereview_dispatcher` and :func:`_ensure_adversarial_judge`.

Endpoints:

* ``GET  /``                            — UI client (served from ``static/``)
* ``GET  /api/config``                  — LLM backend/model catalog + defaults
                                          the console renders its pickers from
* ``POST /api/flow/run``                — start a real flow run; the JSON body
                                          is either a work-brief form payload
                                          (bug/enhancement/new_feature) or a
                                          feature-brief form payload
                                          (``kind: "feature"``)
* ``GET  /api/flow/{run_id}/ws``        — WebSocket multiplexer
                                          (``parrot.flows.dev_loop.flow_stream_ws``);
                                          ``?view=both`` for the event log,
                                          ``?view=state`` for the authoritative
                                          session-state projection
* ``GET  /api/flow/{run_id}/replay``    — JSON dump of stored events for a run
* ``GET  /api/flow/{run_id}/bundle``    — the run bundle (FEAT-378 Module 8):
                                          ``?format=md`` (default) serves the
                                          markdown closing report, ``?format=json``
                                          the structured bundle, and
                                          ``?download=1`` forces an attachment

Runtime requirements:

* Redis on ``REDIS_URL`` (default ``redis://localhost:6379/0``)
* ``ANTHROPIC_API_KEY`` (or any provider key the Claude Agent SDK accepts)
* ``claude`` CLI on ``$PATH`` and authenticated
* Optional Codex Development mode:
  ``DEV_LOOP_DEVELOPMENT_AGENT=codex``, ``codex`` CLI on ``$PATH`` and
  authenticated (or ``OPENAI_API_KEY`` available), and
  ``DEV_LOOP_CODEX_MODEL`` (default ``gpt-5.5``)
* Optional Nvidia/LLM Development mode:
  ``DEV_LOOP_DEVELOPMENT_AGENT=nvidia`` and ``NVIDIA_API_KEY`` available.
  ``DEV_LOOP_NVIDIA_CODE_MODEL`` defaults to
  ``minimaxai/minimax-m3``; set it to ``z-ai/glm-5.2`` and
  ``DEV_LOOP_NVIDIA_ENABLE_THINKING=true`` for GLM reasoning mode.
* Jira service account: ``JIRA_INSTANCE``, ``JIRA_USERNAME``,
  ``JIRA_API_TOKEN`` and (optionally) ``JIRA_PROJECT`` — the toolkit uses
  ``basic_auth``
* AWS credentials (CloudWatch) and ``ELASTICSEARCH_URL`` if you want both
  log toolkits — set ``LOG_TOOLKITS`` (comma-separated) to limit.
* ``gh`` CLI authenticated for the DeploymentHandoff PR step

Repository targeting (FEAT-253):

* Set ``DEV_LOOP_REPOS`` (comma-separated or repeated) to declare one or
  more target repositories. Each entry is one of:

  - An ``owner/name`` slug:        ``phenobarbital/ai-parrot``
  - A full HTTPS clone URL:        ``https://github.com/phenobarbital/ai-parrot.git``
  - A full SSH clone URL:          ``git@github.com:phenobarbital/ai-parrot.git``
  - A JSON object string:
    ``{"alias":"ai-parrot","url":"git@github.com:phenobarbital/ai-parrot.git","branch":"dev","private":true}``

  The **primary** repo (first entry) is cloned/pulled into
  ``BASE_DIR/.claude/worktrees/repos/<run_id>/<alias>`` before the
  ``sdd-research`` dispatch; ``ResearchOutput.repo_path`` is set to that
  clone path and the per-run worktree is branched from the clone.

  When ``DEV_LOOP_REPOS`` is unset or empty the flow targets the local
  checkout at ``BASE_DIR`` (no clone; the ``sdd-research`` dispatch runs
  with ``cwd = WORKTREE_BASE_PATH`` and branches the worktree from
  ``BASE_DIR``).

  Private SSH repos require an SSH key/agent on the host. For ``gh``-based
  auth set ``GITHUB_TOKEN``.

Boot::

    docker run --rm -p 6379:6379 redis:7    # if you don't have one
    source .venv/bin/activate
    # Optional: target a specific repo
    # export DEV_LOOP_REPOS="git@github.com:phenobarbital/ai-parrot.git"
    python examples/dev_loop/server.py
    # http://localhost:8080
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import redis.asyncio as aioredis
from aiohttp import web

from parrot import conf
from parrot.flows.dev_loop import (
    GoogleCodingDispatcher,  # noqa: F401 - re-exported; test-patchable, see agent_builder
    GoogleCodingDispatchProfile,  # noqa: F401 - re-exported; test-patchable, see agent_builder
    BugBrief,
    ClaudeCodeDispatcher,
    CodexCodeDispatcher,
    CodexCodeDispatchProfile,  # noqa: F401 - re-exported; test-patchable, see agent_builder
    GeminiCodeDispatcher,
    GeminiCodeDispatchProfile,  # noqa: F401 - re-exported; test-patchable, see agent_builder
    LLMCodeDispatcher,  # noqa: F401 - re-exported; test-patchable, see agent_builder
    LLMCodeDispatchProfile,  # noqa: F401 - re-exported; test-patchable, see agent_builder
    GrokCodeDispatcher,  # noqa: F401 - re-exported; test-patchable, see agent_builder
    GrokCodeDispatchProfile,  # noqa: F401 - re-exported; test-patchable, see agent_builder
    MoonshotCodeDispatcher,  # noqa: F401 - re-exported; test-patchable, see agent_builder
    MoonshotCodeDispatchProfile,  # noqa: F401 - re-exported; test-patchable, see agent_builder
    ZaiCodeDispatcher,  # noqa: F401 - re-exported; test-patchable, see agent_builder
    ZaiCodeDispatchProfile,  # noqa: F401 - re-exported; test-patchable, see agent_builder
    DevLoopRunner,
    build_dev_loop_flow,
    flow_stream_ws,
    parse_repo_specs,
)
from parrot.flows.dev_loop.agent_builder import build_dispatcher, parse_pool_env, resolve_pool_max
from parrot.flows.dev_loop.code_review import CodeReviewDispatcherFactory
from parrot.flows.dev_loop.graph_memory import DevLoopGraphMemory
from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch
from parrot.flows.dev_loop.models import (
    DevAgentSpec,
    FeatureBrief,
    JudgePanelConfig,
    JudgeSpec,
)
from parrot.flows.dev_loop.runner import build_dev_loop_feature_flow
from parrot_tools.gittoolkit import GitToolkit
from parrot_tools.jiratoolkit import JiraToolkit

# The console's LLM catalog is a sibling module of this example, not a
# library import — make it resolvable whether the server is launched as a
# script (`python examples/dev_loop/server.py`, which already puts this
# directory on sys.path) or imported from elsewhere.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_catalog  # noqa: E402

logger = logging.getLogger("dev_loop.server")
STATIC_DIR = Path(__file__).parent / "static"
RUN_ARTIFACT_DIR = Path(conf.OUTPUT_DIR) / "dev_loop_runs"

# FEAT-323: per-backend max-concurrent env var, mirroring the original
# inline if/elif in ``_on_startup`` verbatim (Module 3 extraction).
_DEVELOPMENT_AGENT_MAX_CONCURRENT_ENV = {
    "codex": "CODEX_CODE_MAX_CONCURRENT_DISPATCHES",
    "gemini": "GEMINI_CODE_MAX_CONCURRENT_DISPATCHES",
    "nvidia": "LLM_CODE_MAX_CONCURRENT_DISPATCHES",
    "grok": "GROK_CODE_MAX_CONCURRENT_DISPATCHES",
    "zai": "ZAI_CODE_MAX_CONCURRENT_DISPATCHES",
    "moonshot": "MOONSHOT_CODE_MAX_CONCURRENT_DISPATCHES",
    "google_coding": "GOOGLE_CODING_MAX_CONCURRENT_DISPATCHES",
}


def _log_development_agent_selection(backend: str, profile: Any) -> None:
    """Log the Development node's dispatcher selection.

    Mirrors the exact log messages/args the pre-FEAT-323 inline if/elif
    block emitted per backend, so the single-agent path stays observably
    unchanged after the Module 3 builder extraction.

    Args:
        backend: The resolved ``DevAgentBackend`` (``"llm"`` normalized to
            ``"nvidia"`` by the caller).
        profile: The dispatch profile returned by ``build_dispatcher``.
    """
    if backend == "codex":
        logger.info("Development node using Codex CLI (model=%s)", profile.model)
    elif backend == "gemini":
        logger.info("Development node using Gemini CLI (model=%s)", profile.model)
    elif backend == "nvidia":
        logger.info(
            "Development node using Nvidia LLM code dispatcher (llm=%s)",
            profile.llm,
        )
    elif backend == "grok":
        logger.info(
            "Development node using Grok code dispatcher (model=%s)",
            profile.model,
        )
    elif backend == "zai":
        logger.info(
            "Development node using Z.ai code dispatcher (model=%s, thinking=%s)",
            profile.model,
            profile.enable_thinking,
        )
    elif backend == "moonshot":
        logger.info(
            "Development node using Moonshot code dispatcher (model=%s, "
            "reasoning_effort=%s)",
            profile.model,
            profile.reasoning_effort,
        )
    elif backend == "google_coding":
        logger.info("Development node using google_coding CLI (model=%s)", profile.model)


def _build_codex_adversarial_reviewer(codex_dispatcher: CodexCodeDispatcher) -> object:
    """Build the ``codex-adversarial`` reviewer, validating scope wiring (FEAT-375).

    Code-review fix: previously, ``DEV_LOOP_ADVERSARIAL_SCOPE=base``/``commit``
    had no way to actually supply the review target — ``review_base``/
    ``review_commit`` were never passed through, so the dispatcher's
    ``_build_review_scope_args()`` deterministically raised at DISPATCH time,
    which the degrade-on-infra-error wrapper silently turned into a
    passing-but-unreviewed verdict, every single run. Rather than let a
    foreseeable misconfiguration masquerade as an infra fluke, fail loudly
    here at server startup instead.

    Args:
        codex_dispatcher: The (possibly shared) ``CodexCodeDispatcher`` to wrap.

    Returns:
        The registered ``codex-adversarial`` reviewer.

    Raises:
        RuntimeError: ``DEV_LOOP_ADVERSARIAL_SCOPE="base"`` without
            ``DEV_LOOP_ADVERSARIAL_BASE_REF`` configured, or
            ``DEV_LOOP_ADVERSARIAL_SCOPE="commit"`` (not supported for this
            static server wiring — a commit SHA is inherently per-run, not a
            persistent setting).
    """
    scope = conf.DEV_LOOP_ADVERSARIAL_SCOPE.strip().lower()
    if scope == "commit":
        raise RuntimeError(
            "DEV_LOOP_ADVERSARIAL_SCOPE='commit' is not supported by this "
            "server's static reviewer wiring — a commit SHA is inherently "
            "per-run, not a persistent setting. Use 'uncommitted' (default) "
            "or 'base' with DEV_LOOP_ADVERSARIAL_BASE_REF set, or drive "
            "'commit' scope via a programmatic "
            "CodexAdversarialReviewDispatcher(review_scope='commit', "
            "review_commit=<sha>) construction outside this bootstrap."
        )
    if scope == "base" and not conf.DEV_LOOP_ADVERSARIAL_BASE_REF:
        raise RuntimeError(
            "DEV_LOOP_ADVERSARIAL_SCOPE='base' requires "
            "DEV_LOOP_ADVERSARIAL_BASE_REF to be set (e.g. 'dev' or "
            "'origin/main') — otherwise every adversarial review would "
            "silently degrade to an unreviewed pass."
        )
    return CodeReviewDispatcherFactory.create(
        "codex-adversarial",
        dispatcher=codex_dispatcher,
        model=conf.DEV_LOOP_ADVERSARIAL_MODEL,
        review_scope=conf.DEV_LOOP_ADVERSARIAL_SCOPE,
        review_base=conf.DEV_LOOP_ADVERSARIAL_BASE_REF if scope == "base" else "",
    )


def _build_nova_adversarial_reviewer() -> object:
    """Build the ``nova-adversarial`` reviewer (FEAT-405 Module 5).

    Mirrors :func:`_build_codex_adversarial_reviewer`'s scope-misconfiguration
    guards (fail loudly at startup rather than let a foreseeable
    misconfiguration degrade to a silent unreviewed pass), but needs no
    underlying CLI dispatcher — ``NovaAdversarialReviewDispatcher`` drives
    ``NovaClient.ask()`` directly.

    Returns:
        The registered ``nova-adversarial`` reviewer.

    Raises:
        RuntimeError: Same conditions as
            :func:`_build_codex_adversarial_reviewer`.
    """
    scope = conf.DEV_LOOP_ADVERSARIAL_SCOPE.strip().lower()
    if scope == "commit":
        raise RuntimeError(
            "DEV_LOOP_ADVERSARIAL_SCOPE='commit' is not supported by this "
            "server's static reviewer wiring — a commit SHA is inherently "
            "per-run, not a persistent setting. Use 'uncommitted' (default) "
            "or 'base' with DEV_LOOP_ADVERSARIAL_BASE_REF set, or drive "
            "'commit' scope via a programmatic "
            "NovaAdversarialReviewDispatcher(review_scope='commit', "
            "review_commit=<sha>) construction outside this bootstrap."
        )
    if scope == "base" and not conf.DEV_LOOP_ADVERSARIAL_BASE_REF:
        raise RuntimeError(
            "DEV_LOOP_ADVERSARIAL_SCOPE='base' requires "
            "DEV_LOOP_ADVERSARIAL_BASE_REF to be set (e.g. 'dev' or "
            "'origin/main') — otherwise every adversarial review would "
            "silently degrade to an unreviewed pass."
        )
    return CodeReviewDispatcherFactory.create(
        "nova-adversarial",
        model=conf.DEV_LOOP_NOVA_REVIEW_MODEL,
        review_scope=conf.DEV_LOOP_ADVERSARIAL_SCOPE,
        review_base=conf.DEV_LOOP_ADVERSARIAL_BASE_REF if scope == "base" else "",
    )


def _build_adversarial_reviewer(
    codex_dispatcher: CodexCodeDispatcher,
) -> tuple[object, str]:
    """Build the adversarial reviewer for whichever backend is configured.

    FEAT-405 Module 5: ``DEV_LOOP_ADVERSARIAL_BACKEND`` (resolved via
    :func:`llm_catalog.resolve_adversarial_backend`) selects ``codex``
    (default — [R3]: unset config is byte-identical to before FEAT-405) or
    ``nova``. Renamed/generalized from the FEAT-375 codex-only adversarial
    builder to make the backend selectable, per spec §5 "The adversarial
    reviewer is selectable over {codex, nova}".

    Args:
        codex_dispatcher: The (possibly shared) ``CodexCodeDispatcher`` —
            only actually used when the resolved backend is ``codex``.

    Returns:
        A ``(reviewer, agent_key)`` pair; ``agent_key`` is the
        ``CodeReviewDispatcherFactory`` registration name of whichever
        reviewer was actually built (``"codex-adversarial"`` or
        ``"nova-adversarial"``).
    """
    if llm_catalog.resolve_adversarial_backend() == "nova":
        return _build_nova_adversarial_reviewer(), "nova-adversarial"
    return _build_codex_adversarial_reviewer(codex_dispatcher), "codex-adversarial"


def _ensure_adversarial_judge(judges: list[JudgeSpec]) -> list[JudgeSpec]:
    """Guarantee a Codex seat in a feature-mode judge panel.

    The adversarial review is not optional in this server. In feature
    mode the adversary is a *judge*: ``JudgePanelReviewDispatcher`` maps
    the ``"codex"`` backend to :class:`CodexAdversarialReviewDispatcher`,
    the read-only ``sdd-secondopinion`` reviewer. A panel without a Codex
    judge is therefore a panel with no adversarial perspective, so one is
    appended rather than rejected — the operator's other judges are kept
    intact.

    Args:
        judges: The panel as configured (brief override, or
            ``DEV_LOOP_JUDGE_PANEL`` / ``default_judge_panel()``).

    Returns:
        The same list when it already holds a Codex judge, otherwise a
        copy with one appended.
    """
    if any(j.agent == llm_catalog.ADVERSARIAL_BACKEND for j in judges):
        return judges
    logger.warning(
        "Judge panel had no %r judge — appending the mandatory adversarial "
        "seat (model=%s). Adversarial review is not optional in this server.",
        llm_catalog.ADVERSARIAL_BACKEND,
        conf.DEV_LOOP_ADVERSARIAL_MODEL,
    )
    return [
        *judges,
        JudgeSpec(
            agent=llm_catalog.ADVERSARIAL_BACKEND,
            model=conf.DEV_LOOP_ADVERSARIAL_MODEL,
        ),
    ]


def _codex_dispatcher_for(
    development_dispatcher: object, redis_url: str
) -> CodexCodeDispatcher:
    """Reuse the development Codex dispatcher, or build a dedicated one.

    Avoids a second CLI-spawning dispatcher instance when the Development
    node already runs on Codex (the FEAT-270 reuse pattern).

    Args:
        development_dispatcher: The dispatcher wired into DevelopmentNode.
        redis_url: Redis URL for a freshly-built dispatcher.

    Returns:
        A :class:`CodexCodeDispatcher` suitable for the adversarial seat.
    """
    if isinstance(development_dispatcher, CodexCodeDispatcher):
        return development_dispatcher
    return CodexCodeDispatcher(
        max_concurrent=conf.config.getint(
            "CODEX_CODE_MAX_CONCURRENT_DISPATCHES",
            fallback=conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES,
        ),
        redis_url=redis_url,
        stream_ttl_seconds=conf.FLOW_STREAM_TTL_SECONDS,
    )


def _build_primary_reviewer(
    agent: str, *, dispatcher: object, development_dispatcher: object, redis_url: str
) -> object:
    """Build the write-enabled primary reviewer for ``agent`` (FEAT-270).

    Args:
        agent: ``"claude-code"``, ``"codex"`` or ``"gemini"``.
        dispatcher: The shared ``ClaudeCodeDispatcher``.
        development_dispatcher: DevelopmentNode's dispatcher, reused when
            its backend matches ``agent``.
        redis_url: Redis URL for any dispatcher built here.

    Returns:
        The registered primary review dispatcher.

    Raises:
        RuntimeError: If ``agent`` has no primary-review mapping.
    """
    if agent in {"claude", "claude-code"}:
        return CodeReviewDispatcherFactory.create("claude-code", dispatcher=dispatcher)
    if agent == "codex":
        return CodeReviewDispatcherFactory.create(
            "codex",
            dispatcher=_codex_dispatcher_for(development_dispatcher, redis_url),
        )
    if agent == "gemini":
        underlying = (
            development_dispatcher
            if isinstance(development_dispatcher, GeminiCodeDispatcher)
            else GeminiCodeDispatcher(
                max_concurrent=conf.config.getint(
                    "GEMINI_CODE_MAX_CONCURRENT_DISPATCHES",
                    fallback=conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES,
                ),
                redis_url=redis_url,
                stream_ttl_seconds=conf.FLOW_STREAM_TTL_SECONDS,
            )
        )
        return CodeReviewDispatcherFactory.create("gemini", dispatcher=underlying)
    if agent == "google_coding":
        underlying = (
            development_dispatcher
            if isinstance(development_dispatcher, GoogleCodingDispatcher)
            else GoogleCodingDispatcher(
                max_concurrent=conf.config.getint(
                    "GOOGLE_CODING_MAX_CONCURRENT_DISPATCHES",
                    fallback=conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES,
                ),
                redis_url=redis_url,
                stream_ttl_seconds=conf.FLOW_STREAM_TTL_SECONDS,
            )
        )
        return CodeReviewDispatcherFactory.create("google_coding", dispatcher=underlying)
    raise RuntimeError(
        "DEV_LOOP_CODEREVIEW_AGENT must be 'claude-code', 'codex', 'gemini', "
        f"'google_coding', 'codex-adversarial', or 'parallel', got {agent!r}"
    )


def _resolve_codereview_dispatcher(
    *, dispatcher: object, development_dispatcher: object, redis_url: str
) -> tuple[object, str]:
    """Build the QA node's code-review dispatcher, adversary included.

    **Adversarial review is not optional in this server.** Of the five
    registered reviewers only ``codex-adversarial`` and ``parallel``
    involve an adversarial seat; the three single-agent reviewers
    (``claude-code``/``codex``/``gemini``) do not. Rather than reject
    those three — which would make the common default
    (``DEV_LOOP_CODEREVIEW_AGENT=claude-code``) un-runnable — this
    function *upgrades* them: the configured agent stays the write-enabled
    primary, and a ``parallel`` reviewer pairs it with the adversary.

    FEAT-405 Module 5: the adversary itself is now backend-selectable
    (``DEV_LOOP_ADVERSARIAL_BACKEND`` — ``codex`` default or ``nova``, via
    :func:`_build_adversarial_reviewer`); the ``DEV_LOOP_CODEREVIEW_AGENT``
    mode string ``"codex-adversarial"`` still selects "advisory-only mode"
    regardless of which backend serves it (unchanged surface, [R3]).

    Args:
        dispatcher: The shared ``ClaudeCodeDispatcher``.
        development_dispatcher: DevelopmentNode's dispatcher (reused when
            the reviewer needs the same backend).
        redis_url: Redis URL for any dispatcher built here.

    Returns:
        A ``(dispatcher, agent_key)`` tuple; ``agent_key`` names the
        reviewer actually wired up, which may differ from the configured
        value when it was upgraded.

    Raises:
        RuntimeError: If ``DEV_LOOP_CODEREVIEW_AGENT`` is unknown, or the
            adversarial scope is misconfigured (see
            :func:`_build_adversarial_reviewer`).
    """
    configured = conf.config.get(
        "DEV_LOOP_CODEREVIEW_AGENT", fallback="parallel"
    ).strip().lower()

    adversary, adversary_key = _build_adversarial_reviewer(
        _codex_dispatcher_for(development_dispatcher, redis_url)
    )

    if configured == "codex-adversarial":
        # Advisory-only review: already adversarial, nothing to upgrade.
        return adversary, adversary_key

    primary_agent = "claude-code" if configured == "parallel" else configured
    primary = _build_primary_reviewer(
        primary_agent,
        dispatcher=dispatcher,
        development_dispatcher=development_dispatcher,
        redis_url=redis_url,
    )
    if configured != "parallel":
        logger.warning(
            "DEV_LOOP_CODEREVIEW_AGENT=%r has no adversarial perspective — "
            "upgrading to the 'parallel' reviewer (primary=%s + %s). "
            "Adversarial review is not optional in this server.",
            configured,
            primary_agent,
            adversary_key,
        )
    return (
        CodeReviewDispatcherFactory.create(
            "parallel",
            primary=primary,
            adversary=adversary,
            judge_enabled=conf.DEV_LOOP_CODEREVIEW_JUDGE,
            judge_dispatcher=dispatcher if conf.DEV_LOOP_CODEREVIEW_JUDGE else None,
        ),
        "parallel",
    )


def _build_judge_panel_dispatcher(
    *, redis_url: str, judges: Optional[list[JudgeSpec]] = None
) -> object:
    """Build the feature-mode ``judge-panel`` reviewer (FEAT-378 Module 4).

    Args:
        redis_url: Redis URL forwarded to every per-judge dispatcher.
        judges: Explicit panel (a per-run brief override). When ``None``
            the catalog resolves ``DEV_LOOP_JUDGE_PANEL`` /
            ``default_judge_panel()``.

    Returns:
        A ``JudgePanelReviewDispatcher`` whose panel always contains the
        mandatory Codex adversarial judge.
    """
    resolved = _ensure_adversarial_judge(
        judges
        if judges is not None
        else [
            JudgeSpec(**spec)
            for spec in llm_catalog.default_judge_panel_payload()
        ]
    )
    logger.info(
        "Feature-mode QA judge panel: %s",
        ", ".join(f"{j.agent}{f':{j.model}' if j.model else ''}" for j in resolved),
    )
    return CodeReviewDispatcherFactory.create(
        "judge-panel",
        judges=resolved,
        redis_url=redis_url,
        max_concurrent=conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES,
        stream_ttl_seconds=conf.FLOW_STREAM_TTL_SECONDS,
    )


# ---------------------------------------------------------------------------
# Toolkit wiring
# ---------------------------------------------------------------------------


def _build_jira_toolkit() -> JiraToolkit:
    """Service-account JiraToolkit (flow-bot, basic_auth).

    Declares the project's **workflow path** so ``jira_transition_to`` can
    walk multi-stage custom workflows. Jira's API only exposes the
    transitions available from an issue's *current* status, so a single hop
    cannot cross a chain like ``Backlog → Open → In Progress → Resolved →
    Closed`` — without a declared path the dev-loop's resolve/deploy
    transition silently falls back to one direct hop and fails. The path is
    read from ``JIRA_WORKFLOW_PATH_<PROJECT>`` (e.g. ``JIRA_WORKFLOW_PATH_NAV``)
    and defaults to ``DEV_LOOP_JIRA_WORKFLOW_PATH`` from ``conf``.
    Separators: ``>``, ``->`` or ``→``.
    """
    project = conf.config.get("JIRA_PROJECT") or "NAV"
    workflow_path = conf.config.get(
        f"JIRA_WORKFLOW_PATH_{project.upper()}",
        fallback=conf.DEV_LOOP_JIRA_WORKFLOW_PATH,
    )
    return JiraToolkit(
        server_url=conf.config.get("JIRA_INSTANCE"),
        auth_type="basic_auth",
        username=conf.config.get("JIRA_USERNAME"),
        password=conf.config.get("JIRA_API_TOKEN"),
        default_project=project,
        workflow_paths={project: workflow_path},
    )


def _build_git_toolkit() -> GitToolkit:
    """Build a GitToolkit for repo clone/pull operations (FEAT-253).

    Reads credentials from the environment:

    * ``GITHUB_TOKEN`` — personal access token (PAT) for private HTTPS
      repos or ``gh``-style auth; can be left unset when using SSH keys.
    * ``GIT_DEFAULT_BRANCH`` — default branch for clones (default: ``main``).

    For private SSH repos (``git@github.com:...``) ensure an SSH key/agent
    is configured on the host — ``GitToolkit`` passes the URL as-is to the
    ``git`` CLI and relies on the host's SSH configuration.
    """
    return GitToolkit(
        github_token=conf.config.get("GITHUB_TOKEN", fallback=None),
        default_branch=conf.config.get("GIT_DEFAULT_BRANCH", fallback="main"),
    )


def _build_pageindex_toolkit(wiki_dir: Path) -> object | None:
    """Build the ``PageIndexToolkit`` backing the wiki's authoring plane.

    ``LLMWikiToolkit.create_page`` writes to two planes: the WikiStore
    retrieval plane (always) and the PageIndex authoring plane (this
    toolkit). Passing ``None`` for the latter made every ``create_page``
    call raise ``AttributeError`` inside the toolkit's own best-effort
    ``except``, logging ``'NoneType' object has no attribute
    'insert_markdown'`` on every handed-off feature and falling back to a
    fabricated ``page-<slug>`` id instead of a real PageIndex node id.

    Mirrors the construction ``wikitoolkit ingest`` uses
    (``knowledge/wiki/cli.py``): one LLM client from the ``WIKI_MODEL``
    spec, wrapped in a :class:`PageIndexLLMAdapter`, over
    ``<wiki_dir>/pageindex``.

    Args:
        wiki_dir: The wiki's storage directory (``project.storage_path``).

    Returns:
        A ready ``PageIndexToolkit``, or ``None`` when no ``WIKI_MODEL`` is
        configured or construction fails — the caller then runs without an
        authoring plane, which ``create_page`` degrades on cleanly.
    """
    try:
        from navconfig import config as _nav

        model_spec = _nav.get("WIKI_MODEL", fallback=None)
    except Exception:  # noqa: BLE001 - navconfig optional; env is enough
        model_spec = os.environ.get("WIKI_MODEL")

    if not model_spec:
        logger.warning(
            "WIKI_MODEL is not configured — feature-handoff pages will be "
            "written to the WikiStore retrieval plane only, not the "
            "PageIndex authoring plane. Set WIKI_MODEL (format "
            "'provider:model', e.g. 'google:gemini-3.1-flash-lite-preview') "
            "to enable it."
        )
        return None

    try:
        from parrot.clients.factory import LLMFactory
        from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
        from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

        _, model_id = LLMFactory.parse_llm_string(model_spec)
        adapter = PageIndexLLMAdapter(LLMFactory.create(model_spec), model=model_id)
        pageindex_dir = Path(wiki_dir) / "pageindex"
        pageindex_dir.mkdir(parents=True, exist_ok=True)
        toolkit = PageIndexToolkit(adapter, storage_dir=pageindex_dir)
        logger.info(
            "PageIndexToolkit ready (model=%s, storage=%s)",
            model_spec, pageindex_dir,
        )
        return toolkit
    except Exception as exc:  # noqa: BLE001 - authoring plane is best-effort
        logger.warning(
            "PageIndexToolkit unavailable (%s); feature-handoff pages will "
            "skip the authoring plane.", exc,
        )
        return None


def _build_wiki_toolkit() -> object | None:
    """Build the optional ``LLMWikiToolkit`` for feature-mode handoff.

    ``FeatureHandoffNode`` ingests its ``docs/features/…`` artifact as a
    wiki page so the finished work is queryable by ``wikitoolkit query``.
    That ingest is explicitly degradable (spec §7: "wiki uninitialized →
    skipped with warning, does not block the PR"), and it is gated on
    ``DEV_LOOP_WIKI_PAGE_INGEST``, so every failure path here returns
    ``None`` rather than refusing to boot the server.

    Returns:
        A wired ``LLMWikiToolkit``, or ``None`` when the ingest is
        disabled or the toolkit cannot be constructed.
    """
    if not conf.DEV_LOOP_WIKI_PAGE_INGEST:
        logger.info(
            "DEV_LOOP_WIKI_PAGE_INGEST is off — feature handoff will skip "
            "the wiki page ingest."
        )
        return None
    try:
        from pathlib import Path

        from parrot.knowledge.wiki.models import WikiConfig
        from parrot.knowledge.wiki.project import (
            find_project_root,
            load_project_config,
        )
        from parrot.knowledge.wiki.toolkit import LLMWikiToolkit

        root = find_project_root(Path.cwd())
        project = load_project_config(root)          # reads .parrot/wiki.json
        wiki_config = WikiConfig(
            wiki_name=project.wiki_name,
            storage_dir=project.storage_path(root),
            storage_backend=project.backend,
            # The GraphIndex mirror needs a real graphindex_toolkit; with
            # None it would only warn on every ingest, so keep it off.
            sync_graph=False,
        )
        pageindex_toolkit = _build_pageindex_toolkit(project.storage_path(root))
        toolkit = LLMWikiToolkit(
            pageindex_toolkit, None, None, wiki_config, agent_id="dev-loop"
        )
        logger.info(
            "LLMWikiToolkit ready for feature-mode docs ingest "
            "(wiki=%s, store=%s, pageindex=%s)",
            project.wiki_name, project.storage_path(root),
            "on" if pageindex_toolkit is not None else "off",
        )
        return toolkit
    except Exception as exc:  # noqa: BLE001 - wiki ingest is best-effort
        logger.warning(
            "LLMWikiToolkit unavailable (%s); feature handoff will skip the "
            "wiki page ingest.", exc,
        )
        return None


def _build_log_toolkits() -> dict[str, object]:
    """Real-mode log toolkits.

    The CloudWatch toolkit is configured with a fixed ``aws_id`` profile
    and ``default_log_group`` per project policy — the per-source log
    group from each :class:`LogSource` is no longer forwarded as a
    per-query kwarg.

    CloudWatch is optional: when AWS credentials are missing the server
    starts without log-fetching capability and ResearchNode gracefully
    skips the ``cloudwatch`` source.

    ``DEV_LOOP_CLOUDWATCH_ENABLED=false`` short-circuits before the import,
    so a local run never touches botocore or an AWS profile at all.
    """
    if not conf.DEV_LOOP_CLOUDWATCH_ENABLED:
        logger.info(
            "CloudWatch disabled (DEV_LOOP_CLOUDWATCH_ENABLED=false) — bug "
            "runs will triage from inline/attached log sources only."
        )
        return {}

    from parrot_tools.aws.cloudwatch import CloudWatchToolkit

    aws_id = conf.config.get("AWS_PROFILE", fallback="cloudwatch")
    log_group = conf.config.get("CLOUDWATCH_LOG_GROUP", fallback="fluent-bit-cloudwatch")
    toolkits: dict[str, object] = {}
    try:
        toolkits["cloudwatch"] = CloudWatchToolkit(
            aws_id=aws_id,
            default_log_group=log_group,
        )
        logger.info(
            "CloudWatch toolkit ready (profile=%s, log_group=%s)",
            aws_id,
            log_group,
        )
    except (ValueError, ImportError) as exc:
        logger.warning(
            "CloudWatch toolkit disabled — missing credentials or "
            "dependency (%s). Log-fetching will be unavailable.",
            exc,
        )
    return toolkits


# ---------------------------------------------------------------------------
# BugBrief / WorkBrief construction from form payload
# ---------------------------------------------------------------------------


_ALLOWED_SHELL_HEADS = {
    "task",
    "flowtask",
    "pytest",
    "ruff",
    "mypy",
    "pylint",
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
                                 to ``CLOUDWATCH_LOG_GROUP``. Only used when
                                 ``kind == "bug"`` — non-bug runs get an
                                 empty ``log_sources`` list.
    * ``time_window_minutes``  — CloudWatch lookback window (default 60).
    * ``skip_cloudwatch``      — truthy to attach NO CloudWatch source to a
                                 bug run (local reproduction, no AWS profile).
                                 The server-wide equivalent is
                                 ``DEV_LOOP_CLOUDWATCH_ENABLED=false``.
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
        logger.warning("Unknown kind %r submitted; defaulting to 'bug'", raw_kind)
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

    log_group = form.get("log_group") or conf.config.get("CLOUDWATCH_LOG_GROUP", fallback="fluent-bit-cloudwatch")
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
    reporter = form.get("reporter") or conf.config.get("JIRA_REPORTER_ACCOUNT_ID", fallback=bot_account)
    escalation = form.get("escalation_assignee") or conf.config.get("JIRA_ESCALATION_ACCOUNT_ID", fallback=bot_account)
    if not reporter or not escalation:
        raise ValueError(
            "reporter and escalation_assignee are required; set "
            "FLOW_BOT_JIRA_ACCOUNT_ID, JIRA_REPORTER_ACCOUNT_ID and "
            "JIRA_ESCALATION_ACCOUNT_ID in the environment, or pass them "
            "in the form payload."
        )

    # CloudWatch is a bug-triage affordance: only a defect run has an
    # incident whose logs are worth pulling. Enhancement / new-feature runs
    # get no remote log source at all, so ResearchNode never issues a
    # StartQuery for them. ``DEV_LOOP_LOG_FETCH_MODE`` is the node-side
    # backstop for briefs built elsewhere (API clients, quickstart, tests).
    #
    # Two ways a bug run opts out of CloudWatch as well: the server-wide
    # DEV_LOOP_CLOUDWATCH_ENABLED=false kill switch, and the per-run
    # `skip_cloudwatch` toggle for a local reproduction where the incident
    # is in front of you and an AWS query is only latency. Either one leaves
    # `log_sources` empty, so ResearchNode never issues a StartQuery.
    skip_cloudwatch = bool(form.get("skip_cloudwatch", False))
    cloudwatch_available = bool(conf.DEV_LOOP_CLOUDWATCH_ENABLED)
    log_sources: list[dict[str, Any]] = []
    if raw_kind == "bug" and cloudwatch_available and not skip_cloudwatch:
        log_sources.append(
            {
                "kind": "cloudwatch",
                "locator": log_group,
                "time_window_minutes": window,
            }
        )
    elif raw_kind == "bug":
        logger.info(
            "Bug run without a CloudWatch source (skip_cloudwatch=%s, "
            "DEV_LOOP_CLOUDWATCH_ENABLED=%s) — research triages from the "
            "description and the codebase only.",
            skip_cloudwatch, cloudwatch_available,
        )

    payload: dict[str, Any] = {
        "kind": raw_kind,  # FEAT-132
        "summary": summary,
        "description": description,
        "affected_component": component,
        "log_sources": log_sources,
        "acceptance_criteria": criteria,
        "reporter": reporter,
        "escalation_assignee": escalation,
    }
    existing = (form.get("existing_issue_key") or "").strip()
    if existing:
        payload["existing_issue_key"] = existing

    # FEAT-323: per-run dev-agent pool override. Absent → the flow's own
    # cascade (env pool, then single-agent) decides, exactly as before.
    dev_agents = _parse_dev_agents(form.get("dev_agents"))
    if dev_agents:
        payload["dev_agents"] = dev_agents
        isolation = (form.get("dev_isolation") or "").strip().lower()
        if isolation in {"shared", "isolated"}:
            payload["dev_isolation"] = isolation

    # FEAT-466 TASK-2508: per-run flow-type/base-branch override.
    _apply_flow_override(payload, form)
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
            out.append(
                {
                    "kind": "shell",
                    "name": f"{head}-criterion-{idx}",
                    "command": cmd,
                }
            )
        else:
            out.append(
                {
                    "kind": "manual",
                    "name": f"manual-criterion-{idx}",
                    "text": line,
                }
            )
    return out


_FLOW_TYPES = {"feature", "hotfix"}


def _apply_flow_override(payload: dict[str, Any], form: dict[str, Any]) -> None:
    """Parse the console's flow-type/base-branch override into ``payload``.

    FEAT-466 TASK-2508: mirrors the ``dev_isolation`` validation idiom
    verbatim — read, normalise, validate against a literal set, add only on
    success. ``flow_type`` is a closed set and is rejected (omitted) when
    invalid rather than passed to pydantic; ``base_branch`` is deliberately
    open (CLAUDE.md allows sub-feature branches as a base), so any non-empty
    string is accepted and left to ``resolve_flow``/``FlowMeta`` to reject an
    invalid *combination*. The console's ``"auto"`` sentinel must never reach
    here — both consoles omit the key entirely instead of sending ``"auto"``.

    Args:
        payload: The brief payload dict being built; mutated in place.
        form: The raw decoded form/JSON body.
    """
    flow_type = (form.get("flow_type") or "").strip().lower()
    if flow_type in _FLOW_TYPES:
        payload["flow_type"] = flow_type

    base_branch = (form.get("base_branch") or "").strip()
    if base_branch:
        payload["base_branch"] = base_branch


def _parse_dev_agents(raw: Any) -> Optional[list[DevAgentSpec]]:
    """Translate the UI's dev-agent rows into ``DevAgentSpec`` objects.

    Args:
        raw: A list of ``{"agent": str, "model": str, "count": int}``
            dicts (the console's "Agents & models" tab), or anything else
            — non-lists and empty lists both mean "no override".

    Returns:
        The parsed specs, or ``None`` when no pool was declared (which
        leaves the library's own cascade — brief → env → single-agent —
        untouched).

    Raises:
        ValueError: If a row names a backend the dev-loop cannot build.
    """
    if not isinstance(raw, list) or not raw:
        return None
    specs: list[DevAgentSpec] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        agent = str(row.get("agent") or "").strip()
        if not agent:
            continue
        if llm_catalog.get_backend(agent) is None:
            raise ValueError(
                f"unknown dev agent backend {agent!r} — supported: "
                f"{', '.join(b.id for b in llm_catalog.BACKENDS)}"
            )
        specs.append(
            DevAgentSpec(
                agent=agent,
                model=str(row.get("model") or "").strip(),
                count=max(1, int(row.get("count") or 1)),
            )
        )
    return specs or None


def _parse_judge_panel(raw: Any) -> Optional[list[JudgeSpec]]:
    """Translate the UI's judge rows into ``JudgeSpec`` objects.

    Args:
        raw: A list of ``{"agent": str, "model": str}`` dicts, or anything
            else (meaning "use the configured default panel").

    Returns:
        The parsed judges, or ``None`` when none were declared.

    Raises:
        ValueError: If a row names a backend with no review dispatcher —
            ``JudgePanelReviewDispatcher`` supports only claude-code,
            codex and gemini.
    """
    if not isinstance(raw, list) or not raw:
        return None
    judges: list[JudgeSpec] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        agent = str(row.get("agent") or "").strip()
        if not agent:
            continue
        if agent not in llm_catalog.JUDGE_BACKENDS:
            raise ValueError(
                f"backend {agent!r} cannot serve as a QA judge — supported: "
                f"{', '.join(llm_catalog.JUDGE_BACKENDS)}"
            )
        judges.append(JudgeSpec(agent=agent, model=str(row.get("model") or "").strip()))
    return judges or None


def _build_feature_brief_from_form(form: dict[str, Any]) -> FeatureBrief:
    """Translate the console's feature-mode form into a ``FeatureBrief``.

    Feature-mode intake is document-driven: instead of a summary plus log
    sources plus executable criteria, the run points at an existing SDD
    markdown (brainstorm, proposal or already-resolved spec) and lets
    ``PlannerNode`` generate whatever is still missing.

    Required form fields:

    * ``document_path`` — path to the driving markdown. Validated eagerly
      by ``FeatureBrief`` itself (must exist and be readable), so a typo
      fails here rather than after a dispatch has been spent.
    * ``document_kind`` — ``brainstorm`` | ``proposal`` | ``spec``.

    Optional form fields:

    * ``jira_issue_key`` — feature-mode never *creates* a ticket; when
      set, downstream nodes only link/transition/comment on it.
    * ``dev_agents`` — explicit dev-agent pool rows; when omitted the
      planner sizes the pool from the first ``TaskScheduler`` wave.
    * ``judge_panel`` — explicit QA judge rows; the mandatory Codex
      adversarial seat is appended later regardless
      (:func:`_ensure_adversarial_judge`).

    Args:
        form: The decoded JSON body posted by the console.

    Returns:
        The validated :class:`FeatureBrief`.

    Raises:
        ValueError: On a missing/unreadable document, an unknown backend,
            or an incoherent document kind (raised by the model's own
            validators).
    """
    document_path = (form.get("document_path") or "").strip()
    if not document_path:
        raise ValueError(
            "document_path is required in feature mode — point it at the "
            "brainstorm, proposal or spec markdown that drives the run."
        )
    document_kind = (form.get("document_kind") or "").strip().lower()
    if document_kind not in {"brainstorm", "proposal", "spec"}:
        raise ValueError(
            "document_kind must be 'brainstorm', 'proposal' or 'spec', got "
            f"{document_kind!r}"
        )

    payload: dict[str, Any] = {
        "kind": "feature",
        "document_path": document_path,
        "document_kind": document_kind,
    }
    issue_key = (form.get("jira_issue_key") or "").strip()
    if issue_key:
        payload["jira_issue_key"] = issue_key
    dev_agents = _parse_dev_agents(form.get("dev_agents"))
    if dev_agents:
        payload["dev_agents"] = dev_agents
    judges = _parse_judge_panel(form.get("judge_panel"))
    if judges:
        payload["judge_panel"] = JudgePanelConfig(judges=judges)

    # FEAT-466 TASK-2508: same override parsing as the bug/work-brief path,
    # for consistency. NOTE: FeatureBrief.kind is a fixed Literal["feature"]
    # and the model does not declare `flow_type`/`base_branch` fields (out
    # of scope for this task — see FeatureBrief in models/base.py), so
    # Pydantic's default `extra="ignore"` silently drops these keys today;
    # they are parsed here only to keep both payload builders symmetric.
    _apply_flow_override(payload, form)
    return FeatureBrief.model_validate(payload)


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------


async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_config(request: web.Request) -> web.Response:
    """Serve the console's configuration catalog.

    The UI renders every ``<select>`` from this payload — LLM backends and
    their models per role, the resolved judge panel, the acceptance-criteria
    shell allowlist, and the operator-visible defaults — so the console
    never hardcodes what the server supports.
    """
    app = request.app
    return web.json_response(
        {
            **llm_catalog.catalog_payload(),
            "kinds": [
                {"value": "bug", "label": "Bug"},
                {"value": "enhancement", "label": "Enhancement"},
                {"value": "new_feature", "label": "New Feature"},
                {"value": "feature", "label": "Feature (SDD)"},
            ],
            "shell_criteria_heads": sorted(_ALLOWED_SHELL_HEADS),
            "document_kinds": ["brainstorm", "proposal", "spec"],
            "defaults": {
                "development_agent": conf.config.get(
                    "DEV_LOOP_DEVELOPMENT_AGENT", fallback="claude-code"
                ),
                "codereview_agent": app.get("codereview_agent_key", "parallel"),
                "codereview_agent_configured": conf.config.get(
                    "DEV_LOOP_CODEREVIEW_AGENT", fallback="parallel"
                ),
                "log_group": conf.config.get(
                    "CLOUDWATCH_LOG_GROUP", fallback="fluent-bit-cloudwatch"
                ),
                "time_window_minutes": 60,
                "cloudwatch_enabled": bool(conf.DEV_LOOP_CLOUDWATCH_ENABLED),
                "jira_project": conf.config.get("JIRA_PROJECT") or "NAV",
                "qa_max_retries": conf.DEV_LOOP_QA_MAX_RETRIES,
                "docs_artifact_dir": conf.DEV_LOOP_DOCS_ARTIFACT_DIR,
                "wiki_page_ingest": conf.DEV_LOOP_WIKI_PAGE_INGEST,
                "wiki_search": app.get("wiki_search") is not None,
                "skip_qa": bool(getattr(conf, "DEV_LOOP_SKIP_QA", False)),
                "development_pool_max": app.get("development_pool_max", 4),
                "max_concurrent_runs": getattr(
                    app.get("runner"), "max_concurrent_runs", None
                ),
            },
            "adversarial_review": {
                "mandatory": True,
                "scope": conf.DEV_LOOP_ADVERSARIAL_SCOPE,
                "base_ref": conf.DEV_LOOP_ADVERSARIAL_BASE_REF,
                "note": (
                    "Every run pairs the primary reviewer with the read-only "
                    "Codex sdd-secondopinion seat; feature-mode runs carry it "
                    "as a judge in the QA panel. It cannot be switched off."
                ),
            },
            "feature_mode": {
                "available": bool(app.get("feature_mode_available")),
                "reason": app.get("feature_mode_reason", ""),
            },
        }
    )


async def handle_run(request: web.Request) -> web.Response:
    """Start a real ``runner.run(...)`` invocation in either mode.

    The JSON body is a console form payload. ``kind`` selects the
    topology: ``"feature"`` builds a :class:`FeatureBrief` and runs the
    FEAT-378 document-driven flow; anything else builds a ``BugBrief``
    and runs the original bug/enhancement/new_feature topology. Both are
    dispatched through the same :class:`DevLoopRunner`, which routes on
    the brief's own type.
    """
    if not request.can_read_body:
        return web.json_response({"error": "JSON body required"}, status=400)
    try:
        form = await request.json()
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"error": f"invalid JSON: {exc}"}, status=400)
    if not isinstance(form, dict):
        return web.json_response({"error": "body must be a JSON object"}, status=400)

    is_feature = (form.get("kind") or "").strip().lower().replace(" ", "_") == "feature"
    if is_feature and not request.app.get("feature_mode_available"):
        return web.json_response(
            {
                "error": (
                    "feature mode is unavailable on this server: "
                    f"{request.app.get('feature_mode_reason') or 'not wired'}"
                )
            },
            status=409,
        )

    brief: Any
    try:
        if is_feature:
            brief = _build_feature_brief_from_form(form)
            initial_task = f"feature: {Path(brief.document_path).name}"
            label = brief.document_path
        else:
            brief = BugBrief.model_validate(_build_brief_from_form(form))
            initial_task = f"resolve: {brief.summary[:120]}"
            label = brief.summary
    except (ValueError, TypeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001 - validation surface
        return web.json_response({"error": str(exc)}, status=400)

    run_id = f"run-{uuid.uuid4().hex[:8]}"
    runner: DevLoopRunner = request.app["runner"]
    started_at = time.time()

    skip_qa = bool(form.get("skip_qa", False))
    skip_jira = bool(form.get("skip_jira", False))
    extra_shared: dict[str, Any] = {}
    if skip_qa:
        extra_shared["skip_qa"] = True
    if skip_jira:
        extra_shared["skip_jira"] = True

    async def _run() -> None:
        try:
            logger.info(
                "Starting %s flow run_id=%s (%s) skip_qa=%s skip_jira=%s",
                "FEATURE" if is_feature else "bug", run_id, label, skip_qa, skip_jira,
            )
            result = await runner.run(
                brief,
                run_id=run_id,
                initial_task=initial_task,
                extra_shared=extra_shared or None,
            )
            logger.info("Flow run_id=%s finished status=%s in %.1fs", run_id, result.status, time.time() - started_at)
        except Exception:
            logger.exception("Flow run_id=%s failed", run_id)

    task = asyncio.create_task(_run(), name=f"flow-run-{run_id}")
    request.app["flow_tasks"][run_id] = task
    task.add_done_callback(lambda t: request.app["flow_tasks"].pop(run_id, None))

    return web.json_response(
        {
            "run_id": run_id,
            "mode": "feature" if is_feature else "bug",
            "ws_url": f"/api/flow/{run_id}/ws",
            "state_ws_url": f"/api/flow/{run_id}/ws?view=state",
            "bundle_url": f"/api/flow/{run_id}/bundle",
        }
    )


async def handle_cancel(request: web.Request) -> web.Response:
    """Cancel a running flow: apply RunCancelled + cancel the asyncio task."""
    run_id = request.match_info["run_id"]
    runner: DevLoopRunner = request.app["runner"]

    try:
        envelope = await runner.cancel_run(run_id, requested_by="console-user")
    except KeyError:
        return web.json_response({"error": "unknown_run"}, status=404)

    task = request.app["flow_tasks"].get(run_id)
    if task and not task.done():
        task.cancel()

    logger.info("cancel_run: run_id=%s", run_id)
    return web.json_response({"envelope": envelope.model_dump(mode="json")})


def _run_id_is_safe(run_id: str) -> bool:
    """Reject run ids that could escape the artifact directory.

    Run ids are server-minted (``run-<hex8>`` / ``rev-<hex8>``), but the
    bundle endpoint interpolates one into a filesystem path, so the value
    coming off the URL is validated rather than trusted.

    Args:
        run_id: The id from the request path.

    Returns:
        ``True`` when the id is a plain identifier with no path syntax.
    """
    return bool(run_id) and all(c.isalnum() or c in "-_" for c in run_id)


async def handle_bundle(request: web.Request) -> web.Response:
    """Serve a finished run's exported bundle (FEAT-378 Module 8).

    ``DevLoopRunner._close_host`` writes ``{run_id}.bundle.json`` and
    ``{run_id}.report.md`` under ``conf.OUTPUT_DIR/dev_loop_runs/`` when
    a run terminates. This endpoint is a thin reader over those artifacts
    — deliberately not a second implementation of the bundle, so the
    console's "Download run bundle" and the on-disk report can never
    disagree.

    Query parameters:

    * ``format`` — ``md`` (default) or ``json``.
    * ``download`` — truthy forces a ``Content-Disposition: attachment``.

    Returns:
        The artifact, or 404 while the run is still in flight / the
        export has not landed.
    """
    run_id = request.match_info["run_id"]
    if not _run_id_is_safe(run_id):
        return web.json_response({"error": "invalid run_id"}, status=400)

    fmt = (request.query.get("format") or "md").strip().lower()
    if fmt not in {"md", "json"}:
        return web.json_response(
            {"error": "format must be 'md' or 'json'"}, status=400
        )

    suffix = "report.md" if fmt == "md" else "bundle.json"
    path = (RUN_ARTIFACT_DIR / f"{run_id}.{suffix}").resolve()
    # Security: verify resolved path stays within RUN_ARTIFACT_DIR
    _artifact_base = RUN_ARTIFACT_DIR.resolve()
    if not str(path).startswith(str(_artifact_base) + os.sep):
        return web.json_response({"error": "invalid run_id"}, status=400)
    if not path.is_file():
        return web.json_response(
            {
                "error": (
                    f"no run bundle for {run_id} yet — the export is written "
                    "when the run terminates."
                ),
                "expected_path": str(path),
            },
            status=404,
        )

    body = await asyncio.to_thread(path.read_text)
    headers = {}
    if request.query.get("download"):
        headers["Content-Disposition"] = f'attachment; filename="{path.name}"'
    return web.Response(
        body=body.encode("utf-8"),
        content_type="text/markdown" if fmt == "md" else "application/json",
        charset="utf-8",
        headers=headers,
    )


async def handle_replay(request: web.Request) -> web.Response:
    """Dump every stored event for a run (debugging helper)."""
    run_id = request.match_info["run_id"]
    redis = request.app["redis"]
    flow_key = f"flow:{run_id}:flow"
    dispatch_keys = [k async for k in redis.scan_iter(match=f"flow:{run_id}:dispatch:*")]
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
    development_dispatcher: object = dispatcher
    development_profile: object | None = None
    development_agent = conf.config.get("DEV_LOOP_DEVELOPMENT_AGENT", fallback="claude-code").strip().lower()
    if development_agent in {"claude", "claude-code"}:
        pass  # development_dispatcher/development_profile already set above
    elif development_agent in _DEVELOPMENT_AGENT_MAX_CONCURRENT_ENV or development_agent == "llm":
        # FEAT-323 Module 3: materialize via the reusable builder instead of
        # a dedicated inline branch per backend. "llm" is a legacy alias for
        # "nvidia" (DevAgentBackend only knows "nvidia").
        backend = "nvidia" if development_agent == "llm" else development_agent
        development_dispatcher, development_profile = build_dispatcher(
            DevAgentSpec(agent=backend),
            redis_url=redis_url,
            max_concurrent=conf.config.getint(
                _DEVELOPMENT_AGENT_MAX_CONCURRENT_ENV[backend],
                fallback=conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES,
            ),
            stream_ttl_seconds=conf.FLOW_STREAM_TTL_SECONDS,
        )
        _log_development_agent_selection(backend, development_profile)
    else:
        raise RuntimeError(
            "DEV_LOOP_DEVELOPMENT_AGENT must be 'claude-code', 'codex', "
            "'gemini', 'nvidia', 'grok', 'zai', or 'moonshot', "
            f"got {development_agent!r}"
        )

    codereview_dispatcher, codereview_agent_key = _resolve_codereview_dispatcher(
        dispatcher=dispatcher,
        development_dispatcher=development_dispatcher,
        redis_url=redis_url,
    )
    logger.info("QA code-review gate using %s reviewer", codereview_agent_key)

    judge_panel_dispatcher = _build_judge_panel_dispatcher(redis_url=redis_url)

    # FEAT-253: parse DEV_LOOP_REPOS -> list[RepoSpec] and wire git_toolkit.
    # When DEV_LOOP_REPOS is unset/empty, repos == [] and the flow falls
    # back to the local checkout at BASE_DIR (no clone, no network call).
    repos = parse_repo_specs(conf.DEV_LOOP_REPOS)
    if repos:
        logger.info(
            "DEV_LOOP_REPOS configured: %d repo(s) — primary alias=%r",
            len(repos),
            repos[0].alias,
        )
    else:
        logger.info("DEV_LOOP_REPOS not set; flow will target local checkout at BASE_DIR")

    # FEAT-323: resolve the dev-agent pool from env (DEV_LOOP_DEV_AGENTS /
    # DEV_LOOP_DEV_ISOLATION / DEV_LOOP_DEV_POOL_MAX). This is ADDITIVE to
    # the single-agent selection above — with DEV_LOOP_DEV_AGENTS unset,
    # DevelopmentNode's cascade resolves to `None` and runs single-agent
    # exactly as before.
    development_pool_config = parse_pool_env(conf.config.get)
    development_pool_max = resolve_pool_max(conf.config.get)
    # ALWAYS wire the builder, even with DEV_LOOP_DEV_AGENTS unset. The env
    # pool is only one of two ways a run acquires a pool — the console's
    # "Agents & models" tab sends a per-run `dev_agents` on the brief
    # (FEAT-323), which DevelopmentNode resolves at execute time. Gating the
    # builder on the env pool meant those per-run pools reached the node with
    # `dispatcher_builder=None` and silently degraded to a single agent
    # ("Pool config present but no dispatcher_builder was configured").
    # The builder is a lazy factory: with no pool resolved it is never called.
    development_dispatcher_builder = functools.partial(
        build_dispatcher,
        redis_url=redis_url,
        max_concurrent=conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES,
        stream_ttl_seconds=conf.FLOW_STREAM_TTL_SECONDS,
    )
    if development_pool_config is not None:
        backends_summary = ", ".join(
            f"{spec.agent}x{spec.count}" for spec in development_pool_config.agents
        )
        logger.info(
            "Dev-agent pool configured: %s (isolation=%s, pool_max=%d)",
            backends_summary,
            development_pool_config.isolation_mode,
            development_pool_max,
        )
    else:
        logger.info(
            "Dev-agent pool not configured in env (DEV_LOOP_DEV_AGENTS unset); "
            "DevelopmentNode runs single-agent unless a run declares its own "
            "dev_agents (pool_max=%d).",
            development_pool_max,
        )

    # FEAT-377 TASK-1914/1915 (G2): opt-in GraphIndex facade. from_config()
    # returns None when DEV_LOOP_GRAPH_MEMORY_PATH is unset — every seam it
    # backs (research context, run write-back, grounded findings) degrades
    # to a no-op, so this is a strict extension, never a behavior change.
    graph_memory = await DevLoopGraphMemory.from_config()

    # Auto-detect wiki search: if .parrot/wiki.json exists and the plane
    # is built, provide token-budgeted codebase context to ResearchNode's
    # dispatch brief — no env var required.
    wiki_search = DevLoopWikiSearch.from_project()
    app["wiki_search"] = wiki_search

    # Warn when wikitoolkit CLI is not in PATH — the sdd-research subagent
    # uses it for wiki-first triage via Bash, so a missing binary means
    # the agent silently falls back to grep.
    if not shutil.which("wikitoolkit"):
        logger.warning(
            "wikitoolkit not found in PATH — sdd-research subagent's "
            "wiki-first triage (step 0) will silently fall back to grep. "
            "Activate the venv or install wikitoolkit to enable CLI-based "
            "wiki search in dispatched sessions."
        )

    # FEAT-377 TASK-1916 (G5): opt-in plan_approval gate. False (default)
    # preserves current behavior exactly.
    require_plan_approval = bool(
        getattr(conf, "DEV_LOOP_REQUIRE_PLAN_APPROVAL", False)
    )
    skip_qa = bool(getattr(conf, "DEV_LOOP_SKIP_QA", False))

    jira_toolkit = _build_jira_toolkit()
    git_toolkit = _build_git_toolkit()
    app["flow"] = build_dev_loop_flow(
        dispatcher=dispatcher,
        jira_toolkit=jira_toolkit,
        log_toolkits=_build_log_toolkits(),
        redis_url=redis_url,
        development_dispatcher=development_dispatcher,
        development_profile=development_profile,
        development_pool_config=development_pool_config,
        development_dispatcher_builder=development_dispatcher_builder,
        development_pool_max=development_pool_max,
        name="dev-loop-demo",
        git_toolkit=git_toolkit,
        repos=repos,
        codereview_dispatcher=codereview_dispatcher,
        wiki_search=wiki_search,
        graph_memory=graph_memory,
        require_plan_approval=require_plan_approval,
        skip_qa=skip_qa,
    )
    # Orchestrator-side run cap (FLOW_MAX_CONCURRENT_RUNS) — spec G5.
    # The extra deps let the runner build the revision (FEAT-250) and
    # feature (FEAT-378) topologies on demand. graph_memory is forwarded
    # for the lazily-built revision flow (FEAT-377 TASK-1914/1915), keeping
    # both call sites consistent.
    wiki_toolkit = _build_wiki_toolkit()
    runner = DevLoopRunner(
        app["flow"],
        dispatcher=dispatcher,
        jira_toolkit=jira_toolkit,
        git_toolkit=git_toolkit,
        wiki_toolkit=wiki_toolkit,
        redis_url=redis_url,
        codereview_dispatcher=codereview_dispatcher,
        graph_memory=graph_memory,
    )

    # Feature mode (FEAT-378). `DevLoopRunner._run_feature` builds its flow
    # with `build_dev_loop_feature_flow`'s defaults, which leave
    # DevelopmentNode without a dispatcher builder and without the judge
    # panel — i.e. single-agent development and the bug-mode reviewer. The
    # console lets an operator size the pool and pick judges per run, so the
    # flow is pre-built here with the full wiring and seeded into the
    # runner's cache; `_run_feature` then reuses it instead of building a
    # thinner one.
    app["feature_mode_available"] = False
    app["feature_mode_reason"] = ""
    try:
        runner._feature_flow = build_dev_loop_feature_flow(  # noqa: SLF001
            dispatcher=dispatcher,
            jira_toolkit=jira_toolkit,
            git_toolkit=git_toolkit,
            wiki_toolkit=wiki_toolkit,
            redis_url=redis_url,
            codereview_dispatcher=judge_panel_dispatcher,
            development_dispatcher_builder=functools.partial(
                build_dispatcher,
                redis_url=redis_url,
                max_concurrent=conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES,
                stream_ttl_seconds=conf.FLOW_STREAM_TTL_SECONDS,
            ),
            development_pool_max=development_pool_max,
            # FEAT-377 TASK-1914/1915/1916: same graph_memory/
            # require_plan_approval already computed above for the
            # bug-mode build_dev_loop_flow() call — feature mode gets the
            # identical opt-in wiring instead of silently dropping it.
            graph_memory=graph_memory,
            require_plan_approval=require_plan_approval,
            skip_qa=skip_qa,
        )
        app["feature_mode_available"] = True
        logger.info(
            "Feature-mode topology ready (planner → development → synthesis "
            "→ qa[judge-panel] → feature_handoff → close; pool_max=%d)",
            development_pool_max,
        )
    except Exception as exc:  # noqa: BLE001 - feature mode is additive
        app["feature_mode_reason"] = str(exc)
        logger.warning(
            "Feature-mode topology unavailable (%s); the console will only "
            "offer bug/enhancement/new_feature runs.", exc,
        )

    app["runner"] = runner
    app["codereview_agent_key"] = codereview_agent_key
    app["development_pool_max"] = development_pool_max
    app["flow_tasks"] = {}  # run_id -> asyncio.Task
    logger.info(
        "Dev-loop flow ready (max %d concurrent runs)",
        runner.max_concurrent_runs,
    )


async def _on_cleanup(app: web.Application) -> None:
    """Graceful Ctrl-C / SIGTERM cleanup.

    Cancels every in-flight flow task and waits for them to settle (so
    we don't leave zombies that scribble on Redis after the loop is
    teared down), then closes the shared Redis client. Each step
    swallows its own exceptions because shutdown errors should never
    mask each other.
    """
    tasks = list(app.get("flow_tasks", {}).values())
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
                logger.debug("redis close raised during shutdown", exc_info=True)
        except Exception:  # pragma: no cover
            logger.debug("redis aclose raised during shutdown", exc_info=True)


def build_app(redis_url: str = "redis://localhost:6379/0") -> web.Application:
    app = web.Application()
    app["redis_url"] = redis_url
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)

    app.router.add_get("/", handle_index)
    app.router.add_static("/static/", STATIC_DIR, show_index=False)
    app.router.add_get("/api/config", handle_config)
    app.router.add_post("/api/flow/run", handle_run)
    app.router.add_get("/api/flow/{run_id}/bundle", handle_bundle)
    app.router.add_get("/api/flow/{run_id}/replay", handle_replay)
    app.router.add_get("/api/flow/{run_id}/ws", flow_stream_ws)
    app.router.add_post("/api/flow/{run_id}/cancel", handle_cancel)
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
    logger.info("Dev-loop demo on http://%s:%s (Redis=%s)", host, port, redis_url)
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    main()
