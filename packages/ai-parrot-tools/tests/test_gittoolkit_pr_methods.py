"""Unit tests for the PR-review helpers added to GitToolkit.

Network calls are mocked at ``requests.request`` so the tests stay hermetic.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from parrot_tools.gittoolkit import GitToolkit, GitToolkitError


def _make_response(
    status_code: int = 200, json_data=None, text: str = "", headers=None
):
    class _Resp:
        def __init__(self):
            self.status_code = status_code
            self._json = json_data
            self.text = text
            self.headers = headers or {}

        def json(self):
            if self._json is None:
                raise ValueError("no json body")
            return self._json

    return _Resp()


def _toolkit() -> GitToolkit:
    return GitToolkit(default_repository="owner/repo", github_token="fake-token")


class TestGetPullRequest:
    def test_returns_json(self):
        toolkit = _toolkit()
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(200, json_data={"number": 42}),
        ) as mocked:
            result = asyncio.run(toolkit.get_pull_request(pr_number=42))
        assert result == {"number": 42}
        assert mocked.call_args.args[0] == "GET"
        assert "/repos/owner/repo/pulls/42" in mocked.call_args.args[1]


class TestListPullRequests:
    def test_passes_state_and_per_page(self):
        toolkit = _toolkit()
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(
                200, json_data=[{"number": 1}, {"number": 2}]
            ),
        ) as mocked:
            result = asyncio.run(
                toolkit.list_pull_requests(state="open", per_page=50)
            )
        assert len(result) == 2
        assert mocked.call_args.kwargs["params"] == {
            "state": "open",
            "per_page": 50,
        }

    def test_clamps_per_page_to_100(self):
        toolkit = _toolkit()
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(200, json_data=[]),
        ) as mocked:
            asyncio.run(toolkit.list_pull_requests(per_page=9999))
        assert mocked.call_args.kwargs["params"]["per_page"] == 100


class TestGetPullRequestDiff:
    def test_truncates_when_over_max_bytes(self):
        diff = "diff --git a/x b/x\n" + ("+" * 1000) + "\n"
        toolkit = _toolkit()
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(200, text=diff),
        ):
            result = asyncio.run(
                toolkit.get_pull_request_diff(pr_number=7, max_bytes=100)
            )
        assert result["truncated"] is True
        assert len(result["diff"]) == 100

    def test_does_not_truncate_when_smaller(self):
        diff = "tiny diff"
        toolkit = _toolkit()
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(200, text=diff),
        ):
            result = asyncio.run(
                toolkit.get_pull_request_diff(pr_number=7, max_bytes=10_000)
            )
        assert result["truncated"] is False
        assert result["diff"] == diff


class TestSubmitPRReview:
    def test_request_changes_payload(self):
        toolkit = _toolkit()
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(
                200,
                json_data={"id": 5, "state": "CHANGES_REQUESTED", "html_url": "u"},
            ),
        ) as mocked:
            result = asyncio.run(
                toolkit.submit_pr_review(
                    pr_number=12, event="REQUEST_CHANGES", body="nope"
                )
            )
        assert result == {"id": 5, "state": "CHANGES_REQUESTED", "html_url": "u"}
        assert mocked.call_args.kwargs["json"] == {
            "event": "REQUEST_CHANGES",
            "body": "nope",
        }
        assert "/reviews" in mocked.call_args.args[1]


class TestAddPRComment:
    def test_posts_to_issues_endpoint(self):
        toolkit = _toolkit()
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(
                201, json_data={"id": 99, "html_url": "u"}
            ),
        ) as mocked:
            asyncio.run(toolkit.add_pr_comment(pr_number=3, body="hi"))
        assert "/issues/3/comments" in mocked.call_args.args[1]
        assert mocked.call_args.kwargs["json"] == {"body": "hi"}


class TestEnsureWebhook:
    _LIST_URL = "https://api.github.com/repos/owner/repo/hooks"

    def test_creates_when_absent(self):
        toolkit = _toolkit()

        def fake_request(method, url, **kwargs):
            if method == "GET" and url == self._LIST_URL:
                return _make_response(200, json_data=[])
            if method == "POST" and url == self._LIST_URL:
                return _make_response(201, json_data={"id": 1})
            raise AssertionError(f"Unexpected call: {method} {url}")

        with patch(
            "parrot_tools.gittoolkit.requests.request", side_effect=fake_request
        ):
            result = asyncio.run(
                toolkit.ensure_webhook(
                    webhook_url="https://example.com/hook", secret="sss"
                )
            )
        assert result["status"] == "created"

    def test_returns_already_exists_when_present(self):
        toolkit = _toolkit()
        existing = [
            {
                "id": 7,
                "config": {"url": "https://example.com/hook"},
            }
        ]
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(200, json_data=existing),
        ):
            result = asyncio.run(
                toolkit.ensure_webhook(webhook_url="https://example.com/hook")
            )
        assert result["status"] == "already_exists"
        assert result["hook"]["id"] == 7

    def test_handles_no_permission_on_list(self):
        toolkit = _toolkit()
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(403, text="Forbidden"),
        ):
            result = asyncio.run(
                toolkit.ensure_webhook(webhook_url="https://example.com/hook")
            )
        assert result["status"] == "no_permission"
        assert result["operation"] == "list"
        assert result["status_code"] == 403

    def test_no_permission_carries_github_context(self):
        """A 403 on the list call surfaces GitHub's message and the header."""
        toolkit = _toolkit()
        denial = _make_response(
            403,
            json_data={"message": "Resource not accessible by personal access token"},
            text="{}",
            headers={"x-accepted-github-permissions": "repository_hooks=write"},
        )
        with patch(
            "parrot_tools.gittoolkit.requests.request", return_value=denial
        ):
            result = asyncio.run(
                toolkit.ensure_webhook(webhook_url="https://example.com/hook")
            )
        assert result["status"] == "no_permission"
        assert result["api_message"] == (
            "Resource not accessible by personal access token"
        )
        assert result["required_permission"] == "repository_hooks=write"

    def test_non_permission_status_is_error(self):
        """A 500 is an error, not a permission problem, even on /hooks."""
        toolkit = _toolkit()
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(500, text="boom"),
        ):
            result = asyncio.run(
                toolkit.ensure_webhook(webhook_url="https://example.com/hook")
            )
        assert result["status"] == "error"
        assert result["status_code"] == 500

    def test_handles_no_permission_on_create(self):
        toolkit = _toolkit()

        def fake_request(method, url, **kwargs):
            if method == "GET":
                return _make_response(200, json_data=[])
            return _make_response(403, text="Forbidden")

        with patch(
            "parrot_tools.gittoolkit.requests.request", side_effect=fake_request
        ):
            result = asyncio.run(
                toolkit.ensure_webhook(webhook_url="https://example.com/hook")
            )
        assert result["status"] == "no_permission"
        assert result["operation"] == "create"


