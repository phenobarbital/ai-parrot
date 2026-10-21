"""Unit tests for GitHubReviewer pure helpers.

Avoids instantiating the full ``Agent`` MRO (which requires the Cython
``parrot.utils.types`` extension at import time) by exercising the pure /
static helpers directly. End-to-end review flow is covered by integration
tests.
"""

from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot import conf
from parrot.bots import github_reviewer
from parrot.bots.github_reviewer import (
    ChatId,
    ChartReply,
    Discrepancy,
    GitHubReviewer,
    MergeVerdict,
    PRChecksSummary,
    PRReviewResult,
    WeeklyActivitySummary,
    WeeklyLLMSummarizationError,
    _ContributorWindowSummary,
    _flatten_adf,
    _read_only_excludes,
    _STRUCTURAL_READ_TOOLS,
    _WIKI_READ_TOOLS,
    _WIKI_TOOLS_PROMPT,
)
from parrot_tools.gittoolkit import (
    ContributorStats,
    ContributorWeek,
    StatsNotReadyError,
    WeeklyCodeFrequency,
)


class _MinimalReviewer:
    """Cheap stand-in that reuses real helpers but skips Agent.__init__."""

    def __init__(
        self,
        repository: str = "owner/repo",
        jira_project: str = "NAV",
        max_ticket_bytes: int = 20_000,
        ac_field_id: str = "customfield_10100",
    ) -> None:
        self.repository = repository
        self._repository_lc = repository.lower()
        self.jira_project = jira_project
        self.max_ticket_bytes = max_ticket_bytes
        self._ac_field_id = ac_field_id
        self._jira_fields = ",".join(sorted({"summary", "description", "status", ac_field_id}))
        self._jira_strict_fields = ",".join(sorted({"summary", "description", "status", "assignee", ac_field_id}))
        self._ticket_key_regex = re.compile(rf"\b{re.escape(jira_project)}-\d+\b")
        # /review_pr gate knobs — mirror GitHubReviewer.__init__ defaults.
        self.min_check_pass_ratio = 0.8
        self.require_checks = False
        self.public_channel_id: Optional[ChatId] = None
        self._reviewed_shas: Dict[Any, str] = {}
        # Mirrors GitHubReviewer.__init__: an unset management chat falls back
        # to the public channel, so the management reports never go silent.
        # A property (not a plain attribute) because tests assign
        # ``public_channel_id`` after construction.
        self._management_chat_id: Optional[ChatId] = None
        self._no_ticket_notified: set = set()
        self._wiki_cache = None
        self._wiki_warmup_task = None
        self._wiki_refresh_task = None
        self._wiki_toolkits_attached = False
        self._wiki_store = None
        self._wiki_branch = None
        self._wiki_built_at = None
        self._wiki_context_available = False
        self._llm = None

    @property
    def management_chat_id(self) -> Optional[ChatId]:
        return self._management_chat_id or self.public_channel_id

    @management_chat_id.setter
    def management_chat_id(self, value: Optional[ChatId]) -> None:
        self._management_chat_id = value

    # Bind the real helpers we want to test.
    _extract_ticket_key = GitHubReviewer._extract_ticket_key
    _format_review_body = GitHubReviewer._format_review_body
    _format_alert_message = GitHubReviewer._format_alert_message
    _format_no_ticket_comment = GitHubReviewer._format_no_ticket_comment
    _clamp = GitHubReviewer._clamp
    _fetch_ticket = GitHubReviewer._fetch_ticket
    _notify_missing_ticket = GitHubReviewer._notify_missing_ticket
    _build_wiki_context = GitHubReviewer._build_wiki_context
    _ask_llm_for_review = GitHubReviewer._ask_llm_for_review
    review_pull_request = GitHubReviewer.review_pull_request
    handle_hook_event = GitHubReviewer.handle_hook_event
    report_stale_pull_requests = GitHubReviewer.report_stale_pull_requests
    today_pr = GitHubReviewer.today_pr
    _chunk_digest_messages = GitHubReviewer._chunk_digest_messages
    _format_pr_digest = GitHubReviewer._format_pr_digest
    _format_stale_prs_digest = GitHubReviewer._format_stale_prs_digest
    _format_today_prs_digest = GitHubReviewer._format_today_prs_digest
    _pr_state_label = staticmethod(GitHubReviewer._pr_state_label)
    # Already bound to GitHubReviewer as a classmethod — assign it as-is.
    _is_open_pull_request = GitHubReviewer._is_open_pull_request
    report_weekly_activity = GitHubReviewer.report_weekly_activity
    _defer_weekly_report = GitHubReviewer._defer_weekly_report
    _shutdown_weekly_retry = GitHubReviewer._shutdown_weekly_retry
    # staticmethod(): a bare assignment would rebind it as an instance method.
    _parse_iso8601 = staticmethod(GitHubReviewer._parse_iso8601)
    _get_telegram_bot = GitHubReviewer._get_telegram_bot
    _build_wiki_cache = GitHubReviewer._build_wiki_cache
    _schedule_wiki_warmup = GitHubReviewer._schedule_wiki_warmup
    _shutdown_wiki_warmup = GitHubReviewer._shutdown_wiki_warmup
    _refresh_wiki_context = GitHubReviewer._refresh_wiki_context
    _start_wiki_refresh = GitHubReviewer._start_wiki_refresh
    _await_wiki_refresh = GitHubReviewer._await_wiki_refresh
    _wiki_review_lease = GitHubReviewer._wiki_review_lease
    _attach_wiki_toolkits = GitHubReviewer._attach_wiki_toolkits
    _document_wiki_tools = GitHubReviewer._document_wiki_tools
    # Class-level constants needed by some helpers.
    _WEEKLY_LLM_SYSTEM_PROMPT = GitHubReviewer._WEEKLY_LLM_SYSTEM_PROMPT
    _PARTIAL_WEEKLY_NOTICE = GitHubReviewer._PARTIAL_WEEKLY_NOTICE
    _TELEGRAM_MAX_MESSAGE = GitHubReviewer._TELEGRAM_MAX_MESSAGE
    _TELEGRAM_PART_RESERVE = GitHubReviewer._TELEGRAM_PART_RESERVE
    _STALE_TITLE_MAX = GitHubReviewer._STALE_TITLE_MAX
    _TODAY_PR_HEADING = GitHubReviewer._TODAY_PR_HEADING
    _TODAY_PR_WINDOW_HOURS = GitHubReviewer._TODAY_PR_WINDOW_HOURS
    # Jira ticket summary (open / in progress / closed by assignee).
    report_jira_tickets = GitHubReviewer.report_jira_tickets
    _collect_ticket_summary = GitHubReviewer._collect_ticket_summary
    _summarize_tickets = GitHubReviewer._summarize_tickets
    _format_jira_tickets_digest = GitHubReviewer._format_jira_tickets_digest
    _format_ticket_counts = GitHubReviewer._format_ticket_counts
    _ticket_bucket = classmethod(GitHubReviewer._ticket_bucket.__func__)
    _ticket_assignee = staticmethod(GitHubReviewer._ticket_assignee)
    _TICKET_RECENT_HOURS = GitHubReviewer._TICKET_RECENT_HOURS
    _TICKET_WINDOW_DAYS = GitHubReviewer._TICKET_WINDOW_DAYS
    _TICKET_SUMMARY_FIELDS = GitHubReviewer._TICKET_SUMMARY_FIELDS
    _TICKET_BUCKETS = GitHubReviewer._TICKET_BUCKETS
    _TICKET_BUCKET_ORDER = GitHubReviewer._TICKET_BUCKET_ORDER
    _TICKET_ASSIGNEE_MAX = GitHubReviewer._TICKET_ASSIGNEE_MAX
    _TICKET_HEADING = GitHubReviewer._TICKET_HEADING
    # Monthly ticket pie (/monthly_jira_tickets + the 1st-of-month report).
    monthly_jira_tickets = GitHubReviewer.monthly_jira_tickets
    report_monthly_jira_tickets = GitHubReviewer.report_monthly_jira_tickets
    _TELEGRAM_MAX_CAPTION = GitHubReviewer._TELEGRAM_MAX_CAPTION
    _ticket_pie_slices = classmethod(GitHubReviewer._ticket_pie_slices.__func__)
    _render_ticket_pie = GitHubReviewer._render_ticket_pie
    _format_monthly_tickets_text = GitHubReviewer._format_monthly_tickets_text
    _format_monthly_tickets_digest = GitHubReviewer._format_monthly_tickets_digest
    _monthly_ticket_headings = GitHubReviewer._monthly_ticket_headings
    _monthly_ticket_rows = GitHubReviewer._monthly_ticket_rows
    _build_monthly_ticket_pie = GitHubReviewer._build_monthly_ticket_pie
    _TICKET_MONTH_DAYS = GitHubReviewer._TICKET_MONTH_DAYS
    _TICKET_PIE_MAX_SLICES = GitHubReviewer._TICKET_PIE_MAX_SLICES
    _TICKET_PIE_OTHERS = GitHubReviewer._TICKET_PIE_OTHERS
    # Strict on-demand gate (/review_pr).
    review_pr = GitHubReviewer.review_pr
    strict_review_pull_request = GitHubReviewer.strict_review_pull_request
    _parse_pr_target = classmethod(GitHubReviewer._parse_pr_target.__func__)
    _summarize_checks = classmethod(GitHubReviewer._summarize_checks.__func__)
    _fetch_pr_payload = GitHubReviewer._fetch_pr_payload
    _fetch_checks = GitHubReviewer._fetch_checks
    _merge_verdict = GitHubReviewer._merge_verdict
    _submit_review = GitHubReviewer._submit_review
    _format_checks_line = GitHubReviewer._format_checks_line
    _format_block_comment = GitHubReviewer._format_block_comment
    _format_deferred_body = GitHubReviewer._format_deferred_body
    _format_command_reply = GitHubReviewer._format_command_reply
    _format_blocked_message = GitHubReviewer._format_blocked_message
    _deferral_cause = staticmethod(GitHubReviewer._deferral_cause)
    _format_findings_section = GitHubReviewer._format_findings_section
    _notify_blocked_pr = GitHubReviewer._notify_blocked_pr
    _resolve_assignee = GitHubReviewer._resolve_assignee
    _roster = GitHubReviewer._roster
    _telegram_mention = staticmethod(GitHubReviewer._telegram_mention)
    _TEST_CHECK_RE = GitHubReviewer._TEST_CHECK_RE
    _PR_URL_RE = GitHubReviewer._PR_URL_RE
    _PR_SLUG_RE = GitHubReviewer._PR_SLUG_RE
    _PR_NUMBER_RE = GitHubReviewer._PR_NUMBER_RE
    # Resolved/Closed ticket listing (report_resolved_tickets).
    report_resolved_tickets = GitHubReviewer.report_resolved_tickets
    _collect_resolved_tickets = GitHubReviewer._collect_resolved_tickets
    _resolved_ticket_rows = GitHubReviewer._resolved_ticket_rows
    _format_resolved_tickets_digest = GitHubReviewer._format_resolved_tickets_digest
    _jira_browse_url = GitHubReviewer._jira_browse_url
    _RESOLVED_WINDOW_HOURS = GitHubReviewer._RESOLVED_WINDOW_HOURS
    _RESOLVED_STATUSES = GitHubReviewer._RESOLVED_STATUSES
    _RESOLVED_FIELDS = GitHubReviewer._RESOLVED_FIELDS
    _RESOLVED_HEADING = GitHubReviewer._RESOLVED_HEADING
    _RESOLVED_SUMMARY_MAX = GitHubReviewer._RESOLVED_SUMMARY_MAX


class _StubEvent:
    """Stand-in for parrot.core.hooks.models.HookEvent — only the fields
    handle_hook_event reads."""

    def __init__(self, event_type: str, payload: Dict[str, Any]):
        self.event_type = event_type
        self.payload = payload


def _wire_reviewer(**overrides: Any) -> _MinimalReviewer:
    """Build a stub reviewer with mocked toolkits + logger.

    Tests can patch the returned reviewer further before exercising it.
    """
    r = _MinimalReviewer(**overrides)
    r.logger = MagicMock()
    r.git_toolkit = MagicMock()
    r.jira_toolkit = MagicMock()
    r._wrapper = None
    return r


class TestWikiLifecycle:
    """Focused lifecycle coverage for the optional reviewer wiki plane."""

    async def test_wiki_cache_disabled_by_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Disabled configuration creates neither cache nor warm-up task."""
        reviewer = _wire_reviewer()
        monkeypatch.setattr(conf, "GITHUB_REVIEW_WIKI_ENABLED", False)
        monkeypatch.setattr(conf, "GITHUB_REVIEW_CACHE_DIR", str(tmp_path))

        assert reviewer._build_wiki_cache() is None
        await reviewer._schedule_wiki_warmup()
        assert reviewer._wiki_warmup_task is None

    async def test_warmup_task_is_owned_and_cancelled(self) -> None:
        """Warm-up is named, retained and cancelled by its lifecycle helper."""
        reviewer = _wire_reviewer()
        started = asyncio.Event()
        release = asyncio.Event()

        async def refresh(repository: str) -> None:
            started.set()
            await release.wait()

        reviewer._wiki_cache = MagicMock()
        reviewer._refresh_wiki_context = refresh
        await reviewer._schedule_wiki_warmup()
        task = reviewer._wiki_warmup_task
        assert task is not None
        assert task.get_name() == "github-reviewer-wiki-warmup:owner/repo"
        await started.wait()

        await reviewer._shutdown_wiki_warmup()
        assert reviewer._wiki_warmup_task is None
        assert task.cancelled()

    async def test_enrichment_ignores_foreign_payload_repository(self) -> None:
        """A different payload repository cannot select another cache entry."""
        reviewer = _wire_reviewer()
        reviewer._wiki_cache = MagicMock()
        reviewer._wiki_cache.ensure_fresh = AsyncMock()

        assert await reviewer._refresh_wiki_context("other/repository") is None
        reviewer._wiki_cache.ensure_fresh.assert_not_awaited()

    def test_toolkits_attached_once(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A completed plane registers the two wiki toolkits only once."""
        reviewer = _wire_reviewer()
        paths = MagicMock(slug="owner-repo", plane_dir=tmp_path / "plane")
        reviewer._wiki_cache = MagicMock()
        reviewer._wiki_cache.paths_for.return_value = paths
        reviewer._attach_toolkit = MagicMock()
        structural = MagicMock()
        wiki = MagicMock()
        monkeypatch.setattr(github_reviewer, "create_wiki_store", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(github_reviewer, "CodeStructuralToolkit", MagicMock(return_value=structural))
        monkeypatch.setattr(github_reviewer, "LLMWikiToolkit", MagicMock(return_value=wiki))

        reviewer._attach_wiki_toolkits(tmp_path / "clone")
        reviewer._attach_wiki_toolkits(tmp_path / "clone")

        assert reviewer._attach_toolkit.call_count == 2
        assert reviewer._wiki_toolkits_attached is True

    def test_llm_wiki_toolkit_confines_sources(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The LLM wiki surface is explicitly confined to the cache plane."""
        reviewer = _wire_reviewer()
        paths = MagicMock(slug="owner-repo", plane_dir=tmp_path / "plane")
        reviewer._wiki_cache = MagicMock()
        reviewer._wiki_cache.paths_for.return_value = paths
        reviewer._attach_toolkit = MagicMock()
        toolkit_factory = MagicMock()
        monkeypatch.setattr(github_reviewer, "create_wiki_store", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(github_reviewer, "CodeStructuralToolkit", MagicMock())
        monkeypatch.setattr(github_reviewer, "LLMWikiToolkit", toolkit_factory)

        reviewer._attach_wiki_toolkits(tmp_path / "clone")

        assert toolkit_factory.call_args.kwargs["confine_sources"] is True


class TestWikiToolSurface:
    """The reviewer's wiki surface is read-only and self-documenting."""

    def test_write_tools_are_withheld(self) -> None:
        """Every mutating LLMWikiToolkit coroutine is excluded, the five reads are not."""
        from parrot.knowledge.wiki.toolkit import LLMWikiToolkit

        excluded = _read_only_excludes(LLMWikiToolkit, _WIKI_READ_TOOLS)

        for write_tool in (
            "create_page",
            "update_page",
            "delete_page",
            "create_wiki",
            "delete_wiki",
            "remember",
            "ingest_source",
            "ingest_obsidian_vault",
            "reingest_source",
            "rebuild_index",
            "export_okf",
        ):
            assert write_tool in excluded, f"{write_tool} is still exposed to the review LLM"
        assert not set(_WIKI_READ_TOOLS) & set(excluded)

    def test_keep_lists_name_real_methods(self) -> None:
        """A typo in a keep-list would silently exclude the tool it means to keep."""
        from parrot.knowledge.wiki.structural.toolkit import CodeStructuralToolkit
        from parrot.knowledge.wiki.toolkit import LLMWikiToolkit

        for toolkit_cls, keep in (
            (LLMWikiToolkit, _WIKI_READ_TOOLS),
            (CodeStructuralToolkit, _STRUCTURAL_READ_TOOLS),
        ):
            for name in keep:
                assert callable(getattr(toolkit_cls, name, None)), f"{toolkit_cls.__name__}.{name} does not exist"

    def test_excludes_are_set_before_registration(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both toolkits carry exclude_tools when they reach _attach_toolkit.

        Tools are generated lazily on the first get_tools(), so the
        exclusions must be in place before registration, not after.
        """
        reviewer = _wire_reviewer()
        paths = MagicMock(slug="owner-repo", plane_dir=tmp_path / "plane")
        reviewer._wiki_cache = MagicMock()
        reviewer._wiki_cache.paths_for.return_value = paths
        reviewer._attach_toolkit = MagicMock()
        structural = MagicMock()
        wiki = MagicMock()
        monkeypatch.setattr(github_reviewer, "create_wiki_store", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(github_reviewer, "CodeStructuralToolkit", MagicMock(return_value=structural))
        monkeypatch.setattr(github_reviewer, "LLMWikiToolkit", MagicMock(return_value=wiki))

        reviewer._attach_wiki_toolkits(tmp_path / "clone")

        registered = [call.args[0] for call in reviewer._attach_toolkit.call_args_list]
        assert registered == [structural, wiki]
        for toolkit in registered:
            assert isinstance(toolkit.exclude_tools, tuple)

    def test_prompt_documents_the_tools_once_attached(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The section lands on the prompt exactly once, carrying the plane name."""
        reviewer = _wire_reviewer()
        reviewer.system_prompt_template = "BASE PROMPT"
        paths = MagicMock(slug="owner-repo", plane_dir=tmp_path / "plane")
        reviewer._wiki_cache = MagicMock()
        reviewer._wiki_cache.paths_for.return_value = paths
        reviewer._attach_toolkit = MagicMock()
        monkeypatch.setattr(github_reviewer, "create_wiki_store", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(github_reviewer, "CodeStructuralToolkit", MagicMock())
        monkeypatch.setattr(github_reviewer, "LLMWikiToolkit", MagicMock())

        reviewer._attach_wiki_toolkits(tmp_path / "clone")
        reviewer._attach_wiki_toolkits(tmp_path / "clone")

        prompt = reviewer.system_prompt_template
        assert prompt.startswith("BASE PROMPT")
        assert prompt.count("## Repository knowledge graph") == 1
        assert 'wiki_name="owner-repo"' in prompt
        for tool in (
            "code_symbol_lookup",
            "code_outline",
            "code_blast_radius",
            "wiki_search_compact",
            "wiki_read_page",
            "wiki_expand",
            "wiki_find_related",
            "wiki_browse_pages",
        ):
            assert tool in prompt

    def test_prompt_names_only_registered_tools(self) -> None:
        """Every ``code_*``/``wiki_*`` name in the prompt is a tool the reviewer keeps."""
        exposed = {f"code_{name}" for name in _STRUCTURAL_READ_TOOLS}
        exposed |= {f"wiki_{name}" for name in _WIKI_READ_TOOLS}
        documented = set(re.findall(r"``((?:code|wiki)_[a-z_]+)\(", _WIKI_TOOLS_PROMPT))

        assert documented, "the prompt documents no tools at all"
        assert documented <= exposed, f"prompt advertises tools the reviewer does not register: {documented - exposed}"

    def test_prompt_survives_template_substitution(self) -> None:
        """A stray ``$`` would be eaten by _define_prompt's safe_substitute."""
        from string import Template

        rendered = _WIKI_TOOLS_PROMPT.format(wiki_name="owner-repo")

        assert Template(rendered).safe_substitute() == rendered

    def test_prompt_extension_never_breaks_the_attach(self) -> None:
        """A bot without a string prompt template logs and carries on."""
        reviewer = _wire_reviewer()
        reviewer.system_prompt_template = None

        reviewer._document_wiki_tools("owner-repo")

        assert reviewer.system_prompt_template is None
        reviewer.logger.warning.assert_called_once()


class TestWikiPromptContext:
    """Coverage for bounded local-wiki prompt enrichment."""

    @staticmethod
    def _ready_reviewer() -> _MinimalReviewer:
        reviewer = _wire_reviewer()
        reviewer._wiki_context_available = True
        reviewer._wiki_store = MagicMock()
        reviewer._wiki_branch = "release/\u03b2"
        reviewer._wiki_built_at = datetime(2026, 10, 15, 12, 30, tzinfo=timezone.utc)
        return reviewer

    async def test_wiki_context_respects_token_budget(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The completed context block never exceeds its configured budget."""
        reviewer = self._ready_reviewer()
        result = {
            "concept_id": "file:src/\u03c0.py",
            "title": "\u03c0 module",
            "summary": "\u00e9" * 500,
            "score": 1.0,
        }
        search = MagicMock()
        search.search = AsyncMock(return_value=[result])
        monkeypatch.setattr(github_reviewer, "WikiCombinedSearch", MagicMock(return_value=search))
        monkeypatch.setattr(conf, "GITHUB_REVIEW_WIKI_CONTEXT_TOKENS", 100)

        context = await reviewer._build_wiki_context(
            {"pr_title": "A\u00f1adir \u03c0 support"},
            "diff --git a/src/\u03c0.py b/src/\u03c0.py\n",
        )

        assert context is not None
        assert github_reviewer.estimate_tokens(context) <= conf.GITHUB_REVIEW_WIKI_CONTEXT_TOKENS

    async def test_wiki_context_carries_base_branch_label(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The header states both the snapshot branch and absence caveat."""
        reviewer = self._ready_reviewer()
        search = MagicMock()
        search.search = AsyncMock(
            return_value=[{"concept_id": "file:src/widget.py", "title": "Widget", "summary": "Widget helpers."}]
        )
        monkeypatch.setattr(github_reviewer, "WikiCombinedSearch", MagicMock(return_value=search))
        monkeypatch.setattr(conf, "GITHUB_REVIEW_WIKI_CONTEXT_TOKENS", 4000)

        context = await reviewer._build_wiki_context(
            {"pr_title": "Add widget"},
            "diff --git a/src/widget.py b/src/widget.py\n",
        )

        assert context is not None
        assert "SNAPSHOT OF BRANCH release/\u03b2" in context
        assert "A symbol introduced by this PR is EXPECTED to be absent" in context

    async def test_review_prompt_unchanged_without_context(self, tmp_path: Path) -> None:
        """Absent enrichment preserves the established question byte-for-byte."""
        reviewer = _wire_reviewer()
        reviewer.max_review_tool_calls = 5
        captured_questions: list[str] = []
        expected = PRReviewResult(jira_key="NAV-1", discrepancies=[], summary="Looks good.", approve=True)

        async def ask(**kwargs: Any) -> MagicMock:
            captured_questions.append(kwargs["question"])
            return _make_fake_response(expected)

        reviewer.ask = ask
        await reviewer._ask_llm_for_review(
            payload={"repository": "owner/repo", "pr_number": 7, "pr_title": "Add widget", "pr_body": "Fixes NAV-1"},
            ticket_key="NAV-1",
            ticket={
                "fields": {
                    "summary": "Widget work",
                    "description": "Implement the widget.",
                    "customfield_10100": "AC: widget works",
                }
            },
            diff_text="diff --git a/src/widget.py b/src/widget.py\n+widget\n",
            diff_truncated=False,
            diff_available=True,
        )

        assert captured_questions == [
            "Review pull request owner/repo#7 against Jira ticket NAV-1.\n\n"
            "PR title: Add widget\n"
            "PR body:\nFixes NAV-1\n\n"
            "=== Jira ticket NAV-1 ===\n"
            "Summary: Widget work\n\n"
            "Description:\nImplement the widget.\n\n"
            "Acceptance Criteria:\nAC: widget works\n\n"
            "=== PR diff (truncated=False) ===\n"
            "diff --git a/src/widget.py b/src/widget.py\n+widget\n\n\n"
            "Compare them and return a PRReviewResult JSON object."
        ]


class TestWikiBoundedWait:
    """Bounded delivery wait, shared refresh task and read lease."""

    async def test_slow_refresh_does_not_block_review(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "GITHUB_REVIEW_WIKI_WAIT", 0.05)
        reviewer = _wire_reviewer()
        release = asyncio.Event()
        reviewer._wiki_cache = MagicMock()

        async def refresh(repository: str) -> None:
            await release.wait()

        reviewer._refresh_wiki_context = refresh
        task = reviewer._start_wiki_refresh("owner/repo")
        assert task is not None
        started = time.monotonic()
        assert await reviewer._await_wiki_refresh(task) is False
        assert time.monotonic() - started < 2
        assert not task.done() and not task.cancelled()
        release.set()
        await task

    async def test_refresh_task_reused_across_deliveries(self) -> None:
        reviewer = _wire_reviewer()
        release = asyncio.Event()
        calls = 0
        reviewer._wiki_cache = MagicMock()

        async def refresh(repository: str) -> None:
            nonlocal calls
            calls += 1
            await release.wait()

        reviewer._refresh_wiki_context = refresh
        first = reviewer._start_wiki_refresh("owner/repo")
        second = reviewer._start_wiki_refresh("Owner/Repo")
        assert first is second
        release.set()
        await first
        assert calls == 1
        assert reviewer._start_wiki_refresh("other/repo") is None

    async def test_warmup_task_is_first_refresh(self) -> None:
        reviewer = _wire_reviewer()
        release = asyncio.Event()
        reviewer._wiki_cache = MagicMock()

        async def refresh(repository: str) -> None:
            await release.wait()

        reviewer._refresh_wiki_context = refresh
        await reviewer._schedule_wiki_warmup()
        assert reviewer._start_wiki_refresh("owner/repo") is reviewer._wiki_warmup_task
        await reviewer._shutdown_wiki_warmup()

    async def test_review_runs_inside_read_lease(self) -> None:
        events: list[str] = []

        @asynccontextmanager
        async def read_lease(repository: str, *, timeout: float = 0.0):
            events.append("enter")
            try:
                yield MagicMock()
            finally:
                events.append("exit")

        reviewer = _wire_reviewer()
        reviewer._wiki_cache = MagicMock()
        reviewer._wiki_cache.read_lease = read_lease
        reviewer._wiki_context_available = True
        reviewer._refresh_wiki_context = AsyncMock(return_value=None)

        async def fake_ticket(key):
            return {"fields": {"summary": "S"}}

        async def fake_diff(repo, pr):
            return ("d", False, True)

        async def fake_ask(*, payload, ticket_key, ticket, diff_text, diff_truncated, diff_available, use_wiki=True):
            events.append(f"ask:{use_wiki}")
            return PRReviewResult(jira_key=ticket_key, discrepancies=[], summary="ok", approve=True)

        reviewer._fetch_ticket = fake_ticket
        reviewer._fetch_diff = fake_diff
        reviewer._ask_llm_for_review = fake_ask
        reviewer.git_toolkit.submit_pr_review = AsyncMock(return_value={"id": 1})
        out = await reviewer.review_pull_request(
            {"repository": "owner/repo", "pr_number": 3, "pr_body": "NAV-3", "pr_title": ""}
        )
        assert out["status"] == "reviewed"
        assert events == ["enter", "ask:True", "exit"]

    async def test_no_lease_means_no_wiki_block(self) -> None:
        @asynccontextmanager
        async def read_lease(repository: str, *, timeout: float = 0.0):
            yield None

        reviewer = _wire_reviewer()
        reviewer._wiki_cache = MagicMock()
        reviewer._wiki_cache.read_lease = read_lease
        reviewer._wiki_context_available = True
        reviewer._wiki_store = MagicMock()
        reviewer._wiki_branch = "main"
        reviewer._wiki_built_at = datetime(2026, 10, 15, tzinfo=timezone.utc)
        async with reviewer._wiki_review_lease() as leased:
            assert leased is False
        assert await reviewer._build_wiki_context({"pr_title": "t"}, "diff --git a/x b/x\n", enabled=False) is None
        reviewer._wiki_context_available = False
        async with reviewer._wiki_review_lease() as leased:
            assert leased is False

    async def test_shutdown_cancels_inflight_refresh(self) -> None:
        reviewer = _wire_reviewer()
        reviewer._wiki_cache = MagicMock()

        async def refresh(repository: str) -> None:
            await asyncio.Event().wait()

        reviewer._refresh_wiki_context = refresh
        task = reviewer._start_wiki_refresh("owner/repo")
        await asyncio.sleep(0)
        await reviewer._shutdown_wiki_warmup()
        assert task.cancelled()
        assert reviewer._wiki_refresh_task is None


class TestExtractTicketKey:
    def test_returns_first_match_from_body(self):
        r = _MinimalReviewer()
        key = r._extract_ticket_key("Implements NAV-9999 with helpers", "")
        assert key == "NAV-9999"

    def test_falls_back_to_title_when_body_empty(self):
        r = _MinimalReviewer()
        assert r._extract_ticket_key("", "[NAV-42] hotfix") == "NAV-42"

    def test_no_match_returns_none(self):
        r = _MinimalReviewer()
        assert r._extract_ticket_key("just a fix", "minor tweak") is None

    def test_does_not_match_other_projects(self):
        r = _MinimalReviewer(jira_project="NAV")
        assert r._extract_ticket_key("see ABC-1", "") is None

    def test_word_boundary_required(self):
        r = _MinimalReviewer()
        # XNAV-1 must NOT match — guards against false positives.
        assert r._extract_ticket_key("backport XNAV-1", "") is None


class TestFormatReviewBody:
    def test_includes_severity_and_link(self):
        r = _MinimalReviewer()
        result = PRReviewResult(
            jira_key="NAV-1",
            discrepancies=[
                Discrepancy(
                    criterion="AC #2: endpoint accepts JSON",
                    issue="Only form-data branch implemented",
                    severity="major",
                ),
                Discrepancy(
                    criterion="AC #3: returns 201",
                    issue="Returns 200",
                    severity="blocker",
                ),
            ],
            summary="Two AC gaps.",
            approve=False,
        )
        body = r._format_review_body({}, "NAV-1", result)
        assert "NAV-1" in body
        assert "[MAJOR]" in body
        assert "[BLOCKER]" in body
        assert "AC #2: endpoint accepts JSON" in body
        assert "Two AC gaps." in body


class TestFormatAlertMessage:
    def test_counts_severities(self):
        r = _MinimalReviewer()
        payload = {
            "repository": "owner/repo",
            "pr_number": 17,
            "pr_title": "Feature",
            "pr_url": "https://github.com/owner/repo/pull/17",
        }
        result = PRReviewResult(
            jira_key="NAV-1",
            discrepancies=[
                Discrepancy(criterion="x", issue="y", severity="blocker"),
                Discrepancy(criterion="x", issue="y", severity="blocker"),
                Discrepancy(criterion="x", issue="y", severity="major"),
                Discrepancy(criterion="x", issue="y", severity="minor"),
            ],
            summary="Stuff",
            approve=False,
        )
        msg = r._format_alert_message(payload, "NAV-1", result)
        assert "blocker=2" in msg
        assert "major=1" in msg
        assert "minor=1" in msg
        assert "NAV-1" in msg
        assert "owner/repo" in msg


class TestParseIso8601:
    def test_parses_zulu(self):
        dt = GitHubReviewer._parse_iso8601("2026-01-01T12:00:00Z")
        assert dt == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def test_parses_offset(self):
        dt = GitHubReviewer._parse_iso8601("2026-01-01T12:00:00+00:00")
        assert dt == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    @pytest.mark.parametrize("value", [None, "", "not-a-date"])
    def test_invalid_returns_none(self, value):
        assert GitHubReviewer._parse_iso8601(value) is None


class TestFlattenAdf:
    def test_plain_string_passthrough(self):
        assert _flatten_adf("hello world") == "hello world"

    def test_none_returns_empty(self):
        assert _flatten_adf(None) == ""

    def test_adf_paragraph(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "AC #1: returns 201"}],
                }
            ],
        }
        assert "AC #1: returns 201" in _flatten_adf(doc)

    def test_adf_bullet_list(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "one"}],
                                }
                            ],
                        },
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "two"}],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
        out = _flatten_adf(doc)
        assert "one" in out and "two" in out

    def test_non_dict_non_list_stringified(self):
        assert _flatten_adf(42) == "42"


