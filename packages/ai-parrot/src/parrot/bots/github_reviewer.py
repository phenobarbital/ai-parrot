"""GitHub Code Reviewer agent.

Reviews GitHub artefacts against the acceptance criteria of the linked
Jira ticket. Today the agent only handles pull requests; future revisions
are expected to layer additional code-review duties on top of the same
class. Designed to be subclassed per repository (mirrors the
:class:`~parrot.bots.jira_specialist.JiraSpecialist` pattern).

Workflow:

* On ``github.pr_opened`` / ``pr_reopened`` / ``pr_synchronize`` events
  emitted by :class:`~parrot.core.hooks.github_webhook.GitHubWebhookHook`,
  :meth:`handle_hook_event` is invoked by the orchestrator. It extracts the
  ``NAV-xxx`` (or any configured project prefix) key from the PR body /
  title, pulls the ticket from Jira, fetches the PR diff, asks the LLM for a
  structured comparison and either submits a ``REQUEST_CHANGES`` review
  with Telegram alerts (when discrepancies are found) or posts an
  ``APPROVE`` review (when all acceptance criteria are satisfied).
  Re-deliveries with the same ``head_sha`` are deduplicated in-memory so
  pushing multiple commits to a still-failing PR does not produce a
  storm of reviews and alerts.
* :meth:`report_stale_pull_requests` is decorated with
  :func:`schedule_daily_report` so it runs once a day and reports every open
  PR older than 24h to a public Telegram channel.

Authentication, toolkit wiring and the LLM model selection follow the same
pattern as :class:`JiraSpecialist` so a deployment that already runs
JiraSpecialist needs no extra plumbing beyond a new ``@register_agent``
subclass per watched repository.
"""

from __future__ import annotations

import asyncio
import html
import inspect
import json
import logging as _stdlib_logging
import re
import shutil
from collections import Counter
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from navconfig import config
from pydantic import BaseModel, Field

from parrot import conf
from parrot.bots import Agent
from parrot.core.hooks.github_webhook import GitHubWebhookHook
from parrot.knowledge.wiki.context import pack_results, truncate_to_tokens
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.repo_cache import RepoWikiCache
from parrot.knowledge.wiki.search import WikiCombinedSearch
from parrot.knowledge.wiki.store import create_wiki_store, estimate_tokens
from parrot.knowledge.wiki.structural.toolkit import CodeStructuralToolkit
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit

# FEAT-317: GitHubWebhookConfig/HookEvent moved to navigator_eventbus.hooks;
# imported here via the parrot.core.hooks re-export facade.
from parrot.core.hooks import GitHubWebhookConfig, HookEvent
from parrot.integrations.telegram import telegram_command
from parrot.scheduler import ScheduleType, schedule, schedule_daily_report, schedule_weekly_report
from parrot_tools.gittoolkit import (
    ContributorStats,
    ContributorWeek,
    GitToolkit,
    StatsNotReadyError,
    WeeklyCodeFrequency,
)
from parrot_tools.jiratoolkit import JiraToolkit

ChatId = Union[int, str]

#: Fire time of :meth:`GitHubReviewer.report_jira_tickets` — 10:00 in New
#: York, as a timezone rather than a UTC offset so it survives DST. Module
#: level because a decorator argument cannot read an attribute of the class
#: it is being defined in.
_TICKET_REPORT_HOUR = 10
_TICKET_REPORT_MINUTE = 0
_TICKET_REPORT_TIMEZONE = "America/New_York"
#: Day of the month :meth:`GitHubReviewer.report_monthly_jira_tickets` fires
#: on, at the same hour and timezone as the daily digest above.
_TICKET_MONTH_REPORT_DAY = 1

_WIKI_CONTEXT_HEADER = (
    "=== Codebase context (knowledge graph) ===\n"
    "SNAPSHOT OF BRANCH {branch} AT {built_at} — it does NOT contain this "
    "PR's changes. A symbol introduced by this PR is EXPECTED to be absent "
    "here; never report such a symbol as nonexistent on that basis."
)

#: The only ``LLMWikiToolkit`` methods the review LLM is given. Every other
#: public coroutine of that toolkit — ingest, create/update/delete page,
#: create/delete wiki, remember, reingest, export, rebuild index — is
#: withheld, so a review can never mutate the plane it reads.
#: ``confine_sources`` is not a substitute: it only forces ``ingest_source``
#: to take an http(s) URL, it does not make the toolkit read-only.
_WIKI_READ_TOOLS: tuple[str, ...] = (
    "search_compact",
    "read_page",
    "expand",
    "find_related",
    "browse_pages",
)

#: Same treatment for the structural plane. All three are already
#: read-only; naming them keeps anything a future release adds opt-in.
_STRUCTURAL_READ_TOOLS: tuple[str, ...] = (
    "symbol_lookup",
    "outline",
    "blast_radius",
)


def _read_only_excludes(toolkit_cls: type, keep: Sequence[str]) -> tuple[str, ...]:
    """Every public coroutine of ``toolkit_cls`` outside ``keep``.

    Derived by introspection instead of hardcoded so the deny-list cannot
    drift behind the toolkit: a write tool added by a future release is
    excluded by default rather than silently exposed to the reviewer.

    Args:
        toolkit_cls: Toolkit class whose tool surface is being narrowed.
        keep: Unprefixed method names to keep exposed.

    Returns:
        Names for ``exclude_tools`` (``_generate_tools`` matches on the
        unprefixed method name).
    """
    return tuple(
        name
        for name, _ in inspect.getmembers(toolkit_cls, inspect.iscoroutinefunction)
        if not name.startswith("_") and name not in keep
    )


#: Appended to the system prompt once the wiki tools are really attached,
#: so a reviewer whose build failed is never told about tools it lacks.
_WIKI_TOOLS_PROMPT = """

## Repository knowledge graph

You also have a prebuilt knowledge graph of this repository: one page per
file, directory and symbol, each with a summary and an API outline, linked
by ``contains`` (directory to child) and ``references`` (import) edges,
plus a structural plane of call/extend/implement relations between symbols.

It is a snapshot of the BASE branch, so it shows the code the PR changes
*from* — never the PR's own changes, which only the diff carries. A symbol
the PR introduces is expected to be absent from it.

Use it to judge blast radius and completeness: who calls the symbol a hunk
touches, which module a changed file belongs to, whether an acceptance
criterion is already implemented elsewhere in the repo.

Structural tools (start here for a named function, class or method):
- ``code_symbol_lookup(query)`` — find a symbol by name or qualname;
  returns file and line for each hit.
- ``code_outline(path)`` — list a file's symbols before reading it whole.
- ``code_blast_radius(symbol)`` — every symbol that transitively calls,
  extends or implements it. Run this before judging a change to a
  widely-used function or class.

Graph tools (for a question rather than a name) — pass
``wiki_name="{wiki_name}"`` to every one of these:
- ``wiki_search_compact(wiki_name, query)`` — token-budgeted stubs (page
  id, title, lead sentence, cost of reading the full page).
- ``wiki_read_page(wiki_name, page_id, max_tokens?)`` — the full body of a
  stub worth its tokens. Page ids are ``file:path/to/module.py``,
  ``dir:path/to``, or ``sym:path/to/module.py#Class.method``.
- ``wiki_expand(wiki_name, page_id, rel?)`` — the page's graph
  neighbourhood as stubs; ``rel="references"`` for import edges.
- ``wiki_find_related(wiki_name, page_id, depth?)`` — multi-hop neighbours.
- ``wiki_browse_pages(wiki_name, category?, search?)`` — stubs by category
  (``module``, ``document``, ``config``, ``overview``, ``symbol``).

These calls share the same per-review tool budget as the GitHub tools, so
spend them only when the diff and the codebase context block above cannot
answer the question. The graph is background context: the diff and the
acceptance criteria decide the verdict.
"""


def _flatten_adf(node: Any) -> str:
    """Flatten an Atlassian Document Format (ADF) tree into plain text.

    Returns ``node`` unchanged when it is already a string; for any non-dict /
    non-list input returns ``str(node)`` (or empty). Walks ``content`` arrays
    recursively and concatenates every ``text`` leaf, inserting newlines
    around block-level nodes so paragraphs and bullets remain readable.
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(filter(None, (_flatten_adf(n) for n in node)))
    if not isinstance(node, dict):
        return str(node)

    text = node.get("text")
    if isinstance(text, str):
        return text

    inner = _flatten_adf(node.get("content"))
    block_types = {
        "paragraph",
        "heading",
        "bulletList",
        "orderedList",
        "listItem",
        "codeBlock",
        "blockquote",
        "rule",
    }
    if node.get("type") in block_types and inner:
        return f"{inner}\n"
    return inner


# ──────────────────────────────────────────────────────────────
# Structured output
# ──────────────────────────────────────────────────────────────


class Discrepancy(BaseModel):
    """Single mismatch between the PR and the Jira acceptance criteria."""

    criterion: str = Field(description="The acceptance criterion or ticket requirement not met.")
    issue: str = Field(description="What the PR misses, contradicts or deviates from.")
    severity: Literal["minor", "major", "blocker"] = Field(
        description=("Severity. 'blocker' = MUST fix before merge, " "'major' = should fix, 'minor' = nice-to-have."),
    )


class PRReviewResult(BaseModel):
    """LLM-produced summary of a PR review."""

    jira_key: Optional[str] = Field(
        default=None,
        description="The Jira issue key referenced by the PR, if any.",
    )
    discrepancies: List[Discrepancy] = Field(
        default_factory=list,
        description="Discrepancies found between the PR and the ticket.",
    )
    summary: str = Field(
        description="One-paragraph human summary of the review.",
    )
    approve: bool = Field(
        description="True if the PR satisfies every acceptance criterion.",
    )


class PRChecksSummary(BaseModel):
    """Normalized CI picture of a pull request's head commit.

    Produced by :meth:`GitHubReviewer._summarize_checks` from the raw
    ``get_pr_checks`` payload, so the gate reasons about counts rather than
    about GitHub's two overlapping status APIs.
    """

    available: bool = True
    """False when GitHub could not be asked at all (no toolkit, API error).
    Distinguishes "no checks" from "we don't know", which the gate treats
    very differently."""
    declared: bool = False
    """True when the head commit has at least one check run or commit status."""
    total: int = 0
    success: int = 0
    failure: int = 0
    pending: int = 0
    pass_ratio: float = 0.0
    """``success / (success + failure)`` — checks still running are excluded,
    so a half-finished pipeline cannot dilute the ratio. 0.0 when nothing has
    completed yet."""
    failing: List[str] = Field(default_factory=list)
    """Names of the failing checks, for the PR comment and the alerts."""
    running: List[str] = Field(default_factory=list)
    """Names of the checks still in flight."""
    test_checks: int = 0
    """How many declared checks look like a test suite (name heuristic). Used
    only for wording and for ``require_checks``; the gate itself scores every
    check equally, because a failing lint job also blocks a merge."""
    denied: List[str] = Field(default_factory=list)
    """Which CI endpoints the token was refused (``check_runs`` /
    ``commit_statuses``). Non-empty with ``available`` True means the picture
    is partial: one API answered and the other was denied."""
    reason: Optional[str] = None
    """Why the picture is unavailable or incomplete — names the missing token
    permission when GitHub refused a CI read."""


class MergeVerdict(BaseModel):
    """Outcome of the strict gate: may this PR stay mergeable?"""

    mergeable: bool
    """True only when the review approved it AND the CI gate passed."""
    defer: bool = False
    """True when the verdict cannot be reached yet because checks are still
    running. The PR is neither approved nor drafted — the next push, or the
    next manual call, decides."""
    reasons: List[str] = Field(default_factory=list)
    """Human-readable blocking reasons, in the order they are reported. Empty
    when ``mergeable`` is True."""
    warnings: List[str] = Field(default_factory=list)
    """Non-blocking observations (minor findings, missing CI, unreadable CI)."""


# ---------------------------------------------------------------------------
# Weekly activity report models (FEAT-180)
# ---------------------------------------------------------------------------


class _ContributorWindowSummary(BaseModel):
    """One contributor's activity inside the reporting window."""

    login: str
    """GitHub login of the contributor."""
    commits_this_week: int
    """Number of commits in the current (most recent completed) week."""
    additions: int
    """Lines added in the current week."""
    deletions: int
    """Lines deleted in the current week (non-negative)."""
    weeks_silent: int
    """Consecutive weeks with zero commits up to and including the last completed
    week. Zero when the contributor was active in the last completed week."""


class WeeklyActivitySummary(BaseModel):
    """Structured input to the templated/LLM renderer for the weekly digest."""

    repository: str
    """Repository name in ``owner/name`` format."""
    period_start: datetime
    """Sunday 00:00 UTC that begins the reporting week."""
    period_end: datetime
    """Sunday 00:00 UTC that begins the FOLLOWING week (exclusive upper bound)."""
    contributors_active: List[_ContributorWindowSummary]
    """Contributors with at least one commit in the reporting week, sorted by
    commits desc then additions+deletions desc then login."""
    contributors_silent: List[_ContributorWindowSummary]
    """Contributors whose last ``weeks_silent >= threshold`` consecutive weeks
    all had zero commits. Sorted by weeks_silent desc then login. Uncapped."""
    total_commits: int
    """Sum of commits across all contributors in the current week."""
    total_additions: int
    """Sum of additions across all contributors in the current week."""
    total_deletions: int
    """Sum of deletions across all contributors in the current week."""
    prev_total_commits: int
    """Total commits in the week immediately before the reporting window
    (from code_frequency data, 0 if not available)."""
    prev_total_additions: int
    """Total additions in the previous week (from code_frequency, 0 if missing)."""
    prev_total_deletions: int
    """Total deletions in the previous week (from code_frequency, 0 if missing)."""
    code_freq_available: bool = True
    """False when the previous week's ``code_frequency`` slice was missing — a
    cold ``/stats`` cache (persistent 202) or a repo without that much history.
    The ``prev_total_additions`` / ``prev_total_deletions`` zeros are then
    *unknown*, not measured, so renderers must not derive a line delta from
    them. ``prev_total_commits`` is unaffected: it is summed from the
    contributor slices, never from ``code_frequency``."""


class ChartReply(BaseModel):
    """A command reply the channel wrappers deliver as text plus a chart.

    Duck-typed to what ``parrot.integrations.parser.parse_response()``
    reads off an ``AIMessage``: ``output`` becomes the message text and
    ``charts`` becomes attachments, so a ``@telegram_command`` method can
    return one of these and let the wrapper do the sending — Telegram as a
    photo (``send_photo``), MS Teams as a card image. The command method
    then never needs to know which chat asked.
    """

    output: str
    """Message text. Markdown; fence anything whose alignment matters."""
    charts: List[Dict[str, Any]] = Field(default_factory=list)
    """``{"path", "title", "chart_type", "format"}`` entries, one per image.
    Empty when the chart could not be rendered — the text still goes out."""


class WeeklyLLMSummarizationError(RuntimeError):
    """Raised when the LLM summarizer fails; caller falls back to templated output."""


# ──────────────────────────────────────────────────────────────
# System prompt
# ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a strict but constructive Pull Request reviewer. For every review you
receive a Jira ticket (description + acceptance criteria) and a GitHub pull
request (title, body, diff). Your job is to determine whether the PR fully
implements the acceptance criteria.

Rules:
- Treat the acceptance criteria as the ground truth. The PR must satisfy
  every criterion; bonus work is fine but unrelated work is a discrepancy.
- For each unmet or partially-met criterion, emit ONE Discrepancy.
- Pick severity carefully: 'blocker' if the criterion is essentially not
  addressed, 'major' if addressed but incomplete or incorrect, 'minor' for
  cosmetic gaps.
- If the PR clearly does work that the ticket does not request, that is a
  'major' discrepancy too (scope drift).
- Never hallucinate code that is not in the diff. If the diff is truncated,
  say so in the summary and bias toward fewer-but-confident discrepancies.
- Return a PRReviewResult. ``approve`` is True ONLY when ``discrepancies``
  is empty AND nothing in the diff contradicts the ticket.

