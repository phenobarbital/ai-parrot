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
  structured comparison and — when discrepancies are found — submits a
  ``REQUEST_CHANGES`` review and alerts the configured Telegram chats.
* :meth:`report_stale_pull_requests` is decorated with
  :func:`schedule_daily_report` so it runs once a day and reports every open
  PR older than 24h to a public Telegram channel.

Authentication, toolkit wiring and the LLM model selection follow the same
pattern as :class:`JiraSpecialist` so a deployment that already runs
JiraSpecialist needs no extra plumbing beyond a new ``@register_agent``
subclass per watched repository.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from navconfig import config
from pydantic import BaseModel, Field

from parrot.auth.credentials import OAuthCredentialResolver
from parrot.bots import Agent
from parrot.core.hooks.models import HookEvent
from parrot.models.google import GoogleModel
from parrot.scheduler import schedule_daily_report
from parrot_tools.gittoolkit import GitToolkit
from parrot_tools.jiratoolkit import JiraToolkit


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
"""


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
    """

    model = GoogleModel.GEMINI_3_FLASH_PREVIEW

    def __init__(
        self,
        repository: str,
        *,
        jira_project: str = "NAV",
        alert_chat_ids: Optional[List[int]] = None,
        public_channel_id: Optional[Any] = None,
        webhook_public_url: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        stale_after_hours: int = 24,
        max_diff_bytes: int = 50_000,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("injection_probability_threshold", 0.995)
        kwargs.setdefault("system_prompt", _SYSTEM_PROMPT)

        self._init_kwargs: Dict[str, Any] = dict(
            kwargs,
            repository=repository,
            jira_project=jira_project,
            alert_chat_ids=list(alert_chat_ids or []),
            public_channel_id=public_channel_id,
            webhook_public_url=webhook_public_url,
            webhook_secret=webhook_secret,
            stale_after_hours=stale_after_hours,
            max_diff_bytes=max_diff_bytes,
        )

        super().__init__(**kwargs)

        self.repository = repository
        self.jira_project = jira_project
        self.alert_chat_ids: List[int] = [int(c) for c in (alert_chat_ids or [])]
        self.public_channel_id = public_channel_id
        self.webhook_public_url = webhook_public_url
        self.webhook_secret = webhook_secret
        self.stale_after_hours = int(stale_after_hours)
        self.max_diff_bytes = int(max_diff_bytes)

        self._ticket_key_regex = re.compile(
            rf"\b{re.escape(self.jira_project)}-\d+\b"
        )

        self.git_toolkit: Optional[GitToolkit] = None
        self.jira_toolkit: Optional[JiraToolkit] = None
        self._wrapper = None  # Set by TelegramAgentWrapper after init

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
        is attached. Auth selection mirrors :class:`JiraSpecialist`.
        """
        await super().post_configure()

        self.git_toolkit = self._build_git_toolkit()
        self.jira_toolkit = self._build_jira_toolkit()

        if self.git_toolkit is not None:
            try:
                tools = self.tool_manager.register_toolkit(self.git_toolkit)
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "GitHubReviewer: failed to register Git tools: %s",
                    exc,
                    exc_info=True,
                )
            else:
                if tools:
                    if not hasattr(self, "tools") or self.tools is None:
                        self.tools = []
                    self.tools.extend(tools)

        if self.jira_toolkit is not None:
            try:
                tools = self.tool_manager.register_toolkit(self.jira_toolkit)
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "GitHubReviewer: failed to register Jira tools: %s",
                    exc,
                    exc_info=True,
                )
            else:
                if tools:
                    if not hasattr(self, "tools") or self.tools is None:
                        self.tools = []
                    self.tools.extend(tools)

        if self._llm is not None and hasattr(self._llm, "tool_manager"):
            try:
                self.sync_tools(self._llm)
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "GitHubReviewer: failed to sync tools to LLM: %s",
                    exc,
                    exc_info=True,
                )

        await self._ensure_webhook_subscription()

    def _build_git_toolkit(self) -> Optional[GitToolkit]:
        token = config.get("GITHUB_TOKEN")
        if not token:
            self.logger.warning(
                "GitHubReviewer: GITHUB_TOKEN is not set; PR operations "
                "will fail until a token is configured."
            )
        return GitToolkit(
            default_repository=self.repository,
            default_branch=config.get("GIT_DEFAULT_BRANCH", fallback="main"),
            github_token=token,
        )

    def _build_jira_toolkit(self) -> Optional[JiraToolkit]:
        auth_type = (config.get("JIRA_AUTH_TYPE") or "").lower()
        oauth_manager = self.app.get("jira_oauth_manager") if self.app else None
        use_oauth = auth_type == "oauth2_3lo" or (
            not auth_type and oauth_manager is not None
        )

        if use_oauth:
            if oauth_manager is None:
                self.logger.warning(
                    "GitHubReviewer: JIRA_AUTH_TYPE=oauth2_3lo but "
                    "app['jira_oauth_manager'] is missing; Jira lookups disabled."
                )
                return None
            return JiraToolkit(
                auth_type="oauth2_3lo",
                credential_resolver=OAuthCredentialResolver(oauth_manager),
                default_project=self.jira_project,
            )

        effective = auth_type or "basic_auth"
        toolkit_kwargs: Dict[str, Any] = {
            "server_url": config.get("JIRA_INSTANCE"),
            "auth_type": effective,
            "default_project": self.jira_project,
        }
        if effective == "basic_auth":
            toolkit_kwargs["username"] = config.get("JIRA_USERNAME")
            toolkit_kwargs["password"] = config.get("JIRA_API_TOKEN")
        elif effective == "token_auth":
            toolkit_kwargs["token"] = (
                config.get("JIRA_SECRET_TOKEN") or config.get("JIRA_API_TOKEN")
            )
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
        if payload.get("repository") and payload["repository"] != self.repository:
            return None  # multi-tenant guard

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
                ``pr_title``, ``pr_url`` and ``repository``.

        Returns:
            A dict with ``status`` and the relevant artifacts (jira key,
            review id, alert results). On the unhappy path ``status`` is one
            of ``"no_ticket"``, ``"ticket_not_found"`` or ``"error"``.
        """
        pr_number = payload.get("pr_number")
        if pr_number is None:
            return {"status": "error", "reason": "missing pr_number"}

        repo = payload.get("repository") or self.repository
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
            return {"status": "no_ticket", "pr_number": pr_number}

        ticket = await self._fetch_ticket(ticket_key)
        if ticket is None:
            return {
                "status": "ticket_not_found",
                "jira_key": ticket_key,
                "pr_number": pr_number,
            }

        diff_text, diff_truncated = await self._fetch_diff(repo, pr_number)

        result = await self._ask_llm_for_review(
            payload=payload,
            ticket_key=ticket_key,
            ticket=ticket,
            diff_text=diff_text,
            diff_truncated=diff_truncated,
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

        if not result.approve and result.discrepancies:
            review_body = self._format_review_body(payload, ticket_key, result)
            try:
                review_response = await self.git_toolkit.submit_pr_review(
                    pr_number=pr_number,
                    event="REQUEST_CHANGES",
                    body=review_body,
                    repository=repo,
                )
                outcome["review"] = review_response
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "GitHubReviewer: failed to submit review on %s#%s: %s",
                    repo,
                    pr_number,
                    exc,
                    exc_info=True,
                )
                outcome["review_error"] = str(exc)

            outcome["alerts"] = await self._notify_telegram_alert(
                payload, ticket_key, result
            )

        return outcome

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
                fields="summary,description,status,customfield_10100",
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "GitHubReviewer: jira_get_issue(%s) failed: %s",
                ticket_key,
                exc,
                exc_info=True,
            )
            return None

        status = (envelope or {}).get("status")
        if status not in ("ok",):
            return None
        return (envelope or {}).get("data")

    async def _fetch_diff(self, repo: str, pr_number: int) -> tuple[str, bool]:
        if self.git_toolkit is None:
            return ("", False)
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
            return ("", False)
        return (data.get("diff", ""), bool(data.get("truncated")))

    async def _ask_llm_for_review(
        self,
        *,
        payload: Dict[str, Any],
        ticket_key: str,
        ticket: Dict[str, Any],
        diff_text: str,
        diff_truncated: bool,
    ) -> PRReviewResult:
        fields = (ticket or {}).get("fields") or {}
        summary = fields.get("summary") or ""
        description = fields.get("description") or ""
        # Jira's "Acceptance Criteria" custom field default id; teams override
        # via JIRA_ACCEPTANCE_CRITERIA_FIELD.
        ac_field_id = config.get(
            "JIRA_ACCEPTANCE_CRITERIA_FIELD", fallback="customfield_10100"
        )
        acceptance_criteria = fields.get(ac_field_id) or "(not provided)"

        question = (
            f"Review pull request {payload.get('repository')}#"
            f"{payload.get('pr_number')} against Jira ticket {ticket_key}.\n\n"
            f"PR title: {payload.get('pr_title', '')}\n"
            f"PR body:\n{payload.get('pr_body', '')}\n\n"
            f"=== Jira ticket {ticket_key} ===\n"
            f"Summary: {summary}\n\n"
            f"Description:\n{description}\n\n"
            f"Acceptance Criteria:\n{acceptance_criteria}\n\n"
            f"=== PR diff (truncated={diff_truncated}) ===\n"
            f"{diff_text or '(empty diff)'}\n\n"
            "Compare them and return a PRReviewResult JSON object."
        )

        try:
            response = await self.ask(
                question=question, structured_output=PRReviewResult
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
        lines: List[str] = [
            f"## Automated review — discrepancies vs. {ticket_key}",
            "",
            result.summary or "Discrepancies detected against the linked ticket.",
            "",
            "### Findings",
        ]
        for d in result.discrepancies:
            lines.append(
                f"- **[{d.severity.upper()}] {d.criterion}** — {d.issue}"
            )
        lines.extend(
            [
                "",
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
                    parse_mode="Markdown",
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
        blockers = sum(1 for d in result.discrepancies if d.severity == "blocker")
        majors = sum(1 for d in result.discrepancies if d.severity == "major")
        minors = sum(1 for d in result.discrepancies if d.severity == "minor")
        lines = [
            "*PR review — discrepancies*",
            f"Repo: `{payload.get('repository')}`",
            f"PR: [{payload.get('pr_title', '')}]({payload.get('pr_url', '')})",
            f"Ticket: `{ticket_key}`",
            f"Severity: blocker={blockers}, major={majors}, minor={minors}",
            "",
            result.summary or "(no summary)",
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
                for pr in stale:
                    text = (
                        f"*Stale PR* on `{self.repository}`\n"
                        f"[{pr['title']}]({pr['html_url']}) — "
                        f"by {pr['user']}, open for {pr['age_hours']}h"
                    )
                    try:
                        await bot.send_message(
                            chat_id=self.public_channel_id,
                            text=text,
                            parse_mode="Markdown",
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


__all__ = [
    "Discrepancy",
    "PRReviewResult",
    "GitHubReviewer",
]
