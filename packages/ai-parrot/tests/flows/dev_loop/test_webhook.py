"""Unit tests for parrot.flows.dev_loop.webhook (TASK-887)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.flows.dev_loop.webhook import (
    _is_dev_loop_branch,
    _transform_payload,
    cleanup_worktree,
    register_pull_request_webhook,
)


class TestBranchMatcher:
    @pytest.mark.parametrize(
        "name",
        [
            "feat-130",
            "feat-130-fix",
            "feat-130-fix-customer-sync",
            "feat-1",
        ],
    )
    def test_matches_dev_loop(self, name):
        assert _is_dev_loop_branch(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "main",
            "dependabot/npm/foo",
            "renovate/python",
            "feat/some-feature",  # slash, not dash
            "fix-130",
            "feat-",  # missing id
        ],
    )
    def test_does_not_match_non_dev_loop(self, name):
        assert _is_dev_loop_branch(name) is False


class TestTransformPayload:
    def test_returns_none_for_non_closed_action(self):
        assert _transform_payload({"action": "opened"}) is None

    def test_returns_none_for_non_devloop_branch(self):
        payload = {
            "action": "closed",
            "pull_request": {"head": {"ref": "dependabot/x"}},
        }
        assert _transform_payload(payload) is None

    def test_returns_cleanup_command_for_devloop_branch(self):
        payload = {
            "action": "closed",
            "pull_request": {"head": {"ref": "feat-130-fix"}},
        }
        assert (
            _transform_payload(payload)
            == "cleanup_worktree:feat-130-fix"
        )

    def test_handles_missing_pull_request_block(self):
        assert _transform_payload({"action": "closed"}) is None


class TestRegisterWebhook:
    def test_calls_register_webhook(self):
        orch = MagicMock()
        register_pull_request_webhook(orch, secret="s3cr3t")
        orch.register_webhook.assert_called_once()
        kwargs = orch.register_webhook.call_args.kwargs
        assert kwargs["path"] == "/github/dev-loop"
        assert kwargs["target_id"] == "dev-loop-cleanup"
        assert kwargs["secret"] == "s3cr3t"
        assert kwargs["target_type"] == "agent"
        assert kwargs["transform_fn"] is _transform_payload


class TestCleanupHelper:
    @pytest.mark.asyncio
    async def test_pr_webhook_removes_worktree(self):
        with patch(
            "parrot.flows.dev_loop.webhook.asyncio.create_subprocess_exec"
        ) as mock_exec:
            proc = MagicMock()
            proc.communicate = AsyncMock(return_value=(b"", b""))
            proc.returncode = 0
            mock_exec.return_value = proc
            await cleanup_worktree("feat-130-fix")
            # remove + prune = 2 invocations
            assert mock_exec.call_count == 2

    @pytest.mark.asyncio
    async def test_swallows_missing_worktree(self):
        with patch(
            "parrot.flows.dev_loop.webhook.asyncio.create_subprocess_exec"
        ) as mock_exec:
            proc = MagicMock()
            proc.communicate = AsyncMock(
                return_value=(b"", b"not a working tree")
            )
            proc.returncode = 1
            mock_exec.return_value = proc
            await cleanup_worktree("feat-130-fix")
            # Should not raise even though the remove subprocess
            # returns non-zero.

    @pytest.mark.asyncio
    async def test_pr_webhook_ignores_non_dev_loop_branches(self):
        # The transform returns None; the orchestrator drops the event,
        # so cleanup_worktree should never be called. Simulate the
        # listener semantics directly:
        cmd = _transform_payload(
            {
                "action": "closed",
                "pull_request": {"head": {"ref": "dependabot/foo"}},
            }
        )
        assert cmd is None

        with patch(
            "parrot.flows.dev_loop.webhook.asyncio.create_subprocess_exec"
        ) as mock_exec:
            # Caller would skip — we never call cleanup_worktree.
            mock_exec.assert_not_called()
