"""Unit tests for GitHubWebhookHook classification and signature verification."""
from __future__ import annotations

import hashlib
import hmac
from unittest.mock import MagicMock

from parrot.core.hooks.github_webhook import GitHubWebhookHook
from navigator_eventbus.hooks.models import GitHubWebhookConfig


def _build_hook(secret: str | None = None) -> GitHubWebhookHook:
    return GitHubWebhookHook(
        GitHubWebhookConfig(
            url="/api/v1/hooks/github",
            secret_token=secret,
            target_id="agent",
        )
    )


class TestClassifyEvent:
    def test_pull_request_opened_returns_pr_opened(self):
        event = GitHubWebhookHook._classify_event(
            "pull_request", {"action": "opened"}
        )
        assert event == "pr_opened"

    def test_pull_request_reopened_returns_pr_reopened(self):
        event = GitHubWebhookHook._classify_event(
            "pull_request", {"action": "reopened"}
        )
        assert event == "pr_reopened"

    def test_pull_request_synchronize_returns_pr_synchronize(self):
        event = GitHubWebhookHook._classify_event(
            "pull_request", {"action": "synchronize"}
        )
        assert event == "pr_synchronize"

    def test_pull_request_closed_is_ignored(self):
        assert (
            GitHubWebhookHook._classify_event(
                "pull_request", {"action": "closed"}
            )
            is None
        )

    def test_non_pull_request_event_is_ignored(self):
        assert (
            GitHubWebhookHook._classify_event(
                "push", {"action": "opened"}
            )
            is None
        )

    def test_missing_action_is_ignored(self):
        assert (
            GitHubWebhookHook._classify_event("pull_request", {}) is None
        )


class TestVerifySignature:
    def test_valid_signature_passes(self):
        hook = _build_hook(secret="topsecret")
        body = b'{"action":"opened"}'
        computed = "sha256=" + hmac.new(
            b"topsecret", body, hashlib.sha256
        ).hexdigest()
        request = MagicMock()
        request.headers = {"X-Hub-Signature-256": computed}
        assert hook._verify_signature(request, body) is True

    def test_invalid_signature_fails(self):
        hook = _build_hook(secret="topsecret")
        body = b'{"action":"opened"}'
        request = MagicMock()
        request.headers = {"X-Hub-Signature-256": "sha256=deadbeef"}
        assert hook._verify_signature(request, body) is False

    def test_missing_signature_fails(self):
        hook = _build_hook(secret="topsecret")
        request = MagicMock()
        request.headers = {}
        assert hook._verify_signature(request, b"{}") is False