class TestClamp:
    def test_returns_value_under_budget(self):
        r = _MinimalReviewer(max_ticket_bytes=100)
        assert r._clamp("short") == "short"

    def test_truncates_marker_appended(self):
        r = _MinimalReviewer(max_ticket_bytes=10)
        out = r._clamp("x" * 50)
        assert out.startswith("x" * 10)
        assert "truncated" in out

    def test_empty_input(self):
        r = _MinimalReviewer()
        assert r._clamp("") == ""
        assert r._clamp(None) == ""


class TestFormatReviewBodyApprovePath:
    def test_approve_renders_satisfied_header_no_findings(self):
        r = _MinimalReviewer()
        result = PRReviewResult(
            jira_key="NAV-7",
            discrepancies=[],
            summary="Everything good.",
            approve=True,
        )
        body = r._format_review_body({}, "NAV-7", result)
        assert "acceptance criteria satisfied" in body
        assert "NAV-7" in body
        assert "Everything good." in body
        assert "### Findings" not in body


class TestFormatAlertMessageEscaping:
    def test_escapes_html_special_chars(self):
        """Real-world PR titles with `<`, `>`, `&` must not break HTML parse."""
        r = _MinimalReviewer()
        payload = {
            "repository": "owner/repo",
            "pr_number": 17,
            "pr_title": "feat: support <X> & </Y>",
            "pr_url": "https://github.com/owner/repo/pull/17?q=a&b=c",
        }
        result = PRReviewResult(
            jira_key="NAV-1",
            discrepancies=[Discrepancy(criterion="c", issue="i", severity="major")],
            summary="A & B happen <here>",
            approve=False,
        )
        msg = r._format_alert_message(payload, "NAV-1", result)
        # Special chars are escaped, raw forms are gone.
        assert "<X>" not in msg
        assert "&lt;X&gt;" in msg
        assert "&amp;" in msg
        # URL query separator must also be escaped (quote=True path).
        assert "q=a&amp;b=c" in msg
        # The wrapping tags we wrote are still present.
        assert msg.startswith("<b>PR review")
        assert "<code>" in msg

    def test_counter_returns_zero_for_missing_severity(self):
        r = _MinimalReviewer()
        result = PRReviewResult(
            jira_key="NAV-1",
            discrepancies=[Discrepancy(criterion="c", issue="i", severity="minor")],
            summary="x",
            approve=False,
        )
        msg = r._format_alert_message({"repository": "o/r"}, "NAV-1", result)
        assert "blocker=0" in msg
        assert "major=0" in msg
        assert "minor=1" in msg


class TestRepoCaseInsensitive:
    async def test_handle_hook_event_matches_lowercased_repo(self):
        r = _wire_reviewer(repository="Owner/Repo")
        captured: List[Dict[str, Any]] = []

        async def fake_review(payload):
            captured.append(payload)
            return {"status": "stub"}

        r.review_pull_request = fake_review  # type: ignore[assignment]

        event = _StubEvent(
            "github.pr_opened",
            {"repository": "owner/repo", "pr_number": 1},
        )
        out = await r.handle_hook_event(event)
        assert out == {"status": "stub"}
        assert captured and captured[0]["pr_number"] == 1

    async def test_handle_hook_event_rejects_other_repo(self):
        r = _wire_reviewer(repository="owner/repo")
        r.review_pull_request = MagicMock()  # type: ignore[assignment]
        event = _StubEvent(
            "github.pr_opened",
            {"repository": "someone/else", "pr_number": 1},
        )
        out = await r.handle_hook_event(event)
        assert out is None
        r.review_pull_request.assert_not_called()

    async def test_handle_hook_event_ignores_unrelated_events(self):
        r = _wire_reviewer()
        r.review_pull_request = MagicMock()  # type: ignore[assignment]
        out = await r.handle_hook_event(_StubEvent("github.pr_closed", {}))
        assert out is None


class TestReviewPullRequestDedup:
    async def test_already_reviewed_short_circuits(self):
        r = _wire_reviewer()
        r._reviewed_shas[("owner/repo", 42)] = "abc123"

        # These shouldn't even be reached:
        r._fetch_ticket = MagicMock()  # type: ignore[assignment]
        r._fetch_diff = MagicMock()  # type: ignore[assignment]

        out = await r.review_pull_request(
            {
                "repository": "owner/repo",
                "pr_number": 42,
                "head_sha": "abc123",
                "pr_body": "Implements NAV-1",
                "pr_title": "",
            }
        )
        assert out["status"] == "already_reviewed"
        assert out["head_sha"] == "abc123"
        r._fetch_ticket.assert_not_called()
        r._fetch_diff.assert_not_called()

    async def test_new_sha_records_after_review(self):
        r = _wire_reviewer()

        async def fake_fetch_ticket(key):
            return {"fields": {"summary": "S", "description": "D"}}

        async def fake_fetch_diff(repo, pr):
            return ("diff text", False, True)

        async def fake_ask(*, payload, ticket_key, ticket, diff_text, diff_truncated, diff_available, use_wiki=True):
            return PRReviewResult(
                jira_key=ticket_key,
                discrepancies=[],
                summary="all good",
                approve=True,
            )

        async def fake_submit(**kwargs):
            return {"id": 1, "state": "APPROVED"}

        r._fetch_ticket = fake_fetch_ticket  # type: ignore[assignment]
        r._fetch_diff = fake_fetch_diff  # type: ignore[assignment]
        r._ask_llm_for_review = fake_ask  # type: ignore[assignment]
        r.git_toolkit.submit_pr_review = fake_submit

        out = await r.review_pull_request(
            {
                "repository": "Owner/Repo",
                "pr_number": 9,
                "head_sha": "deadbeef",
                "pr_body": "Fixes NAV-9",
                "pr_title": "",
            }
        )
        assert out["status"] == "reviewed"
        assert out["approve"] is True
        assert r._reviewed_shas[("owner/repo", 9)] == "deadbeef"

    async def test_tool_call_cap_warning_logged(self):
        """When tool_calls >= max_review_tool_calls, a WARNING is emitted.

        This test verifies the cap-enforcement detection path: even if the
        underlying LLM client does not honour max_iterations, the post-call
        count check catches it and logs a WARNING so operators know the cap was
        hit.

        It also verifies that max_iterations is passed to self.ask() as
        max_review_tool_calls + 1 (per the FEAT-182 spec).
        """
        r = _wire_reviewer()
        r.max_review_tool_calls = 2
        # Bind the real _ask_llm_for_review so we exercise the actual logic.
        r._ask_llm_for_review = GitHubReviewer._ask_llm_for_review.__get__(r, type(r))

        # Fake tool-call objects — each has a 'name' attribute.
        class _FakeTC:
            def __init__(self, name):
                self.name = name

        # Simulate an ask() that returns a response with exactly max_review_tool_calls
        # tool calls (triggering the warning).
        class _FakeResponse:
            tool_calls = [_FakeTC("get_file_content_at_ref"), _FakeTC("search_repo_code")]
            output = PRReviewResult(
                jira_key="NAV-1",
                discrepancies=[],
                summary="looks good",
                approve=True,
            )

        captured_max_iterations: List[int] = []

        async def fake_ask(question, structured_output, max_iterations, **kw):
            captured_max_iterations.append(max_iterations)
            return _FakeResponse()

        r.ask = fake_ask  # type: ignore[assignment]
        r._ac_field_id = "customfield_10100"
        r._fetch_ticket = AsyncMock(return_value={"fields": {"summary": "S", "description": "D"}})
        r._fetch_diff = AsyncMock(return_value=("diff text", False, True))

        out = await r.review_pull_request(
            {
                "repository": "owner/repo",
                "pr_number": 5,
                "head_sha": "cap-sha",
                "pr_body": "Fixes NAV-5",
                "pr_title": "",
            }
        )
        # max_iterations must be max_review_tool_calls + 1 as specified.
        assert captured_max_iterations == [r.max_review_tool_calls + 1]
        # Review completed; warning about cap was logged.
        r.logger.warning.assert_called_once()
        warning_args = r.logger.warning.call_args[0]
        assert "cap" in warning_args[0].lower() or "cap" in str(warning_args).lower()


class TestFetchTicketFields:
    async def test_passes_configured_ac_field(self):
        """Override JIRA_ACCEPTANCE_CRITERIA_FIELD must be reflected in
        the fields= argument sent to Jira."""
        r = _wire_reviewer(ac_field_id="customfield_99999")

        captured: Dict[str, Any] = {}

        async def fake_get(**kwargs):
            captured.update(kwargs)
            return {"status": "ok", "data": {"fields": {}}}

        r.jira_toolkit.jira_get_issue = fake_get

        await r._fetch_ticket("NAV-1")
        assert "customfield_99999" in captured["fields"]
        # Stable field list is sorted, so summary/description/status remain.
        for f in ("summary", "description", "status"):
            assert f in captured["fields"]

    async def test_returns_none_when_envelope_not_ok(self):
        r = _wire_reviewer()

        async def fake_get(**kwargs):
            return {"status": "error", "data": None}

        r.jira_toolkit.jira_get_issue = fake_get
        assert await r._fetch_ticket("NAV-1") is None

    async def test_returns_none_when_toolkit_missing(self):
        r = _wire_reviewer()
        r.jira_toolkit = None
        assert await r._fetch_ticket("NAV-1") is None


class TestNoTicketComment:
    def test_format_includes_project_and_author(self):
        r = _MinimalReviewer(jira_project="NAV")
        body = r._format_no_ticket_comment({"author": "octocat", "pr_title": "x", "pr_body": ""})
        assert "@octocat" in body
        assert "NAV-<number>" in body
        assert "NAV-123" in body
        assert "title or description" in body

    def test_format_handles_missing_author(self):
        r = _MinimalReviewer(jira_project="PARROT")
        body = r._format_no_ticket_comment({"pr_title": "x", "pr_body": ""})
        # No salutation prefix when author is missing.
        assert "@" not in body.split("\n")[2]
        assert "PARROT-<number>" in body

    async def test_review_posts_comment_when_no_ticket(self):
        r = _wire_reviewer()
        captured: Dict[str, Any] = {}

        async def fake_add(**kwargs):
            captured.update(kwargs)
            return {"id": 42, "html_url": "https://github.com/x/y/issues/1#issuecomment-42"}

        r.git_toolkit.add_pr_comment = fake_add

        out = await r.review_pull_request(
            {
                "repository": "owner/repo",
                "pr_number": 17,
                "head_sha": "deadbeef",
                "pr_body": "no jira reference here",
                "pr_title": "drive-by fix",
                "author": "octocat",
            }
        )
        assert out["status"] == "no_ticket"
        assert out["comment"]["id"] == 42
        assert captured["pr_number"] == 17
        assert captured["repository"] == "owner/repo"
        assert "NAV-<number>" in captured["body"]
        assert "@octocat" in captured["body"]
        # PR is now in the dedup set.
        assert ("owner/repo", 17) in r._no_ticket_notified

    async def test_second_delivery_does_not_repost(self):
        r = _wire_reviewer()
        calls = 0

        async def fake_add(**kwargs):
            nonlocal calls
            calls += 1
            return {"id": calls}

        r.git_toolkit.add_pr_comment = fake_add

        payload = {
            "repository": "owner/repo",
            "pr_number": 17,
            "head_sha": "sha-a",
            "pr_body": "no ticket",
            "pr_title": "",
        }
        await r.review_pull_request(payload)
        # Different SHA but same PR — must still skip.
        payload["head_sha"] = "sha-b"
        out2 = await r.review_pull_request(payload)
        assert calls == 1
        # Second response has no `comment` key because we didn't post.
        assert "comment" not in out2
        assert out2["status"] == "no_ticket"

    async def test_skips_silently_when_git_toolkit_missing(self):
        r = _wire_reviewer()
        r.git_toolkit = None

        out = await r.review_pull_request(
            {
                "repository": "owner/repo",
                "pr_number": 1,
                "pr_body": "",
                "pr_title": "no ticket",
            }
        )
        assert out["status"] == "no_ticket"
        assert "comment" not in out
        # Did not mark as notified — a later config fix can still produce
        # the comment on the next delivery.
        assert r._no_ticket_notified == set()

    async def test_does_not_mark_when_post_fails(self):
        r = _wire_reviewer()

        async def fake_add(**kwargs):
            raise RuntimeError("boom")

        r.git_toolkit.add_pr_comment = fake_add

        await r.review_pull_request(
            {
                "repository": "owner/repo",
                "pr_number": 99,
                "pr_body": "",
                "pr_title": "no ticket",
            }
        )
        # Failure must NOT poison the dedup set; the next delivery retries.
        assert r._no_ticket_notified == set()