class TestResolveHelpers:
    def test_resolve_repository_uses_default(self):
        toolkit = _toolkit()
        assert toolkit._resolve_repository(None) == "owner/repo"

    def test_resolve_repository_raises_without_default(self):
        toolkit = GitToolkit(default_repository=None, github_token="x")
        with pytest.raises(GitToolkitError):
            toolkit._resolve_repository(None)

    def test_resolve_token_raises_without_token(self):
        toolkit = GitToolkit(default_repository="owner/repo", github_token=None)
        with pytest.raises(GitToolkitError):
            toolkit._resolve_token()


class TestClassifyCheck:
    """``_classify_check`` folds GitHub's status+conclusion pair into one word."""

    def test_completed_conclusions(self):
        assert GitToolkit._classify_check("completed", "success") == "success"
        assert GitToolkit._classify_check("completed", "failure") == "failure"
        assert GitToolkit._classify_check("completed", "timed_out") == "failure"
        assert GitToolkit._classify_check("completed", "action_required") == "failure"

    def test_neutral_and_skipped_count_as_passes(self):
        """A skipped job is not a broken one."""
        assert GitToolkit._classify_check("completed", "neutral") == "success"
        assert GitToolkit._classify_check("completed", "skipped") == "success"

    def test_in_flight_runs_are_pending(self):
        assert GitToolkit._classify_check("queued", None) == "pending"
        assert GitToolkit._classify_check("in_progress", None) == "pending"
        assert GitToolkit._classify_check("waiting", "") == "pending"

    def test_cancelled_is_pending_not_failure(self):
        """A cancelled run is usually a superseded push, not a red test."""
        assert GitToolkit._classify_check("completed", "cancelled") == "pending"

    def test_unknown_values_fall_back_to_pending(self):
        assert GitToolkit._classify_check(None, None) == "pending"
        assert GitToolkit._classify_check("completed", "something_new") == "pending"


