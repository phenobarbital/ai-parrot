"""Unit tests for SubWorktreeManager (FEAT-323 TASK-1861), on a real temp git repo."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from parrot.flows.dev_loop.worktree_manager import (
    SubWorktreeManager,
    SubWorktreeMergeError,
)


async def _run_git(*args: str, cwd: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    assert proc.returncode == 0, (
        f"git {' '.join(args)} failed in {cwd}: {err.decode()}\n{out.decode()}"
    )


async def _write_and_commit(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content)
    await _run_git("add", filename, cwd=repo)
    await _run_git("commit", "-m", message, cwd=repo)


@pytest.fixture
async def git_sandbox(tmp_path):
    """Bare-ish temp repo: init, initial commit, feature branch checked out.

    Returns (base_worktree, feature_branch, worktree_base_path).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    await _run_git("init", "-b", "main", cwd=repo)
    await _run_git("config", "user.email", "test@example.com", cwd=repo)
    await _run_git("config", "user.name", "Test", cwd=repo)
    await _write_and_commit(repo, "README.md", "hello\n", "initial commit")

    feature_branch = "feat-323-x"
    await _run_git("checkout", "-b", feature_branch, cwd=repo)

    return repo, feature_branch, tmp_path


@pytest.mark.asyncio
class TestCreate:
    async def test_paths_under_base(self, git_sandbox):
        base_worktree, feature_branch, worktree_base_path = git_sandbox
        manager = SubWorktreeManager(
            base_worktree=str(base_worktree),
            feature_branch=feature_branch,
            worktree_base_path=str(worktree_base_path),
        )

        path = await manager.create("development.w1")

        assert Path(path).resolve().is_relative_to(Path(str(worktree_base_path)).resolve())
        assert Path(path).exists()

    async def test_base_worktree_outside_base_path_rejected(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        inside = tmp_path / "base" / "inside"
        inside.mkdir(parents=True)
        with pytest.raises(ValueError):
            SubWorktreeManager(
                base_worktree=str(outside),
                feature_branch="feat-x",
                worktree_base_path=str(tmp_path / "base"),
            )


@pytest.mark.asyncio
class TestMerge:
    async def test_clean_merge_two_workers(self, git_sandbox):
        base_worktree, feature_branch, worktree_base_path = git_sandbox
        manager = SubWorktreeManager(
            base_worktree=str(base_worktree),
            feature_branch=feature_branch,
            worktree_base_path=str(worktree_base_path),
        )

        w1_path = await manager.create("development.w1")
        w2_path = await manager.create("development.w2")

        await _write_and_commit(Path(w1_path), "w1.py", "w1\n", "w1 work")
        await _write_and_commit(Path(w2_path), "w2.py", "w2\n", "w2 work")

        report = await manager.merge_sequential(resolver=None)

        assert len(report.merged) == 2
        assert report.conflicts_resolved == []
        assert report.kept_for_inspection == []
        assert (base_worktree / "w1.py").exists()
        assert (base_worktree / "w2.py").exists()

    async def test_refresh_all_fast_forwards_subworktrees(self, git_sandbox):
        """After a wave's merge, ``refresh_all`` brings every sub-worktree up
        to the integrated feature branch (so the next wave is not stale)."""
        base_worktree, feature_branch, worktree_base_path = git_sandbox
        manager = SubWorktreeManager(
            base_worktree=str(base_worktree),
            feature_branch=feature_branch,
            worktree_base_path=str(worktree_base_path),
        )

        w1_path = await manager.create("development.w1")
        w2_path = await manager.create("development.w2")

        # Only w1 does work this wave; w2 produced nothing.
        await _write_and_commit(Path(w1_path), "w1.py", "w1\n", "w1 work")
        await manager.merge_sequential(resolver=None)

        # Before refresh: w2's sub-worktree cannot see w1's merged file.
        assert not (Path(w2_path) / "w1.py").exists()

        await manager.refresh_all()

        # After refresh: every live sub-worktree contains the merged output.
        assert (Path(w1_path) / "w1.py").exists()
        assert (Path(w2_path) / "w1.py").exists()

    async def test_conflict_calls_resolver(self, git_sandbox):
        base_worktree, feature_branch, worktree_base_path = git_sandbox
        manager = SubWorktreeManager(
            base_worktree=str(base_worktree),
            feature_branch=feature_branch,
            worktree_base_path=str(worktree_base_path),
        )

        w1_path = await manager.create("development.w1")
        # Conflicting edits to the SAME file on both branches.
        await _write_and_commit(base_worktree, "README.md", "base change\n", "base edits readme")
        await _write_and_commit(Path(w1_path), "README.md", "worker change\n", "worker edits readme")

        calls = []

        async def resolver(path: str, description: str) -> bool:
            calls.append((path, description))
            # Simulate the resolver fixing the conflict in-place and committing.
            (base_worktree / "README.md").write_text("resolved\n")
            await _run_git("add", "README.md", cwd=base_worktree)
            await _run_git("commit", "-m", "resolve conflict", cwd=base_worktree)
            return True

        report = await manager.merge_sequential(resolver=resolver)

        assert len(calls) == 1
        # Regression (FEAT-323 TASK-1864 found this): the resolver must
        # receive `base_worktree` — where `git merge` actually ran and the
        # conflict markers/`git status` live — NOT the failed worker's own
        # sub-worktree (`w1_path`), which never has any conflict state.
        assert calls[0][0] == str(base_worktree.resolve())
        assert calls[0][0] != w1_path
        assert report.conflicts_resolved == [f"{feature_branch}--development-w1"]
        assert report.kept_for_inspection == []

    async def test_resolver_failure_raises_and_keeps(self, git_sandbox):
        base_worktree, feature_branch, worktree_base_path = git_sandbox
        manager = SubWorktreeManager(
            base_worktree=str(base_worktree),
            feature_branch=feature_branch,
            worktree_base_path=str(worktree_base_path),
        )

        w1_path = await manager.create("development.w1")
        await _write_and_commit(base_worktree, "README.md", "base change\n", "base edits readme")
        await _write_and_commit(Path(w1_path), "README.md", "worker change\n", "worker edits readme")

        async def failing_resolver(path: str, description: str) -> bool:
            return False

        with pytest.raises(SubWorktreeMergeError) as excinfo:
            await manager.merge_sequential(resolver=failing_resolver)

        assert excinfo.value.branch == f"{feature_branch}--development-w1"
        assert Path(w1_path).exists()  # sub-worktree preserved for inspection

    async def test_no_resolver_raises_and_keeps(self, git_sandbox):
        base_worktree, feature_branch, worktree_base_path = git_sandbox
        manager = SubWorktreeManager(
            base_worktree=str(base_worktree),
            feature_branch=feature_branch,
            worktree_base_path=str(worktree_base_path),
        )

        w1_path = await manager.create("development.w1")
        await _write_and_commit(base_worktree, "README.md", "base change\n", "base edits readme")
        await _write_and_commit(Path(w1_path), "README.md", "worker change\n", "worker edits readme")

        with pytest.raises(SubWorktreeMergeError):
            await manager.merge_sequential(resolver=None)

        assert Path(w1_path).exists()


@pytest.mark.asyncio
class TestCleanup:
    async def test_removes_merged_keeps_conflicted(self, git_sandbox):
        base_worktree, feature_branch, worktree_base_path = git_sandbox
        manager = SubWorktreeManager(
            base_worktree=str(base_worktree),
            feature_branch=feature_branch,
            worktree_base_path=str(worktree_base_path),
        )

        clean_path = await manager.create("development.w1")
        conflict_path = await manager.create("development.w2")

        await _write_and_commit(Path(clean_path), "clean.py", "clean\n", "clean work")
        await _write_and_commit(base_worktree, "README.md", "base change\n", "base edits readme")
        await _write_and_commit(
            Path(conflict_path), "README.md", "worker change\n", "worker edits readme"
        )

        with pytest.raises(SubWorktreeMergeError):
            await manager.merge_sequential(resolver=None)

        await manager.cleanup(keep_on_conflict=True)

        assert not Path(clean_path).exists()
        assert Path(conflict_path).exists()


@pytest.mark.asyncio
async def test_merge_sequential_aborts_an_interrupted_merge(tmp_path, monkeypatch) -> None:
    """Host cancellation mid-`git merge` must leave the feature worktree clean (no MERGE_HEAD)."""
    import asyncio

    from parrot.flows.dev_loop.worktree_manager import SubWorktreeManager

    base = tmp_path / "base"
    base.mkdir()
    manager = SubWorktreeManager(base_worktree=str(base), feature_branch="feat", worktree_base_path=str(tmp_path))
    manager._created["w1"] = (str(tmp_path / "w1"), "feat--w1")
    calls: list[tuple[str, ...]] = []

    async def fake_git(*args: str, cwd: str):
        calls.append(args)
        if args[0] == "rev-list":
            return 0, "1\n", ""
        if args[:2] == ("merge", "--abort"):
            return 0, "", ""
        if args[0] == "merge":
            await asyncio.sleep(30)  # the child hangs until the host cancels us
        return 0, "", ""

    monkeypatch.setattr(manager, "_git", fake_git)
    task = asyncio.create_task(manager.merge_sequential(resolver=None))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ("merge", "--abort") in calls
    assert calls.index(("merge", "--abort")) > calls.index(("merge", "--no-ff", "feat--w1", "-m", "merge feat--w1"))
