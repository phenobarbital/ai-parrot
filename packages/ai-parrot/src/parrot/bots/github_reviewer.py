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
import json
import logging as _stdlib_logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import (
    Any, Awaitable, Callable, Dict, List, Literal, Optional, Tuple, Union,
)

from navconfig import config
from pydantic import BaseModel, Field

from parrot.bots import Agent
from parrot.core.hooks.github_webhook import GitHubWebhookHook
# FEAT-317: GitHubWebhookConfig/HookEvent moved to navigator_eventbus.hooks;
# imported here via the parrot.core.hooks re-export facade.
from parrot.core.hooks import GitHubWebhookConfig, HookEvent
from parrot.models.google import GoogleModel
from parrot.scheduler import schedule_daily_report, schedule_weekly_report
from parrot_tools.gittoolkit import (
    ContributorStats,
    ContributorWeek,
    GitToolkit,
    WeeklyCodeFrequency,
)
from parrot_tools.jiratoolkit import JiraToolkit


ChatId = Union[int, str]


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
        "paragraph", "heading", "bulletList", "orderedList",
        "listItem", "codeBlock", "blockquote", "rule",
    }
    if node.get("type") in block_types and inner:
        return f"{inner}\n"
    return inner


# ──────────────────────────────────────────────────────────────
# Structured output
# ──────────────────────────────────────────────────────────────

