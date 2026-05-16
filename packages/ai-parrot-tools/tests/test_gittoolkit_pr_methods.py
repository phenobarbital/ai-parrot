"""Unit tests for the PR-review helpers added to GitToolkit.

Network calls are mocked at ``requests.request`` so the tests stay hermetic.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from parrot_tools.gittoolkit import GitToolkit, GitToolkitError


def _make_response(status_code: int = 200, json_data=None, text: str = ""):
    class _Resp:
        def __init__(self):
            self.status_code = status_code
            self._json = json_data
            self.text = text

        def json(self):
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
