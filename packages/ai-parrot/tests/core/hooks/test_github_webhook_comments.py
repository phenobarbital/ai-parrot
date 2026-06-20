"""GitHubWebhookHook PR-comment / PR-review classification + parsing (FEAT-250 TASK-011)."""
from __future__ import annotations

from parrot.core.hooks.github_webhook import GitHubWebhookHook


# ── classification ─────────────────────────────────────────────────────


def test_issue_comment_on_pr_emits_pr_comment():
    event = GitHubWebhookHook._classify_event(
        "issue_comment",
        {
            "action": "created",
            "issue": {"number": 42, "pull_request": {"url": "..."}},
            "comment": {"body": "please fix"},
        },
    )
    assert event == "pr_comment"


def test_issue_comment_on_plain_issue_ignored():
    assert (
        GitHubWebhookHook._classify_event(
            "issue_comment",
            {"action": "created", "issue": {"number": 7}, "comment": {"body": "x"}},
        )
        is None
    )


def test_issue_comment_non_created_ignored():
    assert (
        GitHubWebhookHook._classify_event(
            "issue_comment",
            {
                "action": "edited",
                "issue": {"number": 42, "pull_request": {}},
                "comment": {"body": "x"},
            },
        )
        is None
    )


def test_pull_request_review_submitted_emits_pr_review():
    assert (
        GitHubWebhookHook._classify_event(
            "pull_request_review", {"action": "submitted"}
        )
        == "pr_review"
    )


def test_pull_request_review_dismissed_ignored():
    assert (
        GitHubWebhookHook._classify_event(
            "pull_request_review", {"action": "dismissed"}
        )
        is None
    )


def test_existing_pull_request_classification_unchanged():
    assert (
        GitHubWebhookHook._classify_event("pull_request", {"action": "opened"})
        == "pr_opened"
    )


# ── payload parsing ────────────────────────────────────────────────────


def test_pr_comment_payload_fields():
    payload = {
        "action": "created",
        "repository": {"full_name": "owner/repo", "name": "repo",
                       "owner": {"login": "owner"}},
        "issue": {"number": 42, "html_url": "https://github.com/owner/repo/pull/42",
                  "title": "Fix sync", "pull_request": {}},
        "comment": {"body": "please handle the null case", "user": {"login": "alice"}},
    }
    out = GitHubWebhookHook._build_event_payload(
        "issue_comment", "pr_comment", payload, "deliv-1"
    )
    assert out["pr_number"] == 42
    assert out["body"] == "please handle the null case"
    assert out["author"] == "alice"
    assert out["repository"] == "owner/repo"
    assert out["review_state"] is None
    # head_sha is not available on issue_comment payloads.
    assert out["head_sha"] is None


def test_pr_review_payload_fields():
    payload = {
        "action": "submitted",
        "repository": {"full_name": "owner/repo", "name": "repo",
                       "owner": {"login": "owner"}},
        "pull_request": {
            "number": 9,
            "html_url": "https://github.com/owner/repo/pull/9",
            "title": "Fix sync",
            "head": {"sha": "deadbeef", "ref": "feat-9-fix"},
            "base": {"ref": "dev"},
        },
        "review": {"body": "needs work", "state": "changes_requested",
                   "user": {"login": "bob"}},
    }
    out = GitHubWebhookHook._build_event_payload(
        "pull_request_review", "pr_review", payload, "deliv-2"
    )
    assert out["pr_number"] == 9
    assert out["head_sha"] == "deadbeef"
    assert out["branch"] == "feat-9-fix"
    assert out["review_state"] == "changes_requested"
    assert out["body"] == "needs work"
    assert out["author"] == "bob"


def test_pull_request_payload_still_parses():
    payload = {
        "action": "opened",
        "repository": {"full_name": "owner/repo", "name": "repo",
                       "owner": {"login": "owner"}},
        "pull_request": {
            "number": 1,
            "title": "T",
            "body": "B",
            "head": {"sha": "abc", "ref": "feat-1"},
            "base": {"ref": "dev"},
            "user": {"login": "carol"},
            "draft": True,
        },
    }
    out = GitHubWebhookHook._build_event_payload(
        "pull_request", "pr_opened", payload, "deliv-3"
    )
    assert out["pr_number"] == 1
    assert out["head_sha"] == "abc"
    assert out["pr_body"] == "B"
    assert out["draft"] is True
    assert out["author"] == "carol"