Be concise. Prefer concrete pointers ("AC #2 says the endpoint must accept
JSON, but the diff only adds a form-data branch") over vague language.

## Tool Use Guide

When reviewing the PR diff, you have three tools to pull additional
context from the repository. Use them sparingly — the cap is 5 calls
per review.

- ``get_file_content_at_ref(path, ref, start_line?, end_line?)`` —
  fetch the full body of a file at a given commit, branch, or tag.
  Use when the diff hunk shows a small change to a function whose
  full body or class context is needed to judge whether the change
  is correct. Prefer ``start_line``/``end_line`` slicing on large files.

- ``compare_pr_versions(pr_number, path)`` — fetch both the base and
  head versions of a single file in the PR. Use when the diff hunk
  is too small to see the full before/after of a refactored function
  or class.

- ``search_repo_code(query)`` — search the PR's repository for a
  string or symbol on the default branch only. Use when you suspect
  a change has callers or related code elsewhere that the diff does
  not show. Note: this only indexes the default branch and is
  rate-limited.

If you are confident in your verdict from the diff alone, do not call
any tools — return the PRReviewResult directly.
"""


# ──────────────────────────────────────────────────────────────
# LLM weekly report system prompt (module-level — not class attr,
# so it remains accessible when methods are bound to test stubs)
# ──────────────────────────────────────────────────────────────

_WEEKLY_LLM_SYSTEM_PROMPT = (
    "You write concise, factual weekly engineering activity reports for a "
    "software team. Given a structured JSON summary of last week's GitHub "
    "activity, output a short English digest (3-5 short paragraphs total, "
    "~150 words max). Lead with totals, highlight 1-2 notable contributors, "
    "and call out anyone who has gone silent. Do not invent numbers; only "
    "use values present in the input JSON. Do not include HTML tags or "
    "markdown bullets. Plain prose only."
)


# ──────────────────────────────────────────────────────────────
# GitHubReviewer
# ──────────────────────────────────────────────────────────────


class GitHubReviewer(Agent):
    """Reviews GitHub PRs against linked Jira ticket acceptance criteria.

    Like :class:`JiraSpecialist`, this class is abstract by convention:
    deployments should subclass it (one subclass per repository) and apply
    ``@register_agent`` on the subclass.

    Args:
        repository: Target GitHub repository in ``"owner/name"`` format.
        jira_project: Jira project key whose tickets the PRs reference
            (default ``"NAV"``). Used to build the regex that extracts the
            ticket key from the PR body / title.
        alert_chat_ids: Telegram chat IDs that should receive a private
            alert when a discrepancy is found.
        public_channel_id: Telegram chat / channel ID that receives the
            daily summary of stale (>24h) open PRs.
        management_chat_id: Telegram chat / channel ID that receives the
            management reports — :meth:`today_pr`,
            :meth:`report_weekly_activity` and
            :meth:`report_jira_tickets`. Defaults to ``public_channel_id``
            so those reports keep arriving when it is not configured.
        webhook_public_url: Public HTTPS URL of the GitHub webhook
            endpoint (e.g. ``https://parrot.example.com/api/v1/hooks/github``).
            When set, :meth:`post_configure` calls
            :meth:`GitToolkit.ensure_webhook` to register it.
        webhook_secret: Shared secret GitHub will use to sign deliveries.
            Required for HMAC verification on the receiving end.
        stale_after_hours: How long an open PR must be unattended before
            being included in :meth:`report_stale_pull_requests`.
            Defaults to ``24``.
        max_diff_bytes: How much of the diff to feed the LLM. Larger diffs
            are truncated; the prompt instructs the LLM to acknowledge it.
        max_ticket_bytes: Per-field clamp applied to the Jira description
            and acceptance criteria text before they are spliced into the
            LLM prompt. Prevents one oversized ticket from blowing the
            context window. Defaults to ``20_000``.
        min_check_pass_ratio: Share of a PR's COMPLETED CI checks that must
            be green for :meth:`review_pr` to approve it — "all OK, or a
            great part of them". Clamped to ``[0, 1]``; defaults to
            ``GITHUB_REVIEW_MIN_CHECK_PASS_RATIO`` (0.8).
        require_checks: When True, a PR whose head commit declares no checks
            at all is refused instead of merely warned about. Defaults to
            ``GITHUB_REVIEW_REQUIRE_CHECKS`` (False), so a repository
            without CI is not blocked wholesale.
        google_api_key: Google credential this agent bills its LLM traffic
            to, so reviewer usage can be metered and rotated apart from the
            process-wide key. Defaults to
            ``GITHUB_REVIEW_GOOGLE_API_KEY``; when neither is set the
            Google client falls back to ``GOOGLE_API_KEY`` as before.

    Notes:
        Jira **per-user OAuth2 3LO** is unsupported by this agent: webhook
        deliveries arrive without a caller identity, so the resolver has
        no user whose tokens it could load. When ``JIRA_AUTH_TYPE`` is
        ``oauth2_3lo`` the agent falls back to service-account
        ``basic_auth`` using ``JIRA_USERNAME`` + ``JIRA_API_TOKEN``; if
        those are missing, ``self.jira_toolkit`` stays ``None`` and the
        reviewer disables itself with a clear error in the logs.

        Reviews are de-duplicated **in-memory** by ``(repo, pr_number,
        head_sha)``. Pushing eight commits to a still-failing PR will not
        produce eight reviews or eight Telegram alerts; the dedup cache
        resets when the process restarts.

        Note on prompt caching: This agent enables ``prompt_caching=True`` by
        default (FEAT-181). Prompt caching activates provider-side caching of
        the static system prompt prefix. The default model
        (``GEMINI_3_FLASH_PREVIEW``) requires ≥4096 tokens in the cacheable
        prefix for caching to take effect. If the system prompt + agent context
        document are below this threshold, caching silently skips with a
        ``PromptCacheSkippedEvent``. For guaranteed caching, use an Anthropic
        or OpenAI model.
    """

    model = "gemini-3.7-flash"

    # aiohttp app keys. The dispatcher fans out to every listener so multiple
    # GitHubReviewer subclasses (one per repo) can share a single endpoint;
    # the multi-tenant guard in handle_hook_event keeps deliveries on-topic.
    WEBHOOK_APP_KEY: str = "github_review_hook"
    WEBHOOK_LISTENERS_KEY: str = "github_review_hook_listeners"
    _WEBHOOK_STARTED_KEY: str = "github_review_hook_started"

    @classmethod
    def setup_webhook_route(
        cls,
        app: Any,
        *,
        url: str = "/api/v1/hooks/github",
        secret: Optional[str] = None,
        name: str = "github_review_hook",
    ) -> GitHubWebhookHook:
        """Register the aiohttp route that receives GitHub webhook deliveries.

        Call this from the **synchronous** application setup phase
        (e.g. ``Main.configure()`` in a Navigator app) — *before* aiohttp
        freezes its router on ``on_startup``. Adding routes from
        :meth:`post_configure` is too late and will raise
        ``RuntimeError: Cannot register a resource into frozen router``.

        Idempotent: subsequent calls return the existing hook stored in
        ``app[WEBHOOK_APP_KEY]``. Multiple agent instances share one hook
        and one route; each agent appends its
        :meth:`handle_hook_event` as a listener during
        :meth:`post_configure`, and the dispatcher fans every delivery
        out to all listeners. ``handle_hook_event`` already filters by
        ``payload.repository``, so cross-repo noise is dropped per agent.

        **Auth integration**: GitHub signs deliveries with HMAC-SHA256
        (verified by :class:`GitHubWebhookHook`), not with Bearer tokens.
        If your app uses an auth middleware (e.g. navigator-auth) you
        must whitelist the returned hook's ``url`` so deliveries are not
        rejected with a 401::

            github_hook = GitHubReviewer.setup_webhook_route(app)
            auth.setup(app)
            auth.add_exclude_list(github_hook.url)

        Args:
            app: The aiohttp ``web.Application``.
            url: The route path. Must match what GitHub points its
                webhook at; default ``"/api/v1/hooks/github"``.
            secret: HMAC-SHA256 shared secret used to verify deliveries.
                Falls back to
                :data:`parrot.conf.GITHUB_REVIEW_WEBHOOK_SECRET` when
                ``None``. Pass an explicit empty string to disable
                verification (not recommended).
            name: Logical name of the hook instance, surfaced in logs.

        Returns:
            The shared :class:`GitHubWebhookHook` instance.
        """
        existing = app.get(cls.WEBHOOK_APP_KEY)
        if existing is not None:
            return existing

        if secret is None:
            secret = config.get("GITHUB_REVIEW_WEBHOOK_SECRET")

        listeners: List[Callable[[HookEvent], Awaitable[None]]] = []
        dispatch_logger = _stdlib_logging.getLogger(f"parrot.hooks.{name}.dispatch")

        async def _dispatch(event: HookEvent) -> None:
            # Fan out to every registered listener; one listener raising
            # must not block the others from getting the event.
            for listener in list(listeners):
                try:
                    await listener(event)
                except Exception as exc:  # noqa: BLE001
                    dispatch_logger.error(
                        "Listener %r raised on %s: %s",
                        listener,
                        event.event_type,
                        exc,
                        exc_info=True,
                    )

        hook = GitHubWebhookHook(
            config=GitHubWebhookConfig(
                name=name,
                url=url,
                secret_token=secret or None,
            ),
        )
        hook.setup_routes(app)
        hook.set_callback(_dispatch)

        app[cls.WEBHOOK_APP_KEY] = hook
        app[cls.WEBHOOK_LISTENERS_KEY] = listeners
        app[cls._WEBHOOK_STARTED_KEY] = False
        return hook

    def __init__(
        self,
        repository: str,
        *,
        jira_project: str = "NAV",
        alert_chat_ids: Optional[List[ChatId]] = None,
        public_channel_id: Optional[ChatId] = None,
        management_chat_id: Optional[ChatId] = None,
        webhook_public_url: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        stale_after_hours: int = 24,
        max_diff_bytes: int = 50_000,
        max_ticket_bytes: int = 20_000,
        silent_weeks_threshold: int = 3,
        top_n_contributors: int = 10,
        use_llm_summary: bool = False,
        max_review_tool_calls: Optional[int] = None,
        min_check_pass_ratio: Optional[float] = None,
        require_checks: Optional[bool] = None,
        google_api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("injection_probability_threshold", 0.995)
        kwargs.setdefault("system_prompt", _SYSTEM_PROMPT)
        kwargs.setdefault("prompt_caching", True)  # FEAT-181

        super().__init__(**kwargs)

        # Bill this agent's Google traffic to its own credential. Must run
        # after super().__init__() (which builds ``_llm_kwargs``) and before
        # configure() (which reads them to construct the client).
        self._apply_google_api_key(google_api_key)

        self.repository = repository
        self._repository_lc = repository.lower()
        self.jira_project = jira_project
        self.alert_chat_ids: List[ChatId] = list(alert_chat_ids or [])
        self.public_channel_id = public_channel_id
        # Management reports (today's PRs, weekly activity, Jira tickets) go
        # here. Falling back to the public channel keeps them delivered on a
        # deployment that has not split the two destinations yet;
        # post_configure() warns when that fallback is in effect.
        self.management_chat_id = management_chat_id or public_channel_id
        self.webhook_public_url = webhook_public_url
        self.webhook_secret = webhook_secret
        self.stale_after_hours = int(stale_after_hours)
        self.max_diff_bytes = int(max_diff_bytes)
        self.max_ticket_bytes = int(max_ticket_bytes)
        self.silent_weeks_threshold = int(silent_weeks_threshold)
        self.top_n_contributors = int(top_n_contributors)
        self.use_llm_summary = bool(use_llm_summary)

        # FEAT-182: tool-call cap per review session.
        # Priority: explicit kwarg > GITHUB_REVIEWER_MAX_TOOL_CALLS env var > 5.
        if max_review_tool_calls is not None:
            self.max_review_tool_calls = int(max_review_tool_calls)
        else:
            env_cap = config.get("GITHUB_REVIEWER_MAX_TOOL_CALLS", fallback=5)
            self.max_review_tool_calls = int(env_cap)

        self._ac_field_id: str = config.get("JIRA_ACCEPTANCE_CRITERIA_FIELD", fallback="customfield_10100")
        self._jira_fields: str = ",".join(sorted({"summary", "description", "status", self._ac_field_id}))
        # The strict gate also needs the assignee, to find who to notify when
        # it drafts a PR; the webhook path does not, so it keeps the narrower
        # field list and the cheaper Jira response.
        self._jira_strict_fields: str = ",".join(
            sorted({"summary", "description", "status", "assignee", self._ac_field_id})
        )

        # /review_pr gate. A ratio outside [0, 1] is operator error, not a
        # reason to approve everything or nothing, so it is clamped.
        ratio = conf.GITHUB_REVIEW_MIN_CHECK_PASS_RATIO if min_check_pass_ratio is None else min_check_pass_ratio
        try:
            ratio = float(ratio)
        except (TypeError, ValueError):
            ratio = conf.GITHUB_REVIEW_MIN_CHECK_PASS_RATIO
        self.min_check_pass_ratio: float = min(1.0, max(0.0, ratio))
        self.require_checks: bool = bool(
            conf.GITHUB_REVIEW_REQUIRE_CHECKS if require_checks is None else require_checks
        )

        self._ticket_key_regex = re.compile(rf"\b{re.escape(self.jira_project)}-\d+\b")

        self.git_toolkit: Optional[GitToolkit] = None
        self.jira_toolkit: Optional[JiraToolkit] = None
        self._wiki_cache: Optional[RepoWikiCache] = None
        self._wiki_warmup_task: Optional[asyncio.Task[None]] = None
        self._wiki_refresh_task: Optional[asyncio.Task[Optional[Path]]] = None
        # Deferred weekly retry (cold GitHub /stats/* cache). Both knobs are
        # plain attributes rather than constructor kwargs so a test can set
        # them without widening the already-wide signature.
        self._weekly_retry_task: Optional[asyncio.Task[None]] = None
        self._weekly_retry_attempt = 0
        self._stats_retry_delay = conf.GITHUB_REVIEW_STATS_RETRY_DELAY
        self._stats_retry_max = conf.GITHUB_REVIEW_STATS_RETRY_MAX
        self._wiki_toolkits_attached = False
        self._wiki_store: Any = None
        self._wiki_branch: Optional[str] = None
        self._wiki_built_at: Optional[datetime] = None
        self._wiki_context_available = False
        self._wrapper = None  # Set by TelegramAgentWrapper after init
        # In-memory dedup: (repo_lc, pr_number) -> last reviewed head_sha.
        # Cheap and process-local; restart resets it (acceptable tradeoff —
        # GitHub will simply re-fire the latest synchronize event).
        self._reviewed_shas: Dict[Tuple[str, int], str] = {}
        # PRs we already pinged about a missing Jira key. Dedup is per-PR
        # (not per-SHA) — pushing more commits without adding the ticket
        # must not spam the conversation. Cleared on process restart.
        self._no_ticket_notified: set[Tuple[str, int]] = set()

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_google_api_key(explicit: Optional[str] = None) -> Optional[str]:
        """Resolve the Google credential this agent should use for its LLM.

        Priority: the constructor's ``google_api_key=`` argument >
        :data:`parrot.conf.GITHUB_REVIEW_GOOGLE_API_KEY` > ``None``.

        Read through the ``conf`` module object rather than a from-import so
        a monkeypatched value is honoured.

        Args:
            explicit: The constructor's ``google_api_key=`` argument.

        Returns:
            The credential to inject, or ``None`` meaning "inject nothing" —
            the Google client then resolves ``GOOGLE_API_KEY`` itself, exactly
            as it did before this knob existed. The value is never logged.
        """
        if explicit:
            return explicit
        return getattr(conf, "GITHUB_REVIEW_GOOGLE_API_KEY", None) or None

    def _apply_google_api_key(self, explicit: Optional[str] = None) -> bool:
        """Point this agent's Google client at the reviewer's own credential.

        Rebinds ``self._llm_kwargs`` to a NEW dict instead of mutating it: the
        existing dict may be the very object the caller passed as
        ``llm_kwargs=`` (or that a stored agent row holds), and mutating it
        would leak the credential into a shared, possibly persisted mapping.

        Call after ``super().__init__()``, which builds ``_llm_kwargs``, and
        before ``configure()``, which reads them to construct the client.

        No-ops — leaving the client's own ``GOOGLE_API_KEY`` fallback in place
        — when no dedicated key is configured, when the agent's LLM is not
        Google, or when the caller already brought a credential of their own
        (``api_key`` / ``credentials_file`` / ``credentials`` / ``vertexai``).

        Args:
            explicit: The constructor's ``google_api_key=`` argument.

        Returns:
            ``True`` when the key was injected, ``False`` otherwise.
        """
        key = self._resolve_google_api_key(explicit)
        if not key:
            self.logger.debug(
                "GITHUB_REVIEW_GOOGLE_API_KEY is not set; the reviewer's Google client falls back to GOOGLE_API_KEY."
            )
            return False

        # Lazy import: ``parrot.bots.flows`` pulls the whole orchestration
        # stack, which this module otherwise never needs.
        from parrot.bots.flows.crew.credentials import (  # noqa: PLC0415 — FEAT-523 lazy import
            has_explicit_google_credential,
            is_google_llm,
        )

        if not is_google_llm(getattr(self, "_llm_raw", None), getattr(self, "_default_llm", "google")):
            self.logger.warning(
                "A GitHub Reviewer Google key is configured, but this agent's LLM is not a Google provider; "
                "ignoring it."
            )
            return False

        llm_kwargs = getattr(self, "_llm_kwargs", None) or {}
        if has_explicit_google_credential(llm_kwargs):
            self.logger.debug("Agent already carries an explicit Google credential; the reviewer key is ignored.")
            return False

        self._llm_kwargs = {**llm_kwargs, "api_key": key}
        self.logger.debug("Using the dedicated GitHub Reviewer Google API key for this agent's LLM.")
        return True

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def set_wrapper(self, wrapper) -> None:
        """Called by :class:`TelegramAgentWrapper` so the agent can push
        proactive messages over the Telegram Bot it shares with the wrapper.
        """
        self._wrapper = wrapper

    async def post_configure(self) -> None:
        """Wire :class:`GitToolkit` and :class:`JiraToolkit` once ``self.app``
        is attached. Auth selection mirrors :class:`JiraSpecialist`, with the
        important difference that per-user OAuth is rejected (no caller).

        Also attaches :meth:`handle_hook_event` to the shared
        :class:`GitHubWebhookHook` that
        :meth:`setup_webhook_route` registered during sync setup. If
        ``setup_webhook_route`` was never called the agent logs a clear
        warning — the bot still works for manually-triggered reviews, but
        GitHub deliveries land on a 404 until the route is registered
        before the aiohttp router freezes.
        """
        await super().post_configure()

        if self.management_chat_id and self.management_chat_id == self.public_channel_id:
            self.logger.warning(
                "GitHubReviewer: no management chat configured "
                "(GITHUB_MANAGEMENT_TELEGRAM_CHAT_ID); today_pr, the weekly "
                "activity digest and the Jira ticket summary will go to the "
                "public channel %s alongside the stale-PR nag.",
                self.public_channel_id,
            )

        self.git_toolkit = self._build_git_toolkit()
        self._wiki_cache = self._build_wiki_cache()
        await self._schedule_wiki_warmup()
        self.jira_toolkit = self._build_jira_toolkit()

        self._attach_toolkit(self.git_toolkit, "Git")
        self._attach_toolkit(self.jira_toolkit, "Jira")

        if self._llm is not None and hasattr(self._llm, "tool_manager"):
            try:
                self.sync_tools(self._llm)
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "GitHubReviewer: failed to sync tools to LLM: %s",
                    exc,
                    exc_info=True,
                )

        await self._attach_webhook_listener()
        await self._ensure_webhook_subscription()

    async def shutdown(self, **kwargs: Any) -> None:
        """Stop the owned background tasks before the inherited agent shutdown."""
        try:
            await self._shutdown_wiki_warmup()
            await self._shutdown_weekly_retry()
        finally:
            await super().shutdown(**kwargs)

    async def _shutdown_weekly_retry(self) -> None:
        """Cancel and await a pending deferred weekly retry."""
        task = self._weekly_retry_task
        self._weekly_retry_task = None
        self._weekly_retry_attempt = 0
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _build_wiki_cache(self) -> Optional[RepoWikiCache]:
        """Build the optional repository wiki cache from reviewer settings."""
        if not conf.GITHUB_REVIEW_WIKI_ENABLED:
            return None
        if self.git_toolkit is None:
            self.logger.warning("GitHubReviewer: wiki cache disabled because GitToolkit is unavailable.")
            return None
        if shutil.which("wikitoolkit") is None:
            self.logger.warning("GitHubReviewer: wiki cache disabled because wikitoolkit is unavailable.")
            return None
        try:
            cache_dir = Path(conf.GITHUB_REVIEW_CACHE_DIR).expanduser().resolve()
            return RepoWikiCache(
                self.git_toolkit,
                cache_dir,
                max_bytes=conf.GITHUB_REVIEW_CACHE_MAX_BYTES,
                clone_branch=conf.GITHUB_REVIEW_CLONE_BRANCH,
                clone_depth=conf.GITHUB_REVIEW_CLONE_DEPTH,
                build_timeout=conf.GITHUB_REVIEW_BUILD_TIMEOUT,
                logger=self.logger,
            )
        except Exception as exc:  # noqa: BLE001 - wiki enrichment must fail closed
            self.logger.warning("GitHubReviewer: wiki cache unavailable: %s", exc, exc_info=True)
            return None

    async def _schedule_wiki_warmup(self) -> None:
        """Create a named warm-up task and log unhandled failures."""
        if self._wiki_cache is None or self._wiki_warmup_task is not None:
            return

        async def warmup() -> None:
            await self._refresh_wiki_context(self.repository)

        task = asyncio.create_task(warmup(), name=f"github-reviewer-wiki-warmup:{self._repository_lc}")
        self._wiki_warmup_task = task
        self._wiki_refresh_task = task  # first delivery reuses the warm-up

        def log_failure(completed: asyncio.Task[None]) -> None:
            if completed.cancelled():
                return
            try:
                completed.result()
            except Exception as exc:  # noqa: BLE001 - callback must consume task failures
                self.logger.warning("GitHubReviewer: wiki warm-up failed: %s", exc, exc_info=True)

        task.add_done_callback(log_failure)

    async def _shutdown_wiki_warmup(self) -> None:
        """Cancel and await the wiki warm-up task when it is still active."""
        tasks: list[asyncio.Task[Any]] = []
        for task in (self._wiki_warmup_task, self._wiki_refresh_task):
            if task is not None and task not in tasks:
                tasks.append(task)
        self._wiki_warmup_task = None
        self._wiki_refresh_task = None
        for task in tasks:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 - callback already logged the failure
                pass

    async def _refresh_wiki_context(self, repository: str) -> Optional[Path]:
        """Refresh this reviewer's wiki plane, never one selected by a payload."""
        if self._wiki_cache is None or not isinstance(repository, str) or repository.lower() != self._repository_lc:
            return None
        try:
            paths = await self._wiki_cache.ensure_fresh(self.repository)
        except Exception as exc:  # noqa: BLE001 - diff-only review remains available
            self._wiki_context_available = False
            self.logger.warning("GitHubReviewer: wiki refresh unavailable for %s: %s", self.repository, exc)
            return None
        if paths is None:
            self._wiki_context_available = False
            return None
        self._attach_wiki_toolkits(paths.clone_dir)
        self._wiki_branch = await self._wiki_cache._git_output(
            ["git", "-C", str(paths.clone_dir), "branch", "--show-current"]
        )
        self._wiki_built_at = self._wiki_cache.build_runner.last_good(paths.plane_dir)
        self._wiki_context_available = self._wiki_toolkits_attached
        return paths.clone_dir

    def _start_wiki_refresh(self, repository: str) -> Optional[asyncio.Task[Optional[Path]]]:
        """Start (or reuse) the single in-flight wiki refresh for this reviewer's repository."""
        if self._wiki_cache is None or not isinstance(repository, str) or repository.lower() != self._repository_lc:
            return None
        current = self._wiki_refresh_task
        if current is not None and not current.done():
            return current
        task = asyncio.create_task(
            self._refresh_wiki_context(self.repository),
            name=f"github-reviewer-wiki-refresh:{self._repository_lc}",
        )
        self._wiki_refresh_task = task

        def log_failure(completed: asyncio.Task[Optional[Path]]) -> None:
            if completed.cancelled():
                return
            try:
                completed.result()
            except Exception as exc:  # noqa: BLE001 - callback must consume task failures
                self.logger.warning("GitHubReviewer: wiki refresh failed: %s", exc, exc_info=True)

        task.add_done_callback(log_failure)
        return task

    async def _await_wiki_refresh(self, task: Optional[asyncio.Task[Optional[Path]]]) -> bool:
        """Wait at most ``GITHUB_REVIEW_WIKI_WAIT`` seconds; never cancel the refresh."""
        if task is None:
            return False
        done, _pending = await asyncio.wait({task}, timeout=conf.GITHUB_REVIEW_WIKI_WAIT)
        if not done:
            self.logger.info(
                "GitHubReviewer: wiki refresh still running after %ss; reviewing without fresh wiki context.",
                conf.GITHUB_REVIEW_WIKI_WAIT,
            )
            return False
        return True

    @asynccontextmanager
    async def _wiki_review_lease(self) -> AsyncIterator[bool]:
        """Hold a shared read lease on the plane for the duration of one review."""
        if self._wiki_cache is None or not self._wiki_context_available:
            yield False
            return
        async with AsyncExitStack() as stack:
            try:
                paths = await stack.enter_async_context(self._wiki_cache.read_lease(self.repository, timeout=0.0))
            except Exception as exc:  # noqa: BLE001 - wiki enrichment must fail closed
                self.logger.warning("GitHubReviewer: wiki read lease unavailable: %s", exc)
                paths = None
            yield paths is not None

    def _attach_wiki_toolkits(self, clone_root: Path) -> None:
        """Attach external-plane wiki toolkits once after a successful build."""
        if self._wiki_toolkits_attached or self._wiki_cache is None:
            return
        try:
            paths = self._wiki_cache.paths_for(self.repository)
            project_config = WikiProjectConfig(
                wiki_name=paths.slug,
                storage_dir=str(paths.plane_dir),
                backend="sqlite",
            )
            store = create_wiki_store(paths.plane_dir, wiki_name=paths.slug, backend="sqlite")
            structural = CodeStructuralToolkit(root=clone_root, store=store, config=project_config)
            wiki_config = WikiConfig(
                wiki_name=paths.slug,
                storage_dir=paths.plane_dir,
                storage_backend="sqlite",
            )
            wiki = LLMWikiToolkit(None, None, None, wiki_config, store=store, confine_sources=True)
            # Narrow both toolkits to their read surface. Set before
            # registration: tools are generated lazily on the first
            # get_tools(), so the exclusions still apply.
            structural.exclude_tools = _read_only_excludes(CodeStructuralToolkit, _STRUCTURAL_READ_TOOLS)
            wiki.exclude_tools = _read_only_excludes(LLMWikiToolkit, _WIKI_READ_TOOLS)
            self._attach_toolkit(structural, "Wiki structural")
            self._attach_toolkit(wiki, "Wiki")
            self._wiki_store = store
            self._wiki_toolkits_attached = True
            # Only now that the tools exist does the prompt describe them.
            self._document_wiki_tools(paths.slug)
            if self._llm is not None and hasattr(self._llm, "tool_manager"):
                self.sync_tools(self._llm)
        except Exception as exc:  # noqa: BLE001 - wiki tools are strictly optional
            self.logger.warning("GitHubReviewer: failed to attach wiki tools: %s", exc, exc_info=True)

    def _document_wiki_tools(self, wiki_name: str) -> None:
        """Append the knowledge-graph section to the system prompt.

        Called only once the toolkits are really registered, so a reviewer
        whose clone or build failed is never told about tools it does not
        have. ``ask()`` re-renders ``system_prompt_template`` on every
        call, so appending after ``configure()`` still reaches every
        subsequent review.

        Guarded rather than asserted: a prompt that cannot be extended
        must not fail an attach that already succeeded — the tools stay
        usable, they are just undocumented.

        Args:
            wiki_name: Plane name the LLM must pass to every ``wiki_*`` call.
        """
        template = getattr(self, "system_prompt_template", None)
        if not isinstance(template, str):
            self.logger.warning(
                "GitHubReviewer: wiki tools attached but the system prompt could not be "
                "extended (system_prompt_template is %s); the model will not be told they exist.",
                type(template).__name__,
            )
            return
        self.system_prompt_template = template + _WIKI_TOOLS_PROMPT.format(wiki_name=wiki_name)

    async def _attach_webhook_listener(self) -> None:
        """Hook ``self.handle_hook_event`` into the shared dispatcher."""
        if self.app is None:
            return
        hook = self.app.get(self.WEBHOOK_APP_KEY)
        if hook is None:
            self.logger.warning(
                "GitHubReviewer: aiohttp route for GitHub deliveries is "
                "not registered. Call "
                "GitHubReviewer.setup_webhook_route(app) from your sync "
                "app setup so deliveries can reach %s.",
                self.repository,
            )
            return

        listeners = self.app.setdefault(self.WEBHOOK_LISTENERS_KEY, [])
        if self.handle_hook_event not in listeners:
            listeners.append(self.handle_hook_event)

        # Start the hook exactly once per process, even when several
        # GitHubReviewer instances share the same route.
        if not self.app.get(self._WEBHOOK_STARTED_KEY, False):
            try:
                await hook.start()
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "GitHubReviewer: hook.start() raised: %s",
                    exc,
                )
            self.app[self._WEBHOOK_STARTED_KEY] = True

    def _attach_toolkit(self, toolkit: Any, name: str) -> None:
        """Register ``toolkit`` and extend ``self.tools`` with its exports."""
        if toolkit is None:
            return
        try:
            tools = self.tool_manager.register_toolkit(toolkit)
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "GitHubReviewer: failed to register %s tools: %s",
                name,
                exc,
                exc_info=True,
            )
            return
        if not tools:
            return
        if not hasattr(self, "tools") or self.tools is None:
            self.tools = []
        self.tools.extend(tools)

    def _build_git_toolkit(self) -> Optional[GitToolkit]:
        """Build a :class:`GitToolkit` for this reviewer.

        Reads ``GITHUB_AUTH_TYPE`` (default ``"pat"``) from configuration and
        routes to the appropriate constructor kwargs. Fails closed — returns
        ``None`` and emits an error log — when required configuration for the
        selected mode is absent or when ``GitToolkit.__init__`` raises.

        Returns:
            A configured :class:`GitToolkit`, or ``None`` when the reviewer
            should disable itself.
        """
        auth_type = (config.get("GITHUB_AUTH_TYPE") or "pat").lower()
        default_branch = config.get("GIT_DEFAULT_BRANCH", fallback="main")

        if auth_type == "pat":
            token = config.get("GITHUB_TOKEN")
            if not token:
                self.logger.error(
                    "GitHubReviewer: GITHUB_TOKEN is not set; the agent will "
                    "disable itself (no PR fetch/review/webhook calls)."
                )
                return None
            return GitToolkit(
                default_repository=self.repository,
                default_branch=default_branch,
                github_token=token,
            )

        if auth_type == "github_app":
            app_id_raw = config.get("GITHUB_APP_ID")
            installation_id_raw = config.get("GITHUB_APP_INSTALLATION_ID")
            private_key = config.get("GITHUB_APP_PRIVATE_KEY")
            private_key_path = config.get("GITHUB_APP_PRIVATE_KEY_PATH")

            missing = []
            if not app_id_raw:
                missing.append("GITHUB_APP_ID")
            if not installation_id_raw:
                missing.append("GITHUB_APP_INSTALLATION_ID")
            if not (private_key or private_key_path):
                missing.append("GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH")
            if missing:
                self.logger.error(
                    "GitHubReviewer: GITHUB_AUTH_TYPE=github_app but missing %s; "
                    "the agent will disable itself (no PR fetch/review/webhook calls).",
                    ", ".join(missing),
                )
                return None

            try:
                return GitToolkit(
                    default_repository=self.repository,
                    default_branch=default_branch,
                    auth_type="github_app",
                    app_id=int(app_id_raw),
                    installation_id=int(installation_id_raw),
                    private_key=private_key,
                    private_key_path=private_key_path,
                )
            except Exception as exc:  # noqa: BLE001 — fail closed
                self.logger.error(
                    "GitHubReviewer: failed to build GitHub App toolkit: %s. " "The agent will disable itself.",
                    exc,
                )
                return None

        self.logger.error(
            "GitHubReviewer: unknown GITHUB_AUTH_TYPE=%r (expected 'pat' or "
            "'github_app'); the agent will disable itself.",
            auth_type,
        )
        return None

    def _build_jira_toolkit(self) -> Optional[JiraToolkit]:
        """Build a service-account JiraToolkit.

        Per-user OAuth2 3LO is rejected: webhook events carry no caller, so
        :class:`OAuthCredentialResolver` would have no identity to resolve.
        When ``JIRA_AUTH_TYPE=oauth2_3lo`` is set globally for sibling
        agents, this method falls back to ``basic_auth`` using
        ``JIRA_USERNAME`` + ``JIRA_API_TOKEN``. If those credentials are
        absent, the toolkit is disabled (``None``) and the reviewer logs
        a clear error.
        """
        auth_type = (config.get("JIRA_AUTH_TYPE") or "").lower()
        if auth_type == "oauth2_3lo":
            self.logger.error(
                "GitHubReviewer: per-user OAuth2 3LO is not supported "
                "(webhook events have no caller identity). Falling back to "
                "service-account basic_auth via JIRA_USERNAME/JIRA_API_TOKEN."
            )
            auth_type = ""  # force the basic_auth fallback below

        effective = auth_type or "basic_auth"
        toolkit_kwargs: Dict[str, Any] = {
            "server_url": config.get("JIRA_INSTANCE"),
            "auth_type": effective,
            "default_project": self.jira_project,
        }
        if effective == "basic_auth":
            username = config.get("JIRA_USERNAME")
            password = config.get("JIRA_API_TOKEN")
            if not (username and password):
                self.logger.error(
                    "GitHubReviewer: basic_auth requires JIRA_USERNAME and " "JIRA_API_TOKEN; Jira lookups disabled."
                )
                return None
            toolkit_kwargs["username"] = username
            toolkit_kwargs["password"] = password
        elif effective == "token_auth":
            token = config.get("JIRA_SECRET_TOKEN") or config.get("JIRA_API_TOKEN")
            if not token:
                self.logger.error(
                    "GitHubReviewer: token_auth requires JIRA_SECRET_TOKEN or " "JIRA_API_TOKEN; Jira lookups disabled."
                )
                return None
            toolkit_kwargs["token"] = token
        return JiraToolkit(**toolkit_kwargs)

    @staticmethod
    def _describe_webhook_denial(result: Dict[str, Any]) -> str:
        """Explain, in operator terms, why GitHub refused the hooks endpoint.

        The old message blamed a missing ``admin:repo_hook`` scope, which sent
        debugging down the wrong path: the usual cause is the *role*, since
        repository webhooks need **admin** on the repo and a fine-grained token
        cannot grant more than its owner holds. ``ensure_webhook`` now returns
        the HTTP status, GitHub's own ``message`` and the
        ``x-accepted-github-permissions`` header; any of them can be missing
        (non-JSON body, pre-request failure), so each part is optional and the
        raw message is the last resort.
        """
        parts: List[str] = []
        status_code = result.get("status_code")
        if status_code:
            parts.append(f"HTTP {status_code}")
        api_message = result.get("api_message")
        if api_message:
            parts.append(str(api_message))
        required = result.get("required_permission")
        if required:
            parts.append(f"endpoint wants {required}")
        if status_code == 403:
            parts.append("repository webhooks also require the admin role on the repo")
        if not parts:
            return str(result.get("message") or "no detail returned by GitHub")
        return "; ".join(parts)

    async def _ensure_webhook_subscription(self) -> None:
        """Hybrid auto-subscription. No-op when ``webhook_public_url`` is unset."""
        if not self.webhook_public_url or self.git_toolkit is None:
            return
        try:
            result = await self.git_toolkit.ensure_webhook(
                webhook_url=self.webhook_public_url,
                repository=self.repository,
                secret=self.webhook_secret,
                events=["pull_request"],
            )
        except Exception as exc:  # noqa: BLE001 — never block startup
            self.logger.warning(
                "GitHubReviewer: ensure_webhook raised for %s: %s",
                self.repository,
                exc,
            )
            return

        status = result.get("status")
        if status == "created":
            self.logger.info(
                "GitHubReviewer: webhook registered on %s -> %s",
                self.repository,
                self.webhook_public_url,
            )
        elif status == "already_exists":
            self.logger.info(
                "GitHubReviewer: webhook already present on %s",
                self.repository,
            )
        elif status == "no_permission":
            self.logger.warning(
                "GitHubReviewer: cannot manage webhooks on %s (%s); " "configure the webhook manually pointing to %s.",
                self.repository,
                self._describe_webhook_denial(result),
                self.webhook_public_url,
            )
        else:
            self.logger.warning(
                "GitHubReviewer: ensure_webhook returned status=%s for %s: %s",
                status,
                self.repository,
                result.get("message"),
            )

    # ------------------------------------------------------------------
    # Hook entry point
    # ------------------------------------------------------------------

    async def handle_hook_event(self, event: HookEvent) -> Optional[Dict[str, Any]]:
        """Route :class:`HookEvent` instances from :class:`GitHubWebhookHook`."""
        if event.event_type not in (
            "github.pr_opened",
            "github.pr_reopened",
            "github.pr_synchronize",
        ):
            return None

        payload = event.payload or {}
        # Multi-tenant guard. GitHub's full_name is canonical, but operator
        # config may differ in case; compare lower-cased.
        repo = payload.get("repository")
        if repo and repo.lower() != self._repository_lc:
            return None

        return await self.review_pull_request(payload)

    # ------------------------------------------------------------------
    # Review logic
    # ------------------------------------------------------------------

    def _extract_ticket_key(self, *texts: str) -> Optional[str]:
        for text in texts:
            if not text:
                continue
            match = self._ticket_key_regex.search(text)
            if match:
                return match.group(0)
        return None

    async def review_pull_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single PR review and return a summary dict.

        Used both by :meth:`handle_hook_event` (via webhook) and as a public
        entry point for manual triggering / tests.

        Args:
            payload: Mapping with at least ``pr_number``, ``pr_body``,
                ``pr_title``, ``pr_url``, ``repository`` and ``head_sha``.

        Returns:
            A dict with ``status`` and the relevant artifacts (jira key,
            review id, alert results). On the unhappy path ``status`` is
            one of ``"no_ticket"``, ``"ticket_not_found"``,
            ``"already_reviewed"`` or ``"error"``.
        """
        pr_number = payload.get("pr_number")
        if pr_number is None:
            return {"status": "error", "reason": "missing pr_number"}

        repo = payload.get("repository") or self.repository
        repo_key = (repo.lower(), int(pr_number))
        head_sha = payload.get("head_sha")
        if head_sha and self._reviewed_shas.get(repo_key) == head_sha:
            self.logger.info(
                "PR %s#%s already reviewed at SHA %s; skipping.",
                repo,
                pr_number,
                head_sha,
            )
            return {
                "status": "already_reviewed",
                "pr_number": pr_number,
                "head_sha": head_sha,
            }

        ticket_key = self._extract_ticket_key(payload.get("pr_body") or "", payload.get("pr_title") or "")
        if not ticket_key:
            self.logger.info(
                "PR %s#%s does not reference a %s ticket; skipping.",
                repo,
                pr_number,
                self.jira_project,
            )
            outcome: Dict[str, Any] = {
                "status": "no_ticket",
                "pr_number": pr_number,
            }
            comment = await self._notify_missing_ticket(repo=repo, pr_number=pr_number, payload=payload)
            if comment is not None:
                outcome["comment"] = comment
            return outcome

        wiki_refresh = self._start_wiki_refresh(repo)

        ticket = await self._fetch_ticket(ticket_key)
        if ticket is None:
            return {
                "status": "ticket_not_found",
                "jira_key": ticket_key,
                "pr_number": pr_number,
            }

        diff_text, diff_truncated, diff_available = await self._fetch_diff(repo, pr_number)
        await self._await_wiki_refresh(wiki_refresh)

        async with self._wiki_review_lease() as wiki_leased:
            result = await self._ask_llm_for_review(
                payload=payload,
                ticket_key=ticket_key,
                ticket=ticket,
                diff_text=diff_text,
                diff_truncated=diff_truncated,
                diff_available=diff_available,
                use_wiki=wiki_leased,
            )

        outcome: Dict[str, Any] = {
            "status": "reviewed",
            "pr_number": pr_number,
            "repository": repo,
            "jira_key": ticket_key,
            "approve": result.approve,
            "discrepancies": [d.model_dump() for d in result.discrepancies],
            "summary": result.summary,
        }

        review_body = self._format_review_body(payload, ticket_key, result)
        event = "APPROVE" if result.approve else "REQUEST_CHANGES"
        # APPROVE has no actionable findings to alert about; only ping
        # Telegram when discrepancies were raised.
        should_post_review = self.git_toolkit is not None and (result.approve or result.discrepancies)
        if should_post_review:
            try:
                review_response = await self.git_toolkit.submit_pr_review(
                    pr_number=pr_number,
                    event=event,
                    body=review_body,
                    repository=repo,
                )
                outcome["review"] = review_response
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "GitHubReviewer: failed to submit %s review on %s#%s: %s",
                    event,
                    repo,
                    pr_number,
                    exc,
                    exc_info=True,
                )
                outcome["review_error"] = str(exc)

            if not result.approve and result.discrepancies:
                outcome["alerts"] = await self._notify_telegram_alert(payload, ticket_key, result)

        if head_sha:
            self._reviewed_shas[repo_key] = head_sha

        return outcome

    async def _notify_missing_ticket(
        self,
        *,
        repo: str,
        pr_number: int,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Leave a single PR comment when no Jira ticket key is referenced.

        Dedup is per-PR (not per-SHA): subsequent pushes without a ticket
        do not produce more comments. The deduplication set lives in
        memory and resets on process restart — that is intentional, so a
        new deploy can re-ping a stale PR if needed.

        Returns the API response from GitHub when a comment is posted,
        ``None`` when posting was skipped (already commented, no toolkit,
        post failed).
        """
        key = (repo.lower(), int(pr_number))
        if key in self._no_ticket_notified:
            return None
        if self.git_toolkit is None:
            self.logger.warning(
                "GitHubReviewer: cannot comment about missing %s ticket on " "%s#%s — git_toolkit is not configured.",
                self.jira_project,
                repo,
                pr_number,
            )
            return None

        body = self._format_no_ticket_comment(payload)
        try:
            response = await self.git_toolkit.add_pr_comment(
                pr_number=pr_number,
                body=body,
                repository=repo,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "GitHubReviewer: failed to post no-ticket comment on %s#%s: %s",
                repo,
                pr_number,
                exc,
                exc_info=True,
            )
            return None

        # Mark only on success so a transient API failure can be retried
        # by the next delivery.
        self._no_ticket_notified.add(key)
        return response

    def _format_no_ticket_comment(self, payload: Dict[str, Any]) -> str:
        """Render the comment posted when the PR references no Jira ticket."""
        author = payload.get("author")
        salutation = f"@{author} " if author else ""
        return (
            f"### Automated review skipped — no Jira ticket referenced\n\n"
            f"{salutation}This pull request does not reference a "
            f"`{self.jira_project}-<number>` Jira ticket in its title or "
            f"description, so the automated reviewer cannot compare the "
            f"changes against the acceptance criteria.\n\n"
            f"**To unblock review**, edit the PR title or description to "
            f"include a key from the `{self.jira_project}` project — for "
            f"example `{self.jira_project}-123` — and push a new commit "
            f"to re-trigger the reviewer.\n\n"
            f"_Posted by the GitHubReviewer agent._"
        )

    async def _fetch_ticket(
        self,
        ticket_key: str,
        *,
        fields: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch a Jira issue, or ``None`` when it cannot be read.

        Args:
            ticket_key: The issue key, e.g. ``NAV-123``.
            fields: Comma-separated Jira field list. Defaults to
                :attr:`_jira_fields`; the strict gate passes
                :attr:`_jira_strict_fields`, which also carries the assignee.
        """
        if self.jira_toolkit is None:
            self.logger.warning(
                "GitHubReviewer: jira_toolkit unavailable; cannot fetch %s",
                ticket_key,
            )
            return None
        try:
            envelope = await self.jira_toolkit.jira_get_issue(
                issue=ticket_key,
                fields=fields or self._jira_fields,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "GitHubReviewer: jira_get_issue(%s) failed: %s",
                ticket_key,
                exc,
                exc_info=True,
            )
            return None

        envelope = envelope or {}
        if envelope.get("status") != "ok":
            return None
        return envelope.get("data")

    async def _fetch_diff(self, repo: str, pr_number: int) -> Tuple[str, bool, bool]:
        """Return ``(diff_text, truncated, available)``.

        ``available`` is ``False`` when the diff could not be retrieved
        (no toolkit or an HTTP error) so the LLM can distinguish a real
        empty diff from "we just don't know."
        """
        if self.git_toolkit is None:
            return ("", False, False)
        try:
            data = await self.git_toolkit.get_pull_request_diff(
                pr_number=pr_number,
                repository=repo,
                max_bytes=self.max_diff_bytes,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "GitHubReviewer: get_pull_request_diff failed for %s#%s: %s",
                repo,
                pr_number,
                exc,
            )
            return ("", False, False)
        return (data.get("diff", ""), bool(data.get("truncated")), True)

    def _clamp(self, value: str) -> str:
        """Clamp a ticket field to :attr:`max_ticket_bytes`."""
        if not value:
            return ""
        if len(value) <= self.max_ticket_bytes:
            return value
        return value[: self.max_ticket_bytes] + "\n[... truncated ...]"

    async def _build_wiki_context(
        self, payload: Dict[str, Any], diff_text: str, *, enabled: bool = True
    ) -> Optional[str]:
        """Return token-bounded local-wiki context for a pull request.

        The reviewer only searches the store attached after a successful
        refresh of its own repository. Failures are deliberately contained so
        the existing diff-only review path remains available.
        """
        if (
            not enabled
            or not self._wiki_context_available
            or self._wiki_store is None
            or not self._wiki_branch
            or self._wiki_built_at is None
        ):
            return None

        budget_tokens = conf.GITHUB_REVIEW_WIKI_CONTEXT_TOKENS
        header = _WIKI_CONTEXT_HEADER.format(
            branch=self._wiki_branch,
            built_at=self._wiki_built_at.isoformat(),
        )
        if budget_tokens <= 0 or estimate_tokens(header) > budget_tokens:
            return None

        title = payload.get("pr_title")
        title_text = title if isinstance(title, str) else ""
        changed_paths: list[str] = []
        for _old_path, new_path in re.findall(r"^diff --git a/(.+?) b/(.+?)$", diff_text, flags=re.MULTILINE):
            if new_path not in changed_paths:
                changed_paths.append(new_path)
        query_parts = [part for part in (title_text, *changed_paths) if part]
        if not query_parts:
            return None
        query = "PR title: " + title_text + "\nChanged paths:\n" + "\n".join(changed_paths)

        try:
            search = WikiCombinedSearch(None, None, store=self._wiki_store)
            results = await search.search(query, mode="combined", top_k=10)
            if not results:
                return None

            separator = "\n\n"
            body_budget = budget_tokens - estimate_tokens(header) - estimate_tokens(separator)
            if body_budget <= 0:
                return None
            packed = pack_results(results, budget_tokens=body_budget)
            if not packed.text or not packed.results_packed:
                return None

            body, _ = truncate_to_tokens(packed.text, body_budget)
            context = f"{header}{separator}{body}"
            while estimate_tokens(context) > budget_tokens:
                next_budget = estimate_tokens(body) - (estimate_tokens(context) - budget_tokens)
                if next_budget <= 0:
                    return None
                shortened, _ = truncate_to_tokens(body, next_budget)
                if shortened == body or estimate_tokens(shortened) >= estimate_tokens(body):
                    # truncate_to_tokens is heuristic (chars/4) and can under-cut
                    # multi-byte text; fall back to a proportional character cut.
                    shortened = body[: max(0, int(len(body) * next_budget / max(estimate_tokens(body), 1)) - 1)]
                    if not shortened or shortened == body:
                        return None
                body = shortened
                context = f"{header}{separator}{body}"
            return context
        except Exception as exc:  # noqa: BLE001 - context enrichment is optional
            self.logger.warning("GitHubReviewer: wiki context unavailable: %s", exc, exc_info=True)
            return None

    async def _ask_llm_for_review(
        self,
        *,
        payload: Dict[str, Any],
        ticket_key: str,
        ticket: Dict[str, Any],
        diff_text: str,
        diff_truncated: bool,
        diff_available: bool,
        use_wiki: bool = True,
    ) -> PRReviewResult:
        fields = (ticket or {}).get("fields") or {}
        summary = _flatten_adf(fields.get("summary")) or ""
        description = self._clamp(_flatten_adf(fields.get("description")))
        # The acceptance-criteria custom field id was resolved in __init__
        # from JIRA_ACCEPTANCE_CRITERIA_FIELD (fallback: customfield_10100)
        # and is included in the Jira ``fields=`` request.
        acceptance_criteria = self._clamp(_flatten_adf(fields.get(self._ac_field_id))) or "(not provided)"

        if diff_available:
            diff_block = diff_text or "(empty diff — PR adds/removes nothing)"
            header = f"=== PR diff (truncated={diff_truncated}) ==="
        else:
            diff_block = (
                "(diff unavailable — could not be retrieved from GitHub. " "Do NOT conclude that the PR is empty.)"
            )
            header = "=== PR diff (unavailable) ==="

        wiki_context = await self._build_wiki_context(payload, diff_text, enabled=use_wiki)
        wiki_block = f"{wiki_context}\n\n" if wiki_context else ""
        question = (
            f"Review pull request {payload.get('repository')}#"
            f"{payload.get('pr_number')} against Jira ticket {ticket_key}.\n\n"
            f"PR title: {payload.get('pr_title', '')}\n"
            f"PR body:\n{payload.get('pr_body', '')}\n\n"
            f"=== Jira ticket {ticket_key} ===\n"
            f"Summary: {summary}\n\n"
            f"Description:\n{description}\n\n"
            f"Acceptance Criteria:\n{acceptance_criteria}\n\n"
            f"{header}\n"
            f"{diff_block}\n\n"
            f"{wiki_block}"
            "Compare them and return a PRReviewResult JSON object."
        )

        # FEAT-182: pass max_iterations to the LLM client to enforce the cap.
        # base.py's ask() now forwards max_iterations to any client whose
        # ask() signature declares the parameter (currently Google/Gemini only).
        # For other backends the cap is not enforced at the client level, but
        # the post-call tool-count check below will emit a WARNING when
        # self.max_review_tool_calls is reached.
        try:
            response = await self.ask(
                question=question,
                structured_output=PRReviewResult,
                max_iterations=self.max_review_tool_calls + 1,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "GitHubReviewer: LLM review failed for PR %s: %s",
                payload.get("pr_number"),
                exc,
                exc_info=True,
            )
            return PRReviewResult(
                jira_key=ticket_key,
                discrepancies=[],
                summary=f"LLM review failed: {exc}",
                approve=False,
            )

        # FEAT-182: detect tool-call cap hit and emit a WARNING log.
        tool_calls = getattr(response, "tool_calls", None) or []
        tool_call_count = len(tool_calls)
        if tool_call_count >= self.max_review_tool_calls and self.max_review_tool_calls > 0:
            tool_names = [getattr(tc, "name", str(tc)) for tc in tool_calls]
            self.logger.warning(
                "GitHubReviewer: PR %s#%s hit tool-call cap (count=%d, tools=%s)",
                payload.get("repository"),
                payload.get("pr_number"),
                tool_call_count,
                tool_names,
            )

        output = getattr(response, "output", response)
        if isinstance(output, PRReviewResult):
            output.jira_key = output.jira_key or ticket_key
            return output
        if isinstance(output, dict):
            try:
                result = PRReviewResult.model_validate(output)
            except Exception:  # noqa: BLE001
                result = PRReviewResult(
                    jira_key=ticket_key,
                    discrepancies=[],
                    summary=str(output),
                    approve=False,
                )
            result.jira_key = result.jira_key or ticket_key
            return result
        return PRReviewResult(
            jira_key=ticket_key,
            discrepancies=[],
            summary=str(output),
            approve=False,
        )

    def _format_review_body(
        self,
        payload: Dict[str, Any],
        ticket_key: str,
        result: PRReviewResult,
    ) -> str:
        """Render the GitHub review body in GitHub-flavored Markdown.

        Note: this targets GitHub, *not* Telegram, so Markdown is fine —
        only the Telegram messages need entity escaping.
        """
        if result.approve:
            header = f"## Automated review — acceptance criteria satisfied ({ticket_key})"
            default_summary = "All acceptance criteria are addressed by this PR."
        else:
            header = f"## Automated review — discrepancies vs. {ticket_key}"
            default_summary = "Discrepancies detected against the linked ticket."
        lines: List[str] = [
            header,
            "",
            result.summary or default_summary,
            "",
        ]
        if result.discrepancies:
            lines.append("### Findings")
            for d in result.discrepancies:
                lines.append(f"- **[{d.severity.upper()}] {d.criterion}** — {d.issue}")
            lines.append("")
        lines.extend(
            [
                f"Linked Jira ticket: {ticket_key}",
                "",
                "_Posted by the GitHubReviewer agent. Push a follow-up "
                "commit and the next webhook delivery will re-trigger this "
                "review._",
            ]
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Telegram notifications
    # ------------------------------------------------------------------

    async def _notify_telegram_alert(
        self,
        payload: Dict[str, Any],
        ticket_key: str,
        result: PRReviewResult,
    ) -> Dict[str, Any]:
        bot = self._get_telegram_bot()
        if bot is None:
            return {"sent": 0, "reason": "no telegram wrapper"}
        if not self.alert_chat_ids:
            return {"sent": 0, "reason": "no alert_chat_ids configured"}

        text = self._format_alert_message(payload, ticket_key, result)
        sent = 0
        errors: List[str] = []
        for chat_id in self.alert_chat_ids:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                sent += 1
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "GitHubReviewer: failed to alert chat %s: %s",
                    chat_id,
                    exc,
                )
                errors.append(f"{chat_id}: {exc}")
        return {"sent": sent, "errors": errors}

    def _get_telegram_bot(self):
        if self._wrapper is None:
            return None
        return getattr(self._wrapper, "bot", None)

    def _format_alert_message(
        self,
        payload: Dict[str, Any],
        ticket_key: str,
        result: PRReviewResult,
    ) -> str:
        """Build a Telegram HTML message — all user-data interpolations
        are ``html.escape``-d so a PR title like ``feat: X_y <z>`` does not
        break parsing (Telegram returns 400 on malformed entities).
        """
        counts = Counter(d.severity for d in result.discrepancies)
        repo = html.escape(str(payload.get("repository") or ""))
        title = html.escape(str(payload.get("pr_title") or ""))
        url = html.escape(str(payload.get("pr_url") or ""), quote=True)
        ticket = html.escape(ticket_key)
        summary = html.escape(result.summary or "(no summary)")
        lines = [
            "<b>PR review — discrepancies</b>",
            f"Repo: <code>{repo}</code>",
            f'PR: <a href="{url}">{title}</a>',
            f"Ticket: <code>{ticket}</code>",
            (
                f"Severity: blocker={counts.get('blocker', 0)}, "
                f"major={counts.get('major', 0)}, "
                f"minor={counts.get('minor', 0)}"
            ),
            "",
            summary,
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Strict on-demand review (/review_pr)
    # ------------------------------------------------------------------

    #: Heuristic for "this check is a test suite" — only shapes the wording of
    #: the comment and feeds ``require_checks``; the gate scores every check.
    _TEST_CHECK_RE = re.compile(r"test|pytest|spec|unit|e2e|coverage", re.IGNORECASE)
    #: ``https://github.com/owner/repo/pull/123`` (trailing path/query ignored).
    _PR_URL_RE = re.compile(
        r"^(?:https?://)?(?:www\.)?github\.com/(?P<repo>[\w.-]+/[\w.-]+)/pull/(?P<number>\d+)",
        re.IGNORECASE,
    )
    #: ``owner/repo#123`` or ``owner/repo/pull/123`` without a scheme.
    _PR_SLUG_RE = re.compile(r"^(?P<repo>[\w.-]+/[\w.-]+?)(?:#|/pull/)(?P<number>\d+)$")
    #: A bare ``#123`` / ``123`` — resolved against the configured repository.
    _PR_NUMBER_RE = re.compile(r"^#?(?P<number>\d+)$")

    @classmethod
    def _parse_pr_target(cls, text: str) -> Tuple[Optional[str], Optional[int], Optional[str]]:
        """Resolve a user-typed PR reference to ``(repository, number, error)``.

        Accepts a full PR URL, ``owner/repo#123``, ``owner/repo/pull/123`` or a
        bare number (which uses the configured repository). Everything after
        the first whitespace is ignored, so a pasted URL followed by a comment
        still parses.

        Returns:
            ``(repo, number, None)`` on success — ``repo`` is ``None`` when the
            caller must fall back to :attr:`repository` — or
            ``(None, None, message)`` with an operator-facing explanation.
        """
        raw = (text or "").strip()
        if not raw:
            return (None, None, "no pull request given")
        token = raw.split()[0].strip().rstrip(".,;")

        match = cls._PR_URL_RE.match(token)
        if match:
            return (match.group("repo"), int(match.group("number")), None)
        match = cls._PR_SLUG_RE.match(token)
        if match:
            return (match.group("repo"), int(match.group("number")), None)
        match = cls._PR_NUMBER_RE.match(token)
        if match:
            return (None, int(match.group("number")), None)
        # A repository link with no PR number is the most likely mistake, so
        # name it instead of printing the generic usage line.
        if re.match(r"^(?:https?://)?(?:www\.)?github\.com/[\w.-]+/[\w.-]+/?$", token, re.IGNORECASE):
            return (None, None, "that is a repository link, not a pull request link")
        return (None, None, f"could not read a pull request from {token!r}")

    async def _fetch_pr_payload(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]]:
        """Build the review payload for a PR from the GitHub API.

        Returns the same shape the webhook delivers (so the review pipeline is
        fed identically either way), plus ``draft`` and ``state``, or ``None``
        when the PR could not be read.
        """
        if self.git_toolkit is None:
            return None
        try:
            pr = await self.git_toolkit.get_pull_request(pr_number=pr_number, repository=repo)
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "GitHubReviewer: cannot read %s#%s: %s",
                repo,
                pr_number,
                exc,
                exc_info=True,
            )
            return None
        pr = pr or {}
        return {
            "repository": repo,
            "pr_number": pr_number,
            "pr_title": pr.get("title") or "",
            "pr_body": pr.get("body") or "",
            "pr_url": pr.get("html_url") or "",
            "head_sha": ((pr.get("head") or {}).get("sha")) or "",
            "author": ((pr.get("user") or {}).get("login")) or "",
            "draft": bool(pr.get("draft")),
            "state": pr.get("state") or "",
        }

    @classmethod
    def _summarize_checks(cls, raw: Optional[Dict[str, Any]]) -> PRChecksSummary:
        """Fold a ``get_pr_checks`` payload into a :class:`PRChecksSummary`.

        Pure: every count comes from the payload, nothing is fetched. Checks
        still running are counted but excluded from ``pass_ratio``, so a
        pipeline that is half green and half pending does not read as 50%.
        """
        if not raw:
            return PRChecksSummary(available=False, reason="no CI data returned")
        denied = [str(name) for name in (raw.get("denied") or [])]
        # The toolkit decides availability: it knows whether BOTH CI APIs were
        # refused (unknown) or only one (partial, still usable).
        if raw.get("available") is False:
            return PRChecksSummary(
                available=False,
                denied=denied,
                reason=raw.get("reason") or "CI could not be read",
            )
        checks = raw.get("checks") or []
        success = int(raw.get("success") or 0)
        failure = int(raw.get("failure") or 0)
        pending = int(raw.get("pending") or 0)
        completed = success + failure
        return PRChecksSummary(
            available=True,
            declared=bool(checks),
            total=int(raw.get("total") or len(checks)),
            success=success,
            failure=failure,
            pending=pending,
            pass_ratio=(success / completed) if completed else 0.0,
            failing=[str(c.get("name") or "?") for c in checks if c.get("state") == "failure"],
            running=[str(c.get("name") or "?") for c in checks if c.get("state") == "pending"],
            test_checks=sum(1 for c in checks if cls._TEST_CHECK_RE.search(str(c.get("name") or ""))),
            denied=denied,
            reason=raw.get("reason"),
        )

    async def _fetch_checks(self, repo: str, pr_number: int, head_sha: str = "") -> PRChecksSummary:
        """Read the PR's CI checks, never raising.

        An unreadable CI is reported as ``available=False`` rather than as a
        green or a red pipeline: the gate must not approve a PR because the
        checks endpoint happened to 500, nor draft it for the same reason.
        """
        if self.git_toolkit is None:
            return PRChecksSummary(available=False, reason="git_toolkit is not configured")
        try:
            raw = await self.git_toolkit.get_pr_checks(
                pr_number=pr_number,
                repository=repo,
                head_sha=head_sha or None,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "GitHubReviewer: cannot read checks for %s#%s: %s",
                repo,
                pr_number,
                exc,
            )
            return PRChecksSummary(available=False, reason=str(exc))
        return self._summarize_checks(raw)

    def _merge_verdict(self, result: PRReviewResult, checks: PRChecksSummary) -> MergeVerdict:
        """Decide whether a reviewed PR may stay mergeable.

        Two independent gates, both of which must pass:

        1. **Jira** — the review approved it and raised no blocker/major
           discrepancy against the ticket's acceptance criteria.
        2. **Tests** — the declared checks are green, or green enough
           (:attr:`min_check_pass_ratio`, "all OK or a great part").

        A pipeline still running — or a CI status GitHub would not hand over —
        produces ``defer``: the PR is left exactly as it is, because approving
        it would claim test evidence nobody saw, and drafting it would punish a
        developer for an outage or a missing token scope.
        """
        reasons: List[str] = []
        warnings: List[str] = []

        if not result.approve:
            reasons.append(result.summary.strip() or "the review did not confirm the acceptance criteria are met")
        for d in result.discrepancies:
            line = f"[{d.severity.upper()}] {d.criterion} — {d.issue}"
            if d.severity in ("blocker", "major"):
                reasons.append(line)
            else:
                warnings.append(line)

        unknown_ci = False
        if not checks.available:
            warnings.append(
                f"CI status could not be read ({checks.reason or 'unknown error'}); tests were not verified"
            )
            unknown_ci = True
        elif not checks.declared:
            if checks.denied:
                # Zero checks because an endpoint was refused is NOT "this repo
                # has no CI": the evidence may exist and simply be invisible to
                # this token, so the verdict is unknown, never a free pass.
                warnings.append(f"no CI check was visible to this token — {checks.reason}")
                unknown_ci = True
            else:
                message = "the head commit declares no CI checks, so no test evidence could be verified"
                (reasons if self.require_checks else warnings).append(message)
        else:
            if checks.failure and checks.pass_ratio < self.min_check_pass_ratio:
                names = ", ".join(checks.failing[:10]) or "unnamed checks"
                reasons.append(
                    f"{checks.failure} of {checks.success + checks.failure} completed checks are failing "
                    f"({checks.pass_ratio:.0%} green, {self.min_check_pass_ratio:.0%} required): {names}"
                )
            elif checks.failure:
                names = ", ".join(checks.failing[:10]) or "unnamed checks"
                warnings.append(
                    f"{checks.failure} check(s) are failing but {checks.pass_ratio:.0%} of the completed checks are "
                    f"green, at or above the {self.min_check_pass_ratio:.0%} bar: {names}"
                )
            if not checks.test_checks:
                warnings.append("none of the declared checks looks like a test suite")
            if checks.denied:
                # One API answered, the other was refused: say so, because the
                # verdict rests on a partial picture. Not deferred — there IS
                # test evidence here, just possibly not all of it.
                warnings.append(f"part of the CI picture is missing — {checks.reason}")
            if checks.pending:
                unknown_ci = True

        # Unknown test evidence defers rather than approves: a pipeline still
        # running, a CI status GitHub refused to hand over, or checks hidden
        # behind a missing permission is not a pass. Either way it only defers
        # when nothing else already disqualifies the PR — a blocker finding is
        # reason enough to draft it now.
        defer = bool(unknown_ci and not reasons)
        return MergeVerdict(mergeable=not reasons and not defer, defer=defer, reasons=reasons, warnings=warnings)

    def _format_checks_line(self, checks: PRChecksSummary) -> str:
        """One-line CI summary shared by the comment and the Telegram alerts."""
        if not checks.available:
            return f"CI: unreadable ({checks.reason or 'unknown error'})"
        if not checks.declared:
            suffix = f" (and {', '.join(checks.denied)} denied to this token)" if checks.denied else ""
            return f"CI: no checks declared on the head commit{suffix}"
        partial = f", {', '.join(checks.denied)} denied" if checks.denied else ""
        return (
            f"CI: {checks.success} passed, {checks.failure} failed, {checks.pending} running "
            f"({checks.pass_ratio:.0%} of completed green{partial})"
        )

    def _format_block_comment(
        self,
        payload: Dict[str, Any],
        ticket_key: str,
        result: PRReviewResult,
        checks: PRChecksSummary,
        verdict: MergeVerdict,
    ) -> str:
        """Render the PR comment that explains why the PR is not mergeable.

        GitHub-flavored Markdown, so no entity escaping — unlike the Telegram
        messages built below.
        """
        author = payload.get("author")
        salutation = f"@{author} " if author else ""
        lines: List[str] = [
            f"## Automated review — not mergeable ({ticket_key})",
            "",
            f"{salutation}this pull request was converted to **draft** because it does not yet satisfy "
            f"what `{ticket_key}` asks for. The reasons are below; fix them, push, and mark the PR "
            f"ready for review (or run the reviewer again) to clear this.",
            "",
            "### Why this is blocked",
        ]
        lines.extend(f"{i}. {reason}" for i, reason in enumerate(verdict.reasons, start=1))
        lines.extend(["", f"**{self._format_checks_line(checks)}**"])
        if checks.failing:
            lines.append("")
            lines.append("Failing checks: " + ", ".join(f"`{name}`" for name in checks.failing[:20]))
        if verdict.warnings:
            lines.extend(["", "### Also worth fixing (non-blocking)"])
            lines.extend(f"- {warning}" for warning in verdict.warnings)
        if result.summary:
            lines.extend(["", "### Review summary", "", result.summary])
        lines.extend(
            [
                "",
                f"Linked Jira ticket: {ticket_key}",
                "",
                "_Posted by the GitHubReviewer agent._",
            ]
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Assignee resolution + alerts for a blocked PR
    # ------------------------------------------------------------------

    def _roster(self) -> List[Dict[str, Any]]:
        """The configured Jira↔Telegram roster (:data:`parrot.conf.JIRA_USERS`).

        Read through the module so a test can monkeypatch ``conf.JIRA_USERS``,
        and defensively filtered to dicts — one malformed entry must not break
        the notification path of a real review.
        """
        raw = getattr(conf, "JIRA_USERS", None) or []
        return [entry for entry in raw if isinstance(entry, dict)]

    def _resolve_assignee(self, ticket: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Find the roster entry for a ticket's assignee, or ``None``.

        Matches on every identifier the two sides can share — Jira's
        ``emailAddress`` against ``jira_username``/``username``, its
        ``accountId`` against ``jira_account_id``/``id``, and ``displayName``
        against ``name`` — because JIRA_USERS entries are hand-written and
        rarely carry all three.
        """
        assignee = (((ticket or {}).get("fields") or {}).get("assignee")) or {}
        if not assignee:
            return None
        account_id = str(assignee.get("accountId") or "").strip().lower()
        email = str(assignee.get("emailAddress") or "").strip().lower()
        display = str(assignee.get("displayName") or "").strip().lower()
        for entry in self._roster():
            emails = {
                str(entry.get("jira_username") or "").strip().lower(),
                str(entry.get("username") or "").strip().lower(),
            }
            accounts = {
                str(entry.get("jira_account_id") or "").strip().lower(),
                str(entry.get("id") or "").strip().lower(),
            }
            names = {str(entry.get("name") or "").strip().lower()}
            if (email and email in emails) or (account_id and account_id in accounts) or (display and display in names):
                return entry
        return None

    @staticmethod
    def _telegram_mention(entry: Dict[str, Any]) -> str:
        """Render a Telegram HTML mention for a roster entry.

        Prefers a real ``@username`` when the entry declares one; otherwise
        falls back to a ``tg://user?id=`` link, which notifies the user in a
        group exactly like an @mention does and is the only way to mention
        someone whose Telegram username is unknown.
        """
        name = html.escape(str(entry.get("name") or "developer"))
        username = str(entry.get("telegram_username") or "").strip().lstrip("@")
        if username:
            return f"@{html.escape(username)}"
        chat_id = str(entry.get("telegram_chat_id") or "").strip()
        if chat_id:
            return f'<a href="tg://user?id={html.escape(chat_id, quote=True)}">@{name}</a>'
        return f"@{name}"

    def _format_blocked_message(
        self,
        payload: Dict[str, Any],
        ticket_key: str,
        checks: PRChecksSummary,
        verdict: MergeVerdict,
        *,
        mention: Optional[str] = None,
    ) -> str:
        """Telegram HTML for a blocked PR — private DM or public channel.

        ``mention`` is prepended for the channel copy so the assignee is
        pinged there too. Every interpolated value is ``html.escape``-d: a PR
        title like ``feat: X_y <z>`` otherwise makes Telegram answer 400.
        """
        repo = html.escape(str(payload.get("repository") or ""))
        title = html.escape(str(payload.get("pr_title") or ""))
        url = html.escape(str(payload.get("pr_url") or ""), quote=True)
        number = html.escape(str(payload.get("pr_number") or ""))
        lines: List[str] = []
        if mention:
            lines.append(f"{mention} — your pull request was marked as <b>draft</b>")
        else:
            lines.append("<b>Your pull request was marked as draft</b>")
        lines.extend(
            [
                f"Repo: <code>{repo}</code>",
                f'PR: <a href="{url}">#{number} {title}</a>',
                f"Ticket: <code>{html.escape(ticket_key)}</code>",
                html.escape(self._format_checks_line(checks)),
                "",
                "<b>Why</b>",
            ]
        )
        lines.extend(f"{i}. {html.escape(reason)}" for i, reason in enumerate(verdict.reasons, start=1))
        lines.extend(
            [
                "",
                "Fix these, push, and mark the PR ready for review — the full explanation is in a comment on the PR.",
            ]
        )
        return "\n".join(lines)

    async def _notify_blocked_pr(
        self,
        payload: Dict[str, Any],
        ticket_key: str,
        checks: PRChecksSummary,
        verdict: MergeVerdict,
        ticket: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Tell the assignee and the public channel that a PR was drafted.

        Three deliveries, each independent so one failure cannot swallow the
        others: a private DM to the assignee (when the ticket's assignee maps
        to a roster entry), and one message to
        :attr:`public_channel_id` that mentions them.

        Returns a report with ``assignee``, ``dm`` and ``channel`` keys.
        """
        report: Dict[str, Any] = {"assignee": None, "dm": {"sent": False}, "channel": {"sent": False}}
        bot = self._get_telegram_bot()
        if bot is None:
            report["reason"] = "no telegram wrapper"
            return report

        entry = self._resolve_assignee(ticket)
        mention: Optional[str] = None
        if entry is not None:
            report["assignee"] = entry.get("name") or entry.get("jira_username")
            mention = self._telegram_mention(entry)
            chat_id = entry.get("telegram_chat_id")
            if chat_id:
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=self._format_blocked_message(payload, ticket_key, checks, verdict),
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    report["dm"] = {"sent": True, "chat_id": chat_id}
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning(
                        "GitHubReviewer: could not DM %s (chat %s) about %s#%s: %s",
                        report["assignee"],
                        chat_id,
                        payload.get("repository"),
                        payload.get("pr_number"),
                        exc,
                    )
                    report["dm"] = {"sent": False, "chat_id": chat_id, "error": str(exc)}
            else:
                report["dm"] = {"sent": False, "reason": "roster entry has no telegram_chat_id"}
        else:
            self.logger.info(
                "GitHubReviewer: %s has no JIRA_USERS entry for its assignee; no private notice sent.",
                ticket_key,
            )
            report["dm"] = {"sent": False, "reason": "assignee not in JIRA_USERS"}

        if not self.public_channel_id:
            report["channel"] = {"sent": False, "reason": "no public channel configured"}
            return report
        try:
            await bot.send_message(
                chat_id=self.public_channel_id,
                text=self._format_blocked_message(payload, ticket_key, checks, verdict, mention=mention),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            report["channel"] = {"sent": True, "chat_id": self.public_channel_id}
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "GitHubReviewer: could not post the draft notice for %s#%s to channel %s: %s",
                payload.get("repository"),
                payload.get("pr_number"),
                self.public_channel_id,
                exc,
            )
            report["channel"] = {"sent": False, "chat_id": self.public_channel_id, "error": str(exc)}
        return report

    # ------------------------------------------------------------------
    # The gate itself
    # ------------------------------------------------------------------

    async def strict_review_pull_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Review a PR and enforce the verdict on GitHub.

        The same review pipeline as :meth:`review_pull_request` — ticket
        lookup, diff, wiki-assisted LLM comparison against the acceptance
        criteria — plus the CI gate and the consequences:

        * **mergeable** → an ``APPROVE`` review.
        * **deferred** (checks still running) → a ``COMMENT`` review; the PR
          is left untouched.
        * **not mergeable** → the PR is converted to a draft, a comment
          explains why, and the assignee is notified privately and in the
          public channel.

        The webhook path deliberately keeps its own, gentler orchestration
        (:meth:`review_pull_request` never drafts a PR), so this method does
        not reuse it; both share every underlying helper.

        Args:
            payload: Review payload — ``repository``, ``pr_number``,
                ``pr_title``, ``pr_body``, ``pr_url``, ``head_sha``,
                ``author``.

        Returns:
            ``{"status": ..., ...}`` where ``status`` is ``approved``,
            ``deferred``, ``blocked``, ``no_ticket``, ``ticket_not_found`` or
            ``error``.
        """
        pr_number = payload.get("pr_number")
        if pr_number is None:
            return {"status": "error", "reason": "missing pr_number"}
        repo = payload.get("repository") or self.repository

        ticket_key = self._extract_ticket_key(payload.get("pr_body") or "", payload.get("pr_title") or "")
        if not ticket_key:
            outcome: Dict[str, Any] = {"status": "no_ticket", "repository": repo, "pr_number": pr_number}
            comment = await self._notify_missing_ticket(repo=repo, pr_number=pr_number, payload=payload)
            if comment is not None:
                outcome["comment"] = comment
            return outcome

        wiki_refresh = self._start_wiki_refresh(repo)
        ticket = await self._fetch_ticket(ticket_key, fields=self._jira_strict_fields)
        if ticket is None:
            await self._await_wiki_refresh(wiki_refresh)
            return {
                "status": "ticket_not_found",
                "repository": repo,
                "pr_number": pr_number,
                "jira_key": ticket_key,
            }

        diff_text, diff_truncated, diff_available = await self._fetch_diff(repo, pr_number)
        checks = await self._fetch_checks(repo, int(pr_number), str(payload.get("head_sha") or ""))
        await self._await_wiki_refresh(wiki_refresh)

        async with self._wiki_review_lease() as wiki_leased:
            result = await self._ask_llm_for_review(
                payload=payload,
                ticket_key=ticket_key,
                ticket=ticket,
                diff_text=diff_text,
                diff_truncated=diff_truncated,
                diff_available=diff_available,
                use_wiki=wiki_leased,
            )

        verdict = self._merge_verdict(result, checks)
        outcome = {
            "status": "approved" if verdict.mergeable else ("deferred" if verdict.defer else "blocked"),
            "repository": repo,
            "pr_number": pr_number,
            "jira_key": ticket_key,
            "approve": result.approve,
            "discrepancies": [d.model_dump() for d in result.discrepancies],
            "summary": result.summary,
            "checks": checks.model_dump(),
            "verdict": verdict.model_dump(),
        }
        if self.git_toolkit is None:
            outcome["review_error"] = "git_toolkit is not configured"
            return outcome

        if verdict.defer:
            await self._submit_review(
                repo,
                int(pr_number),
                "COMMENT",
                self._format_deferred_body(payload, ticket_key, checks),
                outcome,
            )
            self.logger.info(
                "GitHubReviewer: %s#%s deferred — %d check(s) still running.",
                repo,
                pr_number,
                checks.pending,
            )
            return outcome

        if verdict.mergeable:
            await self._submit_review(
                repo,
                int(pr_number),
                "APPROVE",
                self._format_review_body(payload, ticket_key, result),
                outcome,
            )
            self.logger.info("GitHubReviewer: %s#%s approved by the strict gate.", repo, pr_number)
            return outcome

        # Blocked: draft first, so the PR stops being mergeable before anyone
        # reads the explanation.
        try:
            outcome["draft"] = await self.git_toolkit.convert_pr_to_draft(pr_number=int(pr_number), repository=repo)
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "GitHubReviewer: could not convert %s#%s to draft: %s",
                repo,
                pr_number,
                exc,
                exc_info=True,
            )
            outcome["draft_error"] = str(exc)

        body = self._format_block_comment(payload, ticket_key, result, checks, verdict)
        try:
            outcome["comment"] = await self.git_toolkit.add_pr_comment(
                pr_number=int(pr_number),
                body=body,
                repository=repo,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "GitHubReviewer: could not comment on %s#%s: %s",
                repo,
                pr_number,
                exc,
                exc_info=True,
            )
            outcome["comment_error"] = str(exc)

        await self._submit_review(repo, int(pr_number), "REQUEST_CHANGES", body, outcome)
        outcome["alerts"] = await self._notify_blocked_pr(payload, ticket_key, checks, verdict, ticket)
        self.logger.info(
            "GitHubReviewer: %s#%s blocked — %d reason(s), draft=%s, assignee=%s.",
            repo,
            pr_number,
            len(verdict.reasons),
            (outcome.get("draft") or {}).get("status", "error"),
            (outcome.get("alerts") or {}).get("assignee"),
        )
        return outcome

    async def _submit_review(
        self,
        repo: str,
        pr_number: int,
        event: Literal["APPROVE", "REQUEST_CHANGES", "COMMENT"],
        body: str,
        outcome: Dict[str, Any],
    ) -> None:
        """Submit a review, recording the result (or the error) in ``outcome``."""
        try:
            outcome["review"] = await self.git_toolkit.submit_pr_review(
                pr_number=pr_number,
                event=event,
                body=body,
                repository=repo,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "GitHubReviewer: failed to submit %s review on %s#%s: %s",
                event,
                repo,
                pr_number,
                exc,
                exc_info=True,
            )
            outcome["review_error"] = str(exc)

    @staticmethod
    def _deferral_cause(checks: PRChecksSummary, *, code: bool = False) -> str:
        """Explain, in one clause, why the test evidence is unknown.

        Three distinct causes, which must not be confused — reporting "0 checks
        are still running" for a permission denial tells the operator nothing:

        * neither CI API could be read;
        * an API was refused and nothing else was visible (the evidence may
          well exist, just not for this token);
        * the pipeline is genuinely still running.

        Args:
            checks: The CI picture to explain.
            code: Wrap check names in backticks (Markdown targets: the PR
                comment). Left off for Telegram, which escapes HTML instead.
        """
        if not checks.available:
            return (
                f"the CI status could not be read ({checks.reason or 'unknown error'}), so the test "
                f"evidence could not be verified"
            )
        if checks.denied and not checks.declared:
            return f"no CI check was visible to this token — {checks.reason}"
        names = [f"`{name}`" if code else name for name in checks.running[:20]]
        running = ", ".join(names) or "unnamed checks"
        return f"{checks.pending} check(s) are still running ({running})"

    def _format_deferred_body(
        self,
        payload: Dict[str, Any],
        ticket_key: str,
        checks: PRChecksSummary,
    ) -> str:
        """Render the COMMENT review left when the test evidence is unknown."""
        cause = self._deferral_cause(checks, code=True)
        return (
            f"## Automated review — verdict deferred ({ticket_key})\n\n"
            f"The comparison against `{ticket_key}` is done, but {cause}, so the verdict is "
            f"deferred rather than guessed. The PR was left exactly as it is — neither approved "
            f"nor converted to a draft.\n\n"
            f"Re-run the reviewer once CI settles — or push a commit and the webhook will do it "
            f"for you.\n\n"
            f"_Posted by the GitHubReviewer agent._"
        )

    @telegram_command(
        "review_pr",
        description="Review a PR against its Jira ticket and draft it if it does not comply",
        parse_mode="raw",
    )
    async def review_pr(self, target: str = "", **kwargs: Any) -> str:
        """Answer ``/review_pr <pull request link>``.

        Runs the full gate on demand: code review against the Jira ticket and
        its acceptance criteria, plus the CI/test check. A PR that complies is
        approved; one that does not is converted to a draft, commented on, and
        its assignee is pinged privately and in the public channel.

        Args:
            target: The PR to review — a GitHub PR URL,
                ``owner/repo#123``, or a bare ``123`` for the configured
                repository. Telegram hands the whole argument string through
                (``parse_mode="raw"``) so a pasted URL survives intact.

        Returns:
            A Markdown summary of the verdict, which the channel wrapper
            delivers to whoever asked. Failures come back as a one-line
            notice, never as an exception.
        """
        if kwargs:
            self.logger.debug("/review_pr: ignoring unexpected arguments %s", sorted(kwargs))

        repo, pr_number, error = self._parse_pr_target(target)
        if error or pr_number is None:
            return (
                f"⚠️ {error or 'no pull request given'}.\n\n"
                f"Usage: `/review_pr https://github.com/{self.repository}/pull/123` "
                f"— a `{self.repository}#123` slug or a bare `123` also work."
            )
        repo = repo or self.repository
        if self.git_toolkit is None:
            return "⚠️ GitHub is not configured on this agent, so no PR can be reviewed."

        payload = await self._fetch_pr_payload(repo, pr_number)
        if payload is None:
            return f"⚠️ Could not read `{repo}#{pr_number}` from GitHub. Check the link and the agent's access."
        if payload.get("draft"):
            self.logger.info("GitHubReviewer: /review_pr on %s#%s, which is already a draft.", repo, pr_number)
        if (payload.get("state") or "").lower() != "open":
            return f"⚠️ `{repo}#{pr_number}` is {payload.get('state') or 'not open'}; only an open PR is reviewed."

        outcome = await self.strict_review_pull_request(payload)
        return self._format_command_reply(repo, pr_number, payload, outcome)

    def _format_command_reply(
        self,
        repo: str,
        pr_number: int,
        payload: Dict[str, Any],
        outcome: Dict[str, Any],
    ) -> str:
        """Render the ``/review_pr`` reply for the person who asked."""
        status = outcome.get("status")
        title = str(payload.get("pr_title") or "").strip()
        head = f"`{repo}#{pr_number}`" + (f" — {title}" if title else "")
        ticket = outcome.get("jira_key")

        if status == "no_ticket":
            return (
                f"🤷 {head}\n\nNo `{self.jira_project}-<number>` ticket is referenced in the title or body, "
                f"so there is nothing to compare the PR against. I left a comment on the PR saying so."
            )
        if status == "ticket_not_found":
            return f"⚠️ {head}\n\nThe PR references `{ticket}`, but that ticket could not be read from Jira."
        if status == "error":
            return f"⚠️ {head}\n\nThe review could not run: {outcome.get('reason') or 'unknown error'}."

        verdict = outcome.get("verdict") or {}
        checks = PRChecksSummary.model_validate(outcome.get("checks") or {})
        lines: List[str] = []
        if status == "approved":
            lines.append(f"✅ {head}\n\nMeets `{ticket}` and its acceptance criteria. Approved.")
        elif status == "deferred":
            cause = self._deferral_cause(checks)
            lines.append(
                f"⏳ {head}\n\nThe comparison against `{ticket}` is done, but {cause}, so I left a "
                f"comment instead of a verdict and changed nothing on the PR."
            )
        else:
            draft = (outcome.get("draft") or {}).get("status")
            drafted = {
                "converted": "converted to **draft**",
                "already_draft": "already a draft",
                "not_open": "not open, so the draft flag was left alone",
            }.get(draft, "**not** converted to draft (the API call failed)")
            lines.append(f"🚫 {head}\n\nDoes not comply with `{ticket}` — {drafted}.")
            reasons = verdict.get("reasons") or []
            if reasons:
                lines.append("")
                lines.append("*Blocking reasons*")
                lines.extend(f"{i}. {reason}" for i, reason in enumerate(reasons[:10], start=1))
            alerts = outcome.get("alerts") or {}
            assignee = alerts.get("assignee")
            notified = []
            if (alerts.get("dm") or {}).get("sent"):
                notified.append(f"DM to {assignee}")
            if (alerts.get("channel") or {}).get("sent"):
                notified.append("the public channel")
            lines.append("")
            lines.append("Notified: " + (", ".join(notified) if notified else "nobody (see the logs)"))

        lines.append("")
        lines.append(self._format_checks_line(checks))
        warnings = verdict.get("warnings") or []
        if warnings:
            lines.append("")
            lines.append("*Non-blocking*")
            lines.extend(f"- {warning}" for warning in warnings[:10])
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # PR digests (shared) + daily stale PR report
    # ------------------------------------------------------------------

    #: Telegram rejects a ``sendMessage`` payload longer than 4096 characters.
    _TELEGRAM_MAX_MESSAGE = 4096
    #: Head-room reserved in each chunk for the ``(part n/m)`` marker, which is
    #: only known after the chunking decided how many parts there are.
    _TELEGRAM_PART_RESERVE = 32
    #: A ``sendPhoto`` caption is capped far lower than a message body.
    _TELEGRAM_MAX_CAPTION = 1024
    #: Per-entry title clamp, so one novel-length PR title cannot produce an
    #: entry that alone overflows a message.
    _STALE_TITLE_MAX = 150
    #: Generic opening line of the :meth:`today_pr` digest.
    _TODAY_PR_HEADING = "Review Today's Pull Requests"
    #: Default window of :meth:`today_pr`, in hours.
    _TODAY_PR_WINDOW_HOURS = 24

    def _chunk_digest_messages(self, entries: List[str], *, header: str) -> List[Tuple[str, int]]:
        """Pack rendered digest entries into as few Telegram messages as fit.

        Shared by every one-entry-per-item digest: the PR reports
        (:meth:`_format_pr_digest`) and the resolved-ticket listing
        (:meth:`_format_resolved_tickets_digest`) differ in what an entry
        says, not in how entries are packed into messages.

        Args:
            entries: Rendered entries, each already carrying its own leading
                newline, in the order they should be announced.
            header: The message's opening lines, repeated on every part.

        Returns:
            A list of ``(text, entry_count)`` pairs — a single pair in the
            normal case. Enough entries to blow Telegram's 4096-char limit
            are split into as few messages as still fit, each carrying its
            own header and a ``(part n/m)`` marker. ``entry_count`` is how
            many entries that message announces, so a caller can attribute a
            failed send to the items it would have covered.
        """
        budget = self._TELEGRAM_MAX_MESSAGE - len(header) - self._TELEGRAM_PART_RESERVE
        chunks: List[List[str]] = [[]]
        used = 0
        for entry in entries:
            if chunks[-1] and used + len(entry) > budget:
                chunks.append([])
                used = 0
            chunks[-1].append(entry)
            used += len(entry)

        total = len(chunks)
        messages: List[Tuple[str, int]] = []
        for part, chunk in enumerate(chunks, start=1):
            marker = f"(part {part}/{total})\n" if total > 1 else ""
            messages.append((header + marker + "".join(chunk), len(chunk)))
        return messages

    def _format_pr_digest(
        self,
        prs: List[Dict[str, Any]],
        *,
        heading: str,
        subtitle: str,
        detail: Callable[[Dict[str, Any]], str],
    ) -> List[Tuple[str, int]]:
        """Render a list of PRs as ONE Telegram HTML digest message.

        Shared by :meth:`_format_stale_prs_digest` and
        :meth:`_format_today_prs_digest` — every PR report sends a single
        message, never one per PR.

        Args:
            prs: PR dicts carrying ``number``, ``title``, ``html_url``,
                ``user`` and whatever keys ``detail`` reads.
            heading: Bold first line, rendered as ``<b>{heading}</b> on
                <code>{repository}</code>``.
            subtitle: Second line, typically the count and the window.
            detail: Callback returning the trailing half of a PR's second
                line (the part after ``by {user} — ``).

        Returns:
            A list of ``(text, pr_count)`` pairs — a single pair in the normal
            case. A repo with enough PRs to blow Telegram's 4096-char limit is
            split into as few messages as still fit, each carrying its own
            header and a ``(part n/m)`` marker. ``pr_count`` is how many PRs
            that message announces, so a caller can attribute a failed send to
            the PRs it would have covered.
        """
        header = f"<b>{heading}</b> on <code>{html.escape(self.repository)}</code>\n{subtitle}\n"

        entries: List[str] = []
        for idx, pr in enumerate(prs, start=1):
            title = str(pr.get("title") or "")
            if len(title) > self._STALE_TITLE_MAX:
                title = title[: self._STALE_TITLE_MAX - 1].rstrip() + "…"
            title = html.escape(title)
            url = html.escape(str(pr.get("html_url") or ""), quote=True)
            user = html.escape(str(pr.get("user") or "unknown"))
            number = pr.get("number")
            label = f"#{number} {title}".strip() if number is not None else title
            entries.append(f'\n{idx}. <a href="{url}">{label}</a>\n' f"    by {user} — {detail(pr)}")

        return self._chunk_digest_messages(entries, header=header)

    def _format_stale_prs_digest(self, stale: List[Dict[str, Any]]) -> List[Tuple[str, int]]:
        """Build the daily stale-PR digest (see :meth:`_format_pr_digest`)."""
        plural = "" if len(stale) == 1 else "s"
        return self._format_pr_digest(
            stale,
            heading=f"Stale PR{plural}",
            subtitle=f"{len(stale)} open PR{plural} unattended for {self.stale_after_hours}h or more",
            detail=lambda pr: f"open for {pr['age_hours']}h",
        )

    def _format_today_prs_digest(self, prs: List[Dict[str, Any]], window_hours: int) -> List[Tuple[str, int]]:
        """Build the today's-PR digest (see :meth:`_format_pr_digest`)."""
        plural = "" if len(prs) == 1 else "s"
        return self._format_pr_digest(
            prs,
            heading=self._TODAY_PR_HEADING,
            subtitle=f"{len(prs)} open PR{plural} opened in the last {window_hours}h",
            detail=lambda pr: f"opened {pr['age_hours']}h ago",
        )

    @schedule_daily_report
    async def report_stale_pull_requests(self) -> Dict[str, Any]:
        """Scan open PRs on the configured repo and announce stale ones.

        A PR is "stale" when its ``created_at`` is older than
        :attr:`stale_after_hours` (defaults to 24h). All stale PRs are
        announced to :attr:`public_channel_id` in a SINGLE digest message
        (split into as few messages as fit only when the digest would
        exceed Telegram's 4096-char limit). Returns a small dict with
        counts (useful for tests and scheduler logs).

        Scheduled by :func:`schedule_daily_report`; override the run time
        per deployment via ``{AGENT_ID}_DAILY_REPORT`` env var (``HH:MM`` UTC).
        """
        if self.git_toolkit is None:
            return {"status": "error", "reason": "git_toolkit not configured"}

        try:
            pulls = await self.git_toolkit.list_pull_requests(repository=self.repository, state="open", per_page=100)
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "GitHubReviewer: list_pull_requests failed for %s: %s",
                self.repository,
                exc,
                exc_info=True,
            )
            return {"status": "error", "reason": str(exc)}

        now = datetime.now(timezone.utc)
        stale: List[Dict[str, Any]] = []
        for pr in pulls or []:
            created_at = self._parse_iso8601(pr.get("created_at"))
            if created_at is None:
                continue
            age_hours = (now - created_at).total_seconds() / 3600.0
            if age_hours >= self.stale_after_hours:
                stale.append(
                    {
                        "number": pr.get("number"),
                        "title": pr.get("title"),
                        "html_url": pr.get("html_url"),
                        "user": (pr.get("user") or {}).get("login"),
                        "age_hours": round(age_hours, 1),
                    }
                )

        sent = 0
        messages_sent = 0
        if stale:
            bot = self._get_telegram_bot()
            if bot is not None and self.public_channel_id:
                for text, covered in self._format_stale_prs_digest(stale):
                    try:
                        await bot.send_message(
                            chat_id=self.public_channel_id,
                            text=text,
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                        messages_sent += 1
                        sent += covered
                    except Exception as exc:  # noqa: BLE001
                        self.logger.warning(
                            "GitHubReviewer: failed to send stale-PR digest to chat %s: %s",
                            self.public_channel_id,
                            exc,
                        )

        self.logger.info(
            "GitHubReviewer: daily report — %d open PR(s), %d stale, %d announced in %d message(s).",
            len(pulls or []),
            len(stale),
            sent,
            messages_sent,
        )
        return {
            "status": "ok",
            "repository": self.repository,
            "open_count": len(pulls or []),
            "stale_count": len(stale),
            "announced": sent,
            "messages_sent": messages_sent,
            "stale": stale,
        }

    # ------------------------------------------------------------------
    # Daily "today's PRs" report
    # ------------------------------------------------------------------

    @staticmethod
    def _pr_state_label(pr: Dict[str, Any]) -> str:
        """``"merged"`` / ``"closed"`` / ``"open"`` for a PR payload."""
        if pr.get("merged_at"):
            return "merged"
        return "closed" if str(pr.get("state") or "open").lower() == "closed" else "open"

    @classmethod
    def _is_open_pull_request(cls, pr: Dict[str, Any]) -> bool:
        """Whether a PR payload is still open (not closed, not merged)."""
        return cls._pr_state_label(pr) == "open"

    @schedule_daily_report
    async def today_pr(self, window_hours: Optional[int] = None) -> Dict[str, Any]:
        """Announce every PR opened in the last ``window_hours`` as one message.

        Only PRs that are still **open** are reported: one opened and already
        closed or merged inside the window is left out, because the digest is
        a review queue, not an activity log.

        When no open PR was created inside the window — or the repo has no PRs
        at all — the method **terminates silently**: nothing is sent to
        Telegram and the returned dict carries ``today_count: 0``.

        Args:
            window_hours: How far back to look. Defaults to
                :attr:`_TODAY_PR_WINDOW_HOURS` (24h).

        Returns:
            A status dict with ``status``, ``repository``, ``window_hours``,
            ``today_count``, ``announced`` (PRs covered by a successful send),
            ``messages_sent`` and ``today`` (the PR entries).

        Scheduled by :func:`schedule_daily_report`, so it fires at the same
        ``{AGENT_ID}_DAILY_REPORT`` time (``HH:MM`` UTC) as the stale-PR
        report, as its own APScheduler job (``auto_<bot>_today_pr``).
        """
        window = self._TODAY_PR_WINDOW_HOURS if window_hours is None else window_hours
        if self.git_toolkit is None:
            return {"status": "error", "reason": "git_toolkit not configured"}

        try:
            pulls = await self.git_toolkit.list_pull_requests(repository=self.repository, state="open", per_page=100)
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "GitHubReviewer: list_pull_requests failed for %s: %s",
                self.repository,
                exc,
                exc_info=True,
            )
            return {"status": "error", "reason": str(exc)}

        now = datetime.now(timezone.utc)
        today: List[Dict[str, Any]] = []
        for pr in pulls or []:
            # Belt and braces: the listing already asked for state="open", but a
            # closed or merged payload must never reach the digest.
            if not self._is_open_pull_request(pr):
                continue
            created_at = self._parse_iso8601(pr.get("created_at"))
            if created_at is None:
                continue
            age_hours = (now - created_at).total_seconds() / 3600.0
            if age_hours > window:
                continue
            today.append(
                {
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "html_url": pr.get("html_url"),
                    "user": (pr.get("user") or {}).get("login"),
                    "age_hours": round(age_hours, 1),
                    "state": "open",
                }
            )

        base = {
            "status": "ok",
            "repository": self.repository,
            "window_hours": window,
            "today_count": len(today),
        }

        if not today:
            # Silent exit: an empty digest is noise, so no message goes out.
            self.logger.info(
                "GitHubReviewer: today's PR report — no open PR created on %s in the last %sh; staying silent.",
                self.repository,
                window,
            )
            return {**base, "announced": 0, "messages_sent": 0, "today": []}

        sent = 0
        messages_sent = 0
        bot = self._get_telegram_bot()
        if bot is not None and self.management_chat_id:
            for text, covered in self._format_today_prs_digest(today, window):
                try:
                    await bot.send_message(
                        chat_id=self.management_chat_id,
                        text=text,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    messages_sent += 1
                    sent += covered
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning(
                        "GitHubReviewer: failed to send today's-PR digest to chat %s: %s",
                        self.management_chat_id,
                        exc,
                    )

        self.logger.info(
            "GitHubReviewer: today's PR report — %d open PR(s) created in the last %sh on %s, "
            "%d announced in %d message(s).",
            len(today),
            window,
            self.repository,
            sent,
            messages_sent,
        )
        return {**base, "announced": sent, "messages_sent": messages_sent, "today": today}

    @staticmethod
    def _parse_iso8601(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Daily Jira ticket summary (open / in progress / closed by assignee)
    # ------------------------------------------------------------------

    #: Short column of the ticket digest, in hours.
    _TICKET_RECENT_HOURS = 24
    #: Long column of the ticket digest, in days. Also the JQL window: the
    #: 24h column is derived from it, so the report is ONE Jira round-trip.
    _TICKET_WINDOW_DAYS = 14
    #: Minimal field set for the summary — counts only, no prose, no ADF.
    _TICKET_SUMMARY_FIELDS = "key,assignee,status,updated"
    #: Jira ``status.statusCategory.key`` -> bucket.
    _TICKET_BUCKETS: Dict[str, str] = {
        "new": "open",
        "indeterminate": "in_progress",
        "done": "closed",
    }
    #: Column order of the digest table, and of every counts dict returned.
    _TICKET_BUCKET_ORDER: Tuple[str, ...] = ("open", "in_progress", "closed")
    #: Assignee-name clamp, so the fixed-width table stays aligned.
    _TICKET_ASSIGNEE_MAX = 16
    #: Opening line of the digest.
    _TICKET_HEADING = "Jira tickets by assignee"
    #: Window of the on-demand monthly pie chart, in days.
    _TICKET_MONTH_DAYS = 30
    #: Assignees that get a wedge of their own in that pie; the tail is
    #: folded into one, because 40 slivers read as a colour wheel.
    _TICKET_PIE_MAX_SLICES = 9
    #: Label of the folded wedge (the assignee count is appended).
    _TICKET_PIE_OTHERS = "Others"

    @classmethod
    def _ticket_bucket(cls, issue: Dict[str, Any]) -> str:
        """``"open"`` / ``"in_progress"`` / ``"closed"`` for one Jira issue.

        Keys off ``status.statusCategory.key``, not the status name, so the
        buckets hold for any workflow: a project that renamed "In Progress"
        to "Doing" still reports it as in progress. Jira Server instances
        that omit the category fall back to matching the status name, and
        anything still unrecognised counts as open — a ticket is never
        dropped from the digest for having an exotic status.
        """
        status = ((issue.get("fields") or {}).get("status")) or {}
        category = str(((status.get("statusCategory") or {}).get("key")) or "").lower()
        bucket = cls._TICKET_BUCKETS.get(category)
        if bucket is not None:
            return bucket

        name = str(status.get("name") or "").lower()
        if any(word in name for word in ("progress", "doing", "review")):
            return "in_progress"
        if any(word in name for word in ("done", "closed", "resolved", "complete")):
            return "closed"
        return "open"

    @staticmethod
    def _ticket_assignee(issue: Dict[str, Any]) -> str:
        """Display name of an issue's assignee, or ``"Unassigned"``."""
        assignee = ((issue.get("fields") or {}).get("assignee")) or {}
        return str(assignee.get("displayName") or assignee.get("name") or assignee.get("emailAddress") or "Unassigned")

    def _summarize_tickets(
        self,
        issues: List[Dict[str, Any]],
        *,
        now: datetime,
        recent_hours: int,
        window_days: int,
    ) -> Dict[str, Any]:
        """Bucket ``issues`` per assignee into the two reported windows.

        The caller already restricted the JQL to the long window, so the
        24h column is derived here from each issue's ``updated`` stamp
        rather than costing a second Jira round-trip. An issue whose
        ``updated`` is missing or unparseable counts in the long window
        only.

        Args:
            issues: Raw Jira issue dicts (``{"key": ..., "fields": {...}}``).
            now: Reference instant, passed in so tests are deterministic.
            recent_hours: Width of the short column.
            window_days: Width of the long column (reported back verbatim).

        Returns:
            ``{"recent_hours", "window_days", "ticket_count", "assignees",
            "totals"}``. ``assignees`` is a list of
            ``{"assignee", "recent": {...}, "window": {...}}`` rows sorted
            by long-window volume (ties broken by name); each counts dict
            carries the three buckets plus their ``total``.
        """
        recent_cutoff = now - timedelta(hours=recent_hours)
        rows: Dict[str, Dict[str, Counter]] = {}
        totals: Dict[str, Counter] = {"recent": Counter(), "window": Counter()}

        for issue in issues:
            bucket = self._ticket_bucket(issue)
            name = self._ticket_assignee(issue)
            row = rows.setdefault(name, {"recent": Counter(), "window": Counter()})
            row["window"][bucket] += 1
            totals["window"][bucket] += 1
            # Jira renders offsets as ``+0000`` (no colon), which
            # fromisoformat() accepts on the 3.11+ this package requires.
            updated = self._parse_iso8601(((issue.get("fields") or {}).get("updated")))
            if updated is not None and updated >= recent_cutoff:
                row["recent"][bucket] += 1
                totals["recent"][bucket] += 1

        def _counts(counter: Counter) -> Dict[str, int]:
            data = {bucket: int(counter.get(bucket, 0)) for bucket in self._TICKET_BUCKET_ORDER}
            data["total"] = sum(data.values())
            return data

        assignees = [
            {
                "assignee": name,
                "recent": _counts(row["recent"]),
                "window": _counts(row["window"]),
            }
            for name, row in rows.items()
        ]
        assignees.sort(key=lambda entry: (-entry["window"]["total"], entry["assignee"].lower()))

        return {
            "recent_hours": recent_hours,
            "window_days": window_days,
            "ticket_count": len(issues),
            "assignees": assignees,
            "totals": {"recent": _counts(totals["recent"]), "window": _counts(totals["window"])},
        }

    def _format_ticket_counts(self, counts: Dict[str, int]) -> str:
        """Render one window's three buckets as a fixed-width cell group."""
        return " ".join(f"{counts.get(bucket, 0):>3}" for bucket in self._TICKET_BUCKET_ORDER)

    def _format_jira_tickets_digest(self, summary: Dict[str, Any]) -> List[Tuple[str, int]]:
        """Render :meth:`_summarize_tickets` output as ONE Telegram message.

        The body is a monospace ``<pre>`` table: one row per assignee, two
        column groups — the last ``recent_hours`` and the last
        ``window_days`` — each holding open / in progress / closed. The
        ``TOTAL`` row closes the table.

        Returns:
            A list of ``(text, assignee_rows)`` pairs, a single pair in the
            normal case. A project with enough assignees to blow Telegram's
            4096-char limit is split into as few messages as still fit,
            each carrying its own header, table head and ``(part n/m)``
            marker; the ``TOTAL`` row rides on the last part only, so it is
            never double-counted. ``assignee_rows`` is how many assignees
            that message reports, so a caller can attribute a failed send
            to the rows it would have covered.
        """
        recent_hours = int(summary.get("recent_hours") or self._TICKET_RECENT_HOURS)
        window_days = int(summary.get("window_days") or self._TICKET_WINDOW_DAYS)
        ticket_count = int(summary.get("ticket_count") or 0)
        plural = "" if ticket_count == 1 else "s"

        name_w = self._TICKET_ASSIGNEE_MAX
        recent_label = f"last {recent_hours}h"
        window_label = f"last {window_days}d"
        head = (
            f"{'':<{name_w}}{recent_label:^11}   {window_label:^11}\n"
            f"{'Assignee':<{name_w}}{'  O   P   C'}   {'  O   P   C'}\n"
            f"{'-' * (name_w + 25)}"
        )
        header = (
            f"<b>{html.escape(self._TICKET_HEADING)}</b> on "
            f"<code>{html.escape(str(self.jira_project))}</code>\n"
            f"{ticket_count} ticket{plural} with activity in the {window_label}\n"
            "O = open · P = in progress · C = closed\n"
        )

        def _row(name: str, recent: Dict[str, int], window: Dict[str, int]) -> str:
            label = name if len(name) <= name_w else name[: name_w - 2].rstrip() + "…"
            # Pad first, escape after: inside <pre> the rendered width is the
            # DECODED width, so padding an escaped "&amp;" would misalign it.
            return (
                f"\n{html.escape(f'{label:<{name_w}}')}"
                f"{self._format_ticket_counts(recent)}   {self._format_ticket_counts(window)}"
            )

        entries = [
            _row(entry["assignee"], entry["recent"], entry["window"]) for entry in summary.get("assignees") or []
        ]
        totals = summary.get("totals") or {}
        total_row = _row("TOTAL", totals.get("recent") or {}, totals.get("window") or {})

        # ``<pre>``/``</pre>`` plus the table head and the TOTAL row are
        # per-message overhead, so they come off the budget before the
        # assignee rows are packed into it.
        fixed = len(header) + len(head) + len(total_row) + len("<pre>\n</pre>") + self._TELEGRAM_PART_RESERVE
        budget = self._TELEGRAM_MAX_MESSAGE - fixed
        chunks: List[List[str]] = [[]]
        used = 0
        for entry in entries:
            if chunks[-1] and used + len(entry) > budget:
                chunks.append([])
                used = 0
            chunks[-1].append(entry)
            used += len(entry)

        total_parts = len(chunks)
        messages: List[Tuple[str, int]] = []
        for part, chunk in enumerate(chunks, start=1):
            marker = f"(part {part}/{total_parts})\n" if total_parts > 1 else ""
            tail = total_row if part == total_parts else ""
            body = f"<pre>{head}{''.join(chunk)}{tail}\n</pre>"
            messages.append((header + marker + body, len(chunk)))
        return messages

    async def _collect_ticket_summary(self, *, recent_hours: int, window_days: int) -> Dict[str, Any]:
        """Run the project's ticket JQL once and bucket it per assignee.

        Shared by the two ticket digests — :meth:`report_jira_tickets`
        (daily table, 14 days) and :meth:`monthly_jira_tickets` (pie chart,
        30 days) report the same numbers over different windows, so the
        Jira round-trip, its error handling and the bucketing live here and
        the callers only render.

        Args:
            recent_hours: Width of the short column; derived locally from
                each ticket's ``updated``, never a second Jira call.
            window_days: Width of the JQL window (``updated >= -{days}d``).

        Returns:
            On success, ``status: "ok"`` plus ``project``, ``jql``,
            ``recent_hours``, ``window_days`` merged with
            :meth:`_summarize_tickets` (``ticket_count``, ``assignees``,
            ``totals``); ``assignees`` is empty when nothing was touched in
            the window. On failure, ``status: "error"`` and a ``reason``.
        """
        if self.jira_toolkit is None:
            return {"status": "error", "reason": "jira_toolkit not configured"}

        jql = f"project = {self.jira_project} AND updated >= -{window_days}d ORDER BY updated DESC"
        base: Dict[str, Any] = {
            "status": "ok",
            "project": self.jira_project,
            "jql": jql,
            "recent_hours": recent_hours,
            "window_days": window_days,
        }

        try:
            envelope = await self.jira_toolkit.jira_search_issues(
                jql=jql,
                # None fetches every page: a partial page would silently
                # under-count, which is worse than a slower report.
                max_results=None,
                fields=self._TICKET_SUMMARY_FIELDS,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "GitHubReviewer: jira_search_issues failed for project %s: %s",
                self.jira_project,
                exc,
                exc_info=True,
            )
            return {**base, "status": "error", "reason": str(exc)}

        envelope = envelope or {}
        status = envelope.get("status")
        if status not in ("ok", "empty"):
            reason = str(envelope.get("message") or "jira_search_issues returned no data")
            self.logger.error(
                "GitHubReviewer: Jira ticket summary for %s failed: %s",
                self.jira_project,
                reason,
            )
            return {**base, "status": "error", "reason": reason}

        issues = ((envelope.get("data") or {}).get("issues")) or []
        summary = self._summarize_tickets(
            issues,
            now=datetime.now(timezone.utc),
            recent_hours=recent_hours,
            window_days=window_days,
        )
        return {**base, **summary}

    # Daily at 10:00 America/New_York, NOT @schedule_daily_report: the
    # ``daily`` schedule type builds a ``CronTrigger`` with no timezone, so it
    # can only fire on the scheduler's own clock (UTC), and its config would
    # be re-resolved from ``{AGENT_ID}_DAILY_REPORT`` at register time —
    # sharing the stale-PR digest's run time. ``ScheduleType.CRON`` takes an
    # explicit timezone and carries no report marker, so this stays at 10:00
    # New York across DST (14:00 UTC in EDT, 15:00 UTC in EST).
    @schedule(
        schedule_type=ScheduleType.CRON,
        hour=_TICKET_REPORT_HOUR,
        minute=_TICKET_REPORT_MINUTE,
        timezone=_TICKET_REPORT_TIMEZONE,
    )
    async def report_jira_tickets(
        self,
        recent_hours: Optional[int] = None,
        window_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Digest the review project's tickets by assignee and state.

        Counterpart of :meth:`report_stale_pull_requests` on the Jira side:
        one JQL search over ``self.jira_project`` (the project the reviewer
        already resolves PR tickets against), bucketed per assignee into
        open / in progress / closed via each ticket's ``statusCategory``,
        and reported in two columns — the last ``recent_hours`` and the
        last ``window_days``.

        Scope is **activity**, not backlog: the JQL is
        ``updated >= -{window_days}d``, so a ticket nobody has touched in
        that window does not appear in either column, and the 24h column
        is the subset of those tickets updated in the last
        ``recent_hours`` (derived locally — no second Jira call).

        When the project had no activity in the window — or Jira returns
        nothing — the method **terminates silently** like :meth:`today_pr`:
        nothing is sent and the returned dict carries ``ticket_count: 0``.

        Args:
            recent_hours: Width of the short column. Defaults to
                :attr:`_TICKET_RECENT_HOURS` (24h).
            window_days: Width of the long column, and of the JQL window.
                Defaults to :attr:`_TICKET_WINDOW_DAYS` (14 days).

        Returns:
            A status dict with ``status``, ``project``, ``jql``,
            ``recent_hours``, ``window_days``, ``ticket_count``,
            ``assignees``, ``totals``, ``announced`` (assignee rows covered
            by a successful send) and ``messages_sent``.

        Scheduled daily at 10:00 ``America/New_York`` (DST-aware), on its
        own cron job rather than the ``{AGENT_ID}_DAILY_REPORT`` tick the
        other reports share — see the decorator above.
        """
        recent = self._TICKET_RECENT_HOURS if recent_hours is None else int(recent_hours)
        days = self._TICKET_WINDOW_DAYS if window_days is None else int(window_days)

        summary = await self._collect_ticket_summary(recent_hours=recent, window_days=days)
        if summary["status"] != "ok":
            return summary
        base = summary

        if not summary["assignees"]:
            # Silent exit: an empty table is noise, so no message goes out.
            self.logger.info(
                "GitHubReviewer: Jira ticket summary — no %s ticket touched in the last %sd; staying silent.",
                self.jira_project,
                days,
            )
            return {**base, "announced": 0, "messages_sent": 0}

        sent = 0
        messages_sent = 0
        bot = self._get_telegram_bot()
        if bot is not None and self.management_chat_id:
            for text, covered in self._format_jira_tickets_digest(summary):
                try:
                    await bot.send_message(
                        chat_id=self.management_chat_id,
                        text=text,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    messages_sent += 1
                    sent += covered
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning(
                        "GitHubReviewer: failed to send Jira ticket digest to chat %s: %s",
                        self.management_chat_id,
                        exc,
                    )

        self.logger.info(
            "GitHubReviewer: Jira ticket summary — %d ticket(s) across %d assignee(s) on %s "
            "(last %sh / last %sd), %d row(s) announced in %d message(s).",
            summary["ticket_count"],
            len(summary["assignees"]),
            self.jira_project,
            recent,
            days,
            sent,
            messages_sent,
        )
        return {**base, "announced": sent, "messages_sent": messages_sent}

    # ------------------------------------------------------------------
    # Daily list of tickets that moved to Resolved / Closed (last 24h)
    # ------------------------------------------------------------------

    #: Default window of :meth:`report_resolved_tickets`, in hours.
    _RESOLVED_WINDOW_HOURS = 24
    #: Transition targets the report looks for. Status *names*, not
    #: ``statusCategory`` keys like :attr:`_TICKET_BUCKETS`: both of these
    #: live in the ``done`` category, and a workflow that has both
    #: distinguishes them (resolved-but-not-closed is a state people track),
    #: so the names are what the JQL must ask for. Override in a subclass
    #: whose project renamed them.
    _RESOLVED_STATUSES: Tuple[str, ...] = ("Resolved", "Closed")
    #: Field set of the listing — one line per ticket, so it needs the
    #: summary and the resolution stamp on top of the digest's counting
    #: fields.
    _RESOLVED_FIELDS = "key,summary,assignee,status,updated,resolutiondate"
    #: Opening line of the listing.
    _RESOLVED_HEADING = "Tickets resolved or closed"
    #: Per-entry summary clamp, so one novel-length ticket summary cannot
    #: produce an entry that alone overflows a message.
    _RESOLVED_SUMMARY_MAX = 120

    def _jira_browse_url(self, key: str) -> str:
        """``<instance>/browse/<key>``, or ``""`` when the instance is unknown.

        Read off the live toolkit rather than ``JIRA_INSTANCE`` so the link
        always points at the Jira the tickets were actually read from. An
        empty string means "render this ticket as plain text": a report must
        not lose a ticket over a missing base URL.
        """
        base = getattr(self.jira_toolkit, "server_url", None)
        base = base.rstrip("/") if isinstance(base, str) else ""
        return f"{base}/browse/{key}" if base else ""

    def _resolved_ticket_rows(
        self,
        issues: List[Dict[str, Any]],
        *,
        now: datetime,
        window_hours: int,
    ) -> List[Dict[str, Any]]:
        """Project raw Jira issues into the rows the listing renders.

        Args:
            issues: Raw Jira issue dicts (``{"key": ..., "fields": {...}}``).
            now: Reference instant, passed in so tests are deterministic.
            window_hours: Width of the window, used to decide whether a
                ticket's ``resolutiondate`` belongs to *this* transition.

        Returns:
            One dict per ticket — ``key``, ``summary``, ``assignee``,
            ``status``, ``url``, ``moved_at`` (a ``datetime`` or ``None``)
            and ``hours_ago`` (rounded, or ``None``) — most recently moved
            first, tickets with no usable stamp last (ties by key).
        """
        cutoff = now - timedelta(hours=window_hours)
        rows: List[Dict[str, Any]] = []
        for issue in issues:
            fields = issue.get("fields") or {}
            # ``resolutiondate`` names the moment far better than
            # ``updated`` — but a ticket resolved long ago, reopened and
            # re-closed inside the window keeps the OLD resolution stamp,
            # and a Closed-without-resolution ticket has none at all. Only
            # trust it when it falls inside the window the JQL asked about.
            moved_at = self._parse_iso8601(fields.get("resolutiondate"))
            if moved_at is None or moved_at < cutoff:
                moved_at = self._parse_iso8601(fields.get("updated"))
            key = str(issue.get("key") or "")
            rows.append(
                {
                    "key": key,
                    "summary": str(fields.get("summary") or ""),
                    "assignee": self._ticket_assignee(issue),
                    "status": str(((fields.get("status") or {}).get("name")) or "unknown"),
                    "url": self._jira_browse_url(key) if key else "",
                    "moved_at": moved_at,
                    "hours_ago": (None if moved_at is None else round((now - moved_at).total_seconds() / 3600, 1)),
                }
            )

        # ``moved_at`` is optional, so it cannot be the sort key directly:
        # a stampless ticket sorts into its own group (last), and the rest go
        # by recency — ascending ``hours_ago`` is most-recent-first.
        rows.sort(
            key=lambda row: (
                row["hours_ago"] is None,
                row["hours_ago"] if row["hours_ago"] is not None else 0.0,
                row["key"],
            )
        )
        return rows

    def _format_resolved_tickets_digest(self, payload: Dict[str, Any]) -> List[Tuple[str, int]]:
        """Render :meth:`_collect_resolved_tickets` output as a Telegram digest.

        One numbered line per ticket — the key and summary as a link to the
        issue, then the assignee, the status it now sits in and how long ago
        it got there — chunked by :meth:`_chunk_digest_messages`, so a day
        with a hundred closures still arrives as a handful of messages
        rather than a hundred.

        Returns:
            A list of ``(text, ticket_count)`` pairs (see
            :meth:`_chunk_digest_messages`).
        """
        tickets = payload.get("tickets") or []
        window_hours = int(payload.get("window_hours") or self._RESOLVED_WINDOW_HOURS)
        plural = "" if len(tickets) == 1 else "s"
        targets = " or ".join(self._RESOLVED_STATUSES)
        header = (
            f"<b>{html.escape(self._RESOLVED_HEADING)}</b> on "
            f"<code>{html.escape(str(self.jira_project))}</code>\n"
            f"{len(tickets)} ticket{plural} moved to {html.escape(targets)} "
            f"in the last {window_hours}h\n"
        )

        entries: List[str] = []
        for idx, ticket in enumerate(tickets, start=1):
            summary = str(ticket.get("summary") or "")
            if len(summary) > self._RESOLVED_SUMMARY_MAX:
                summary = summary[: self._RESOLVED_SUMMARY_MAX - 1].rstrip() + "…"
            label = html.escape(f"{ticket.get('key')} {summary}".strip())
            url = str(ticket.get("url") or "")
            # No base URL (see :meth:`_jira_browse_url`): the ticket still
            # gets its line, just without the hyperlink.
            title = f'<a href="{html.escape(url, quote=True)}">{label}</a>' if url else f"<b>{label}</b>"
            hours_ago = ticket.get("hours_ago")
            when = "recently" if hours_ago is None else f"{hours_ago}h ago"
            entries.append(
                f"\n{idx}. {title}\n"
                f"    {html.escape(str(ticket.get('assignee') or 'Unassigned'))} — "
                f"{html.escape(str(ticket.get('status') or 'unknown'))}, {when}"
            )

        return self._chunk_digest_messages(entries, header=header)

    async def _collect_resolved_tickets(self, *, window_hours: int) -> Dict[str, Any]:
        """Search the project for tickets that *transitioned* in the window.

        One JQL round-trip on ``status CHANGED TO (...) AFTER -{hours}h``,
        which is a changelog question, not a state one: a ticket closed
        three months ago and merely touched today does NOT match, and a
        ticket that moved to Closed and then back out still does — it did
        make the transition, and its row reports the status it sits in now.

        Args:
            window_hours: Width of the changelog window, in hours.

        Returns:
            On success, ``status: "ok"`` plus ``project``, ``jql``,
            ``window_hours``, ``ticket_count`` and ``tickets`` (the rows of
            :meth:`_resolved_ticket_rows`, empty when nothing moved). On
            failure, ``status: "error"`` and a ``reason``.
        """
        if self.jira_toolkit is None:
            return {"status": "error", "reason": "jira_toolkit not configured"}

        targets = ", ".join(f'"{status}"' for status in self._RESOLVED_STATUSES)
        jql = (
            f"project = {self.jira_project} "
            f"AND status CHANGED TO ({targets}) AFTER -{window_hours}h "
            "ORDER BY updated DESC"
        )
        base: Dict[str, Any] = {
            "status": "ok",
            "project": self.jira_project,
            "jql": jql,
            "window_hours": window_hours,
        }

        try:
            envelope = await self.jira_toolkit.jira_search_issues(
                jql=jql,
                # None fetches every page: a partial page would silently
                # drop closures, and a day's worth can exceed one page.
                max_results=None,
                fields=self._RESOLVED_FIELDS,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "GitHubReviewer: jira_search_issues failed for resolved tickets on %s: %s",
                self.jira_project,
                exc,
                exc_info=True,
            )
            return {**base, "status": "error", "reason": str(exc)}

        envelope = envelope or {}
        if envelope.get("status") not in ("ok", "empty"):
            reason = str(envelope.get("message") or "jira_search_issues returned no data")
            self.logger.error(
                "GitHubReviewer: resolved-ticket listing for %s failed: %s",
                self.jira_project,
                reason,
            )
            return {**base, "status": "error", "reason": reason}

        issues = ((envelope.get("data") or {}).get("issues")) or []
        tickets = self._resolved_ticket_rows(
            issues,
            now=datetime.now(timezone.utc),
            window_hours=window_hours,
        )
        return {**base, "ticket_count": len(tickets), "tickets": tickets}

    # Daily at 10:00 America/New_York, on the same timezone-aware cron as
    # the ticket digest above and for the same reasons (see the note on
    # report_jira_tickets): ScheduleType.DAILY would fire on the
    # scheduler's UTC clock and share the stale-PR digest's configured time.
    @schedule(
        schedule_type=ScheduleType.CRON,
        hour=_TICKET_REPORT_HOUR,
        minute=_TICKET_REPORT_MINUTE,
        timezone=_TICKET_REPORT_TIMEZONE,
    )
    async def report_resolved_tickets(self, window_hours: Optional[int] = None) -> Dict[str, Any]:
        """List the tickets that moved to Resolved or Closed, and send it.

        The named counterpart of :meth:`report_jira_tickets`: that one
        counts a project by assignee, this one names the tickets that
        actually crossed the finish line in the last ``window_hours`` —
        what got done, with a link per ticket — and posts the list to
        :attr:`management_chat_id` (``GITHUB_MANAGEMENT_TELEGRAM_CHAT_ID``,
        falling back to the public channel).

        Scope is the **transition**, not the current state: the JQL asks
        ``status CHANGED TO (Resolved, Closed) AFTER -{window_hours}h``, so
        a ticket that has sat in Closed for a month is absent however often
        it was touched, while one that moved to Closed and was reopened the
        same day is present — it did get resolved, and its row shows the
        status it sits in now.

        When nothing moved — or Jira returns nothing — the method
        **terminates silently** like the other digests: no message goes
        out and the returned dict carries ``ticket_count: 0``.

        Args:
            window_hours: Width of the window. Defaults to
                :attr:`_RESOLVED_WINDOW_HOURS` (24h).

        Returns:
            A status dict with ``status``, ``project``, ``jql``,
            ``window_hours``, ``ticket_count``, ``tickets`` (bare keys),
            ``announced`` (tickets covered by a successful send) and
            ``messages_sent``.

            ``tickets`` carries keys rather than the rendered rows on
            purpose: ``/call <method>`` echoes a method's return value back
            into the chat through Telegram's *legacy Markdown* parser, which
            a ticket summary holding ``_`` or ``*`` breaks (the digest
            itself is sent as HTML and is unaffected). Telemetry stays
            printable; :meth:`_collect_resolved_tickets` is where a caller
            that wants the full rows goes.

        Scheduled daily at 10:00 ``America/New_York`` (DST-aware); it is
        equally dispatchable on demand, which is what ``/call
        report_resolved_tickets`` does.
        """
        hours = self._RESOLVED_WINDOW_HOURS if window_hours is None else int(window_hours)
        if hours <= 0:
            hours = self._RESOLVED_WINDOW_HOURS

        payload = await self._collect_resolved_tickets(window_hours=hours)
        if payload["status"] != "ok":
            return payload

        # The rows feed the digest; the status dict gets their keys (see the
        # docstring's Returns section for why it carries no prose).
        rows: List[Dict[str, Any]] = payload["tickets"]
        base = {**payload, "tickets": [str(row["key"]) for row in rows]}

        if not rows:
            # Silent exit: an empty list is noise, like the digests above.
            self.logger.info(
                "GitHubReviewer: resolved-ticket listing — no %s ticket moved to %s in the last %sh; staying silent.",
                self.jira_project,
                " or ".join(self._RESOLVED_STATUSES),
                hours,
            )
            return {**base, "announced": 0, "messages_sent": 0}

        sent = 0
        messages_sent = 0
        bot = self._get_telegram_bot()
        if bot is None or not self.management_chat_id:
            self.logger.warning(
                "GitHubReviewer: %d resolved ticket(s) to report but no %s to send them to; skipping.",
                len(rows),
                "Telegram bot" if bot is None else "management chat id",
            )
            return {**base, "announced": 0, "messages_sent": 0}

        for text, covered in self._format_resolved_tickets_digest(payload):
            try:
                await bot.send_message(
                    chat_id=self.management_chat_id,
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                messages_sent += 1
                sent += covered
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "GitHubReviewer: failed to send the resolved-ticket listing to chat %s: %s",
                    self.management_chat_id,
                    exc,
                )

        self.logger.info(
            "GitHubReviewer: resolved-ticket listing — %d %s ticket(s) moved to %s in the last %sh, "
            "%d announced in %d message(s).",
            payload["ticket_count"],
            self.jira_project,
            " or ".join(self._RESOLVED_STATUSES),
            hours,
            sent,
            messages_sent,
        )
        return {**base, "announced": sent, "messages_sent": messages_sent}

    # ------------------------------------------------------------------
    # On-demand monthly ticket pie chart (/monthly_jira_tickets)
    # ------------------------------------------------------------------

    @classmethod
    def _ticket_pie_slices(
        cls,
        summary: Dict[str, Any],
        *,
        max_slices: Optional[int] = None,
    ) -> List[Tuple[str, int]]:
        """Wedges for the monthly pie: ``(assignee, tickets)``, biggest first.

        ``summary["assignees"]`` already arrives sorted by long-window
        volume, so the tail past ``max_slices`` is folded into a single
        ``Others (n)`` wedge. Assignees with no ticket in the window are
        dropped: a zero wedge is invisible but still eats a legend row.

        Args:
            summary: A :meth:`_collect_ticket_summary` result.
            max_slices: Named wedges to keep. Defaults to
                :attr:`_TICKET_PIE_MAX_SLICES`; ``0`` keeps every assignee.

        Returns:
            The wedges, or an empty list when nothing was touched.
        """
        limit = cls._TICKET_PIE_MAX_SLICES if max_slices is None else int(max_slices)
        rows = [
            (
                str(entry.get("assignee") or "Unassigned"),
                int((entry.get("window") or {}).get("total") or 0),
            )
            for entry in summary.get("assignees") or []
        ]
        rows = [row for row in rows if row[1] > 0]
        if limit > 0 and len(rows) > limit:
            head, tail = rows[:limit], rows[limit:]
            head.append((f"{cls._TICKET_PIE_OTHERS} ({len(tail)})", sum(count for _, count in tail)))
            return head
        return rows

    async def _render_ticket_pie(self, slices: List[Tuple[str, int]], *, title: str) -> Optional[Path]:
        """Render ``slices`` as a PNG pie chart, or ``None`` when it cannot.

        PNG export goes through ``parrot_tools.chart`` (altair), which needs
        the optional ``vl-convert-python`` dependency; without it the chart
        tool falls back to writing a Vega-Lite JSON spec, which Telegram
        cannot show as a photo. Both that fallback and an outright failure
        return ``None`` so the caller still sends the text ranking — a
        missing chart must never cost the whole reply.

        Args:
            slices: ``(label, count)`` wedges from :meth:`_ticket_pie_slices`.
            title: Chart title, also used as the attachment caption.

        Returns:
            Path to the rendered PNG, or ``None``.
        """
        if not slices:
            return None
        # Local import: charts are an optional extra of ai-parrot-tools, and
        # pulling altair in at module import time would tax every reviewer.
        from parrot_tools.chart import generate_chart

        try:
            path = await generate_chart(
                "pie",
                title,
                {
                    "labels": [label for label, _ in slices],
                    "values": [count for _, count in slices],
                },
                legend_title="Assignee",
                output_format="png",
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "GitHubReviewer: could not render the %s ticket pie chart: %s",
                self.jira_project,
                exc,
            )
            return None

        if path is None or path.suffix.lower() != ".png":
            self.logger.warning(
                "GitHubReviewer: pie chart export fell back to '%s' — install "
                "ai-parrot-tools[charts] (vl-convert-python) for PNG; sending text only.",
                path.suffix.lstrip(".") if path is not None else "nothing",
            )
            return None
        return path

    def _monthly_ticket_headings(self, summary: Dict[str, Any]) -> Tuple[str, str]:
        """``(title, subtitle)`` for the monthly digest, without any markup.

        Both renderings start from the same two lines so the chat message
        and the command reply can never describe the same numbers
        differently; each escapes or decorates them as its format needs.
        """
        days = int(summary.get("window_days") or self._TICKET_MONTH_DAYS)
        ticket_count = int(summary.get("ticket_count") or 0)
        plural = "" if ticket_count == 1 else "s"
        return (
            f"{self._TICKET_HEADING} — last {days} days on {self.jira_project}",
            f"{ticket_count} ticket{plural} with activity, {len(summary.get('assignees') or [])} assignee(s)",
        )

    def _monthly_ticket_rows(
        self,
        slices: List[Tuple[str, int]],
    ) -> List[str]:
        """The pie's own numbers as fixed-width lines, no markup.

        The chart carries the shape, these carry the values — and they are
        the whole report when PNG export is unavailable. Shared by both
        renderings so the columns and percentages cannot drift apart; the
        caller wraps them in a Markdown fence or a ``<pre>`` block, which
        is also what keeps an ``A & <b>`` display name from reaching
        Telegram as entities.

        Args:
            slices: The wedges being drawn, biggest first.

        Returns:
            One line per wedge, then a rule and a TOTAL line.
        """
        drawn = sum(count for _, count in slices)
        name_w = self._TICKET_ASSIGNEE_MAX + 4  # the folded wedge carries a count

        def _row(label: str, count: int) -> str:
            clipped = label if len(label) <= name_w else label[: name_w - 2].rstrip() + "…"
            share = (count * 100 / drawn) if drawn else 0
            return f"{clipped:<{name_w}}{count:>5}{share:>6.1f}%"

        return [
            *(_row(label, count) for label, count in slices),
            "-" * (name_w + 12),
            _row("TOTAL", drawn),
        ]

    def _format_monthly_tickets_text(
        self,
        summary: Dict[str, Any],
        slices: List[Tuple[str, int]],
    ) -> str:
        """Markdown rendering, for the command reply the wrapper delivers.

        Fenced on purpose: the wrapper runs the text through
        Markdown→HTML, and the fence makes that pass escape the assignee
        names instead of letting markup in a display name break Telegram's
        parser.

        Args:
            summary: A :meth:`_collect_ticket_summary` result.
            slices: The wedges being drawn, biggest first.

        Returns:
            Two header lines plus a fenced table.
        """
        title, subtitle = self._monthly_ticket_headings(summary)
        return f"{title}\n{subtitle}\n\n```\n" + "\n".join(self._monthly_ticket_rows(slices)) + "\n```"

    def _format_monthly_tickets_digest(
        self,
        summary: Dict[str, Any],
        slices: List[Tuple[str, int]],
    ) -> str:
        """Telegram-HTML rendering, for the monthly report's own send.

        The scheduled report talks to ``bot.send_photo`` /
        ``send_message`` directly — no wrapper, so no Markdown pass — and
        therefore escapes here, like :meth:`_format_jira_tickets_digest`.

        Args:
            summary: A :meth:`_collect_ticket_summary` result.
            slices: The wedges being drawn, biggest first.

        Returns:
            HTML: a bold title, the subtitle, and the table in ``<pre>``.
        """
        title, subtitle = self._monthly_ticket_headings(summary)
        rows = html.escape("\n".join(self._monthly_ticket_rows(slices)))
        return f"<b>{html.escape(title)}</b>\n{html.escape(subtitle)}\n<pre>\n{rows}\n</pre>"

    async def _build_monthly_ticket_pie(self, *, window_days: int) -> Dict[str, Any]:
        """Collect the month's tickets, slice them and render the pie.

        The whole body of the monthly digest, minus delivery: the
        ``@telegram_command`` hands it to the wrapper, the scheduled report
        sends it to the management channel, and neither duplicates the
        other's logic.

        Args:
            window_days: Width of the window, in days.

        Returns:
            ``{"status": "ok", "summary", "slices", "chart"}`` — ``chart``
            is the PNG path or ``None`` when export was unavailable;
            ``{"status": "empty"}`` when nothing was touched in the window;
            or the ``status: "error"`` dict from
            :meth:`_collect_ticket_summary`.
        """
        summary = await self._collect_ticket_summary(
            recent_hours=self._TICKET_RECENT_HOURS,
            window_days=window_days,
        )
        if summary["status"] != "ok":
            return summary

        slices = self._ticket_pie_slices(summary)
        if not slices:
            self.logger.info(
                "GitHubReviewer: monthly ticket pie — no %s ticket touched in the last %sd; staying silent.",
                self.jira_project,
                window_days,
            )
            return {"status": "empty", "summary": summary, "slices": [], "chart": None}

        title = f"{self._TICKET_HEADING} — last {window_days}d ({self.jira_project})"
        chart = await self._render_ticket_pie(slices, title=title)
        self.logger.info(
            "GitHubReviewer: monthly ticket pie — %d ticket(s) across %d assignee(s) on %s "
            "(last %sd), %d wedge(s), chart=%s.",
            int(summary.get("ticket_count") or 0),
            len(summary.get("assignees") or []),
            self.jira_project,
            window_days,
            len(slices),
            chart.name if chart is not None else "none",
        )
        return {"status": "ok", "summary": summary, "slices": slices, "chart": chart, "title": title}

    @telegram_command(
        "monthly_jira_tickets",
        description="Pie chart of the last month's Jira tickets by assignee",
        parse_mode="keyword",
    )
    async def monthly_jira_tickets(
        self,
        window_days: Optional[int] = None,
        **kwargs: Any,
    ) -> ChartReply:
        """Answer ``/monthly_jira_tickets`` with a per-assignee pie chart.

        The same JQL and bucketing as :meth:`report_jira_tickets`, over 30
        days instead of 14, drawn as each assignee's share of the month's
        ticket activity — scope is activity, not backlog, so a ticket
        nobody touched this month is in neither the pie nor the table.

        The reply is returned, not sent: the channel wrapper reads
        :class:`ChartReply` and delivers it (Telegram as a photo with the
        ranking as its message), so this method never has to know which
        chat asked. It is therefore equally dispatchable from a schedule or
        another agent — the caller decides where the chart lands.

        Args:
            window_days: Width of the window in days, default 30. Telegram
                passes command arguments as strings
                (``/monthly_jira_tickets window_days=60``), so the value is
                coerced; anything unparseable or non-positive falls back to
                the default.

        Returns:
            A :class:`ChartReply` with the ranking text and, when PNG
            export worked, one pie-chart attachment. Jira failures come
            back as a one-line notice, not an exception.
        """
        if kwargs:
            self.logger.debug(
                "/monthly_jira_tickets: ignoring unexpected arguments %s",
                sorted(kwargs),
            )
        try:
            days = self._TICKET_MONTH_DAYS if window_days is None else int(window_days)
        except (TypeError, ValueError):
            self.logger.warning(
                "/monthly_jira_tickets: unparseable window_days=%r; using %s.",
                window_days,
                self._TICKET_MONTH_DAYS,
            )
            days = self._TICKET_MONTH_DAYS
        if days <= 0:
            days = self._TICKET_MONTH_DAYS

        built = await self._build_monthly_ticket_pie(window_days=days)
        if built["status"] == "error":
            return ChartReply(output=f"⚠️ Could not read {self.jira_project} tickets: {built.get('reason')}")
        if built["status"] == "empty":
            return ChartReply(output=f"No {self.jira_project} ticket was touched in the last {days} days.")

        chart = built["chart"]
        charts: List[Dict[str, Any]] = []
        if chart is not None:
            charts.append(
                {
                    "path": str(chart),
                    "title": built["title"],
                    "chart_type": "pie",
                    "format": "png",
                }
            )
        return ChartReply(
            output=self._format_monthly_tickets_text(built["summary"], built["slices"]),
            charts=charts,
        )

    # Monthly, on the 1st at 10:00 America/New_York — the same timezone-aware
    # cron as the daily ticket digest (see the note on report_jira_tickets):
    # ScheduleType.DAILY/WEEKLY carry a report marker whose config is
    # re-resolved from {AGENT_ID}_DAILY_REPORT at register time and fire on
    # the scheduler's UTC clock, and there is no monthly report type at all.
    @schedule(
        schedule_type=ScheduleType.CRON,
        day=_TICKET_MONTH_REPORT_DAY,
        hour=_TICKET_REPORT_HOUR,
        minute=_TICKET_REPORT_MINUTE,
        timezone=_TICKET_REPORT_TIMEZONE,
    )
    async def report_monthly_jira_tickets(self, window_days: Optional[int] = None) -> Dict[str, Any]:
        """Send the monthly ticket pie to the management channel.

        The scheduled twin of :meth:`monthly_jira_tickets`: same numbers,
        same chart, but it delivers them itself — on the 1st of the month
        to :attr:`management_chat_id` (``GITHUB_MANAGEMENT_TELEGRAM_CHAT_ID``,
        falling back to the public channel), alongside the other reports
        people read to follow the project.

        The table rides as the photo's caption when it fits Telegram's
        1024-character limit, so the chat shows one item instead of two;
        otherwise the digest goes as its own message. Without a PNG
        (no ``vl-convert-python``) only that message goes out — a missing
        chart never costs the report.

        Args:
            window_days: Width of the window in days; defaults to
                :attr:`_TICKET_MONTH_DAYS` (30).

        Returns:
            A status dict with ``status``, ``project``, ``window_days``,
            ``ticket_count``, ``wedges``, ``chart`` (the PNG's name or
            ``None``) and ``messages_sent``.
        """
        days = self._TICKET_MONTH_DAYS if window_days is None else int(window_days)
        built = await self._build_monthly_ticket_pie(window_days=days)
        base: Dict[str, Any] = {
            "status": built["status"],
            "project": self.jira_project,
            "window_days": days,
        }
        if built["status"] == "error":
            return {**base, "reason": built.get("reason")}

        summary = built.get("summary") or {}
        base = {
            **base,
            "status": "ok",
            "ticket_count": int(summary.get("ticket_count") or 0),
            "wedges": len(built["slices"]),
            "chart": built["chart"].name if built["chart"] is not None else None,
        }
        if built["status"] == "empty":
            # Silent exit: an empty pie is noise, like the daily digest's.
            return {**base, "messages_sent": 0}

        bot = self._get_telegram_bot()
        if bot is None or not self.management_chat_id:
            self.logger.warning(
                "GitHubReviewer: monthly ticket pie ready but no %s to send it to; skipping.",
                "Telegram bot" if bot is None else "management chat id",
            )
            return {**base, "messages_sent": 0}

        digest = self._format_monthly_tickets_digest(summary, built["slices"])
        chart = built["chart"]
        caption: Optional[str] = None
        messages_sent = 0
        if chart is not None:
            # The table rides along as the caption when it fits, so the
            # channel shows one item instead of two.
            caption = digest if len(digest) <= self._TELEGRAM_MAX_CAPTION else None
            try:
                # aiogram lives in ai-parrot-integrations, like the wrapper
                # that owns this bot — imported here, not at module import.
                from aiogram.types import FSInputFile

                await bot.send_photo(
                    chat_id=self.management_chat_id,
                    photo=FSInputFile(chart),
                    caption=caption,
                    parse_mode="HTML",
                )
                messages_sent += 1
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "GitHubReviewer: failed to send the monthly ticket pie to chat %s: %s",
                    self.management_chat_id,
                    exc,
                )
                # The numbers are the report; a lost photo must not take
                # them with it, so the digest goes out on its own below.
                caption = None

        if caption is None:
            try:
                await bot.send_message(
                    chat_id=self.management_chat_id,
                    text=digest,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                messages_sent += 1
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "GitHubReviewer: failed to send the monthly ticket digest to chat %s: %s",
                    self.management_chat_id,
                    exc,
                )

        return {**base, "messages_sent": messages_sent}

    # ------------------------------------------------------------------
    # Weekly activity report helpers (FEAT-180)
    # ------------------------------------------------------------------

    def _build_weekly_summary(
        self,
        contributors: List[ContributorStats],
        code_freq: List[WeeklyCodeFrequency],
        *,
        threshold_weeks: int,
        top_n: int = 10,
        now: Optional[datetime] = None,
    ) -> WeeklyActivitySummary:
        """Reshape raw stats into a WeeklyActivitySummary for rendering.

        Pure function — no I/O, no LLM calls, no Telegram. Deterministic given
        the same inputs and ``now`` value.

        Args:
            contributors: Per-contributor weekly stats from :meth:`GitToolkit.get_contributor_stats`.
            code_freq: Repo-wide weekly code frequency from :meth:`GitToolkit.get_code_frequency`.
                May be empty: the reporting window is then taken from ``contributors``
                alone and the result carries ``code_freq_available=False``.
            threshold_weeks: Number of consecutive zero-commit weeks to flag a
                contributor as silent.
            top_n: Maximum number of active contributors in the output (silent list
                is uncapped).
            now: Reference point for "current" week (defaults to
                ``datetime.now(timezone.utc)``).

        Returns:
            A :class:`WeeklyActivitySummary` covering the most recently completed
            GitHub-aligned (Sunday 00:00 UTC) week strictly before ``now``.

        Raises:
            ValueError: When both ``contributors`` and ``code_freq`` are empty
                (cannot determine the reporting window).
        """
        now = now or datetime.now(timezone.utc)

        # 1. Find the most recent completed week's period_start.
        #    Gather all week_start values from contributors and code_freq,
        #    pick the latest one that is strictly before `now`.
        week_starts: List[datetime] = []
        for cs in contributors:
            for w in cs.weeks:
                if w.week_start < now:
                    week_starts.append(w.week_start)
        if not week_starts:
            for cf in code_freq:
                if cf.week_start < now:
                    week_starts.append(cf.week_start)

        if not week_starts:
            raise ValueError(
                "Cannot determine reporting window: no week data before "
                f"{now.isoformat()} found in contributors or code_freq."
            )

        period_start = max(week_starts)
        period_end = period_start + timedelta(days=7)
        prev_period_start = period_start - timedelta(days=7)

        # 2. Build lookup for code_freq by week_start (for totals).
        cf_by_week: Dict[datetime, WeeklyCodeFrequency] = {cf.week_start: cf for cf in code_freq}

        # 3. Per-contributor processing.
        active: List[_ContributorWindowSummary] = []
        silent: List[_ContributorWindowSummary] = []

        for cs in contributors:
            # Skip anonymous (login is None).
            if cs.login is None:
                continue

            # Build a lookup from week_start to week slice.
            week_by_start: Dict[datetime, ContributorWeek] = {w.week_start: w for w in cs.weeks}

            # Current week slice.
            current_slice = week_by_start.get(period_start)
            commits_this_week = current_slice.commits if current_slice else 0
            additions = current_slice.additions if current_slice else 0
            deletions = current_slice.deletions if current_slice else 0

            # Count consecutive silent weeks going backwards from period_start.
            # Only count weeks where we have data AND commits == 0.
            # Stop as soon as we hit a week with commits > 0 OR a week with no data.
            weeks_silent = 0
            check_date = period_start
            while True:
                slice_ = week_by_start.get(check_date)
                if slice_ is None:
                    # No data for this week — treat as a missing slice (not silent).
                    # Count it silent only if it's the current week (no current data
                    # means the contributor was not present this week).
                    if check_date == period_start:
                        weeks_silent += 1
                        check_date = check_date - timedelta(days=7)
                        continue
                    break
                if slice_.commits == 0:
                    weeks_silent += 1
                else:
                    break
                check_date = check_date - timedelta(days=7)

            summary_entry = _ContributorWindowSummary(
                login=cs.login,
                commits_this_week=commits_this_week,
                additions=additions,
                deletions=deletions,
                weeks_silent=weeks_silent,
            )

            if commits_this_week > 0:
                active.append(summary_entry)
            if weeks_silent >= threshold_weeks:
                silent.append(summary_entry)

        # 4. Sort active: commits desc, then additions+deletions desc, then login.
        active.sort(key=lambda c: (-c.commits_this_week, -(c.additions + c.deletions), c.login))
        active = active[:top_n]

        # 5. Sort silent: weeks_silent desc, then login.
        silent.sort(key=lambda c: (-c.weeks_silent, c.login))

        # 6. Totals from contributors (current week).
        total_commits = sum(c.commits_this_week for c in active) + sum(
            c.commits_this_week for c in silent if c.commits_this_week > 0
        )
        # Re-sum from all contributors (active list is truncated).
        all_this_week = [cs for cs in contributors if cs.login is not None]
        total_commits = 0
        total_additions = 0
        total_deletions = 0
        for cs in all_this_week:
            week_by_start = {w.week_start: w for w in cs.weeks}
            current_slice = week_by_start.get(period_start)
            if current_slice:
                total_commits += current_slice.commits
                total_additions += current_slice.additions
                total_deletions += current_slice.deletions

        # 7. Previous week totals from code_freq.
        prev_cf = cf_by_week.get(prev_period_start)
        prev_total_commits = 0  # code_freq doesn't have per-week commit count
        prev_total_additions = prev_cf.additions if prev_cf else 0
        prev_total_deletions = prev_cf.deletions if prev_cf else 0

        # For prev_total_commits: sum from all contributors' prev-week slices.
        for cs in all_this_week:
            week_by_start = {w.week_start: w for w in cs.weeks}
            prev_slice = week_by_start.get(prev_period_start)
            if prev_slice:
                prev_total_commits += prev_slice.commits

        return WeeklyActivitySummary(
            repository=self.repository,
            period_start=period_start,
            period_end=period_end,
            contributors_active=active,
            contributors_silent=silent,
            total_commits=total_commits,
            total_additions=total_additions,
            total_deletions=total_deletions,
            prev_total_commits=prev_total_commits,
            prev_total_additions=prev_total_additions,
            prev_total_deletions=prev_total_deletions,
            code_freq_available=prev_cf is not None,
        )

    _PARTIAL_WEEKLY_NOTICE = (
        "<i>Partial data: GitHub was still computing this repository's "
        "<code>code_frequency</code> stats, so week-over-week line totals are omitted.</i>"
    )
    """Appended to any digest built with ``code_freq_available=False``, so a
    degraded report is never mistaken for a complete one."""

    def _format_weekly_activity_html(
        self,
        summary: WeeklyActivitySummary,
    ) -> str:
        """Build the Telegram HTML body for the weekly activity digest.

        All user-data interpolations are ``html.escape``-d to avoid malformed
        Telegram HTML entities. Uses only the Telegram-whitelisted HTML tag subset:
        ``<b>``, ``<i>``, ``<code>``, ``<a>``, ``<pre>``.

        Args:
            summary: The :class:`WeeklyActivitySummary` to render.

        Returns:
            A Telegram-ready HTML string, under 4096 characters when
            ``summary.contributors_active`` is at most ``top_n`` (default 10).
        """
        repo = html.escape(summary.repository)
        # Display period as Sun → Sat (period_end is the following Sunday, so -1 day)
        period = f"{summary.period_start:%Y-%m-%d} → " f"{(summary.period_end - timedelta(days=1)):%Y-%m-%d}"

        def pct(curr: int, prev: int) -> str:
            """Format a percentage delta string with direction arrow."""
            if prev == 0:
                return "n/a" if curr == 0 else "▲ new"
            delta = (curr - prev) / prev * 100
            if abs(delta) < 0.5:
                return "flat 0%"
            arrow = "▲" if delta > 0 else "▼"
            return f"{arrow} {delta:+.0f}%"

        # Without the previous week's code_frequency slice the prev line totals
        # are unknown rather than zero, so pct() would read "▲ new" off missing
        # data. The commits delta stays: it comes from the contributor slices.
        if summary.code_freq_available:
            line_delta = pct(
                summary.total_additions + summary.total_deletions,
                summary.prev_total_additions + summary.prev_total_deletions,
            )
        else:
            line_delta = "n/a"

        lines: List[str] = [
            f"<b>Weekly activity — <code>{repo}</code></b>",
            f"Period: {period}",
            "",
            (f"<b>{summary.total_commits}</b> commits " f"({pct(summary.total_commits, summary.prev_total_commits)})"),
            (f"{summary.total_additions:,} added / " f"{summary.total_deletions:,} removed " f"({line_delta})"),
        ]

        if summary.contributors_active:
            lines.append("")
            lines.append("<b>Top contributors</b>")
            for i, c in enumerate(summary.contributors_active, start=1):
                login = html.escape(c.login)
                lines.append(
                    f"{i}. <code>{login}</code> — {c.commits_this_week} commits, " f"{c.additions:,} / {c.deletions:,}"
                )

        if summary.contributors_silent:
            lines.append("")
            lines.append("<b>Silent contributors</b>")
            for c in summary.contributors_silent:
                login = html.escape(c.login)
                lines.append(f"<code>{login}</code> — silent {c.weeks_silent} weeks")

        if not summary.code_freq_available:
            lines.append("")
            lines.append(self._PARTIAL_WEEKLY_NOTICE)

        lines.append("")
        lines.append("<i>Posted by the GitHubReviewer agent.</i>")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # LLM prose summarizer (FEAT-180, TASK-1214)
    # ------------------------------------------------------------------

    _WEEKLY_LLM_SYSTEM_PROMPT = (
        "You write concise, factual weekly engineering activity reports for a "
        "software team. Given a structured JSON summary of last week's GitHub "
        "activity, output a short English digest (3-5 short paragraphs total, "
        "~150 words max). Lead with totals, highlight 1-2 notable contributors, "
        "and call out anyone who has gone silent. Do not invent numbers; only "
        "use values present in the input JSON. If 'code_freq_available' is "
        "false, the previous week's line totals are unknown (the zeros are "
        "placeholders): never compare lines added or removed against the "
        "previous week in that case. Do not include HTML tags or "
        "markdown bullets. Plain prose only."
    )

    async def _llm_summarize_weekly(
        self,
        summary: WeeklyActivitySummary,
    ) -> str:
        """Build a prose digest via the agent's LLM.

        Serialises ``summary`` as JSON and calls :meth:`ask` with a tight system
        prompt. On any failure raises :class:`WeeklyLLMSummarizationError` so the
        caller can fall back to the templated output.

        Args:
            summary: The structured summary to rephrase.

        Returns:
            A plain-prose string (no HTML) suitable for wrapping in
            :meth:`_wrap_llm_prose_in_html_envelope`.

        Raises:
            WeeklyLLMSummarizationError: On any exception from :meth:`ask`.
        """
        payload = summary.model_dump(mode="json")
        question = (
            "Summarize this week's GitHub activity. Output prose only.\n\n"
            f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
        )
        try:
            response = await self.ask(
                question=question,
                system_prompt=self._WEEKLY_LLM_SYSTEM_PROMPT,
            )
        except Exception as exc:  # noqa: BLE001
            raise WeeklyLLMSummarizationError(f"LLM weekly summarization failed: {exc}") from exc

        output = getattr(response, "output", response)
        if isinstance(output, str):
            return output.strip()
        return str(output).strip()

    def _wrap_llm_prose_in_html_envelope(
        self,
        prose: str,
        summary: WeeklyActivitySummary,
    ) -> str:
        """Wrap plain LLM prose in a minimal HTML envelope for Telegram.

        Args:
            prose: Plain prose text from the LLM summariser.
            summary: Used to build the header line.

        Returns:
            Telegram-safe HTML with a header, the escaped prose body, and a footer.
        """
        repo = html.escape(summary.repository)
        body = html.escape(prose)
        notice = "" if summary.code_freq_available else f"{self._PARTIAL_WEEKLY_NOTICE}\n\n"
        return (
            f"<b>Weekly activity — <code>{repo}</code></b>\n\n"
            f"{body}\n\n"
            f"{notice}"
            f"<i>Posted by the GitHubReviewer agent.</i>"
        )

    # ------------------------------------------------------------------
    # Weekly activity report orchestrator (FEAT-180, TASK-1215)
    # ------------------------------------------------------------------

    def _defer_weekly_report(self, exc: StatsNotReadyError) -> Dict[str, Any]:
        """Re-run the weekly report later instead of failing on a cold cache.

        GitHub computes ``/stats/*`` lazily, so the request that times out is
        also the one that *starts* the computation: a later attempt normally
        gets 200 for free. This logs a warning without a traceback — a stack
        trace here would describe documented GitHub behaviour, not a defect —
        and publishes nothing to Telegram until there is real data.

        Returns:
            ``status="stats_pending"`` with ``retry_scheduled`` telling the
            caller whether a deferred run was armed. ``retry_scheduled=False``
            means the budget is spent and the deferral lane is done — the
            caller then decides between a partial digest and nothing.
        """
        pending: Dict[str, Any] = {
            "status": "stats_pending",
            "repository": self.repository,
            "reason": str(exc),
            "attempts": exc.attempts,
        }

        if self._weekly_retry_task is not None and not self._weekly_retry_task.done():
            # A deferred run is already armed; never stack two.
            return {**pending, "retry_scheduled": True, "already_armed": True}

        if self._weekly_retry_attempt >= self._stats_retry_max:
            self.logger.warning(
                "GitHubReviewer: weekly stats for %s still not ready after %d deferred "
                "retries; no further deferral.",
                self.repository,
                self._weekly_retry_attempt,
            )
            self._weekly_retry_attempt = 0
            return {**pending, "retry_scheduled": False}

        self._weekly_retry_attempt += 1
        attempt = self._weekly_retry_attempt
        delay = self._stats_retry_delay
        self.logger.warning(
            "GitHubReviewer: weekly stats not ready for %s (%s); retrying in %ds " "(deferred attempt %d/%d).",
            self.repository,
            exc,
            delay,
            attempt,
            self._stats_retry_max,
        )

        async def deferred_run() -> None:
            await asyncio.sleep(delay)
            await self.report_weekly_activity()

        task = asyncio.create_task(
            deferred_run(),
            name=f"github-reviewer-weekly-retry:{self._repository_lc}",
        )
        self._weekly_retry_task = task

        def log_failure(completed: asyncio.Task[None]) -> None:
            if completed.cancelled():
                return
            try:
                completed.result()
            except Exception as task_exc:  # noqa: BLE001 - callback must consume failures
                self.logger.warning(
                    "GitHubReviewer: deferred weekly retry for %s failed: %s",
                    self.repository,
                    task_exc,
                    exc_info=True,
                )

        task.add_done_callback(log_failure)
        return {**pending, "retry_scheduled": True, "retry_in": delay, "attempt": attempt}

    @schedule_weekly_report
    async def report_weekly_activity(self) -> Dict[str, Any]:
        """Compose and send the weekly contributor-activity digest.

        Scheduled by :func:`schedule_weekly_report`. Override the firing
        day/time per deployment via ``{AGENT_ID}_WEEKLY_REPORT=DDD HH:MM``
        (UTC, default ``MON 09:00``).

        Returns:
            A status dict with keys: ``status``, ``repository``,
            ``period_start``, ``period_end``, ``active``, ``silent``,
            ``rendered_via``, ``telegram_sent``, ``partial`` (True when
            ``code_frequency`` never became ready and the digest went out
            without its week-over-week line totals).
        """
        if self.git_toolkit is None:
            self.logger.warning("GitHubReviewer: weekly activity report skipped — " "git_toolkit not configured.")
            return {"status": "error", "reason": "git_toolkit not configured"}

        # return_exceptions: the two /stats endpoints warm up independently, and
        # on a large repo an asymmetric 202 is the normal case. A bare gather()
        # would raise on the pending one and discard the stats that did arrive.
        results = await asyncio.gather(
            self.git_toolkit.get_contributor_stats(repository=self.repository),
            self.git_toolkit.get_code_frequency(repository=self.repository),
            return_exceptions=True,
        )
        contributors, code_freq = results

        # return_exceptions also captures a CancelledError raised inside a call;
        # shutdown must stay a cancellation, not become status="error".
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                raise result

        # A real failure of either call is still an error, with its traceback.
        fatal = next(
            (r for r in results if isinstance(r, BaseException) and not isinstance(r, StatsNotReadyError)),
            None,
        )
        if fatal is not None:
            self.logger.error(
                "GitHubReviewer: weekly stats fetch failed for %s: %s",
                self.repository,
                fatal,
                exc_info=fatal,
            )
            return {"status": "error", "reason": str(fatal)}

        if isinstance(contributors, StatsNotReadyError):
            # The contributor slices carry the whole digest — there is nothing
            # to degrade to. Defer: GitHub is computing, this is not a failure.
            return self._defer_weekly_report(contributors)

        if isinstance(code_freq, StatsNotReadyError):
            deferred = self._defer_weekly_report(code_freq)
            if deferred["retry_scheduled"] or not contributors:
                return deferred
            # Deferral budget spent and the contributor stats are good: publish
            # a partial digest instead of losing the week. code_frequency only
            # feeds the week-over-week line delta, which the renderer then
            # marks unavailable (issue:5bb826dc1922).
            self.logger.warning(
                "GitHubReviewer: publishing a partial weekly digest for %s — "
                "code_frequency never became ready, so week-over-week line "
                "totals are omitted.",
                self.repository,
            )
            code_freq = []

        try:
            summary = self._build_weekly_summary(
                contributors,
                code_freq,
                threshold_weeks=self.silent_weeks_threshold,
                top_n=self.top_n_contributors,
            )
        except ValueError as exc:
            # Empty repo or no historical data.
            self.logger.error(
                "GitHubReviewer: weekly summary build failed for %s: %s",
                self.repository,
                exc,
            )
            # Post a "no data" message to Telegram if available.
            bot = self._get_telegram_bot()
            if bot is not None and self.management_chat_id:
                no_data_msg = (
                    f"<b>Weekly activity — <code>{html.escape(self.repository)}</code></b>\n\n"
                    "No GitHub stats data is available for this week. GitHub may still be "
                    "computing the statistics (202 Accepted). The report will be retried "
                    "next week.\n\n"
                    "<i>Posted by the GitHubReviewer agent.</i>"
                )
                try:
                    await bot.send_message(
                        chat_id=self.management_chat_id,
                        text=no_data_msg,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                except Exception as send_exc:  # noqa: BLE001
                    # Delivery failure is non-fatal here (the caller already
                    # returns status=error for the missing stats), but it must
                    # not be silent: this was the one send path that left no
                    # trace at all.
                    self.logger.warning(
                        "GitHubReviewer: failed to send weekly no-data notice to chat %s: %s",
                        self.management_chat_id,
                        send_exc,
                    )
            return {"status": "error", "reason": str(exc)}

        rendered_via = "templated"
        if self.use_llm_summary:
            try:
                llm_body = await self._llm_summarize_weekly(summary)
                text = self._wrap_llm_prose_in_html_envelope(llm_body, summary)
                rendered_via = "llm"
            except WeeklyLLMSummarizationError as exc:
                self.logger.warning(
                    "GitHubReviewer: LLM summary failed (%s); falling back to " "templated output.",
                    exc,
                )
                text = self._format_weekly_activity_html(summary)
        else:
            text = self._format_weekly_activity_html(summary)

        telegram_sent = 0
        bot = self._get_telegram_bot()
        if bot is not None and self.management_chat_id:
            try:
                await bot.send_message(
                    chat_id=self.management_chat_id,
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                telegram_sent = 1
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "GitHubReviewer: failed to send weekly report to chat %s: %s",
                    self.management_chat_id,
                    exc,
                )

        self.logger.info(
            "GitHubReviewer: weekly activity report — repo=%s, active=%d, "
            "silent=%d, rendered_via=%s, telegram_sent=%d, partial=%s.",
            self.repository,
            len(summary.contributors_active),
            len(summary.contributors_silent),
            rendered_via,
            telegram_sent,
            not summary.code_freq_available,
        )

        # A completed run clears the deferral budget, so a future cold cache
        # gets its own full set of retries instead of inheriting this one's.
        self._weekly_retry_attempt = 0

        return {
            "status": "ok",
            "repository": self.repository,
            "period_start": summary.period_start.isoformat(),
            "period_end": summary.period_end.isoformat(),
            "active": len(summary.contributors_active),
            "silent": len(summary.contributors_silent),
            "rendered_via": rendered_via,
            "telegram_sent": telegram_sent,
            "partial": not summary.code_freq_available,
        }


__all__ = [
    "Discrepancy",
    "PRReviewResult",
    "WeeklyActivitySummary",
    "_ContributorWindowSummary",
    "WeeklyLLMSummarizationError",
    "GitHubReviewer",
]
