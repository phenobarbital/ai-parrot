"""Unit tests for GitHubReviewer pure helpers.

Avoids instantiating the full ``Agent`` MRO (which requires the Cython
``parrot.utils.types`` extension at import time) by exercising the pure /
static helpers directly. End-to-end review flow is covered by integration
tests.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from parrot.bots.github_reviewer import (
    Discrepancy,
    GitHubReviewer,
    PRReviewResult,
    _flatten_adf,
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

    # Bind the real helpers we want to test.
    _extract_ticket_key = GitHubReviewer._extract_ticket_key
    _format_review_body = GitHubReviewer._format_review_body
    _format_alert_message = GitHubReviewer._format_alert_message
    _clamp = GitHubReviewer._clamp
    _fetch_ticket = GitHubReviewer._fetch_ticket
    review_pull_request = GitHubReviewer.review_pull_request
    handle_hook_event = GitHubReviewer.handle_hook_event


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
    def test_handle_hook_event_matches_lowercased_repo(self):
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
        out = asyncio.run(r.handle_hook_event(event))
        assert out == {"status": "stub"}
        assert captured and captured[0]["pr_number"] == 1

    def test_handle_hook_event_rejects_other_repo(self):
        r = _wire_reviewer(repository="owner/repo")
        r.review_pull_request = MagicMock()  # type: ignore[assignment]
        event = _StubEvent(
            "github.pr_opened",
            {"repository": "someone/else", "pr_number": 1},
        )
        out = asyncio.run(r.handle_hook_event(event))
        assert out is None
        r.review_pull_request.assert_not_called()

    def test_handle_hook_event_ignores_unrelated_events(self):
        r = _wire_reviewer()
        r.review_pull_request = MagicMock()  # type: ignore[assignment]
        out = asyncio.run(
            r.handle_hook_event(_StubEvent("github.pr_closed", {}))
        )
        assert out is None


class TestReviewPullRequestDedup:
    def test_already_reviewed_short_circuits(self):
        r = _wire_reviewer()
        r._reviewed_shas[("owner/repo", 42)] = "abc123"

        # These shouldn't even be reached:
        r._fetch_ticket = MagicMock()  # type: ignore[assignment]
        r._fetch_diff = MagicMock()  # type: ignore[assignment]

        out = asyncio.run(
            r.review_pull_request(
                {
                    "repository": "owner/repo",
                    "pr_number": 42,
                    "head_sha": "abc123",
                    "pr_body": "Implements NAV-1",
                    "pr_title": "",
                }
            )
        )
        assert out["status"] == "already_reviewed"
        assert out["head_sha"] == "abc123"
        r._fetch_ticket.assert_not_called()
        r._fetch_diff.assert_not_called()

    def test_new_sha_records_after_review(self):
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

        out = asyncio.run(
            r.review_pull_request(
                {
                    "repository": "Owner/Repo",
                    "pr_number": 9,
                    "head_sha": "deadbeef",
                    "pr_body": "Fixes NAV-9",
                    "pr_title": "",
                }
            )
        )
        assert out["status"] == "reviewed"
        assert out["approve"] is True
        assert r._reviewed_shas[("owner/repo", 9)] == "deadbeef"


class TestFetchTicketFields:
    def test_passes_configured_ac_field(self):
        """Override JIRA_ACCEPTANCE_CRITERIA_FIELD must be reflected in
        the fields= argument sent to Jira."""
        r = _wire_reviewer(ac_field_id="customfield_99999")

        captured: Dict[str, Any] = {}

        async def fake_get(**kwargs):
            captured.update(kwargs)
            return {"status": "ok", "data": {"fields": {}}}

        r.jira_toolkit.jira_get_issue = fake_get

        asyncio.run(r._fetch_ticket("NAV-1"))
        assert "customfield_99999" in captured["fields"]
        # Stable field list is sorted, so summary/description/status remain.
        for f in ("summary", "description", "status"):
            assert f in captured["fields"]

    def test_returns_none_when_envelope_not_ok(self):
        r = _wire_reviewer()

        async def fake_get(**kwargs):
            return {"status": "error", "data": None}

        r.jira_toolkit.jira_get_issue = fake_get
        assert asyncio.run(r._fetch_ticket("NAV-1")) is None

    def test_returns_none_when_toolkit_missing(self):
        r = _wire_reviewer()
        r.jira_toolkit = None
        assert asyncio.run(r._fetch_ticket("NAV-1")) is None


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

    def test_dispatcher_fans_out(self):
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
        asyncio.run(hook._callback(event))

        assert received == ["a:github.pr_opened", "b:github.pr_opened"]

    def test_dispatcher_isolates_listener_errors(self):
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
        asyncio.run(hook._callback(event))
        assert survived == ["ok"]