class TestSetupWebhookRoute:
    """Sync classmethod that wires the aiohttp route + dispatcher.

    We use a real aiohttp.web.Application here because the contract we
    care about (route registration + listener fan-out + idempotency) only
    holds against the real router.
    """

    def test_registers_route_and_dispatcher(self):
        from aiohttp import web

        app = web.Application()
        hook = GitHubReviewer.setup_webhook_route(app, secret="s3cr3t")

        # The hook is stored on the app for post_configure to find.
        assert app[GitHubReviewer.WEBHOOK_APP_KEY] is hook
        # Empty listener list seeded.
        assert app[GitHubReviewer.WEBHOOK_LISTENERS_KEY] == []
        # Route really registered.
        paths = [r.resource.canonical for r in app.router.routes()]
        assert "/api/v1/hooks/github" in paths
        # The hook has a callback set (the dispatcher).
        assert hook._callback is not None

    def test_idempotent(self):
        from aiohttp import web

        app = web.Application()
        h1 = GitHubReviewer.setup_webhook_route(app)
        h2 = GitHubReviewer.setup_webhook_route(app)
        assert h1 is h2
        # Only one route, not duplicated.
        routes = [r for r in app.router.routes() if r.resource.canonical == "/api/v1/hooks/github"]
        assert len(routes) == 1

    def test_custom_url_is_respected(self):
        from aiohttp import web

        app = web.Application()
        GitHubReviewer.setup_webhook_route(app, url="/custom/gh")
        paths = [r.resource.canonical for r in app.router.routes()]
        assert "/custom/gh" in paths
        assert "/api/v1/hooks/github" not in paths

    async def test_dispatcher_fans_out(self):
        from aiohttp import web

        app = web.Application()
        hook = GitHubReviewer.setup_webhook_route(app)
        listeners = app[GitHubReviewer.WEBHOOK_LISTENERS_KEY]

        received: List[str] = []

        async def listener_a(event):
            received.append(f"a:{event.event_type}")

        async def listener_b(event):
            received.append(f"b:{event.event_type}")

        listeners.extend([listener_a, listener_b])

        # Fake event (only event_type is used here).
        event = MagicMock()
        event.event_type = "github.pr_opened"
        await hook._callback(event)

        assert received == ["a:github.pr_opened", "b:github.pr_opened"]

    async def test_dispatcher_isolates_listener_errors(self):
        from aiohttp import web

        app = web.Application()
        hook = GitHubReviewer.setup_webhook_route(app)
        listeners = app[GitHubReviewer.WEBHOOK_LISTENERS_KEY]

        survived: List[str] = []

        async def bad(event):
            raise RuntimeError("boom")

        async def good(event):
            survived.append("ok")

        listeners.extend([bad, good])

        event = MagicMock()
        event.event_type = "github.pr_opened"
        # Must NOT raise.
        await hook._callback(event)
        assert survived == ["ok"]


# ---------------------------------------------------------------------------
# FEAT-180: Shared test fixtures and helpers
# ---------------------------------------------------------------------------

# Sunday 2026-05-10 00:00 UTC (prev) and 2026-05-17 00:00 UTC (current)
W_PREV = datetime(2026, 5, 10, tzinfo=timezone.utc)
W_CURR = datetime(2026, 5, 17, tzinfo=timezone.utc)
NOW = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)  # Monday after W_CURR


def _cs(login, weeks_data):
    """Build a ContributorStats from a list of (week_start, commits, adds, dels)."""
    weeks = [
        ContributorWeek(
            week_start=ws,
            commits=c,
            additions=a,
            deletions=d,
        )
        for ws, c, a, d in weeks_data
    ]
    return ContributorStats(
        login=login,
        total_commits=sum(w.commits for w in weeks),
        weeks=weeks,
    )


def _cf(week_start, additions, deletions):
    """Build a WeeklyCodeFrequency."""
    return WeeklyCodeFrequency(
        week_start=week_start,
        additions=additions,
        deletions=deletions,
    )


def _minimal_reviewer(repository="owner/repo"):
    """Return a _MinimalReviewer-style object with the weekly helpers bound."""
    r = _MinimalReviewer(repository=repository)
    r.logger = MagicMock()
    r._wrapper = None
    r.git_toolkit = None
    r.public_channel_id = None
    r.silent_weeks_threshold = 3
    r.top_n_contributors = 10
    r.use_llm_summary = False
    # Bind the weekly helpers that are available
    r._build_weekly_summary = GitHubReviewer._build_weekly_summary.__get__(r, type(r))
    if hasattr(GitHubReviewer, "_format_weekly_activity_html"):
        r._format_weekly_activity_html = GitHubReviewer._format_weekly_activity_html.__get__(r, type(r))
    return r


def _base_summary(**overrides):
    """Return a minimal WeeklyActivitySummary for renderer tests."""
    defaults = dict(
        repository="owner/repo",
        period_start=W_CURR,
        period_end=W_CURR + timedelta(days=7),
        contributors_active=[
            _ContributorWindowSummary(
                login="alice",
                commits_this_week=12,
                additions=1834,
                deletions=421,
                weeks_silent=0,
            )
        ],
        contributors_silent=[],
        total_commits=12,
        total_additions=1834,
        total_deletions=421,
        prev_total_commits=10,
        prev_total_additions=2000,
        prev_total_deletions=500,
    )
    defaults.update(overrides)
    return WeeklyActivitySummary(**defaults)


# ---------------------------------------------------------------------------
# TASK-1212: TestBuildWeeklySummary
# ---------------------------------------------------------------------------


class TestBuildWeeklySummary:
    """Tests for GitHubReviewer._build_weekly_summary."""

    def test_picks_completed_week_before_now(self):
        """Given NOW on Monday after W_CURR, picks W_CURR as period_start."""
        r = _minimal_reviewer()
        contributors = [_cs("alice", [(W_CURR, 5, 100, 20)])]
        code_freq = [_cf(W_CURR, 100, 20)]
        summary = r._build_weekly_summary(contributors, code_freq, threshold_weeks=3, now=NOW)
        assert summary.period_start == W_CURR
        assert summary.period_end == W_CURR + timedelta(days=7)
        assert summary.total_commits == 5

    def test_flags_silent_at_threshold(self):
        """Contributor with 3 consecutive zero weeks is in contributors_silent."""
        r = _minimal_reviewer()
        # charlie has 0 commits in W_CURR, W_PREV, and W_PREV-7
        weeks_data = [
            (W_CURR, 0, 0, 0),
            (W_PREV, 0, 0, 0),
            (W_PREV - timedelta(days=7), 0, 0, 0),
        ]
        contributors = [_cs("charlie", weeks_data)]
        code_freq = [_cf(W_CURR, 0, 0)]
        summary = r._build_weekly_summary(contributors, code_freq, threshold_weeks=3, now=NOW)
        assert len(summary.contributors_silent) == 1
        assert summary.contributors_silent[0].login == "charlie"
        assert summary.contributors_silent[0].weeks_silent >= 3

    def test_does_not_flag_below_threshold(self):
        """Contributor with only 2 silent weeks is NOT in contributors_silent
        when threshold is 3."""
        r = _minimal_reviewer()
        weeks_data = [
            (W_CURR, 0, 0, 0),
            (W_PREV, 0, 0, 0),
            # 2 silent weeks only
        ]
        contributors = [_cs("bob", weeks_data)]
        code_freq = [_cf(W_CURR, 0, 0)]
        summary = r._build_weekly_summary(contributors, code_freq, threshold_weeks=3, now=NOW)
        assert len(summary.contributors_silent) == 0

    def test_excludes_anonymous_contributors(self):
        """Contributors with login=None are excluded from both lists."""
        r = _minimal_reviewer()
        anon = ContributorStats(
            login=None,
            total_commits=5,
            weeks=[ContributorWeek(week_start=W_CURR, commits=5, additions=100, deletions=10)],
        )
        code_freq = [_cf(W_CURR, 100, 10)]
        summary = r._build_weekly_summary([anon], code_freq, threshold_weeks=3, now=NOW)
        assert summary.contributors_active == []
        assert summary.contributors_silent == []

    def test_top_n_truncates_active_list(self):
        """Active list is capped at top_n; silent list is uncapped."""
        r = _minimal_reviewer()
        contributors = [_cs(f"u{i}", [(W_CURR, 30 - i, 100, 10)]) for i in range(15)]
        code_freq = [_cf(W_CURR, 500, 100)]
        summary = r._build_weekly_summary(contributors, code_freq, threshold_weeks=3, top_n=10, now=NOW)
        assert len(summary.contributors_active) == 10

    def test_delta_from_code_freq(self):
        """prev_total_additions comes from code_freq at W_PREV."""
        r = _minimal_reviewer()
        contributors = [_cs("alice", [(W_CURR, 5, 100, 20), (W_PREV, 7, 200, 50)])]
        code_freq = [
            _cf(W_CURR, 100, 20),
            _cf(W_PREV, 300, 80),
        ]
        summary = r._build_weekly_summary(contributors, code_freq, threshold_weeks=3, now=NOW)
        assert summary.prev_total_additions == 300
        assert summary.prev_total_deletions == 80

    def test_active_sorted_by_commits_desc(self):
        """Active contributors sorted by commits desc."""
        r = _minimal_reviewer()
        contributors = [
            _cs("alice", [(W_CURR, 3, 50, 10)]),
            _cs("bob", [(W_CURR, 10, 200, 50)]),
            _cs("charlie", [(W_CURR, 7, 100, 20)]),
        ]
        code_freq = [_cf(W_CURR, 350, 80)]
        summary = r._build_weekly_summary(contributors, code_freq, threshold_weeks=3, now=NOW)
        logins = [c.login for c in summary.contributors_active]
        assert logins == ["bob", "charlie", "alice"]

    def test_empty_contributors_raises(self):
        """Raises ValueError when both contributors and code_freq are empty."""
        r = _minimal_reviewer()
        with pytest.raises(ValueError, match="Cannot determine reporting window"):
            r._build_weekly_summary([], [], threshold_weeks=3, now=NOW)

    def test_prev_week_slice_marks_code_freq_available(self):
        """The prev-week code_freq entry is what makes the line delta real."""
        r = _minimal_reviewer()
        contributors = [_cs("alice", [(W_CURR, 5, 100, 20), (W_PREV, 3, 50, 10)])]
        summary = r._build_weekly_summary(
            contributors,
            [_cf(W_CURR, 100, 20), _cf(W_PREV, 50, 10)],
            threshold_weeks=3,
            now=NOW,
        )
        assert summary.code_freq_available is True
        assert summary.prev_total_additions == 50

    def test_empty_code_freq_degrades_instead_of_raising(self):
        """With contributors present, an empty code_freq yields a partial summary.

        The reporting window and every current-week figure come from the
        contributor slices; only the previous week's line totals are lost.
        """
        r = _minimal_reviewer()
        contributors = [_cs("alice", [(W_CURR, 5, 100, 20), (W_PREV, 3, 50, 10)])]
        summary = r._build_weekly_summary(contributors, [], threshold_weeks=3, now=NOW)
        assert summary.code_freq_available is False
        assert summary.period_start == W_CURR
        assert summary.total_commits == 5
        assert summary.total_additions == 100
        assert summary.prev_total_commits == 3  # real: summed from contributors
        assert summary.prev_total_additions == 0  # unknown, not measured


# ---------------------------------------------------------------------------
# TASK-1213: TestFormatWeeklyActivityHtml
# ---------------------------------------------------------------------------


class TestFormatWeeklyActivityHtml:
    """Tests for GitHubReviewer._format_weekly_activity_html."""

    def test_escapes_special_chars_in_login(self):
        """Logins with <, >, & are HTML-escaped in the output."""
        r = _minimal_reviewer()
        s = _base_summary(
            contributors_active=[
                _ContributorWindowSummary(
                    login="<bad>&you",
                    commits_this_week=1,
                    additions=0,
                    deletions=0,
                    weeks_silent=0,
                )
            ]
        )
        body = r._format_weekly_activity_html(s)
        assert "&lt;bad&gt;&amp;you" in body
        assert "<bad>" not in body

    def test_skips_empty_silent_section(self):
        """When contributors_silent is empty, 'Silent contributors' is absent."""
        r = _minimal_reviewer()
        s = _base_summary(contributors_silent=[])
        body = r._format_weekly_activity_html(s)
        assert "Silent contributors" not in body

    def test_includes_silent_section_when_present(self):
        """When contributors_silent is non-empty, the section appears."""
        r = _minimal_reviewer()
        s = _base_summary(
            contributors_silent=[
                _ContributorWindowSummary(
                    login="charlie",
                    commits_this_week=0,
                    additions=0,
                    deletions=0,
                    weeks_silent=4,
                )
            ]
        )
        body = r._format_weekly_activity_html(s)
        assert "Silent" in body
        assert "charlie" in body

    def test_pct_handles_zero_prev_commits(self):
        """When prev_total_commits == 0, pct shows 'n/a' or '▲ new'."""
        r = _minimal_reviewer()
        s = _base_summary(prev_total_commits=0, prev_total_additions=0, prev_total_deletions=0)
        body = r._format_weekly_activity_html(s)
        # Should not raise; pct output is either "n/a" or "▲ new"
        assert "n/a" in body or "▲ new" in body or "▲" in body

    def test_partial_summary_marks_the_line_delta_unavailable(self):
        """code_freq_available=False prints 'n/a', never a delta off the zeros."""
        r = _minimal_reviewer()
        s = _base_summary(
            prev_total_additions=0,
            prev_total_deletions=0,
            code_freq_available=False,
        )
        body = r._format_weekly_activity_html(s)
        assert "removed (n/a)" in body
        assert "Partial data" in body
        assert "▲ new" not in body
        # The commits delta survives: it never came from code_frequency.
        assert "▲" in body.split("added /")[0]

    def test_complete_summary_carries_no_partial_notice(self):
        """The notice is absent whenever the prev-week slice was there."""
        r = _minimal_reviewer()
        body = r._format_weekly_activity_html(_base_summary())
        assert "Partial data" not in body

    def test_llm_envelope_carries_the_partial_notice(self):
        """The prose path flags a degraded digest too, not just the template."""
        r = _minimal_reviewer()
        r._wrap_llm_prose_in_html_envelope = GitHubReviewer._wrap_llm_prose_in_html_envelope.__get__(r, type(r))
        partial = r._wrap_llm_prose_in_html_envelope("prose", _base_summary(code_freq_available=False))
        complete = r._wrap_llm_prose_in_html_envelope("prose", _base_summary())
        assert "Partial data" in partial
        assert "Partial data" not in complete

    def test_pct_positive_delta(self):
        """A positive delta shows an upward arrow."""
        r = _minimal_reviewer()
        s = _base_summary(
            total_commits=20,
            prev_total_commits=10,
        )
        body = r._format_weekly_activity_html(s)
        assert "▲" in body

    def test_pct_negative_delta(self):
        """A negative delta shows a downward arrow."""
        r = _minimal_reviewer()
        s = _base_summary(
            total_commits=5,
            prev_total_commits=20,
        )
        body = r._format_weekly_activity_html(s)
        assert "▼" in body

    def test_message_length_under_4096(self):
        """Output stays under Telegram's 4096-char limit with default top_n=10."""
        r = _minimal_reviewer()
        s = _base_summary(
            contributors_active=[
                _ContributorWindowSummary(
                    login=f"user{i}",
                    commits_this_week=10 - i,
                    additions=100,
                    deletions=50,
                    weeks_silent=0,
                )
                for i in range(10)
            ],
            contributors_silent=[
                _ContributorWindowSummary(
                    login=f"silent{i}",
                    commits_this_week=0,
                    additions=0,
                    deletions=0,
                    weeks_silent=3,
                )
                for i in range(5)
            ],
        )
        body = r._format_weekly_activity_html(s)
        assert len(body) < 4096

    def test_escapes_repository_name(self):
        """Repository name is also HTML-escaped."""
        r = _minimal_reviewer(repository="owner/<repo>")
        s = _base_summary(repository="owner/<repo>")
        body = r._format_weekly_activity_html(s)
        assert "&lt;repo&gt;" in body
        assert "<repo>" not in body


# ---------------------------------------------------------------------------
# TASK-1214: TestLLMSummarizeWeekly
# ---------------------------------------------------------------------------


class TestLLMSummarizeWeekly:
    """Tests for GitHubReviewer._llm_summarize_weekly."""

    async def test_success_returns_llm_string(self):
        """When ask() succeeds, returns the LLM output string."""
        r = _minimal_reviewer()
        r._llm_summarize_weekly = GitHubReviewer._llm_summarize_weekly.__get__(r, type(r))

        async def fake_ask(question, **kwargs):
            result = MagicMock()
            result.output = "Alice led the team with 12 commits this week."
            return result

        r.ask = fake_ask
        summary = _base_summary()
        out = await r._llm_summarize_weekly(summary)
        assert "Alice" in out

    async def test_raises_wrapped_error_on_failure(self):
        """When ask() raises, re-raises as WeeklyLLMSummarizationError."""
        r = _minimal_reviewer()
        r._llm_summarize_weekly = GitHubReviewer._llm_summarize_weekly.__get__(r, type(r))

        async def fake_ask(question, **kwargs):
            raise RuntimeError("LLM is down")

        r.ask = fake_ask
        summary = _base_summary()
        with pytest.raises(WeeklyLLMSummarizationError, match="LLM is down"):
            await r._llm_summarize_weekly(summary)

    async def test_coerces_non_string_output(self):
        """A non-string response is coerced to str."""
        r = _minimal_reviewer()
        r._llm_summarize_weekly = GitHubReviewer._llm_summarize_weekly.__get__(r, type(r))

        async def fake_ask(question, **kwargs):
            # Return something without .output attribute
            return {"some": "dict"}

        r.ask = fake_ask
        summary = _base_summary()
        out = await r._llm_summarize_weekly(summary)
        assert isinstance(out, str)

    async def test_prompt_contains_json_summary(self):
        """The prompt sent to ask() contains the JSON-serialized summary."""
        r = _minimal_reviewer()
        r._llm_summarize_weekly = GitHubReviewer._llm_summarize_weekly.__get__(r, type(r))

        captured_question = []

        async def fake_ask(question, **kwargs):
            captured_question.append(question)
            result = MagicMock()
            result.output = "Summary text"
            return result

        r.ask = fake_ask
        summary = _base_summary()
        await r._llm_summarize_weekly(summary)
        assert captured_question
        assert "alice" in captured_question[0].lower() or "owner/repo" in captured_question[0]


# ---------------------------------------------------------------------------
# TASK-1215: TestReportWeeklyActivity
# ---------------------------------------------------------------------------


class TestReportWeeklyActivity:
    """Tests for GitHubReviewer.report_weekly_activity."""

    def _build_reviewer(self, **overrides):
        """Build a reviewer stub for orchestrator tests."""
        r = _minimal_reviewer()
        r.git_toolkit = MagicMock()
        r.public_channel_id = "@test_channel"
        r.silent_weeks_threshold = 3
        r.top_n_contributors = 10
        r.use_llm_summary = False
        # Wire report_weekly_activity through the decorator
        r.report_weekly_activity = GitHubReviewer.report_weekly_activity.__get__(r, type(r))
        r._build_weekly_summary = GitHubReviewer._build_weekly_summary.__get__(r, type(r))
        r._format_weekly_activity_html = GitHubReviewer._format_weekly_activity_html.__get__(r, type(r))
        r._llm_summarize_weekly = GitHubReviewer._llm_summarize_weekly.__get__(r, type(r))
        r._wrap_llm_prose_in_html_envelope = GitHubReviewer._wrap_llm_prose_in_html_envelope.__get__(r, type(r))
        r._get_telegram_bot = GitHubReviewer._get_telegram_bot.__get__(r, type(r))

        # Stub toolkit calls with minimal data
        async def fake_get_contributor_stats(**kwargs):
            return [_cs("alice", [(W_CURR, 5, 100, 20), (W_PREV, 3, 50, 10)])]

        async def fake_get_code_frequency(**kwargs):
            return [_cf(W_CURR, 100, 20), _cf(W_PREV, 50, 10)]

        r.git_toolkit.get_contributor_stats = fake_get_contributor_stats
        r.git_toolkit.get_code_frequency = fake_get_code_frequency

        # Bot that records sends
        sent_messages = []

        async def fake_send(**kwargs):
            sent_messages.append(kwargs)

        fake_bot = MagicMock()
        fake_bot.send_message = AsyncMock(side_effect=fake_send)
        r._wrapper = MagicMock(bot=fake_bot)
        r._sent_messages = sent_messages

        for key, val in overrides.items():
            setattr(r, key, val)
        return r

    async def test_no_toolkit_returns_error(self):
        """When git_toolkit is None, returns error dict without raising."""
        r = _minimal_reviewer()
        r.git_toolkit = None
        r.report_weekly_activity = GitHubReviewer.report_weekly_activity.__get__(r, type(r))
        out = await r.report_weekly_activity()
        assert out["status"] == "error"
        assert "git_toolkit" in out["reason"]

    async def test_weekly_report_goes_to_the_management_chat(self):
        """The weekly digest is a management report."""
        r = self._build_reviewer(management_chat_id="-1009998877")

        await r.report_weekly_activity()

        assert r._sent_messages
        assert r._sent_messages[-1]["chat_id"] == "-1009998877"

    async def test_templated_success_path(self):
        """Happy path with templated rendering returns documented keys."""
        r = self._build_reviewer()
        out = await r.report_weekly_activity()
        assert out["status"] == "ok"
        assert out["repository"] == "owner/repo"
        assert "period_start" in out
        assert "period_end" in out
        assert "active" in out
        assert "silent" in out
        assert out["rendered_via"] == "templated"
        assert out["telegram_sent"] == 1

    async def test_no_telegram_wrapper_returns_zero_sent(self):
        """When _wrapper is None, returns telegram_sent=0 without raising."""
        r = self._build_reviewer()
        r._wrapper = None
        out = await r.report_weekly_activity()
        assert out["status"] == "ok"
        assert out["telegram_sent"] == 0

    async def test_stats_fetch_failure_returns_error(self):
        """When get_contributor_stats raises, returns status=error."""
        r = _minimal_reviewer()
        r.git_toolkit = MagicMock()
        r.report_weekly_activity = GitHubReviewer.report_weekly_activity.__get__(r, type(r))
        r._build_weekly_summary = GitHubReviewer._build_weekly_summary.__get__(r, type(r))
        r._format_weekly_activity_html = GitHubReviewer._format_weekly_activity_html.__get__(r, type(r))
        r._llm_summarize_weekly = GitHubReviewer._llm_summarize_weekly.__get__(r, type(r))
        r._wrap_llm_prose_in_html_envelope = GitHubReviewer._wrap_llm_prose_in_html_envelope.__get__(r, type(r))
        r._get_telegram_bot = GitHubReviewer._get_telegram_bot.__get__(r, type(r))
        r.public_channel_id = "@channel"
        r.silent_weeks_threshold = 3
        r.top_n_contributors = 10
        r.use_llm_summary = False
        r._wrapper = None

        async def fail(**kwargs):
            raise RuntimeError("stats unavailable")

        r.git_toolkit.get_contributor_stats = fail
        r.git_toolkit.get_code_frequency = fail
        out = await r.report_weekly_activity()
        assert out["status"] == "error"
        assert "stats unavailable" in out["reason"]

    async def test_llm_failure_falls_back_to_templated(self):
        """When LLM summarization fails, falls back to templated rendering."""
        r = self._build_reviewer(use_llm_summary=True)

        async def llm_boom(summary):
            raise WeeklyLLMSummarizationError("LLM exploded")

        r._llm_summarize_weekly = llm_boom
        out = await r.report_weekly_activity()
        assert out["status"] == "ok"
        assert out["rendered_via"] == "templated"
        assert out["telegram_sent"] == 1

    async def test_telegram_failure_does_not_raise(self):
        """When Telegram bot.send_message raises, returns telegram_sent=0."""
        r = self._build_reviewer()

        async def fail_send(**kwargs):
            raise RuntimeError("telegram 500")

        r._wrapper.bot.send_message = fail_send
        out = await r.report_weekly_activity()
        assert out["status"] == "ok"
        assert out["telegram_sent"] == 0