class TestGetPRChecks:
    _RUNS = {
        "check_runs": [
            {"name": "pytest", "status": "completed", "conclusion": "success", "html_url": "u1"},
            {"name": "e2e", "status": "completed", "conclusion": "failure", "html_url": "u2"},
            {"name": "build", "status": "in_progress", "conclusion": None, "html_url": "u3"},
        ]
    }
    _STATUS = {"state": "failure", "statuses": [{"context": "ci/jenkins", "state": "success", "target_url": "u4"}]}

    def test_merges_both_github_apis(self):
        """Checks API and the legacy Commit Status API both count."""
        toolkit = _toolkit()
        responses = [
            _make_response(200, json_data=self._RUNS),
            _make_response(200, json_data=self._STATUS),
        ]
        with patch("parrot_tools.gittoolkit.requests.request", side_effect=responses) as mocked:
            result = asyncio.run(toolkit.get_pr_checks(pr_number=42, head_sha="abc123"))

        assert result["head_sha"] == "abc123"
        assert (result["success"], result["failure"], result["pending"]) == (2, 1, 1)
        assert result["total"] == 4
        assert {c["source"] for c in result["checks"]} == {"check_run", "commit_status"}
        # head_sha supplied → no extra /pulls lookup, just the two check calls.
        assert mocked.call_count == 2
        assert "/commits/abc123/check-runs" in mocked.call_args_list[0].args[1]
        assert "/commits/abc123/status" in mocked.call_args_list[1].args[1]

    def test_resolves_the_head_sha_when_not_given(self):
        toolkit = _toolkit()
        responses = [
            _make_response(200, json_data={"number": 42, "head": {"sha": "deadbeef"}}),
            _make_response(200, json_data={"check_runs": []}),
            _make_response(200, json_data={"state": "pending", "statuses": []}),
        ]
        with patch("parrot_tools.gittoolkit.requests.request", side_effect=responses) as mocked:
            result = asyncio.run(toolkit.get_pr_checks(pr_number=42))

        assert result["head_sha"] == "deadbeef"
        assert result["total"] == 0
        assert mocked.call_count == 3
        assert "/pulls/42" in mocked.call_args_list[0].args[1]

    def test_raises_when_the_head_sha_cannot_be_resolved(self):
        toolkit = _toolkit()
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(200, json_data={"number": 42}),
        ):
            with pytest.raises(GitToolkitError, match="head SHA"):
                asyncio.run(toolkit.get_pr_checks(pr_number=42))

    def test_a_commit_status_error_state_counts_as_a_failure(self):
        toolkit = _toolkit()
        responses = [
            _make_response(200, json_data={"check_runs": []}),
            _make_response(
                200,
                json_data={"state": "error", "statuses": [{"context": "deploy", "state": "error"}]},
            ),
        ]
        with patch("parrot_tools.gittoolkit.requests.request", side_effect=responses):
            result = asyncio.run(toolkit.get_pr_checks(pr_number=42, head_sha="s"))
        assert result["failure"] == 1


class TestConvertPRToDraft:
    def test_converts_an_open_pr_via_graphql(self):
        toolkit = _toolkit()
        responses = [
            _make_response(200, json_data={"number": 42, "node_id": "PR_abc", "state": "open", "draft": False}),
            _make_response(
                200,
                json_data={"data": {"convertPullRequestToDraft": {"pullRequest": {"number": 42, "isDraft": True}}}},
            ),
        ]
        with patch("parrot_tools.gittoolkit.requests.request", side_effect=responses) as mocked:
            result = asyncio.run(toolkit.convert_pr_to_draft(pr_number=42))

        assert result == {"status": "converted", "repository": "owner/repo", "pr_number": 42, "is_draft": True}
        graphql_call = mocked.call_args_list[1]
        assert graphql_call.args[1] == "https://api.github.com/graphql"
        assert graphql_call.kwargs["json"]["variables"] == {"id": "PR_abc"}
        assert "convertPullRequestToDraft" in graphql_call.kwargs["json"]["query"]

    def test_an_already_draft_pr_short_circuits(self):
        """No mutation is sent — the PR is already not mergeable."""
        toolkit = _toolkit()
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(200, json_data={"number": 42, "node_id": "x", "state": "open", "draft": True}),
        ) as mocked:
            result = asyncio.run(toolkit.convert_pr_to_draft(pr_number=42))
        assert result["status"] == "already_draft"
        assert result["is_draft"] is True
        assert mocked.call_count == 1

    def test_a_closed_pr_is_left_alone(self):
        toolkit = _toolkit()
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(
                200, json_data={"number": 42, "node_id": "x", "state": "closed", "draft": False}
            ),
        ) as mocked:
            result = asyncio.run(toolkit.convert_pr_to_draft(pr_number=42))
        assert result["status"] == "not_open"
        assert "closed" in result["message"]
        assert mocked.call_count == 1

    def test_graphql_errors_raise_even_on_http_200(self):
        """GraphQL reports failure in the body, not in the status code."""
        toolkit = _toolkit()
        responses = [
            _make_response(200, json_data={"number": 42, "node_id": "PR_abc", "state": "open", "draft": False}),
            _make_response(200, json_data={"errors": [{"message": "Resource not accessible by integration"}]}),
        ]
        with patch("parrot_tools.gittoolkit.requests.request", side_effect=responses):
            with pytest.raises(GitToolkitError, match="not accessible"):
                asyncio.run(toolkit.convert_pr_to_draft(pr_number=42))

    def test_a_missing_node_id_raises(self):
        toolkit = _toolkit()
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(200, json_data={"number": 42, "state": "open", "draft": False}),
        ):
            with pytest.raises(GitToolkitError, match="node_id"):
                asyncio.run(toolkit.convert_pr_to_draft(pr_number=42))


