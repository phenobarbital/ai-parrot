"""Unit tests for GitHubReviewer pure helpers.

Avoids instantiating the full ``Agent`` MRO (which requires the Cython
``parrot.utils.types`` extension at import time) by exercising the pure /
static helpers directly. End-to-end review flow is covered by integration
tests.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from parrot.bots.github_reviewer import (
    Discrepancy,
    GitHubReviewer,
    PRReviewResult,
)


class _MinimalReviewer:
    """Cheap stand-in that reuses real helpers but skips Agent.__init__."""

    def __init__(
        self,
        repository: str = "owner/repo",
        jira_project: str = "NAV",
    ) -> None:
        self.repository = repository
        self.jira_project = jira_project
        self._ticket_key_regex = re.compile(
            rf"\b{re.escape(jira_project)}-\d+\b"
        )

    # Bind the real helpers we want to test.
    _extract_ticket_key = GitHubReviewer._extract_ticket_key
    _format_review_body = GitHubReviewer._format_review_body
    _format_alert_message = GitHubReviewer._format_alert_message


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