# ---------------------------------------------------------------------------
# FEAT-182 TASK-1222: Tool-calling loop tests
# ---------------------------------------------------------------------------


def _wire_reviewer_with_tool_cap(max_tool_calls: int = 5, **overrides: Any) -> Any:
    """Build a reviewer stub with max_review_tool_calls set, for tool-loop tests."""
    r = _wire_reviewer(**overrides)
    r.max_review_tool_calls = max_tool_calls
    # Bind _ask_llm_for_review so we can call it directly.
    r._ask_llm_for_review = GitHubReviewer._ask_llm_for_review.__get__(r, type(r))
    return r


def _make_fake_response(
    result: PRReviewResult,
    tool_calls: Optional[List[Any]] = None,
) -> MagicMock:
    """Build a mock agent response object as returned by self.ask()."""
    response = MagicMock()
    response.output = result
    response.tool_calls = tool_calls or []
    return response


class TestReviewToolCallingLoop:
    """Unit tests for the FEAT-182 tool-calling loop in _ask_llm_for_review."""

    _FIXTURE_PAYLOAD: Dict[str, Any] = {
        "repository": "owner/repo",
        "pr_number": 42,
        "pr_title": "feat: add logging",
        "pr_body": "Fixes NAV-100",
        "pr_url": "https://github.com/owner/repo/pull/42",
        "head_sha": "abc123",
    }

    _TICKET: Dict[str, Any] = {
        "fields": {
            "summary": "Add logging",
            "description": "Log all requests.",
            "status": {"name": "In Progress"},
            "customfield_10100": "AC #1: logging added",
        }
    }

    async def test_review_no_tool_calls_unchanged_behavior(self):
        """When the LLM emits PRReviewResult with no tool calls, the review
        output is identical to the structured-output path (no-regression)."""
        r = _wire_reviewer_with_tool_cap(max_tool_calls=5)

        expected = PRReviewResult(
            jira_key="NAV-100",
            discrepancies=[],
            summary="All criteria met.",
            approve=True,
        )
        fake_response = _make_fake_response(expected, tool_calls=[])

        async def fake_ask(**kwargs):
            return fake_response

        r.ask = fake_ask

        result = await r._ask_llm_for_review(
            payload=self._FIXTURE_PAYLOAD,
            ticket_key="NAV-100",
            ticket=self._TICKET,
            diff_text="diff --git a/logging.py ...",
            diff_truncated=False,
            diff_available=True,
        )

        assert isinstance(result, PRReviewResult)
        assert result.approve is True
        assert result.jira_key == "NAV-100"
        assert result.summary == "All criteria met."
        assert result.discrepancies == []
        # No warning should have been emitted (0 tool calls < cap of 5).
        r.logger.warning.assert_not_called()

    async def test_review_with_tool_calls_within_cap(self):
        """When LLM makes 2 tool calls (below cap of 5), result is returned
        correctly and no warning is emitted."""
        r = _wire_reviewer_with_tool_cap(max_tool_calls=5)

        # Simulate 2 tool calls in the response.
        tc1 = MagicMock()
        tc1.name = "get_file_content_at_ref"
        tc2 = MagicMock()
        tc2.name = "search_repo_code"

        expected = PRReviewResult(
            jira_key="NAV-100",
            discrepancies=[
                Discrepancy(
                    criterion="AC #1: logging added",
                    issue="Logger not imported in new module",
                    severity="major",
                )
            ],
            summary="One AC gap found.",
            approve=False,
        )
        fake_response = _make_fake_response(expected, tool_calls=[tc1, tc2])

        async def fake_ask(**kwargs):
            return fake_response

        r.ask = fake_ask

        result = await r._ask_llm_for_review(
            payload=self._FIXTURE_PAYLOAD,
            ticket_key="NAV-100",
            ticket=self._TICKET,
            diff_text="diff --git a/logging.py ...",
            diff_truncated=False,
            diff_available=True,
        )

        assert isinstance(result, PRReviewResult)
        assert result.approve is False
        assert len(result.discrepancies) == 1
        # 2 calls < cap of 5 — no warning.
        r.logger.warning.assert_not_called()

    async def test_review_cap_hit_logs_warning(self):
        """When the LLM exhausts the tool-call budget (count >= cap), a WARNING
        is logged containing pr_number, count=, and tools=."""
        r = _wire_reviewer_with_tool_cap(max_tool_calls=5)

        # Simulate exactly 5 tool calls (== cap, triggers warning).
        tool_calls = []
        for name in [
            "get_file_content_at_ref",
            "compare_pr_versions",
            "search_repo_code",
            "get_file_content_at_ref",
            "compare_pr_versions",
        ]:
            tc = MagicMock()
            tc.name = name
            tool_calls.append(tc)

        expected = PRReviewResult(
            jira_key="NAV-100",
            discrepancies=[],
            summary="Budget exhausted; partial review.",
            approve=False,
        )
        fake_response = _make_fake_response(expected, tool_calls=tool_calls)

        async def fake_ask(**kwargs):
            return fake_response

        r.ask = fake_ask

        await r._ask_llm_for_review(
            payload=self._FIXTURE_PAYLOAD,
            ticket_key="NAV-100",
            ticket=self._TICKET,
            diff_text="diff --git a/logging.py ...",
            diff_truncated=False,
            diff_available=True,
        )

        # WARNING must have been called at least once.
        assert r.logger.warning.called, "expected logger.warning to be called"
        call_args = r.logger.warning.call_args
        # The format string and args are the first positional argument.
        fmt = call_args[0][0]
        args = call_args[0][1:]
        message = fmt % args
        assert "hit tool-call cap" in message
        assert "42" in message  # pr_number
        assert "count=5" in message  # count
        # tool names must appear somewhere in the message
        assert "get_file_content_at_ref" in message or "compare_pr_versions" in message

    def test_attach_toolkit_registers_new_tools(self):
        """_attach_toolkit(git_toolkit, 'Git') extends self.tools with the
        3 new tool names: get_file_content_at_ref, compare_pr_versions,
        search_repo_code."""
        r = _wire_reviewer()
        r.tools = []

        # Build three fake AbstractTool objects with the expected names.
        new_tool_names = [
            "get_file_content_at_ref",
            "compare_pr_versions",
            "search_repo_code",
        ]
        fake_tools = []
        for name in new_tool_names:
            t = MagicMock()
            t.name = name
            fake_tools.append(t)

        # Mock tool_manager.register_toolkit to return the fake tools.
        mock_tool_manager = MagicMock()
        mock_tool_manager.register_toolkit.return_value = fake_tools
        r.tool_manager = mock_tool_manager

        # Mock git_toolkit instance.
        mock_git_toolkit = MagicMock()

        # Call the real _attach_toolkit.
        GitHubReviewer._attach_toolkit(r, mock_git_toolkit, "Git")

        # Verify tools were extended.
        registered_names = [getattr(t, "name", None) for t in r.tools]
        for expected_name in new_tool_names:
            assert (
                expected_name in registered_names
            ), f"Expected tool '{expected_name}' in r.tools, got: {registered_names}"


# ---------------------------------------------------------------------------
# FEAT-182 TASK-1223: Integration tests
# ---------------------------------------------------------------------------


class TestIntegrationToolAssistedReview:
    """Integration tests for the FEAT-182 tool-assisted review flow.

    These tests exercise review_pull_request end-to-end with fully mocked
    dependencies (no network calls) to verify the tool-calling path works
    correctly from the top-level entry point.
    """

    _FIXTURE_PAYLOAD: Dict[str, Any] = {
        "repository": "owner/repo",
        "pr_number": 99,
        "pr_title": "feat: refactor login handler",
        "pr_body": "Implements NAV-200",
        "pr_url": "https://github.com/owner/repo/pull/99",
        "head_sha": "feedcafe",
    }

    _FIXTURE_TICKET: Dict[str, Any] = {
        "fields": {
            "summary": "Refactor login handler",
            "description": "The login handler must validate email format.",
            "status": {"name": "In Progress"},
            "customfield_10100": ("AC #1: validate email format\n" "AC #2: return 400 on invalid email"),
        }
    }

    def _build_integration_reviewer(self, max_tool_calls: int = 3) -> Any:
        """Build a reviewer stub wired for integration-style tests."""
        r = _wire_reviewer_with_tool_cap(max_tool_calls=max_tool_calls)
        r._reviewed_shas = {}
        r._no_ticket_notified = set()
        # Bind review_pull_request and _ask_llm_for_review onto stub.
        r.review_pull_request = GitHubReviewer.review_pull_request.__get__(r, type(r))
        r._ask_llm_for_review = GitHubReviewer._ask_llm_for_review.__get__(r, type(r))
        r._extract_ticket_key = GitHubReviewer._extract_ticket_key.__get__(r, type(r))
        r._clamp = GitHubReviewer._clamp.__get__(r, type(r))
        r._format_review_body = GitHubReviewer._format_review_body.__get__(r, type(r))
        r._notify_telegram_alert = GitHubReviewer._notify_telegram_alert.__get__(r, type(r))
        r._notify_missing_ticket = GitHubReviewer._notify_missing_ticket.__get__(r, type(r))
        r._get_telegram_bot = GitHubReviewer._get_telegram_bot.__get__(r, type(r))
        r._fetch_ticket = GitHubReviewer._fetch_ticket.__get__(r, type(r))
        r._fetch_diff = GitHubReviewer._fetch_diff.__get__(r, type(r))
        r._ac_field_id = "customfield_10100"
        r.jira_project = "NAV"
        r.max_diff_bytes = 50_000
        return r

    async def test_full_review_with_real_diff_fixture(self):
        """End-to-end review: LLM makes one tool call then produces a
        PRReviewResult discrepancy. The outcome dict must reflect this."""
        r = self._build_integration_reviewer(max_tool_calls=3)

        # Mock Jira fetch.
        async def fake_fetch_ticket(key):
            return self._FIXTURE_TICKET

        # Mock diff fetch.
        async def fake_fetch_diff(repo, pr_number):
            return (
                "diff --git a/login.py b/login.py\n" "+def login(email):\n" "+    return 200\n",
                False,
                True,
            )

        # Mock one tool call in the response (within cap of 3).
        tool_call = MagicMock()
        tool_call.name = "get_file_content_at_ref"

        expected_result = PRReviewResult(
            jira_key="NAV-200",
            discrepancies=[
                Discrepancy(
                    criterion="AC #2: return 400 on invalid email",
                    issue="login() always returns 200; no email validation present",
                    severity="blocker",
                )
            ],
            summary="The login handler does not validate email format.",
            approve=False,
        )
        fake_response = _make_fake_response(expected_result, tool_calls=[tool_call])

        async def fake_ask(**kwargs):
            return fake_response

        # Mock git_toolkit.submit_pr_review.
        async def fake_submit(**kwargs):
            return {"id": 77, "state": "REQUEST_CHANGES"}

        r._fetch_ticket = fake_fetch_ticket
        r._fetch_diff = fake_fetch_diff
        r.ask = fake_ask
        r.git_toolkit.submit_pr_review = fake_submit

        outcome = await r.review_pull_request(self._FIXTURE_PAYLOAD)

        assert outcome["status"] == "reviewed"
        assert outcome["approve"] is False
        assert len(outcome["discrepancies"]) == 1
        assert outcome["discrepancies"][0]["severity"] == "blocker"
        assert "NAV-200" in outcome["jira_key"]

    async def test_full_review_falls_back_when_tools_disabled(self):
        """max_review_tool_calls=0 causes self.ask() to be called with
        max_iterations=1 (= 0 + 1), effectively disabling the tool loop."""
        r = self._build_integration_reviewer(max_tool_calls=0)

        # Record kwargs passed to ask().
        ask_kwargs: Dict[str, Any] = {}

        async def fake_fetch_ticket(key):
            return self._FIXTURE_TICKET

        async def fake_fetch_diff(repo, pr_number):
            return ("diff ...", False, True)

        async def fake_ask(**kwargs):
            ask_kwargs.update(kwargs)
            result = PRReviewResult(
                jira_key="NAV-200",
                discrepancies=[],
                summary="All criteria met.",
                approve=True,
            )
            return _make_fake_response(result, tool_calls=[])

        async def fake_submit(**kwargs):
            return {"id": 1, "state": "APPROVED"}

        r._fetch_ticket = fake_fetch_ticket
        r._fetch_diff = fake_fetch_diff
        r.ask = fake_ask
        r.git_toolkit.submit_pr_review = fake_submit

        outcome = await r.review_pull_request(self._FIXTURE_PAYLOAD)

        assert outcome["status"] == "reviewed"
        # max_iterations must have been passed as 0+1=1, indicating one-shot.
        assert ask_kwargs.get("max_iterations") == 1
        # No warning should have been logged (count=0 < max_review_tool_calls=0
        # comparison: 0 >= 0 is True but max_review_tool_calls == 0 so the
        # guard `and self.max_review_tool_calls > 0` prevents the log).
        r.logger.warning.assert_not_called()


class TestPublicChannelSendFailureLogging:
    """A failed public-channel send must name the chat it was aimed at.

    Regression for issue:7d1aeb70b417: the three ``public_channel_id`` send
    paths logged the exception without the destination, so four identical
    "chat not found" lines gave the operator no way to tell which of the two
    configured destinations (``alert_chat_ids`` vs ``public_channel_id``) was
    broken, nor which id was attempted.
    """

    @staticmethod
    def _stale_reviewer(chat_id: str = "4663754211") -> _MinimalReviewer:
        """A reviewer with one stale PR and a Telegram bot that refuses sends."""
        reviewer = _wire_reviewer()
        reviewer.stale_after_hours = 24
        reviewer.public_channel_id = chat_id
        old = datetime.now(timezone.utc) - timedelta(hours=72)
        reviewer.git_toolkit.list_pull_requests = AsyncMock(
            return_value=[
                {
                    "number": 7,
                    "title": "feat: something",
                    "html_url": "https://github.com/owner/repo/pull/7",
                    "user": {"login": "someone"},
                    "created_at": old.isoformat().replace("+00:00", "Z"),
                }
            ]
        )
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=RuntimeError("Telegram server says - Bad Request: chat not found"))
        reviewer._wrapper = MagicMock(bot=bot)
        return reviewer

    async def test_stale_alert_failure_names_the_chat_id(self) -> None:
        """The warning carries public_channel_id, not just the exception."""
        reviewer = self._stale_reviewer()

        await reviewer.report_stale_pull_requests()

        reviewer.logger.warning.assert_called_once()
        fmt, *args = reviewer.logger.warning.call_args.args
        assert "to chat %s" in fmt
        assert args[0] == "4663754211"
        assert "chat not found" in str(args[1])

    async def test_stale_alert_failure_does_not_count_as_announced(self) -> None:
        """A refused send leaves the stale PR unannounced in the summary."""
        reviewer = self._stale_reviewer()

        result = await reviewer.report_stale_pull_requests()

        assert result["stale_count"] == 1
        assert len(result["stale"]) == 1
        assert result["announced"] == 0


class TestStalePRDigest:
    """All stale PRs go out as ONE Telegram message, not one per PR."""

    @staticmethod
    def _reviewer(count: int, *, title: str = "feat: something") -> _MinimalReviewer:
        reviewer = _wire_reviewer()
        reviewer.stale_after_hours = 24
        reviewer.public_channel_id = "4663754211"
        old = datetime.now(timezone.utc) - timedelta(hours=72)
        reviewer.git_toolkit.list_pull_requests = AsyncMock(
            return_value=[
                {
                    "number": n,
                    "title": f"{title} #{n}",
                    "html_url": f"https://github.com/owner/repo/pull/{n}",
                    "user": {"login": f"dev{n}"},
                    "created_at": old.isoformat().replace("+00:00", "Z"),
                }
                for n in range(1, count + 1)
            ]
        )
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=None)
        reviewer._wrapper = MagicMock(bot=bot)
        return reviewer

    async def test_many_stale_prs_send_one_message(self) -> None:
        reviewer = self._reviewer(3)

        result = await reviewer.report_stale_pull_requests()

        bot = reviewer._wrapper.bot
        bot.send_message.assert_awaited_once()
        text = bot.send_message.await_args.kwargs["text"]
        for n in (1, 2, 3):
            assert f"/pull/{n}" in text
            assert f"dev{n}" in text
        assert result["stale_count"] == 3
        assert result["announced"] == 3
        assert result["messages_sent"] == 1

    async def test_stale_digest_stays_on_the_public_channel(self) -> None:
        """The stale-PR nag is not a management report: public channel."""
        reviewer = self._reviewer(2)
        reviewer.management_chat_id = "-1009998877"

        await reviewer.report_stale_pull_requests()

        kwargs = reviewer._wrapper.bot.send_message.await_args.kwargs
        assert kwargs["chat_id"] == "4663754211"

    async def test_digest_escapes_user_data(self) -> None:
        reviewer = self._reviewer(1, title="feat: X_y <z> & more")

        await reviewer.report_stale_pull_requests()

        text = reviewer._wrapper.bot.send_message.await_args.kwargs["text"]
        assert "&lt;z&gt; &amp; more" in text
        assert "<z>" not in text

    def test_digest_splits_when_over_the_telegram_limit(self) -> None:
        reviewer = self._reviewer(1)
        stale = [
            {
                "number": n,
                "title": "x" * 150,
                "html_url": f"https://github.com/owner/repo/pull/{n}",
                "user": {"login": f"dev{n}"},
                "age_hours": 72.0,
            }
            for n in range(1, 61)
        ]

        messages = reviewer._format_stale_prs_digest(stale)

        assert len(messages) > 1
        assert sum(covered for _, covered in messages) == 60
        for text, _ in messages:
            assert len(text) <= GitHubReviewer._TELEGRAM_MAX_MESSAGE
            assert "part " in text

    async def test_failed_digest_announces_nothing(self) -> None:
        """One refused send leaves every PR in it unannounced."""
        reviewer = self._reviewer(3)
        reviewer._wrapper.bot.send_message = AsyncMock(side_effect=RuntimeError("chat not found"))

        result = await reviewer.report_stale_pull_requests()

        assert result["announced"] == 0
        assert result["messages_sent"] == 0
        reviewer.logger.warning.assert_called_once()


class TestTodayPRReport:
    """``today_pr()`` digests the last 24h into ONE message, or says nothing."""

    @staticmethod
    def _reviewer(pulls: List[Dict[str, Any]]) -> _MinimalReviewer:
        reviewer = _wire_reviewer()
        reviewer.stale_after_hours = 24
        reviewer.public_channel_id = "4663754211"
        reviewer.git_toolkit.list_pull_requests = AsyncMock(return_value=pulls)
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=None)
        reviewer._wrapper = MagicMock(bot=bot)
        return reviewer

    @staticmethod
    def _pr(number: int, *, hours_ago: float, **extra: Any) -> Dict[str, Any]:
        created = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        pr = {
            "number": number,
            "title": f"feat: change {number}",
            "html_url": f"https://github.com/owner/repo/pull/{number}",
            "user": {"login": f"dev{number}"},
            "created_at": created.isoformat().replace("+00:00", "Z"),
            "state": "open",
        }
        pr.update(extra)
        return pr

    async def test_todays_prs_go_out_as_one_message(self) -> None:
        reviewer = self._reviewer(
            [
                self._pr(11, hours_ago=1.0),
                self._pr(12, hours_ago=8.5),
                self._pr(13, hours_ago=23.0),
            ]
        )

        result = await reviewer.today_pr()

        bot = reviewer._wrapper.bot
        bot.send_message.assert_awaited_once()
        text = bot.send_message.await_args.kwargs["text"]
        assert text.startswith("<b>Review Today's Pull Requests</b> on <code>owner/repo</code>")
        assert "3 open PRs opened in the last 24h" in text
        for n in (11, 12, 13):
            assert f"/pull/{n}" in text
            assert f"dev{n}" in text
        assert result["today_count"] == 3
        assert result["announced"] == 3
        assert result["messages_sent"] == 1
        assert result["window_hours"] == 24

    async def test_prs_older_than_the_window_are_excluded(self) -> None:
        reviewer = self._reviewer([self._pr(11, hours_ago=2.0), self._pr(9, hours_ago=48.0)])

        result = await reviewer.today_pr()

        text = reviewer._wrapper.bot.send_message.await_args.kwargs["text"]
        assert "/pull/11" in text
        assert "/pull/9" not in text
        assert result["today_count"] == 1
        assert "1 open PR opened in the last 24h" in text

    async def test_closed_and_merged_prs_are_excluded(self) -> None:
        """Only open PRs are reported — the listing asks for state='open'."""
        reviewer = self._reviewer(
            [
                self._pr(11, hours_ago=3.0, state="closed", merged_at="2026-10-21T10:00:00Z"),
                self._pr(12, hours_ago=4.0, state="closed"),
                self._pr(13, hours_ago=5.0),
            ]
        )

        result = await reviewer.today_pr()

        assert reviewer.git_toolkit.list_pull_requests.await_args.kwargs["state"] == "open"
        text = reviewer._wrapper.bot.send_message.await_args.kwargs["text"]
        assert "/pull/11" not in text
        assert "/pull/12" not in text
        assert "/pull/13" in text
        assert result["today_count"] == 1
        assert [pr["state"] for pr in result["today"]] == ["open"]

    async def test_only_closed_prs_in_the_window_terminate_silently(self) -> None:
        """A day whose PRs were all merged leaves nothing to review."""
        reviewer = self._reviewer(
            [
                self._pr(11, hours_ago=2.0, state="closed", merged_at="2026-10-21T10:00:00Z"),
                self._pr(12, hours_ago=3.0, state="closed"),
            ]
        )

        result = await reviewer.today_pr()

        reviewer._wrapper.bot.send_message.assert_not_awaited()
        assert result["today_count"] == 0
        assert result["today"] == []

    async def test_no_recent_pr_terminates_silently(self) -> None:
        reviewer = self._reviewer([self._pr(9, hours_ago=72.0)])

        result = await reviewer.today_pr()

        reviewer._wrapper.bot.send_message.assert_not_awaited()
        assert result["status"] == "ok"
        assert result["today_count"] == 0
        assert result["today"] == []
        assert result["messages_sent"] == 0
        reviewer.logger.warning.assert_not_called()

    async def test_empty_repository_terminates_silently(self) -> None:
        reviewer = self._reviewer([])

        result = await reviewer.today_pr()

        reviewer._wrapper.bot.send_message.assert_not_awaited()
        assert result["today_count"] == 0
        reviewer.logger.warning.assert_not_called()

    async def test_custom_window_is_honoured(self) -> None:
        reviewer = self._reviewer([self._pr(11, hours_ago=5.0), self._pr(12, hours_ago=20.0)])

        result = await reviewer.today_pr(window_hours=6)

        assert result["window_hours"] == 6
        assert result["today_count"] == 1
        assert "1 open PR opened in the last 6h" in reviewer._wrapper.bot.send_message.await_args.kwargs["text"]

    async def test_failed_send_names_the_chat_and_announces_nothing(self) -> None:
        reviewer = self._reviewer([self._pr(11, hours_ago=1.0)])
        reviewer._wrapper.bot.send_message = AsyncMock(side_effect=RuntimeError("chat not found"))

        result = await reviewer.today_pr()

        assert result["announced"] == 0
        assert result["messages_sent"] == 0
        reviewer.logger.warning.assert_called_once()
        fmt, *args = reviewer.logger.warning.call_args.args
        assert "to chat %s" in fmt
        assert args[0] == "4663754211"

    async def test_list_failure_is_an_error(self) -> None:
        reviewer = self._reviewer([])
        reviewer.git_toolkit.list_pull_requests = AsyncMock(side_effect=RuntimeError("boom"))

        result = await reviewer.today_pr()

        assert result["status"] == "error"
        assert "boom" in result["reason"]
        reviewer._wrapper.bot.send_message.assert_not_awaited()

    async def test_today_digest_goes_to_the_management_chat(self) -> None:
        """today_pr is a management report, not a public-channel nag."""
        reviewer = self._reviewer([self._pr(11, hours_ago=1.0)])
        reviewer.management_chat_id = "-1009998877"

        result = await reviewer.today_pr()

        kwargs = reviewer._wrapper.bot.send_message.await_args.kwargs
        assert kwargs["chat_id"] == "-1009998877"
        assert result["announced"] == 1

    def test_today_pr_digest_splits_when_over_the_telegram_limit(self) -> None:
        reviewer = self._reviewer([])
        prs = [
            {
                "number": n,
                "title": "x" * 150,
                "html_url": f"https://github.com/owner/repo/pull/{n}",
                "user": f"dev{n}",
                "age_hours": 3.0,
                "state": "open",
            }
            for n in range(1, 61)
        ]

        messages = reviewer._format_today_prs_digest(prs, 24)

        assert len(messages) > 1
        assert sum(covered for _, covered in messages) == 60
        for text, _ in messages:
            assert len(text) <= GitHubReviewer._TELEGRAM_MAX_MESSAGE

    def test_today_pr_is_scheduled_daily(self) -> None:
        """today_pr is a daily report, under its own job name."""
        marker = getattr(GitHubReviewer.today_pr, "_schedule_report_type", None)
        assert marker == "daily", "today_pr lost @schedule_daily_report"
        cfg = GitHubReviewer.today_pr._schedule_config
        assert cfg["method_name"] == "today_pr"
        assert cfg["schedule_type"] == "daily"

    def test_every_report_is_on_its_cron(self) -> None:
        """stale + today_pr are daily, the activity digest is weekly."""
        assert GitHubReviewer.report_stale_pull_requests._schedule_report_type == "daily"
        assert GitHubReviewer.report_stale_pull_requests._schedule_config["schedule_type"] == "daily"
        assert GitHubReviewer.report_weekly_activity._schedule_report_type == "weekly"
        assert GitHubReviewer.report_weekly_activity._schedule_config["schedule_type"] == "weekly"


