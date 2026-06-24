"""Unit tests for parrot.flows.dev_loop.webhook (TASK-887)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.flows.dev_loop.webhook import (
    _is_dev_loop_branch,
    _list_dev_loop_worktrees,
    _transform_payload,
    cleanup_worktree,
    register_pull_request_webhook,
    sweep_finished_worktrees,
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


_WORKTREE_LIST = (
    b"worktree /repo\nHEAD aaa\nbranch refs/heads/dev\n\n"
    b"worktree /repo/.claude/worktrees/feat-1-merged\nHEAD bbb\n"
    b"branch refs/heads/feat-1-merged\n\n"
    b"worktree /repo/.claude/worktrees/feat-2-open\nHEAD ccc\n"
    b"branch refs/heads/feat-2-open\n\n"
    b"worktree /repo/.claude/worktrees/feat-3-orphan\nHEAD ddd\n"
    b"branch refs/heads/feat-3-orphan\n\n"
)


def _patch_worktree_list(stdout: bytes = _WORKTREE_LIST, returncode: int = 0):
    """Patch create_subprocess_exec so `git worktree list` yields *stdout*."""
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.returncode = returncode
    return patch(
        "parrot.flows.dev_loop.webhook.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    )


class TestListDevLoopWorktrees:
    @pytest.mark.asyncio
    async def test_parses_only_dev_loop_branches(self):
        with _patch_worktree_list():
            entries = await _list_dev_loop_worktrees()
        # `dev` (primary) is excluded; the three feat-* worktrees are kept.
        assert [b for _p, b in entries] == [
            "feat-1-merged", "feat-2-open", "feat-3-orphan",
        ]

    @pytest.mark.asyncio
    async def test_returns_empty_on_git_failure(self):
        with _patch_worktree_list(stdout=b"", returncode=1):
            assert await _list_dev_loop_worktrees() == []


class TestSweepFinishedWorktrees:
    @staticmethod
    def _states(mapping):
        async def _fn(branch):
            return mapping.get(branch)
        return _fn

    @pytest.mark.asyncio
    async def test_removes_only_merged_and_closed(self):
        states = self._states({
            "feat-1-merged": "merged",
            "feat-2-open": "open",
            "feat-3-orphan": None,
        })
        with _patch_worktree_list(), patch(
            "parrot.flows.dev_loop.webhook.cleanup_worktree", new=AsyncMock()
        ) as mock_clean:
            report = await sweep_finished_worktrees(pr_state_fn=states)

        mock_clean.assert_awaited_once_with("feat-1-merged")
        assert [r["branch"] for r in report["removed"]] == ["feat-1-merged"]
        kept = {k["branch"]: k["reason"] for k in report["kept"]}
        assert kept == {"feat-2-open": "pr_open", "feat-3-orphan": "no_pr"}

    @pytest.mark.asyncio
    async def test_remove_orphans_also_clears_no_pr(self):
        states = self._states({
            "feat-1-merged": "closed",
            "feat-2-open": "open",
            "feat-3-orphan": None,
        })
        with _patch_worktree_list(), patch(
            "parrot.flows.dev_loop.webhook.cleanup_worktree", new=AsyncMock()
        ) as mock_clean:
            report = await sweep_finished_worktrees(
                pr_state_fn=states, remove_orphans=True
            )

        removed = {r["branch"]: r["reason"] for r in report["removed"]}
        assert removed == {
            "feat-1-merged": "pr_closed", "feat-3-orphan": "orphan_no_pr",
        }
        assert mock_clean.await_count == 2

    @pytest.mark.asyncio
    async def test_dry_run_removes_nothing(self):
        states = self._states({"feat-1-merged": "merged"})
        with _patch_worktree_list(
            stdout=(
                b"worktree /repo/.claude/worktrees/feat-1-merged\nHEAD b\n"
                b"branch refs/heads/feat-1-merged\n\n"
            )
        ), patch(
            "parrot.flows.dev_loop.webhook.cleanup_worktree", new=AsyncMock()
        ) as mock_clean:
            report = await sweep_finished_worktrees(
                pr_state_fn=states, dry_run=True
            )

        mock_clean.assert_not_awaited()
        assert report["removed"] == [
            {"branch": "feat-1-merged", "reason": "pr_merged", "dry_run": True}
        ]

    @pytest.mark.asyncio
    async def test_per_branch_error_is_isolated(self):
        async def _boom(branch):
            if branch == "feat-2-open":
                raise RuntimeError("gh exploded")
            return "merged"

        with _patch_worktree_list(), patch(
            "parrot.flows.dev_loop.webhook.cleanup_worktree", new=AsyncMock()
        ) as mock_clean:
            report = await sweep_finished_worktrees(pr_state_fn=_boom)

        # The exploding branch is reported; the others still get processed.
        assert [e["branch"] for e in report["errors"]] == ["feat-2-open"]
        assert {r["branch"] for r in report["removed"]} == {
            "feat-1-merged", "feat-3-orphan",
        }
        assert mock_clean.await_count == 2
