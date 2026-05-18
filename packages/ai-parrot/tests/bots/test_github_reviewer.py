"""Unit tests for GitHubReviewer pure helpers.

Avoids instantiating the full ``Agent`` MRO (which requires the Cython
``parrot.utils.types`` extension at import time) by exercising the pure /
static helpers directly. End-to-end review flow is covered by integration
tests.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.github_reviewer import (
    Discrepancy,
    GitHubReviewer,
    PRReviewResult,
    WeeklyActivitySummary,
    WeeklyLLMSummarizationError,
    _ContributorWindowSummary,
    _flatten_adf,
)
from parrot_tools.gittoolkit import (
    ContributorStats,
    ContributorWeek,
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
        self._jira_fields = ",".join(
            sorted({"summary", "description", "status", ac_field_id})
        )
        self._ticket_key_regex = re.compile(
            rf"\b{re.escape(jira_project)}-\d+\b"
        )
        self._reviewed_shas: Dict[Any, str] = {}
        self._no_ticket_notified: set = set()

    # Bind the real helpers we want to test.
    _extract_ticket_key = GitHubReviewer._extract_ticket_key
    _format_review_body = GitHubReviewer._format_review_body
    _format_alert_message = GitHubReviewer._format_alert_message
    _format_no_ticket_comment = GitHubReviewer._format_no_ticket_comment
    _clamp = GitHubReviewer._clamp
    _fetch_ticket = GitHubReviewer._fetch_ticket
    _notify_missing_ticket = GitHubReviewer._notify_missing_ticket
    _ask_llm_for_review = GitHubReviewer._ask_llm_for_review
    review_pull_request = GitHubReviewer.review_pull_request
    handle_hook_event = GitHubReviewer.handle_hook_event
    # Class-level constants needed by some helpers.
    _WEEKLY_LLM_SYSTEM_PROMPT = GitHubReviewer._WEEKLY_LLM_SYSTEM_PROMPT


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
                                    "content": [
                                        {"type": "text", "text": "one"}
                                    ],
                                }
                            ],
                        },
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": "two"}
                                    ],
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

        async def fake_ask(*, payload, ticket_key, ticket, diff_text,
                           diff_truncated, diff_available):
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
        r._fetch_ticket = AsyncMock(
            return_value={"fields": {"summary": "S", "description": "D"}}
        )
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
        body = r._format_no_ticket_comment(
            {"author": "octocat", "pr_title": "x", "pr_body": ""}
        )
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
        routes = [
            r for r in app.router.routes()
            if r.resource.canonical == "/api/v1/hooks/github"
        ]
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
        summary = r._build_weekly_summary(
            contributors, code_freq, threshold_weeks=3, now=NOW
        )
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
        summary = r._build_weekly_summary(
            contributors, code_freq, threshold_weeks=3, now=NOW
        )
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
        summary = r._build_weekly_summary(
            contributors, code_freq, threshold_weeks=3, now=NOW
        )
        assert len(summary.contributors_silent) == 0

    def test_excludes_anonymous_contributors(self):
        """Contributors with login=None are excluded from both lists."""
        r = _minimal_reviewer()
        anon = ContributorStats(
            login=None,
            total_commits=5,
            weeks=[
                ContributorWeek(
                    week_start=W_CURR, commits=5, additions=100, deletions=10
                )
            ],
        )
        code_freq = [_cf(W_CURR, 100, 10)]
        summary = r._build_weekly_summary(
            [anon], code_freq, threshold_weeks=3, now=NOW
        )
        assert summary.contributors_active == []
        assert summary.contributors_silent == []

    def test_top_n_truncates_active_list(self):
        """Active list is capped at top_n; silent list is uncapped."""
        r = _minimal_reviewer()
        contributors = [
            _cs(f"u{i}", [(W_CURR, 30 - i, 100, 10)])
            for i in range(15)
        ]
        code_freq = [_cf(W_CURR, 500, 100)]
        summary = r._build_weekly_summary(
            contributors, code_freq, threshold_weeks=3, top_n=10, now=NOW
        )
        assert len(summary.contributors_active) == 10

    def test_delta_from_code_freq(self):
        """prev_total_additions comes from code_freq at W_PREV."""
        r = _minimal_reviewer()
        contributors = [_cs("alice", [(W_CURR, 5, 100, 20), (W_PREV, 7, 200, 50)])]
        code_freq = [
            _cf(W_CURR, 100, 20),
            _cf(W_PREV, 300, 80),
        ]
        summary = r._build_weekly_summary(
            contributors, code_freq, threshold_weeks=3, now=NOW
        )
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
        summary = r._build_weekly_summary(
            contributors, code_freq, threshold_weeks=3, now=NOW
        )
        logins = [c.login for c in summary.contributors_active]
        assert logins == ["bob", "charlie", "alice"]

    def test_empty_contributors_raises(self):
        """Raises ValueError when both contributors and code_freq are empty."""
        r = _minimal_reviewer()
        with pytest.raises(ValueError, match="Cannot determine reporting window"):
            r._build_weekly_summary([], [], threshold_weeks=3, now=NOW)


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
        assert "42" in message           # pr_number
        assert "count=5" in message      # count
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
            assert expected_name in registered_names, (
                f"Expected tool '{expected_name}' in r.tools, got: {registered_names}"
            )


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
            "customfield_10100": (
                "AC #1: validate email format\n"
                "AC #2: return 400 on invalid email"
            ),
        }
    }

    def _build_integration_reviewer(
        self, max_tool_calls: int = 3
    ) -> Any:
        """Build a reviewer stub wired for integration-style tests."""
        r = _wire_reviewer_with_tool_cap(max_tool_calls=max_tool_calls)
        r._reviewed_shas = {}
        r._no_ticket_notified = set()
        # Bind review_pull_request and _ask_llm_for_review onto stub.
        r.review_pull_request = GitHubReviewer.review_pull_request.__get__(
            r, type(r)
        )
        r._ask_llm_for_review = GitHubReviewer._ask_llm_for_review.__get__(
            r, type(r)
        )
        r._extract_ticket_key = GitHubReviewer._extract_ticket_key.__get__(
            r, type(r)
        )
        r._clamp = GitHubReviewer._clamp.__get__(r, type(r))
        r._format_review_body = GitHubReviewer._format_review_body.__get__(
            r, type(r)
        )
        r._notify_telegram_alert = GitHubReviewer._notify_telegram_alert.__get__(
            r, type(r)
        )
        r._notify_missing_ticket = GitHubReviewer._notify_missing_ticket.__get__(
            r, type(r)
        )
        r._get_telegram_bot = GitHubReviewer._get_telegram_bot.__get__(
            r, type(r)
        )
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
                "diff --git a/login.py b/login.py\n"
                "+def login(email):\n"
                "+    return 200\n",
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
        fake_response = _make_fake_response(
            expected_result, tool_calls=[tool_call]
        )

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