class TestJiraTicketSummary:
    """``report_jira_tickets()`` counts a project by assignee in two columns."""

    @staticmethod
    def _issue(
        key: str,
        *,
        assignee: Optional[str],
        category: str,
        hours_ago: float,
        status_name: str = "Some status",
    ) -> Dict[str, Any]:
        updated = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        return {
            "key": key,
            "fields": {
                "assignee": None if assignee is None else {"displayName": assignee},
                "status": {"name": status_name, "statusCategory": {"key": category}},
                # Jira renders the offset without a colon; the summary must
                # parse that shape, not just GitHub's trailing "Z".
                "updated": updated.isoformat().replace("+00:00", "+0000"),
            },
        }

    @classmethod
    def _reviewer(cls, issues: List[Dict[str, Any]], *, status: str = "ok") -> _MinimalReviewer:
        reviewer = _wire_reviewer()
        reviewer.public_channel_id = "4663754211"
        reviewer.jira_toolkit.jira_search_issues = AsyncMock(
            return_value={
                "status": status,
                "data": {"total": len(issues), "issues": issues},
                "query": "project = NAV",
                "message": "" if status != "error" else "boom",
            }
        )
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=None)
        reviewer._wrapper = MagicMock(bot=bot)
        return reviewer

    def test_summary_buckets_by_assignee_and_window(self) -> None:
        reviewer = _wire_reviewer()
        issues = [
            self._issue("NAV-1", assignee="Ana", category="new", hours_ago=2),
            self._issue("NAV-2", assignee="Ana", category="indeterminate", hours_ago=5),
            self._issue("NAV-3", assignee="Ana", category="done", hours_ago=100),
            self._issue("NAV-4", assignee="Ana", category="done", hours_ago=200),
            self._issue("NAV-5", assignee="Bob", category="new", hours_ago=48),
        ]

        summary = reviewer._summarize_tickets(
            issues,
            now=datetime.now(timezone.utc),
            recent_hours=24,
            window_days=14,
        )

        assert summary["ticket_count"] == 5
        # Ana leads the 14d column, so she sorts first.
        ana, bob = summary["assignees"]
        assert ana["assignee"] == "Ana"
        assert ana["recent"] == {"open": 1, "in_progress": 1, "closed": 0, "total": 2}
        assert ana["window"] == {"open": 1, "in_progress": 1, "closed": 2, "total": 4}
        assert bob["recent"] == {"open": 0, "in_progress": 0, "closed": 0, "total": 0}
        assert bob["window"]["open"] == 1
        assert summary["totals"]["recent"]["total"] == 2
        assert summary["totals"]["window"]["total"] == 5

    def test_unassigned_and_unknown_category_still_counted(self) -> None:
        reviewer = _wire_reviewer()
        issues = [
            self._issue("NAV-1", assignee=None, category="new", hours_ago=1),
            # No statusCategory at all: the name decides the bucket.
            {
                "key": "NAV-2",
                "fields": {
                    "assignee": {"name": "cmartinez"},
                    "status": {"name": "In Review"},
                    "updated": datetime.now(timezone.utc).isoformat(),
                },
            },
            # Neither category nor a recognisable name: counts as open.
            {
                "key": "NAV-3",
                "fields": {"assignee": {"name": "cmartinez"}, "status": {"name": "Pending QA"}},
            },
        ]

        summary = reviewer._summarize_tickets(
            issues,
            now=datetime.now(timezone.utc),
            recent_hours=24,
            window_days=14,
        )

        rows = {entry["assignee"]: entry for entry in summary["assignees"]}
        assert rows["Unassigned"]["recent"]["open"] == 1
        assert rows["cmartinez"]["window"] == {"open": 1, "in_progress": 1, "closed": 0, "total": 2}
        # NAV-3 has no ``updated``: long window only.
        assert rows["cmartinez"]["recent"] == {"open": 0, "in_progress": 1, "closed": 0, "total": 1}

    async def test_report_sends_one_message_with_both_columns(self) -> None:
        reviewer = self._reviewer(
            [
                self._issue("NAV-1", assignee="Ana", category="new", hours_ago=2),
                self._issue("NAV-2", assignee="Ana", category="done", hours_ago=90),
                self._issue("NAV-3", assignee="Bob", category="indeterminate", hours_ago=3),
            ]
        )

        result = await reviewer.report_jira_tickets()

        jql = reviewer.jira_toolkit.jira_search_issues.await_args.kwargs["jql"]
        assert "project = NAV" in jql
        assert "updated >= -14d" in jql
        assert reviewer.jira_toolkit.jira_search_issues.await_args.kwargs["max_results"] is None

        bot = reviewer._wrapper.bot
        bot.send_message.assert_awaited_once()
        text = bot.send_message.await_args.kwargs["text"]
        assert "last 24h" in text
        assert "last 14d" in text
        assert "TOTAL" in text
        assert "<pre>" in text
        for name in ("Ana", "Bob"):
            assert name in text

        assert result["status"] == "ok"
        assert result["ticket_count"] == 3
        assert result["announced"] == 2
        assert result["messages_sent"] == 1
        assert result["totals"]["window"]["total"] == 3
        assert result["totals"]["recent"]["total"] == 2

    async def test_digest_goes_to_the_management_chat(self) -> None:
        """The ticket summary is a management report."""
        reviewer = self._reviewer([self._issue("NAV-1", assignee="Ana", category="new", hours_ago=1)])
        reviewer.management_chat_id = "-1009998877"

        await reviewer.report_jira_tickets()

        kwargs = reviewer._wrapper.bot.send_message.await_args.kwargs
        assert kwargs["chat_id"] == "-1009998877"

    async def test_no_activity_stays_silent(self) -> None:
        reviewer = self._reviewer([], status="empty")

        result = await reviewer.report_jira_tickets()

        reviewer._wrapper.bot.send_message.assert_not_awaited()
        assert result["status"] == "ok"
        assert result["ticket_count"] == 0
        assert result["assignees"] == []
        assert result["messages_sent"] == 0

    async def test_error_envelope_is_reported_not_sent(self) -> None:
        reviewer = self._reviewer([], status="error")

        result = await reviewer.report_jira_tickets()

        reviewer._wrapper.bot.send_message.assert_not_awaited()
        assert result["status"] == "error"
        assert result["reason"] == "boom"

    async def test_search_failure_is_reported(self) -> None:
        reviewer = self._reviewer([])
        reviewer.jira_toolkit.jira_search_issues = AsyncMock(side_effect=RuntimeError("jira down"))

        result = await reviewer.report_jira_tickets()

        assert result["status"] == "error"
        assert result["reason"] == "jira down"
        reviewer.logger.error.assert_called_once()

    async def test_without_a_jira_toolkit_it_reports_an_error(self) -> None:
        reviewer = self._reviewer([])
        reviewer.jira_toolkit = None

        result = await reviewer.report_jira_tickets()

        assert result == {"status": "error", "reason": "jira_toolkit not configured"}

    async def test_failed_send_announces_nothing(self) -> None:
        reviewer = self._reviewer([self._issue("NAV-1", assignee="Ana", category="new", hours_ago=1)])
        reviewer._wrapper.bot.send_message = AsyncMock(side_effect=RuntimeError("chat not found"))

        result = await reviewer.report_jira_tickets()

        assert result["announced"] == 0
        assert result["messages_sent"] == 0
        reviewer.logger.warning.assert_called_once()

    async def test_custom_windows_reach_the_jql_and_the_header(self) -> None:
        reviewer = self._reviewer([self._issue("NAV-1", assignee="Ana", category="new", hours_ago=1)])

        result = await reviewer.report_jira_tickets(recent_hours=8, window_days=3)

        assert "updated >= -3d" in reviewer.jira_toolkit.jira_search_issues.await_args.kwargs["jql"]
        text = reviewer._wrapper.bot.send_message.await_args.kwargs["text"]
        assert "last 8h" in text
        assert "last 3d" in text
        assert result["recent_hours"] == 8
        assert result["window_days"] == 3

    def test_digest_escapes_assignee_names(self) -> None:
        reviewer = _wire_reviewer()
        summary = reviewer._summarize_tickets(
            [self._issue("NAV-1", assignee="A & <b>B</b>", category="new", hours_ago=1)],
            now=datetime.now(timezone.utc),
            recent_hours=24,
            window_days=14,
        )

        messages = reviewer._format_jira_tickets_digest(summary)

        assert len(messages) == 1
        text = messages[0][0]
        assert "A &amp; &lt;b&gt;" in text
        assert "<b>B</b>" not in text

    def test_digest_splits_when_over_the_telegram_limit(self) -> None:
        reviewer = _wire_reviewer()
        issues = [
            self._issue(f"NAV-{n}", assignee=f"developer-number-{n:03d}", category="new", hours_ago=1)
            for n in range(1, 201)
        ]
        summary = reviewer._summarize_tickets(
            issues,
            now=datetime.now(timezone.utc),
            recent_hours=24,
            window_days=14,
        )

        messages = reviewer._format_jira_tickets_digest(summary)

        assert len(messages) > 1
        assert sum(covered for _, covered in messages) == 200
        for text, _ in messages:
            assert len(text) <= GitHubReviewer._TELEGRAM_MAX_MESSAGE
            assert "part " in text
        # The TOTAL row rides on the last part only, so it is never doubled.
        assert sum(text.count("TOTAL") for text, _ in messages) == 1

    def test_table_columns_stay_aligned(self) -> None:
        reviewer = _wire_reviewer()
        summary = reviewer._summarize_tickets(
            [
                self._issue("NAV-1", assignee="Ana", category="new", hours_ago=1),
                self._issue("NAV-2", assignee="a-very-long-developer-name", category="done", hours_ago=1),
            ],
            now=datetime.now(timezone.utc),
            recent_hours=24,
            window_days=14,
        )

        messages = reviewer._format_jira_tickets_digest(summary)

        assert len(messages) == 1
        body = messages[0][0].split("<pre>", 1)[1].split("</pre>", 1)[0]
        rows = [line for line in body.splitlines() if line and not line.startswith("-")]
        assert len({len(line) for line in rows}) == 1
        # The long name is clamped into the fixed-width first column.
        assert "…" in body

    def test_report_jira_tickets_fires_at_10am_new_york(self) -> None:
        """Daily at 10:00 America/New_York, on its own cron job."""
        cfg = GitHubReviewer.report_jira_tickets._schedule_config
        assert cfg["method_name"] == "report_jira_tickets"
        assert cfg["schedule_type"] == "cron"
        assert cfg["schedule_config"] == {"hour": 10, "minute": 0, "timezone": "America/New_York"}
        # A cron job must NOT carry the report marker, or
        # register_bot_schedules() would overwrite its config with the
        # {AGENT_ID}_DAILY_REPORT env var — dragging it back to UTC.
        assert not hasattr(GitHubReviewer.report_jira_tickets, "_schedule_report_type")

    def test_report_jira_tickets_trigger_tracks_dst(self) -> None:
        """10:00 New York is 14:00 UTC in summer and 15:00 UTC in winter."""
        from zoneinfo import ZoneInfo

        from apscheduler.triggers.cron import CronTrigger

        from parrot.scheduler.sanitize import sanitize_schedule_config

        cfg = GitHubReviewer.report_jira_tickets._schedule_config["schedule_config"]
        trigger = CronTrigger(**sanitize_schedule_config("cron", cfg))
        ny = ZoneInfo("America/New_York")

        summer = trigger.get_next_fire_time(None, datetime(2026, 7, 1, 0, 0, tzinfo=ny))
        winter = trigger.get_next_fire_time(None, datetime(2026, 12, 1, 0, 0, tzinfo=ny))

        assert (summer.hour, summer.minute) == (10, 0)
        assert (winter.hour, winter.minute) == (10, 0)
        assert summer.astimezone(timezone.utc).hour == 14
        assert winter.astimezone(timezone.utc).hour == 15


class TestResolvedTicketListing:
    """``report_resolved_tickets()`` names what crossed the finish line."""

    @staticmethod
    def _issue(
        key: str,
        *,
        summary: str = "Some work",
        assignee: Optional[str] = "Ana",
        status_name: str = "Closed",
        hours_ago: Optional[float] = 3,
        resolved_hours_ago: Optional[float] = None,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        fields: Dict[str, Any] = {
            "summary": summary,
            "assignee": None if assignee is None else {"displayName": assignee},
            "status": {"name": status_name, "statusCategory": {"key": "done"}},
        }
        if hours_ago is not None:
            fields["updated"] = (now - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "+0000")
        if resolved_hours_ago is not None:
            fields["resolutiondate"] = (
                (now - timedelta(hours=resolved_hours_ago)).isoformat().replace("+00:00", "+0000")
            )
        return {"key": key, "fields": fields}

    @classmethod
    def _reviewer(cls, issues: List[Dict[str, Any]], *, status: str = "ok") -> _MinimalReviewer:
        reviewer = _wire_reviewer()
        reviewer.public_channel_id = "4663754211"
        reviewer.jira_toolkit.server_url = "https://example.atlassian.net"
        reviewer.jira_toolkit.jira_search_issues = AsyncMock(
            return_value={
                "status": status,
                "data": {"total": len(issues), "issues": issues},
                "query": "project = NAV",
                "message": "" if status != "error" else "boom",
            }
        )
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=None)
        reviewer._wrapper = MagicMock(bot=bot)
        return reviewer

    async def test_jql_asks_for_the_transition_not_the_state(self) -> None:
        reviewer = self._reviewer([self._issue("NAV-1")])

        result = await reviewer.report_resolved_tickets()

        kwargs = reviewer.jira_toolkit.jira_search_issues.await_args.kwargs
        assert kwargs["jql"] == (
            'project = NAV AND status CHANGED TO ("Resolved", "Closed") AFTER -24h ORDER BY updated DESC'
        )
        # Every page, or a busy day silently loses closures.
        assert kwargs["max_results"] is None
        assert kwargs["fields"] == reviewer._RESOLVED_FIELDS
        assert result["window_hours"] == 24

    async def test_sends_one_message_listing_every_ticket(self) -> None:
        reviewer = self._reviewer(
            [
                self._issue("NAV-1", summary="Fix the importer", assignee="Ana", hours_ago=2),
                self._issue("NAV-2", summary="Ship the report", assignee="Bob", status_name="Resolved", hours_ago=9),
            ]
        )

        result = await reviewer.report_resolved_tickets()

        assert result["status"] == "ok"
        assert result["ticket_count"] == 2
        assert (result["announced"], result["messages_sent"]) == (2, 1)
        bot = reviewer._wrapper.bot
        assert bot.send_message.await_count == 1
        kwargs = bot.send_message.await_args.kwargs
        assert kwargs["chat_id"] == "4663754211"
        text = kwargs["text"]
        assert "2 tickets moved to Resolved or Closed in the last 24h" in text
        # Most recent first, each ticket linked to its own Jira issue.
        assert text.index("NAV-1") < text.index("NAV-2")
        assert '<a href="https://example.atlassian.net/browse/NAV-1">NAV-1 Fix the importer</a>' in text
        assert "Bob — Resolved, 9.0h ago" in text

    async def test_stale_resolutiondate_falls_back_to_updated(self) -> None:
        """A ticket reopened and re-closed keeps an old ``resolutiondate``."""
        reviewer = _wire_reviewer()
        rows = reviewer._resolved_ticket_rows(
            [
                self._issue("NAV-1", hours_ago=1, resolved_hours_ago=900),
                self._issue("NAV-2", hours_ago=20, resolved_hours_ago=19),
            ],
            now=datetime.now(timezone.utc),
            window_hours=24,
        )

        by_key = {row["key"]: row for row in rows}
        # 900h ago is outside the window, so the ``updated`` stamp wins.
        assert by_key["NAV-1"]["hours_ago"] == 1.0
        # Inside the window, ``resolutiondate`` is the better stamp.
        assert by_key["NAV-2"]["hours_ago"] == 19.0
        assert [row["key"] for row in rows] == ["NAV-1", "NAV-2"]

    async def test_unassigned_and_stampless_ticket_still_listed(self) -> None:
        reviewer = self._reviewer(
            [
                self._issue("NAV-9", assignee=None, hours_ago=None),
                self._issue("NAV-8", assignee="Ana", hours_ago=4),
            ]
        )

        result = await reviewer.report_resolved_tickets()

        assert result["ticket_count"] == 2
        # A ticket with no usable stamp is reported last, never dropped.
        assert result["tickets"] == ["NAV-8", "NAV-9"]
        text = reviewer._wrapper.bot.send_message.await_args.kwargs["text"]
        assert "Unassigned — Closed, recently" in text

    async def test_returned_dict_is_printable_telemetry(self) -> None:
        """``/call`` echoes the return value through legacy Markdown.

        A summary carrying ``_`` or ``*`` broke that parse, so the status
        dict reports keys and counts — no prose, no datetimes (which are
        not JSON-serialisable either). The digest itself goes out as HTML
        and is unaffected.
        """
        reviewer = self._reviewer([self._issue("NAV-1", summary="Fix snake_case *and* `ticks`")])

        result = await reviewer.report_resolved_tickets()

        assert result["tickets"] == ["NAV-1"]
        rendered = str(result)
        for breaker in ("snake_case", "*and*", "`ticks`", "datetime"):
            assert breaker not in rendered
        # The prose did reach Telegram — in the HTML digest, where it is safe.
        sent = reviewer._wrapper.bot.send_message.await_args.kwargs
        assert sent["parse_mode"] == "HTML"
        assert "Fix snake_case *and* `ticks`" in sent["text"]

    async def test_no_transitions_stays_silent(self) -> None:
        reviewer = self._reviewer([], status="empty")

        result = await reviewer.report_resolved_tickets()

        assert result["status"] == "ok"
        assert (result["ticket_count"], result["announced"], result["messages_sent"]) == (0, 0, 0)
        reviewer._wrapper.bot.send_message.assert_not_awaited()

    async def test_jira_error_is_reported_not_raised(self) -> None:
        reviewer = self._reviewer([], status="error")

        result = await reviewer.report_resolved_tickets()

        assert result["status"] == "error"
        assert result["reason"] == "boom"
        reviewer._wrapper.bot.send_message.assert_not_awaited()

    async def test_search_exception_is_reported_not_raised(self) -> None:
        reviewer = self._reviewer([])
        reviewer.jira_toolkit.jira_search_issues = AsyncMock(side_effect=RuntimeError("jira down"))

        result = await reviewer.report_resolved_tickets()

        assert result["status"] == "error"
        assert "jira down" in result["reason"]

    async def test_custom_window_is_honoured(self) -> None:
        reviewer = self._reviewer([self._issue("NAV-1", hours_ago=30)])

        result = await reviewer.report_resolved_tickets(window_hours=48)

        assert "AFTER -48h" in reviewer.jira_toolkit.jira_search_issues.await_args.kwargs["jql"]
        assert result["window_hours"] == 48
        assert "in the last 48h" in reviewer._wrapper.bot.send_message.await_args.kwargs["text"]

    async def test_missing_server_url_keeps_the_ticket_unlinked(self) -> None:
        reviewer = self._reviewer([self._issue("NAV-1", summary="Fix the importer")])
        reviewer.jira_toolkit.server_url = None

        await reviewer.report_resolved_tickets()

        text = reviewer._wrapper.bot.send_message.await_args.kwargs["text"]
        assert "<a href=" not in text
        assert "<b>NAV-1 Fix the importer</b>" in text

    async def test_long_listing_is_split_into_parts(self) -> None:
        reviewer = self._reviewer(
            [self._issue(f"NAV-{i}", summary="x" * 110, assignee=f"Dev {i}", hours_ago=i) for i in range(1, 61)]
        )

        result = await reviewer.report_resolved_tickets()

        bot = reviewer._wrapper.bot
        assert bot.send_message.await_count > 1
        assert result["messages_sent"] == bot.send_message.await_count
        assert result["announced"] == 60
        for call in bot.send_message.await_args_list:
            text = call.kwargs["text"]
            assert len(text) <= reviewer._TELEGRAM_MAX_MESSAGE
            assert "(part " in text

    async def test_failed_send_does_not_count_as_announced(self) -> None:
        reviewer = self._reviewer([self._issue("NAV-1"), self._issue("NAV-2")])
        reviewer._wrapper.bot.send_message = AsyncMock(side_effect=RuntimeError("telegram down"))

        result = await reviewer.report_resolved_tickets()

        assert result["ticket_count"] == 2
        assert (result["announced"], result["messages_sent"]) == (0, 0)
        reviewer.logger.warning.assert_called()

    async def test_without_a_bot_nothing_is_announced(self) -> None:
        reviewer = self._reviewer([self._issue("NAV-1")])
        reviewer._wrapper = None

        result = await reviewer.report_resolved_tickets()

        assert result["ticket_count"] == 1
        assert (result["announced"], result["messages_sent"]) == (0, 0)
        reviewer.logger.warning.assert_called()

    def test_report_is_scheduled_on_a_timezone_aware_cron(self) -> None:
        """Losing the decorator would silently un-schedule the listing."""
        cfg = getattr(GitHubReviewer.report_resolved_tickets, "_schedule_config", None)
        assert cfg is not None, "report_resolved_tickets lost its @schedule decorator"
        assert cfg["method_name"] == "report_resolved_tickets"
        # Not a daily/weekly report marker: those fire on the scheduler's
        # UTC clock and re-resolve their time from {AGENT_ID}_DAILY_REPORT.
        assert not hasattr(GitHubReviewer.report_resolved_tickets, "_schedule_report_type")