class TestGetPRChecksPermissionDenials:
    """The two CI APIs sit behind independent token permissions."""

    _DENIED = {"message": "Resource not accessible by personal access token", "status": "403"}

    def test_a_denied_checks_api_does_not_discard_the_commit_statuses(self):
        """403 on check-runs must not throw away what the token CAN read."""
        toolkit = _toolkit()
        responses = [
            _make_response(403, json_data=self._DENIED, text="denied"),
            _make_response(
                200,
                json_data={"state": "success", "statuses": [{"context": "ci/jenkins", "state": "success"}]},
            ),
        ]
        with patch("parrot_tools.gittoolkit.requests.request", side_effect=responses):
            result = asyncio.run(toolkit.get_pr_checks(pr_number=548, head_sha="d5fda5e"))

        assert result["available"] is True
        assert result["denied"] == ["check_runs"]
        assert result["success"] == 1
        assert "'Checks' (Read-only)" in result["reason"]
        assert "classic PAT" in result["reason"]

    def test_a_denied_status_api_keeps_the_check_runs(self):
        toolkit = _toolkit()
        responses = [
            _make_response(
                200,
                json_data={"check_runs": [{"name": "pytest", "status": "completed", "conclusion": "success"}]},
            ),
            _make_response(403, json_data=self._DENIED, text="denied"),
        ]
        with patch("parrot_tools.gittoolkit.requests.request", side_effect=responses):
            result = asyncio.run(toolkit.get_pr_checks(pr_number=1, head_sha="s"))

        assert result["available"] is True
        assert result["denied"] == ["commit_statuses"]
        assert result["success"] == 1
        assert "'Commit statuses' (Read-only)" in result["reason"]

    def test_both_denied_reports_unavailable(self):
        """Both refused means "we do not know" — never "green"."""
        toolkit = _toolkit()
        responses = [
            _make_response(403, json_data=self._DENIED, text="denied"),
            _make_response(403, json_data=self._DENIED, text="denied"),
        ]
        with patch("parrot_tools.gittoolkit.requests.request", side_effect=responses):
            result = asyncio.run(toolkit.get_pr_checks(pr_number=1, head_sha="s"))

        assert result["available"] is False
        assert result["denied"] == ["check_runs", "commit_statuses"]
        assert result["total"] == 0

    def test_404_is_tolerated_like_403(self):
        """A fine-grained PAT hides an inaccessible resource behind 404 too."""
        toolkit = _toolkit()
        responses = [
            _make_response(404, json_data={"message": "Not Found"}, text="nf"),
            _make_response(200, json_data={"state": "pending", "statuses": []}),
        ]
        with patch("parrot_tools.gittoolkit.requests.request", side_effect=responses):
            result = asyncio.run(toolkit.get_pr_checks(pr_number=1, head_sha="s"))
        assert result["denied"] == ["check_runs"]
        assert result["available"] is True

    def test_other_http_errors_still_raise(self):
        """A 500 is an outage, not a permission answer — do not swallow it."""
        toolkit = _toolkit()
        with patch(
            "parrot_tools.gittoolkit.requests.request",
            return_value=_make_response(500, json_data={"message": "boom"}, text="boom"),
        ):
            with pytest.raises(GitToolkitError, match="500"):
                asyncio.run(toolkit.get_pr_checks(pr_number=1, head_sha="s"))