class Discrepancy(BaseModel):
    """Single mismatch between the PR and the Jira acceptance criteria."""

    criterion: str = Field(
        description="The acceptance criterion or ticket requirement not met."
    )
    issue: str = Field(
        description="What the PR misses, contradicts or deviates from."
    )
    severity: Literal["minor", "major", "blocker"] = Field(
        description=(
            "Severity. 'blocker' = MUST fix before merge, "
            "'major' = should fix, 'minor' = nice-to-have."
        ),
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

    model = GoogleModel.GEMINI_3_FLASH_PREVIEW

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
        dispatch_logger = _stdlib_logging.getLogger(
            f"parrot.hooks.{name}.dispatch"
        )

        async def _dispatch(event: HookEvent) -> None:
            # Fan out to every registered listener; one listener raising
            # must not block the others from getting the event.
            for listener in list(listeners):
                try:
                    await listener(event)
                except Exception as exc:  # noqa: BLE001
                    dispatch_logger.error(
                        "Listener %r raised on %s: %s",
                        listener, event.event_type, exc,
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
        webhook_public_url: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        stale_after_hours: int = 24,
        max_diff_bytes: int = 50_000,
        max_ticket_bytes: int = 20_000,
        silent_weeks_threshold: int = 3,
        top_n_contributors: int = 10,
        use_llm_summary: bool = False,
        max_review_tool_calls: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("injection_probability_threshold", 0.995)
        kwargs.setdefault("system_prompt", _SYSTEM_PROMPT)
        kwargs.setdefault("prompt_caching", True)  # FEAT-181

        super().__init__(**kwargs)

        self.repository = repository
        self._repository_lc = repository.lower()
        self.jira_project = jira_project
        self.alert_chat_ids: List[ChatId] = list(alert_chat_ids or [])
        self.public_channel_id = public_channel_id
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

        self._ac_field_id: str = config.get(
            "JIRA_ACCEPTANCE_CRITERIA_FIELD", fallback="customfield_10100"
        )
        self._jira_fields: str = ",".join(
            sorted({"summary", "description", "status", self._ac_field_id})
        )

        self._ticket_key_regex = re.compile(
            rf"\b{re.escape(self.jira_project)}-\d+\b"
        )

        self.git_toolkit: Optional[GitToolkit] = None
        self.jira_toolkit: Optional[JiraToolkit] = None
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

        self.git_toolkit = self._build_git_toolkit()
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
                    "GitHubReviewer: hook.start() raised: %s", exc,
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
                name, exc, exc_info=True,
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
                    "GitHubReviewer: failed to build GitHub App toolkit: %s. "
                    "The agent will disable itself.",
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
                    "GitHubReviewer: basic_auth requires JIRA_USERNAME and "
                    "JIRA_API_TOKEN; Jira lookups disabled."
                )
                return None
            toolkit_kwargs["username"] = username
            toolkit_kwargs["password"] = password
        elif effective == "token_auth":
            token = (
                config.get("JIRA_SECRET_TOKEN") or config.get("JIRA_API_TOKEN")
            )
            if not token:
                self.logger.error(
                    "GitHubReviewer: token_auth requires JIRA_SECRET_TOKEN or "
                    "JIRA_API_TOKEN; Jira lookups disabled."
                )
                return None
            toolkit_kwargs["token"] = token
        return JiraToolkit(**toolkit_kwargs)

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
                "GitHubReviewer: token lacks admin:repo_hook on %s; "
                "configure the webhook manually pointing to %s.",
                self.repository,
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

    async def handle_hook_event(
        self, event: HookEvent
    ) -> Optional[Dict[str, Any]]:
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

    async def review_pull_request(
        self, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
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
                repo, pr_number, head_sha,
            )
            return {
                "status": "already_reviewed",
                "pr_number": pr_number,
                "head_sha": head_sha,
            }

        ticket_key = self._extract_ticket_key(
            payload.get("pr_body") or "", payload.get("pr_title") or ""
        )
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
            comment = await self._notify_missing_ticket(
                repo=repo, pr_number=pr_number, payload=payload
            )
            if comment is not None:
                outcome["comment"] = comment
            return outcome

        ticket = await self._fetch_ticket(ticket_key)
        if ticket is None:
            return {
                "status": "ticket_not_found",
                "jira_key": ticket_key,
                "pr_number": pr_number,
            }

        diff_text, diff_truncated, diff_available = await self._fetch_diff(
            repo, pr_number
        )

        result = await self._ask_llm_for_review(
            payload=payload,
            ticket_key=ticket_key,
            ticket=ticket,
            diff_text=diff_text,
            diff_truncated=diff_truncated,
            diff_available=diff_available,
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
        should_post_review = (
            self.git_toolkit is not None
            and (result.approve or result.discrepancies)
        )
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
                    event, repo, pr_number, exc, exc_info=True,
                )
                outcome["review_error"] = str(exc)

            if not result.approve and result.discrepancies:
                outcome["alerts"] = await self._notify_telegram_alert(
                    payload, ticket_key, result
                )

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
                "GitHubReviewer: cannot comment about missing %s ticket on "
                "%s#%s — git_toolkit is not configured.",
                self.jira_project, repo, pr_number,
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
                repo, pr_number, exc, exc_info=True,
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

    async def _fetch_ticket(self, ticket_key: str) -> Optional[Dict[str, Any]]:
        if self.jira_toolkit is None:
            self.logger.warning(
                "GitHubReviewer: jira_toolkit unavailable; cannot fetch %s",
                ticket_key,
            )
            return None
        try:
            envelope = await self.jira_toolkit.jira_get_issue(
                issue=ticket_key,
                fields=self._jira_fields,
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

    async def _fetch_diff(
        self, repo: str, pr_number: int
    ) -> Tuple[str, bool, bool]:
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
                repo, pr_number, exc,
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

    async def _ask_llm_for_review(
        self,
        *,
        payload: Dict[str, Any],
        ticket_key: str,
        ticket: Dict[str, Any],
        diff_text: str,
        diff_truncated: bool,
        diff_available: bool,
    ) -> PRReviewResult:
        fields = (ticket or {}).get("fields") or {}
        summary = _flatten_adf(fields.get("summary")) or ""
        description = self._clamp(_flatten_adf(fields.get("description")))
        # The acceptance-criteria custom field id was resolved in __init__
        # from JIRA_ACCEPTANCE_CRITERIA_FIELD (fallback: customfield_10100)
        # and is included in the Jira ``fields=`` request.
        acceptance_criteria = self._clamp(
            _flatten_adf(fields.get(self._ac_field_id))
        ) or "(not provided)"

        if diff_available:
            diff_block = diff_text or "(empty diff — PR adds/removes nothing)"
            header = f"=== PR diff (truncated={diff_truncated}) ==="
        else:
            diff_block = (
                "(diff unavailable — could not be retrieved from GitHub. "
                "Do NOT conclude that the PR is empty.)"
            )
            header = "=== PR diff (unavailable) ==="

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
            default_summary = (
                "All acceptance criteria are addressed by this PR."
            )
        else:
            header = f"## Automated review — discrepancies vs. {ticket_key}"
            default_summary = (
                "Discrepancies detected against the linked ticket."
            )
        lines: List[str] = [
            header,
            "",
            result.summary or default_summary,
            "",
        ]
        if result.discrepancies:
            lines.append("### Findings")
            for d in result.discrepancies:
                lines.append(
                    f"- **[{d.severity.upper()}] {d.criterion}** — {d.issue}"
                )
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
    # Daily stale PR report
    # ------------------------------------------------------------------

    @schedule_daily_report
    async def report_stale_pull_requests(self) -> Dict[str, Any]:
        """Scan open PRs on the configured repo and announce stale ones.

        A PR is "stale" when its ``created_at`` is older than
        :attr:`stale_after_hours` (defaults to 24h). For every stale PR a
        message is sent to :attr:`public_channel_id`. Returns a small dict
        with counts (useful for tests and scheduler logs).

        Scheduled by :func:`schedule_daily_report`; override the run time
        per deployment via ``{AGENT_ID}_DAILY_REPORT`` env var (``HH:MM`` UTC).
        """
        if self.git_toolkit is None:
            return {"status": "error", "reason": "git_toolkit not configured"}

        try:
            pulls = await self.git_toolkit.list_pull_requests(
                repository=self.repository, state="open", per_page=100
            )
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
        if stale:
            bot = self._get_telegram_bot()
            if bot is not None and self.public_channel_id:
                repo_html = html.escape(self.repository)
                for pr in stale:
                    title = html.escape(str(pr.get("title") or ""))
                    url = html.escape(
                        str(pr.get("html_url") or ""), quote=True
                    )
                    user = html.escape(str(pr.get("user") or "unknown"))
                    text = (
                        f"<b>Stale PR</b> on <code>{repo_html}</code>\n"
                        f'<a href="{url}">{title}</a> — '
                        f"by {user}, open for {pr['age_hours']}h"
                    )
                    try:
                        await bot.send_message(
                            chat_id=self.public_channel_id,
                            text=text,
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                        sent += 1
                    except Exception as exc:  # noqa: BLE001
                        self.logger.warning(
                            "GitHubReviewer: failed to send stale-PR alert: %s",
                            exc,
                        )

        self.logger.info(
            "GitHubReviewer: daily report — %d open PR(s), %d stale, %d announced.",
            len(pulls or []),
            len(stale),
            sent,
        )
        return {
            "status": "ok",
            "repository": self.repository,
            "open_count": len(pulls or []),
            "stale_count": len(stale),
            "announced": sent,
            "stale": stale,
        }

    @staticmethod
    def _parse_iso8601(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

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
        cf_by_week: Dict[datetime, WeeklyCodeFrequency] = {
            cf.week_start: cf for cf in code_freq
        }

        # 3. Per-contributor processing.
        active: List[_ContributorWindowSummary] = []
        silent: List[_ContributorWindowSummary] = []

        for cs in contributors:
            # Skip anonymous (login is None).
            if cs.login is None:
                continue

            # Build a lookup from week_start to week slice.
            week_by_start: Dict[datetime, ContributorWeek] = {
                w.week_start: w for w in cs.weeks
            }

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
        active.sort(
            key=lambda c: (-c.commits_this_week, -(c.additions + c.deletions), c.login)
        )
        active = active[:top_n]

        # 5. Sort silent: weeks_silent desc, then login.
        silent.sort(key=lambda c: (-c.weeks_silent, c.login))

        # 6. Totals from contributors (current week).
        total_commits = sum(c.commits_this_week for c in active) + sum(
            c.commits_this_week for c in silent if c.commits_this_week > 0
        )
        # Re-sum from all contributors (active list is truncated).
        all_this_week = [
            cs for cs in contributors
            if cs.login is not None
        ]
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
        )

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
        period = (
            f"{summary.period_start:%Y-%m-%d} → "
            f"{(summary.period_end - timedelta(days=1)):%Y-%m-%d}"
        )

        def pct(curr: int, prev: int) -> str:
            """Format a percentage delta string with direction arrow."""
            if prev == 0:
                return "n/a" if curr == 0 else "▲ new"
            delta = (curr - prev) / prev * 100
            if abs(delta) < 0.5:
                return "flat 0%"
            arrow = "▲" if delta > 0 else "▼"
            return f"{arrow} {delta:+.0f}%"

        lines: List[str] = [
            f"<b>Weekly activity — <code>{repo}</code></b>",
            f"Period: {period}",
            "",
            (
                f"<b>{summary.total_commits}</b> commits "
                f"({pct(summary.total_commits, summary.prev_total_commits)})"
            ),
            (
                f"{summary.total_additions:,} added / "
                f"{summary.total_deletions:,} removed "
                f"({pct(summary.total_additions + summary.total_deletions, summary.prev_total_additions + summary.prev_total_deletions)})"
            ),
        ]

        if summary.contributors_active:
            lines.append("")
            lines.append("<b>Top contributors</b>")
            for i, c in enumerate(summary.contributors_active, start=1):
                login = html.escape(c.login)
                lines.append(
                    f"{i}. <code>{login}</code> — {c.commits_this_week} commits, "
                    f"{c.additions:,} / {c.deletions:,}"
                )

        if summary.contributors_silent:
            lines.append("")
            lines.append("<b>Silent contributors</b>")
            for c in summary.contributors_silent:
                login = html.escape(c.login)
                lines.append(
                    f"<code>{login}</code> — silent {c.weeks_silent} weeks"
                )

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
        "use values present in the input JSON. Do not include HTML tags or "
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
            raise WeeklyLLMSummarizationError(
                f"LLM weekly summarization failed: {exc}"
            ) from exc

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
        return (
            f"<b>Weekly activity — <code>{repo}</code></b>\n\n"
            f"{body}\n\n"
            f"<i>Posted by the GitHubReviewer agent.</i>"
        )

    # ------------------------------------------------------------------
    # Weekly activity report orchestrator (FEAT-180, TASK-1215)
    # ------------------------------------------------------------------

    @schedule_weekly_report
    async def report_weekly_activity(self) -> Dict[str, Any]:
        """Compose and send the weekly contributor-activity digest.

        Scheduled by :func:`schedule_weekly_report`. Override the firing
        day/time per deployment via ``{AGENT_ID}_WEEKLY_REPORT=DDD HH:MM``
        (UTC, default ``MON 09:00``).

        Returns:
            A status dict with keys: ``status``, ``repository``,
            ``period_start``, ``period_end``, ``active``, ``silent``,
            ``rendered_via``, ``telegram_sent``.
        """
        if self.git_toolkit is None:
            self.logger.warning(
                "GitHubReviewer: weekly activity report skipped — "
                "git_toolkit not configured."
            )
            return {"status": "error", "reason": "git_toolkit not configured"}

        try:
            contributors, code_freq = await asyncio.gather(
                self.git_toolkit.get_contributor_stats(repository=self.repository),
                self.git_toolkit.get_code_frequency(repository=self.repository),
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "GitHubReviewer: weekly stats fetch failed for %s: %s",
                self.repository,
                exc,
                exc_info=True,
            )
            return {"status": "error", "reason": str(exc)}

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
            if bot is not None and self.public_channel_id:
                no_data_msg = (
                    f"<b>Weekly activity — <code>{html.escape(self.repository)}</code></b>\n\n"
                    "No GitHub stats data is available for this week. GitHub may still be "
                    "computing the statistics (202 Accepted). The report will be retried "
                    "next week.\n\n"
                    "<i>Posted by the GitHubReviewer agent.</i>"
                )
                try:
                    await bot.send_message(
                        chat_id=self.public_channel_id,
                        text=no_data_msg,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                except Exception:  # noqa: BLE001
                    pass
            return {"status": "error", "reason": str(exc)}

        rendered_via = "templated"
        if self.use_llm_summary:
            try:
                llm_body = await self._llm_summarize_weekly(summary)
                text = self._wrap_llm_prose_in_html_envelope(llm_body, summary)
                rendered_via = "llm"
            except WeeklyLLMSummarizationError as exc:
                self.logger.warning(
                    "GitHubReviewer: LLM summary failed (%s); falling back to "
                    "templated output.",
                    exc,
                )
                text = self._format_weekly_activity_html(summary)
        else:
            text = self._format_weekly_activity_html(summary)

        telegram_sent = 0
        bot = self._get_telegram_bot()
        if bot is not None and self.public_channel_id:
            try:
                await bot.send_message(
                    chat_id=self.public_channel_id,
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                telegram_sent = 1
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "GitHubReviewer: failed to send weekly report: %s", exc,
                )

        self.logger.info(
            "GitHubReviewer: weekly activity report — repo=%s, active=%d, "
            "silent=%d, rendered_via=%s, telegram_sent=%d.",
            self.repository,
            len(summary.contributors_active),
            len(summary.contributors_silent),
            rendered_via,
            telegram_sent,
        )

        return {
            "status": "ok",
            "repository": self.repository,
            "period_start": summary.period_start.isoformat(),
            "period_end": summary.period_end.isoformat(),
            "active": len(summary.contributors_active),
            "silent": len(summary.contributors_silent),
            "rendered_via": rendered_via,
            "telegram_sent": telegram_sent,
        }


__all__ = [
    "Discrepancy",
    "PRReviewResult",
    "WeeklyActivitySummary",
    "_ContributorWindowSummary",
    "WeeklyLLMSummarizationError",
    "GitHubReviewer",
]