class TestMonthlyTicketPie:
    """``/monthly_jira_tickets`` — the month's tickets per assignee, as a pie."""

    @classmethod
    def _reviewer(cls, issues: List[Dict[str, Any]], *, status: str = "ok") -> _MinimalReviewer:
        reviewer = _wire_reviewer()
        reviewer.public_channel_id = "4663754211"
        reviewer.jira_toolkit.jira_search_issues = AsyncMock(
            return_value={
                "status": status,
                "data": {"total": len(issues), "issues": issues},
                "query": "project = NAV",
                "message": "" if status != "error" else "boom",
            }
        )
        return reviewer

    @staticmethod
    def _tickets(**per_assignee: int) -> List[Dict[str, Any]]:
        """``Ana=3`` -> three NAV issues assigned to Ana inside the window."""
        issues: List[Dict[str, Any]] = []
        for name, count in per_assignee.items():
            for n in range(count):
                issues.append(
                    TestJiraTicketSummary._issue(
                        f"NAV-{name}-{n}",
                        assignee=name,
                        category="new",
                        hours_ago=48,
                    )
                )
        return issues

    @staticmethod
    def _png(tmp_path: Path) -> Path:
        path = tmp_path / "chart_abc123.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return path

    def test_slices_rank_by_volume_and_fold_the_tail(self) -> None:
        reviewer = _wire_reviewer()
        summary = {"assignees": [{"assignee": f"dev-{n:02d}", "window": {"total": 50 - n}} for n in range(12)]}

        slices = reviewer._ticket_pie_slices(summary)

        assert len(slices) == GitHubReviewer._TICKET_PIE_MAX_SLICES + 1
        assert slices[0] == ("dev-00", 50)
        # The three assignees past the cap ride in one wedge, counts summed.
        assert slices[-1] == ("Others (3)", (50 - 9) + (50 - 10) + (50 - 11))
        # Folding never loses a ticket.
        assert sum(count for _, count in slices) == sum(50 - n for n in range(12))

    def test_slices_keep_everyone_under_the_cap_and_drop_the_idle(self) -> None:
        reviewer = _wire_reviewer()
        summary = {
            "assignees": [
                {"assignee": "Ana", "window": {"total": 3}},
                {"assignee": "Bob", "window": {"total": 0}},
                {"assignee": None, "window": {"total": 1}},
            ]
        }

        assert reviewer._ticket_pie_slices(summary) == [("Ana", 3), ("Unassigned", 1)]

    async def test_command_answers_with_the_ranking_and_one_png(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reviewer = self._reviewer(self._tickets(Ana=3, Bob=1))
        seen: Dict[str, Any] = {}

        async def fake_generate_chart(chart_type: str, title: str, data: Dict[str, Any], **kwargs: Any) -> Path:
            seen.update(chart_type=chart_type, title=title, data=data, kwargs=kwargs)
            return self._png(tmp_path)

        monkeypatch.setattr("parrot_tools.chart.generate_chart", fake_generate_chart)

        reply = await reviewer.monthly_jira_tickets()

        # One JQL call, over the month — same shape as the daily digest.
        assert "updated >= -30d" in reviewer.jira_toolkit.jira_search_issues.await_args.kwargs["jql"]
        assert reviewer.jira_toolkit.jira_search_issues.await_args.kwargs["max_results"] is None
        # A pie of each assignee's share, biggest first.
        assert seen["chart_type"] == "pie"
        assert seen["data"] == {"labels": ["Ana", "Bob"], "values": [3, 1]}
        assert seen["kwargs"]["output_format"] == "png"
        # The reply is returned, not sent: the wrapper delivers it.
        assert isinstance(reply, ChartReply)
        assert reply.charts == [
            {
                "path": str(tmp_path / "chart_abc123.png"),
                "title": seen["title"],
                "chart_type": "pie",
                "format": "png",
            }
        ]
        assert "last 30 days on NAV" in reply.output
        assert "Ana" in reply.output and "Bob" in reply.output
        # Nothing was pushed anywhere: the command needs no bot of its own.
        assert reviewer._wrapper is None

    async def test_text_fences_the_table_so_names_cannot_break_parsing(self) -> None:
        reviewer = _wire_reviewer()
        summary = {
            "window_days": 30,
            "ticket_count": 1,
            "assignees": [{"assignee": "A & <b>B</b>", "window": {"total": 1}}],
        }

        text = reviewer._format_monthly_tickets_text(summary, reviewer._ticket_pie_slices(summary))

        # Fenced: the wrapper's Markdown->HTML pass escapes the block, so a
        # display name with markup can never reach Telegram as entities.
        assert text.count("```") == 2
        table = text.split("```")[1]
        assert "A & <b>B" in table
        assert "TOTAL" in table
        assert "100.0%" in table

    async def test_a_chart_that_cannot_be_a_png_still_sends_the_ranking(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No vl-convert-python: the tool writes a Vega-Lite spec instead."""
        reviewer = self._reviewer(self._tickets(Ana=2))
        spec = tmp_path / "chart_abc123.json"
        spec.write_text("{}")

        async def fallback(*_args: Any, **_kwargs: Any) -> Path:
            return spec

        monkeypatch.setattr("parrot_tools.chart.generate_chart", fallback)

        reply = await reviewer.monthly_jira_tickets()

        assert reply.charts == []
        assert "Ana" in reply.output
        reviewer.logger.warning.assert_called_once()

    async def test_a_failing_renderer_is_contained(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reviewer = self._reviewer(self._tickets(Ana=2))

        async def boom(*_args: Any, **_kwargs: Any) -> Path:
            raise RuntimeError("vega exploded")

        monkeypatch.setattr("parrot_tools.chart.generate_chart", boom)

        reply = await reviewer.monthly_jira_tickets()

        assert reply.charts == []
        assert "Ana" in reply.output
        reviewer.logger.warning.assert_called_once()

    async def test_a_jira_failure_comes_back_as_a_notice(self) -> None:
        reviewer = self._reviewer([])
        reviewer.jira_toolkit.jira_search_issues = AsyncMock(side_effect=RuntimeError("jira down"))

        reply = await reviewer.monthly_jira_tickets()

        assert reply.charts == []
        assert "jira down" in reply.output
        assert "NAV" in reply.output

    async def test_a_quiet_month_says_so_instead_of_an_empty_pie(self) -> None:
        reviewer = self._reviewer([])

        reply = await reviewer.monthly_jira_tickets()

        assert reply.charts == []
        assert reply.output == "No NAV ticket was touched in the last 30 days."

    async def test_window_days_survives_telegram_passing_it_as_a_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reviewer = self._reviewer(self._tickets(Ana=1))
        monkeypatch.setattr(
            "parrot_tools.chart.generate_chart",
            AsyncMock(return_value=self._png(tmp_path)),
        )

        reply = await reviewer.monthly_jira_tickets(window_days="7", unexpected="ignored")

        assert "updated >= -7d" in reviewer.jira_toolkit.jira_search_issues.await_args.kwargs["jql"]
        assert "last 7 days on NAV" in reply.output

    async def test_an_unusable_window_falls_back_to_the_month(self) -> None:
        reviewer = self._reviewer([])

        await reviewer.monthly_jira_tickets(window_days="soon")

        assert "updated >= -30d" in reviewer.jira_toolkit.jira_search_issues.await_args.kwargs["jql"]
        reviewer.logger.warning.assert_called_once()

    def test_it_is_exposed_as_a_telegram_command(self) -> None:
        meta = GitHubReviewer.monthly_jira_tickets._telegram_command

        assert meta["command"] == "monthly_jira_tickets"
        # Keyword parsing: `/monthly_jira_tickets window_days=60`.
        assert meta["parse_mode"] == "keyword"
        assert meta["description"]
        # On demand only — it must not join the scheduled reports.
        assert not hasattr(GitHubReviewer.monthly_jira_tickets, "_schedule_config")


class TestMonthlyTicketReport:
    """``report_monthly_jira_tickets()`` — the 1st-of-month send to management."""

    @classmethod
    def _reviewer(cls, issues: List[Dict[str, Any]], **attrs: Any) -> _MinimalReviewer:
        reviewer = TestMonthlyTicketPie._reviewer(issues)
        reviewer.management_chat_id = "-1002223334444"
        bot = MagicMock()
        bot.send_photo = AsyncMock(return_value=None)
        bot.send_message = AsyncMock(return_value=None)
        reviewer._wrapper = MagicMock(bot=bot)
        for name, value in attrs.items():
            setattr(reviewer, name, value)
        return reviewer

    @staticmethod
    def _with_chart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        png = TestMonthlyTicketPie._png(tmp_path)
        monkeypatch.setattr("parrot_tools.chart.generate_chart", AsyncMock(return_value=png))
        return png

    async def test_the_pie_goes_to_management_with_the_table_as_its_caption(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        png = self._with_chart(tmp_path, monkeypatch)
        reviewer = self._reviewer(TestMonthlyTicketPie._tickets(Ana=3, Bob=1))

        result = await reviewer.report_monthly_jira_tickets()

        assert "updated >= -30d" in reviewer.jira_toolkit.jira_search_issues.await_args.kwargs["jql"]
        photo = reviewer._wrapper.bot.send_photo.await_args.kwargs
        assert photo["chat_id"] == "-1002223334444"
        assert Path(photo["photo"].path) == png
        assert photo["parse_mode"] == "HTML"
        # One item in the channel, not two: the digest rides as the caption.
        assert "<pre>" in photo["caption"] and "Ana" in photo["caption"]
        reviewer._wrapper.bot.send_message.assert_not_awaited()
        assert result == {
            "status": "ok",
            "project": "NAV",
            "window_days": 30,
            "ticket_count": 4,
            "wedges": 2,
            "chart": png.name,
            "messages_sent": 1,
        }

    async def test_a_caption_that_would_not_fit_becomes_its_own_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Telegram caps a sendPhoto caption at 1024 characters."""
        self._with_chart(tmp_path, monkeypatch)
        reviewer = self._reviewer(TestMonthlyTicketPie._tickets(Ana=2), _TELEGRAM_MAX_CAPTION=10)

        result = await reviewer.report_monthly_jira_tickets()

        assert reviewer._wrapper.bot.send_photo.await_args.kwargs["caption"] is None
        assert "<pre>" in reviewer._wrapper.bot.send_message.await_args.kwargs["text"]
        assert result["messages_sent"] == 2

    async def test_without_a_png_the_digest_still_goes_out(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = tmp_path / "chart_abc123.json"
        spec.write_text("{}")
        monkeypatch.setattr("parrot_tools.chart.generate_chart", AsyncMock(return_value=spec))
        reviewer = self._reviewer(TestMonthlyTicketPie._tickets(Ana=2))

        result = await reviewer.report_monthly_jira_tickets()

        reviewer._wrapper.bot.send_photo.assert_not_awaited()
        assert "Ana" in reviewer._wrapper.bot.send_message.await_args.kwargs["text"]
        assert result["chart"] is None
        assert result["messages_sent"] == 1

    async def test_a_lost_photo_does_not_take_the_numbers_with_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._with_chart(tmp_path, monkeypatch)
        reviewer = self._reviewer(TestMonthlyTicketPie._tickets(Ana=2))
        reviewer._wrapper.bot.send_photo = AsyncMock(side_effect=RuntimeError("file too big"))

        result = await reviewer.report_monthly_jira_tickets()

        assert "Ana" in reviewer._wrapper.bot.send_message.await_args.kwargs["text"]
        assert result["messages_sent"] == 1
        reviewer.logger.warning.assert_called_once()

    async def test_no_destination_means_nothing_is_sent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both unset: ``management_chat_id`` falls back to the public channel."""
        self._with_chart(tmp_path, monkeypatch)
        reviewer = self._reviewer(
            TestMonthlyTicketPie._tickets(Ana=2),
            management_chat_id=None,
            public_channel_id=None,
        )

        result = await reviewer.report_monthly_jira_tickets()

        reviewer._wrapper.bot.send_photo.assert_not_awaited()
        reviewer._wrapper.bot.send_message.assert_not_awaited()
        assert result["messages_sent"] == 0
        reviewer.logger.warning.assert_called_once()

    async def test_a_quiet_month_stays_silent(self) -> None:
        reviewer = self._reviewer([])

        result = await reviewer.report_monthly_jira_tickets()

        reviewer._wrapper.bot.send_photo.assert_not_awaited()
        reviewer._wrapper.bot.send_message.assert_not_awaited()
        assert result["status"] == "ok"
        assert result["ticket_count"] == 0
        assert result["messages_sent"] == 0

    async def test_a_jira_failure_is_reported_not_raised(self) -> None:
        reviewer = self._reviewer([])
        reviewer.jira_toolkit.jira_search_issues = AsyncMock(side_effect=RuntimeError("jira down"))

        result = await reviewer.report_monthly_jira_tickets()

        assert result["status"] == "error"
        assert result["reason"] == "jira down"
        reviewer._wrapper.bot.send_photo.assert_not_awaited()

    def test_digest_is_escaped_html(self) -> None:
        reviewer = _wire_reviewer()
        summary = {
            "window_days": 30,
            "ticket_count": 1,
            "assignees": [{"assignee": "A & <b>B</b>", "window": {"total": 1}}],
        }

        digest = reviewer._format_monthly_tickets_digest(summary, reviewer._ticket_pie_slices(summary))

        # Sent straight to the Bot API — no wrapper, so it escapes here.
        assert "A &amp; &lt;b&gt;" in digest
        assert "<b>B</b>" not in digest
        assert digest.startswith("<b>Jira tickets by assignee")
        assert "<pre>" in digest

    def test_it_fires_monthly_at_10am_new_york(self) -> None:
        cfg = GitHubReviewer.report_monthly_jira_tickets._schedule_config

        assert cfg["method_name"] == "report_monthly_jira_tickets"
        assert cfg["schedule_type"] == "cron"
        assert cfg["schedule_config"] == {
            "day": 1,
            "hour": 10,
            "minute": 0,
            "timezone": "America/New_York",
        }
        # Same reason as the daily digest: a report marker would have its
        # config re-resolved from {AGENT_ID}_DAILY_REPORT and fire in UTC.
        assert not hasattr(GitHubReviewer.report_monthly_jira_tickets, "_schedule_report_type")

    def test_its_trigger_survives_sanitizing(self) -> None:
        """``day`` is a supported cron field, so nothing is dropped."""
        from apscheduler.triggers.cron import CronTrigger

        from parrot.scheduler.sanitize import sanitize_schedule_config

        cfg = GitHubReviewer.report_monthly_jira_tickets._schedule_config["schedule_config"]
        cleaned = sanitize_schedule_config("cron", cfg)

        # The sanitizer normalizes cron fields to strings; what matters is
        # that ``day`` survived it at all (an unsupported field is dropped).
        assert str(cleaned["day"]) == "1"
        fire = CronTrigger(**cleaned).get_next_fire_time(None, datetime(2026, 1, 15, tzinfo=timezone.utc))
        assert (fire.day, fire.hour, fire.minute) == (1, 10, 0)


class TestWeeklyStatsPending:
    """A persistent 202 from /stats/* defers instead of failing.

    GitHub computes repository stats lazily, so the request that exhausts the
    toolkit's 202 budget is also the one that starts the computation: the next
    attempt usually gets 200. Before this, the exhausted budget surfaced as an
    ERROR with a traceback and the week's report was simply lost.
    """

    @staticmethod
    def _reviewer(delay: int = 0, max_retries: int = 3) -> _MinimalReviewer:
        reviewer = _wire_reviewer()
        reviewer.public_channel_id = "-4788340010"
        reviewer._weekly_retry_task = None
        reviewer._weekly_retry_attempt = 0
        reviewer._stats_retry_delay = delay
        reviewer._stats_retry_max = max_retries
        reviewer._wrapper = None
        exc = StatsNotReadyError(
            "GitHub stats call to https://api.github.com/repos/o/r/stats/code_frequency "
            "returned 202 after 7 attempts; giving up.",
            attempts=7,
            url="https://api.github.com/repos/o/r/stats/code_frequency",
        )
        reviewer.git_toolkit.get_contributor_stats = AsyncMock(return_value=[])
        reviewer.git_toolkit.get_code_frequency = AsyncMock(side_effect=exc)
        return reviewer

    @staticmethod
    def _degradable_reviewer(max_retries: int = 1) -> _MinimalReviewer:
        """Same cold code_frequency, but with usable contributor stats.

        This is the asymmetric 202 measured on a large repo: /stats/contributors
        answers 200 while /stats/code_frequency is still computing.
        """
        reviewer = TestWeeklyStatsPending._reviewer(delay=3600, max_retries=max_retries)
        reviewer.use_llm_summary = False
        reviewer.silent_weeks_threshold = 3
        reviewer.top_n_contributors = 10
        reviewer.git_toolkit.get_contributor_stats = AsyncMock(
            return_value=[_cs("alice", [(W_CURR, 5, 100, 20), (W_PREV, 3, 50, 10)])]
        )
        reviewer._build_weekly_summary = GitHubReviewer._build_weekly_summary.__get__(reviewer, type(reviewer))
        reviewer._format_weekly_activity_html = GitHubReviewer._format_weekly_activity_html.__get__(
            reviewer, type(reviewer)
        )
        sent: List[Dict[str, Any]] = []
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=lambda **kwargs: sent.append(kwargs))
        reviewer._wrapper = MagicMock(bot=bot)
        reviewer._sent = sent
        return reviewer

    async def test_pending_code_freq_defers_while_budget_remains(self) -> None:
        """A partial digest is the last resort, not the first move."""
        reviewer = self._degradable_reviewer(max_retries=3)
        try:
            result = await reviewer.report_weekly_activity()

            assert result["status"] == "stats_pending"
            assert result["retry_scheduled"] is True
            assert reviewer._sent == []
        finally:
            await reviewer._shutdown_weekly_retry()

    async def test_exhausted_budget_publishes_a_partial_digest(self) -> None:
        """The contributor stats that did arrive no longer die with the week."""
        reviewer = self._degradable_reviewer(max_retries=1)
        try:
            await reviewer.report_weekly_activity()
            await reviewer._shutdown_weekly_retry()  # drop the armed task
            reviewer._weekly_retry_attempt = 1  # as if that retry had run

            result = await reviewer.report_weekly_activity()

            assert result["status"] == "ok"
            assert result["partial"] is True
            assert result["active"] == 1
            assert result["telegram_sent"] == 1
            body = reviewer._sent[-1]["text"]
            assert "removed (n/a)" in body  # no delta invented off the zeros
            assert "Partial data" in body
            assert "▲ new" not in body
            # Expected GitHub behaviour: still no ERROR, still no traceback.
            reviewer.logger.error.assert_not_called()
        finally:
            await reviewer._shutdown_weekly_retry()

    async def test_pending_contributor_stats_never_degrade(self) -> None:
        """Without contributor slices there is nothing to publish."""
        reviewer = self._degradable_reviewer(max_retries=1)
        reviewer.git_toolkit.get_contributor_stats = AsyncMock(
            side_effect=StatsNotReadyError(
                "GitHub stats call to .../stats/contributors returned 202 after 7 attempts; giving up.",
                attempts=7,
                url="https://api.github.com/repos/o/r/stats/contributors",
            )
        )
        reviewer.git_toolkit.get_code_frequency = AsyncMock(return_value=[_cf(W_CURR, 100, 20)])
        reviewer._weekly_retry_attempt = 1  # budget already spent
        try:
            result = await reviewer.report_weekly_activity()

            assert result["status"] == "stats_pending"
            assert result["retry_scheduled"] is False
            assert reviewer._sent == []
        finally:
            await reviewer._shutdown_weekly_retry()

    async def test_hard_failure_is_still_an_error(self) -> None:
        """A non-202 failure keeps its ERROR + traceback and publishes nothing."""
        reviewer = self._degradable_reviewer(max_retries=1)
        reviewer.git_toolkit.get_code_frequency = AsyncMock(side_effect=RuntimeError("boom"))

        result = await reviewer.report_weekly_activity()

        assert result["status"] == "error"
        assert "boom" in result["reason"]
        reviewer.logger.error.assert_called_once()
        assert isinstance(reviewer.logger.error.call_args.kwargs.get("exc_info"), RuntimeError)
        assert reviewer._sent == []

    async def test_pending_stats_defer_instead_of_erroring(self) -> None:
        """The outcome is stats_pending with a retry armed, not status=error."""
        reviewer = self._reviewer(delay=3600)
        try:
            result = await reviewer.report_weekly_activity()

            assert result["status"] == "stats_pending"
            assert result["retry_scheduled"] is True
            assert result["attempt"] == 1
            assert result["attempts"] == 7  # the toolkit's in-call 202 budget
            # Logged as a warning without a traceback: expected GitHub behaviour.
            reviewer.logger.error.assert_not_called()
            reviewer.logger.warning.assert_called_once()
            assert "exc_info" not in reviewer.logger.warning.call_args.kwargs
        finally:
            await reviewer._shutdown_weekly_retry()

    async def test_second_call_does_not_stack_a_retry(self) -> None:
        """While a deferred run is armed, another cold run reuses it."""
        reviewer = self._reviewer(delay=3600)
        try:
            await reviewer.report_weekly_activity()
            second = await reviewer.report_weekly_activity()

            assert second["already_armed"] is True
            assert reviewer._weekly_retry_attempt == 1
        finally:
            await reviewer._shutdown_weekly_retry()

    async def test_budget_exhaustion_stops_retrying(self) -> None:
        """Past the budget it gives up quietly until the next scheduled run."""
        reviewer = self._reviewer(delay=3600, max_retries=1)
        try:
            await reviewer.report_weekly_activity()
            await reviewer._shutdown_weekly_retry()  # drop the armed task
            reviewer._weekly_retry_attempt = 1  # as if that retry had run

            result = await reviewer.report_weekly_activity()

            assert result["status"] == "stats_pending"
            assert result["retry_scheduled"] is False
            assert reviewer._weekly_retry_attempt == 0  # budget reset for next week
        finally:
            await reviewer._shutdown_weekly_retry()

    async def test_shutdown_cancels_the_armed_retry(self) -> None:
        """A pending deferral must not outlive the agent."""
        reviewer = self._reviewer(delay=3600)
        await reviewer.report_weekly_activity()
        task = reviewer._weekly_retry_task
        assert task is not None and not task.done()

        await reviewer._shutdown_weekly_retry()

        assert task.cancelled()
        assert reviewer._weekly_retry_task is None


class TestScheduledReportDecorators:
    """The two report methods must keep carrying their schedule decorator.

    ``register_bot_schedules()`` discovers them by the ``_schedule_report_type``
    marker that ``@schedule_daily_report`` / ``@schedule_weekly_report`` leave
    on the wrapper, so losing a decorator silently un-schedules the report —
    no error anywhere, the job just never runs again. Inserting a helper
    between a decorator and its function is an easy way to cause exactly that.
    """

    def test_stale_report_is_scheduled_daily(self) -> None:
        marker = getattr(GitHubReviewer.report_stale_pull_requests, "_schedule_report_type", None)
        assert marker == "daily", "report_stale_pull_requests lost @schedule_daily_report"
        cfg = GitHubReviewer.report_stale_pull_requests._schedule_config
        assert cfg["method_name"] == "report_stale_pull_requests"

    def test_weekly_report_is_scheduled_weekly(self) -> None:
        marker = getattr(GitHubReviewer.report_weekly_activity, "_schedule_report_type", None)
        assert marker == "weekly", "report_weekly_activity lost @schedule_weekly_report"
        cfg = GitHubReviewer.report_weekly_activity._schedule_config
        assert cfg["method_name"] == "report_weekly_activity"

    def test_helpers_are_not_scheduled(self) -> None:
        """A decorator must never land on a plain helper by accident."""
        for name in ("_defer_weekly_report", "_shutdown_weekly_retry", "_describe_webhook_denial"):
            attr = getattr(GitHubReviewer, name)
            assert not hasattr(attr, "_schedule_report_type"), f"{name} is decorated as a report"


# ---------------------------------------------------------------------------
# /review_pr — strict on-demand gate (code review + Jira + CI, then enforce)
# ---------------------------------------------------------------------------


_ROSTER = [
    {
        "id": "35",
        "name": "Jesus Lara",
        "jira_username": "jesuslarag@gmail.com",
        "telegram_chat_id": "286137732",
        "username": "jlara@trocglobal.com",
    }
]


def _checks(
    *,
    success: int = 2,
    failure: int = 0,
    pending: int = 0,
    names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a raw ``get_pr_checks`` payload with the given state counts."""
    entries: List[Dict[str, Any]] = []
    pool = list(names or [])

    def _name(default: str) -> str:
        return pool.pop(0) if pool else default

    for _ in range(success):
        entries.append({"name": _name("pytest"), "state": "success"})
    for _ in range(failure):
        entries.append({"name": _name("e2e tests"), "state": "failure"})
    for _ in range(pending):
        entries.append({"name": _name("build"), "state": "pending"})
    return {
        "repository": "owner/repo",
        "pr_number": 42,
        "head_sha": "sha",
        "checks": entries,
        "total": len(entries),
        "success": success,
        "failure": failure,
        "pending": pending,
    }


def _ticket(assignee: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    fields: Dict[str, Any] = {"summary": "S", "description": "D"}
    if assignee is not None:
        fields["assignee"] = assignee
    return {"fields": fields}


def _wire_strict(
    *,
    approve: bool = True,
    discrepancies: Optional[List[Discrepancy]] = None,
    checks_raw: Optional[Dict[str, Any]] = None,
    checks_error: Optional[Exception] = None,
    assignee: Optional[Dict[str, Any]] = None,
    ticket: Any = "default",
) -> Any:
    """A reviewer wired for the strict path: ticket, diff, LLM, CI and bot."""
    r = _wire_reviewer()
    r.public_channel_id = "-1009999"
    resolved = _ticket(assignee) if ticket == "default" else ticket
    r._fetch_ticket = AsyncMock(return_value=resolved)
    r._fetch_diff = AsyncMock(return_value=("diff", False, True))
    r._ask_llm_for_review = AsyncMock(
        return_value=PRReviewResult(
            jira_key="NAV-1",
            discrepancies=list(discrepancies or []),
            summary="reviewed",
            approve=approve,
        )
    )
    if checks_error is not None:
        r.git_toolkit.get_pr_checks = AsyncMock(side_effect=checks_error)
    else:
        r.git_toolkit.get_pr_checks = AsyncMock(return_value=checks_raw if checks_raw is not None else _checks())
    r.git_toolkit.submit_pr_review = AsyncMock(return_value={"id": 1, "state": "APPROVED"})
    r.git_toolkit.add_pr_comment = AsyncMock(return_value={"id": 7, "html_url": "u"})
    r.git_toolkit.convert_pr_to_draft = AsyncMock(
        return_value={"status": "converted", "pr_number": 42, "is_draft": True}
    )
    bot = MagicMock()
    bot.send_message = AsyncMock()
    r._wrapper = MagicMock()
    r._wrapper.bot = bot
    return r


_PAYLOAD = {
    "repository": "owner/repo",
    "pr_number": 42,
    "pr_title": "feat: thing",
    "pr_body": "Implements NAV-1",
    "pr_url": "https://github.com/owner/repo/pull/42",
    "head_sha": "sha",
    "author": "octocat",
    "draft": False,
    "state": "open",
}


class TestParsePRTarget:
    """``/review_pr`` must accept whatever shape the PR arrives in."""

    def test_accepts_url_slug_and_bare_number(self) -> None:
        assert GitHubReviewer._parse_pr_target("https://github.com/owner/repo/pull/42") == ("owner/repo", 42, None)
        assert GitHubReviewer._parse_pr_target("http://www.github.com/o/r/pull/7/files") == ("o/r", 7, None)
        assert GitHubReviewer._parse_pr_target("owner/repo#13") == ("owner/repo", 13, None)
        assert GitHubReviewer._parse_pr_target("owner/repo/pull/13") == ("owner/repo", 13, None)
        # A bare number leaves the repository to the caller's default.
        assert GitHubReviewer._parse_pr_target("#99") == (None, 99, None)
        assert GitHubReviewer._parse_pr_target("99") == (None, 99, None)

    def test_ignores_trailing_prose_and_punctuation(self) -> None:
        assert GitHubReviewer._parse_pr_target("https://github.com/o/r/pull/5 please review") == ("o/r", 5, None)
        assert GitHubReviewer._parse_pr_target("  owner/repo#8,  ") == ("owner/repo", 8, None)

    def test_names_the_repository_link_mistake(self) -> None:
        """A repo link is the likeliest typo, so it gets its own message."""
        repo, number, error = GitHubReviewer._parse_pr_target("https://github.com/owner/repo")
        assert (repo, number) == (None, None)
        assert "repository link" in str(error)

    def test_rejects_junk_and_emptiness(self) -> None:
        assert GitHubReviewer._parse_pr_target("")[2] == "no pull request given"
        assert "could not read a pull request" in str(GitHubReviewer._parse_pr_target("hola")[2])


class TestSummarizeChecks:
    def test_counts_states_and_excludes_pending_from_the_ratio(self) -> None:
        """A half-finished pipeline must not read as half-failing."""
        summary = GitHubReviewer._summarize_checks(_checks(success=2, failure=1, pending=1))
        assert (summary.success, summary.failure, summary.pending) == (2, 1, 1)
        # 2 of the 3 COMPLETED checks are green — the pending one is excluded.
        assert summary.pass_ratio == pytest.approx(2 / 3)
        assert summary.failing == ["e2e tests"]
        assert summary.running == ["build"]
        assert summary.declared is True

    def test_distinguishes_absent_checks_from_unreadable_ones(self) -> None:
        absent = GitHubReviewer._summarize_checks({"checks": [], "total": 0})
        assert (absent.available, absent.declared) == (True, False)
        unreadable = GitHubReviewer._summarize_checks(None)
        assert (unreadable.available, unreadable.declared) == (False, False)
        assert unreadable.reason

    def test_recognizes_test_shaped_check_names(self) -> None:
        summary = GitHubReviewer._summarize_checks(
            _checks(success=3, names=["pytest unit", "build docker", "e2e-suite"])
        )
        assert summary.test_checks == 2

    async def test_fetch_checks_never_raises(self) -> None:
        r = _wire_reviewer()
        r.git_toolkit.get_pr_checks = AsyncMock(side_effect=RuntimeError("403 no checks:read"))
        summary = await r._fetch_checks("owner/repo", 42, "sha")
        assert summary.available is False
        assert "403" in str(summary.reason)
        r.logger.warning.assert_called_once()

    async def test_fetch_checks_without_a_toolkit(self) -> None:
        r = _wire_reviewer()
        r.git_toolkit = None
        summary = await r._fetch_checks("owner/repo", 42)
        assert summary.available is False
        assert "git_toolkit" in str(summary.reason)


class TestMergeVerdict:
    """The gate: Jira compliance AND test evidence, both required."""

    def _result(self, approve: bool, *discrepancies: Discrepancy) -> PRReviewResult:
        return PRReviewResult(jira_key="NAV-1", discrepancies=list(discrepancies), summary="s", approve=approve)

    def test_green_and_compliant_is_mergeable(self) -> None:
        r = _wire_reviewer()
        verdict = r._merge_verdict(self._result(True), GitHubReviewer._summarize_checks(_checks(success=3)))
        assert verdict.mergeable is True
        assert verdict.defer is False
        assert verdict.reasons == []

    def test_a_blocker_finding_blocks_even_with_green_ci(self) -> None:
        r = _wire_reviewer()
        blocker = Discrepancy(criterion="AC2", issue="endpoint missing", severity="blocker")
        verdict = r._merge_verdict(self._result(False, blocker), GitHubReviewer._summarize_checks(_checks(success=3)))
        assert verdict.mergeable is False
        assert any("AC2" in reason for reason in verdict.reasons)

    def test_a_minor_finding_is_only_a_warning(self) -> None:
        r = _wire_reviewer()
        minor = Discrepancy(criterion="AC9", issue="typo in a docstring", severity="minor")
        verdict = r._merge_verdict(self._result(True, minor), GitHubReviewer._summarize_checks(_checks(success=3)))
        assert verdict.mergeable is True
        assert any("AC9" in warning for warning in verdict.warnings)

    def test_failing_ci_below_the_ratio_blocks(self) -> None:
        r = _wire_reviewer()
        verdict = r._merge_verdict(
            self._result(True),
            GitHubReviewer._summarize_checks(_checks(success=1, failure=3)),
        )
        assert verdict.mergeable is False
        assert any("failing" in reason for reason in verdict.reasons)

    def test_mostly_green_ci_is_tolerated(self) -> None:
        """ "All OK — or a great part of them": 8/10 green clears a 0.8 bar."""
        r = _wire_reviewer()
        verdict = r._merge_verdict(
            self._result(True),
            GitHubReviewer._summarize_checks(_checks(success=8, failure=2)),
        )
        assert verdict.mergeable is True
        assert any("at or above" in warning for warning in verdict.warnings)

    def test_the_ratio_is_configurable(self) -> None:
        r = _wire_reviewer()
        r.min_check_pass_ratio = 1.0
        verdict = r._merge_verdict(
            self._result(True),
            GitHubReviewer._summarize_checks(_checks(success=9, failure=1)),
        )
        assert verdict.mergeable is False

    def test_running_checks_defer_the_verdict(self) -> None:
        r = _wire_reviewer()
        verdict = r._merge_verdict(self._result(True), GitHubReviewer._summarize_checks(_checks(success=1, pending=2)))
        assert (verdict.mergeable, verdict.defer) == (False, True)
        assert verdict.reasons == []

    def test_running_checks_do_not_defer_an_already_blocked_pr(self) -> None:
        """A blocker is reason enough to draft the PR now, CI or no CI."""
        r = _wire_reviewer()
        blocker = Discrepancy(criterion="AC1", issue="not implemented", severity="blocker")
        verdict = r._merge_verdict(
            self._result(False, blocker),
            GitHubReviewer._summarize_checks(_checks(success=0, pending=4)),
        )
        assert (verdict.mergeable, verdict.defer) == (False, False)

    def test_unreadable_ci_defers_rather_than_approving(self) -> None:
        """An outage or a missing scope is not test evidence — and not a fault."""
        r = _wire_reviewer()
        verdict = r._merge_verdict(self._result(True), PRChecksSummary(available=False, reason="403"))
        assert (verdict.mergeable, verdict.defer) == (False, True)
        assert verdict.reasons == []
        assert any("could not be read" in warning for warning in verdict.warnings)

    def test_absent_checks_warn_by_default(self) -> None:
        r = _wire_reviewer()
        verdict = r._merge_verdict(self._result(True), GitHubReviewer._summarize_checks({"checks": [], "total": 0}))
        assert verdict.mergeable is True
        assert any("no CI checks" in warning for warning in verdict.warnings)

    def test_absent_checks_block_when_checks_are_required(self) -> None:
        r = _wire_reviewer()
        r.require_checks = True
        verdict = r._merge_verdict(self._result(True), GitHubReviewer._summarize_checks({"checks": [], "total": 0}))
        assert verdict.mergeable is False
        assert any("no CI checks" in reason for reason in verdict.reasons)


class TestAssigneeResolution:
    def test_matches_on_email_account_id_or_display_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        r = _wire_reviewer()
        monkeypatch.setattr(conf, "JIRA_USERS", _ROSTER)
        by_email = r._resolve_assignee(_ticket({"emailAddress": "JesusLaraG@gmail.com"}))
        by_account = r._resolve_assignee(_ticket({"accountId": "35"}))
        by_name = r._resolve_assignee(_ticket({"displayName": "jesus lara"}))
        assert by_email is not None and by_email["name"] == "Jesus Lara"
        assert by_account is by_email
        assert by_name is by_email

    def test_unknown_or_absent_assignee_resolves_to_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        r = _wire_reviewer()
        monkeypatch.setattr(conf, "JIRA_USERS", _ROSTER)
        assert r._resolve_assignee(_ticket({"emailAddress": "stranger@example.com"})) is None
        assert r._resolve_assignee(_ticket()) is None
        assert r._resolve_assignee(None) is None

    def test_malformed_roster_entries_are_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One bad entry must not break the notification path of a real review."""
        r = _wire_reviewer()
        monkeypatch.setattr(conf, "JIRA_USERS", ["not-a-dict", None, *_ROSTER])
        found = r._resolve_assignee(_ticket({"emailAddress": "jesuslarag@gmail.com"}))
        assert found is not None and found["telegram_chat_id"] == "286137732"

    def test_mention_prefers_a_username_and_falls_back_to_a_tg_link(self) -> None:
        assert GitHubReviewer._telegram_mention({"name": "A", "telegram_username": "@ada"}) == "@ada"
        link = GitHubReviewer._telegram_mention({"name": "Ada L", "telegram_chat_id": "123"})
        assert link == '<a href="tg://user?id=123">@Ada L</a>'
        # Neither id nor username: still renders something mention-shaped.
        assert GitHubReviewer._telegram_mention({"name": "Ada"}) == "@Ada"


class TestBlockedPRNotifications:
    def test_message_escapes_user_data(self) -> None:
        r = _wire_reviewer()
        payload = {**_PAYLOAD, "pr_title": "feat: X_y <z> & more"}
        verdict = MergeVerdict(mergeable=False, reasons=["AC1 <broken> & unmet"])
        text = r._format_blocked_message(payload, "NAV-1", PRChecksSummary(available=False), verdict)
        assert "&lt;z&gt; &amp; more" in text
        assert "&lt;broken&gt; &amp; unmet" in text
        assert "<z>" not in text

    def test_channel_copy_carries_the_mention_and_the_dm_does_not(self) -> None:
        r = _wire_reviewer()
        verdict = MergeVerdict(mergeable=False, reasons=["nope"])
        checks = GitHubReviewer._summarize_checks(_checks(success=1, failure=1))
        dm = r._format_blocked_message(_PAYLOAD, "NAV-1", checks, verdict)
        channel = r._format_blocked_message(_PAYLOAD, "NAV-1", checks, verdict, mention="@ada")
        assert dm.startswith("<b>Your pull request")
        assert channel.startswith("@ada — your pull request")
        assert "1 passed, 1 failed" in dm

    async def test_dm_and_channel_both_go_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "JIRA_USERS", _ROSTER)
        r = _wire_strict()
        verdict = MergeVerdict(mergeable=False, reasons=["AC1 unmet"])
        report = await r._notify_blocked_pr(
            _PAYLOAD,
            "NAV-1",
            PRChecksSummary(available=True, declared=True, success=1),
            verdict,
            _ticket({"emailAddress": "jesuslarag@gmail.com"}),
        )
        bot = r._wrapper.bot
        assert report["assignee"] == "Jesus Lara"
        assert report["dm"] == {"sent": True, "chat_id": "286137732"}
        assert report["channel"]["sent"] is True
        assert bot.send_message.await_count == 2
        dm_call, channel_call = bot.send_message.await_args_list
        assert dm_call.kwargs["chat_id"] == "286137732"
        assert channel_call.kwargs["chat_id"] == "-1009999"
        assert "tg://user?id=286137732" in channel_call.kwargs["text"]

    async def test_assignee_outside_the_roster_still_reaches_the_channel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "JIRA_USERS", _ROSTER)
        r = _wire_strict()
        report = await r._notify_blocked_pr(
            _PAYLOAD,
            "NAV-1",
            PRChecksSummary(),
            MergeVerdict(mergeable=False, reasons=["x"]),
            _ticket({"emailAddress": "stranger@example.com"}),
        )
        assert report["assignee"] is None
        assert report["dm"] == {"sent": False, "reason": "assignee not in JIRA_USERS"}
        assert report["channel"]["sent"] is True
        # Exactly one send: the channel copy, with no mention to render.
        assert r._wrapper.bot.send_message.await_count == 1

    async def test_a_failed_dm_does_not_stop_the_channel_notice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "JIRA_USERS", _ROSTER)
        r = _wire_strict()

        async def _send(chat_id: Any, **kwargs: Any) -> None:
            if str(chat_id) == "286137732":
                raise RuntimeError("bot was blocked by the user")

        r._wrapper.bot.send_message = AsyncMock(side_effect=_send)
        report = await r._notify_blocked_pr(
            _PAYLOAD,
            "NAV-1",
            PRChecksSummary(),
            MergeVerdict(mergeable=False, reasons=["x"]),
            _ticket({"emailAddress": "jesuslarag@gmail.com"}),
        )
        assert report["dm"]["sent"] is False
        assert "blocked" in report["dm"]["error"]
        assert report["channel"]["sent"] is True

    async def test_a_failed_channel_send_names_the_chat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "JIRA_USERS", _ROSTER)
        r = _wire_strict()
        r._wrapper.bot.send_message = AsyncMock(side_effect=RuntimeError("chat not found"))
        report = await r._notify_blocked_pr(
            _PAYLOAD, "NAV-1", PRChecksSummary(), MergeVerdict(mergeable=False, reasons=["x"]), _ticket()
        )
        assert report["channel"] == {"sent": False, "chat_id": "-1009999", "error": "chat not found"}
        logged = str(r.logger.warning.call_args)
        assert "-1009999" in logged

    async def test_no_channel_configured_is_reported_not_crashed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "JIRA_USERS", _ROSTER)
        r = _wire_strict()
        r.public_channel_id = None
        report = await r._notify_blocked_pr(
            _PAYLOAD, "NAV-1", PRChecksSummary(), MergeVerdict(mergeable=False, reasons=["x"]), _ticket()
        )
        assert report["channel"] == {"sent": False, "reason": "no public channel configured"}

    async def test_without_a_telegram_wrapper_nothing_is_sent(self) -> None:
        r = _wire_strict()
        r._wrapper = None
        report = await r._notify_blocked_pr(
            _PAYLOAD, "NAV-1", PRChecksSummary(), MergeVerdict(mergeable=False, reasons=["x"]), _ticket()
        )
        assert report["reason"] == "no telegram wrapper"
        assert report["dm"]["sent"] is False


class TestStrictReviewPullRequest:
    """The enforcement path: approve, defer, or draft + comment + notify."""

    async def test_compliant_pr_is_approved_and_never_drafted(self) -> None:
        r = _wire_strict(approve=True, checks_raw=_checks(success=3))
        out = await r.strict_review_pull_request(dict(_PAYLOAD))
        assert out["status"] == "approved"
        r.git_toolkit.convert_pr_to_draft.assert_not_awaited()
        r.git_toolkit.add_pr_comment.assert_not_awaited()
        assert r.git_toolkit.submit_pr_review.await_args.kwargs["event"] == "APPROVE"

    async def test_strict_path_asks_jira_for_the_assignee(self) -> None:
        """The webhook path does not need the assignee; this one does."""
        r = _wire_strict()
        await r.strict_review_pull_request(dict(_PAYLOAD))
        assert "assignee" in r._fetch_ticket.await_args.kwargs["fields"]

    async def test_noncompliant_pr_is_drafted_commented_and_announced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "JIRA_USERS", _ROSTER)
        blocker = Discrepancy(criterion="AC2", issue="endpoint missing", severity="blocker")
        r = _wire_strict(
            approve=False,
            discrepancies=[blocker],
            checks_raw=_checks(success=1, failure=2),
            assignee={"emailAddress": "jesuslarag@gmail.com"},
        )
        out = await r.strict_review_pull_request(dict(_PAYLOAD))

        assert out["status"] == "blocked"
        assert out["draft"]["status"] == "converted"
        r.git_toolkit.convert_pr_to_draft.assert_awaited_once()
        body = r.git_toolkit.add_pr_comment.await_args.kwargs["body"]
        assert "not mergeable" in body
        assert "AC2" in body
        assert "@octocat" in body  # the PR author is pinged on GitHub
        assert r.git_toolkit.submit_pr_review.await_args.kwargs["event"] == "REQUEST_CHANGES"
        assert out["alerts"]["dm"]["sent"] is True
        assert out["alerts"]["channel"]["sent"] is True

    async def test_the_draft_call_precedes_the_comment(self) -> None:
        """The PR must stop being mergeable before anyone reads the reason."""
        r = _wire_strict(approve=False, checks_raw=_checks(success=0, failure=2))
        order: List[str] = []
        r.git_toolkit.convert_pr_to_draft = AsyncMock(
            side_effect=lambda **kw: order.append("draft") or {"status": "converted"}
        )
        r.git_toolkit.add_pr_comment = AsyncMock(side_effect=lambda **kw: order.append("comment") or {"id": 1})
        await r.strict_review_pull_request(dict(_PAYLOAD))
        assert order == ["draft", "comment"]

    async def test_a_failed_draft_conversion_still_comments_and_notifies(self) -> None:
        r = _wire_strict(approve=False, checks_raw=_checks(success=0, failure=2))
        r.git_toolkit.convert_pr_to_draft = AsyncMock(side_effect=RuntimeError("422 not permitted"))
        out = await r.strict_review_pull_request(dict(_PAYLOAD))
        assert out["status"] == "blocked"
        assert "422" in out["draft_error"]
        r.git_toolkit.add_pr_comment.assert_awaited_once()
        assert out["alerts"]["channel"]["sent"] is True

    async def test_a_failed_comment_is_recorded_without_losing_the_draft(self) -> None:
        r = _wire_strict(approve=False, checks_raw=_checks(success=0, failure=2))
        r.git_toolkit.add_pr_comment = AsyncMock(side_effect=RuntimeError("503"))
        out = await r.strict_review_pull_request(dict(_PAYLOAD))
        assert out["draft"]["status"] == "converted"
        assert out["comment_error"] == "503"

    async def test_running_checks_leave_the_pr_untouched(self) -> None:
        r = _wire_strict(approve=True, checks_raw=_checks(success=1, pending=2))
        out = await r.strict_review_pull_request(dict(_PAYLOAD))
        assert out["status"] == "deferred"
        r.git_toolkit.convert_pr_to_draft.assert_not_awaited()
        call = r.git_toolkit.submit_pr_review.await_args.kwargs
        assert call["event"] == "COMMENT"
        assert "deferred" in call["body"]
        assert r._wrapper.bot.send_message.await_count == 0

    async def test_unreadable_checks_defer_and_say_why(self) -> None:
        r = _wire_strict(approve=True, checks_error=RuntimeError("403 no checks:read"))
        out = await r.strict_review_pull_request(dict(_PAYLOAD))
        assert out["status"] == "deferred"
        body = r.git_toolkit.submit_pr_review.await_args.kwargs["body"]
        assert "could not be read" in body
        assert "403" in body
        r.git_toolkit.convert_pr_to_draft.assert_not_awaited()

    async def test_a_pr_without_a_ticket_gets_the_missing_ticket_comment(self) -> None:
        r = _wire_strict()
        r._notify_missing_ticket = AsyncMock(return_value={"id": 3})
        out = await r.strict_review_pull_request({**_PAYLOAD, "pr_body": "no key here", "pr_title": "chore"})
        assert out["status"] == "no_ticket"
        assert out["comment"] == {"id": 3}
        r._ask_llm_for_review.assert_not_awaited()
        r.git_toolkit.convert_pr_to_draft.assert_not_awaited()

    async def test_an_unreadable_ticket_stops_before_touching_github(self) -> None:
        r = _wire_strict(ticket=None)
        out = await r.strict_review_pull_request(dict(_PAYLOAD))
        assert out["status"] == "ticket_not_found"
        assert out["jira_key"] == "NAV-1"
        r._ask_llm_for_review.assert_not_awaited()
        r.git_toolkit.submit_pr_review.assert_not_awaited()

    async def test_a_missing_pr_number_is_an_error(self) -> None:
        r = _wire_strict()
        out = await r.strict_review_pull_request({"repository": "owner/repo"})
        assert out == {"status": "error", "reason": "missing pr_number"}

    async def test_without_github_the_verdict_is_still_computed(self) -> None:
        """No toolkit: report the verdict instead of pretending to enforce it."""
        r = _wire_strict(approve=False, checks_raw=_checks(success=0, failure=2))
        r.git_toolkit = None
        out = await r.strict_review_pull_request(dict(_PAYLOAD))
        assert out["status"] == "blocked"
        assert out["review_error"] == "git_toolkit is not configured"
        assert out["verdict"]["reasons"]


class TestReviewPRCommand:
    async def test_is_registered_as_a_raw_telegram_command(self) -> None:
        """``raw`` keeps a pasted URL intact — keyword parsing would mangle it."""
        meta = GitHubReviewer.review_pr._telegram_command
        assert meta["command"] == "review_pr"
        assert meta["parse_mode"] == "raw"
        assert meta["description"]

    async def test_a_repository_link_gets_usage_help(self) -> None:
        r = _wire_strict()
        reply = await r.review_pr("https://github.com/owner/repo")
        assert "repository link" in reply
        assert "Usage:" in reply
        r.git_toolkit.get_pull_request.assert_not_called()

    async def test_an_empty_argument_gets_usage_help(self) -> None:
        r = _wire_strict()
        assert "Usage:" in await r.review_pr("")

    async def test_without_github_configured_it_says_so(self) -> None:
        r = _wire_strict()
        r.git_toolkit = None
        assert "not configured" in await r.review_pr("42")

    async def test_an_unreadable_pr_is_reported(self) -> None:
        r = _wire_strict()
        r.git_toolkit.get_pull_request = AsyncMock(side_effect=RuntimeError("404"))
        reply = await r.review_pr("https://github.com/owner/repo/pull/42")
        assert "Could not read" in reply
        assert "owner/repo#42" in reply

    async def test_a_closed_pr_is_refused_before_any_review(self) -> None:
        r = _wire_strict()
        r.git_toolkit.get_pull_request = AsyncMock(
            return_value={"title": "t", "state": "closed", "head": {"sha": "s"}, "user": {"login": "o"}}
        )
        reply = await r.review_pr("42")
        assert "closed" in reply
        r._ask_llm_for_review.assert_not_awaited()

    async def test_a_bare_number_uses_the_configured_repository(self) -> None:
        r = _wire_strict()
        r.git_toolkit.get_pull_request = AsyncMock(
            return_value={
                "title": "t",
                "body": "Implements NAV-1",
                "state": "open",
                "html_url": "u",
                "head": {"sha": "s"},
                "user": {"login": "o"},
            }
        )
        await r.review_pr("42")
        assert r.git_toolkit.get_pull_request.await_args.kwargs["repository"] == "owner/repo"

    async def test_the_blocked_reply_lists_reasons_and_who_was_told(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "JIRA_USERS", _ROSTER)
        r = _wire_strict(
            approve=False,
            discrepancies=[Discrepancy(criterion="AC2", issue="missing", severity="blocker")],
            checks_raw=_checks(success=0, failure=2),
            assignee={"emailAddress": "jesuslarag@gmail.com"},
        )
        r.git_toolkit.get_pull_request = AsyncMock(
            return_value={
                "title": "feat: thing",
                "body": "Implements NAV-1",
                "state": "open",
                "html_url": "https://github.com/owner/repo/pull/42",
                "head": {"sha": "s"},
                "user": {"login": "octocat"},
            }
        )
        reply = await r.review_pr("https://github.com/owner/repo/pull/42")
        assert reply.startswith("🚫")
        assert "converted to **draft**" in reply
        assert "AC2" in reply
        assert "DM to Jesus Lara" in reply
        assert "the public channel" in reply
        assert "0 passed, 2 failed" in reply

    async def test_the_approved_reply_is_short_and_green(self) -> None:
        r = _wire_strict(approve=True, checks_raw=_checks(success=3))
        r.git_toolkit.get_pull_request = AsyncMock(
            return_value={
                "title": "feat: thing",
                "body": "Implements NAV-1",
                "state": "open",
                "html_url": "u",
                "head": {"sha": "s"},
                "user": {"login": "o"},
            }
        )
        reply = await r.review_pr("42")
        assert reply.startswith("✅")
        assert "Approved" in reply
        assert "3 passed, 0 failed" in reply

    async def test_a_ticketless_pr_reply_explains_the_skip(self) -> None:
        r = _wire_strict()
        r._notify_missing_ticket = AsyncMock(return_value={"id": 1})
        r.git_toolkit.get_pull_request = AsyncMock(
            return_value={
                "title": "chore: tidy",
                "body": "",
                "state": "open",
                "html_url": "u",
                "head": {"sha": "s"},
                "user": {"login": "o"},
            }
        )
        reply = await r.review_pr("42")
        assert "NAV-<number>" in reply
        assert "left a comment" in reply


# ---------------------------------------------------------------------------
# Dedicated Google credential (GITHUB_REVIEW_GOOGLE_API_KEY)
# ---------------------------------------------------------------------------


class _CredentialStub:
    """Agent stand-in carrying only what ``_apply_google_api_key`` reads."""

    # The real resolver — the method under test dispatches through ``self``
    # so a subclass can override it.
    _resolve_google_api_key = staticmethod(GitHubReviewer._resolve_google_api_key)

    def __init__(self, llm: Any = None, llm_kwargs: Optional[Dict[str, Any]] = None) -> None:
        self._llm_raw = llm
        self._default_llm = "google"
        self._llm_kwargs: Dict[str, Any] = {"temperature": 0.1} if llm_kwargs is None else llm_kwargs
        self.logger = MagicMock()


def _apply(stub: _CredentialStub, explicit: Optional[str] = None) -> bool:
    return GitHubReviewer._apply_google_api_key(stub, explicit)


class TestGoogleApiKeyResolution:
    """The reviewer bills its LLM traffic to its own Google credential."""

    def test_explicit_argument_wins_over_the_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "GITHUB_REVIEW_GOOGLE_API_KEY", "from-env", raising=False)
        assert GitHubReviewer._resolve_google_api_key("explicit") == "explicit"

    def test_the_dedicated_env_var_is_used_when_no_argument_is_given(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "GITHUB_REVIEW_GOOGLE_API_KEY", "reviewer-key", raising=False)
        assert GitHubReviewer._resolve_google_api_key() == "reviewer-key"

    def test_an_unset_key_resolves_to_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "GITHUB_REVIEW_GOOGLE_API_KEY", None, raising=False)
        assert GitHubReviewer._resolve_google_api_key() is None

    def test_an_empty_key_resolves_to_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "GITHUB_REVIEW_GOOGLE_API_KEY", "", raising=False)
        assert GitHubReviewer._resolve_google_api_key() is None

    def test_the_key_is_injected_into_the_llm_kwargs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "GITHUB_REVIEW_GOOGLE_API_KEY", "reviewer-key", raising=False)
        stub = _CredentialStub()
        assert _apply(stub) is True
        assert stub._llm_kwargs["api_key"] == "reviewer-key"
        # The other LLM settings survive the rebind.
        assert stub._llm_kwargs["temperature"] == 0.1

    def test_injection_does_not_mutate_the_callers_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "GITHUB_REVIEW_GOOGLE_API_KEY", "reviewer-key", raising=False)
        shared: Dict[str, Any] = {"temperature": 0.1}
        stub = _CredentialStub(llm_kwargs=shared)
        assert _apply(stub) is True
        assert "api_key" not in shared

    def test_an_unset_key_falls_back_to_the_clients_google_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nothing is injected, so the Google client resolves GOOGLE_API_KEY itself."""
        monkeypatch.setattr(conf, "GITHUB_REVIEW_GOOGLE_API_KEY", None, raising=False)
        stub = _CredentialStub()
        assert _apply(stub) is False
        assert "api_key" not in stub._llm_kwargs

    def test_an_explicit_caller_credential_is_never_overridden(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "GITHUB_REVIEW_GOOGLE_API_KEY", "reviewer-key", raising=False)
        stub = _CredentialStub(llm_kwargs={"api_key": "caller-key"})
        assert _apply(stub) is False
        assert stub._llm_kwargs["api_key"] == "caller-key"

    def test_vertexai_agents_keep_their_own_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "GITHUB_REVIEW_GOOGLE_API_KEY", "reviewer-key", raising=False)
        stub = _CredentialStub(llm_kwargs={"vertexai": True})
        assert _apply(stub) is False
        assert "api_key" not in stub._llm_kwargs

    def test_a_non_google_llm_is_left_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "GITHUB_REVIEW_GOOGLE_API_KEY", "reviewer-key", raising=False)
        stub = _CredentialStub(llm="openai:gpt-5")
        assert _apply(stub) is False
        assert "api_key" not in stub._llm_kwargs
        assert stub.logger.warning.called

    def test_a_google_llm_string_is_recognised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "GITHUB_REVIEW_GOOGLE_API_KEY", "reviewer-key", raising=False)
        stub = _CredentialStub(llm="google:gemini-3.7-flash")
        assert _apply(stub) is True
        assert stub._llm_kwargs["api_key"] == "reviewer-key"

    def test_the_key_value_is_never_logged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(conf, "GITHUB_REVIEW_GOOGLE_API_KEY", "s3cr3t-key", raising=False)
        stub = _CredentialStub()
        _apply(stub)
        logged = " ".join(str(call) for call in stub.logger.mock_calls)
        assert "s3cr3t-key" not in logged


class TestCIPermissionDenials:
    """A token that cannot see the checks must never produce a free pass.

    Reproduces the live 403 on ``/check-runs`` ("Resource not accessible by
    personal access token") that a fine-grained PAT without the *Checks*
    permission returns.
    """

    _REASON = (
        "check_runs denied (needs 'Checks' (Read-only) on a fine-grained PAT, or a classic PAT with the 'repo' scope)"
    )

    def _approved(self) -> PRReviewResult:
        return PRReviewResult(jira_key="NAV-1", discrepancies=[], summary="s", approve=True)

    def test_summarize_honours_the_payloads_own_availability(self) -> None:
        summary = GitHubReviewer._summarize_checks(
            {"available": False, "denied": ["check_runs", "commit_statuses"], "reason": "both refused"}
        )
        assert summary.available is False
        assert summary.denied == ["check_runs", "commit_statuses"]
        assert summary.reason == "both refused"

    def test_summarize_keeps_a_partial_picture_usable(self) -> None:
        summary = GitHubReviewer._summarize_checks(
            {
                "checks": [{"name": "ci/jenkins", "state": "success"}],
                "total": 1,
                "success": 1,
                "available": True,
                "denied": ["check_runs"],
                "reason": self._REASON,
            }
        )
        assert (summary.available, summary.declared) == (True, True)
        assert summary.denied == ["check_runs"]
        assert summary.success == 1

    def test_zero_visible_checks_behind_a_denial_defers(self) -> None:
        """The regression this class exists for.

        An Actions-only repo whose ``check-runs`` endpoint is denied reports
        zero checks. That is NOT "this repo has no CI" — the evidence exists
        and is invisible — so the verdict must defer instead of approving.
        """
        r = _wire_reviewer()
        checks = GitHubReviewer._summarize_checks(
            {"checks": [], "total": 0, "available": True, "denied": ["check_runs"], "reason": self._REASON}
        )
        assert checks.declared is False
        verdict = r._merge_verdict(self._approved(), checks)
        assert (verdict.mergeable, verdict.defer) == (False, True)
        assert verdict.reasons == []
        assert any("not visible to this token" in w or "visible to this token" in w for w in verdict.warnings)
        assert any("'Checks' (Read-only)" in w for w in verdict.warnings)

    def test_require_checks_does_not_turn_a_denial_into_a_blocker(self) -> None:
        """Requiring CI must not punish a developer for a missing token scope."""
        r = _wire_reviewer()
        r.require_checks = True
        checks = GitHubReviewer._summarize_checks(
            {"checks": [], "total": 0, "available": True, "denied": ["check_runs"], "reason": self._REASON}
        )
        verdict = r._merge_verdict(self._approved(), checks)
        assert (verdict.mergeable, verdict.defer) == (False, True)
        assert verdict.reasons == []

    def test_a_partial_picture_still_approves_but_says_so(self) -> None:
        r = _wire_reviewer()
        checks = GitHubReviewer._summarize_checks(
            {
                "checks": [{"name": "pytest", "state": "success"}],
                "total": 1,
                "success": 1,
                "available": True,
                "denied": ["commit_statuses"],
                "reason": "commit_statuses denied (needs 'Commit statuses' (Read-only) on a fine-grained PAT)",
            }
        )
        verdict = r._merge_verdict(self._approved(), checks)
        assert (verdict.mergeable, verdict.defer) == (True, False)
        assert any("part of the CI picture is missing" in w for w in verdict.warnings)

    def test_genuinely_absent_ci_is_unaffected(self) -> None:
        """Nothing denied + nothing declared keeps the old warn-only behaviour."""
        r = _wire_reviewer()
        checks = GitHubReviewer._summarize_checks({"checks": [], "total": 0})
        verdict = r._merge_verdict(self._approved(), checks)
        assert (verdict.mergeable, verdict.defer) == (True, False)
        assert any("no CI checks" in w for w in verdict.warnings)

    def test_the_checks_line_names_the_denial(self) -> None:
        r = _wire_reviewer()
        empty = GitHubReviewer._summarize_checks(
            {"checks": [], "total": 0, "available": True, "denied": ["check_runs"], "reason": self._REASON}
        )
        partial = GitHubReviewer._summarize_checks(
            {
                "checks": [{"name": "pytest", "state": "success"}],
                "total": 1,
                "success": 1,
                "available": True,
                "denied": ["check_runs"],
                "reason": self._REASON,
            }
        )
        assert "check_runs denied to this token" in r._format_checks_line(empty)
        assert "check_runs denied" in r._format_checks_line(partial)

    async def test_the_deferred_comment_names_the_missing_permission(self) -> None:
        """The operator must read the fix in the PR, not only in the logs."""
        r = _wire_strict(
            approve=True,
            checks_raw={
                "checks": [],
                "total": 0,
                "available": True,
                "denied": ["check_runs"],
                "reason": self._REASON,
            },
        )
        out = await r.strict_review_pull_request(dict(_PAYLOAD))
        assert out["status"] == "deferred"
        r.git_toolkit.convert_pr_to_draft.assert_not_awaited()
        body = r.git_toolkit.submit_pr_review.await_args.kwargs["body"]
        assert "'Checks' (Read-only)" in body
        assert "neither approved" in body


class TestDeferredReviewReportsTheComparison:
    """A deferred verdict must still report what the review found.

    The ticket comparison DID finish; only the CI verdict is unknown. An
    earlier version printed nothing but the CI cause, which threw away the
    valuable half of the review.
    """

    async def test_the_comment_leads_with_the_acceptance_criteria(self) -> None:
        r = _wire_strict(
            approve=True,
            discrepancies=[Discrepancy(criterion="AC3", issue="no docstring on the new tool", severity="minor")],
            checks_raw=_checks(success=1, pending=2),
        )
        r._ask_llm_for_review = AsyncMock(
            return_value=PRReviewResult(
                jira_key="NAV-10333",
                discrepancies=[Discrepancy(criterion="AC3", issue="no docstring", severity="minor")],
                summary="Adds the endpoint and its tests; matches AC1 and AC2.",
                approve=True,
            )
        )
        out = await r.strict_review_pull_request(dict(_PAYLOAD))
        assert out["status"] == "deferred"
        body = r.git_toolkit.submit_pr_review.await_args.kwargs["body"]

        # The comparison, not just the CI excuse.
        assert "### Comparison against the ticket" in body
        assert "Every acceptance criterion is addressed" in body
        assert "matches AC1 and AC2" in body
        assert "[MINOR] AC3" in body
        # And then why there is no verdict yet.
        assert "### Why the verdict is deferred" in body
        assert "still running" in body
        assert "neither approved nor converted to a draft" in body
        # The comparison section comes first.
        assert body.index("Comparison against the ticket") < body.index("Why the verdict is deferred")

    async def test_the_comment_says_so_when_nothing_was_found(self) -> None:
        r = _wire_strict(approve=True, checks_raw=_checks(success=1, pending=1))
        out = await r.strict_review_pull_request(dict(_PAYLOAD))
        assert out["status"] == "deferred"
        body = r.git_toolkit.submit_pr_review.await_args.kwargs["body"]
        assert "No discrepancy was found" in body

    async def test_the_cause_keeps_ci_capitalized(self) -> None:
        """``str.capitalize()`` would print "Ci status could not be read"."""
        r = _wire_strict(approve=True, checks_error=RuntimeError("403 denied"))
        await r.strict_review_pull_request(dict(_PAYLOAD))
        body = r.git_toolkit.submit_pr_review.await_args.kwargs["body"]
        assert "The CI status could not be read" in body
        assert "Ci status" not in body

    async def test_the_telegram_reply_carries_the_verdict_and_findings(self) -> None:
        r = _wire_strict(approve=True, checks_raw=_checks(success=1, pending=2))
        r._ask_llm_for_review = AsyncMock(
            return_value=PRReviewResult(
                jira_key="NAV-10333",
                discrepancies=[Discrepancy(criterion="AC3", issue="no docstring", severity="minor")],
                summary="Adds the endpoint and its tests.",
                approve=True,
            )
        )
        r.git_toolkit.get_pull_request = AsyncMock(
            return_value={
                "title": "feat: thing",
                "body": "Implements NAV-10333",
                "state": "open",
                "html_url": "u",
                "head": {"sha": "s"},
                "user": {"login": "o"},
            }
        )
        reply = await r.review_pr("42")
        assert reply.startswith("⏳")
        assert "meets" in reply
        assert "Adds the endpoint and its tests." in reply
        assert "[MINOR] AC3" in reply
        assert "No merge verdict yet" in reply

    async def test_a_failed_review_is_reported_as_unconfirmed(self) -> None:
        """``approve=False`` with no blocker: say the criteria are unconfirmed."""
        r = _wire_reviewer()
        unconfirmed = PRReviewResult(
            jira_key="NAV-1",
            discrepancies=[],
            summary="LLM review failed: timeout",
            approve=False,
        )
        section = "\n".join(r._format_findings_section(unconfirmed))
        assert "did not confirm" in section
        assert "LLM review failed: timeout" in section

    async def test_a_finding_is_not_repeated_under_non_blocking(self) -> None:
        """A minor finding is both a finding and a warning — print it once."""
        r = _wire_strict(approve=True, checks_raw=_checks(success=1, pending=1))
        r._ask_llm_for_review = AsyncMock(
            return_value=PRReviewResult(
                jira_key="NAV-1",
                discrepancies=[Discrepancy(criterion="AC4", issue="no audit entry", severity="minor")],
                summary="s",
                approve=True,
            )
        )
        r.git_toolkit.get_pull_request = AsyncMock(
            return_value={
                "title": "t",
                "body": "Implements NAV-1",
                "state": "open",
                "html_url": "u",
                "head": {"sha": "s"},
                "user": {"login": "o"},
            }
        )
        reply = await r.review_pr("42")
        assert reply.count("[MINOR] AC4") == 1
