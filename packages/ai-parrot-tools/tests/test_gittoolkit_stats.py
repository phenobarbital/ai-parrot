"""Unit tests for GitToolkit stats polling helper and stats tools.

Tests for TASK-1210 (_get_stats_with_polling) and TASK-1211 (stats tools).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from parrot_tools.gittoolkit import GitToolkit, GitToolkitError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_response(status_code: int, body: str = "") -> MagicMock:
    """Create a mock requests.Response with the given status code."""
    r = MagicMock()
    r.status_code = status_code
    r.text = body
    r.json.return_value = {} if body == "" else None
    return r


def _toolkit() -> GitToolkit:
    """Return a GitToolkit configured with a default repository and token."""
    return GitToolkit(
        default_repository="owner/repo",
        github_token="tok",
    )


# ---------------------------------------------------------------------------
# TASK-1210: _get_stats_with_polling
# ---------------------------------------------------------------------------


class TestStatsPolling:
    """Tests for GitToolkit._get_stats_with_polling."""

    def test_returns_immediately_on_200(self):
        """Single 200 response returns immediately without retrying."""
        with patch("parrot_tools.gittoolkit.requests.get") as m:
            m.return_value = _mk_response(200, '{"ok": true}')
            resp = GitToolkit._get_stats_with_polling(
                "https://api.github.com/x", "tok", initial_delay=0.01
            )
            assert resp.status_code == 200
            assert m.call_count == 1

    def test_handles_202_then_200(self):
        """Two 202 responses then 200 returns the 200 response."""
        with patch("parrot_tools.gittoolkit.requests.get") as m, \
             patch("parrot_tools.gittoolkit.time.sleep"):
            m.side_effect = [
                _mk_response(202),
                _mk_response(202),
                _mk_response(200, "[]"),
            ]
            resp = GitToolkit._get_stats_with_polling(
                "https://api.github.com/x", "tok", initial_delay=0.01
            )
            assert resp.status_code == 200
            assert m.call_count == 3

    def test_gives_up_after_max_retries(self):
        """All 202 responses exhaust retries and raise GitToolkitError."""
        with patch("parrot_tools.gittoolkit.requests.get") as m, \
             patch("parrot_tools.gittoolkit.time.sleep"):
            m.return_value = _mk_response(202)
            with pytest.raises(GitToolkitError, match="returned 202 after"):
                GitToolkit._get_stats_with_polling(
                    "https://api.github.com/x", "tok",
                    max_retries=2, initial_delay=0.01,
                )
            # max_retries=2 means 3 calls total (attempts 0, 1, 2)
            assert m.call_count == 3

    def test_non_202_non_200_short_circuits(self):
        """A 404 response raises immediately without retrying."""
        with patch("parrot_tools.gittoolkit.requests.get") as m:
            m.return_value = _mk_response(404, "Not Found")
            with pytest.raises(GitToolkitError, match="failed with status 404"):
                GitToolkit._get_stats_with_polling(
                    "https://api.github.com/x", "tok", initial_delay=0.01
                )
            assert m.call_count == 1

    def test_exponential_backoff_delays(self):
        """Verify sleep is called with exponential backoff values."""
        with patch("parrot_tools.gittoolkit.requests.get") as m, \
             patch("parrot_tools.gittoolkit.time.sleep") as sleep_mock:
            # 3 retries: will call sleep twice before the final 202 → error
            m.return_value = _mk_response(202)
            with pytest.raises(GitToolkitError):
                GitToolkit._get_stats_with_polling(
                    "https://api.github.com/x", "tok",
                    max_retries=2, initial_delay=1.0, max_delay=60.0,
                )
            # sleep should be called for attempt 0 and attempt 1
            assert sleep_mock.call_count == 2
            # attempt 0: min(1.0 * 2^0, 60) = 1.0
            assert sleep_mock.call_args_list[0][0][0] == 1.0
            # attempt 1: min(1.0 * 2^1, 60) = 2.0
            assert sleep_mock.call_args_list[1][0][0] == 2.0


# ---------------------------------------------------------------------------
# TASK-1211: get_contributor_stats
# ---------------------------------------------------------------------------


class TestGetContributorStats:
    """Tests for GitToolkit.get_contributor_stats."""

    def test_parses_weeks(self):
        """Contributor stats are parsed into typed ContributorStats models."""
        from parrot_tools.gittoolkit import ContributorStats, ContributorWeek

        canned = [{
            "author": {"login": "alice", "avatar_url": "x"},
            "total": 27,
            "weeks": [
                {"w": 1716422400, "a": 100, "d": 20, "c": 4},
                {"w": 1715817600, "a": 200, "d": 50, "c": 7},
            ],
        }]
        with patch.object(GitToolkit, "_get_stats_with_polling") as m:
            m.return_value.json.return_value = canned
            out = asyncio.run(_toolkit().get_contributor_stats())
        assert len(out) == 1
        assert out[0].login == "alice"
        assert out[0].total_commits == 27
        # 1716422400 = 2024-05-23 00:00 UTC
        assert out[0].weeks[0].week_start == datetime(
            2024, 5, 23, 0, 0, tzinfo=timezone.utc
        )
        assert out[0].weeks[0].commits == 4
        assert out[0].weeks[0].additions == 100
        assert out[0].weeks[0].deletions == 20

    def test_anonymous_author(self):
        """Contributor with author=None produces login=None, not a crash."""
        canned = [{
            "author": None,
            "total": 3,
            "weeks": [{"w": 1716422400, "a": 5, "d": 0, "c": 1}],
        }]
        with patch.object(GitToolkit, "_get_stats_with_polling") as m:
            m.return_value.json.return_value = canned
            out = asyncio.run(_toolkit().get_contributor_stats())
        assert len(out) == 1
        assert out[0].login is None
        assert out[0].avatar_url is None
        assert out[0].total_commits == 3

    def test_empty_response(self):
        """Empty list from GitHub returns empty typed list."""
        with patch.object(GitToolkit, "_get_stats_with_polling") as m:
            m.return_value.json.return_value = []
            out = asyncio.run(_toolkit().get_contributor_stats())
        assert out == []

    def test_datetimes_are_utc_aware(self):
        """All returned datetime fields are timezone-aware UTC."""
        canned = [{
            "author": {"login": "bob"},
            "total": 5,
            "weeks": [{"w": 1716422400, "a": 10, "d": 5, "c": 2}],
        }]
        with patch.object(GitToolkit, "_get_stats_with_polling") as m:
            m.return_value.json.return_value = canned
            out = asyncio.run(_toolkit().get_contributor_stats())
        assert out[0].weeks[0].week_start.tzinfo is not None
        assert out[0].weeks[0].week_start.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# TASK-1211: get_code_frequency
# ---------------------------------------------------------------------------


class TestGetCodeFrequency:
    """Tests for GitToolkit.get_code_frequency."""

    def test_normalizes_deletions_to_positive(self):
        """GitHub returns negative deletion counts; model stores them as absolute."""
        from parrot_tools.gittoolkit import WeeklyCodeFrequency

        canned = [[1716422400, 100, -45]]
        with patch.object(GitToolkit, "_get_stats_with_polling") as m:
            m.return_value.json.return_value = canned
            out = asyncio.run(_toolkit().get_code_frequency())
        assert len(out) == 1
        assert out[0].additions == 100
        assert out[0].deletions == 45  # absolute value
        assert out[0].week_start.tzinfo is timezone.utc

    def test_week_start_is_utc_aware(self):
        """WeeklyCodeFrequency.week_start is timezone-aware UTC."""
        canned = [[1716422400, 50, -10]]
        with patch.object(GitToolkit, "_get_stats_with_polling") as m:
            m.return_value.json.return_value = canned
            out = asyncio.run(_toolkit().get_code_frequency())
        assert out[0].week_start == datetime(2024, 5, 23, 0, 0, tzinfo=timezone.utc)

    def test_positive_deletions_unchanged(self):
        """If GitHub ever returns positive deletions, store them as-is."""
        canned = [[1716422400, 200, 30]]
        with patch.object(GitToolkit, "_get_stats_with_polling") as m:
            m.return_value.json.return_value = canned
            out = asyncio.run(_toolkit().get_code_frequency())
        assert out[0].deletions == 30

    def test_multiple_weeks(self):
        """Multiple entries are all parsed."""
        canned = [
            [1716422400, 100, -45],
            [1715817600, 200, -80],
        ]
        with patch.object(GitToolkit, "_get_stats_with_polling") as m:
            m.return_value.json.return_value = canned
            out = asyncio.run(_toolkit().get_code_frequency())
        assert len(out) == 2
        assert out[0].additions == 100
        assert out[1].additions == 200


# ---------------------------------------------------------------------------
# TASK-1211: get_weekly_commit_activity
# ---------------------------------------------------------------------------


class TestGetWeeklyCommitActivity:
    """Tests for GitToolkit.get_weekly_commit_activity."""

    def test_returns_raw_dicts(self):
        """Weekly commit activity returns a list of raw dicts."""
        canned = [
            {"days": [0, 3, 26, 20, 39, 1, 0], "total": 89, "week": 1336280400},
            {"days": [1, 2, 3, 4, 5, 6, 7], "total": 28, "week": 1336885200},
        ]
        with patch.object(GitToolkit, "_get_stats_with_polling") as m:
            m.return_value.json.return_value = canned
            out = asyncio.run(_toolkit().get_weekly_commit_activity())
        assert isinstance(out, list)
        assert len(out) == 2
        assert out[0]["total"] == 89
        assert out[1]["total"] == 28

    def test_empty_response(self):
        """Empty list from GitHub returns empty list."""
        with patch.object(GitToolkit, "_get_stats_with_polling") as m:
            m.return_value.json.return_value = []
            out = asyncio.run(_toolkit().get_weekly_commit_activity())
        assert out == []
